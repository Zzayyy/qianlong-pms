"""审计留痕与多实例任务锁测试（真实库）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from pms.audit.lock import OWNER_TOKEN, acquire, release
from pms.audit.service import record_login, record_operate
from pms.core.database import get_session_factory
from pms.jobs import run_exclusive
from pms.system.seed import DEFAULT_PASSWORD
from pms.org.models import SysOperateLog
from pms.system.models import SysJobLock, SysLoginLog

pytestmark = pytest.mark.integration


def _lock_name() -> str:
    return f"test_lock_{uuid.uuid4().hex[:10]}"


async def _cleanup_lock(name: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(SysJobLock).where(SysJobLock.lock_name == name))
        await session.commit()


async def test_lock_is_exclusive_between_owners() -> None:
    """同一时刻只有一个持有者；释放后其他实例可抢占。"""
    name = _lock_name()
    try:
        factory = get_session_factory()
        async with factory() as session:
            assert await acquire(session, name, 60, owner="instance-A") is True
            assert await acquire(session, name, 60, owner="instance-B") is False
            # 同一持有者重复抢占等于续期
            assert await acquire(session, name, 60, owner="instance-A") is True
            await release(session, name, owner="instance-A")
            assert await acquire(session, name, 60, owner="instance-B") is True
    finally:
        await _cleanup_lock(name)


async def test_lock_takeover_after_expire() -> None:
    """持有者崩溃（锁过期）后可由其他实例接管。"""
    name = _lock_name()
    try:
        factory = get_session_factory()
        async with factory() as session:
            assert await acquire(session, name, 60, owner="instance-A") is True
            row = (
                await session.execute(
                    select(SysJobLock).where(SysJobLock.lock_name == name)
                )
            ).scalar_one()
            row.expire_at = datetime.now() - timedelta(seconds=1)
            await session.commit()
        async with factory() as session:
            assert await acquire(session, name, 60, owner="instance-B") is True
    finally:
        await _cleanup_lock(name)


async def test_run_exclusive_skips_when_locked() -> None:
    """`run_exclusive` 抢不到锁时跳过任务且不抛错。"""
    name = _lock_name()
    calls: list[int] = []

    async def task() -> int:
        calls.append(1)
        return 42

    try:
        factory = get_session_factory()
        async with factory() as session:
            await acquire(session, name, 60, owner="instance-OTHER")
        result = await run_exclusive(name, task)
        assert result is None
        assert calls == []
        async with factory() as session:
            await release(session, name, owner="instance-OTHER")
        assert await run_exclusive(name, task) == 42
        assert calls == [1]
        # run_exclusive 结束后释放锁，当前进程可再次抢到
        async with factory() as session:
            row = (
                await session.execute(
                    select(SysJobLock).where(SysJobLock.lock_name == name)
                )
            ).scalar_one()
            assert row.owner_token == OWNER_TOKEN
    finally:
        await _cleanup_lock(name)


async def test_record_login_and_operate_written() -> None:
    """登录日志与操作审计能落库并可按 traceId 追溯。"""
    factory = get_session_factory()
    await record_login(
        username="audit_test_user",
        ip="127.0.0.1",
        user_agent="pytest",
        status="SUCCESS",
        message="单元测试",
    )
    await record_operate(
        user_id=0,
        module="test",
        operation="POST /api/v1/test",
        method="POST",
        url="/api/v1/test",
        params='{"password":"secret"}',
        result="SUCCESS",
        ip="127.0.0.1",
        cost_ms=1,
    )
    try:
        async with factory() as session:
            login = (
                await session.execute(
                    select(SysLoginLog).where(SysLoginLog.username == "audit_test_user")
                )
            ).scalars().all()
            operate = (
                await session.execute(
                    select(SysOperateLog).where(SysOperateLog.module == "test")
                )
            ).scalars().all()
        assert len(login) == 1
        assert login[0].status == "SUCCESS"
        assert len(operate) == 1
        assert "secret" not in (operate[0].params or "")
        assert operate[0].result == "SUCCESS"
    finally:
        async with factory() as session:
            await session.execute(
                delete(SysLoginLog).where(SysLoginLog.username == "audit_test_user")
            )
            await session.execute(delete(SysOperateLog).where(SysOperateLog.module == "test"))
            await session.commit()


async def test_audit_query_requires_permission() -> None:
    """审计查询需 `sys:log:view`：ADMIN 可查，DEV 角色被拒。"""
    import httpx

    from pms.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        admin = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": DEFAULT_PASSWORD}
        )
        admin_token = admin.json()["data"]["token"]
        dev = await client.post(
            "/api/v1/auth/login", json={"username": "dev1", "password": DEFAULT_PASSWORD}
        )
        dev_token = dev.json()["data"]["token"]

        ok_resp = await client.get(
            "/api/v1/audit/operate-logs?pageNum=1&pageSize=5",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        denied = await client.get(
            "/api/v1/audit/login-logs?pageNum=1&pageSize=5",
            headers={"Authorization": f"Bearer {dev_token}"},
        )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["code"] == 0
    assert isinstance(ok_resp.json()["data"]["list"], list)
    assert denied.status_code == 403
    assert denied.json()["code"] != 0


async def test_audit_middleware_logs_write_and_denied() -> None:
    """中间件对写操作留痕，对 401 拒绝留痕 DENIED。"""
    import httpx

    from pms.main import app

    factory = get_session_factory()
    transport = httpx.ASGITransport(app=app)
    mark = f"mw_{uuid.uuid4().hex[:8]}"
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"username": f"{mark}_nobody", "password": "WrongPass123"},
            )
            denied = await client.get(
                "/api/v1/projects?pageNum=1&pageSize=1",
                headers={"Authorization": "Bearer invalid.token.value"},
            )
        assert denied.status_code == 401
        async with factory() as session:
            rows = (
                await session.execute(
                    select(SysOperateLog).where(SysOperateLog.params.contains(mark))
                )
            ).scalars().all()
            denied_rows = (
                await session.execute(
                    select(SysOperateLog).where(
                        SysOperateLog.url.contains("/api/v1/projects"),
                        SysOperateLog.result == "DENIED",
                    )
                )
            ).scalars().all()
            login_rows = (
                await session.execute(
                    select(SysLoginLog).where(SysLoginLog.username == f"{mark}_nobody")
                )
            ).scalars().all()
        assert rows and rows[0].result == "DENIED"
        assert "WrongPass123" not in (rows[0].params or "")
        assert denied_rows
        assert login_rows and login_rows[0].status == "FAIL"
    finally:
        async with factory() as session:
            await session.execute(
                delete(SysOperateLog).where(SysOperateLog.url.contains(mark))
            )
            await session.execute(
                delete(SysLoginLog).where(SysLoginLog.username == f"{mark}_nobody")
            )
            await session.execute(
                delete(SysOperateLog).where(
                    SysOperateLog.url.contains("/api/v1/projects"),
                    SysOperateLog.result == "DENIED",
                )
            )
            await session.commit()
