"""
全局配置
--------
敏感信息（API Key）请填写在项目根目录的 .env 文件中。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass
class Config:
    # ── 火山引擎 Ark 平台（UI-TARS + 规划 LLM 共用）────────────
    ark_api_key: str = field(
        default_factory=lambda: os.getenv("ARK_API_KEY", "")
    )
    ark_base_url: str = field(
        default_factory=lambda: os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    )

    # ── 视觉模型（UI-TARS 或通用视觉模型接入点）─────────────────
    # 优先使用 VISION_EP（通用视觉模型接入点），UI-TARS 权限开放后改用 UI_TARS_MODEL
    vision_ep: str = field(
        default_factory=lambda: os.getenv("VISION_EP", os.getenv("UI_TARS_MODEL", ""))
    )

    # ── LLM 规划器 ────────────────────────────────────────────
    planner_ep: str = field(
        default_factory=lambda: os.getenv("PLANNER_EP", os.getenv("PLANNER_MODEL", ""))
    )
    planner_api_key: str = field(
        default_factory=lambda: os.getenv("PLANNER_API_KEY", os.getenv("ARK_API_KEY", ""))
    )

    # ── Agent 执行行为 ────────────────────────────────────────
    max_retry: int = 2
    action_wait_ms: int = 500
    ui_render_timeout: float = 3.0

    # ── 对话管理 ──────────────────────────────────────────────
    max_clarification_turns: int = 2

    # ── 飞书窗口 ──────────────────────────────────────────────
    feishu_window_title_pattern: str = ".*飞书.*"

    # ── 测试专用 ──────────────────────────────────────────────
    test_contact_name: str = field(
        default_factory=lambda: os.getenv("TEST_CONTACT_NAME", "")
    )


config = Config()
