"""变更管理服务：申请、评估定级、审批链、执行与基线联动（设计稿 06）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.change.models import ChgApproval, ChgImpact, ChgItem, ChgRequest
from pms.change.rules import (
    ApprovalNode,
    ChangeLevel,
    ImpactDimension,
    ImpactInput,
    LevelThresholds,
    build_chain,
    evaluate_level,
)
from pms.change.state import ApprovalStatus, ChangeNode, ChangeStatus, assert_transit
from pms.common.exceptions import BizRuleError, ConflictError, ForbiddenError, NotFoundError
from pms.core.context import AuthContext
from pms.org.models import SysRole, SysUser, SysUserRole
from pms.project import service as project_service
from pms.project.models import (
    PrjBaseline,
    PrjMember,
    PrjMilestone,
    PrjProject,
    PrjStage,
    PrjTask,
)
from pms.project.state import ProjectStatus
from pms.system.config_service import ConfigService

_CODE_PREFIX: Final[str] = "CR"
# R-CHG-02：仅以下项目状态可提交变更
_ALLOWED_PROJECT_STATUS: Final[frozenset[str]] = frozenset(
    {ProjectStatus.APPROVED, ProjectStatus.IN_PROGRESS, ProjectStatus.SUSPENDED}
)


async def _thresholds(config: ConfigService) -> LevelThresholds:
    """从系统参数读取定级与审批阈值（禁止硬编码）。"""
    return LevelThresholds(
        schedule_pct=await config.get_float("change.level.schedulePct"),
        cost_pct=await config.get_float("change.level.costPct"),
        schedule_days=await config.get_int("change.level.scheduleDays"),
        cost_pct5=await config.get_float("change.level.costPct5"),
        schedule_days_l3=await config.get_int("change.level.scheduleDaysL3"),
        sla_days_l1=await config.get_int("change.sla.daysL1"),
        sla_days_l2=await config.get_int("change.sla.daysL2"),
        sla_days_l3=await config.get_int("change.sla.daysL3"),
    )


async def next_change_code(session: AsyncSession, when: date | None = None) -> str:
    """生成变更编号 `CR-2026-0001`（按年重置，R-CHG-01）。"""
    year = (when or date.today()).year
    pattern = f"{_CODE_PREFIX}-{year}-%"
    stmt = select(func.count(ChgRequest.id)).where(
        ChgRequest.deleted == 0, ChgRequest.request_code.like(pattern)
    )
    result = await session.execute(stmt)
    return f"{_CODE_PREFIX}-{year}-{int(result.scalar_one()) + 1:04d}"


async def create_request(
    session: AsyncSession,
    context: AuthContext,
    *,
    project_id: int,
    change_type: str,
    title: str,
    reason: str = "",
    content: str = "",
    expect_result: str = "",
    source: str = "INTERNAL",
    is_emergency: bool = False,
) -> ChgRequest:
    """创建变更申请（草稿）。R-CHG-02：项目须已立项或在执行中。"""
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        raise NotFoundError("项目不存在")
    if project.status not in _ALLOWED_PROJECT_STATUS:
        raise ConflictError(f"项目状态 {project.status} 不允许提交变更")
    if not await _can_initiate(session, project, context):
        raise ForbiddenError("仅项目经理可发起变更申请")

    request = ChgRequest(
        request_code=await next_change_code(session),
        project_id=project_id,
        change_type=change_type,
        title=title,
        reason=reason,
        content=content,
        expect_result=expect_result,
        source=source,
        status=ChangeStatus.DRAFT,
        is_emergency=1 if is_emergency else 0,
        submitter_id=context.user_id,
        pm_id=project.pm_id,
        create_by=context.user_id,
    )
    session.add(request)
    await session.flush()
    return request


async def submit(session: AsyncSession, request_id: int, operator_id: int = 0) -> ChgRequest:
    """提交变更：DRAFT → SUBMITTED。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.SUBMITTED)
    request.submit_time = date.today()
    request.update_by = operator_id
    await session.flush()
    return request


async def assess(
    session: AsyncSession,
    request_id: int,
    operator_id: int = 0,
    *,
    impacts: list[dict[str, object]],
    items: list[dict[str, object]] | None = None,
    contract_commitment: bool = False,
    tech_architecture: bool | None = None,
    dept_leader_id: int = 0,
    pmo_id: int = 0,
    exec_id: int = 0,
) -> ChgRequest:
    """PM 完成六维评估：写入评估与影响项 → **自动定级** → 生成审批链 → ASSESSED。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.ASSESSED)
    request.update_by = operator_id

    for payload in impacts:
        session.add(ChgImpact(request_id=request_id, **_impact_kwargs(payload)))
    for payload in items or []:
        session.add(ChgItem(request_id=request_id, **_item_kwargs(payload)))
    await session.flush()

    impact_input = await _to_impact_input(
        session, request, impacts, contract_commitment, tech_architecture
    )
    config = ConfigService(session)
    level = evaluate_level(impact_input, await _thresholds(config))
    request.level = str(level)
    request.schedule_impact_days = impact_input.schedule_impact_days
    request.cost_impact_amount = impact_input.cost_impact_amount

    directors = await project_service.director_ids(session, request.project_id)
    if not directors:
        raise BizRuleError("请先在项目详情中指派项目总监，再提交评估")
    resolved_pmo = pmo_id or await _resolve_role_user(session, "PMO")
    resolved_exec = exec_id or await _resolve_role_user(session, "EXEC")
    if ChangeLevel(level) is not ChangeLevel.L1 and not resolved_pmo:
        raise BizRuleError("未找到 PMO 审批人，请为 PMO 角色配置在职用户")
    if ChangeLevel(level) is ChangeLevel.L3 and not resolved_exec:
        raise BizRuleError("未找到公司领导审批人，请为 EXEC 角色配置在职用户")

    chain = build_chain(
        level,
        directors=directors,
        pmo_id=resolved_pmo,
        exec_id=resolved_exec,
        thresholds=await _thresholds(config),
    )
    # 说明：`dept_leader_id` 仅保留入参兼容旧前端，审批链第一节点已改为项目总监会签
    for node in chain:
        session.add(_approval_row(request_id, node))
    await session.flush()
    return request


async def approve(
    session: AsyncSession,
    request_id: int,
    operator_id: int,
    opinion: str = "",
    *,
    is_privileged: bool = False,
) -> ChgRequest:
    """审批当前节点（同序号多行为会签，全部通过才推进）；末节点通过后应用影响项。"""
    request = await _get(session, request_id)
    row = await _current_actor_row(
        session, request_id, operator_id, is_privileged=is_privileged
    )

    row.status = ApprovalStatus.APPROVED
    row.opinion = opinion
    row.approve_time = date.today()
    row.update_by = operator_id
    await session.flush()

    approves = await list_approvals(session, request_id)
    if all(item.status == ApprovalStatus.APPROVED for item in approves):
        request.status = assert_transit(request.status, ChangeStatus.APPROVED)
        request.approve_time = date.today()
        await _apply_items(session, request, operator_id)
        await _freeze_change_baseline(session, request, operator_id)
    return request


async def reject(
    session: AsyncSession,
    request_id: int,
    operator_id: int,
    reason: str = "",
    *,
    is_privileged: bool = False,
) -> ChgRequest:
    """驳回变更：当前节点任一审批人驳回即 REJECTED（会签节点同样一票否决）。"""
    request = await _get(session, request_id)
    row = await _current_actor_row(
        session, request_id, operator_id, is_privileged=is_privileged
    )
    request.status = assert_transit(request.status, ChangeStatus.REJECTED)
    request.update_by = operator_id
    row.status = ApprovalStatus.REJECTED
    row.opinion = reason
    row.approve_time = date.today()
    await session.flush()
    return request


async def request_more_assessment(
    session: AsyncSession,
    request_id: int,
    operator_id: int,
    reason: str = "",
    *,
    is_privileged: bool = False,
) -> ChgRequest:
    """审批人要求补充评估：ASSESSED → DRAFT。"""
    request = await _get(session, request_id)
    await _current_actor_row(session, request_id, operator_id, is_privileged=is_privileged)
    request.status = assert_transit(request.status, ChangeStatus.DRAFT)
    request.update_by = operator_id
    if reason:
        request.content = f"{request.content}\n[补充评估要求] {reason}"
    await session.flush()
    return request


async def withdraw(session: AsyncSession, request_id: int, operator_id: int) -> ChgRequest:
    """撤回 / 中止变更。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.WITHDRAWN)
    request.update_by = operator_id
    await session.flush()
    return request


async def start_execute(session: AsyncSession, request_id: int, operator_id: int) -> ChgRequest:
    """开始执行变更：APPROVED → EXECUTING。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.EXECUTING)
    request.update_by = operator_id
    await session.flush()
    return request


async def submit_verify(session: AsyncSession, request_id: int, operator_id: int) -> ChgRequest:
    """提交验证：EXECUTING → VERIFIED。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.VERIFIED)
    request.update_by = operator_id
    await session.flush()
    return request


async def verify_fail(session: AsyncSession, request_id: int, operator_id: int) -> ChgRequest:
    """验证不通过：VERIFIED → EXECUTING（重新执行）。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.EXECUTING)
    request.update_by = operator_id
    await session.flush()
    return request


async def close(session: AsyncSession, request_id: int, operator_id: int) -> ChgRequest:
    """关闭变更：VERIFIED → CLOSED。"""
    request = await _get(session, request_id)
    request.status = assert_transit(request.status, ChangeStatus.CLOSED)
    request.close_time = date.today()
    request.update_by = operator_id
    await session.flush()
    return request


async def mark_emergency(
    session: AsyncSession, request_id: int, operator_id: int
) -> ChgRequest:
    """标记紧急变更：按 `change.emergency.days` 生成补审批期限（R-CHG-09）。"""
    request = await _get(session, request_id)
    config = ConfigService(session)
    days = await config.get_int("change.emergency.days")
    request.is_emergency = 1
    request.emergency_due = (date.today() + timedelta(days=days)).isoformat()
    request.update_by = operator_id
    await session.flush()
    return request


async def get_request(session: AsyncSession, request_id: int) -> ChgRequest:
    """取变更申请（对外）。"""
    return await _get(session, request_id)


async def list_requests(
    session: AsyncSession,
    project_id: int | None = None,
    status: str = "",
    offset: int = 0,
    limit: int = 20,
) -> list[ChgRequest]:
    """变更台账列表。"""
    stmt = select(ChgRequest).where(ChgRequest.deleted == 0)
    if project_id:
        stmt = stmt.where(ChgRequest.project_id == project_id)
    if status:
        stmt = stmt.where(ChgRequest.status == status)
    stmt = stmt.order_by(ChgRequest.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_requests(
    session: AsyncSession, project_id: int | None = None, status: str = ""
) -> int:
    """变更台账总数。"""
    stmt = select(func.count(ChgRequest.id)).where(ChgRequest.deleted == 0)
    if project_id:
        stmt = stmt.where(ChgRequest.project_id == project_id)
    if status:
        stmt = stmt.where(ChgRequest.status == status)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_approvals(session: AsyncSession, request_id: int) -> list[ChgApproval]:
    """审批链（按序号）。"""
    stmt = (
        select(ChgApproval)
        .where(ChgApproval.request_id == request_id, ChgApproval.deleted == 0)
        .order_by(ChgApproval.seq)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_items(session: AsyncSession, request_id: int) -> list[ChgItem]:
    """影响项明细。"""
    stmt = (
        select(ChgItem)
        .where(ChgItem.request_id == request_id, ChgItem.deleted == 0)
        .order_by(ChgItem.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_impacts(session: AsyncSession, request_id: int) -> list[ChgImpact]:
    """六维评估明细。"""
    stmt = (
        select(ChgImpact)
        .where(ChgImpact.request_id == request_id, ChgImpact.deleted == 0)
        .order_by(ChgImpact.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _impact_kwargs(payload: dict[str, object]) -> dict[str, object]:
    """评估入参转模型字段。"""
    dimension = str(payload.get("dimension", ImpactDimension.SCOPE)).upper()
    return {
        "dimension": dimension,
        "description": str(payload.get("description", "")),
        "scope_expanded": 1 if bool(payload.get("scopeExpanded", False)) else 0,
        "deliverable_add": int(payload.get("deliverableAdd", 0) or 0),
        "deliverable_del": int(payload.get("deliverableDel", 0) or 0),
        "schedule_impact_days": float(payload.get("scheduleImpactDays", 0) or 0),
        "new_end_date": payload.get("newEndDate"),
        "cost_impact_amount": float(payload.get("costImpactAmount", 0) or 0),
        "new_budget": float(payload.get("newBudget", 0) or 0),
        "headcount_delta": int(payload.get("headcountDelta", 0) or 0),
        "role_name": str(payload.get("roleName", "")),
        "allocation": float(payload.get("allocation", 0) or 0),
        "risk_level": str(payload.get("riskLevel", "LOW")),
        "quality_desc": str(payload.get("qualityDesc", "")),
    }


def _item_kwargs(payload: dict[str, object]) -> dict[str, object]:
    """影响项入参转模型字段。"""
    return {
        "item_type": str(payload.get("itemType", "TASK")).upper(),
        "action": str(payload.get("action", "UPDATE")).upper(),
        "biz_id": int(payload.get("bizId", 0) or 0),
        "field_name": str(payload.get("fieldName", "")),
        "before_value": str(payload.get("beforeValue", "")),
        "after_value": str(payload.get("afterValue", "")),
    }


def _approval_row(request_id: int, node: ApprovalNode) -> ChgApproval:
    """审批链节点转模型。"""
    return ChgApproval(
        request_id=request_id,
        seq=node.seq,
        node_role=node.node_role,
        approver_id=node.approver_id,
        status=ApprovalStatus.PENDING,
        sla_days=node.sla_days,
    )


async def _to_impact_input(
    session: AsyncSession,
    request: ChgRequest,
    impacts: list[dict[str, object]],
    contract_commitment: bool,
    tech_architecture: bool | None,
) -> ImpactInput:
    """六维评估结果归并为定级输入。"""
    schedule_days = 0.0
    cost_amount = 0.0
    scope_expanded = False
    need_new_resource = False
    high_risk = False
    for payload in impacts:
        dimension = str(payload.get("dimension", "")).upper()
        if dimension == ImpactDimension.SCOPE:
            scope_expanded = scope_expanded or bool(payload.get("scopeExpanded", False))
        elif dimension == ImpactDimension.SCHEDULE:
            schedule_days += float(payload.get("scheduleImpactDays", 0) or 0)
        elif dimension == ImpactDimension.COST:
            cost_amount += float(payload.get("costImpactAmount", 0) or 0)
        elif dimension == ImpactDimension.RESOURCE:
            need_new_resource = need_new_resource or int(payload.get("headcountDelta", 0) or 0) > 0
        elif dimension == ImpactDimension.RISK:
            high_risk = high_risk or str(payload.get("riskLevel", "LOW")).upper() == "HIGH"

    project = await session.get(PrjProject, request.project_id)
    contract_amount = float(project.contract_amount) if project else 0.0
    plan_days = _plan_days(
        project.plan_start if project else None, project.plan_end if project else None
    )
    if tech_architecture is None:
        tech_architecture = request.change_type == "TECH"
    return ImpactInput(
        scope_expanded=scope_expanded,
        schedule_impact_days=schedule_days,
        plan_total_days=plan_days,
        cost_impact_amount=cost_amount,
        contract_amount=contract_amount,
        contract_commitment=contract_commitment,
        need_new_resource=need_new_resource,
        tech_architecture=bool(tech_architecture),
        high_risk=high_risk,
    )


def _plan_days(plan_start: object | None, plan_end: object | None) -> float:
    """计划总天数（用于计算工期影响占比）。"""
    if not plan_start or not plan_end:
        return 0.0
    start = _to_date(plan_start)
    end = _to_date(plan_end)
    if start is None or end is None:
        return 0.0
    return float((end - start).days)


def _to_date(value: object) -> date | None:
    """把日期列值（可能是 str/date）统一为 `date`。"""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _num(value: str) -> float:
    """字符串转数值，失败返回 0。"""
    try:
        return float(value)
    except ValueError:
        return 0.0


def _shift_date(value: object | None, days: int) -> str | None:
    """日期顺延指定天数。"""
    base = _to_date(value)
    if base is None:
        return None
    return (base + timedelta(days=int(days))).isoformat()


async def _apply_items(session: AsyncSession, request: ChgRequest, operator_id: int) -> None:
    """应用影响项到项目计划（阶段/里程碑/任务/资源/预算）。"""
    items = await list_items(session, request.id)
    project = await session.get(PrjProject, request.project_id)
    for item in items:
        if item.applied:
            continue
        if item.item_type == "TASK":
            task = await session.get(PrjTask, item.biz_id)
            if task is None:
                continue
            if item.field_name == "planHours":
                item.before_value = f"{float(task.plan_hours):.2f}"
                task.plan_hours = _num(item.after_value)
            elif item.field_name == "planEnd":
                item.before_value = str(task.plan_end or "")
                task.plan_end = item.after_value
        elif item.item_type == "MILESTONE":
            milestone = await session.get(PrjMilestone, item.biz_id)
            if milestone is not None and item.field_name == "planDate":
                item.before_value = str(milestone.plan_date or "")
                milestone.plan_date = item.after_value
        elif item.item_type == "STAGE":
            stage = await session.get(PrjStage, item.biz_id)
            if stage is not None and item.field_name in {"planStart", "planEnd"}:
                item.before_value = str(getattr(stage, _field_of(item.field_name)) or "")
                setattr(stage, _field_of(item.field_name), item.after_value)
        elif item.item_type == "BUDGET" and project is not None:
            if item.field_name == "contractAmount":
                item.before_value = f"{float(project.contract_amount):.2f}"
                project.contract_amount = _num(item.after_value)
        elif item.item_type == "RESOURCE":
            if item.action == "ADD":
                # 幂等入组：成员已存在时不报错（立项时负责人已自动入组）
                await project_service.ensure_member(
                    session,
                    request.project_id,
                    item.biz_id,
                    0,
                    role_in_project=item.after_value or "MEMBER",
                )
        item.applied = 1
        item.update_by = operator_id

    if project is not None and float(request.schedule_impact_days) > 0:
        project.plan_end = _shift_date(project.plan_end, int(request.schedule_impact_days))
    await session.flush()
    await project_service.recalc_progress(session, request.project_id)


def _field_of(field_name: str) -> str:
    """驼峰字段转模型属性名。"""
    return {"planStart": "plan_start", "planEnd": "plan_end"}.get(field_name, "plan_end")


async def _freeze_change_baseline(
    session: AsyncSession, request: ChgRequest, operator_id: int
) -> PrjBaseline:
    """变更后冻结新基线 v(n+1) 并记录前后版本（06 §6）。"""
    before_stmt = (
        select(PrjBaseline.version)
        .where(PrjBaseline.project_id == request.project_id, PrjBaseline.deleted == 0)
        .order_by(PrjBaseline.id.desc())
        .limit(1)
    )
    before_result = await session.execute(before_stmt)
    request.baseline_before = str(before_result.scalar_one_or_none() or "")

    baseline = await project_service.freeze_baseline(session, request.project_id, operator_id)
    count_stmt = select(func.count(PrjBaseline.id)).where(
        PrjBaseline.project_id == request.project_id, PrjBaseline.deleted == 0
    )
    version = f"V{int((await session.execute(count_stmt)).scalar_one())}.0"
    baseline.baseline_type = "CHANGE"
    baseline.baseline_name = f"变更基线 {request.request_code}"
    baseline.version = version
    baseline.change_id = request.id
    request.baseline_after = version
    await session.flush()
    return baseline


async def _can_initiate(
    session: AsyncSession, project: PrjProject, context: AuthContext
) -> bool:
    """是否可发起变更：项目经理（负责人/组内 PM）或特权角色（PMO/公司领导）。"""
    if context.is_privileged or project.pm_id == context.user_id:
        return True
    stmt = select(PrjMember.id).where(
        PrjMember.project_id == project.id,
        PrjMember.user_id == context.user_id,
        PrjMember.role_in_project == "PM",
        PrjMember.deleted == 0,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _resolve_role_user(session: AsyncSession, role_code: str) -> int:
    """按角色取第一个在职用户（PMO / EXEC 审批人兜底）。"""
    stmt = (
        select(SysUser.id)
        .join(SysUserRole, SysUserRole.user_id == SysUser.id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysRole.role_code == role_code,
            SysRole.deleted == 0,
            SysUserRole.deleted == 0,
            SysUser.deleted == 0,
            SysUser.status == "ENABLED",
        )
        .order_by(SysUser.id)
        .limit(1)
    )
    return int((await session.execute(stmt)).scalar_one_or_none() or 0)


async def _current_actor_row(
    session: AsyncSession,
    request_id: int,
    operator_id: int,
    *,
    is_privileged: bool = False,
) -> ChgApproval:
    """取当前待审批节点中属于操作人的一行（会签节点仅本人可审）。"""
    approves = await list_approvals(session, request_id)
    pending = [row for row in approves if row.status == ApprovalStatus.PENDING]
    if not pending:
        raise ConflictError("没有待审批节点")
    current_seq = min(row.seq for row in pending)
    rows = [row for row in pending if row.seq == current_seq]
    mine = next((row for row in rows if row.approver_id == operator_id), None)
    if mine is not None:
        return mine
    # PMO/公司领导可代审 PMO/EXEC 节点，但不能代替项目总监会签
    if is_privileged and rows[0].node_role != ChangeNode.DIRECTOR:
        return rows[0]
    raise ForbiddenError("当前用户不是该节点审批人（项目总监节点需总监本人会签）")


async def _get(session: AsyncSession, request_id: int) -> ChgRequest:
    """按 ID 取变更申请。"""
    request = await session.get(ChgRequest, request_id)
    if request is None or request.deleted:
        raise NotFoundError("变更申请不存在")
    return request
