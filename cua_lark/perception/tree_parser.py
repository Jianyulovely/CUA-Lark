"""
UI 树解析器
-----------
基于 pywinauto (UIA backend) 提取飞书界面的结构化坐标信息。

实测特性（飞书 Electron 应用）：
  - auto_id 基本为空，只能用 control_type + name 匹配
  - 输入框不暴露 Edit 控件，通过占位文本 (Text) 坐标定位
  - 部分弹窗（如"创建日程"）以独立顶层窗口形式出现，需单独连接
  - 含 Group name='scrollable content' 的区域存在折叠内容
  - 坐标为实时屏幕绝对坐标，每次执行前必须重新查询
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import win32con
import win32gui
from pywinauto import Desktop
from pywinauto.application import Application

from cua_lark.core.logger import get_logger

_log = get_logger("感知")


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class UITreeSelector:
    """UI 树元素的查询条件"""
    control_type: str
    name: str | None = None           # 精确匹配（区分大小写）
    name_contains: str | None = None  # 模糊匹配（适用于动态占位文本）


@dataclass
class UIElement:
    """UI 树中的一个元素，携带坐标和原始句柄"""
    control_type: str
    name: str
    auto_id: str
    center_x: int
    center_y: int
    rect: tuple[int, int, int, int]   # (left, top, right, bottom)
    _raw: Any                          # pywinauto 原始元素，供高级操作使用

    @property
    def center(self) -> tuple[int, int]:
        return (self.center_x, self.center_y)


# ── 主类 ──────────────────────────────────────────────────────────────────────

class TreeParser:
    """
    飞书 UI 树解析器。

    使用方式：
        parser = TreeParser()
        parser.connect()                        # 连接主窗口
        elem = parser.find(UITreeSelector("Button", name="创建日程"))
        print(elem.center)                      # (1453, 113)

        # 连接弹出的子窗口（如创建日程弹窗）
        parser.connect_window("创建日程")
        save_btn = parser.find(UITreeSelector("Button", name="保存"))
    """

    def __init__(self):
        self._app: Application | None = None
        self._win = None

    # ── 连接 ─────────────────────────────────────────────────────────────────

    def connect(self, title: str = "飞书") -> None:
        """
        连接飞书主窗口（精确标题匹配）。
        - 自动唤起最小化/后台的飞书窗口并置于前台
        - 若存在多个同名窗口，取面积最大的作为主窗口
        - 找不到则提示用户打开飞书
        """
        _log.info(f"搜索窗口 '{title}'...")
        handles: list[int] = []
        def _enum(hwnd, _):
            if win32gui.GetWindowText(hwnd) == title:
                handles.append(hwnd)
        win32gui.EnumWindows(_enum, None)

        if not handles:
            raise RuntimeError(f"未找到标题为 '{title}' 的窗口，请先打开飞书桌面端")

        def _area(h: int) -> int:
            l, t, r, b = win32gui.GetWindowRect(h)
            return (r - l) * (b - t)

        hwnd = max(handles, key=_area)
        _log.info(f"唤起窗口 hwnd={hwnd}，置前台...")
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.8)

        self._app = Application(backend="uia").connect(handle=hwnd)
        self._win = self._app.top_window()
        _log.info("飞书主窗口连接成功")

    def connect_window(self, title: str, timeout: float = 5.0) -> bool:
        """
        连接指定标题的顶层窗口（用于独立弹窗，如"创建日程"）。
        返回 True 表示连接成功，False 表示超时未找到。
        """
        _log.info(f"等待新窗口 '{title}'（超时 {timeout}s）...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            for w in Desktop(backend="uia").windows():
                try:
                    if w.window_text() == title:
                        self._win = w
                        _log.info(f"已连接新窗口 '{title}'")
                        return True
                except Exception:
                    pass
            time.sleep(0.3)
        return False

    def wait_for_new_window(
        self, known_titles: set[str], timeout: float = 5.0
    ) -> str | None:
        """
        等待出现一个新的顶层窗口（标题不在 known_titles 中）。
        返回新窗口标题，超时返回 None。
        用于检测"创建日程"等弹窗的出现。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for w in Desktop(backend="uia").windows():
                try:
                    title = w.window_text()
                    if title and title not in known_titles:
                        return title
                except Exception:
                    pass
            time.sleep(0.3)
        return None

    def current_window_titles(self) -> set[str]:
        """返回当前所有顶层窗口标题的集合（用于快照对比）"""
        titles = set()
        for w in Desktop(backend="uia").windows():
            try:
                t = w.window_text()
                if t:
                    titles.add(t)
            except Exception:
                pass
        return titles

    # ── 查找元素 ──────────────────────────────────────────────────────────────

    def find(self, selector: UITreeSelector) -> UIElement | None:
        """
        在当前窗口中查找第一个匹配的元素。
        找不到返回 None，不抛异常。
        """
        results = self.find_all(selector)
        return results[0] if results else None

    def find_all(self, selector: UITreeSelector) -> list[UIElement]:
        """返回所有匹配的元素列表"""
        if self._win is None:
            raise RuntimeError("未连接窗口，请先调用 connect() 或 connect_window()")

        matched = []
        try:
            for elem in self._win.descendants():
                ui_elem = self._to_ui_element(elem)
                if ui_elem and self._matches(ui_elem, selector):
                    matched.append(ui_elem)
        except Exception:
            pass
        return matched

    def get_all(self, visible_only: bool = True) -> list[UIElement]:
        """返回当前窗口所有有效元素（用于调试和状态快照）"""
        if self._win is None:
            raise RuntimeError("未连接窗口")

        result = []
        try:
            for elem in self._win.descendants():
                ui_elem = self._to_ui_element(elem)
                if ui_elem:
                    if visible_only and ui_elem.center_x == 0 and ui_elem.center_y == 0:
                        continue
                    result.append(ui_elem)
        except Exception:
            pass
        return result

    # ── 滚动区域支持 ──────────────────────────────────────────────────────────

    def scroll_and_find(
        self,
        selector: UITreeSelector,
        scroll_target: UIElement,
        max_scrolls: int = 5,
        scroll_amount: int = 3,
    ) -> UIElement | None:
        """
        在可滚动区域内逐步向下滚动并查找目标元素。
        scroll_target: 要在其上执行滚动的元素（通常是 Group 'scrollable content'）
        """
        import pyautogui

        for _ in range(max_scrolls):
            result = self.find(selector)
            if result:
                return result
            pyautogui.scroll(-scroll_amount, x=scroll_target.center_x, y=scroll_target.center_y)
            time.sleep(0.4)

        return None

    # ── 私有辅助方法 ──────────────────────────────────────────────────────────

    def _to_ui_element(self, raw_elem) -> UIElement | None:
        """将 pywinauto 原始元素转换为 UIElement，失败返回 None"""
        try:
            info = raw_elem.element_info
            name    = info.name or ""
            auto_id = info.automation_id or ""
            ctrl    = info.control_type
            rect    = raw_elem.rectangle()
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            return UIElement(
                control_type=ctrl,
                name=name,
                auto_id=auto_id,
                center_x=cx,
                center_y=cy,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                _raw=raw_elem,
            )
        except Exception:
            return None

    def _matches(self, elem: UIElement, sel: UITreeSelector) -> bool:
        """判断元素是否满足 selector 条件"""
        if elem.control_type != sel.control_type:
            return False
        if sel.name is not None and elem.name != sel.name:
            return False
        if sel.name_contains is not None and sel.name_contains not in elem.name:
            return False
        return True
