"""端到端冒烟：立项 → 变更申请 → 六维评估自动定级 → 审批 → 基线联动 → 执行关闭。

需要真实 MySQL（`.env`），用例自带数据清理，可重复执行。
"""

from __future__ import annotations

import time
from typing import Final

import pytest
from sqlalchemy import delete, select

from pms.change import service as change_service
from pms.change.models import ChgApproval, ChgImpact, ChgItem, ChgRequest
from pms.core.context import AuthContext
from pms.core.database import get_session_factory
from pms.org.models import SysDept, SysUser
from pms.project import service as project_service
from pms.project.models import (
    PrjBaseline,
    PrjDirector,
    PrjMilestone,
    PrjProject,
    PrjStage,
    PrjTask,
)
from pms.system.config_service import ConfigService

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time()) % 100000)


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


async def test_change_approval_and_baseline_flow() -> None:
    """L2 变更全链路：定级 → 两级审批 → 基线 v2 + 计划顺延。"""
    factory = get_session_factory()
    created: dict[type, list[int]] = {
        SysDept: [],
        SysUser: [],
        PrjProject: [],
        PrjDirector: [],
        PrjStage: [],
        PrjTask: [],
        PrjMilestone: [],
        PrjBaseline: [],
        ChgRequest: [],
        ChgImpact: [],
        ChgItem: [],
        ChgApproval: [],
    }
    async with factory() as session:
        try:
            await ConfigService(session).seed_defaults()
            await session.commit()

            dept = SysDept(parent_id=0, dept_name=f"变更部门{_SUFFIX}", dept_code=f"CH{_SUFFIX}", path="/", level=1)
            session.add(dept)
            await session.flush()
            created[SysDept].append(dept.id)

            pm = SysUser(username=f"chg_pm_{_SUFFIX}", real_name="项目经理", dept_id=dept.id, password_hash="x")
            director1 = SysUser(username=f"chg_dir1_{_SUFFIX}", real_name="总监甲", dept_id=dept.id, password_hash="x")
            director2 = SysUser(username=f"chg_dir2_{_SUFFIX}", real_name="总监乙", dept_id=dept.id, password_hash="x")
            pmo = SysUser(username=f"chg_pmo_{_SUFFIX}", real_name="PMO", dept_id=dept.id, password_hash="x")
            session.add_all([pm, director1, director2, pmo])
            await session.flush()
            created[SysUser].extend([pm.id, director1.id, director2.id, pmo.id])
            await session.commit()

            context = _context(pm, dept.id)

            # 1. 立项并冻结 V1.0 基线
            project = await project_service.create_project(
                session,
                context,
                project_name=f"变更冒烟项目{_SUFFIX}",
                dept_id=dept.id,
                pm_id=pm.id,
                contract_amount=100000,
                plan_start="2026-11-01",
                plan_end="2026-12-31",
            )
            created[PrjProject].append(project.id)
            await project_service.submit_for_approval(session, project.id)
            await project_service.approve_project(session, project.id, pm.id)
            # 指派两名项目总监（会签）
            directors = await project_service.set_directors(
                session, project.id, [director1.id, director2.id], operator_id=pm.id
            )
            created[PrjDirector].extend(row.id for row in directors)
            assert await project_service.is_director(session, project.id, director1.id)
            task = await project_service.create_task(
                session, project.id, "编码", stage_id=0, plan_hours=100, plan_start="2026-11-01", plan_end="2026-12-20"
            )
            created[PrjTask].append(task.id)
            milestone = await project_service.create_milestone(session, project.id, "提测", "2026-12-20")
            created[PrjMilestone].append(milestone.id)
            await session.commit()

            # 2. 变更申请 → 提交
            request = await change_service.create_request(
                session, context, project_id=project.id, change_type="SCHEDULE", title="延期 5 天"
            )
            created[ChgRequest].append(request.id)
            assert request.status == "DRAFT"
            assert request.request_code.startswith("CR-")

            submitted = await change_service.submit(session, request.id, pm.id)
            assert submitted.status == "SUBMITTED"

            # 3. 六维评估：工期 5 天（占比 8.3% < 10%）→ L2
            assessed = await change_service.assess(
                session,
                request.id,
                pm.id,
                impacts=[
                    {"dimension": "SCHEDULE", "scheduleImpactDays": 5, "newEndDate": "2027-01-05"},
                    {"dimension": "COST", "costImpactAmount": 1000},
                    {"dimension": "RISK", "riskLevel": "LOW"},
                ],
                items=[
                    {"itemType": "TASK", "action": "UPDATE", "bizId": task.id, "fieldName": "planHours", "afterValue": "120"},
                    {"itemType": "MILESTONE", "action": "UPDATE", "bizId": milestone.id, "fieldName": "planDate", "afterValue": "2027-01-05"},
                ],
                pmo_id=pmo.id,
            )
            await session.commit()
            assert assessed.level == "L2", "工期 5 天且占比未超阈值应定级 L2"
            assert assessed.status == "ASSESSED"
            assert float(assessed.schedule_impact_days) == 5

            approves = await change_service.list_approvals(session, request.id)
            assert [row.node_role for row in approves] == ["DIRECTOR", "DIRECTOR", "PMO"]
            assert [row.seq for row in approves] == [1, 1, 2]
            assert {row.approver_id for row in approves[:2]} == {director1.id, director2.id}

            # 4. 非审批人不能审批；PMO 也不能代替项目总监会签
            from pms.common.exceptions import ForbiddenError

            with pytest.raises(ForbiddenError):
                await change_service.approve(session, request.id, pm.id, "越权审批")
            with pytest.raises(ForbiddenError):
                await change_service.approve(
                    session, request.id, pmo.id, "代签总监", is_privileged=True
                )

            # 5. 会签：两名总监都通过后才进入 PMO 节点
            await change_service.approve(session, request.id, director1.id, "同意")
            await session.commit()
            assert (await change_service.get_request(session, request.id)).status == "ASSESSED"

            await change_service.approve(session, request.id, director2.id, "同意")
            await session.commit()
            assert (await change_service.get_request(session, request.id)).status == "ASSESSED", (
                "总监会签完成后仍需 PMO 审批"
            )

            await change_service.approve(session, request.id, pmo.id, "同意")
            await session.commit()

            approved = await change_service.get_request(session, request.id)
            assert approved.status == "APPROVED"
            assert approved.baseline_before == "V1.0"
            assert approved.baseline_after == "V2.0"

            # 6. 基线联动：影响项已应用、计划顺延 5 天
            items = await change_service.list_items(session, request.id)
            assert all(item.applied for item in items)
            await session.refresh(project)
            assert str(project.plan_end) == "2027-01-05"
            await session.refresh(task)
            assert float(task.plan_hours) == 120
            await session.refresh(milestone)
            assert str(milestone.plan_date) == "2027-01-05"

            baseline_rows = await session.execute(
                select(PrjBaseline.id).where(PrjBaseline.project_id == project.id)
            )
            created[PrjBaseline].extend(baseline_rows.scalars().all())

            # 7. 执行 → 验证 → 关闭
            assert (await change_service.start_execute(session, request.id, pm.id)).status == "EXECUTING"
            assert (await change_service.submit_verify(session, request.id, pm.id)).status == "VERIFIED"
            assert (await change_service.close(session, request.id, pmo.id)).status == "CLOSED"
            await session.commit()

            # 8. 紧急变更标记
            emergency = await change_service.create_request(
                session, context, project_id=project.id, change_type="TECH", title="紧急修复", is_emergency=True
            )
            created[ChgRequest].append(emergency.id)
            marked = await change_service.mark_emergency(session, emergency.id, pm.id)
            await session.commit()
            assert marked.is_emergency == 1
            assert marked.emergency_due is not None
        finally:
            for model, ids in created.items():
                if ids:
                    await session.execute(delete(model).where(model.id.in_(ids)))
            await session.commit()
