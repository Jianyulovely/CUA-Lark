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
from cua_lark.core.logger import get_logger
from cua_lark.execution.cua_executor import CUAExecutor
from cua_lark.perception.tree_parser import TreeParser
from cua_lark.planning.template_library import TemplateStep
from cua_lark.verification.verifier import TaskTemplate

_log = get_logger("执行")


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

    def run_with_verify(self, template: TaskTemplate) -> None:
        """
        执行模板步骤，完成后调用视觉验证，失败则自动重试。
        最多重试 config.max_retry 次（共执行 max_retry+1 次）。
        """
        from cua_lark.config import config

        max_attempts = config.max_retry + 1
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                _log.info(f"─── 第 {attempt} 次重试 ───")
                # 重新连接主窗口（上次执行可能切换了窗口）
                self._parser.connect()

            try:
                self.run(template.steps)
            except RuntimeError as e:
                _log.warning(f"执行失败（第{attempt}次）: {e}")
                if attempt < max_attempts:
                    continue
                raise

            # ── 验证 ──────────────────────────────────────────────────────
            _log.info("执行完毕，开始验证结果...")
            result = template.verify_fn(self._parser, self._ui_tars)

            if result.success:
                _log.info(f"验证通过：{result.message}")
                return

            _log.warning(f"验证失败（第{attempt}次）：{result.message}")
            if attempt < max_attempts:
                _log.info("准备重试整个任务...")
            else:
                raise RuntimeError(
                    f"任务执行完成但验证失败（已重试 {config.max_retry} 次）：{result.message}"
                )

    def run(self, steps: list[TemplateStep]) -> None:
        """按序执行所有步骤（无验证，供内部和测试脚本调用）"""
        _log.info(f"开始执行，共 {len(steps)} 步")
        for step in steps:
            _log.info(f"[{step.step_id}] ({step.routing:8}) {step.description}")
            self._execute_step(step)
            time.sleep(step.wait_ms / 1000)

            # 执行完成后切换到新顶层窗口（如"创建日程"弹窗）
            if step.switch_to_window:
                ok = self._parser.connect_window(step.switch_to_window, timeout=6.0)
                if not ok:
                    raise RuntimeError(
                        f"[{step.step_id}] 等待窗口 '{step.switch_to_window}' 超时"
                    )
        _log.info("所有步骤执行完毕")

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
        # find_fn 优先，selector 兜底
        if step.find_fn is not None:
            elem = step.find_fn(self._parser)
        elif step.selector is not None:
            elem = self._parser.find(step.selector)
        else:
            raise ValueError(f"[{step.step_id}] tree 步骤缺少 selector 或 find_fn")

        if elem is None:
            desc = (f"find_fn={step.find_fn.__name__}" if step.find_fn
                    else f"control_type={step.selector.control_type!r}, "
                         f"name={step.selector.name!r}")
            raise RuntimeError(f"[{step.step_id}] 未在 UI 树中找到元素: {desc}")

        _log.info(f"找到元素 '{elem.name}' @ ({elem.center_x}, {elem.center_y})，执行点击")
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
        _log.info("截图中...")
        screenshot_b64 = _capture_screenshot_base64()
        w, h = pyautogui.size()

        action = self._ui_tars.predict(
            instruction=step.description,
            screenshot_base64=screenshot_b64,
            screen_width=w,
            screen_height=h,
        )

        if action.action_type == "click":
            _log.info(f"执行点击 @ ({action.x}, {action.y})")
            self._executor.click(action.x, action.y)
        elif action.action_type == "finished":
            _log.info("视觉模型认为步骤已完成，跳过点击")
        elif action.action_type == "unknown":
            raise RuntimeError(
                f"[{step.step_id}] 视觉模型输出无法解析，请检查格式。\n"
                f"原始输出：\n{action.raw}"
            )
        else:
            raise RuntimeError(
                f"[{step.step_id}] 视觉模型返回了意外动作类型: {action.action_type}\n"
                f"原始输出：\n{action.raw}"
            )


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _capture_screenshot_base64() -> str:
    """截取全屏并返回 base64 编码的 PNG 字符串"""
    screenshot = pyautogui.screenshot()
    buffer = BytesIO()
    screenshot.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
