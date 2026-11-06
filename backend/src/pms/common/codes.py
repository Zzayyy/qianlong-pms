"""统一错误码。

设计稿 09 §1.2：业务码与 HTTP 状态码一一映射，前端只认 code。
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。"""

    SUCCESS = 0
    PARAM_ERROR = 40001
    UNAUTHORIZED = 40101
    FORBIDDEN = 40301
    DATA_FORBIDDEN = 40302
    NOT_FOUND = 40401
    STATE_INVALID = 40901
    CONFLICT = 40902
    BIZ_RULE = 42201
    RATE_LIMIT = 42901
    SERVER_ERROR = 50001


ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.SUCCESS: 200,
    ErrorCode.PARAM_ERROR: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.DATA_FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.STATE_INVALID: 409,
    ErrorCode.CONFLICT: 409,
    ErrorCode.BIZ_RULE: 422,
    ErrorCode.RATE_LIMIT: 429,
    ErrorCode.SERVER_ERROR: 500,
}


def http_status_of(code: ErrorCode) -> int:
    """返回错误码对应的 HTTP 状态码。"""
    return ERROR_HTTP_STATUS.get(code, 500)
