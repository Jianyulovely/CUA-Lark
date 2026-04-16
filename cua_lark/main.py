"""
CUA-Lark 启动入口
-----------------
运行方式：
    python -m cua_lark.main
    或
    python cua_lark/main.py

运行前请确保：
  1. 飞书桌面端已打开，停在主界面
  2. .env 中 ARK_API_KEY / PLANNER_EP / VISION_EP 均已配置
"""

from __future__ import annotations

import sys
from pathlib import Path

# 直接运行时（python cua_lark/main.py）确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cua_lark.dialogue.dialogue_manager import DialogueManager
from cua_lark.dialogue.intent_router import INTENT_DISPLAY, route
from cua_lark.execution.agent_loop import AgentLoop

_BANNER = """
╔══════════════════════════════════════════╗
║         飞书助手 CUA-Lark                ║
║   输入任务描述，或输入 quit 退出          ║
╚══════════════════════════════════════════╝
支持的操作：
  · 发送消息   ：给 <联系人> 发 <内容>
  · 创建日程   ：<时间> 创建 <标题> 的日程
  · 创建待办文档：创建一个 <标题> 的待办文档，内容是 <事项1>、<事项2>...
"""


def main() -> None:
    print(_BANNER)

    print("正在连接飞书窗口...", end=" ", flush=True)
    loop = AgentLoop()
    loop.connect()
    print("连接成功！\n")

    mgr = DialogueManager()

    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "退出", "q"):
            print("再见！")
            sys.exit(0)

        # 帮助查询：不走 LLM，直接回复
        _HELP_KEYWORDS = ("功能", "帮助", "help", "你能做什么", "怎么用", "支持什么")
        if any(kw in user_input for kw in _HELP_KEYWORDS):
            print("助手：我目前支持以下操作：")
            print("  · 发送消息   ：'给张三发消息说明天开会取消了'")
            print("  · 创建日程   ：'明天下午3点开个需求评审的会'")
            print("  · 创建待办文档：'创建一个今日任务的待办文档，内容是健身、写代码、做饭'")
            continue

        # ── 对话处理循环（单任务内） ──────────────────────────────────────────
        try:
            result = mgr.process(user_input)
        except RuntimeError as e:
            print(f"[错误] {e}")
            mgr.reset()
            continue

        if result is None:
            # 追问或未识别意图，等待下一轮输入
            continue

        intent, slots = result
        display = INTENT_DISPLAY.get(intent, intent)
        print(f"\n[执行] {display}")
        for k, v in slots.items():
            print(f"  {k}: {v}")
        print()

        # ── 执行 + 验证 ───────────────────────────────────────────────────────
        try:
            template = route(intent, slots)
            loop.run_with_verify(template)
            print(f"\n执行完毕！\n")
        except (RuntimeError, KeyError) as e:
            print(f"\n[执行失败] {e}\n")
        finally:
            mgr.reset()


if __name__ == "__main__":
    main()
