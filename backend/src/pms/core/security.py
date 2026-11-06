"""认证凭据：密码哈希与 JWT。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import bcrypt
from jose import JWTError, jwt

from pms.common.exceptions import UnauthorizedError
from pms.core.config import get_settings

_ALGORITHM: Final[str] = "HS256"
_TOKEN_TYPE: Final[str] = "access"
_BCRYPT_ROUNDS: Final[int] = 12


def hash_password(raw: str) -> str:
    """生成密码哈希（BCrypt，cost=12）。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode(
        "utf-8"
    )


def verify_password(raw: str, hashed: str) -> bool:
    """校验密码；哈希异常时按失败处理。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    subject: str,
    extra: dict[str, object] | None = None,
    expires_minutes: int | None = None,
) -> str:
    """签发访问令牌。"""
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now() + timedelta(minutes=minutes)
    payload: dict[str, object] = {
        "sub": subject,
        "type": _TOKEN_TYPE,
        "exp": expire,
        "iat": datetime.now(),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object]:
    """解析令牌；失败抛 UnauthorizedError。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError() from exc
    if payload.get("type") != _TOKEN_TYPE:
        raise UnauthorizedError("令牌类型不正确")
    return payload
