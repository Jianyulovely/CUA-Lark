"""
CUA 执行器
----------
将逻辑动作（click / type / key / scroll / wait）映射为实际的鼠标键盘操作。

中文输入说明：
  pyautogui.typewrite() 不支持非 ASCII 字符，因此 type_text() 使用
  "写入剪贴板 → Ctrl+V 粘贴"的方案，会短暂覆盖系统剪贴板内容。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import pyautogui
import pyperclip

# 关闭 pyautogui 的移动动画，提升速度
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True   # 鼠标移到左上角可紧急中止


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class AtomicAction:
    """单个原子动作"""
    type: Literal["click", "type", "key", "scroll", "wait"]
    # click
    x: int | None = None
    y: int | None = None
    # type
    text: str | None = None
    # key（如 "ctrl+k"、"enter"、"esc"）
    key_combo: str | None = None
    # scroll
    direction: Literal["up", "down"] | None = None
    amount: int = 3
    # wait
    ms: int = 500


@dataclass
class ActionChunk:
    """一组可连续执行的原子动作（无需中途截图）"""
    routing: Literal["tree_keyboard", "vision"]
    sequence: list[AtomicAction] = field(default_factory=list)
    screenshot_after: bool = True   # 执行后是否需要截图（用于验证或下一步决策）


# ── 执行器 ────────────────────────────────────────────────────────────────────

class CUAExecutor:
    """
    封装所有底层鼠标键盘操作。

    使用示例：
        executor = CUAExecutor()
        executor.click(601, 130)
        executor.type_text("张三")
        executor.send_key("enter")
        executor.send_key("ctrl+k")
    """

    # ── 单步操作 ──────────────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left") -> None:
        """鼠标单击屏幕绝对坐标"""
        pyautogui.click(x, y, button=button)

    def double_click(self, x: int, y: int) -> None:
        """鼠标双击"""
        pyautogui.doubleClick(x, y)

    def type_text(self, text: str) -> None:
        """
        输入文本，支持中文。
        原理：写入剪贴板 → Ctrl+V 粘贴。
        注意：会短暂覆盖系统剪贴板内容。
        """
        if not text:
            return
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")

    def send_key(self, key_combo: str) -> None:
        """
        发送快捷键或单键。
        支持格式：
          "enter"、"esc"、"tab"、"backspace"
          "ctrl+k"、"ctrl+v"、"ctrl+a"
          "shift+enter"
        """
        parts = [p.strip().lower() for p in key_combo.split("+")]
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)

    def scroll(
        self,
        x: int,
        y: int,
        direction: Literal["up", "down"] = "down",
        amount: int = 3,
    ) -> None:
        """在指定坐标滚动鼠标滚轮"""
        clicks = -amount if direction == "down" else amount
        pyautogui.scroll(clicks, x=x, y=y)

    def wait(self, ms: int) -> None:
        """等待指定毫秒"""
        time.sleep(ms / 1000)

    # ── 批量执行 ──────────────────────────────────────────────────────────────

    def execute_chunk(self, chunk: ActionChunk) -> None:
        """按序执行一个 ActionChunk 中的所有原子动作"""
        for action in chunk.sequence:
            self._execute_one(action)

    def execute_action(self, action: AtomicAction) -> None:
        """执行单个原子动作（供 Agent Loop 逐步调用）"""
        self._execute_one(action)

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    def _execute_one(self, action: AtomicAction) -> None:
        match action.type:
            case "click":
                assert action.x is not None and action.y is not None
                self.click(action.x, action.y)
            case "type":
                assert action.text is not None
                self.type_text(action.text)
            case "key":
                assert action.key_combo is not None
                self.send_key(action.key_combo)
            case "scroll":
                assert action.x is not None and action.y is not None
                assert action.direction is not None
                self.scroll(action.x, action.y, action.direction, action.amount)
            case "wait":
                self.wait(action.ms)
            case _:
                raise ValueError(f"未知动作类型: {action.type}")
