"""认证凭据测试。"""

from __future__ import annotations

import pytest

from pms.common.exceptions import UnauthorizedError
from pms.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_and_verify() -> None:
    """BCrypt 哈希可验证且不相同。"""
    hashed = hash_password("P@ssw0rd")
    assert hashed != "P@ssw0rd"
    assert verify_password("P@ssw0rd", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_token_roundtrip() -> None:
    """令牌可签发并解析出声明。"""
    token = create_access_token("1001", {"roles": ["DEV"], "dept": 30})
    payload = decode_access_token(token)
    assert payload["sub"] == "1001"
    assert payload["roles"] == ["DEV"]
    assert payload["dept"] == 30


def test_invalid_token_raises() -> None:
    """非法令牌抛未认证异常。"""
    with pytest.raises(UnauthorizedError):
        decode_access_token("not-a-token")
