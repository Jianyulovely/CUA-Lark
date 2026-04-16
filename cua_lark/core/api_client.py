"""
UI-TARS API 客户端
------------------
基于火山引擎 Ark 平台，使用 OpenAI 兼容接口调用 UI-TARS 模型。

UI-TARS 输入：截图（base64）+ 自然语言指令
UI-TARS 输出：结构化动作字符串，格式如：
    click(start_box='[[x1,y1,x2,y2]]')
    type(content='文字内容')
    key(key='Return')
    scroll(start_box='[[x,y,x,y]]', direction='down', step_count=3)
    finished()

坐标系：UI-TARS 输出的坐标为相对坐标（0~1000 范围），
需要乘以屏幕分辨率换算为绝对像素坐标。
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openai import OpenAI

from cua_lark.config import config

# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class UITARSAction:
    """UI-TARS 返回的解析后动作"""
    action_type: Literal["click", "type", "key", "scroll", "finished", "unknown"]
    # click / scroll
    x: int | None = None
    y: int | None = None
    # type
    content: str | None = None
    # key
    key: str | None = None
    # scroll
    direction: Literal["up", "down", "left", "right"] | None = None
    step_count: int = 3
    # 原始输出（调试用）
    raw: str = ""
    thought: str = ""


# ── 客户端 ────────────────────────────────────────────────────────────────────

class UITARSClient:
    """
    UI-TARS 调用封装。

    使用示例：
        client = UITARSClient()
        action = client.predict(
            screenshot_path="screen.png",
            instruction="点击搜索框",
            screen_width=1920,
            screen_height=1080,
        )
        print(action.action_type, action.x, action.y)
    """

    # 系统提示：兼容 UI-TARS 专用模型和通用视觉模型
    # 关键要求：输出必须严格按格式，不能有多余解释
    SYSTEM_PROMPT = (
        "You are a GUI automation agent. "
        "You will receive a screenshot of a desktop application and a task instruction in Chinese or English.\n\n"
        "Your response MUST follow this exact format (no extra text):\n"
        "Thought: <one sentence reasoning>\n"
        "Action: <action_call>\n\n"
        "Available actions:\n"
        "  click(start_box='[[x1,y1,x2,y2]]')               - click the center of this box\n"
        "  type(content='text to type')                      - type text\n"
        "  key(key='key_name')                               - press key (Return, Escape, ctrl+k)\n"
        "  scroll(start_box='[[x,y,x,y]]', direction='down', step_count=3)\n"
        "  finished()                                        - task already done\n\n"
        "Coordinate rules:\n"
        "- All coordinates are integers in 0-1000 range (relative to screen size)\n"
        "- x=0 is left edge, x=1000 is right edge\n"
        "- y=0 is top edge, y=1000 is bottom edge\n"
        "- For click: set x1=x2 and y1=y2 at the element center, e.g. [[500,300,500,300]]\n\n"
        "Example output:\n"
        "Thought: I can see the search button at the top right\n"
        "Action: click(start_box='[[950,50,950,50]]')\n\n"
        "IMPORTANT: Output ONLY the Thought and Action lines. Nothing else."
    )

    def __init__(self):
        self._client = OpenAI(
            api_key=config.ark_api_key,
            base_url=config.ark_base_url,
        )
        self._model = config.vision_ep

    def predict(
        self,
        instruction: str,
        screenshot_path: str | Path | None = None,
        screenshot_base64: str | None = None,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> UITARSAction:
        """
        给定截图和指令，返回解析后的动作。

        参数：
            instruction:      当前步骤的操作指令（自然语言）
            screenshot_path:  截图文件路径（与 screenshot_base64 二选一）
            screenshot_base64: 截图的 base64 字符串（与 screenshot_path 二选一）
            screen_width:     屏幕实际宽度（px），用于坐标换算
            screen_height:    屏幕实际高度（px），用于坐标换算
        """
        if screenshot_base64 is None:
            if screenshot_path is None:
                raise ValueError("screenshot_path 和 screenshot_base64 至少提供一个")
            screenshot_base64 = _encode_image(screenshot_path)

        image_url = f"data:image/png;base64,{screenshot_base64}"

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": instruction},
                    ],
                },
            ],
        )

        raw_output = response.choices[0].message.content or ""
        return _parse_action(raw_output, screen_width, screen_height)


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _encode_image(path: str | Path) -> str:
    """将图片文件编码为 base64 字符串"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _parse_action(raw: str, screen_w: int, screen_h: int) -> UITARSAction:
    """
    解析 UI-TARS 的输出字符串，提取动作类型和参数。
    坐标从 0-1000 相对坐标换算为屏幕绝对像素坐标。
    """
    thought = ""
    action_str = raw.strip()

    # 提取 Thought
    thought_match = re.search(r"Thought:\s*(.+?)(?:\n|Action:)", raw, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # 提取 Action 行
    action_match = re.search(r"Action:\s*(.+)", raw, re.DOTALL)
    if action_match:
        action_str = action_match.group(1).strip()

    base = UITARSAction(action_type="unknown", raw=raw, thought=thought)

    # ── click ──
    m = re.match(
        r'click\(start_box=["\']?\[\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]["\']?\)',
        action_str,
    )
    if m:
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        base.action_type = "click"
        base.x = _scale(x1, x2, screen_w)
        base.y = _scale(y1, y2, screen_h)
        return base

    # ── type ──
    m = re.match(r"type\(content='(.*)'\)", action_str, re.DOTALL)
    if m:
        base.action_type = "type"
        base.content = m.group(1)
        return base

    # ── key ──
    m = re.match(r"key\(key='(.+?)'\)", action_str)
    if m:
        base.action_type = "key"
        base.key = m.group(1)
        return base

    # ── scroll ──
    m = re.match(
        r'scroll\(start_box=["\']?\[\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]["\']?,\s*'
        r"direction='(\w+)',\s*step_count=(\d+)\)",
        action_str,
    )
    if m:
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        base.action_type = "scroll"
        base.x = _scale(x1, x2, screen_w)
        base.y = _scale(y1, y2, screen_h)
        base.direction = m.group(5)
        base.step_count = int(m.group(6))
        return base

    # ── finished ──
    if action_str.startswith("finished"):
        base.action_type = "finished"
        return base

    base.action_type = "unknown"
    return base


def _scale(v1: int, v2: int, screen_dim: int) -> int:
    """将 0-1000 相对坐标的中点换算为屏幕绝对像素"""
    center = (v1 + v2) / 2
    return int(center / 1000 * screen_dim)
