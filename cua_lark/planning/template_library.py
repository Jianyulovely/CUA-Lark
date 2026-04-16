"""
模板库
------
预定义飞书操作场景的步骤序列。每个模板函数接收槽位 dict，返回 TemplateStep 列表。

设计原则：
  - tree 步骤携带 UITreeSelector 或 find_fn，执行时由 AgentLoop 实时查询坐标
  - keyboard 步骤携带具体的 text / key_combo，直接执行
  - vision 步骤只携带自然语言描述，由 AgentLoop 截图后交给视觉模型决策
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from cua_lark.perception.tree_parser import TreeParser, UIElement, UITreeSelector


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class TemplateStep:
    """模板中的单个执行步骤"""
    step_id: str
    routing: Literal["tree", "keyboard", "vision"]
    description: str

    # tree 步骤：二选一
    selector: UITreeSelector | None = None          # 标准选择器
    find_fn: Any | None = None                      # 自定义查找函数 (TreeParser) -> UIElement | None

    # keyboard 步骤
    action_type: Literal["click", "type", "key"] = "click"
    text: str | None = None         # action_type=type 时使用
    key_combo: str | None = None    # action_type=key  时使用

    # 执行后等待时间（毫秒），给 UI 留出渲染时间
    wait_ms: int = 500

    # 执行此步骤后切换到新顶层窗口（用于弹窗场景）
    switch_to_window: str | None = None


# ── 模板一：搜索联系人并发送文字消息 ─────────────────────────────────────────

def send_message_steps(slots: dict) -> list[TemplateStep]:
    """
    必填槽位：
      recipient  联系人姓名
      content    消息正文
    """
    recipient = slots["recipient"]
    content = slots["content"]

    return [
        TemplateStep(
            step_id="s1",
            routing="keyboard",
            description="Ctrl+K 打开搜索框（光标自动聚焦，无需再点击输入框）",
            action_type="key",
            key_combo="ctrl+k",
            wait_ms=1000,
        ),
        # s2 已删除：搜索输入框在 Chromium 渲染区内不可见；Ctrl+K 后光标自动聚焦
        TemplateStep(
            step_id="s3",
            routing="keyboard",
            description=f"输入联系人名称：{recipient}",
            action_type="type",
            text=recipient,
            wait_ms=800,
        ),
        TemplateStep(
            step_id="s4",
            routing="tree",
            description="点击'联系人'筛选按钮",
            selector=UITreeSelector("Button", name="联系人"),
            wait_ms=800,
        ),
        TemplateStep(
            step_id="s5",
            routing="vision",
            description=f"点击搜索结果列表中的联系人：{recipient}",
            wait_ms=1200,
        ),
        TemplateStep(
            step_id="s6",
            routing="tree",
            description="点击消息输入框",
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


# ── 模板二：创建日程 ──────────────────────────────────────────────────────────

def create_event_steps(slots: dict) -> list[TemplateStep]:
    """
    必填槽位：
      title       日程标题
      start_time  开始时间，格式 "HH:MM"
    选填槽位：
      end_time    结束时间，格式 "HH:MM"（默认 start_time + 1 小时）
    """
    title      = slots["title"]
    start_time = slots["start_time"]
    end_time   = slots.get("end_time") or _add_one_hour(start_time)

    return [
        # ── 进入日历，打开弹窗 ────────────────────────────────────────────────
        TemplateStep(
            step_id="e1",
            routing="tree",
            description="点击日历导航标签",
            selector=UITreeSelector("TabItem", name="日历"),
            wait_ms=1500,
        ),
        TemplateStep(
            step_id="e2",
            routing="tree",
            description="点击'创建日程'按钮，等待弹窗",
            selector=UITreeSelector("Button", name="创建日程"),
            switch_to_window="创建日程",   # 点击后切换到弹窗
            wait_ms=1500,
        ),
        # ── 标题：唯一需要视觉的步骤（空输入框，UI 树不可见）────────────────
        TemplateStep(
            step_id="e3",
            routing="vision",
            description="点击弹窗顶部的日程标题输入框（'创建日程'标题文字下方的空白区域）",
            wait_ms=300,
        ),
        TemplateStep(
            step_id="e3b",
            routing="keyboard",
            description=f"输入日程标题：{title}",
            action_type="type",
            text=title,
            wait_ms=300,
        ),
        # ── 开始时间：点击 → Ctrl+A → 输入 → Tab 确认 ────────────────────────
        TemplateStep(
            step_id="e4",
            routing="tree",
            description="点击开始时间框",
            find_fn=lambda p: _find_nth_time_text(p, 0),
            wait_ms=300,
        ),
        TemplateStep(
            step_id="e4b",
            routing="keyboard",
            description="Ctrl+A 全选",
            action_type="key",
            key_combo="ctrl+a",
            wait_ms=100,
        ),
        TemplateStep(
            step_id="e4c",
            routing="keyboard",
            description=f"输入开始时间：{start_time}",
            action_type="type",
            text=start_time,
            wait_ms=100,
        ),
        TemplateStep(
            step_id="e4d",
            routing="keyboard",
            description="Tab 确认开始时间",
            action_type="key",
            key_combo="tab",
            wait_ms=400,
        ),
        # ── 结束时间：同上 ────────────────────────────────────────────────────
        TemplateStep(
            step_id="e5",
            routing="tree",
            description="点击结束时间框",
            find_fn=lambda p: _find_nth_time_text(p, 1),
            wait_ms=300,
        ),
        TemplateStep(
            step_id="e5b",
            routing="keyboard",
            description="Ctrl+A 全选",
            action_type="key",
            key_combo="ctrl+a",
            wait_ms=100,
        ),
        TemplateStep(
            step_id="e5c",
            routing="keyboard",
            description=f"输入结束时间：{end_time}",
            action_type="type",
            text=end_time,
            wait_ms=100,
        ),
        TemplateStep(
            step_id="e5d",
            routing="keyboard",
            description="Tab 确认结束时间",
            action_type="key",
            key_combo="tab",
            wait_ms=400,
        ),
        # ── 保存 ──────────────────────────────────────────────────────────────
        TemplateStep(
            step_id="e6",
            routing="tree",
            description="点击'保存'按钮",
            selector=UITreeSelector("Button", name="保存"),
            wait_ms=800,
        ),
    ]


# ── 私有辅助函数 ──────────────────────────────────────────────────────────────

def _find_nth_time_text(parser: TreeParser, n: int) -> UIElement | None:
    """
    在当前窗口中找第 n 个时间 Text（HH:MM 格式）。
    过滤掉日历视图右侧的时间刻度（x > 900），按 x 坐标升序排列：
      n=0 → 开始时间（x 较小）
      n=1 → 结束时间（x 较大）
    """
    elems = [
        e for e in parser.get_all()
        if e.control_type == "Text"
        and _re.fullmatch(r"\d{1,2}:\d{2}", e.name.strip())
        and e.center_x < 900
    ]
    elems.sort(key=lambda e: e.center_x)
    return elems[n] if n < len(elems) else None


def _add_one_hour(time_str: str) -> str:
    """将 'HH:MM' 加一小时，处理跨天（23:30 → 00:30）"""
    t = datetime.strptime(time_str, "%H:%M")
    return (t + timedelta(hours=1)).strftime("%H:%M")



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
