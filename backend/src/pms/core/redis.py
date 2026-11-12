"""Redis 客户端：会话黑名单、配置缓存、幂等键。

设计稿 02 §3：Redis 不可用时降级为「无缓存」而不是让业务失败。
"""

from __future__ import annotations

import time
from typing import Final

from redis.asyncio import Redis

from pms.common.logging import get_logger
from pms.core.config import get_settings

logger = get_logger(__name__)

_client: Redis | None = None
_unavailable: bool = False
_next_retry_at: float = 0.0

SESSION_BLACKLIST: Final[str] = "pms:session:blacklist:"
CONFIG_CACHE: Final[str] = "pms:config:"
PERM_CACHE: Final[str] = "pms:perm:user:"
USER_EPOCH: Final[str] = "pms:user:epoch:"
IDEMPOTENCY: Final[str] = "pms:idem:"

# 连接/读写超时（秒）：本地 Redis 远快于此；未部署 Redis 时也能快速失败
_CONNECT_TIMEOUT: Final[float] = 0.2
_SOCKET_TIMEOUT: Final[float] = 0.2
# 熔断窗口（秒）：失败后这段时间内直接降级，避免每个请求都等连接超时
_BREAK_SECONDS: Final[float] = 30.0
# 空闲健康检查（秒）：连接空闲超过该时长先 PING 探活，避免把命令写进已被
# 服务端/网络关闭的 socket（表现为 AttributeError: 'NoneType' ... '_add_writer'）
_HEALTH_CHECK_SECONDS: Final[int] = 30


def _mark_unavailable(reason: str) -> None:
    """标记不可用并开启熔断窗口。"""
    global _unavailable, _next_retry_at
    if not _unavailable:
        logger.warning("Redis 不可用，降级为无缓存（%s 秒后重试）：%s", _BREAK_SECONDS, reason)
    _unavailable = True
    _next_retry_at = time.monotonic() + _BREAK_SECONDS


async def _discard_client() -> None:
    """丢弃当前客户端：连接池可能残留失效 socket，重建比复用更可靠。"""
    global _client
    client, _client = _client, None
    if client is None:
        return
    try:
        await client.aclose()
    except Exception as exc:  # noqa: BLE001 关闭本身失败无需上报（连接已不可用）
        logger.debug("关闭 Redis 连接异常：%s", exc)


async def _degrade(exc: BaseException) -> None:
    """Redis 故障统一降级：开熔断窗口 + 丢弃可能已失效的连接池。

    说明：redis-py 在连接被对端关闭后可能抛出 `AttributeError`、`OSError` 等
    非 `RedisError` 的异常（写空传输层）。按设计稿 02 §3「Redis 不可用时降级」，
    这里必须兜住**所有**异常，绝不能让缓存故障变成 500。
    """
    _mark_unavailable(f"{type(exc).__name__}: {exc}")
    await _discard_client()


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
                health_check_interval=_HEALTH_CHECK_SECONDS,
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
    except Exception as exc:  # noqa: BLE001 缓存故障一律降级，不阻断业务
        await _degrade(exc)
        return None
    return value


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    """写入缓存，异常时静默失败。"""
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        await _degrade(exc)


async def cache_delete(key: str) -> None:
    """删除缓存，异常时静默失败。"""
    client = get_redis()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception as exc:  # noqa: BLE001
        await _degrade(exc)


async def cache_delete_prefix(prefix: str, batch: int = 200) -> int:
    """按前缀批量删除缓存（如角色授权变更后清理权限缓存），返回删除条数。

    Redis 不可用时静默返回 0：缓存失效只影响新鲜度，不影响业务正确性。
    """
    client = get_redis()
    if client is None:
        return 0
    removed = 0
    try:
        async for key in client.scan_iter(match=f"{prefix}*", count=batch):
            await client.delete(key)
            removed += 1
    except Exception as exc:  # noqa: BLE001 缓存清理失败不影响主流程
        await _degrade(exc)
    return removed


async def close_redis() -> None:
    """关闭连接（关机钩子调用）。"""
    await _discard_client()


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


# ---------------- 用户会话版本 ----------------
# 令牌中携带 epoch：停用账号、改密、变更角色/部门等操作会递增版本，
# 旧令牌因此立即失效（权限与数据范围不再等到令牌过期才刷新）。
# Redis 不可用时退化为进程内计数，单进程部署同样生效。
_memory_epoch: dict[int, int] = {}


async def get_user_epoch(user_id: int) -> int:
    """读取用户当前会话版本（缺省 0）。"""
    raw = await cache_get(f"{USER_EPOCH}{user_id}")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            logger.warning("会话版本值非法，回退内存：user=%s value=%s", user_id, raw)
    return _memory_epoch.get(user_id, 0)


async def bump_user_epoch(user_id: int) -> int:
    """递增用户会话版本，使已签发的令牌立即失效。"""
    value = await get_user_epoch(user_id) + 1
    _memory_epoch[user_id] = value
    await cache_set(f"{USER_EPOCH}{user_id}", str(value), ttl=30 * 24 * 3600)
    return value
