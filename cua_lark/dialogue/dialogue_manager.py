"""
对话管理器（Stage 6）
----------------------
从用户自然语言输入中提取意图和槽位，不足时最多追问 2 轮。

调用方式：
    mgr = DialogueManager()
    result = mgr.process("帮我给张三发消息说明天开会取消了")
    if result:
        intent, slots = result   # 槽位完整，可以执行
    else:
        pass  # 已打印追问语句，等待用户下一次输入
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from openai import OpenAI

from cua_lark.config import config
from cua_lark.core.logger import get_logger

_log = get_logger("对话")


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class DialogueState:
    intent: str = ""
    filled_slots: dict = field(default_factory=dict)
    missing_slots: list = field(default_factory=list)
    turn_count: int = 0


# 意图 → 必填槽位
INTENT_REQUIRED_SLOTS: dict[str, list[str]] = {
    "send_message":  ["recipient", "content"],
    "create_event":  ["title", "start_time"],
    "add_todo":      ["title", "items"],
}

# 槽位中文说明（用于兜底追问）
SLOT_DESCRIPTIONS: dict[str, str] = {
    "recipient":  "收件人姓名",
    "content":    "消息内容",
    "title":      "标题（日程或文档）",
    "start_time": "开始时间（格式 HH:MM，如 14:30）",
    "end_time":   "结束时间（格式 HH:MM，如 15:30）",
    "items":      "待办事项（多条用顿号或逗号分隔，如：买菜、做饭、洗碗）",
}

_SYSTEM_PROMPT = """\
你是飞书桌面助手的意图识别模块。

支持的意图及其槽位：
- send_message（发送飞书消息）
  必填：recipient（联系人姓名）, content（消息内容）

- create_event（创建日历日程）
  必填：title（日程标题）, start_time（开始时间，HH:MM，如 14:30）
  选填：end_time（结束时间，HH:MM，不填则自动设为 start_time + 1 小时）

- add_todo（在云文档中创建待办事项列表）
  必填：title（文档标题）, items（待办事项，多条用顿号或逗号分隔，如：买菜、做饭、洗碗）

时间解析规则：
- "下午三点" → "15:00"，"下午两点半" → "14:30"，"上午十点" → "10:00"
- "三点" 通常指下午，即 "15:00"

输出规则：
1. 只输出 JSON，不输出任何其他文字
2. 如果无法识别已知意图，intent 填 "unknown"
3. question 字段：missing 非空时填写自然的中文追问语句，否则填空字符串

输出格式（严格 JSON）：
{
  "intent": "send_message" | "create_event" | "add_todo" | "unknown",
  "slots": {"slot_name": "slot_value"},
  "missing": ["missing_required_slot_name"],
  "question": "追问语句或空字符串"
}
"""


# ── 主类 ───────────────────────────────────────────────────────────────────────

class DialogueManager:
    """
    多轮对话管理器。

    每次调用 process(user_input)：
      - 返回 (intent, slots)：槽位完整，可以交给规划层执行
      - 返回 None：需要继续追问（已打印追问语句，等待下次输入）
      - 抛出 RuntimeError：追问次数超限，放弃本次任务
    """

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=config.planner_api_key,
            base_url=config.ark_base_url,
        )
        self._state = DialogueState()
        self._history: list[dict] = []

    def reset(self) -> None:
        """开始新任务前重置状态"""
        self._state = DialogueState()
        self._history.clear()

    def process(self, user_input: str) -> tuple[str, dict] | None:
        """
        处理一轮用户输入。

        Returns:
            (intent, slots) — 槽位完整
            None            — 已追问，等待用户补充
        Raises:
            RuntimeError    — 追问超限，需要重新描述
        """
        self._history.append({"role": "user", "content": user_input})

        _log.info("调用规划模型进行意图识别...")
        raw = self._call_llm()
        parsed = self._parse_response(raw)

        intent = parsed.get("intent", "unknown")
        new_slots = {k: v for k, v in parsed.get("slots", {}).items() if v}
        missing = parsed.get("missing", [])
        _log.info(f"意图={intent}  槽位={new_slots}  缺失={missing}")

        # 无法识别意图
        if intent == "unknown":
            self.reset()
            _log.info("未识别到已知意图，已提示用户")
            print("助手：抱歉，我没有理解你的意图。目前支持：发送消息、创建日程、创建待办文档。请重新描述。")
            return None

        # 更新状态
        self._state.intent = intent
        self._state.filled_slots.update(new_slots)

        # 重新计算缺失槽位（过滤掉已填充的）
        required = INTENT_REQUIRED_SLOTS.get(intent, [])
        self._state.missing_slots = [s for s in required if s not in self._state.filled_slots]

        # 槽位完整 → 返回结果
        if not self._state.missing_slots:
            _log.info(f"槽位完整，准备执行  {self._state.filled_slots}")
            return self._state.intent, dict(self._state.filled_slots)

        # 追问次数超限 → 放弃
        if self._state.turn_count >= config.max_clarification_turns:
            self.reset()
            raise RuntimeError(
                f"已追问 {config.max_clarification_turns} 轮仍缺少：{self._state.missing_slots}。"
                "请重新描述你的任务。"
            )

        # 追问
        question = parsed.get("question", "") or self._build_question()
        self._history.append({"role": "assistant", "content": question})
        self._state.turn_count += 1
        _log.info(f"追问（第{self._state.turn_count}轮）：{question}")
        print(f"助手：{question}")
        return None

    # ── 内部方法 ───────────────────────────────────────────────────────────────

    def _call_llm(self) -> str:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + self._history
        resp = self._client.chat.completions.create(
            model=config.planner_ep,
            messages=messages,
            temperature=0,
            max_tokens=300,
        )
        content = resp.choices[0].message.content.strip()
        self._history.append({"role": "assistant", "content": content})
        return content

    def _parse_response(self, raw: str) -> dict:
        """从 LLM 输出中提取 JSON，容忍模型在 JSON 前后加文字"""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"intent": "unknown", "slots": {}, "missing": [], "question": ""}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"intent": "unknown", "slots": {}, "missing": [], "question": ""}

    def _build_question(self) -> str:
        """兜底追问语句（LLM 没提供 question 时使用）"""
        descs = [SLOT_DESCRIPTIONS.get(s, s) for s in self._state.missing_slots]
        return "请补充以下信息：" + "、".join(descs)
