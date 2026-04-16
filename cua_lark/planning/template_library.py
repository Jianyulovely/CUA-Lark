"""
模板库
------
预定义飞书操作场景的步骤序列。每个模板函数接收槽位 dict，返回 TemplateStep 列表。

设计原则：
  - tree 步骤携带 UITreeSelector，执行时由 AgentLoop 实时查询坐标
  - keyboard 步骤携带具体的 text / key_combo，直接执行
  - vision 步骤只携带自然语言描述，由 AgentLoop 截图后交给 UI-TARS 决策
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cua_lark.perception.tree_parser import UITreeSelector


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class TemplateStep:
    """模板中的单个执行步骤"""
    step_id: str
    routing: Literal["tree", "keyboard", "vision"]
    description: str

    # tree 步骤：要查找并点击的元素
    selector: UITreeSelector | None = None

    # keyboard 步骤
    action_type: Literal["click", "type", "key"] = "click"
    text: str | None = None         # routing=keyboard, action_type=type 时使用
    key_combo: str | None = None    # routing=keyboard, action_type=key  时使用

    # 执行后等待时间（毫秒），给 UI 留出渲染时间
    wait_ms: int = 500


# ── 模板一：搜索联系人并发送文字消息 ─────────────────────────────────────────

def send_message_steps(slots: dict) -> list[TemplateStep]:
    """
    构建 send_message 模板步骤序列。

    必填槽位：
      recipient  联系人姓名（飞书好友列表中存在的名称）
      content    消息正文
    """
    recipient = slots["recipient"]
    content = slots["content"]

    return [
        # ── Chunk A：搜索 + 筛选（纯 tree/keyboard，无需截图）──────────────
        TemplateStep(
            step_id="s1",
            routing="keyboard",
            description="Ctrl+K 打开搜索框（光标自动聚焦，无需再点击输入框）",
            action_type="key",
            key_combo="ctrl+k",
            wait_ms=1000,   # 等待搜索框动画完成 + 光标就绪
        ),
        # s2 已删除：搜索输入框在 Chromium 渲染区内，UI 树不可见；
        # Ctrl+K 打开搜索后光标自动聚焦输入框，直接输入即可。
        TemplateStep(
            step_id="s3",
            routing="keyboard",
            description=f"输入联系人名称：{recipient}",
            action_type="type",
            text=recipient,
            wait_ms=800,    # 等待搜索结果加载
        ),
        TemplateStep(
            step_id="s4",
            routing="tree",
            description="点击'联系人'筛选按钮，过滤搜索结果",
            selector=UITreeSelector("Button", name="联系人"),
            wait_ms=800,    # 等待列表刷新
        ),
        # ── Step 5：视觉识别（搜索结果是动态列表，UI 树不可见）─────────────
        TemplateStep(
            step_id="s5",
            routing="vision",
            description=f"点击搜索结果列表中的联系人：{recipient}",
            wait_ms=1200,   # 等待聊天窗口打开
        ),
        # ── Chunk B：输入消息 + 发送（纯 tree/keyboard）─────────────────────
        TemplateStep(
            step_id="s6",
            routing="tree",
            description="点击消息输入框（占位文本定位）",
            selector=UITreeSelector("Text", name_contains="发送给"),
            wait_ms=300,
        ),
        TemplateStep(
            step_id="s7",
            routing="keyboard",
            description=f"输入消息内容：{content}",
            action_type="type",
            text=content,
            wait_ms=300,
        ),
        TemplateStep(
            step_id="s8",
            routing="keyboard",
            description="Enter 发送消息",
            action_type="key",
            key_combo="enter",
            wait_ms=500,
        ),
    ]
