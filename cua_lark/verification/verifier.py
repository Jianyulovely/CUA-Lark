"""
验证层数据结构与工具
--------------------
VerifyResult  — 验证结果
TaskTemplate  — 执行步骤 + 验证函数的组合体
capture_screenshot_base64 — 截图工具（供验证函数调用）
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Callable

import pyautogui

if TYPE_CHECKING:
    from cua_lark.core.api_client import UITARSClient
    from cua_lark.perception.tree_parser import TreeParser
    from cua_lark.planning.template_library import TemplateStep


@dataclass
class VerifyResult:
    success: bool
    message: str   # 成功/失败的说明


@dataclass
class TaskTemplate:
    """执行步骤 + 验证函数的组合体，由模板函数返回"""
    intent: str
    steps: list[TemplateStep]
    verify_fn: Callable[[TreeParser, UITARSClient], VerifyResult]


def capture_screenshot_base64() -> str:
    """截取全屏并返回 base64 编码的 PNG"""
    screenshot = pyautogui.screenshot()
    buffer = BytesIO()
    screenshot.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
