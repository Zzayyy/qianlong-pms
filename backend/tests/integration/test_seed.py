"""初始化种子数据测试：幂等性 + 账号可登录 + 权限点差异（设计稿 03）。"""

from __future__ import annotations

import pytest

from pms.core.database import get_session_factory
from pms.org import service as org_service
from pms.system.seed import DEFAULT_PASSWORD, reset_password, seed_all

pytestmark = pytest.mark.integration


async def test_seed_is_idempotent() -> None:
    """重复执行种子不应产生重复数据。"""
    factory = get_session_factory()
    async with factory() as session:
        first = await seed_all(session)
        second = await seed_all(session)
        assert first.users >= 0
        assert second.total == 0, "重复初始化产生了新增数据，说明幂等失效"
        assert second.accounts, "应返回内置账号清单"


async def test_admin_can_login_with_all_permissions() -> None:
    """管理员账号可登录且具备系统参数权限。"""
    factory = get_session_factory()
    async with factory() as session:
        result = await org_service.authenticate(session, "admin", DEFAULT_PASSWORD)
        assert result.user_id > 0
        assert "sys:config" in result.permissions
        assert "project:approve" in result.permissions
        assert "ADMIN" in result.roles


async def test_dev_user_permission_scope() -> None:
    """开发账号有填报与查看权，但无系统参数权。"""
    factory = get_session_factory()
    async with factory() as session:
        result = await org_service.authenticate(session, "dev1", DEFAULT_PASSWORD)
        permissions = set(result.permissions)
        assert "worklog:create" in permissions
        assert "project:view" in permissions
        assert "sys:config" not in permissions


async def test_reset_password_roundtrip() -> None:
    """重置密码后可登录；账号不存在返回 False。"""
    factory = get_session_factory()
    async with factory() as session:
        assert await reset_password(session, "dev1", "Temp@12345") is True
        result = await org_service.authenticate(session, "dev1", "Temp@12345")
        assert result.user_id > 0
        assert await reset_password(session, "dev1", DEFAULT_PASSWORD) is True
        assert await reset_password(session, "not_exist_user", DEFAULT_PASSWORD) is False


async def test_seed_creates_dept_tree() -> None:
    """部门树按层级建立且负责人已回填。"""
    from sqlalchemy import select

    from pms.org.models import SysDept

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(SysDept).where(SysDept.deleted == 0).order_by(SysDept.level, SysDept.id)
        )
        depts = list(result.scalars().all())
    codes = {dept.dept_code for dept in depts}
    assert {"ROOT", "SALES", "PRODUCT", "DEV", "TEST", "OPS", "PMO"} <= codes
    root = next(dept for dept in depts if dept.dept_code == "ROOT")
    assert root.level == 1
    children = [dept for dept in depts if dept.parent_id == root.id]
    assert len(children) == 6
    assert all(dept.level == 2 for dept in children)
    assert any(dept.leader_id for dept in children)
