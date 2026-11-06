"""审计表按月归档测试（真实库）。

用例自行造旧数据 → 归档 → 校验主表已清空、月份表已落库 → 清理（删除归档表）。
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from pms.audit.archive import archive_audit, archive_table_name
from pms.core.database import get_session_factory

pytestmark = pytest.mark.integration

_OLD_MONTH = date(2024, 3, 1)


async def _insert_old_rows() -> str:
    """在两张审计表各插入 2 行 2024-03 的旧数据，返回标记。"""
    mark = f"arch_{uuid.uuid4().hex[:8]}"
    factory = get_session_factory()
    async with factory() as session:
        for _ in range(2):
            await session.execute(
                text(
                    "INSERT INTO t_sys_operate_log (id, module, operation, method, url, params, "
                    "result, ip, user_id, cost_ms, trace_id, create_by, create_time, update_time, "
                    "deleted, tenant_id) VALUES (:id, 'test', :op, 'POST', '/api/v1/test', '{}', "
                    "'SUCCESS', '127.0.0.1', 0, 1, :trace, 0, :ct, :ct, 0, 1)"
                ),
                {
                    "id": int(uuid.uuid4().int % (10**17)),
                    "op": f"POST {mark}",
                    "trace": mark,
                    "ct": _OLD_MONTH,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO t_sys_login_log (id, username, ip, user_agent, status, message, "
                    "trace_id, create_by, create_time, update_time, deleted, tenant_id) "
                    "VALUES (:id, :name, '127.0.0.1', 'pytest', 'SUCCESS', 'old', :trace, 0, :ct, "
                    ":ct, 0, 1)"
                ),
                {
                    "id": int(uuid.uuid4().int % (10**17)),
                    "name": mark,
                    "trace": mark,
                    "ct": _OLD_MONTH,
                },
            )
        await session.commit()
    return mark


async def _drop_archive_tables() -> None:
    """删除测试产生的归档表。"""
    factory = get_session_factory()
    async with factory() as session:
        for base in ("t_sys_operate_log", "t_sys_login_log"):
            table = archive_table_name(base, _OLD_MONTH)
            await session.execute(text(f"DROP TABLE IF EXISTS {table}"))  # noqa: S608
        await session.commit()


async def test_archive_moves_month_and_clears_main_table() -> None:
    """归档后：主表该月数据被删除，月份表存在且行数一致。"""
    mark = await _insert_old_rows()
    try:
        factory = get_session_factory()
        async with factory() as session:
            preview = await archive_audit(session, keep_months=1, dry_run=True)
            assert preview["dryRun"] is True
            assert preview["total"] >= 4
            assert "t_sys_operate_log" in preview["tables"]

            report = await archive_audit(session, keep_months=1)
            assert report["dryRun"] is False
            assert report["tables"]["t_sys_operate_log"].get("2024-03") == 2
            assert report["tables"]["t_sys_login_log"].get("2024-03") == 2

            remain_operate = (
                await session.execute(
                    text(
                        "SELECT COUNT(1) FROM t_sys_operate_log WHERE trace_id = :m "
                        "AND create_time < '2024-04-01'"
                    ),
                    {"m": mark},
                )
            ).scalar()
            archive_operate = (
                await session.execute(
                    text(f"SELECT COUNT(1) FROM {archive_table_name('t_sys_operate_log', _OLD_MONTH)}")
                )
            ).scalar()
            archive_login = (
                await session.execute(
                    text(f"SELECT COUNT(1) FROM {archive_table_name('t_sys_login_log', _OLD_MONTH)}")
                )
            ).scalar()
        assert int(remain_operate or 0) == 0
        assert int(archive_operate or 0) == 2
        assert int(archive_login or 0) == 2
    finally:
        async with factory() as session:
            await session.execute(text("DELETE FROM t_sys_operate_log WHERE trace_id = :m"), {"m": mark})
            await session.execute(text("DELETE FROM t_sys_login_log WHERE trace_id = :m"), {"m": mark})
            await session.commit()
        await _drop_archive_tables()


async def test_archive_keeps_recent_data() -> None:
    """当保留期覆盖数据时不做归档（`total == 0`）。"""
    mark = await _insert_old_rows()
    try:
        factory = get_session_factory()
        async with factory() as session:
            report = await archive_audit(session, keep_months=120)
            assert report["total"] == 0
            assert report["tables"] == {}
            remain = (
                await session.execute(
                    text("SELECT COUNT(1) FROM t_sys_operate_log WHERE trace_id = :m"),
                    {"m": mark},
                )
            ).scalar()
        assert int(remain or 0) == 2
    finally:
        async with factory() as session:
            await session.execute(text("DELETE FROM t_sys_operate_log WHERE trace_id = :m"), {"m": mark})
            await session.execute(text("DELETE FROM t_sys_login_log WHERE trace_id = :m"), {"m": mark})
            await session.commit()
