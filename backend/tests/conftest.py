"""pytest 共享夹具。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Final

import pytest
import pytest_asyncio

from pms.common.trace import new_trace_id, set_trace_id
from pms.core.database import dispose_engine
from pms.core.redis import close_redis

BACKEND_ROOT: Final[Path] = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture(autouse=True)
async def _engine() -> AsyncIterator[None]:
    """每个用例结束后释放连接池，避免跨事件循环复用已关闭的连接。

    Redis 客户端是进程级单例，事件循环切换后必须一并关闭，
    否则会报 `Event loop is closed`（Redis 在线时才会暴露）。
    """
    yield
    await dispose_engine()
    await close_redis()


@pytest.fixture(autouse=True)
def _trace() -> Iterator[None]:
    """每个用例分配独立 traceId，避免日志串扰。"""
    set_trace_id(new_trace_id())
    yield
    set_trace_id("")


@pytest.fixture
def project_root() -> Path:
    """后端根目录（`backend/`）。"""
    return BACKEND_ROOT
