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
)

router = APIRouter(prefix="/api/v1/projects", tags=["项目周期"])


async def _can_view(session: AsyncSession, context: AuthContext, project: PrjProject) -> bool:
    """项目可见性判定（设计稿 03 §4.1，参数可在后台调整）。"""
    return await can_view_project(session, context, project)


def _project_out(project: PrjProject) -> dict[str, object]:
    """项目出参。"""
    return {
        "id": project.id,
        "projectCode": project.project_code,
        "projectName": project.project_name,
        "status": project.status,
        "health": project.health,
        "progress": float(project.progress),
        "deptId": project.dept_id,
        "pmId": project.pm_id,
        "customerId": project.customer_id,
        "opportunityId": project.opportunity_id,
        "contractAmount": float(project.contract_amount),
        "planStart": project.plan_start,
        "planEnd": project.plan_end,
        "approvalLevel": project.approval_level,
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
) -> object:
    """分页查询项目，**逐条按四维权限过滤**（维度 ③）。"""
    total = await service.count_projects(session, keyword)
    items = await service.list_projects(session, pagination.offset, pagination.limit, keyword)
    visible_items = [item for item in items if await _can_view(session, context, item)]
    return paged(
        [_project_out(item) for item in visible_items],
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
    """项目详情；不可见时返回 40302（数据越权）。"""
    from pms.common.exceptions import DataForbiddenError

    project = await service.get_project(session, project_id)
    if not await _can_view(session, context, project):
        raise DataForbiddenError("无该项目访问权限")
    return ok(_project_out(project))


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
    """启动 / 挂起 / 完成 / 验收 / 关闭 / 终止（状态机拦截非法流转）。"""
    project = await service.change_status(session, project_id, body.target, context.user_id)
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
    return ok(
        [
            {
                "id": item.id,
                "taskCode": item.task_code,
                "taskName": item.task_name,
                "stageId": item.stage_id,
                "parentId": item.parent_id,
                "ownerId": item.owner_id,
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
    """里程碑列表。"""
    items = await service.list_milestones(session, project_id)
    return ok(
        [
            {
                "id": item.id,
                "milestoneName": item.milestone_name,
                "planDate": item.plan_date,
                "actualDate": item.actual_date,
                "status": item.status,
                "delayDays": item.delay_days,
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
                "realName": names.get(item.user_id, ("", ""))[0],
                "username": names.get(item.user_id, ("", ""))[1],
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
                "realName": names.get(item.user_id, ("", ""))[0],
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
