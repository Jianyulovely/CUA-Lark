"""
Agent 执行主循环（阶段三：单模板版本）
--------------------------------------
按顺序执行 TemplateStep 列表：

  tree     → TreeParser 实时查询坐标 → CUAExecutor.click()
  keyboard → CUAExecutor.type_text() / send_key()
  vision   → 截图 → UITARSClient.predict() → CUAExecutor.click()

阶段三不含重试逻辑；步骤失败直接抛出异常，方便调试定位问题。
"""

from __future__ import annotations

import base64
import time
from io import BytesIO

import pyautogui

from cua_lark.core.api_client import UITARSClient
from cua_lark.execution.cua_executor import CUAExecutor
from cua_lark.perception.tree_parser import TreeParser
from cua_lark.planning.template_library import TemplateStep


class AgentLoop:
    """
    单模板执行循环。

    使用示例：
        loop = AgentLoop()
        loop.connect()
        loop.run(send_message_steps(slots))
    """

    def __init__(self):
        self._parser   = TreeParser()
        self._executor = CUAExecutor()
        self._ui_tars  = UITARSClient()

    def connect(self) -> None:
        """连接飞书主窗口"""
        self._parser.connect()

    def run(self, steps: list[TemplateStep]) -> None:
        """按序执行所有步骤"""
        for step in steps:
            print(f"  [{step.step_id}] {step.description}")
            self._execute_step(step)
            time.sleep(step.wait_ms / 1000)

    # ── 步骤分发 ──────────────────────────────────────────────────────────────

    def _execute_step(self, step: TemplateStep) -> None:
        match step.routing:
            case "tree":
                self._run_tree(step)
            case "keyboard":
                self._run_keyboard(step)
            case "vision":
                self._run_vision(step)
            case _:
                raise ValueError(f"[{step.step_id}] 未知路由类型: {step.routing}")

    # ── tree：实时查坐标 → 点击 ───────────────────────────────────────────────

    def _run_tree(self, step: TemplateStep) -> None:
        if step.selector is None:
            raise ValueError(f"[{step.step_id}] tree 步骤缺少 selector")

        elem = self._parser.find(step.selector)
        if elem is None:
            raise RuntimeError(
                f"[{step.step_id}] 未在 UI 树中找到元素: "
                f"control_type={step.selector.control_type!r}, "
                f"name={step.selector.name!r}, "
                f"name_contains={step.selector.name_contains!r}"
            )

        print(f"         找到元素：{elem.name!r}，中心=({elem.center_x}, {elem.center_y})")
        self._executor.click(elem.center_x, elem.center_y)

    # ── keyboard：直接发送按键或文本 ──────────────────────────────────────────

    def _run_keyboard(self, step: TemplateStep) -> None:
        match step.action_type:
            case "type":
                if step.text is None:
                    raise ValueError(f"[{step.step_id}] type 步骤缺少 text")
                self._executor.type_text(step.text)
            case "key":
                if step.key_combo is None:
                    raise ValueError(f"[{step.step_id}] key 步骤缺少 key_combo")
                self._executor.send_key(step.key_combo)
            case _:
                raise ValueError(f"[{step.step_id}] 未知 action_type: {step.action_type}")

    # ── vision：截图 → UI-TARS → 执行 ────────────────────────────────────────

    def _run_vision(self, step: TemplateStep) -> None:
        print(f"         截图中...")
        screenshot_b64 = _capture_screenshot_base64()
        w, h = pyautogui.size()

        print(f"         调用 UI-TARS，指令：{step.description!r}")
        action = self._ui_tars.predict(
            instruction=step.description,
            screenshot_base64=screenshot_b64,
            screen_width=w,
            screen_height=h,
        )

        print(f"         思考：{action.thought!r}")
        print(f"         动作：{action.action_type}  坐标=({action.x}, {action.y})")

        if action.action_type == "click":
            self._executor.click(action.x, action.y)
        elif action.action_type == "finished":
            print(f"         [视觉模型] 认为步骤已完成，跳过点击")
        elif action.action_type == "unknown":
            raise RuntimeError(
                f"[{step.step_id}] 视觉模型输出无法解析，请检查格式。\n"
                f"         原始输出：\n{action.raw}"
            )
        else:
            raise RuntimeError(
                f"[{step.step_id}] 视觉模型返回了意外动作类型: {action.action_type}\n"
                f"         原始输出：\n{action.raw}"
            )


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _capture_screenshot_base64() -> str:
    """截取全屏并返回 base64 编码的 PNG 字符串"""
    screenshot = pyautogui.screenshot()
    buffer = BytesIO()
    screenshot.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
