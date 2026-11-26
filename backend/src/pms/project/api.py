"""项目周期接口：立项、审批、状态流转、阶段/里程碑/任务/成员（设计稿 09 §2.3）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ForbiddenError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import (
    Pagination,
    get_pagination,
    get_session,
    load_permissions,
    require_any_permission,
    require_permissions,
)
from pms.org.models import SysDept, SysUser
from pms.project import alerts as alert_service
from pms.project import service
from pms.project.models import PrjProject, PrjStage
from pms.project.visibility import (
    can_manage_stage_tasks,
    can_view_project,
    ensure_project_manager,
    ensure_project_visible,
    ensure_stage_task_manager,
    is_project_manager,
)
from pms.system.config_service import ConfigService

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


async def _current_stage_map(
    session: AsyncSession, project_ids: set[int]
) -> dict[int, dict[str, object]]:
    """批量取各项目「当前阶段」：按顺序第一个未完成且未取消的阶段。

    列表页需要「项目走到哪一步」，逐项目查会 N+1，这里按当前页一次性取回；
    带上阶段的计划起止与负责人，前端不必再逐项目拉阶段；
    全部阶段都完成时返回「全部完成」，没有阶段的项目不下发该字段。
    """
    if not project_ids:
        return {}
    rows = await session.execute(
        select(
            PrjStage.project_id,
            PrjStage.stage_name,
            PrjStage.status,
            PrjStage.progress,
            PrjStage.owner_id,
            PrjStage.plan_start,
            PrjStage.plan_end,
        )
        .where(PrjStage.project_id.in_(project_ids), PrjStage.deleted == 0)
        .order_by(PrjStage.project_id, PrjStage.seq, PrjStage.id)
    )
    stages: dict[int, dict[str, object]] = {}
    totals: dict[int, int] = {}
    for project_id, stage_name, status, progress, owner_id, plan_start, plan_end in rows.all():
        code = str(status or "")
        if code == "CANCELLED":
            continue
        key = int(project_id)
        totals[key] = totals.get(key, 0) + 1
        # 已完成的阶段跳过，第一个未完成的就是「当前阶段」
        if code == "DONE" or key in stages:
            continue
        stages[key] = {
            "currentStage": str(stage_name or ""),
            "currentStageStatus": code,
            "currentStageProgress": round(float(progress or 0), 1),
            "currentStageOwnerId": int(owner_id or 0),
            "currentStageStart": str(plan_start or ""),
            "currentStageEnd": str(plan_end or ""),
        }
    for key, total in totals.items():
        if key not in stages and total > 0:
            stages[key] = {
                "currentStage": "全部完成",
                "currentStageStatus": "DONE",
                "currentStageProgress": 100.0,
                "currentStageOwnerId": 0,
                "currentStageStart": "",
                "currentStageEnd": "",
            }
    return stages


def _can_view_amount(context: AuthContext) -> bool:
    """合同额属敏感字段：仅项目维护者（`project:edit`）与审批人（`project:approve`）可见。

    开发 / 测试 / 运维 / 销售等仅有 `project:view` 的普通人员看不到金额，
    后端直接不下发该字段，避免只靠前端隐藏。
    """
    return context.has_permission("project:edit") or context.has_permission("project:approve")


def _project_out(
    project: PrjProject, pm_name: str = "", show_amount: bool = True
) -> dict[str, object]:
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
        # 无权限时置空，前端据此不展示合同额
        "contractAmount": float(project.contract_amount) if show_amount else None,
        "planStart": project.plan_start,
        "planEnd": project.plan_end,
        "approvalLevel": project.approval_level,
        # 补审批状态：0 不涉及，1 待补审批，2 补审批被驳回（项目仍在执行）
        "retroApproval": int(project.retro_approval or 0),
        "retroDue": project.retro_due,
        "terminateReason": project.terminate_reason,
        "notifyEnabled": project.notify_enabled is None or int(project.notify_enabled) == 1,
    }


class ProjectStageIn(BaseModel):
    """立项时一并创建的阶段（默认四段式：设计/开发/测试/交付）。"""

    stageName: str = Field(min_length=1, max_length=128)
    ownerId: int = 0
    weight: float = 0
    seq: int = 1
    planStart: str | None = None
    planEnd: str | None = None
    # 阶段参与人（负责人之外的多人分工），会自动补进项目组
    memberIds: list[int] = Field(default_factory=list)


class ProjectIn(BaseModel):
    """立项入参。"""

    projectName: str = Field(min_length=1, max_length=200)
    deptId: int = 0
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
    stages: list[ProjectStageIn] = Field(default_factory=list)
    directorIds: list[int] = Field(default_factory=list)
    # 创建方式：NONE=直接立项（不审批）、RETRO=先开工后补审批、PRE=先审批后开工
    # 不传则回落到 needApproval（兼容旧前端）/ 系统参数
    approvalMode: str | None = Field(default=None, pattern="^(NONE|RETRO|PRE)$")
    # None=沿用系统参数；显式传入时按项目决定
    needApproval: bool | None = None
    # 立项通过后立即进入 IN_PROGRESS（仅 NONE 模式生效；RETRO 模式必然立即开工）
    startNow: bool = False


class ProjectBasicIn(BaseModel):
    """项目基础信息维护入参（立项后仍可调整的字段，只传需要改的项）。

    `planStart` / `planEnd` 传 `null` 表示清空计划日期（改回「未排期」）。
    `reason` 为必填的变更原因（字段确有变化时校验），用于生成变更留痕。
    """

    deptId: int | None = Field(default=None, ge=0)
    contractAmount: float | None = Field(default=None, ge=0)
    planStart: str | None = None
    planEnd: str | None = None
    # 项目级「自动通知」开关：false 关闭该项目所有业务邮件
    notifyEnabled: bool | None = None
    reason: str = Field(default="", max_length=500)


class StatusIn(BaseModel):
    """状态流转入参。"""

    target: str = Field(min_length=2, max_length=32)
    reason: str = Field(default="", max_length=500)


class StageIn(BaseModel):
    """阶段入参。"""

    stageName: str = Field(min_length=1, max_length=128)
    ownerId: int = 0
    weight: float = 0
    seq: int = 1
    planStart: str | None = None
    planEnd: str | None = None
    # 阶段参与人（负责人之外的多人分工）；传空数组表示清空，仅新增时生效
    memberIds: list[int] | None = None
    # 变更原因（新增/编辑阶段必填，写入变更记录）
    reason: str = Field(default="", max_length=500)

    @field_validator("planStart", "planEnd", mode="before")
    @classmethod
    def _normalize_dates(cls, value: object) -> object:
        """空串 → None（未排期）。"""
        return _blank_date_to_none(value)


class StageStatusIn(BaseModel):
    """阶段状态入参（NOT_STARTED / IN_PROGRESS / DONE）。"""

    target: str = Field(min_length=3, max_length=16)
    reason: str = Field(default="", max_length=500)


def _blank_date_to_none(value: object) -> object:
    """空串统一按「未排期」处理。

    MySQL 的 DATE 列不接受空串（`Incorrect date value: ''`），前端日期选择器
    清空后常以 `""` 提交，这里统一归一为空值，避免落到 500。
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


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
    #: 任务类型：REQ / DEV / TEST / DOC / OPS，空值=未分类
    taskType: str = ""

    @field_validator("planStart", "planEnd", mode="before")
    @classmethod
    def _normalize_dates(cls, value: object) -> object:
        """空串 → None（未排期）。"""
        return _blank_date_to_none(value)


class ProgressIn(BaseModel):
    """任务进度入参。"""

    progress: float = Field(ge=0, le=100)


class MilestoneIn(BaseModel):
    """里程碑入参。"""

    milestoneName: str = Field(min_length=1, max_length=128)
    planDate: str
    ownerId: int = 0
    # 变更原因（新增/编辑里程碑必填，写入变更记录）
    reason: str = Field(default="", max_length=500)


class MilestoneUpdateIn(MilestoneIn):
    """里程碑编辑入参（字段同新增）。"""


class MilestoneStatusIn(BaseModel):
    """里程碑状态入参。"""

    target: str = Field(min_length=3, max_length=16)
    reason: str = Field(default="", max_length=500)


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
    reason: str = Field(default="", max_length=500)


@router.post("", summary="创建项目")
async def create_project(
    body: ProjectIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:create"))],
) -> object:
    """创建项目（手工立项；商机转化走 `/crm/opportunities/{id}/convert`）。

    三种创建方式：
    - `NONE`：直接立项通过并冻结基线，按 `startNow` 决定是否立即开工；
    - `RETRO`：先开工后补审批，创建即进入执行，另记补审批期限；
    - `PRE`：先审批后开工，创建即提交审批（`APPROVING`），通过后才可启动。
    """
    config = ConfigService(session)
    mode = body.approvalMode
    if mode is None:
        need_approval = body.needApproval
        if need_approval is None:
            need_approval = await config.get_bool("approval.project.enabled")
        mode = "PRE" if need_approval else "NONE"
    retro = mode == "RETRO"
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
        stages=[item.model_dump() for item in body.stages],
        director_ids=body.directorIds,
        auto_approve=mode != "PRE",
        start_now=body.startNow,
        retro=retro,
        submit_now=mode == "PRE",
    )
    await session.commit()
    return ok({"id": project.id, "projectCode": project.project_code, "status": project.status})


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
    scope: Annotated[str, Query(pattern="^(all|pm|member)$")] = "all",
) -> object:
    """分页查询项目，**逐条按四维权限过滤**（维度 ③）。

    `status` 支持逗号分组；`deptId` / `pmId` / `health` 为可选的精确筛选。
    `scope` 提供「我的项目」视角：`all` 全部可见（默认）、`pm` 我负责、
    `member` 我参与（负责人 + 项目组成员）；可见性仍受四维权限约束。
    """
    current_user = context.user_id
    effective_pm = pmId or (current_user if scope == "pm" else 0)
    member_id = current_user if scope == "member" else 0
    total = await service.count_projects(
        session,
        keyword,
        status,
        dept_id=deptId or 0,
        pm_id=effective_pm or 0,
        health=health,
        member_id=member_id,
    )
    items = await service.list_projects(
        session,
        pagination.offset,
        pagination.limit,
        keyword,
        status,
        dept_id=deptId or 0,
        pm_id=effective_pm or 0,
        health=health,
        member_id=member_id,
    )
    visible_items = [item for item in items if await _can_view(session, context, item)]
    names = await _user_names(session, {item.pm_id for item in visible_items})
    show_amount = _can_view_amount(context)
    # 「当前阶段」按当前页批量取，避免逐项目查询
    stage_map = await _current_stage_map(session, {item.id for item in visible_items})
    # 当前阶段负责人的姓名与项目经理一起批量补齐，前端不依赖人员列表权限
    owner_ids = {int(row.get("currentStageOwnerId") or 0) for row in stage_map.values()}
    unnamed = owner_ids - set(names)
    if unnamed:
        names.update(await _user_names(session, unnamed))
    for data in stage_map.values():
        data["currentStageOwner"] = names.get(int(data.get("currentStageOwnerId") or 0), "")
    return paged(
        [
            {
                **_project_out(item, names.get(item.pm_id, ""), show_amount=show_amount),
                **stage_map.get(
                    item.id,
                    {"currentStage": "", "currentStageStatus": "", "currentStageProgress": None},
                ),
            }
            for item in visible_items
        ],
        len(visible_items) if len(visible_items) != len(items) else total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/options", summary="新建项目表单选项")
async def project_options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """新建项目所需的轻量配置：审批开关、补审批期限与默认部门（总公司）。"""
    config = ConfigService(session)
    default_dept = await session.execute(
        select(SysDept.id).where(SysDept.dept_code == "ROOT", SysDept.deleted == 0)
    )
    return ok(
        {
            "approvalEnabled": await config.get_bool("approval.project.enabled"),
            "retroDays": await config.get_int("project.retro.days"),
            # 阶段完成前是否强制交付文档：前端提前拦截，避免填完原因才被拒
            "stageDocRequired": await config.get_bool("project.stage.docRequired"),
            "defaultDeptId": default_dept.scalar_one_or_none() or 0,
        }
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
    can_view_amount = _can_view_amount(context)
    data = _project_out(project, names.get(project.pm_id, ""), show_amount=can_view_amount)
    # 前端据此决定是否展示合同额列/指标（与后端下发口径一致）
    data["canViewAmount"] = can_view_amount
    data["canManage"] = await is_project_manager(session, context, project)
    # 项目周报只对项目经理与领导层开放，前端据此决定是否显示「周报」页签
    from pms.weekly import service as weekly_service

    data["canViewWeekly"] = await weekly_service.can_view_project_weekly(
        session, context, project
    )

    # 工时口径：实际工时取已生效日志明细汇总（任务工时是它的下钻视图），
    # assignedHours 为已归到任务的工时，两者之差即「未分配任务工时」
    from pms.worklog import service as worklog_service

    tasks = await service.list_tasks(session, project_id)
    data["planHours"] = round(float(sum(float(task.plan_hours) for task in tasks)), 2)
    data["actualHours"] = round(
        await worklog_service.project_actual_hours(session, project_id), 2
    )
    data["assignedHours"] = round(
        float(sum(float(task.actual_hours) for task in tasks)), 2
    )

    # 读取详情时顺带校准健康度：单项目计算开销小，避免列表长期停留在默认 GREEN
    from pms.report import service as report_service

    health = await report_service.refresh_project_health(session, project_id)
    if str(data["health"]) != health:
        data["health"] = health
        await session.commit()
    return ok(data)


@router.put("/{project_id}", summary="编辑项目基础信息")
async def update_project(
    project_id: int,
    body: ProjectBasicIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """维护立项后仍需调整的基础信息：所属部门、合同金额、计划周期、自动通知开关。

    改金额时草稿态会同步重算审批层级，避免提交审批时阈值与表单不一致；
    计划日期未出现在请求体里表示「不修改」，显式传 null 表示清空。
    其它字段（名称、编码、状态）仍走各自的专用接口。
    """
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    provided = body.model_fields_set
    updated = await service.update_project_basic(
        session,
        project_id,
        dept_id=body.deptId,
        contract_amount=body.contractAmount,
        plan_start=body.planStart if "planStart" in provided else service.UNSET,
        plan_end=body.planEnd if "planEnd" in provided else service.UNSET,
        notify_enabled=body.notifyEnabled,
        operator_id=context.user_id,
        reason=body.reason,
    )
    await session.commit()
    names = await _user_names(session, {updated.pm_id})
    return ok(_project_out(updated, names.get(updated.pm_id, "")))


@router.post("/{project_id}/submit", summary="提交立项审批")
async def submit(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:create"))],
) -> object:
    """提交审批，审批层级按合同金额阈值自动确定。"""
    project = await service.submit_for_approval(session, project_id, context.user_id)
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

    `reason` 必填：状态变化会写一条变更留痕，终止时还额外写入
    `t_prj_project.terminate_reason`，用于追溯「为什么废弃这个项目」。
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
    """阶段列表（含负责人、参与人、权重与进度）。

    出参附加 `canEditTasks`：当前用户能否维护该阶段下的任务
    （项目经理/PMO 全项目，其余角色仅自己负责的阶段），供前端控制入口。
    """
    project = await service.get_project(session, project_id)
    manager = await is_project_manager(session, context, project)
    task_perm = context.has_permission("project:task:manage")
    items = await service.list_stages(session, project_id)
    member_map = await service.list_stage_members(session, [item.id for item in items])
    user_ids = {item.owner_id for item in items} | {
        uid for ids in member_map.values() for uid in ids
    }
    names = await _user_names(session, user_ids)
    return ok(
        [
            {
                "id": item.id,
                "stageName": item.stage_name,
                "ownerId": item.owner_id,
                "ownerName": names.get(item.owner_id, ""),
                "memberIds": member_map.get(item.id, []),
                "memberNames": [names.get(uid, "") for uid in member_map.get(item.id, [])],
                "seq": item.seq,
                "weight": float(item.weight),
                "progress": float(item.progress),
                "planStart": item.plan_start,
                "planEnd": item.plan_end,
                "status": item.status,
                "canEditTasks": manager
                or (task_perm and int(item.owner_id or 0) == context.user_id),
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
        owner_id=body.ownerId,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        operator_id=context.user_id,
        reason=body.reason,
        member_ids=body.memberIds or [],
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
    """编辑阶段名称/权重/顺序/负责人/计划起止/参与人。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    stage = await service.update_stage(
        session,
        project_id,
        stage_id,
        stage_name=body.stageName,
        weight=body.weight,
        seq=body.seq,
        owner_id=body.ownerId,
        plan_start=body.planStart,
        plan_end=body.planEnd,
        operator_id=context.user_id,
        reason=body.reason,
        member_ids=body.memberIds,
    )
    await session.commit()
    return ok({"id": stage.id, "status": stage.status})


@router.delete("/{project_id}/stages/{stage_id}", summary="删除阶段")
async def delete_stage(
    project_id: int,
    stage_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
    reason: Annotated[str, Query(max_length=500)] = "",
) -> object:
    """删除阶段；阶段下仍有任务时拒绝；`reason` 必填（写入变更记录）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    await service.delete_stage(
        session, project_id, stage_id, context.user_id, reason=reason
    )
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
        session, project_id, stage_id, body.target, context.user_id, reason=body.reason
    )
    await session.commit()
    return ok({"id": stage.id, "status": stage.status})


@router.get("/{project_id}/tasks", summary="任务列表")
async def tasks(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """WBS 任务列表（甘特数据源）。

    出参附加 `canEdit`：当前用户能否编辑/删除该任务（项目管理者或所属阶段交付负责人）。
    """
    project = await service.get_project(session, project_id)
    manager = await is_project_manager(session, context, project)
    task_perm = context.has_permission("project:task:manage")
    my_stage_ids = {
        item.id
        for item in await service.list_stages(session, project_id)
        if int(item.owner_id or 0) == context.user_id
    }
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
                "taskType": item.task_type,
                "canEdit": manager or (task_perm and item.stage_id in my_stage_ids),
            }
            for item in items
        ]
    )


@router.post("/{project_id}/tasks", summary="新增任务")
async def create_task(
    project_id: int,
    body: TaskIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext,
        Depends(require_any_permission("project:task:manage", "project:edit")),
    ],
) -> object:
    """新增 WBS 任务。

    项目经理 / PMO 可给任意阶段建任务；阶段交付负责人（`project:task:manage`）
    只能在自己负责的阶段下建，未分配阶段仍只允许项目管理者建。
    """
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    await ensure_stage_task_manager(session, context, project, body.stageId)
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
        task_type=body.taskType,
    )
    await session.commit()
    return ok({"id": task.id})


@router.put("/{project_id}/tasks/{task_id}", summary="编辑任务")
async def update_task(
    project_id: int,
    task_id: int,
    body: TaskIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext,
        Depends(require_any_permission("project:task:manage", "project:edit")),
    ],
) -> object:
    """编辑任务名称/阶段/负责人/权重/工时/计划起止/优先级。

    交付负责人只能改自己阶段下的任务；换阶段时目标阶段也必须在自己权限内。
    """
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    current = await service.get_task(session, project_id, task_id)
    await ensure_stage_task_manager(session, context, project, current.stage_id)
    if body.stageId and body.stageId != current.stage_id:
        await ensure_stage_task_manager(session, context, project, body.stageId)
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
        # 空串表示不修改类型（编辑表单未传时不清空）
        task_type=body.taskType or None,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": task.id})


@router.delete("/{project_id}/tasks/{task_id}", summary="删除任务")
async def delete_task(
    project_id: int,
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext,
        Depends(require_any_permission("project:task:manage", "project:edit")),
    ],
) -> object:
    """删除任务（软删）并重算项目进度；交付负责人仅限自己负责的阶段。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    current = await service.get_task(session, project_id, task_id)
    await ensure_stage_task_manager(session, context, project, current.stage_id)
    await service.delete_task(session, project_id, task_id, context.user_id)
    await session.commit()
    return ok(message="任务已删除")


@router.put("/{project_id}/tasks/{task_id}/progress", summary="更新任务进度")
async def update_task_progress(
    project_id: int,
    task_id: int,
    body: ProgressIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[
        AuthContext,
        Depends(
            require_any_permission(
                "project:task:progress", "project:task:manage", "project:edit"
            )
        ),
    ],
) -> object:
    """更新任务进度并级联重算项目进度。

    执行人凭 `project:task:progress` 上报本人负责任务的进度；
    项目管理者与阶段交付负责人可改该范围内任意任务（服务层再次校验负责人身份）。
    """
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    current = await service.get_task(session, project_id, task_id)
    privileged = await can_manage_stage_tasks(
        session, context, project, current.stage_id
    )
    task = await service.update_task_progress(
        session,
        task_id,
        body.progress,
        context.user_id,
        privileged=privileged,
    )
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


@router.get("/{project_id}/issues", summary="项目问题统计")
async def project_issues(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """项目下的 Bug / 生产问题统计与列表（项目详情「问题」页签）。

    工时占比口径：问题工时 / 项目实际工时。问题工时依赖日志明细关联问题
    （`WlItem.issue_id`，下一步接入），当前按 0 返回，接上后自动生效。
    """
    from pms.issue import service as issue_service
    from pms.worklog import service as worklog_service

    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    rows = await issue_service.list_issues(
        session, project_id=project_id, offset=0, limit=1000
    )
    names = await _user_names(session, {row.owner_id for row in rows})
    bug_total = sum(1 for row in rows if row.issue_type == "BUG")
    prod_total = len(rows) - bug_total
    bug_open = sum(
        1 for row in rows if row.issue_type == "BUG" and row.status != "CLOSED"
    )
    prod_open = sum(
        1 for row in rows if row.issue_type == "PROD" and row.status != "CLOSED"
    )
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for row in rows:
        by_severity[row.severity] = by_severity.get(row.severity, 0) + 1
        by_status[row.status] = by_status.get(row.status, 0) + 1

    project_hours = await worklog_service.project_actual_hours(session, project_id)
    issue_hours = 0.0
    return ok(
        {
            "bugTotal": bug_total,
            "prodTotal": prod_total,
            "openTotal": bug_open + prod_open,
            "bugOpen": bug_open,
            "prodOpen": prod_open,
            "projectHours": round(project_hours, 2),
            "issueHours": round(issue_hours, 2),
            "hoursRatio": (
                round(issue_hours / project_hours * 100, 1) if project_hours > 0 else 0.0
            ),
            "bySeverity": by_severity,
            "byStatus": by_status,
            "list": [
                {
                    "id": row.id,
                    "issueNo": row.issue_no,
                    "issueType": row.issue_type,
                    "title": row.title,
                    "status": row.status,
                    "severity": row.severity,
                    "ownerName": names.get(int(row.owner_id), ""),
                    "foundDate": row.found_date,
                    "closeDate": row.close_date,
                }
                for row in rows
            ],
        }
    )


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
        session,
        project_id,
        body.milestoneName,
        body.planDate,
        owner_id=body.ownerId,
        operator_id=context.user_id,
        reason=body.reason,
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
        reason=body.reason,
    )
    await session.commit()
    return ok({"id": milestone.id, "status": milestone.status})


@router.delete("/{project_id}/milestones/{milestone_id}", summary="删除里程碑")
async def delete_milestone(
    project_id: int,
    milestone_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:stage:edit"))],
    reason: Annotated[str, Query(max_length=500)] = "",
) -> object:
    """删除里程碑（软删）；`reason` 必填（写入变更记录）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    await service.delete_milestone(
        session, project_id, milestone_id, context.user_id, reason=reason
    )
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
        session, project_id, milestone_id, body.target, context.user_id, reason=body.reason
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
    """添加项目成员（重复加入报冲突）；仅项目经理/PMO 可操作。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    member = await service.add_member(
        session,
        project_id,
        body.userId,
        body.deptId,
        role_in_project=body.roleInProject,
        allocation=body.allocation,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": member.id})


class MemberRoleIn(BaseModel):
    """成员组内角色入参。"""

    roleInProject: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=500)


@router.put("/{project_id}/members/{member_id}", summary="修改成员组内角色")
async def update_member(
    project_id: int,
    member_id: int,
    body: MemberRoleIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """调整成员组内角色（项目经理需走「变更项目经理」）。

    `reason` 可不传：角色微调频率高，后端会自动生成「开发 → 测试」形式的留痕原因。
    仅项目经理/PMO 可操作。
    """
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    member = await service.update_member_role(
        session,
        project_id,
        member_id,
        body.roleInProject,
        context.user_id,
        reason=body.reason,
    )
    await session.commit()
    return ok({"id": member.id, "roleInProject": member.role_in_project})


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
        session, project_id, body.pmId, operator_id=context.user_id, reason=body.reason
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
    """移出项目成员；项目负责人需先变更负责人。仅项目经理/PMO 可操作。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
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
        # 来源：MANUAL 人工 / WORKLOG 日志 / ALERT 预警转正（前端展示 + 筛选）
        "source": risk.source,
        "sourceKey": risk.source_key,
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


# ------------------------------ 风险预警 ------------------------------


class AlertKeyIn(BaseModel):
    """预警转正 / 忽略的入参：只传 key，内容以服务端实时计算为准。"""

    key: str = Field(min_length=1, max_length=128)


class AlertIgnoreIn(AlertKeyIn):
    """忽略预警：默认 7 天内不再提示。"""

    days: int = 7


def _alert_out(item: object) -> dict[str, object]:
    """预警出参（不落库，转正后才写风险台账）。"""
    assert isinstance(item, alert_service.Alert)
    return {
        "key": item.key,
        "source": item.source,
        "sourceLabel": alert_service.SOURCE_LABEL.get(item.source, item.source),
        "riskType": item.risk_type,
        "level": item.level,
        "title": item.title,
        "evidence": item.evidence,
        "ownerId": item.owner_id,
        "dueDate": item.due_date,
    }


@router.get("/{project_id}/alerts", summary="项目风险预警")
async def project_alerts(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """待处理预警：进度延期、里程碑逾期、日志问题（只读，转正后才进风险台账）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)
    items = await alert_service.list_alerts(session, project_id)
    return ok({"list": [_alert_out(item) for item in items], "count": len(items)})


@router.post("/{project_id}/alerts/convert", summary="预警转为风险")
async def convert_alert(
    project_id: int,
    body: AlertKeyIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """把一条预警转成正式风险（幂等：同一个 key 只会落一条）。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    existing = await service.find_risk_by_source_key(session, project_id, body.key)
    if existing is not None:
        return ok({"id": existing.id})
    alert = await alert_service.find_alert(session, project_id, body.key)
    if alert is None:
        raise BizRuleError("该预警已处理或已不成立，请刷新后重试")
    risk = await service.create_risk(
        session,
        project_id,
        context.user_id,
        risk_type=alert.risk_type,
        title=alert.title,
        description=alert.evidence,
        level=alert.level,
        owner_id=alert.owner_id,
        due_date=alert.due_date,
        source="ALERT",
        source_key=alert.key,
    )
    await _refresh_health(session, project_id)
    await session.commit()
    return ok({"id": risk.id})


@router.post("/{project_id}/alerts/ignore", summary="忽略预警")
async def ignore_alert(
    project_id: int,
    body: AlertIgnoreIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:edit"))],
) -> object:
    """忽略某个预警一段时间（默认 7 天），内部记录到 `t_prj_alert_mute`。"""
    project = await service.get_project(session, project_id)
    await ensure_project_manager(session, context, project)
    until = await alert_service.mute_alert(
        session, project_id, body.key, body.days, context.user_id
    )
    await session.commit()
    return ok({"mutedUntil": until})


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
