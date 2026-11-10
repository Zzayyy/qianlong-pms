"""pytest 共享夹具。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Final

import pytest
import pytest_asyncio

from pms.common.trace import new_trace_id, set_trace_id
from pms.core.database import dispose_engine, get_session_factory
from pms.core.redis import close_redis
from pms.system.config_service import ConfigService

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


@pytest_asyncio.fixture
async def seed_admin_account() -> AsyncIterator[None]:
    """依赖「种子 admin 默认密码」的用例前置校验。

    开发库里的 admin 密码常被手工改过（改密是正常业务），
    此时用例的前提已不成立，直接跳过而不覆盖真实密码。
    """
    from sqlalchemy import select

    from pms.core.security import verify_password
    from pms.org.models import SysUser
    from pms.system.seed import DEFAULT_PASSWORD

    factory = get_session_factory()
    async with factory() as session:
        user = (
            await session.execute(select(SysUser).where(SysUser.username == "admin"))
        ).scalars().first()
    if user is not None and not verify_password(DEFAULT_PASSWORD, user.password_hash):
        pytest.skip("admin 密码已非种子默认值（开发库被手工改过），跳过依赖默认密码的用例")
    yield


@pytest_asyncio.fixture
async def worklog_confirm_required() -> AsyncIterator[None]:
    """临时开启「日志需 PM 确认」开关，用例结束后还原。

    `worklog.confirm.required` 默认关闭（提交即生效），
    验证确认 / 撤销 / 补填审批链路的用例必须显式开启，
    否则 `submit` 会直接进入 CONFIRMED，`confirm` 无日志可确认。
    """
    factory = get_session_factory()
    async with factory() as session:
        config = ConfigService(session)
        backup = await config.get_str("worklog.confirm.required") or "false"
        await config.set_value("worklog.confirm.required", "true")
        await session.commit()
    try:
        yield
    finally:
        async with factory() as session:
            await ConfigService(session).set_value("worklog.confirm.required", backup)
            await session.commit()
