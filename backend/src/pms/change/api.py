"""变更管理接口：申请、评估定级、审批链、执行与基线联动（设计稿 06）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.change import service
from pms.change.rules import ChangeType, ImpactDimension
from pms.change.state import ChangeStatus
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.org.models import SysUser
from pms.project.models import PrjProject
from pms.system.config_service import ConfigService

router = APIRouter(prefix="/api/v1/changes", tags=["变更管理"])

#: 周期排期角色（如开发 / 测试）默认值，可在「规则参数」中调整 `change.schedule.roles`
_DEFAULT_SCHEDULE_ROLES: tuple[str, ...] = ("开发", "测试", "实施", "运维")


class ScheduleIn(BaseModel):
    """周期排期明细入参：角色 + 负责人 + 日期范围。"""

    roleName: str = Field(min_length=1, max_length=32)
    ownerId: int = 0
    planStart: str
    planEnd: str
    remark: str = ""


class ChangeIn(BaseModel):
    """变更申请入参。"""

    projectId: int
    changeType: str = "OTHER"
    title: str = Field(min_length=1, max_length=200)
    reason: str = ""
    content: str = ""
    expectResult: str = ""
    source: str = "INTERNAL"
    isEmergency: bool = False
    schedules: list[ScheduleIn] = Field(default_factory=list)


class ChangeUpdateIn(BaseModel):
    """编辑变更申请（仅草稿）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str | None = None
    content: str | None = None
    expectResult: str | None = None
    isEmergency: bool | None = None


class SchedulesIn(BaseModel):
    """周期排期保存入参（整体覆盖）。"""

    items: list[ScheduleIn] = Field(default_factory=list)


class AssessIn(BaseModel):
    """评估入参：六维影响 + 影响项 + 定级补充信息。"""

    impacts: list[dict[str, object]] = Field(default_factory=list)
    items: list[dict[str, object]] = Field(default_factory=list)
    contractCommitment: bool = False
    techArchitecture: bool | None = None
    deptLeaderId: int = 0
    pmoId: int = 0
    execId: int = 0


class OpinionIn(BaseModel):
    """审批意见入参。"""

    opinion: str = ""


def _request_out(
    request: object, project_name: str = "", schedule_roles: str = ""
) -> dict[str, object]:
    """变更出参。"""
    from pms.change.models import ChgRequest

    assert isinstance(request, ChgRequest)
    return {
        "id": request.id,
        "requestCode": request.request_code,
        "projectId": request.project_id,
        "projectName": project_name,
        "scheduleRoles": schedule_roles,
        "changeType": request.change_type,
        "title": request.title,
        "reason": request.reason,
        "content": request.content,
        "expectResult": request.expect_result,
        "level": request.level,
        "status": request.status,
        "isEmergency": request.is_emergency,
        "emergencyDue": request.emergency_due,
        "scheduleImpactDays": float(request.schedule_impact_days),
        "costImpactAmount": float(request.cost_impact_amount),
        "submitterId": request.submitter_id,
        "pmId": request.pm_id,
        "submitTime": request.submit_time,
        "approveTime": request.approve_time,
        "closeTime": request.close_time,
        "baselineBefore": request.baseline_before,
        "baselineAfter": request.baseline_after,
    }


def _schedule_out(row: object, user_names: dict[int, str] | None = None) -> dict[str, object]:
    """周期排期出参。"""
    from pms.change.models import ChgSchedule

    assert isinstance(row, ChgSchedule)
    names = user_names or {}
    return {
        "id": row.id,
        "roleName": row.role_name,
        "ownerId": row.owner_id,
        "ownerName": names.get(row.owner_id, ""),
        "planStart": row.plan_start,
        "planEnd": row.plan_end,
        "remark": row.remark,
        "applied": row.applied,
    }


async def _user_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """批量取用户姓名（负责人展示）。"""
    ids = {item for item in user_ids if item}
    if not ids:
        return {}
    rows = await session.execute(
        select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(ids), SysUser.deleted == 0)
    )
    return {row[0]: row[1] for row in rows.all()}


async def _project_names(session: AsyncSession, project_ids: set[int]) -> dict[int, str]:
    """批量取项目名称（台账展示）。"""
    ids = {item for item in project_ids if item}
    if not ids:
        return {}
    rows = await session.execute(
        select(PrjProject.id, PrjProject.project_name).where(
            PrjProject.id.in_(ids), PrjProject.deleted == 0
        )
    )
    return {row[0]: row[1] for row in rows.all()}


@router.post("", summary="创建变更申请")
async def create_change(
    body: ChangeIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """创建变更草稿；项目须处于已立项 / 进行中 / 已挂起（R-CHG-02）。"""
    request = await service.create_request(
        session,
        context,
        project_id=body.projectId,
        change_type=body.changeType,
        title=body.title,
        reason=body.reason,
        content=body.content,
        expect_result=body.expectResult,
        source=body.source,
        is_emergency=body.isEmergency,
    )
    if body.schedules:
        await service.replace_schedules(
            session,
            request.id,
            [item.model_dump() for item in body.schedules],
            context.user_id,
        )
    await session.commit()
    return ok({"id": request.id, "requestCode": request.request_code})


@router.get("", summary="变更台账")
async def list_changes(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    projectId: Annotated[int | None, Query()] = None,
    status: Annotated[str, Query()] = "",
    changeType: Annotated[str, Query()] = "",
    level: Annotated[str, Query()] = "",
    keyword: Annotated[str, Query()] = "",
    emergency: Annotated[bool, Query()] = False,
) -> object:
    """分页查询变更台账；支持项目 / 状态 / 类型 / 级别 / 关键字 / 紧急筛选。"""
    filters = {
        "change_type": changeType,
        "level": level,
        "keyword": keyword,
        "only_emergency": emergency,
    }
    total = await service.count_requests(session, projectId, status, **filters)
    items = await service.list_requests(
        session,
        projectId,
        status,
        pagination.offset,
        pagination.limit,
        **filters,
    )
    names = await _project_names(session, {item.project_id for item in items})
    roles = await service.schedule_summary(session, [item.id for item in items])
    return paged(
        [
            _request_out(item, names.get(item.project_id, ""), roles.get(item.id, ""))
            for item in items
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/options", summary="变更页面选项")
async def change_options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """周期排期角色、变更类型/状态枚举，以及可发起变更的项目状态。

    角色可在「规则参数」中调整；`projectStatuses` 供前端过滤「新建变更」的
    项目下拉，避免用户填完表单才发现项目处于草稿等不可变更状态（R-CHG-02）。
    """
    raw = await ConfigService(session).get_str("change.schedule.roles")
    roles = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return ok(
        {
            "scheduleRoles": roles or list(_DEFAULT_SCHEDULE_ROLES),
            "changeTypes": [item.value for item in ChangeType],
            "dimensions": [item.value for item in ImpactDimension],
            "statuses": [item.value for item in ChangeStatus],
            "projectStatuses": service.allowed_project_statuses(),
        }
    )


@router.get("/{request_id}", summary="变更详情")
async def change_detail(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """变更详情：含周期排期、评估、影响项与审批链。"""
    request = await service.get_request(session, request_id)
    approvals = await service.list_approvals(session, request_id)
    impacts = await service.list_impacts(session, request_id)
    change_items = await service.list_items(session, request_id)
    schedules = await service.list_schedules(session, request_id)
    project_names = await _project_names(session, {request.project_id})
    names = await _user_names(
        session,
        {row.approver_id for row in approvals}
        | {row.owner_id for row in schedules}
        | {request.submitter_id, request.pm_id},
    )
    return ok(
        {
            "request": _request_out(request, project_names.get(request.project_id, "")),
            "schedules": [_schedule_out(row, names) for row in schedules],
            "approvals": [
                {
                    "seq": row.seq,
                    "nodeRole": row.node_role,
                    "approverId": row.approver_id,
                    "approverName": names.get(row.approver_id, ""),
                    "status": row.status,
                    "opinion": row.opinion,
                    "approveTime": row.approve_time,
                    "slaDays": row.sla_days,
                }
                for row in approvals
            ],
            "impacts": [
                {
                    "dimension": row.dimension,
                    "description": row.description,
                    "scopeExpanded": row.scope_expanded,
                    "deliverableAdd": row.deliverable_add,
                    "deliverableDel": row.deliverable_del,
                    "scheduleImpactDays": float(row.schedule_impact_days),
                    "newEndDate": row.new_end_date,
                    "costImpactAmount": float(row.cost_impact_amount),
                    "newBudget": float(row.new_budget),
                    "headcountDelta": row.headcount_delta,
                    "roleName": row.role_name,
                    "allocation": float(row.allocation),
                    "riskLevel": row.risk_level,
                    "qualityDesc": row.quality_desc,
                }
                for row in impacts
            ],
            "items": [
                {
                    "itemType": row.item_type,
                    "action": row.action,
                    "bizId": row.biz_id,
                    "fieldName": row.field_name,
                    "beforeValue": row.before_value,
                    "afterValue": row.after_value,
                    "applied": row.applied,
                }
                for row in change_items
            ],
        }
    )


@router.put("/{request_id}", summary="编辑变更申请")
async def update_change(
    request_id: int,
    body: ChangeUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """编辑草稿的标题/原因/内容/期望结果/紧急标记（仅 DRAFT）。"""
    request = await service.update_request(
        session,
        request_id,
        context.user_id,
        title=body.title,
        reason=body.reason,
        content=body.content,
        expect_result=body.expectResult,
        is_emergency=body.isEmergency,
    )
    await session.commit()
    return ok({"id": request.id, "title": request.title, "status": request.status})


@router.put("/{request_id}/schedules", summary="保存周期排期")
async def save_schedules(
    request_id: int,
    body: SchedulesIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """整体覆盖保存周期排期（角色 + 负责人 + 日期范围）；评估后需先撤回再改。"""
    saved = await service.replace_schedules(
        session, request_id, [item.model_dump() for item in body.items], context.user_id
    )
    await session.commit()
    return ok({"count": len(saved)})


@router.post("/{request_id}/submit", summary="提交变更")
async def submit(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """DRAFT → SUBMITTED。"""
    request = await service.submit(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/assess", summary="六维评估并自动定级")
async def assess(
    request_id: int,
    body: AssessIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """PM 完成评估：写入六维与影响项 → 自动定级 → 生成审批链 → ASSESSED。

    权限为 `change:create`（评估由 PM 完成，`change:approve` 属审批人，见设计稿 06 §3）。
    """
    request = await service.assess(
        session,
        request_id,
        context.user_id,
        impacts=body.impacts,
        items=body.items,
        contract_commitment=body.contractCommitment,
        tech_architecture=body.techArchitecture,
        dept_leader_id=body.deptLeaderId,
        pmo_id=body.pmoId,
        exec_id=body.execId,
    )
    await session.commit()
    return ok({"id": request.id, "level": request.level, "status": request.status})


@router.post("/{request_id}/approve", summary="审批通过")
async def approve(
    request_id: int,
    body: OpinionIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """审批当前节点；同序号多行会签全部通过后才推进，末节点通过后生成新基线。

    权限口径：`change:view` 即可调用，服务层校验「是否为当前节点审批人」；
    项目总监无需全局 `change:approve`，被指派到该项目即取得审核权。
    """
    request = await service.approve(
        session,
        request_id,
        context.user_id,
        body.opinion,
        is_privileged=context.is_privileged,
    )
    await session.commit()
    return ok(
        {
            "id": request.id,
            "status": request.status,
            "baselineAfter": request.baseline_after,
        }
    )


@router.post("/{request_id}/reject", summary="驳回变更")
async def reject(
    request_id: int,
    body: OpinionIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """任一节点驳回 → REJECTED（会签节点一票否决）。"""
    request = await service.reject(
        session,
        request_id,
        context.user_id,
        body.opinion,
        is_privileged=context.is_privileged,
    )
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/more", summary="要求补充评估")
async def more_assessment(
    request_id: int,
    body: OpinionIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """审批人要求补充评估：ASSESSED → DRAFT。"""
    request = await service.request_more_assessment(
        session,
        request_id,
        context.user_id,
        body.opinion,
        is_privileged=context.is_privileged,
    )
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/withdraw", summary="撤回变更")
async def withdraw(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:create"))],
) -> object:
    """撤回或中止变更（仅发起人 / 项目经理 / 特权角色）。"""
    request = await service.withdraw(
        session,
        request_id,
        context.user_id,
        is_privileged=context.is_privileged or context.has_any_role("ADMIN"),
    )
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/execute", summary="开始执行")
async def execute(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:execute"))],
) -> object:
    """APPROVED → EXECUTING。"""
    request = await service.start_execute(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/verify", summary="提交验证")
async def verify(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:execute"))],
) -> object:
    """EXECUTING → VERIFIED。"""
    request = await service.submit_verify(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/verify-fail", summary="验证不通过")
async def verify_fail(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:execute"))],
) -> object:
    """验证不通过，回到执行中。"""
    request = await service.verify_fail(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/close", summary="关闭变更")
async def close(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:execute"))],
) -> object:
    """VERIFIED → CLOSED。"""
    request = await service.close(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "status": request.status})


@router.post("/{request_id}/emergency", summary="标记紧急变更")
async def emergency(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:execute"))],
) -> object:
    """标记紧急变更并生成补审批期限（参数 `change.emergency.days`）。"""
    request = await service.mark_emergency(session, request_id, context.user_id)
    await session.commit()
    return ok({"id": request.id, "emergencyDue": request.emergency_due})
