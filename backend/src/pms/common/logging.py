"""日志配置：JSON 风格输出 + traceId 注入。"""

from __future__ import annotations

import logging
import sys
from typing import Final, override

from pms.common.trace import get_trace_id

_LOG_FORMAT: Final[str] = (
    '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
    '"traceId":"%(traceId)s","message":"%(message)s"}'
)
_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S"


class TraceFilter(logging.Filter):
    """把上下文 traceId 注入日志记录。"""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """为记录补齐 traceId 字段。"""
        record.__dict__.setdefault("traceId", get_trace_id() or "-")
        return True


def setup_logging(level: str = "INFO") -> None:
    """初始化根日志器（幂等）。"""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(TraceFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """获取模块日志器。"""
    return logging.getLogger(name)
