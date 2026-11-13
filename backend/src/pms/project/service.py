"""项目周期服务：立项、状态机、阶段/里程碑/任务、进度重算（设计稿 05）。"""

from __future__ import annotations

import json
from datetime import date
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ConflictError, ForbiddenError, NotFoundError
from pms.common.logging import get_logger
from pms.common.snowflake import next_id
from pms.core.context import AuthContext
from pms.notice import mail as mail_service
from pms.project.models import (
    PrjAttachment,
    PrjBaseline,
    PrjDirector,
    PrjMember,
    PrjMilestone,
    PrjProject,
    PrjRisk,
    PrjStage,
    PrjTask,
)
from pms.project.progress import StageProgress, TaskProgress, project_progress, stage_progress
from pms.project.state import (
    MilestoneStatus,
    ProjectStatus,
    TaskStatus,
    assert_task_transit,
    assert_transit,
)
from pms.system.config_service import ConfigService

_DEFAULT_PREFIX: Final[str] = "PRJ"
_BASELINE_VERSION: Final[str] = "V1.0"

logger = get_logger(__name__)

_PROJECT_STATUS_TEXT: Final[dict[str, str]] = {
    "DRAFT": "草稿",
    "APPROVING": "审批中",
    "APPROVED": "已立项",
    "IN_PROGRESS": "进行中",
    "SUSPENDED": "已挂起",
    "COMPLETED": "已完成",
    "ACCEPTED": "已验收",
    "TERMINATED": "已终止",
    "CLOSED": "已关闭",
}


async def _notify_project(
    session: AsyncSession,
    event_code: str,
    project: PrjProject,
    operator_id: int = 0,
    reason: str = "",
) -> None:
    """发送项目相关邮件（仅入队，失败不影响主流程）。"""
    try:
        if event_code == "PROJECT_SUBMITTED":
            receivers = await mail_service.role_user_ids(session, ("PMO", "ADMIN"))
            receivers.add(int(project.pm_id or 0))
        else:
            receivers = await mail_service.project_recipients(session, project.id)
        await mail_service.notify_event(
            session,
            event_code,
            biz_type="PROJECT",
            biz_id=project.id,
            operator_id=operator_id,
            user_ids=receivers,
            context={
                "project": {
                    "name": project.project_name,
                    "code": project.project_code,
                    "status": _PROJECT_STATUS_TEXT.get(project.status, project.status),
                    "amount": f"{float(project.contract_amount or 0):,.2f}",
                    "approvalLevel": f"L{project.approval_level or 1}",
                },
                "operator": {"name": await mail_service.user_name(session, operator_id)},
                "reason": reason,
                "time": date.today().isoformat(),
                "link": "/projects",
            },
        )
    except Exception:  # noqa: BLE001 - 邮件失败不影响业务事务
        logger.exception("项目邮件通知入队失败：%s %s", event_code, project.id)


async def next_project_code(session: AsyncSession, when: date | None = None) -> str:
    """生成项目编码 `PRJ-2026-0001`（前缀来自参数 `project.code.prefix`）。"""
    config = ConfigService(session)
    prefix = (await config.get_str("project.code.prefix")) or _DEFAULT_PREFIX
    year = (when or date.today()).year
    pattern = f"{prefix}-{year}-%"
    stmt = select(func.count(PrjProject.id)).where(
        PrjProject.deleted == 0, PrjProject.project_code.like(pattern)
    )
    result = await session.execute(stmt)
    serial = int(result.scalar_one()) + 1
    return f"{prefix}-{year}-{serial:04d}"


async def resolve_approval_level(session: AsyncSession, amount: float) -> int:
    """按合同金额确定立项审批层级（阈值来自系统参数）。"""
    config = ConfigService(session)
    level3 = await config.get_int("approval.project.amountL3")
    level2 = await config.get_int("approval.project.amountL2")
    if amount >= level3:
        return 3
    if amount >= level2:
        return 2
    return 1


async def create_project(
    session: AsyncSession,
    context: AuthContext,
    *,
    project_name: str,
    dept_id: int,
    pm_id: int,
    project_type: str = "DEV",
    secret_level: str = "INTERNAL",
    sponsor_id: int = 0,
    customer_id: int | None = None,
    opportunity_id: int | None = None,
    contract_amount: float = 0,
    plan_start: str | None = None,
    plan_end: str | None = None,
    remark: str = "",
    members: list[dict[str, object]] | None = None,
) -> PrjProject:
    """创建项目草稿（立项来源：手工或商机转化），可同时带入项目组成员。

    实现说明：负责人（PM）自动入组；`members` 每项形如
    `{"userId": 1, "deptId": 0, "roleInProject": "MEMBER", "allocation": 100}`，
    重复的成员自动跳过，不因重复而失败。
    """
    project = PrjProject(
        project_code=await next_project_code(session),
        project_name=project_name,
        project_type=project_type,
        secret_level=secret_level,
        dept_id=dept_id,
        pm_id=pm_id,
        sponsor_id=sponsor_id or context.user_id,
        customer_id=customer_id,
        opportunity_id=opportunity_id,
        contract_amount=contract_amount,
        plan_start=plan_start,
        plan_end=plan_end,
        status=ProjectStatus.DRAFT,
        create_by=context.user_id,
        remark=remark,
    )
    session.add(project)
    await session.flush()
    if pm_id:
        await ensure_member(session, project.id, pm_id, 0, role_in_project="PM")
    if members:
        await add_members(session, project.id, members)
    return project


async def ensure_member(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    dept_id: int = 0,
    role_in_project: str = "MEMBER",
    allocation: float = 100,
) -> PrjMember:
    """幂等入组：已是成员则原样返回，否则新增（供立项/变更/转让使用）。"""
    stmt = select(PrjMember).where(
        PrjMember.project_id == project_id,
        PrjMember.user_id == user_id,
        PrjMember.deleted == 0,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    return await add_member(
        session,
        project_id,
        user_id,
        dept_id or await _user_dept_id(session, user_id),
        role_in_project=role_in_project,
        allocation=allocation,
    )


async def _user_dept_id(session: AsyncSession, user_id: int) -> int:
    """取用户所属部门（用于成员记录冗余部门）。"""
    from pms.org.models import SysUser

    result = await session.execute(
        select(SysUser.dept_id).where(SysUser.id == user_id, SysUser.deleted == 0)
    )
    return int(result.scalar_one_or_none() or 0)


async def add_members(
    session: AsyncSession, project_id: int, members: list[dict[str, object]]
) -> list[PrjMember]:
    """批量添加项目成员（重复成员跳过，用户不存在抛 `NotFoundError`）。"""
    added: list[PrjMember] = []
    for item in members:
        user_id = int(item.get("userId") or 0)  # type: ignore[arg-type]
        if not user_id:
            continue
        dept_id = int(item.get("deptId") or 0) or await _user_dept_id(session, user_id)
        if await is_member(session, project_id, user_id):
            continue
        added.append(
            await add_member(
                session,
                project_id,
                user_id,
                dept_id,
                role_in_project=str(item.get("roleInProject") or "MEMBER"),
                allocation=float(item.get("allocation") or 100),  # type: ignore[arg-type]
            )
        )
    return added


async def change_project_pm(
    session: AsyncSession, project_id: int, pm_id: int, operator_id: int = 0
) -> PrjProject:
    """变更项目负责人，并自动把新负责人加入项目组（角色 PM）。"""
    from pms.org.models import SysUser

    project = await _get_project(session, project_id)
    if pm_id:
        user = await session.get(SysUser, pm_id)
        if user is None or user.deleted != 0:
            raise NotFoundError("用户不存在")
    project.pm_id = pm_id
    project.update_by = operator_id
    await session.flush()
    if pm_id:
        # 已是成员时提升组内角色为 PM，避免「负责人却是普通成员」
        member = await ensure_member(session, project_id, pm_id, 0, role_in_project="PM")
        if member.role_in_project != "PM":
            member.role_in_project = "PM"
            await session.flush()
    return project


async def remove_member(
    session: AsyncSession, project_id: int, member_id: int, operator_id: int = 0
) -> None:
    """移出项目成员（软删）；不允许移出当前项目负责人。"""
    member = await session.get(PrjMember, member_id)
    if member is None or member.deleted != 0 or member.project_id != project_id:
        raise NotFoundError("成员不存在")
    project = await _get_project(session, project_id)
    if member.user_id == project.pm_id:
        raise ConflictError("项目负责人不可移出，请先变更负责人")
    member.deleted = 1
    member.update_by = operator_id
    await session.flush()


async def submit_for_approval(
    session: AsyncSession, project_id: int, operator_id: int = 0
) -> PrjProject:
    """提交立项审批：按金额确定审批层级并进入 APPROVING。"""
    project = await _get_project(session, project_id)
    assert_transit(project.status, ProjectStatus.APPROVING)
    project.approval_level = await resolve_approval_level(session, float(project.contract_amount))
    project.status = ProjectStatus.APPROVING
    project.update_by = operator_id or project.create_by
    await session.flush()
    await _notify_project(session, "PROJECT_SUBMITTED", project, operator_id)
    return project


async def approve_project(session: AsyncSession, project_id: int, operator_id: int) -> PrjProject:
    """立项审批通过：进入 APPROVED 并冻结初始基线。"""
    project = await _get_project(session, project_id)
    assert_transit(project.status, ProjectStatus.APPROVED)
    project.status = ProjectStatus.APPROVED
    project.update_by = operator_id
    await session.flush()
    await freeze_baseline(session, project.id, operator_id)
    await _notify_project(session, "PROJECT_APPROVED", project, operator_id)
    return project


async def reject_project(
    session: AsyncSession, project_id: int, operator_id: int, reason: str = ""
) -> PrjProject:
    """立项驳回：回到 DRAFT。"""
    project = await _get_project(session, project_id)
    assert_transit(project.status, ProjectStatus.DRAFT)
    project.status = ProjectStatus.DRAFT
    project.update_by = operator_id
    if reason:
        project.remark = reason
    await session.flush()
    await _notify_project(session, "PROJECT_REJECTED", project, operator_id, reason)
    return project


async def change_status(
    session: AsyncSession, project_id: int, target: str, operator_id: int, reason: str = ""
) -> PrjProject:
    """通用状态流转（启动 / 挂起 / 完成 / 验收 / 关闭 / 终止）。"""
    project = await _get_project(session, project_id)
    project.status = assert_transit(project.status, target)
    project.update_by = operator_id
    if project.status == ProjectStatus.IN_PROGRESS and project.actual_start is None:
        project.actual_start = date.today().isoformat()
    if project.status == ProjectStatus.COMPLETED and project.actual_end is None:
        project.actual_end = date.today().isoformat()
    if project.status == ProjectStatus.TERMINATED:
        # 终止必须留痕：原因写在项目上，前端详情可直接展示
        project.terminate_reason = (reason or "").strip()
    await session.flush()
    await _notify_project(session, "PROJECT_STATUS_CHANGED", project, operator_id, reason)
    return project


async def freeze_baseline(
    session: AsyncSession, project_id: int, operator_id: int
) -> PrjBaseline:
    """冻结范围/进度/成本基线（立项或变更时）。"""
    stages = await list_stages(session, project_id)
    tasks = await list_tasks(session, project_id)
    content = {
        "stages": [
            {
                "id": stage.id,
                "name": stage.stage_name,
                "weight": float(stage.weight),
                "planStart": stage.plan_start,
                "planEnd": stage.plan_end,
            }
            for stage in stages
        ],
        "tasks": [
            {
                "id": task.id,
                "name": task.task_name,
                "weight": float(task.weight),
                "planHours": float(task.plan_hours),
                "planStart": task.plan_start,
                "planEnd": task.plan_end,
            }
            for task in tasks
        ],
        "progress": float(await recalc_progress(session, project_id)),
    }
    baseline = PrjBaseline(
        project_id=project_id,
        baseline_type="SCOPE",
        baseline_name="立项基线",
        version=_BASELINE_VERSION,
        # default=str：基线内容含 date 字段（阶段/任务计划日期），需可序列化
        content_json=json.dumps(content, ensure_ascii=False, default=str),
        frozen_by=operator_id,
        frozen_time=date.today().isoformat(),
        create_by=operator_id,
    )
    session.add(baseline)
    await session.flush()
    return baseline


async def recalc_progress(session: AsyncSession, project_id: int) -> float:
    """重算项目进度：任务加权 → 阶段加权 → 项目进度。"""
    stages = await list_stages(session, project_id)
    tasks = await list_tasks(session, project_id)
    by_stage: dict[int, list[TaskProgress]] = {}
    for task in tasks:
        by_stage.setdefault(task.stage_id, []).append(
            TaskProgress(weight=float(task.weight), progress=float(task.progress))
        )
    stage_inputs = [
        StageProgress(
            weight=float(stage.weight),
            progress=(
                stage_progress(by_stage.get(stage.id, []))
                if stage.id in by_stage
                else float(stage.progress)
            ),
        )
        for stage in stages
    ]
    value = project_progress(stage_inputs)
    project = await _get_project(session, project_id)
    project.progress = value
    for stage in stages:
        if stage.id in by_stage:
            stage.progress = stage_progress(by_stage[stage.id])
            # 任务有了进度，阶段自动进入「进行中」；完成阶段仍需人工点击（要校验交付文档）
            if stage.progress > 0 and stage.status == "NOT_STARTED":
                stage.status = "IN_PROGRESS"
    await session.flush()
    return value


async def add_member(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    dept_id: int,
    role_in_project: str = "MEMBER",
    allocation: float = 100,
) -> PrjMember:
    """添加项目成员（重复加入抛冲突）。"""
    stmt = select(PrjMember).where(
        PrjMember.project_id == project_id,
        PrjMember.user_id == user_id,
        PrjMember.deleted == 0,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise ConflictError("该用户已是项目成员")
    member = PrjMember(
        project_id=project_id,
        user_id=user_id,
        dept_id=dept_id,
        role_in_project=role_in_project,
        allocation=allocation,
        join_date=date.today().isoformat(),
    )
    session.add(member)
    await session.flush()
    return member


async def list_members(session: AsyncSession, project_id: int) -> list[PrjMember]:
    """项目成员列表。"""
    stmt = (
        select(PrjMember)
        .where(PrjMember.project_id == project_id, PrjMember.deleted == 0)
        .order_by(PrjMember.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def is_member(session: AsyncSession, project_id: int, user_id: int) -> bool:
    """判断是否项目成员。"""
    stmt = select(PrjMember.id).where(
        PrjMember.project_id == project_id,
        PrjMember.user_id == user_id,
        PrjMember.deleted == 0,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def create_stage(
    session: AsyncSession,
    project_id: int,
    stage_name: str,
    weight: float = 0,
    seq: int = 1,
    plan_start: str | None = None,
    plan_end: str | None = None,
) -> PrjStage:
    """创建阶段。"""
    stage = PrjStage(
        project_id=project_id,
        stage_name=stage_name,
        weight=weight,
        seq=seq,
        plan_start=plan_start,
        plan_end=plan_end,
    )
    session.add(stage)
    await session.flush()
    return stage


async def list_stages(session: AsyncSession, project_id: int) -> list[PrjStage]:
    """阶段列表（按序号）。"""
    stmt = (
        select(PrjStage)
        .where(PrjStage.project_id == project_id, PrjStage.deleted == 0)
        .order_by(PrjStage.seq, PrjStage.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_task(
    session: AsyncSession,
    project_id: int,
    task_name: str,
    stage_id: int = 0,
    owner_id: int = 0,
    parent_id: int = 0,
    weight: float = 0,
    plan_hours: float = 0,
    plan_start: str | None = None,
    plan_end: str | None = None,
    priority: str = "MEDIUM",
) -> PrjTask:
    """创建 WBS 任务。"""
    task = PrjTask(
        task_code=f"T{next_id() % 100000:05d}",
        project_id=project_id,
        stage_id=stage_id,
        parent_id=parent_id,
        task_name=task_name,
        owner_id=owner_id,
        weight=weight,
        plan_hours=plan_hours,
        plan_start=plan_start,
        plan_end=plan_end,
        priority=priority,
    )
    session.add(task)
    await session.flush()
    return task


async def list_tasks(session: AsyncSession, project_id: int) -> list[PrjTask]:
    """任务列表。"""
    stmt = (
        select(PrjTask)
        .where(PrjTask.project_id == project_id, PrjTask.deleted == 0)
        .order_by(PrjTask.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_task_progress(
    session: AsyncSession,
    task_id: int,
    progress: float,
    operator_id: int,
    *,
    privileged: bool = False,
) -> PrjTask:
    """更新任务进度（0~100），并级联重算项目进度。

    权限口径：`privileged`（`project:edit`，项目维护者）可改任意任务；
    否则仅任务负责人本人可上报自己的进度，既让执行人能干活，
    又不放开任务结构/成员/阶段等项目管理能力。
    """
    task = await session.get(PrjTask, task_id)
    if task is None or task.deleted:
        raise NotFoundError("任务不存在")
    if not privileged and int(task.owner_id or 0) != operator_id:
        raise ForbiddenError("仅任务负责人可更新该任务的进度")
    if not 0 <= progress <= 100:
        raise ConflictError("进度取值应在 0~100 之间")
    task.progress = progress
    # 进度驱动状态，避免任务状态长期停在 NOT_STARTED 与实际进度不符
    if progress >= 100:
        task.status = TaskStatus.DONE
    elif progress <= 0:
        task.status = TaskStatus.NOT_STARTED
    else:
        task.status = TaskStatus.IN_PROGRESS
    task.update_by = operator_id
    await session.flush()
    await recalc_progress(session, task.project_id)
    return task


async def update_task(
    session: AsyncSession,
    project_id: int,
    task_id: int,
    *,
    task_name: str | None = None,
    stage_id: int | None = None,
    owner_id: int | None = None,
    weight: float | None = None,
    plan_hours: float | None = None,
    plan_start: str | None = None,
    plan_end: str | None = None,
    priority: str | None = None,
    operator_id: int = 0,
) -> PrjTask:
    """编辑任务（名称/阶段/负责人/权重/工时/计划起止/优先级）。"""
    task = await session.get(PrjTask, task_id)
    if task is None or task.deleted or task.project_id != project_id:
        raise NotFoundError("任务不存在")
    if task_name is not None:
        task.task_name = task_name
    if stage_id is not None:
        task.stage_id = stage_id
    if owner_id is not None:
        task.owner_id = owner_id
    if weight is not None:
        task.weight = weight
    if plan_hours is not None:
        task.plan_hours = plan_hours
    if plan_start is not None:
        task.plan_start = plan_start or None
    if plan_end is not None:
        task.plan_end = plan_end or None
    if priority is not None:
        task.priority = priority
    task.update_by = operator_id
    await session.flush()
    return task


async def delete_task(
    session: AsyncSession, project_id: int, task_id: int, operator_id: int = 0
) -> None:
    """删除任务（软删）并重算项目进度。"""
    task = await session.get(PrjTask, task_id)
    if task is None or task.deleted or task.project_id != project_id:
        raise NotFoundError("任务不存在")
    task.deleted = 1
    task.update_by = operator_id
    await session.flush()
    await recalc_progress(session, project_id)


async def create_milestone(
    session: AsyncSession,
    project_id: int,
    milestone_name: str,
    plan_date: str,
    owner_id: int = 0,
) -> PrjMilestone:
    """创建里程碑。"""
    milestone = PrjMilestone(
        project_id=project_id,
        milestone_name=milestone_name,
        plan_date=plan_date,
        owner_id=owner_id,
    )
    session.add(milestone)
    await session.flush()
    return milestone


async def list_milestones(session: AsyncSession, project_id: int) -> list[PrjMilestone]:
    """里程碑列表。"""
    stmt = (
        select(PrjMilestone)
        .where(PrjMilestone.project_id == project_id, PrjMilestone.deleted == 0)
        .order_by(PrjMilestone.plan_date, PrjMilestone.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_stage(
    session: AsyncSession,
    project_id: int,
    stage_id: int,
    *,
    stage_name: str,
    weight: float,
    seq: int,
    plan_start: str | None,
    plan_end: str | None,
    operator_id: int = 0,
) -> PrjStage:
    """编辑阶段（名称/权重/序号/计划起止）。"""
    stage = await _get_stage(session, project_id, stage_id)
    stage.stage_name = stage_name
    stage.weight = weight
    stage.seq = seq
    stage.plan_start = plan_start
    stage.plan_end = plan_end
    stage.update_by = operator_id
    await session.flush()
    await recalc_progress(session, project_id)
    return stage


async def delete_stage(
    session: AsyncSession, project_id: int, stage_id: int, operator_id: int = 0
) -> None:
    """删除阶段（存在关联任务时拒绝，避免任务悬挂）。"""
    stage = await _get_stage(session, project_id, stage_id)
    count_stmt = select(func.count(PrjTask.id)).where(
        PrjTask.project_id == project_id,
        PrjTask.stage_id == stage_id,
        PrjTask.deleted == 0,
    )
    if int((await session.execute(count_stmt)).scalar_one()) > 0:
        raise ConflictError("该阶段下仍有任务，请先移出或删除任务")
    stage.deleted = 1
    stage.update_by = operator_id
    await session.flush()
    await recalc_progress(session, project_id)


async def change_stage_status(
    session: AsyncSession,
    project_id: int,
    stage_id: int,
    target: str,
    operator_id: int = 0,
) -> PrjStage:
    """推进阶段状态；完成前按参数校验节点交付文档（R-PRJ-06）。"""
    stage = await _get_stage(session, project_id, stage_id)
    status = assert_task_transit(stage.status, target)
    if status is TaskStatus.DONE:
        config = ConfigService(session)
        if await config.get_bool("project.stage.docRequired"):
            docs = await count_attachments(
                session, project_id, biz_type="STAGE", biz_id=stage_id
            )
            if docs <= 0:
                raise BizRuleError("阶段完成前需上传该节点的交付文档")
        stage.progress = 100
        stage.actual_end = date.today().isoformat()
    elif status is TaskStatus.IN_PROGRESS and stage.actual_start is None:
        stage.actual_start = date.today().isoformat()
    stage.status = status
    stage.update_by = operator_id
    await session.flush()
    await recalc_progress(session, project_id)
    return stage


async def update_milestone(
    session: AsyncSession,
    project_id: int,
    milestone_id: int,
    *,
    milestone_name: str,
    plan_date: str,
    owner_id: int = 0,
    operator_id: int = 0,
) -> PrjMilestone:
    """编辑里程碑。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    milestone.milestone_name = milestone_name
    milestone.plan_date = plan_date
    milestone.owner_id = owner_id
    milestone.update_by = operator_id
    await session.flush()
    return milestone


async def delete_milestone(
    session: AsyncSession, project_id: int, milestone_id: int, operator_id: int = 0
) -> None:
    """删除里程碑（软删）。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    milestone.deleted = 1
    milestone.update_by = operator_id
    await session.flush()


async def change_milestone_status(
    session: AsyncSession,
    project_id: int,
    milestone_id: int,
    target: str,
    operator_id: int = 0,
) -> PrjMilestone:
    """里程碑达成/延期/取消登记。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    status = MilestoneStatus(target)
    if status is MilestoneStatus.PENDING and milestone.status not in {
        MilestoneStatus.DELAYED,
        MilestoneStatus.CANCELLED,
    }:
        raise ConflictError("仅延期或取消的里程碑可恢复为待达成")
    milestone.status = status
    if status is MilestoneStatus.REACHED:
        milestone.actual_date = date.today().isoformat()
        milestone.delay_days = _delay_days(milestone.plan_date, milestone.actual_date)
    elif status is MilestoneStatus.PENDING:
        milestone.actual_date = None
        milestone.delay_days = 0
    milestone.update_by = operator_id
    await session.flush()
    return milestone


def _delay_days(plan_date: object | None, actual_date: object | None) -> int:
    """实际达成日晚于计划日期时返回延期天数。"""
    if not plan_date or not actual_date:
        return 0
    plan = date.fromisoformat(str(plan_date))
    actual = date.fromisoformat(str(actual_date))
    return max((actual - plan).days, 0)


async def list_directors(session: AsyncSession, project_id: int) -> list[PrjDirector]:
    """项目总监列表。"""
    stmt = (
        select(PrjDirector)
        .where(PrjDirector.project_id == project_id, PrjDirector.deleted == 0)
        .order_by(PrjDirector.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def director_ids(session: AsyncSession, project_id: int) -> list[int]:
    """项目总监用户 ID 列表（供变更审批链会签使用）。"""
    rows = await list_directors(session, project_id)
    return [row.user_id for row in rows if row.user_id]


async def is_director(session: AsyncSession, project_id: int, user_id: int) -> bool:
    """判断是否该项目总监。"""
    stmt = select(PrjDirector.id).where(
        PrjDirector.project_id == project_id,
        PrjDirector.user_id == user_id,
        PrjDirector.deleted == 0,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def set_directors(
    session: AsyncSession, project_id: int, user_ids: list[int], operator_id: int = 0
) -> list[PrjDirector]:
    """整体设置项目总监（多人为会签）；被指派者自动入组为 DIRECTOR 角色。"""
    from pms.org.models import SysUser

    project = await _get_project(session, project_id)
    targets = sorted({int(item) for item in user_ids if int(item) > 0})
    if targets:
        rows = await session.execute(
            select(SysUser.id).where(
                SysUser.id.in_(targets), SysUser.deleted == 0, SysUser.status == "ENABLED"
            )
        )
        valid = set(rows.scalars().all())
        missing = [str(item) for item in targets if item not in valid]
        if missing:
            raise NotFoundError(f"用户不存在或已停用：{', '.join(missing)}")

    existing = await list_directors(session, project_id)
    existing_by_user = {row.user_id: row for row in existing}
    removed: list[int] = []
    for user_id, row in existing_by_user.items():
        if user_id not in targets:
            row.deleted = 1
            row.update_by = operator_id
            removed.append(user_id)
    for user_id in targets:
        if user_id in existing_by_user:
            continue
        session.add(
            PrjDirector(
                project_id=project_id,
                user_id=user_id,
                assigned_by=operator_id,
                create_by=operator_id,
            )
        )
        await ensure_member(session, project_id, user_id, 0, role_in_project="DIRECTOR")
    # 取消总监时同步回收「仅因总监身份自动入组」的成员，保持两边一致
    for user_id in removed:
        await _detach_director_member(session, project, user_id, operator_id)
    await session.flush()
    return await list_directors(session, project_id)


async def _detach_director_member(
    session: AsyncSession, project: PrjProject, user_id: int, operator_id: int
) -> None:
    """总监被取消后移出其自动创建的成员记录。

    只处理组内角色仍为 `DIRECTOR` 的成员：已转为开发/测试等业务角色、
    或已成为项目负责人的用户继续留在项目组，避免误删实际参与人员。
    """
    if user_id == project.pm_id:
        return
    stmt = select(PrjMember).where(
        PrjMember.project_id == project.id,
        PrjMember.user_id == user_id,
        PrjMember.deleted == 0,
    )
    member = (await session.execute(stmt)).scalar_one_or_none()
    if member is None or member.role_in_project != "DIRECTOR":
        return
    member.deleted = 1
    member.update_by = operator_id


async def count_attachments(
    session: AsyncSession,
    project_id: int,
    *,
    biz_type: str = "",
    biz_id: int = 0,
) -> int:
    """统计项目附件数量（可按业务类型/节点过滤）。"""
    stmt = select(func.count(PrjAttachment.id)).where(
        PrjAttachment.project_id == project_id, PrjAttachment.deleted == 0
    )
    if biz_type:
        stmt = stmt.where(PrjAttachment.biz_type == biz_type)
    if biz_id:
        stmt = stmt.where(PrjAttachment.biz_id == biz_id)
    return int((await session.execute(stmt)).scalar_one())


async def _get_stage(session: AsyncSession, project_id: int, stage_id: int) -> PrjStage:
    """取项目阶段并校验归属。"""
    stage = await session.get(PrjStage, stage_id)
    if stage is None or stage.deleted or stage.project_id != project_id:
        raise NotFoundError("阶段不存在")
    return stage


async def _get_milestone(
    session: AsyncSession, project_id: int, milestone_id: int
) -> PrjMilestone:
    """取里程碑并校验归属。"""
    milestone = await session.get(PrjMilestone, milestone_id)
    if milestone is None or milestone.deleted or milestone.project_id != project_id:
        raise NotFoundError("里程碑不存在")
    return milestone


def _project_filters(
    keyword: str = "",
    status: str = "",
    dept_id: int = 0,
    pm_id: int = 0,
    health: str = "",
    member_id: int = 0,
) -> list[object]:
    """项目列表查询条件（列表与计数共用）。"""
    clauses: list[object] = []
    if keyword:
        like = f"%{keyword}%"
        clauses.append(PrjProject.project_name.like(like) | PrjProject.project_code.like(like))
    if dept_id:
        clauses.append(PrjProject.dept_id == dept_id)
    if pm_id:
        clauses.append(PrjProject.pm_id == pm_id)
    if health:
        clauses.append(PrjProject.health == health)
    if member_id:
        # 「我参与」：负责人本人 + 项目组成员（负责人变更后也会入组，这里兜住历史数据）
        joined = select(PrjMember.project_id).where(
            PrjMember.user_id == member_id, PrjMember.deleted == 0
        )
        clauses.append((PrjProject.pm_id == member_id) | PrjProject.id.in_(joined))
    if status:
        # 支持逗号分组，便于前端用一段式页签表达「进行中 = IN_PROGRESS+SUSPENDED」
        values = [item.strip() for item in status.split(",") if item.strip()]
        if len(values) > 1:
            clauses.append(PrjProject.status.in_(values))
        elif values:
            clauses.append(PrjProject.status == values[0])
    return clauses


async def count_projects(
    session: AsyncSession,
    keyword: str = "",
    status: str = "",
    *,
    dept_id: int = 0,
    pm_id: int = 0,
    health: str = "",
    member_id: int = 0,
) -> int:
    """项目总数（`member_id` 用于「我参与」视角）。"""
    stmt = select(func.count(PrjProject.id)).where(
        PrjProject.deleted == 0,
        *_project_filters(
            keyword, status, dept_id, pm_id, health, member_id=member_id
        ),
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_projects(
    session: AsyncSession,
    offset: int,
    limit: int,
    keyword: str = "",
    status: str = "",
    *,
    dept_id: int = 0,
    pm_id: int = 0,
    health: str = "",
    member_id: int = 0,
) -> list[PrjProject]:
    """项目分页列表（可见性过滤在 API 层用 `project_visible` 完成）。"""
    stmt = select(PrjProject).where(
        PrjProject.deleted == 0,
        *_project_filters(
            keyword, status, dept_id, pm_id, health, member_id=member_id
        ),
    )
    stmt = stmt.order_by(PrjProject.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_project(session: AsyncSession, project_id: int) -> PrjProject:
    """按 ID 取项目，不存在抛异常。"""
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        raise NotFoundError("项目不存在")
    return project


async def get_project(session: AsyncSession, project_id: int) -> PrjProject:
    """取项目（对外）。"""
    return await _get_project(session, project_id)


# ------------------------------ 基线 ------------------------------

async def list_baselines(session: AsyncSession, project_id: int) -> list[PrjBaseline]:
    """项目基线列表：立项基线与各次变更基线，按冻结顺序倒序。"""
    stmt = (
        select(PrjBaseline)
        .where(PrjBaseline.project_id == project_id, PrjBaseline.deleted == 0)
        .order_by(PrjBaseline.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_baseline(
    session: AsyncSession, project_id: int, baseline_id: int
) -> PrjBaseline:
    """取单条基线，校验归属项目。"""
    baseline = await session.get(PrjBaseline, baseline_id)
    if baseline is None or baseline.deleted or baseline.project_id != project_id:
        raise NotFoundError("基线不存在")
    return baseline


# ------------------------------ 风险 / 问题 ------------------------------

_RISK_TYPES: Final[frozenset[str]] = frozenset({"RISK", "ISSUE"})
_RISK_LEVELS: Final[frozenset[str]] = frozenset({"HIGH", "MEDIUM", "LOW"})
_RISK_STATUSES: Final[frozenset[str]] = frozenset({"OPEN", "CLOSED"})


def _risk_filters(risk_type: str = "", status: str = "") -> list[object]:
    """风险台账查询条件（列表与计数共用）。"""
    clauses: list[object] = []
    if risk_type:
        clauses.append(PrjRisk.risk_type == risk_type)
    if status:
        clauses.append(PrjRisk.status == status)
    return clauses


async def list_risks(
    session: AsyncSession, project_id: int, *, risk_type: str = "", status: str = ""
) -> list[PrjRisk]:
    """项目风险与问题列表（按等级、截止日排序，高风险在前）。"""
    stmt = (
        select(PrjRisk)
        .where(
            PrjRisk.project_id == project_id,
            PrjRisk.deleted == 0,
            *_risk_filters(risk_type, status),
        )
        .order_by(PrjRisk.status, PrjRisk.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_risk(session: AsyncSession, project_id: int, risk_id: int) -> PrjRisk:
    """取单条风险，校验归属项目。"""
    risk = await session.get(PrjRisk, risk_id)
    if risk is None or risk.deleted or risk.project_id != project_id:
        raise NotFoundError("风险条目不存在")
    return risk


async def create_risk(
    session: AsyncSession,
    project_id: int,
    operator_id: int,
    *,
    risk_type: str = "RISK",
    title: str,
    description: str = "",
    level: str = "MEDIUM",
    probability: float = 0,
    impact: str = "",
    strategy: str = "",
    owner_id: int = 0,
    due_date: str | None = None,
) -> PrjRisk:
    """登记风险或问题。"""
    kind = (risk_type or "RISK").upper()
    if kind not in _RISK_TYPES:
        raise BizRuleError("类型只能是 RISK（风险）或 ISSUE（问题）")
    if not title.strip():
        raise BizRuleError("请填写风险标题")
    grade = (level or "MEDIUM").upper()
    if grade not in _RISK_LEVELS:
        raise BizRuleError("等级只能是 HIGH / MEDIUM / LOW")
    if not 0 <= float(probability) <= 100:
        raise BizRuleError("发生概率应在 0~100 之间")
    risk = PrjRisk(
        project_id=project_id,
        risk_type=kind,
        title=title.strip(),
        description=description,
        level=grade,
        probability=float(probability),
        impact=impact,
        strategy=strategy,
        owner_id=owner_id,
        due_date=due_date or None,
        status="OPEN",
        create_by=operator_id,
    )
    session.add(risk)
    await session.flush()
    return risk


async def update_risk(
    session: AsyncSession,
    project_id: int,
    risk_id: int,
    operator_id: int,
    *,
    risk_type: str | None = None,
    title: str | None = None,
    description: str | None = None,
    level: str | None = None,
    probability: float | None = None,
    impact: str | None = None,
    strategy: str | None = None,
    owner_id: int | None = None,
    due_date: str | None = None,
) -> PrjRisk:
    """编辑风险条目（不改状态，状态走 `change_risk_status`）。"""
    risk = await _get_risk(session, project_id, risk_id)
    if risk_type is not None:
        kind = risk_type.upper()
        if kind not in _RISK_TYPES:
            raise BizRuleError("类型只能是 RISK（风险）或 ISSUE（问题）")
        risk.risk_type = kind
    if title is not None:
        if not title.strip():
            raise BizRuleError("请填写风险标题")
        risk.title = title.strip()
    if level is not None:
        grade = level.upper()
        if grade not in _RISK_LEVELS:
            raise BizRuleError("等级只能是 HIGH / MEDIUM / LOW")
        risk.level = grade
    if probability is not None:
        if not 0 <= float(probability) <= 100:
            raise BizRuleError("发生概率应在 0~100 之间")
        risk.probability = float(probability)
    if description is not None:
        risk.description = description
    if impact is not None:
        risk.impact = impact
    if strategy is not None:
        risk.strategy = strategy
    if owner_id is not None:
        risk.owner_id = owner_id
    if due_date is not None:
        risk.due_date = due_date or None
    risk.update_by = operator_id
    await session.flush()
    return risk


async def change_risk_status(
    session: AsyncSession, project_id: int, risk_id: int, target: str, operator_id: int
) -> PrjRisk:
    """关闭 / 重新打开风险；关闭时记录关闭日期。"""
    risk = await _get_risk(session, project_id, risk_id)
    status = (target or "").upper()
    if status not in _RISK_STATUSES:
        raise BizRuleError("状态只能是 OPEN（开放）或 CLOSED（已关闭）")
    risk.status = status
    risk.close_time = date.today().isoformat() if status == "CLOSED" else None
    risk.update_by = operator_id
    await session.flush()
    return risk


async def delete_risk(
    session: AsyncSession, project_id: int, risk_id: int, operator_id: int
) -> None:
    """删除风险条目（软删）。"""
    risk = await _get_risk(session, project_id, risk_id)
    risk.deleted = 1
    risk.update_by = operator_id
    await session.flush()
