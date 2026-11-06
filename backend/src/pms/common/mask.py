"""敏感字段脱敏（设计稿 03 §4.4：字段级权限，非白名单角色出参脱敏）。"""

from __future__ import annotations

from typing import Final

_MASK: Final[str] = "****"


def mask_mobile(mobile: str) -> str:
    """手机号脱敏：`138****1234`。"""
    if len(mobile) < 7:
        return _MASK
    return f"{mobile[:3]}{_MASK}{mobile[-4:]}"


def mask_email(email: str) -> str:
    """邮箱脱敏：首字符 + `****` + 域名。"""
    if "@" not in email:
        return _MASK
    name, domain = email.split("@", 1)
    if not name:
        return f"{_MASK}@{domain}"
    return f"{name[0]}{_MASK}@{domain}"


def mask_name(name: str) -> str:
    """姓名脱敏：保留姓氏。"""
    if len(name) <= 1:
        return name
    return f"{name[0]}{_MASK[0] * min(len(name) - 1, 2)}"


def mask_amount(value: float | None) -> str:
    """金额脱敏：不可见时返回区间标识。"""
    if value is None:
        return _MASK
    return "***" if value > 0 else "0.00"
