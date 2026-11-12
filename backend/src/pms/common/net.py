"""客户端 IP 解析（审计留痕 / 登录日志共用）。

背景：后端常位于反向代理之后（Vite dev server 的 `/api` 代理、Nginx 等），
此时 `request.client.host` 拿到的是代理自己的地址（代理与后端同机时即
`127.0.0.1`），审计里就全是本机回环地址，局域网访问也无法区分是谁操作。

取值规则：
1. 直连对端**不是**可信代理 → 以对端地址为准（不采信请求头，避免伪造 IP）；
2. 直连对端是可信代理（本机回环，或 `TRUSTED_PROXIES` 中配置的地址）→
   读取 `X-Forwarded-For` 代理链，**从右向左**取第一个非代理地址
   （右侧是最近一跳，能抵抗客户端在左侧塞入伪造地址）；
3. 代理链上全是本机/不可解析时，回落到 `X-Real-IP`、最后回落到对端地址。
"""

from __future__ import annotations

import ipaddress
from typing import Final

from starlette.requests import Request

from pms.core.config import get_settings

_LOCAL_ADDRESSES: Final[frozenset[str]] = frozenset({"127.0.0.1", "::1"})
_MAX_LEN: Final[int] = 64


def _normalize(raw: str) -> str:
    """归一化地址文本，非法值返回空串。

    支持 `1.2.3.4:5678`、`[::1]:5173`、`"1.2.3.4"` 等形式，便于直接入库。
    """
    text = raw.strip().strip('"').strip()
    if not text or text.lower() == "unknown":
        return ""
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    else:
        host, sep, port = text.partition(":")
        if sep and port.isdigit():
            text = host
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return ""


def _trusted_proxies() -> frozenset[str]:
    """可信代理集合：本机回环 + 配置项 `TRUSTED_PROXIES`（逗号分隔，`*` 表示全部）。"""
    raw = get_settings().trusted_proxies
    items = {_normalize(part) or part.strip() for part in raw.split(",") if part.strip()}
    return _LOCAL_ADDRESSES | items


def _is_trusted(address: str, trusted: frozenset[str]) -> bool:
    """地址是否为可信代理（`*` 视为全部可信）。"""
    return "*" in trusted or address in trusted


def _forwarded_chain(request: Request) -> list[str]:
    """收集代理链上的候选地址（`X-Forwarded-For` 优先，其次 `X-Real-IP`）。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return [item for item in (_normalize(part) for part in forwarded.split(",")) if item]
    real = _normalize(request.headers.get("x-real-ip", ""))
    return [real] if real else []


def client_ip(request: Request) -> str:
    """取真实客户端 IP（截断到 64 字符）。"""
    raw_peer = request.client.host if request.client else ""
    peer = _normalize(raw_peer)
    trusted = _trusted_proxies()
    if not _is_trusted(peer, trusted):
        return (peer or raw_peer)[:_MAX_LEN]
    for candidate in reversed(_forwarded_chain(request)):
        if not _is_trusted(candidate, trusted):
            return candidate[:_MAX_LEN]
    return (peer or raw_peer)[:_MAX_LEN]
