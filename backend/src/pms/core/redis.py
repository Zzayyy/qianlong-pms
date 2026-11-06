"""Redis 客户端：会话黑名单、配置缓存、幂等键。

设计稿 02 §3：Redis 不可用时降级为「无缓存」而不是让业务失败。
"""

from __future__ import annotations

import time
from typing import Final

from redis.asyncio import Redis
from redis.exceptions import RedisError

from pms.common.logging import get_logger
from pms.core.config import get_settings

logger = get_logger(__name__)

_client: Redis | None = None
_unavailable: bool = False
_next_retry_at: float = 0.0

SESSION_BLACKLIST: Final[str] = "pms:session:blacklist:"
CONFIG_CACHE: Final[str] = "pms:config:"
PERM_CACHE: Final[str] = "pms:perm:user:"
IDEMPOTENCY: Final[str] = "pms:idem:"

# 连接/读写超时（秒）：本地 Redis 远快于此；未部署 Redis 时也能快速失败
_CONNECT_TIMEOUT: Final[float] = 0.2
_SOCKET_TIMEOUT: Final[float] = 0.2
# 熔断窗口（秒）：失败后这段时间内直接降级，避免每个请求都等连接超时
_BREAK_SECONDS: Final[float] = 30.0


def _mark_unavailable(reason: str) -> None:
    """标记不可用并开启熔断窗口。"""
    global _unavailable, _next_retry_at
    if not _unavailable:
        logger.warning("Redis 不可用，降级为无缓存（%s 秒后重试）：%s", _BREAK_SECONDS, reason)
    _unavailable = True
    _next_retry_at = time.monotonic() + _BREAK_SECONDS


def get_redis() -> Redis | None:
    """获取 Redis 客户端；不可用（或熔断中）时返回 None（降级）。"""
    global _client, _unavailable
    if _unavailable:
        if time.monotonic() < _next_retry_at:
            return None
        _unavailable = False  # 熔断到期，允许再试一次
    if _client is None:
        try:
            _client = Redis.from_url(
                get_settings().redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT,
                socket_timeout=_SOCKET_TIMEOUT,
            )
        except Exception as exc:  # 连接串错误等：记录后降级
            _mark_unavailable(str(exc))
            return None
    return _client


async def cache_get(key: str) -> str | None:
    """读取缓存，异常时返回 None。"""
    client = get_redis()
    if client is None:
        return None
    try:
        value = await client.get(key)
    except RedisError as exc:
        _mark_unavailable(str(exc))
        return None
    return value


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    """写入缓存，异常时静默失败。"""
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl)
    except RedisError as exc:
        _mark_unavailable(str(exc))


async def cache_delete(key: str) -> None:
    """删除缓存，异常时静默失败。"""
    client = get_redis()
    if client is None:
        return
    try:
        await client.delete(key)
    except RedisError as exc:
        _mark_unavailable(str(exc))


async def close_redis() -> None:
    """关闭连接（关机钩子调用）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------- 会话黑名单：Redis + 进程内内存兜底 ----------------
# 设计稿 11 §4：登出必须立即失效。Redis 不可用时若只依赖 Redis，
# 令牌在过期前仍可继续访问（安全缺口），故增加进程内黑名单兜底。
_memory_blacklist: dict[str, float] = {}


def _purge_memory() -> None:
    """清理已过期的内存黑名单条目。"""
    now = time.monotonic()
    expired = [key for key, deadline in _memory_blacklist.items() if deadline <= now]
    for key in expired:
        _memory_blacklist.pop(key, None)


async def blacklist_add(token: str, ttl: int) -> None:
    """加入黑名单（同时写 Redis 与内存）。"""
    _purge_memory()
    _memory_blacklist[token] = time.monotonic() + ttl
    await cache_set(f"{SESSION_BLACKLIST}{token}", "1", ttl=ttl)


async def blacklist_contains(token: str) -> bool:
    """判断令牌是否已登出（内存优先，避免每次查 Redis）。"""
    _purge_memory()
    if token in _memory_blacklist:
        return True
    return bool(await cache_get(f"{SESSION_BLACKLIST}{token}"))
