"""Redis 降级测试：不可用时快速失败 + 熔断（不得拖慢业务请求）。"""

from __future__ import annotations

import time

import pytest

from pms.core import redis as redis_module


@pytest.fixture
def _restore_state():
    """用例结束后还原模块级状态。"""
    saved = (redis_module._client, redis_module._unavailable, redis_module._next_retry_at)
    yield
    redis_module._client, redis_module._unavailable, redis_module._next_retry_at = saved


def test_circuit_breaker_returns_none(_restore_state) -> None:
    """熔断窗口内 `get_redis()` 直接返回 None，不重复尝试连接。"""
    redis_module._mark_unavailable("模拟故障")
    assert redis_module.get_redis() is None
    assert redis_module._unavailable is True


def test_circuit_breaker_expires(_restore_state) -> None:
    """熔断到期后允许再次尝试（不再永久降级）。"""
    redis_module._mark_unavailable("模拟故障")
    redis_module._next_retry_at = time.monotonic() - 1
    redis_module._unavailable = False
    assert redis_module._unavailable is False


async def test_cache_ops_never_raise_and_fast(_restore_state) -> None:
    """无 Redis 时缓存读写返回 None 且不抛异常，单次耗时显著小于 2 秒。"""
    redis_module._unavailable = False
    redis_module._next_retry_at = 0.0
    started = time.perf_counter()
    assert await redis_module.cache_get("pms:test:key") is None
    assert await redis_module.cache_set("pms:test:key", "v", ttl=1) is None
    assert await redis_module.cache_delete("pms:test:key") is None
    cost = time.perf_counter() - started
    assert cost < 2.0, f"三次缓存操作耗时 {cost:.2f}s，降级未生效"
