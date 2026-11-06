"""统一响应体测试（设计稿 09 §1.1）。"""

from __future__ import annotations

from pms.common.codes import ErrorCode, http_status_of
from pms.common.response import ok, paged


def test_ok_response_structure() -> None:
    """成功响应包含约定字段且 code 为 0。"""
    payload = ok({"id": 1})
    assert payload.code == ErrorCode.SUCCESS
    assert payload.data == {"id": 1}
    assert payload.timestamp != ""


def test_paged_calculation() -> None:
    """分页总页数向上取整。"""
    payload = paged([1, 2, 3], total=25, page_num=2, page_size=10)
    assert payload.data is not None
    assert payload.data.pages == 3
    assert payload.data.pageNum == 2
    assert payload.data.items == [1, 2, 3]
    assert "list" in payload.data.model_dump(by_alias=True)


def test_error_http_mapping() -> None:
    """错误码映射 HTTP 状态码。"""
    assert http_status_of(ErrorCode.NOT_FOUND) == 404
    assert http_status_of(ErrorCode.BIZ_RULE) == 422
    assert http_status_of(ErrorCode.DATA_FORBIDDEN) == 403
