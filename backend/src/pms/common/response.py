"""统一响应体。

设计稿 09 §1.1：`{code, message, data, traceId, timestamp}`；分页附加 `total/pageNum/pageSize/pages`。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from pms.common.codes import ErrorCode
from pms.common.trace import get_trace_id

T = TypeVar("T")

# JavaScript Number 的安全整数上限，雪花 ID 远超该值
_MAX_SAFE_INT: Final[int] = 2**53 - 1


def stringify_bigints(value: Any) -> Any:
    """递归把超出 JS 安全整数范围的整数转为字符串，避免前端精度丢失。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > _MAX_SAFE_INT else value
    if isinstance(value, dict):
        return {key: stringify_bigints(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [stringify_bigints(item) for item in value]
    return value


class SafeJSONResponse(JSONResponse):
    """统一响应：雪花 ID 以字符串返回，其余整数保持数字。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            stringify_bigints(content),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应体。"""

    code: int = Field(default=ErrorCode.SUCCESS, description="业务错误码")
    message: str = Field(default="success", description="提示信息")
    data: T | None = None
    traceId: str = Field(default="", description="链路追踪 ID")
    timestamp: str = Field(default="", description="响应时间戳")


class PageData(BaseModel, Generic[T]):
    """分页数据包装（对外字段名为 `list`）。"""

    model_config = ConfigDict(populate_by_name=True)

    items: list[T] = Field(default_factory=list, serialization_alias="list")
    total: int = 0
    pageNum: int = 1
    pageSize: int = 20
    pages: int = 0


def now_text() -> str:
    """返回本地时间戳文本（秒精度）。"""
    return datetime.now().isoformat(timespec="seconds")


def ok(data: T | None = None, message: str = "success") -> ApiResponse[T]:
    """构造成功响应。"""
    return ApiResponse[T](
        code=ErrorCode.SUCCESS,
        message=message,
        data=data,
        traceId=get_trace_id(),
        timestamp=now_text(),
    )


def paged(
    items: list[T],
    total: int,
    page_num: int,
    page_size: int,
) -> ApiResponse[PageData[T]]:
    """构造分页成功响应。"""
    pages: int = (total + page_size - 1) // page_size if page_size > 0 else 0
    payload: PageData[T] = PageData[T](
        items=items,
        total=total,
        pageNum=page_num,
        pageSize=page_size,
        pages=pages,
    )
    return ok(payload)
