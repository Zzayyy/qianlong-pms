"""项目周期接口：立项、审批、状态流转、阶段/里程碑/任务/成员（设计稿 09 §2.3）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import ForbiddenError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import (
    Pagination,
    get_pagination,
    get_session,
    load_permissions,
    require_permissions,
)
from pms.org.models import SysUser
from pms.project import service
from pms.project.models import PrjProject
from pms.project.visibility import (
    can_view_project,
    ensure_project_manager,
    ensure_project_visible,
    is_project_manager,
)

router = APIRouter(prefix="/api/v1/projects", tags=["项目周期"])


async def _can_view(session: AsyncSession, context: AuthContext, project: PrjProject) -> bool:
    """项目可见性判定（设计稿 03 §4.1，参数可在后台调整）。"""
    return await can_view_project(session, context, project)


async def _user_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """批量取用户姓名（项目出参里的人名，避免前端依赖人员列表权限）。"""
    ids = {item for item in user_ids if item}
    if not ids:
        return {}
    rows = await session.execute(
        select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(ids), SysUser.deleted == 0)
    )
    return {row[0]: row[1] for row in rows.all()}


def _project_out(project: PrjProject, pm_name: str = "") -> dict[str, object]:
    """项目出参（`pmName` 随行下发，仅 `project:view` 的角色也能看到负责人姓名）。"""
    return {
        "id": project.id,
        "projectCode": project.project_code,
        "projectName": project.project_name,
        "status": project.status,
        "health": project.health,
        "progress": float(project.progress),
        "deptId": project.dept_id,
        "pmId": project.pm_id,
        "pmName": pm_name or "",
        "customerId": project.customer_id,
        "opportunityId": project.opportunity_id,
        "contractAmount": float(project.contract_amount),
        "planStart": project.plan_start,
        "planEnd": project.plan_end,
        "approvalLevel": project.approval_level,
        "terminateReason": project.terminate_reason,
    }


class ProjectIn(BaseModel):
    """立项入参。"""

    projectName: str = Field(min_length=1, max_length=200)
    deptId: int
    pmId: int
    projectType: str = "DEV"
    secretLevel: str = "INTERNAL"
    customerId: int | None = None
    opportunityId: int | None = None
    contractAmount: float = 0
    planStart: str | None = None
    planEnd: str | None = None
    remark: str = ""
    members: list[MemberIn] = Field(default_factory=list)


class StatusIn(BaseModel):
    """状态流转入参。"""

    target: str = Field(min_length=2, max_length=32)
    reason: str = Field(default="", max_length=500)


class StageIn(BaseModel):
    """阶段入参。"""

    stageName: str = Field(min_length=1, max_length=128)
    weight: float = 0
    seq: int = 1
    planStart: str | None = None
    planEnd: str | None = None


class StageStatusIn(BaseModel):
    """阶段状态入参（NOT_STARTED / IN_PROGRESS / DONE）。"""

    target: str = Field(min_length=3, max_length=16)


class TaskIn(BaseModel):
    """任务入参。"""

    taskName: str = Field(min_length=1, max_length=200)
    stageId: int = 0
    ownerId: int = 0
    parentId: int = 0
    weight: float = 0
    planHours: float = 0
    planStart: str | None = None
    planEnd: str | None = None
    priority: str = "MEDIUM"


class ProgressIn(BaseModel):
    """任务进度入参。"""

    progress: float = Field(ge=0, le=100)


class MilestoneIn(BaseModel):
    """里程碑入参。"""

    milestoneName: str = Field(min_length=1, max_length=128)
    planDate: str
    ownerId: int = 0


class MilestoneUpdateIn(MilestoneIn):
    """里程碑编辑入参（字段同新增）。"""


class MilestoneStatusIn(BaseModel):
    """里程碑状态入参。"""

    target: str = Field(min_length=3, max_length=16)


class DirectorsIn(BaseModel):
    """项目总监设置入参（整体覆盖）。"""

    userIds: list[int] = Field(default_factory=list)


class MemberIn(BaseModel):
    """成员入参。"""

    userId: int
    deptId: int = 0
    roleInProject: str = "MEMBER"
    allocation: float = 100


class PmIn(BaseModel):
    """变更负责人入参。"""

    pmId: int


@router.post("", summary="创建项目")
async def create_project(
    body: ProjectIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:create"))],
) -> object:
    """创建项目草稿（手工立项；商机转化走 `/crm/opportunities/{id}/convert`）。"""
    project = await service.create_project(
        session,
        context,
        project_name=body.projectName,
        dept_id=body.deptId,
        pm_id=body.pmId,
        project_type=body.projectType,
        secret_level=body.secretLevel,
        customer_id=body.customerId,
        opportunity_id=body.opportunityId,
        contract_amount=body.contractAmount,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        remark=body.remark,
        members=[item.model_dump() for item in body.members],
    )
    await session.commit()
    return ok({"id": project.id, "projectCode": project.project_code})


@router.get("", summary="项目列表")
async def list_projects(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    keyword: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    deptId: Annotated[int | None, Query()] = None,
    pmId: Annotated[int | None, Query()] = None,
    health: Annotated[str, Query()] = "",
) -> object:
    """分页查询项目，**逐条按四维权限过滤**（维度 ③）。

    `status` 支持逗号分组；`deptId` / `pmId` / `health` 为可选的精确筛选。
    """
    total = await service.count_projects(
        session, keyword, status, dept_id=deptId or 0, pm_id=pmId or 0, health=health
    )
    items = await service.list_projects(
        session,
        pagination.offset,
        pagination.limit,
        keyword,
        status,
        dept_id=deptId or 0,
        pm_id=pmId or 0,
        health=health,
    )
    visible_items = [item for item in items if await _can_view(session, context, item)]
    names = await _user_names(session, {item.pm_id for item in visible_items})
    return paged(
        [_project_out(item, names.get(item.pm_id, "")) for item in visible_items],
        len(visible_items) if len(visible_items) != len(items) else total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/{project_id}", summary="项目详情")
async def project_detail(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """项目详情；不可见时返回 40302（数据越权）。

    出参附加 `canManage`：当前用户是否本项目的项目经理 / PMO，
    前端据此禁用节点、成员、总监等管理动作，避免点了才报 40301。
    """
    from pms.common.exceptions import DataForbiddenError

    project = await service.get_project(session, project_id)
    if not await _can_view(session, context, project):
        raise DataForbiddenError("无该项目访问权限")
    names = await _user_names(session, {project.pm_id})
    data = _project_out(project, names.get(project.pm_id, ""))
    data["canManage"] = await is_project_manager(session, context, project)

    # 读取详情时顺带校准健康度：单项目计算开销小，避免列表长期停留在默认 GREEN
    from pms.report import service as report_service

    health = await report_service.refresh_project_health(session, project_id)
    if str(data["health"]) != health:
        data["health"] = health
        await session.commit()
    return ok(data)


@router.post("/{project_id}/submit", summary="提交立项审批")
async def submit(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:create"))],
) -> object:
    """提交审批，审批层级按合同金额阈值自动确定。"""
    project = await service.submit_for_approval(session, project_id)
    await session.commit()
    return ok({"id": project.id, "status": project.status, "approvalLevel": project.approval_level})


@router.post("/{project_id}/approve", summary="立项审批通过")
async def approve(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:approve"))],
) -> object:
    """审批通过：进入 APPROVED 并冻结初始基线。"""
    project = await service.approve_project(session, project_id, context.user_id)
    await session.commit()
    return ok({"id": project.id, "status": project.status})


class RejectIn(BaseModel):
    """驳回入参。"""

    reason: str = ""


@router.post("/{project_id}/reject", summary="立项驳回")
async def reject(
    project_id: int,
    body: RejectIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:approve"))],
) -> object:
    """驳回回到草稿。"""
    project = await service.reject_project(session, project_id, context.user_id, body.reason)
    await session.commit()
    return ok({"id": project.id, "status": project.status})


@router.put("/{project_id}/status", summary="项目状态流转")
async def change_status(
    project_id: int,
    body: StatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """启动 / 挂起 / 完成 / 验收 / 关闭 / 终止（状态机拦截非法流转）。

    `reason` 仅在终止时记录，用于追溯「为什么废弃这个项目」。
    """
    project = await service.change_status(
        session, project_id, body.target, context.user_id, reason=body.reason
    )
    await session.commit()
    return ok({"id": project.id, "status": project.status})


@router.get("/{project_id}/stages", summary="阶段列表")
async def stages(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """阶段列表（含权重与进度）。"""
    items = await service.list_stages(session, project_id)
    return ok(
        [
            {
                "id": item.id,
                "stageName": item.stage_name,
                "seq": item.seq,
                "weight": float(item.weight),
                "progress": float(item.progress),
                "planStart": item.plan_start,
                "planEnd": item.plan_end,
                "status": item.status,
            }
            for item in items
        ]
    )


@router.post("/{project_id}/stages", summary="新增阶段")
async def create_stage(
    project_id: int,
    body: StageIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """新增阶段（项目经理或 PMO）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    stage = await service.create_stage(
        session,
        project_id,
        body.stageName,
        weight=body.weight,
        seq=body.seq,
        plan_start=body.planStart,
        plan_end=body.planEnd,
    )
    await session.commit()
    return ok({"id": stage.id})


@router.put("/{project_id}/stages/{stage_id}", summary="编辑阶段")
async def update_stage(
    project_id: int,
    stage_id: int,
    body: StageIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """编辑阶段名称/权重/顺序/计划起止。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    stage = await service.update_stage(
        session,
        project_id,
        stage_id,
        stage_name=body.stageName,
        weight=body.weight,
        seq=body.seq,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": stage.id, "status": stage.status})


@router.delete("/{project_id}/stages/{stage_id}", summary="删除阶段")
async def delete_stage(
    project_id: int,
    stage_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """删除阶段；阶段下仍有任务时拒绝。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    await service.delete_stage(session, project_id, stage_id, context.user_id)
    await session.commit()
    return ok(message="阶段已删除")


@router.put("/{project_id}/stages/{stage_id}/status", summary="推进阶段状态")
async def change_stage_status(
    project_id: int,
    stage_id: int,
    body: StageStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """阶段状态流转；完成前校验该节点交付文档（参数 `project.stage.docRequired`）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    stage = await service.change_stage_status(
        session, project_id, stage_id, body.target, context.user_id
    )
    await session.commit()
    return ok({"id": stage.id, "status": stage.status})


@router.get("/{project_id}/tasks", summary="任务列表")
async def tasks(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """WBS 任务列表（甘特数据源）。"""
    items = await service.list_tasks(session, project_id)
    names = await _user_names(session, {item.owner_id for item in items})
    return ok(
        [
            {
                "id": item.id,
                "taskCode": item.task_code,
                "taskName": item.task_name,
                "stageId": item.stage_id,
                "parentId": item.parent_id,
                "ownerId": item.owner_id,
                "ownerName": names.get(item.owner_id, ""),
                "weight": float(item.weight),
                "progress": float(item.progress),
                "planHours": float(item.plan_hours),
                "actualHours": float(item.actual_hours),
                "planStart": item.plan_start,
                "planEnd": item.plan_end,
                "status": item.status,
                "priority": item.priority,
            }
            for item in items
        ]
    )


@router.post("/{project_id}/tasks", summary="新增任务")
async def create_task(
    project_id: int,
    body: TaskIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """新增 WBS 任务。"""
    task = await service.create_task(
        session,
        project_id,
        body.taskName,
        stage_id=body.stageId,
        owner_id=body.ownerId,
        parent_id=body.parentId,
        weight=body.weight,
        plan_hours=body.planHours,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        priority=body.priority,
    )
    await session.commit()
    return ok({"id": task.id})


@router.put("/{project_id}/tasks/{task_id}", summary="编辑任务")
async def update_task(
    project_id: int,
    task_id: int,
    body: TaskIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """编辑任务名称/阶段/负责人/权重/工时/计划起止/优先级。"""
    task = await service.update_task(
        session,
        project_id,
        task_id,
        task_name=body.taskName,
        stage_id=body.stageId,
        owner_id=body.ownerId,
        weight=body.weight,
        plan_hours=body.planHours,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        priority=body.priority,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": task.id})


@router.delete("/{project_id}/tasks/{task_id}", summary="删除任务")
async def delete_task(
    project_id: int,
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """删除任务（软删）并重算项目进度。"""
    await service.delete_task(session, project_id, task_id, context.user_id)
    await session.commit()
    return ok(message="任务已删除")


@router.put("/{project_id}/tasks/{task_id}/progress", summary="更新任务进度")
async def update_task_progress(
    project_id: int,
    task_id: int,
    body: ProgressIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """更新任务进度并级联重算项目进度。"""
    del project_id
    task = await service.update_task_progress(session, task_id, body.progress, context.user_id)
    await session.commit()
    return ok({"id": task.id, "progress": float(task.progress)})


@router.get("/{project_id}/progress", summary="重算项目进度")
async def recalc(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """按任务/阶段权重重算项目进度。"""
    value = await service.recalc_progress(session, project_id)
    await session.commit()
    return ok({"projectId": project_id, "progress": value})


@router.get("/{project_id}/milestones", summary="里程碑列表")
async def milestones(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """里程碑列表（含负责人姓名）。"""
    items = await service.list_milestones(session, project_id)
    names = await _user_names(session, {item.owner_id for item in items})
    return ok(
        [
            {
                "id": item.id,
                "milestoneName": item.milestone_name,
                "planDate": item.plan_date,
                "actualDate": item.actual_date,
                "status": item.status,
                "delayDays": item.delay_days,
                "ownerId": item.owner_id,
                "ownerName": names.get(item.owner_id, ""),
            }
            for item in items
        ]
    )


@router.post("/{project_id}/milestones", summary="新增里程碑")
async def create_milestone(
    project_id: int,
    body: MilestoneIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """新增里程碑（项目经理或 PMO）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    milestone = await service.create_milestone(
        session, project_id, body.milestoneName, body.planDate, owner_id=body.ownerId
    )
    await session.commit()
    return ok({"id": milestone.id})


@router.put("/{project_id}/milestones/{milestone_id}", summary="编辑里程碑")
async def update_milestone(
    project_id: int,
    milestone_id: int,
    body: MilestoneUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """编辑里程碑名称/计划日期/负责人。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    milestone = await service.update_milestone(
        session,
        project_id,
        milestone_id,
        milestone_name=body.milestoneName,
        plan_date=body.planDate,
        owner_id=body.ownerId,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": milestone.id, "status": milestone.status})


@router.delete("/{project_id}/milestones/{milestone_id}", summary="删除里程碑")
async def delete_milestone(
    project_id: int,
    milestone_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """删除里程碑（软删）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    await service.delete_milestone(session, project_id, milestone_id, context.user_id)
    await session.commit()
    return ok(message="里程碑已删除")


@router.put("/{project_id}/milestones/{milestone_id}/status", summary="里程碑状态")
async def change_milestone_status(
    project_id: int,
    milestone_id: int,
    body: MilestoneStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
) -> object:
    """登记里程碑达成/延期/取消。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    milestone = await service.change_milestone_status(
        session, project_id, milestone_id, body.target, context.user_id
    )
    await session.commit()
    return ok({"id": milestone.id, "status": milestone.status})


@router.get("/{project_id}/members", summary="项目成员")
async def members(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """项目成员列表（含姓名与账号，便于前端直接展示）。"""
    from pms.org.models import SysUser

    items = await service.list_members(session, project_id)
    names: dict[int, tuple[str, str]] = {}
    user_ids = [item.user_id for item in items if item.user_id]
    if user_ids:
        rows = await session.execute(
            select(SysUser.id, SysUser.real_name, SysUser.username).where(
                SysUser.id.in_(user_ids)
            )
        )
        names = {row[0]: (row[1], row[2]) for row in rows.all()}
    return ok(
        [
            {
                "id": item.id,
                "userId": item.user_id,
                "deptId": item.dept_id,
                "roleInProject": item.role_in_project,
                "allocation": float(item.allocation),
                "joinDate": item.join_date,
                # 账号可能已被删除（历史数据），不要把雪花 ID 当姓名展示
                "realName": names.get(item.user_id, ("", ""))[0] or "账号已删除",
                "username": names.get(item.user_id, ("", ""))[1],
                "userMissing": item.user_id not in names,
            }
            for item in items
        ]
    )


@router.post("/{project_id}/members", summary="添加成员")
async def add_member(
    project_id: int,
    body: MemberIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """添加项目成员（重复加入报冲突）。"""
    member = await service.add_member(
        session,
        project_id,
        body.userId,
        body.deptId,
        role_in_project=body.roleInProject,
        allocation=body.allocation,
    )
    await session.commit()
    return ok({"id": member.id})


@router.put("/{project_id}/pm", summary="变更项目负责人")
async def change_pm(
    project_id: int,
    body: PmIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(load_permissions)],
) -> object:
    """变更负责人（含「认领为自己的项目」）。

    权限口径：`project:edit` 可改任意项目负责人；当前负责人可转交他人；
    负责人为空时项目成员也可认领（认领给自己）。
    """
    project = await service.get_project(session, project_id)
    can_edit = context.has_permission("project:edit")
    is_owner = project.pm_id == context.user_id
    is_member = await service.is_member(session, project_id, context.user_id)
    if not (can_edit or is_owner or (project.pm_id == 0 and is_member)):
        raise ForbiddenError("仅项目维护者、当前负责人或项目成员（认领）可变更负责人")
    if not (can_edit or is_owner) and body.pmId != context.user_id:
        raise ForbiddenError("成员仅可将项目认领给自己")
    updated = await service.change_project_pm(
        session, project_id, body.pmId, operator_id=context.user_id
    )
    await session.commit()
    return ok({"id": updated.id, "pmId": updated.pm_id})


@router.delete("/{project_id}/members/{member_id}", summary="移出成员")
async def delete_member(
    project_id: int,
    member_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """移出项目成员；项目负责人需先变更负责人。"""
    await service.remove_member(session, project_id, member_id, context.user_id)
    await session.commit()
    return ok(message="成员已移出")


@router.get("/{project_id}/directors", summary="项目总监列表")
async def list_directors(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """项目总监（可多人，变更审批会签）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    items = await service.list_directors(session, project_id)
    names: dict[int, tuple[str, str]] = {}
    user_ids = [item.user_id for item in items if item.user_id]
    if user_ids:
        rows = await session.execute(
            select(SysUser.id, SysUser.real_name, SysUser.username).where(
                SysUser.id.in_(user_ids)
            )
        )
        names = {row[0]: (row[1], row[2]) for row in rows.all()}
    return ok(
        [
            {
                "userId": item.user_id,
                "realName": names.get(item.user_id, ("", ""))[0] or "账号已删除",
                "username": names.get(item.user_id, ("", ""))[1],
            }
            for item in items
        ]
    )


@router.put("/{project_id}/directors", summary="设置项目总监")
async def set_directors(
    project_id: int,
    body: DirectorsIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """整体设置项目总监（覆盖式）：可多人，审批时会签；被指派者自动入组。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    items = await service.set_directors(
        session, project_id, body.userIds, operator_id=context.user_id
    )
    await session.commit()
    return ok([{"userId": item.user_id} for item in items])


@router.get("/{project_id}/attachments", summary="项目文档列表")
async def list_attachments(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
    bizType: Annotated[str, Query()] = "",
    bizId: Annotated[int, Query()] = 0,
) -> object:
    """项目/节点文档列表（按 `bizType` 过滤：PROJECT / STAGE / MILESTONE / TASK）。"""
    from pms.file import service as file_service

    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    return ok(
        await file_service.list_attachments(
            session, project_id, biz_type=bizType, biz_id=bizId
        )
    )


# ------------------------------ 风险 / 问题 ------------------------------


class RiskIn(BaseModel):
    """风险或问题入参。"""

    riskType: str = "RISK"
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    level: str = "MEDIUM"
    probability: float = 0
    impact: str = ""
    strategy: str = ""
    ownerId: int = 0
    dueDate: str | None = None


class RiskUpdateIn(BaseModel):
    """编辑风险（全部可选）。"""

    riskType: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    level: str | None = None
    probability: float | None = None
    impact: str | None = None
    strategy: str | None = None
    ownerId: int | None = None
    dueDate: str | None = None


class RiskStatusIn(BaseModel):
    """风险状态流转（OPEN / CLOSED）。"""

    status: str


def _risk_out(risk: object, names: dict[int, str] | None = None) -> dict[str, object]:
    """风险出参。"""
    from pms.project.models import PrjRisk

    assert isinstance(risk, PrjRisk)
    owner = (names or {}).get(risk.owner_id, "")
    return {
        "id": risk.id,
        "riskType": risk.risk_type,
        "title": risk.title,
        "description": risk.description,
        "level": risk.level,
        "probability": float(risk.probability),
        "impact": risk.impact,
        "strategy": risk.strategy,
        "ownerId": risk.owner_id,
        "ownerName": owner,
        "dueDate": risk.due_date,
        "closeTime": risk.close_time,
        "status": risk.status,
        "createTime": risk.create_time,
    }


async def _refresh_health(session: AsyncSession, project_id: int) -> None:
    """风险变化会影响健康度（高风险判红、未关闭问题计数），随手校准一次。"""
    from pms.report import service as report_service

    await report_service.refresh_project_health(session, project_id)


@router.get("/{project_id}/risks", summary="风险与问题列表")
async def list_risks(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
    riskType: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
) -> object:
    """项目风险 / 问题列表（可按类型与状态过滤）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    risks = await service.list_risks(
        session, project_id, risk_type=riskType.upper(), status=status.upper()
    )
    owner_ids = {risk.owner_id for risk in risks if risk.owner_id}
    names: dict[int, str] = {}
    if owner_ids:
        rows = await session.execute(
            select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(owner_ids))
        )
        names = {row[0]: row[1] for row in rows.all()}
    return ok([_risk_out(risk, names) for risk in risks])


@router.post("/{project_id}/risks", summary="登记风险/问题")
async def create_risk(
    project_id: int,
    body: RiskIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """登记风险或问题（项目经理 / PMO / 管理员）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    risk = await service.create_risk(
        session,
        project_id,
        context.user_id,
        risk_type=body.riskType,
        title=body.title,
        description=body.description,
        level=body.level,
        probability=body.probability,
        impact=body.impact,
        strategy=body.strategy,
        owner_id=body.ownerId,
        due_date=body.dueDate,
    )
    await _refresh_health(session, project_id)
    await session.commit()
    return ok({"id": risk.id})


@router.put("/{project_id}/risks/{risk_id}", summary="编辑风险/问题")
async def update_risk(
    project_id: int,
    risk_id: int,
    body: RiskUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """编辑风险条目的标题/等级/概率/影响/应对/责任人/截止日。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    risk = await service.update_risk(
        session,
        project_id,
        risk_id,
        context.user_id,
        risk_type=body.riskType,
        title=body.title,
        description=body.description,
        level=body.level,
        probability=body.probability,
        impact=body.impact,
        strategy=body.strategy,
        owner_id=body.ownerId,
        due_date=body.dueDate,
    )
    await _refresh_health(session, project_id)
    await session.commit()
    return ok({"id": risk.id})


@router.put("/{project_id}/risks/{risk_id}/status", summary="风险状态")
async def change_risk_status(
    project_id: int,
    risk_id: int,
    body: RiskStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """关闭或重新打开风险 / 问题。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    risk = await service.change_risk_status(
        session, project_id, risk_id, body.status, context.user_id
    )
    await _refresh_health(session, project_id)
    await session.commit()
    return ok({"id": risk.id, "status": risk.status})


@router.delete("/{project_id}/risks/{risk_id}", summary="删除风险/问题")
async def delete_risk(
    project_id: int,
    risk_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """删除风险条目（软删）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    await service.delete_risk(session, project_id, risk_id, context.user_id)
    await _refresh_health(session, project_id)
    await session.commit()
    return ok(message="已删除")


# ------------------------------ 基线 ------------------------------

BASELINE_TYPE_LABEL: dict[str, str] = {
    "SCOPE": "范围基线",
    "SCHEDULE": "进度基线",
    "COST": "成本基线",
    "CHANGE": "变更基线",
}


def _baseline_out(baseline: object, names: dict[int, str] | None = None) -> dict[str, object]:
    """基线出参（列表不含内容，详情才带 content）。"""
    from pms.project.models import PrjBaseline

    assert isinstance(baseline, PrjBaseline)
    return {
        "id": baseline.id,
        "baselineType": baseline.baseline_type,
        "baselineTypeLabel": BASELINE_TYPE_LABEL.get(baseline.baseline_type, ""),
        "baselineName": baseline.baseline_name,
        "version": baseline.version,
        "frozenBy": baseline.frozen_by,
        "frozenByName": (names or {}).get(baseline.frozen_by, ""),
        "frozenTime": baseline.frozen_time,
        "changeId": baseline.change_id,
        "status": baseline.status,
    }


@router.get("/{project_id}/baselines", summary="基线列表")
async def list_baselines(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """项目基线列表：立项基线 + 每次变更通过后冻结的基线。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    baselines = await service.list_baselines(session, project_id)
    user_ids = {item.frozen_by for item in baselines if item.frozen_by}
    names: dict[int, str] = {}
    if user_ids:
        rows = await session.execute(
            select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(user_ids))
        )
        names = {row[0]: row[1] for row in rows.all()}
    return ok([_baseline_out(item, names) for item in baselines])


@router.get("/{project_id}/baselines/{baseline_id}", summary="基线详情")
async def baseline_detail(
    project_id: int,
    baseline_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """基线详情：含冻结时的阶段/任务/进度快照（JSON）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    baseline = await service.get_baseline(session, project_id, baseline_id)
    names: dict[int, str] = {}
    if baseline.frozen_by:
        rows = await session.execute(
            select(SysUser.real_name).where(SysUser.id == baseline.frozen_by)
        )
        names[baseline.frozen_by] = rows.scalar_one_or_none() or ""
    data = _baseline_out(baseline, names)
    data["content"] = baseline.content_json
    return ok(data)
