"""
意图路由器
----------
将意图名称映射到对应的模板函数，返回 TaskTemplate。
"""

from __future__ import annotations

from cua_lark.planning.template_library import (
    TaskTemplate,
    add_todo_steps,
    create_event_steps,
    send_message_steps,
)

# 意图名 → 步骤生成函数
INTENT_REGISTRY: dict[str, callable] = {
    "send_message": send_message_steps,
    "create_event": create_event_steps,
    "add_todo":     add_todo_steps,
}

# 意图中文名（用于打印）
INTENT_DISPLAY: dict[str, str] = {
    "send_message": "发送消息",
    "create_event": "创建日程",
    "add_todo":     "创建待办文档",
}


def route(intent: str, slots: dict) -> TaskTemplate:
    """
    根据意图名和槽位生成 TaskTemplate（步骤 + 验证函数）。

    Raises:
        KeyError: 意图名未注册
    """
    if intent not in INTENT_REGISTRY:
        raise KeyError(f"未知意图：{intent!r}，支持的意图：{list(INTENT_REGISTRY)}")
    return INTENT_REGISTRY[intent](slots)
