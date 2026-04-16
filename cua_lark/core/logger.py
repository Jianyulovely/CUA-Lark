"""
统一日志配置
------------
各模块通过 get_logger(name) 获取 Logger，输出格式：

    14:23:01 [对话] 调用规划模型...
    14:23:02 [视觉] click @ (523, 342)
"""

import logging
import sys

_FMT = "%(asctime)s [%(name)s] %(message)s"
_DATE_FMT = "%H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
