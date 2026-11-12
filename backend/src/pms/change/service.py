"""变更管理服务：申请、评估定级、审批链、执行与基线联动（设计稿 06）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.change.models import ChgApproval, ChgImpact, ChgItem, ChgRequest, ChgSchedule
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
from pms.common.logging import get_logger
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

logger = get_logger(__name__)

_CODE_PREFIX: Final[str] = "CR"
# R-CHG-02：仅以下项目状态可提交变更
_ALLOWED_PROJECT_STATUS: Final[frozenset[str]] = frozenset(
    {ProjectStatus.APPROVED, ProjectStatus.IN_PROGRESS, ProjectStatus.SUSPENDED}
)
# 周期排期只在「未定级」前可改：评估后审批链已按影响定级，改排期必须重新评估
_SCHEDULE_EDITABLE_STATUS: Final[frozenset[str]] = frozenset(
    {ChangeStatus.DRAFT, ChangeStatus.SUBMITTED}
)


def allowed_project_statuses() -> list[str]:
    """可发起变更的项目状态（R-CHG-02），供前端过滤「新建变更」的项目下拉。"""
    return sorted({str(item) for item in _ALLOWED_PROJECT_STATUS})


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


async def update_request(
    session: AsyncSession,
    request_id: int,
    operator_id: int = 0,
    *,
    title: str | None = None,
    reason: str | None = None,
    content: str | None = None,
    expect_result: str | None = None,
    is_emergency: bool | None = None,
) -> ChgRequest:
    """编辑变更申请基本信息（仅草稿状态）。"""
    request = await _get(session, request_id)
    if request.status != ChangeStatus.DRAFT:
        raise ConflictError(f"变更状态 {request.status} 不允许编辑，请撤回后修改")
    if title is not None:
        request.title = title
    if reason is not None:
        request.reason = reason
    if content is not None:
        request.content = content
    if expect_result is not None:
        request.expect_result = expect_result
    if is_emergency is not None:
        request.is_emergency = 1 if is_emergency else 0
    request.update_by = operator_id
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

    # 「要求补充评估」会退回 DRAFT，再次评估时先清空上一轮评估与审批链，避免重复行
    for row in await list_impacts(session, request_id):
        row.deleted = 1
    for row in await list_items(session, request_id):
        row.deleted = 1
    for row in await list_approvals(session, request_id):
        row.deleted = 1
    await session.flush()

    for payload in impacts:
        session.add(ChgImpact(request_id=request_id, **_impact_kwargs(payload)))
    for payload in items or []:
        session.add(ChgItem(request_id=request_id, **_item_kwargs(payload)))
    await session.flush()

    # 周期排期（角色负责人 + 日期范围）折算为项目/阶段计划的影响项
    schedules = await list_schedules(session, request_id)
    if schedules:
        await _append_schedule_items(session, request, schedules)
        await session.flush()

    impact_input = await _to_impact_input(
        session, request, impacts, contract_commitment, tech_architecture
    )
    derived_days = await _schedule_impact_days(session, request, schedules)
    if derived_days > impact_input.schedule_impact_days:
        impact_input = replace(impact_input, schedule_impact_days=derived_days)
    config = ConfigService(session)
    level = evaluate_level(impact_input, await _thresholds(config))
    request.level = str(level)
    request.schedule_impact_days = impact_input.schedule_impact_days
    request.cost_impact_amount = impact_input.cost_impact_amount

    directors = await project_service.director_ids(session, request.project_id)
    if not directors:
        raise BizRuleError("请先在项目详情中指派项目总监，再提交评估")

    # 审批链不得出现「发起人审自己」：优先剔除发起人，取同角色其他在职人员；
    # 若该角色只有发起人一人（小团队常见），保留原节点并由公司领导代审兜底。
    initiator = int(request.submitter_id or 0) or int(operator_id or 0)
    other_directors = [item for item in directors if item != initiator]
    if not other_directors:
        logger.warning(
            "变更 %s 的项目总监仅为发起人本人，将形成自审：%s",
            request.request_code,
            directors,
        )
    else:
        directors = other_directors

    resolved_pmo = pmo_id or await _resolve_role_user(
        session, "PMO", exclude_user_id=initiator
    )
    if not resolved_pmo and ChangeLevel(level) is not ChangeLevel.L1:
        fallback_pmo = await _resolve_role_user(session, "PMO")
        if fallback_pmo:
            logger.warning(
                "PMO 角色仅发起人本人在职，变更 %s 的 PMO 节点需由 PMO/公司领导代审",
                request.request_code,
            )
        resolved_pmo = fallback_pmo

    resolved_exec = exec_id or await _resolve_role_user(
        session, "EXEC", exclude_user_id=initiator
    )
    if not resolved_exec:
        resolved_exec = await _resolve_role_user(session, "EXEC")
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
        await _apply_schedules(session, request, operator_id)
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


async def withdraw(
    session: AsyncSession,
    request_id: int,
    operator_id: int,
    *,
    is_privileged: bool = False,
) -> ChgRequest:
    """撤回 / 中止变更：仅发起人、项目经理或特权角色（PMO/公司领导/管理员）可操作。

    说明：撤回属于「申请人侧」动作（终止自己的申请），与审批人侧的
    「退回补充 / 驳回」是不同职责，不能靠 `change:create` 一个权限放到所有人身上。
    """
    request = await _get(session, request_id)
    if not is_privileged and operator_id not in {request.submitter_id, request.pm_id}:
        raise ForbiddenError("仅发起人或项目经理可撤回该变更")
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


def _request_filters(
    project_id: int | None = None,
    status: str = "",
    change_type: str = "",
    level: str = "",
    keyword: str = "",
    only_emergency: bool = False,
) -> list[object]:
    """变更台账查询条件（列表与计数共用，避免口径不一致）。"""
    clauses: list[object] = []
    if project_id:
        clauses.append(ChgRequest.project_id == project_id)
    if status:
        # 支持逗号分组，便于前端用一段式页签表达「待审批 = SUBMITTED+ASSESSED」
        values = [item.strip() for item in status.split(",") if item.strip()]
        if len(values) > 1:
            clauses.append(ChgRequest.status.in_(values))
        elif values:
            clauses.append(ChgRequest.status == values[0])
    if change_type:
        clauses.append(ChgRequest.change_type == change_type)
    if level:
        clauses.append(ChgRequest.level == level)
    if only_emergency:
        clauses.append(ChgRequest.is_emergency == 1)
    if keyword:
        like = f"%{keyword}%"
        clauses.append(ChgRequest.title.like(like) | ChgRequest.request_code.like(like))
    return clauses


async def list_requests(
    session: AsyncSession,
    project_id: int | None = None,
    status: str = "",
    offset: int = 0,
    limit: int = 20,
    *,
    change_type: str = "",
    level: str = "",
    keyword: str = "",
    only_emergency: bool = False,
) -> list[ChgRequest]:
    """变更台账列表（可按项目/状态/类型/级别/关键字过滤）。"""
    stmt = select(ChgRequest).where(
        ChgRequest.deleted == 0,
        *_request_filters(project_id, status, change_type, level, keyword, only_emergency),
    )
    stmt = stmt.order_by(ChgRequest.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_requests(
    session: AsyncSession,
    project_id: int | None = None,
    status: str = "",
    *,
    change_type: str = "",
    level: str = "",
    keyword: str = "",
    only_emergency: bool = False,
) -> int:
    """变更台账总数（过滤条件与列表一致）。"""
    stmt = select(func.count(ChgRequest.id)).where(
        ChgRequest.deleted == 0,
        *_request_filters(project_id, status, change_type, level, keyword, only_emergency),
    )
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


async def list_schedules(session: AsyncSession, request_id: int) -> list[ChgSchedule]:
    """周期排期明细（按角色+负责人登记的多段日期范围）。"""
    stmt = (
        select(ChgSchedule)
        .where(ChgSchedule.request_id == request_id, ChgSchedule.deleted == 0)
        .order_by(ChgSchedule.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def schedule_summary(
    session: AsyncSession, request_ids: list[int]
) -> dict[int, str]:
    """台账用的排期摘要：每条变更涉及的角色（按登记顺序去重）。"""
    ids = [item for item in request_ids if item]
    if not ids:
        return {}
    stmt = (
        select(ChgSchedule.request_id, ChgSchedule.role_name)
        .where(ChgSchedule.request_id.in_(ids), ChgSchedule.deleted == 0)
        .order_by(ChgSchedule.id)
    )
    summary: dict[int, list[str]] = {}
    for request_id, role_name in (await session.execute(stmt)).all():
        bucket = summary.setdefault(request_id, [])
        if role_name and role_name not in bucket:
            bucket.append(role_name)
    return {key: "、".join(roles) for key, roles in summary.items()}


async def replace_schedules(
    session: AsyncSession,
    request_id: int,
    items: list[dict[str, object]],
    operator_id: int = 0,
) -> list[ChgSchedule]:
    """整体覆盖保存周期排期（仅草稿 / 已提交可改，评估后需重新评估）。"""
    request = await _get(session, request_id)
    if request.status not in _SCHEDULE_EDITABLE_STATUS:
        raise ConflictError(f"变更状态 {request.status} 不允许修改周期排期，请先撤回")
    for row in await list_schedules(session, request_id):
        row.deleted = 1
        row.update_by = operator_id
    await session.flush()

    saved: list[ChgSchedule] = []
    for payload in items:
        role_name = str(payload.get("roleName", "")).strip()
        if not role_name:
            raise BizRuleError("排期角色不能为空（如开发 / 测试）")
        start = _to_date(payload.get("planStart"))
        end = _to_date(payload.get("planEnd"))
        if start is None or end is None:
            raise BizRuleError(f"角色「{role_name}」的排期起止日期不能为空")
        if end < start:
            raise BizRuleError(f"角色「{role_name}」的排期结束日期不能早于开始日期")
        row = ChgSchedule(
            request_id=request_id,
            role_name=role_name,
            owner_id=int(payload.get("ownerId", 0) or 0),
            plan_start=start.isoformat(),
            plan_end=end.isoformat(),
            remark=str(payload.get("remark", "")),
            applied=0,
            create_by=operator_id,
        )
        session.add(row)
        saved.append(row)
    await session.flush()
    return saved


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
    """应用影响项到项目计划（项目/阶段/里程碑/任务/资源/预算）。"""
    items = await list_items(session, request.id)
    project = await session.get(PrjProject, request.project_id)
    has_schedule = await _count_schedules(session, request.id) > 0
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
        elif item.item_type == "PROJECT" and project is not None:
            if item.field_name in {"planStart", "planEnd"}:
                item.before_value = str(getattr(project, _field_of(item.field_name)) or "")
                setattr(project, _field_of(item.field_name), item.after_value)
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

    # 有周期排期时由排期给出准确日期，不再按天数粗放顺延，避免重复叠加
    if project is not None and float(request.schedule_impact_days) > 0 and not has_schedule:
        project.plan_end = _shift_date(project.plan_end, int(request.schedule_impact_days))
    await session.flush()
    await project_service.recalc_progress(session, request.project_id)


def _field_of(field_name: str) -> str:
    """驼峰字段转模型属性名。"""
    return {"planStart": "plan_start", "planEnd": "plan_end"}.get(field_name, "plan_end")


async def _count_schedules(session: AsyncSession, request_id: int) -> int:
    """周期排期条数（判断是否以排期为准）。"""
    stmt = select(func.count(ChgSchedule.id)).where(
        ChgSchedule.request_id == request_id, ChgSchedule.deleted == 0
    )
    return int((await session.execute(stmt)).scalar_one())


async def _schedule_impact_days(
    session: AsyncSession, request: ChgRequest, schedules: list[ChgSchedule]
) -> float:
    """排期相对项目计划结束日的顺延天数（用于自动定级）。"""
    if not schedules:
        return 0.0
    project = await session.get(PrjProject, request.project_id)
    current_end = _to_date(project.plan_end) if project is not None else None
    ends = [moment for moment in (_to_date(row.plan_end) for row in schedules) if moment]
    if current_end is None or not ends:
        return 0.0
    return float(max(0, (max(ends) - current_end).days))


async def _append_schedule_items(
    session: AsyncSession, request: ChgRequest, schedules: list[ChgSchedule]
) -> None:
    """把周期排期折算成影响项（项目计划起止 + 同名阶段计划起止）。

    统一走 `t_chg_item`，审批通过后由 `_apply_items` 落库，前端「影响项」可直接看到前后值。
    """
    project = await session.get(PrjProject, request.project_id)
    if project is None:
        return
    existing = await list_items(session, request.id)
    seen = {(item.item_type, item.biz_id, item.field_name) for item in existing}
    rows: list[dict[str, object]] = []

    starts = [moment for moment in (_to_date(row.plan_start) for row in schedules) if moment]
    ends = [moment for moment in (_to_date(row.plan_end) for row in schedules) if moment]
    if starts:
        new_start = min(starts)
        old_start = _to_date(project.plan_start)
        if old_start is None or new_start < old_start:
            rows.append(
                {
                    "itemType": "PROJECT",
                    "action": "UPDATE",
                    "bizId": project.id,
                    "fieldName": "planStart",
                    "beforeValue": str(project.plan_start or ""),
                    "afterValue": new_start.isoformat(),
                }
            )
    if ends:
        new_end = max(ends)
        old_end = _to_date(project.plan_end)
        if old_end is None or new_end > old_end:
            rows.append(
                {
                    "itemType": "PROJECT",
                    "action": "UPDATE",
                    "bizId": project.id,
                    "fieldName": "planEnd",
                    "beforeValue": str(project.plan_end or ""),
                    "afterValue": new_end.isoformat(),
                }
            )

    stages = await project_service.list_stages(session, request.project_id)
    for row in schedules:
        matched = [stage for stage in stages if row.role_name and row.role_name in stage.stage_name]
        for stage in matched:
            if row.plan_start:
                rows.append(
                    {
                        "itemType": "STAGE",
                        "action": "UPDATE",
                        "bizId": stage.id,
                        "fieldName": "planStart",
                        "beforeValue": str(stage.plan_start or ""),
                        "afterValue": str(row.plan_start),
                    }
                )
            if row.plan_end:
                rows.append(
                    {
                        "itemType": "STAGE",
                        "action": "UPDATE",
                        "bizId": stage.id,
                        "fieldName": "planEnd",
                        "beforeValue": str(stage.plan_end or ""),
                        "afterValue": str(row.plan_end),
                    }
                )

    for row in rows:
        key = (row["itemType"], row["bizId"], row["fieldName"])
        if key in seen:
            continue
        seen.add(key)
        session.add(ChgItem(request_id=request.id, **_item_kwargs(row)))


async def _apply_schedules(
    session: AsyncSession, request: ChgRequest, operator_id: int
) -> None:
    """审批通过后落排期：**只延长不缩短**地校准项目计划起止，并标记已应用。

    排期通常只登记部分角色（如仅测试段），若直接以 `min(开始)` 覆盖，
    会把项目开始日后移、把计划周期压短，与「变更顺延」的语义相反。
    """
    schedules = await list_schedules(session, request.id)
    if not schedules:
        return
    project = await session.get(PrjProject, request.project_id)
    if project is not None:
        starts = [moment for moment in (_to_date(row.plan_start) for row in schedules) if moment]
        ends = [moment for moment in (_to_date(row.plan_end) for row in schedules) if moment]
        if starts:
            new_start = min(starts)
            current_start = _to_date(project.plan_start)
            if current_start is None or new_start < current_start:
                project.plan_start = new_start.isoformat()
        if ends:
            new_end = max(ends)
            current_end = _to_date(project.plan_end)
            if current_end is None or new_end > current_end:
                project.plan_end = new_end.isoformat()
    for row in schedules:
        row.applied = 1
        row.update_by = operator_id
    await session.flush()


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
    """是否可发起变更：项目经理（负责人/组内 PM）、PMO/公司领导或系统管理员。"""
    if context.is_privileged or context.has_any_role("ADMIN"):
        return True
    if project.pm_id == context.user_id:
        return True
    stmt = select(PrjMember.id).where(
        PrjMember.project_id == project.id,
        PrjMember.user_id == context.user_id,
        PrjMember.role_in_project == "PM",
        PrjMember.deleted == 0,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _resolve_role_user(
    session: AsyncSession, role_code: str, *, exclude_user_id: int = 0
) -> int:
    """按角色取第一个在职用户（PMO / EXEC 审批人兜底）。

    `exclude_user_id` 用于排除变更发起人，避免「发起人 = 审批人」自审自批；
    排除后无人可替时返回 0，由调用方决定回退策略。
    """
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
    )
    if exclude_user_id:
        stmt = stmt.where(SysUser.id != exclude_user_id)
    stmt = stmt.order_by(SysUser.id).limit(1)
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
