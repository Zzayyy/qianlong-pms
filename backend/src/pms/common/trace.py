"""链路追踪：基于 contextvars 的 traceId。"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_TRACE_ID: ContextVar[str] = ContextVar("pms_trace_id", default="")


def new_trace_id() -> str:
    """生成新的 traceId（32 位十六进制）。"""
    return uuid.uuid4().hex


def set_trace_id(value: str) -> None:
    """设置当前上下文的 traceId。"""
    _TRACE_ID.set(value)


def get_trace_id() -> str:
    """读取当前上下文的 traceId，缺省时返回空串。"""
    return _TRACE_ID.get()
