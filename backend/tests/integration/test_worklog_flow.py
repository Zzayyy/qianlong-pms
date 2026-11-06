"""端到端冒烟：日志填报 → 提交 → 确认回填 → 撤销 → 补填审批 → 可见性 → 统计。

需要真实 MySQL（`.env`），用例自带数据清理，可重复执行。
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Final

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError
from pms.core.context import AuthContext
from pms.core.database import get_session_factory
from pms.org.models import SysDept, SysUser
from pms.project import service as project_service
from pms.project.models import PrjBaseline, PrjProject, PrjRisk, PrjTask
from pms.system.config_service import ConfigService
from pms.worklog import service as worklog_service
from pms.worklog.models import WlComment, WlItem, WlReminder, WlWorklog
from pms.worklog.rules import WorklogStatus

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time()) % 100000)
_TODAY: Final[str] = date.today().isoformat()
_LATE_DAY: Final[str] = (date.today() - timedelta(days=5)).isoformat()


def _context(user: SysUser, dept_id: int, visible: set[int] | None = None) -> AuthContext:
    """构造服务层身份上下文。"""
    return AuthContext(
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        dept_id=dept_id,
        dept_path=f"/{dept_id}/",
        roles=frozenset(),
        permissions=frozenset(),
        visible_dept_ids=None if visible is None else frozenset(visible),
    )


async def test_worklog_confirm_and_visibility() -> None:
    """日志主链路：确认回填工时、撤销回滚、补填审批、项目组互看、同部门非同项目不可见。"""
    factory = get_session_factory()
    created: dict[type, list[int]] = {
        SysDept: [],
        SysUser: [],
        PrjProject: [],
        PrjTask: [],
        PrjBaseline: [],
        PrjRisk: [],
        WlWorklog: [],
        WlItem: [],
        WlComment: [],
        WlReminder: [],
    }
    async with factory() as session:
        try:
            await ConfigService(session).seed_defaults()
            await session.commit()

            dept = SysDept(parent_id=0, dept_name=f"日志部门{_SUFFIX}", dept_code=f"WL{_SUFFIX}", path="/", level=1)
            session.add(dept)
            await session.flush()
            created[SysDept].append(dept.id)

            member = SysUser(username=f"wl_m_{_SUFFIX}", real_name="成员", dept_id=dept.id, password_hash="x")
            mate = SysUser(username=f"wl_t_{_SUFFIX}", real_name="同事", dept_id=dept.id, password_hash="x")
            pm = SysUser(username=f"wl_pm_{_SUFFIX}", real_name="项目经理", dept_id=dept.id, password_hash="x")
            member.manager_id = None
            session.add_all([member, mate, pm])
            await session.flush()
            member.manager_id = pm.id
            mate.manager_id = pm.id
            created[SysUser].extend([member.id, mate.id, pm.id])
            await session.commit()

            member_ctx = _context(member, dept.id, {dept.id})
            mate_ctx = _context(mate, dept.id, {dept.id})

            project = await project_service.create_project(
                session, _context(pm, dept.id), project_name=f"日志项目{_SUFFIX}", dept_id=dept.id, pm_id=pm.id
            )
            created[PrjProject].append(project.id)
            await project_service.submit_for_approval(session, project.id)
            await project_service.approve_project(session, project.id, pm.id)
            await project_service.add_member(session, project.id, member.id, dept.id, "MEMBER")
            task = await project_service.create_task(
                session, project.id, "开发任务", stage_id=0, owner_id=member.id, plan_hours=40
            )
            created[PrjTask].append(task.id)
            await session.commit()

            # 1. 填报并提交（当日）
            worklog = await worklog_service.save_draft(
                session,
                member_ctx,
                log_date=_TODAY,
                total_hours=6,
                content="完成接口开发",
                items=[{"projectId": project.id, "taskId": task.id, "hours": 6, "progressAfter": 50}],
            )
            created[WlWorklog].append(worklog.id)
            assert worklog.worklog_no.startswith("WL-")

            submitted = await worklog_service.submit(session, worklog.id, member.id)
            await session.commit()
            assert submitted.status == WorklogStatus.SUBMITTED
            assert submitted.late_days == 0

            # 1.1 一人一天可多条：同一天再填一条（绑定项目），累计工时告警但不拦截
            second = await worklog_service.save_draft(
                session,
                member_ctx,
                log_date=_TODAY,
                project_id=project.id,
                task_id=task.id,
                total_hours=3,
                content="继续联调",
            )
            created[WlWorklog].append(second.id)
            assert second.id != worklog.id
            second_submitted = await worklog_service.submit(session, second.id, member.id)
            await session.commit()
            assert second_submitted.status == WorklogStatus.SUBMITTED
            summary = await worklog_service.day_summary(
                session, user_id=member.id, log_date=_TODAY
            )
            assert summary["logCount"] == 2
            assert float(summary["totalHours"]) == 9  # type: ignore[arg-type]
            assert summary["overWarn"] is True
            assert "8" in str(summary["warning"])

            # 1.2 超过补填窗口（默认 5 天）拒绝保存
            with pytest.raises(BizRuleError):
                await worklog_service.save_draft(
                    session,
                    member_ctx,
                    log_date=(date.today() - timedelta(days=6)).isoformat(),
                    project_id=project.id,
                    total_hours=1,
                )

            # 2. 确认：回填任务工时与进度
            confirmed = await worklog_service.confirm(session, worklog.id, pm.id)
            await session.commit()
            assert confirmed.status == WorklogStatus.CONFIRMED
            await session.refresh(task)
            assert float(task.actual_hours) == 6
            assert float(task.progress) == 50

            # 3. 撤销确认：工时回滚
            await worklog_service.unconfirm(session, worklog.id, pm.id)
            await session.commit()
            await session.refresh(task)
            assert float(task.actual_hours) == 0

            await worklog_service.confirm(session, worklog.id, pm.id)
            await session.commit()
            await session.refresh(task)
            assert float(task.actual_hours) == 6

            # 4. 逾期补填 → 需审批
            late = await worklog_service.save_draft(
                session,
                member_ctx,
                log_date=_LATE_DAY,
                total_hours=2,
                content="补填",
                items=[{"projectId": project.id, "taskId": task.id, "hours": 2}],
            )
            created[WlWorklog].append(late.id)
            late_submitted = await worklog_service.submit(session, late.id, member.id)
            await session.commit()
            assert late_submitted.status == WorklogStatus.PENDING_APPROVE
            assert late_submitted.late_days == 5
            assert (await worklog_service.approve_late(session, late.id, pm.id)).status == (
                WorklogStatus.SUBMITTED
            )
            await session.commit()

            # 5. 可见性：同项目组成员可见；同部门非同项目不可见
            assert await worklog_service.can_view(session, member_ctx, worklog) is True
            assert await worklog_service.can_view(session, mate_ctx, worklog) is False
            await project_service.add_member(session, project.id, mate.id, dept.id, "MEMBER")
            await session.commit()
            assert await worklog_service.can_view(session, mate_ctx, worklog) is True

            # 6. 评论与催办
            comment = await worklog_service.add_comment(
                session, worklog.id, _context(pm, dept.id), "辛苦了"
            )
            created[WlComment].append(comment.id)
            reminder = await worklog_service.create_reminder(
                session, user_id=member.id, log_date=_TODAY, remind_by=pm.id, content="请补填"
            )
            created[WlReminder].append(reminder.id)
            await session.commit()

            # 7. 统计：填写率与及时率
            stats = await worklog_service.stats(
                session,
                user_id=member.id,
                date_from=(date.today() - timedelta(days=6)).isoformat(),
                date_to=_TODAY,
            )
            assert stats["submittedDays"] == 2
            assert stats["fillRate"] > 0

            # 8. 明细与列表
            items = await worklog_service.list_items(session, worklog.id)
            assert len(items) == 1
            rows = await worklog_service.list_worklogs(session, user_ids=[member.id])
            assert any(row.id == worklog.id for row in rows)
        finally:
            for model, ids in created.items():
                if ids:
                    await session.execute(delete(model).where(model.id.in_(ids)))
            risk_rows = await session.execute(
                select(PrjRisk.id).where(PrjRisk.title.like(f"日志风险%"))
            )
            risk_ids = risk_rows.scalars().all()
            if risk_ids:
                await session.execute(delete(PrjRisk).where(PrjRisk.id.in_(risk_ids)))
            await session.commit()
