"""
模板库
------
预定义飞书操作场景的步骤序列。每个模板函数接收槽位 dict，返回 TaskTemplate。

设计原则：
  - tree 步骤携带 UITreeSelector 或 find_fn，执行时由 AgentLoop 实时查询坐标
  - keyboard 步骤携带具体的 text / key_combo，直接执行
  - vision 步骤只携带自然语言描述，由 AgentLoop 截图后交给视觉模型决策
  - 每个 TaskTemplate 携带 verify_fn，执行完成后由 AgentLoop 调用视觉模型验证结果
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from cua_lark.perception.tree_parser import TreeParser, UIElement, UITreeSelector
from cua_lark.verification.verifier import TaskTemplate, VerifyResult, capture_screenshot_base64

if TYPE_CHECKING:
    from cua_lark.core.api_client import UITARSClient


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


# ── 模板二：创建日程 ──────────────────────────────────────────────────────────

def create_event_steps(slots: dict) -> TaskTemplate:
    """
    必填槽位：
      title       日程标题
      start_time  开始时间，格式 "HH:MM"
    选填槽位：
      date        日期，格式 "YYYY-MM-DD"（不传则默认今天，弹窗里不修改日期）
      end_time    结束时间，格式 "HH:MM"（默认 start_time + 1 小时）
    """
    title      = slots["title"]
    start_time = slots["start_time"]
    end_time   = slots.get("end_time") or _add_one_hour(start_time)

    # ── 解析目标日期，判断是否需要修改弹窗里的日期 ──────────────────────────
    date_str = slots.get("date", "")
    try:
        target_date = _date.fromisoformat(date_str) if date_str else _date.today()
    except ValueError:
        target_date = _date.today()
    need_date_change = (target_date != _date.today())
    month, day = target_date.month, target_date.day

    steps = [
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
            switch_to_window="创建日程",
            wait_ms=1500,
        ),
    ]

    # ── 日期不是今天时，修改弹窗中的开始日期 ────────────────────────────────
    if need_date_change:
        steps += [
            TemplateStep(
                step_id="e_date",
                routing="vision",
                description=(
                    "点击创建日程弹窗中的开始日期字段"
                    "（显示为'X月X日'格式，位于开始时间左侧），打开日期选择器日历"
                ),
                wait_ms=800,
            ),
            TemplateStep(
                step_id="e_date_b",
                routing="vision",
                description=(
                    f"在弹出的日期选择器日历中，"
                    f"点击数字 {day}（即选择 {month} 月 {day} 日）"
                ),
                wait_ms=500,
            ),
        ]

    steps += [
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
            wait_ms=1500,   # 等待弹窗关闭 + 日历刷新
        ),
    ]

    return TaskTemplate(
        intent="create_event",
        steps=steps,
        verify_fn=lambda parser, ui_tars: _verify_create_event(parser, ui_tars, title),
    )


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


# ── 模板三：创建云文档并添加待办事项 ─────────────────────────────────────────

def add_todo_steps(slots: dict) -> TaskTemplate:
    """
    新建一篇飞书云文档，在正文中插入待办事项块并逐条填入内容。

    必填槽位：
      title   文档标题
      items   待办事项，多个条目用中文顿号或英文逗号分隔
              （如 "买菜、洗碗、做饭" 或 "买菜,洗碗,做饭"）
    """
    title = slots["title"]
    items_raw = slots["items"]
    # 支持中文顿号、全角/半角逗号分隔
    items = [s.strip() for s in _re.split(r"[、,，]", items_raw) if s.strip()]

    steps = [
        # ── 进入云文档，新建文档 ──────────────────────────────────────────────
        TemplateStep(
            step_id="d1",
            routing="tree",
            description="点击'云文档'导航标签",
            selector=UITreeSelector("TabItem", name="云文档"),
            wait_ms=1500,
        ),
        TemplateStep(
            step_id="d2",
            routing="tree",
            description="点击'创建'按钮展开下拉菜单",
            selector=UITreeSelector("Button", name="创建"),
            wait_ms=1000,
        ),
        TemplateStep(
            step_id="d3",
            routing="tree",
            description="点击'新建文档'选项",
            selector=UITreeSelector("Button", name="TitleBarMenu-CREATE_DOC"),
            wait_ms=2500,   # 等待编辑器完全加载
        ),
        # ── 填写文档标题 ──────────────────────────────────────────────────────
        TemplateStep(
            step_id="d4",
            routing="vision",
            description="点击页面顶部的文档标题输入区域（'标题'占位文字所在的空白区域）",
            wait_ms=300,
        ),
        TemplateStep(
            step_id="d4b",
            routing="keyboard",
            description=f"输入文档标题：{title}",
            action_type="type",
            text=title,
            wait_ms=300,
        ),
        # ── 进入正文，插入待办事项块 ──────────────────────────────────────────
        TemplateStep(
            step_id="d5",
            routing="keyboard",
            description="Enter 将光标移入正文区域",
            action_type="key",
            key_combo="enter",
            wait_ms=500,
        ),
        TemplateStep(
            step_id="d6",
            routing="keyboard",
            description="按 / 键打开命令菜单（必须用按键触发，不能用粘贴）",
            action_type="key",
            key_combo="/",
            wait_ms=1000,   # 等待命令菜单完全弹出
        ),
        TemplateStep(
            step_id="d7",
            routing="keyboard",
            description="输入'待办'过滤命令菜单",
            action_type="type",
            text="待办",
            wait_ms=600,
        ),
        TemplateStep(
            step_id="d8",
            routing="keyboard",
            description="Enter 选中'待办事项'块",
            action_type="key",
            key_combo="enter",
            wait_ms=500,
        ),
    ]

    # ── 逐条输入待办事项 ───────────────────────────────────────────────────────
    for i, item in enumerate(items):
        steps.append(TemplateStep(
            step_id=f"d9_{i}",
            routing="keyboard",
            description=f"输入待办事项 {i + 1}：{item}",
            action_type="type",
            text=item,
            wait_ms=200,
        ))
        if i < len(items) - 1:
            steps.append(TemplateStep(
                step_id=f"d10_{i}",
                routing="keyboard",
                description="Enter 换行到下一个待办项",
                action_type="key",
                key_combo="enter",
                wait_ms=200,
            ))

    return TaskTemplate(
        intent="add_todo",
        steps=steps,
        verify_fn=lambda parser, ui_tars: _verify_add_todo(parser, ui_tars, title, items),
    )


# ── 验证函数 ──────────────────────────────────────────────────────────────────

def _verify_send_message(
    _parser: TreeParser,
    ui_tars: "UITARSClient",
    content: str,
) -> VerifyResult:
    """截图后问视觉模型：消息内容是否出现在聊天记录里"""
    screenshot = capture_screenshot_base64()
    return ui_tars.verify(
        question=f"在飞书聊天窗口中，消息内容 '{content}' 是否已经出现在聊天记录里（即已成功发送）？",
        screenshot_base64=screenshot,
    )


def _verify_create_event(
    _parser: TreeParser,
    ui_tars: "UITARSClient",
    title: str,
) -> VerifyResult:
    """截图后问视觉模型：日历视图是否出现了该日程"""
    import time
    _parser.connect()          # 确保飞书主窗口置于前台
    time.sleep(2)              # 等待弹窗关闭 + 日历视图刷新
    screenshot = capture_screenshot_base64()
    return ui_tars.verify(
        question=f"在飞书日历视图中，是否已经出现了标题为 '{title}' 的日程？",
        screenshot_base64=screenshot,
    )


def _verify_add_todo(
    _parser: TreeParser,
    ui_tars: "UITARSClient",
    title: str,
    items: list[str],
) -> VerifyResult:
    """
    验证策略：检查文档标题是否出现在左侧文档库列表，
    不依赖编辑器正文渲染（保存中时正文不可见）。
    """
    import time
    _parser.connect()          # 确保飞书主窗口置于前台
    time.sleep(2)              # 等待文档保存状态稳定
    screenshot = capture_screenshot_base64()
    return ui_tars.verify(
        question=(
            f"在飞书云文档界面，左侧或主区域的文档列表（文档库/最近文档）中，"
            f"是否能看到名为 '{title}' 的文档？"
            f"只要该标题出现在列表里即视为创建成功，不需要检查正文内容。"
        ),
        screenshot_base64=screenshot,
    )


# ── 模板一：搜索联系人并发送文字消息 ─────────────────────────────────────────

def send_message_steps(slots: dict) -> TaskTemplate:
    """
    构建 send_message 模板。

    必填槽位：
      recipient  联系人姓名（飞书好友列表中存在的名称）
      content    消息正文
    """
    recipient = slots["recipient"]
    content = slots["content"]

    steps = [
        # ── Chunk A：搜索 + 筛选（纯 tree/keyboard，无需截图）──────────────
        TemplateStep(
            step_id="s1",
            routing="keyboard",
            description="Ctrl+K 打开搜索框（光标自动聚焦，无需再点击输入框）",
            action_type="key",
            key_combo="ctrl+k",
            wait_ms=1000,
        ),
        TemplateStep(
            step_id="s2a",
            routing="keyboard",
            description="Ctrl+A 全选搜索框，清除可能残留的旧内容",
            action_type="key",
            key_combo="ctrl+a",
            wait_ms=100,
        ),
        TemplateStep(
            step_id="s2b",
            routing="keyboard",
            description="Delete 删除选中内容",
            action_type="key",
            key_combo="delete",
            wait_ms=100,
        ),
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
            description="点击'联系人'筛选按钮，过滤搜索结果",
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
            wait_ms=800,
        ),
    ]

    return TaskTemplate(
        intent="send_message",
        steps=steps,
        verify_fn=lambda parser, ui_tars: _verify_send_message(parser, ui_tars, content),
    )
