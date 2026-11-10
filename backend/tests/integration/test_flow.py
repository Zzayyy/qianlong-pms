"""端到端冒烟：客户 → 商机 → 赢单 → 转项目 → 阶段/任务 → 进度重算。

需要真实 MySQL（`.env` 配置），用例自带数据清理，可重复执行。
标记 `integration`，本地无库时可用 `pytest -m "not integration"` 跳过。
"""

from __future__ import annotations

import time
from typing import Final

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import ConflictError
from pms.core.database import get_session_factory
from pms.crm import service as crm_service
from pms.crm.models import CrmContact, CrmCustomer, CrmFollow, CrmOpportunity
from pms.org import service as org_service
from pms.org.models import SysDept, SysRole, SysUser, SysUserRole
from pms.project import service as project_service
from pms.project.models import (
    PrjBaseline,
    PrjMember,
    PrjMilestone,
    PrjProject,
    PrjStage,
    PrjTask,
)
from pms.system.config_service import ConfigService

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time()) % 100000)


async def _cleanup(session: AsyncSession, ids: dict[type, list[int]]) -> None:
    """按模型清理本用例创建的数据。"""
    for model, values in ids.items():
        if values:
            await session.execute(delete(model).where(model.id.in_(values)))
    await session.commit()


async def test_crm_to_project_flow() -> None:
    """CRM 转化主链路与进度加权计算。"""
    factory = get_session_factory()
    created: dict[type, list[int]] = {
        SysDept: [],
        SysUser: [],
        SysRole: [],
        SysUserRole: [],
        CrmCustomer: [],
        CrmContact: [],
        CrmOpportunity: [],
        CrmFollow: [],
        PrjProject: [],
        PrjStage: [],
        PrjTask: [],
        PrjMilestone: [],
        PrjMember: [],
        PrjBaseline: [],
    }
    async with factory() as session:
        try:
            await ConfigService(session).seed_defaults()
            await session.commit()

            dept = SysDept(parent_id=0, dept_name=f"冒烟部门{_SUFFIX}", dept_code=f"SM{_SUFFIX}", path="/", level=1)
            session.add(dept)
            await session.flush()
            created[SysDept].append(dept.id)

            user = await org_service.create_user(
                session,
                username=f"smoke_{_SUFFIX}",
                password="Smoke@12345",
                real_name="冒烟用户",
                dept_id=dept.id,
            )
            created[SysUser].append(user.id)

            role = SysRole(role_code=f"SMOKE_{_SUFFIX}", role_name="冒烟角色", data_scope="ALL")
            session.add(role)
            await session.flush()
            created[SysRole].append(role.id)

            relation = SysUserRole(user_id=user.id, role_id=role.id)
            session.add(relation)
            await session.flush()
            created[SysUserRole].append(relation.id)
            await session.commit()

            # 1. 登录
            login = await org_service.authenticate(session, f"smoke_{_SUFFIX}", "Smoke@12345")
            assert login.token and login.user_id == user.id

            context = await _context_of(session, user, dept, role)

            # 2. 客户 + 联系人
            customer = await crm_service.create_customer(
                session,
                context,
                customer_name=f"冒烟客户{_SUFFIX}",
                owner_user_id=user.id,
                owner_dept_id=dept.id,
                contact_mobile="13800001111",
                contact_email="smoke@qloffice.com",
            )
            created[CrmCustomer].append(customer.id)
            contact = await crm_service.add_contact(
                session, context, customer.id, name="张三", mobile="13800002222", is_primary=True
            )
            created[CrmContact].append(contact.id)
            # 主联系人回写客户快照，列表与抽屉数据一致
            assert customer.contact_name == "张三"
            assert customer.contact_mobile == "13800002222"

            backup = await crm_service.add_contact(session, context, customer.id, name="李四")
            created[CrmContact].append(backup.id)
            await crm_service.delete_contact(session, context, contact.id)
            # 主联系人删除后顺延下一位
            assert customer.contact_name == "李四"
            assert backup.is_primary == 1

            # 3. 商机 → 赢单
            opportunity = await crm_service.create_opportunity(
                session,
                context,
                opp_name=f"冒烟商机{_SUFFIX}",
                customer_id=customer.id,
                expect_amount=800000,
                owner_user_id=user.id,
                owner_dept_id=dept.id,
            )
            created[CrmOpportunity].append(opportunity.id)
            follow = await crm_service.add_follow(session, context, opportunity.id, content="首次沟通")
            created[CrmFollow].append(follow.id)

            await crm_service.update_stage(session, opportunity.id, "WON", operator_id=user.id)
            await session.commit()

            # 4. 商机转项目
            project = await crm_service.convert_to_project(
                session, context, opportunity.id, pm_id=user.id, plan_start="2026-11-01", plan_end="2026-12-31"
            )
            await session.commit()
            assert isinstance(project, PrjProject)
            created[PrjProject].append(project.id)
            assert project.customer_id == customer.id
            assert float(project.contract_amount) == 800000
            assert project.status == "DRAFT"
            assert opportunity.converted_project_id == project.id
            assert customer.status == "COOPERATING"

            # 5. 立项审批（金额 80 万 → 层级 2）
            submitted = await project_service.submit_for_approval(session, project.id)
            assert submitted.status == "APPROVING"
            assert submitted.approval_level == 2
            approved = await project_service.approve_project(session, project.id, user.id)
            assert approved.status == "APPROVED"

            # 6. 阶段 / 任务 / 里程碑 / 成员
            stage_a = await project_service.create_stage(session, project.id, "需求", weight=1, seq=1)
            stage_b = await project_service.create_stage(session, project.id, "开发", weight=3, seq=2)
            created[PrjStage].extend([stage_a.id, stage_b.id])
            task_a = await project_service.create_task(
                session, project.id, "需求调研", stage_id=stage_a.id, weight=1, plan_hours=40
            )
            task_b = await project_service.create_task(
                session, project.id, "编码实现", stage_id=stage_b.id, weight=1, plan_hours=120
            )
            created[PrjTask].extend([task_a.id, task_b.id])
            milestone = await project_service.create_milestone(
                session, project.id, "需求评审", "2026-11-10", owner_id=user.id
            )
            created[PrjMilestone].append(milestone.id)
            # 负责人立项即自动入组（PM），重复入组走幂等接口不报错
            members = await project_service.list_members(session, project.id)
            assert any(item.user_id == user.id and item.role_in_project == "PM" for item in members)
            with pytest.raises(ConflictError):
                await project_service.add_member(session, project.id, user.id, dept.id, "PM")
            member = await project_service.ensure_member(session, project.id, user.id, dept.id, "PM")
            created[PrjMember].extend([item.id for item in members])
            # 负责人不可直接移出，需先变更负责人
            with pytest.raises(ConflictError):
                await project_service.remove_member(session, project.id, member.id)
            await session.commit()

            # 7. 进度：需求 100%、开发 50% → 阶段权重 1:3 → 62.5
            await project_service.update_task_progress(session, task_a.id, 100, user.id)
            await project_service.update_task_progress(session, task_b.id, 50, user.id)
            progress = await project_service.recalc_progress(session, project.id)
            await session.commit()
            assert round(progress, 2) == 62.5

            # 8. 状态流转
            started = await project_service.change_status(session, project.id, "IN_PROGRESS", user.id)
            assert started.status == "IN_PROGRESS"
            await session.commit()

            # 9. 基线已冻结
            baselines = await session.execute(
                select(PrjBaseline).where(PrjBaseline.project_id == project.id)
            )
            baseline = baselines.scalars().first()
            assert baseline is not None
            if baseline is not None:
                created[PrjBaseline].append(baseline.id)
        finally:
            await _cleanup(session, created)


async def _context_of(session: AsyncSession, user: SysUser, dept: SysDept, role: SysRole) -> object:
    """构造用于服务层调用的精简身份上下文。"""
    from pms.core.context import AuthContext

    return AuthContext(
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        dept_id=dept.id,
        dept_path=f"/{dept.id}/",
        roles=frozenset({role.role_code}),
        permissions=frozenset(),
        visible_dept_ids=None,
        manager_depth=1,
    )
