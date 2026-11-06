"""端到端冒烟：项目看板指标、部门/公司看板、个人看板与日聚合。

需要真实 MySQL（`.env`），用例自带数据清理，可重复执行。
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Final

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.core.context import AuthContext
from pms.core.database import get_session_factory
from pms.org.models import SysDept, SysUser
from pms.project import service as project_service
from pms.project.models import PrjBaseline, PrjProject, PrjStage, PrjTask
from pms.report import service as report_service
from pms.report.models import StProjectDaily, StWorklogDaily
from pms.system.config_service import ConfigService
from pms.worklog import service as worklog_service
from pms.worklog.models import WlItem, WlWorklog

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time()) % 100000)
_TODAY: Final[str] = date.today().isoformat()


def _context(user: SysUser, dept_id: int) -> AuthContext:
    """构造服务层身份上下文。"""
    return AuthContext(
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        dept_id=dept_id,
        dept_path=f"/{dept_id}/",
        roles=frozenset(),
        permissions=frozenset(),
        visible_dept_ids=None,
    )


async def test_dashboards_and_aggregate() -> None:
    """看板指标与日聚合。"""
    factory = get_session_factory()
    created: dict[type, list[int]] = {
        SysDept: [],
        SysUser: [],
        PrjProject: [],
        PrjStage: [],
        PrjTask: [],
        PrjBaseline: [],
        WlWorklog: [],
    }
    async with factory() as session:
        try:
            await ConfigService(session).seed_defaults()
            await session.commit()

            dept = SysDept(parent_id=0, dept_name=f"看板部门{_SUFFIX}", dept_code=f"RP{_SUFFIX}", path="/", level=1)
            session.add(dept)
            await session.flush()
            created[SysDept].append(dept.id)

            pm = SysUser(username=f"rp_pm_{_SUFFIX}", real_name="项目经理", dept_id=dept.id, password_hash="x")
            member = SysUser(username=f"rp_m_{_SUFFIX}", real_name="成员", dept_id=dept.id, password_hash="x")
            session.add_all([pm, member])
            await session.flush()
            created[SysUser].extend([pm.id, member.id])
            await session.commit()

            pm_ctx = _context(pm, dept.id)
            member_ctx = _context(member, dept.id)

            project = await project_service.create_project(
                session,
                pm_ctx,
                project_name=f"看板项目{_SUFFIX}",
                dept_id=dept.id,
                pm_id=pm.id,
                plan_start="2026-11-01",
                plan_end="2026-12-31",
            )
            created[PrjProject].append(project.id)
            await project_service.submit_for_approval(session, project.id)
            await project_service.approve_project(session, project.id, pm.id)
            stage = await project_service.create_stage(session, project.id, "开发阶段", weight=1, seq=1)
            created[PrjStage].append(stage.id)
            await project_service.add_member(session, project.id, member.id, dept.id, "MEMBER")
            task = await project_service.create_task(
                session, project.id, "开发", stage_id=stage.id, owner_id=member.id, plan_hours=100
            )
            created[PrjTask].append(task.id)
            await session.commit()

            # 日志确认 → 实际工时与进度回填
            worklog = await worklog_service.save_draft(
                session,
                member_ctx,
                log_date=_TODAY,
                total_hours=8,
                content="开发",
                items=[{"projectId": project.id, "taskId": task.id, "hours": 8, "progressAfter": 60}],
            )
            created[WlWorklog].append(worklog.id)
            await worklog_service.submit(session, worklog.id, member.id)
            await worklog_service.confirm(session, worklog.id, pm.id)
            await session.commit()

            # 1. 项目看板
            dashboard = await report_service.project_dashboard(session, project.id)
            metric = dashboard["metric"]
            assert float(metric["actualHours"]) == 8
            assert float(metric["plannedHours"]) == 100
            assert metric["health"] in {"GREEN", "YELLOW", "RED"}
            assert float(metric["progress"]) == 60
            assert round(float(metric["spi"]), 2) == 0.6
            assert len(dashboard["stages"]) == 1

            # 2. 部门与公司看板
            dept_board = await report_service.dept_dashboard(session, [dept.id])
            assert dept_board["summary"]["projectCount"] >= 1
            company_board = await report_service.company_dashboard(session)
            assert company_board["summary"]["projectCount"] >= 1
            assert dept.id in company_board["byDept"]

            # 3. 个人看板
            personal = await report_service.personal_summary(
                session,
                user_id=member.id,
                date_from=(date.today() - timedelta(days=7)).isoformat(),
                date_to=_TODAY,
            )
            assert personal["stats"]["submittedDays"] == 1
            assert personal["byProject"][0]["hours"] == 8

            # 4. 日聚合（幂等覆盖）
            result = await report_service.aggregate_daily(session, _TODAY)
            await session.commit()
            assert result["projects"] >= 1
            project_rows = await session.execute(
                select(StProjectDaily.id).where(StProjectDaily.stat_date == _TODAY)
            )
            created[StProjectDaily] = list(project_rows.scalars().all())
            log_rows = await session.execute(
                select(StWorklogDaily.id).where(StWorklogDaily.stat_date == _TODAY)
            )
            created[StWorklogDaily] = list(log_rows.scalars().all())
            assert created[StWorklogDaily], "已确认日志应写入人员日工时快照"

            # 二次执行不重复累加
            again = await report_service.aggregate_daily(session, _TODAY)
            await session.commit()
            assert again["projects"] == result["projects"]
        finally:
            for model, ids in created.items():
                if ids:
                    await session.execute(delete(model).where(model.id.in_(ids)))
            await session.commit()
