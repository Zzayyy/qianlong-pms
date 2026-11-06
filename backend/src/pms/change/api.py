"""变更管理接口：申请、评估定级、审批链、执行与基线联动（设计稿 06）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.change import service
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.org.models import SysUser

router = APIRouter(prefix="/api/v1/changes", tags=["变更管理"])


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


def _request_out(request: object) -> dict[str, object]:
    """变更出参。"""
    from pms.change.models import ChgRequest

    assert isinstance(request, ChgRequest)
    return {
        "id": request.id,
        "requestCode": request.request_code,
        "projectId": request.project_id,
        "changeType": request.change_type,
        "title": request.title,
        "level": request.level,
        "status": request.status,
        "isEmergency": request.is_emergency,
        "emergencyDue": request.emergency_due,
        "scheduleImpactDays": float(request.schedule_impact_days),
        "costImpactAmount": float(request.cost_impact_amount),
        "baselineBefore": request.baseline_before,
        "baselineAfter": request.baseline_after,
    }


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
    await session.commit()
    return ok({"id": request.id, "requestCode": request.request_code})


@router.get("", summary="变更台账")
async def list_changes(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    projectId: Annotated[int | None, Query()] = None,
    status: Annotated[str, Query()] = "",
) -> object:
    """分页查询变更台账。"""
    total = await service.count_requests(session, projectId, status)
    items = await service.list_requests(
        session, projectId, status, pagination.offset, pagination.limit
    )
    return paged(
        [_request_out(item) for item in items], total, pagination.page_num, pagination.page_size
    )


@router.get("/{request_id}", summary="变更详情")
async def change_detail(
    request_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("change:view"))],
) -> object:
    """变更详情：含评估、影响项与审批链。"""
    request = await service.get_request(session, request_id)
    approvals = await service.list_approvals(session, request_id)
    impacts = await service.list_impacts(session, request_id)
    change_items = await service.list_items(session, request_id)
    approver_ids = {row.approver_id for row in approvals if row.approver_id}
    names: dict[int, str] = {}
    if approver_ids:
        rows = await session.execute(
            select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(approver_ids))
        )
        names = {row[0]: row[1] for row in rows.all()}
    return ok(
        {
            "request": _request_out(request),
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
                {"dimension": row.dimension, "description": row.description} for row in impacts
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
    """撤回或中止变更。"""
    request = await service.withdraw(session, request_id, context.user_id)
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
