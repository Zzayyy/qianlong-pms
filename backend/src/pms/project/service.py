"""项目周期服务：立项、状态机、阶段/里程碑/任务、进度重算（设计稿 05）。"""

from __future__ import annotations

import json
from datetime import date, timedelta
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
    PrjStageMember,
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
#: 补审批标记（`t_prj_project.retro_approval`）：待审批 / 已被驳回（项目继续执行）
_RETRO_PENDING: Final[int] = 1
_RETRO_REJECTED: Final[int] = 2

logger = get_logger(__name__)


class _UnsetType:
    """哨兵类型：区分「请求未带该字段」与「显式清空（传 None）」。"""


UNSET = _UnsetType()

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


def _value_text(value: object) -> str:
    """字段值转留痕文本：空值写空串、布尔写是/否，其余直接转字符串。"""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _money_text(value: object) -> str:
    """金额统一两位小数，避免 `1000` 与 `1000.0` 被误判成前后不一致。"""
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return _value_text(value)


def _date_text(value: object) -> str:
    """日期统一 `YYYY-MM-DD`。"""
    if not value:
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)


def _field_items(pairs: list[tuple[str, object, object]]) -> list[dict[str, object]]:
    """把 (字段名, 旧值, 新值) 转成留痕明细，忽略没有变化的字段。"""
    items: list[dict[str, object]] = []
    for name, before, after in pairs:
        old_text, new_text = _value_text(before), _value_text(after)
        if old_text == new_text:
            continue
        items.append(
            {"field_name": name, "before_value": old_text, "after_value": new_text}
        )
    return items


async def _dept_label(session: AsyncSession, dept_id: int) -> str:
    """部门名称（留痕里不展示雪花 ID）。"""
    if not dept_id:
        return ""
    from pms.org.models import SysDept

    row = await session.get(SysDept, dept_id)
    return row.dept_name if row is not None else str(dept_id)


async def _user_label(session: AsyncSession, user_id: int) -> str:
    """人员姓名（留痕里不展示雪花 ID）。"""
    if not user_id:
        return ""
    from pms.org.models import SysUser

    row = await session.get(SysUser, user_id)
    return (row.real_name or row.username) if row is not None else str(user_id)


def _status_text(value: object) -> str:
    """项目状态中文名（未收录的原样返回）。"""
    text = str(value or "")
    return _PROJECT_STATUS_TEXT.get(text, text)


def _notify_text(value: object) -> str:
    """自动通知开关文本；老数据（None）按开启处理。"""
    return "是" if value is None or int(value) == 1 else "否"


async def _log_inline(
    session: AsyncSession,
    *,
    project_id: int,
    title: str,
    reason: str,
    pairs: list[tuple[str, object, object]],
    change_type: str = "OTHER",
    biz_type: str = "PROJECT",
    biz_id: int = 0,
    operator_id: int = 0,
) -> None:
    """登记「详情页编辑」变更留痕。

    实现说明：`change.service` 反向依赖本模块（审批通过要应用影响项），因此这里
    延迟导入避免循环引用；没有实际字段变化时直接跳过，不要求填原因。
    """
    items = _field_items(pairs)
    if not items:
        return
    from pms.change import service as change_service

    await change_service.record_inline(
        session,
        project_id=project_id,
        title=title,
        reason=reason,
        items=items,
        change_type=change_type,
        biz_type=biz_type,
        biz_id=biz_id or project_id,
        operator_id=operator_id,
    )


async def _notify_project(
    session: AsyncSession,
    event_code: str,
    project: PrjProject,
    operator_id: int = 0,
    reason: str = "",
) -> None:
    """发送项目相关邮件（仅入队，失败不影响主流程）。

    项目级开关 `notify_enabled` 关闭时直接跳过，避免该项目继续打扰成员；
    老数据（列为 None）按开启处理。
    """
    if project.notify_enabled is not None and int(project.notify_enabled) == 0:
        logger.info("项目已关闭自动通知，跳过邮件：%s %s", event_code, project.id)
        return
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
    stages: list[dict[str, object]] | None = None,
    director_ids: list[int] | None = None,
    auto_approve: bool = False,
    start_now: bool = False,
    retro: bool = False,
    submit_now: bool = False,
) -> PrjProject:
    """创建项目（立项来源：手工或商机转化），可同时带入成员与初始阶段。

    实现说明：负责人（PM）自动入组；`members` 每项形如
    `{"userId": 1, "deptId": 0, "roleInProject": "MEMBER", "allocation": 100}`，
    重复的成员自动跳过，不因重复而失败。
    `stages` 每项形如 `{"stageName": "设计", "ownerId": 1, "planStart": ..., "planEnd": ...}`；
    阶段负责人同样自动入组，便于其后续上报进度。
    `auto_approve=True` 时跳过审批直接置为 APPROVED 并冻结立项基线；
    `start_now=True` 时在立项通过后继续流转到 IN_PROGRESS（审批模式下忽略）。
    部门传 0 时回落到「总公司」。
    """
    project = PrjProject(
        project_code=await next_project_code(session),
        project_name=project_name,
        project_type=project_type,
        secret_level=secret_level,
        dept_id=dept_id or await default_dept_id(session),
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
    if stages:
        await create_initial_stages(session, project.id, stages)
    if director_ids:
        await set_directors(session, project.id, director_ids, context.user_id)
    if auto_approve:
        project.approval_level = await resolve_approval_level(session, float(contract_amount or 0))
        project.status = ProjectStatus.APPROVED
        await session.flush()
        await freeze_baseline(session, project.id, context.user_id)
        if retro:
            # 先开工后补审批：立即进入执行，另记「补审批期限」，逾期只在界面高亮
            days = await ConfigService(session).get_int("project.retro.days")
            project.retro_approval = 1
            project.retro_due = date.today() + timedelta(days=max(days, 1))
            await session.flush()
        if start_now or retro:
            # 复用状态流转：变更留痕与通知和详情页「启动项目」保持同一条路径
            project = await change_status(
                session,
                project.id,
                ProjectStatus.IN_PROGRESS,
                context.user_id,
                reason=(
                    "先开工后补审批：创建即启动" if retro else "创建项目时直接启动"
                ),
            )
    elif submit_now:
        # 先审批后开工：创建即提交，省掉「建草稿 → 再点一次提交」的往返
        project = await submit_for_approval(session, project.id, context.user_id)
    return project


async def update_project_basic(
    session: AsyncSession,
    project_id: int,
    *,
    dept_id: int | None = None,
    contract_amount: float | None = None,
    plan_start: str | None | _UnsetType = UNSET,
    plan_end: str | None | _UnsetType = UNSET,
    notify_enabled: bool | None = None,
    operator_id: int = 0,
    reason: str = "",
) -> PrjProject:
    """编辑立项后仍可维护的基础信息（所属部门 / 合同金额 / 计划周期 / 自动通知）。

    约定：`dept_id` / `contract_amount` / `notify_enabled` 传 None 表示不修改；
    `plan_start` / `plan_end` 用 `UNSET` 表示不修改、传 None 表示清空，便于前端把日期
    改回「未排期」。部门传 0 视为「未选择」，回落到总公司；合同金额变化时草稿态同步
    重算审批层级。

    字段确有变化时写一条「编辑项目基础信息」变更留痕，`reason` 必填。
    """
    project = await _get_project(session, project_id)
    before_dept = await _dept_label(session, project.dept_id)
    before_amount = _money_text(project.contract_amount)
    before_start = _date_text(project.plan_start)
    before_end = _date_text(project.plan_end)
    before_notify = _notify_text(project.notify_enabled)
    # 先按「本次要落库的值」校验日期，避免校验失败前已改动实体
    # 库里读出的 DATE 是 date 对象、本次传入的是字符串，统一按 ISO 文本比较
    next_start = project.plan_start if isinstance(plan_start, _UnsetType) else plan_start
    next_end = project.plan_end if isinstance(plan_end, _UnsetType) else plan_end
    if next_start and next_end and str(next_start) > str(next_end):
        raise BizRuleError("计划开始日期不能晚于计划结束日期")
    if dept_id is not None:
        project.dept_id = dept_id or await default_dept_id(session)
    if contract_amount is not None:
        project.contract_amount = contract_amount
        if project.status == ProjectStatus.DRAFT:
            project.approval_level = await resolve_approval_level(session, float(contract_amount))
    if not isinstance(plan_start, _UnsetType):
        project.plan_start = plan_start or None
    if not isinstance(plan_end, _UnsetType):
        project.plan_end = plan_end or None
    if notify_enabled is not None:
        project.notify_enabled = 1 if notify_enabled else 0
    project.update_by = operator_id or project.create_by
    await session.flush()
    await _log_inline(
        session,
        project_id=project_id,
        title="编辑项目基础信息",
        reason=reason,
        operator_id=operator_id,
        pairs=[
            ("所属部门", before_dept, await _dept_label(session, project.dept_id)),
            ("合同金额", before_amount, _money_text(project.contract_amount)),
            ("计划开始", before_start, _date_text(project.plan_start)),
            ("计划结束", before_end, _date_text(project.plan_end)),
            ("自动通知", before_notify, _notify_text(project.notify_enabled)),
        ],
    )
    return project


async def default_dept_id(session: AsyncSession) -> int:
    """立项部门缺省值：总公司（dept_code=ROOT），找不到时返回 0。"""
    from pms.org.models import SysDept

    result = await session.execute(
        select(SysDept.id).where(SysDept.dept_code == "ROOT", SysDept.deleted == 0)
    )
    return int(result.scalar_one_or_none() or 0)


async def create_initial_stages(
    session: AsyncSession, project_id: int, stages: list[dict[str, object]]
) -> list[PrjStage]:
    """立项时一次性建立阶段，并把阶段负责人与参与人加入项目组。"""
    created: list[PrjStage] = []
    for index, item in enumerate(stages, start=1):
        name = str(item.get("stageName") or "").strip()
        if not name:
            continue
        owner_id = int(item.get("ownerId") or 0)  # type: ignore[arg-type]
        if owner_id:
            await ensure_member(session, project_id, owner_id, 0, role_in_project="MEMBER")
        created.append(
            await create_stage(
                session,
                project_id,
                name,
                weight=float(item.get("weight") or 0),  # type: ignore[arg-type]
                seq=int(item.get("seq") or index),  # type: ignore[arg-type]
                owner_id=owner_id,
                plan_start=str(item["planStart"]) if item.get("planStart") else None,
                plan_end=str(item["planEnd"]) if item.get("planEnd") else None,
                member_ids=[int(uid) for uid in (item.get("memberIds") or [])],
            )
        )
    return created


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
    session: AsyncSession,
    project_id: int,
    pm_id: int,
    operator_id: int = 0,
    reason: str = "",
) -> PrjProject:
    """变更项目负责人，并自动把新负责人加入项目组（角色 PM）。

    负责人确有变化时写一条「变更项目经理」留痕，`reason` 必填。
    """
    from pms.org.models import SysUser

    project = await _get_project(session, project_id)
    before_pm = await _user_label(session, project.pm_id)
    if pm_id:
        user = await session.get(SysUser, pm_id)
        if user is None or user.deleted != 0:
            raise NotFoundError("用户不存在")
    project.pm_id = pm_id
    project.update_by = operator_id
    await session.flush()
    # 「项目经理」只对应当前负责人：旧负责人降级为普通成员，避免列表中出现多个 PM
    stmt = select(PrjMember).where(
        PrjMember.project_id == project_id,
        PrjMember.role_in_project == "PM",
        PrjMember.deleted == 0,
        PrjMember.user_id != pm_id,
    )
    for old_pm in (await session.execute(stmt)).scalars().all():
        old_pm.role_in_project = "MEMBER"
        old_pm.update_by = operator_id
    await session.flush()
    if pm_id:
        # 已是成员时提升组内角色为 PM，避免「负责人却是普通成员」
        member = await ensure_member(session, project_id, pm_id, 0, role_in_project="PM")
        if member.role_in_project != "PM":
            member.role_in_project = "PM"
            await session.flush()
    await _log_inline(
        session,
        project_id=project_id,
        title="变更项目经理",
        reason=reason,
        operator_id=operator_id,
        change_type="RESOURCE",
        pairs=[("项目经理", before_pm, await _user_label(session, pm_id))],
    )
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
    """提交立项审批：按金额确定审批层级并进入 APPROVING。

    「先开工后补审批」的项目走回溯通道：`IN_PROGRESS → APPROVING`，
    无论后面通过还是驳回都回到 `IN_PROGRESS`，不打断已开始的交付。
    """
    project = await _get_project(session, project_id)
    retro = int(project.retro_approval or 0)
    if project.status == ProjectStatus.IN_PROGRESS:
        if retro not in {_RETRO_PENDING, _RETRO_REJECTED}:
            raise BizRuleError("该项目未设置「先开工后补审批」，无需补审批")
        project.status = assert_transit(project.status, ProjectStatus.APPROVING)
        project.retro_approval = _RETRO_PENDING
        await _log_inline(
            session,
            project_id=project.id,
            title="提交补审批",
            reason="先开工后补审批",
            operator_id=operator_id,
            change_type="SCHEDULE",
            pairs=[
                (
                    "项目状态",
                    _status_text(ProjectStatus.IN_PROGRESS),
                    _status_text(ProjectStatus.APPROVING),
                )
            ],
        )
    else:
        project.status = assert_transit(project.status, ProjectStatus.APPROVING)
    project.approval_level = await resolve_approval_level(session, float(project.contract_amount))
    project.update_by = operator_id or project.create_by
    await session.flush()
    await _notify_project(session, "PROJECT_SUBMITTED", project, operator_id)
    return project


async def approve_project(session: AsyncSession, project_id: int, operator_id: int) -> PrjProject:
    """立项审批通过：进入 APPROVED 并冻结初始基线。

    补审批（先开工后补审批）走另一条路：回到 `IN_PROGRESS`、清除标记，
    基线在创建时已冻结，这里不重复冻结，避免覆盖执行中的实际进度基线。
    """
    project = await _get_project(session, project_id)
    if int(project.retro_approval or 0) == _RETRO_PENDING:
        project.status = assert_transit(project.status, ProjectStatus.IN_PROGRESS)
        project.retro_approval = 0
        project.retro_due = None
        project.update_by = operator_id
        await session.flush()
        await _log_inline(
            session,
            project_id=project.id,
            title="补审批通过",
            reason="补审批通过，项目继续执行",
            operator_id=operator_id,
            change_type="SCHEDULE",
            pairs=[
                (
                    "项目状态",
                    _status_text(ProjectStatus.APPROVING),
                    _status_text(ProjectStatus.IN_PROGRESS),
                )
            ],
        )
        await _notify_project(session, "PROJECT_APPROVED", project, operator_id)
        return project
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
    """立项驳回：草稿项目回到 DRAFT；补审批项目保持执行中，仅记录驳回原因。"""
    project = await _get_project(session, project_id)
    if int(project.retro_approval or 0) == _RETRO_PENDING:
        # 已开工的项目不因审批驳回而停摆：状态回执行中，标记「审批未通过」待整改重报
        project.status = assert_transit(project.status, ProjectStatus.IN_PROGRESS)
        project.retro_approval = _RETRO_REJECTED
        project.update_by = operator_id
        if reason:
            project.remark = reason
        await session.flush()
        await _log_inline(
            session,
            project_id=project.id,
            title="补审批驳回",
            reason=reason,
            operator_id=operator_id,
            change_type="SCHEDULE",
            pairs=[
                (
                    "项目状态",
                    _status_text(ProjectStatus.APPROVING),
                    _status_text(ProjectStatus.IN_PROGRESS),
                )
            ],
        )
        await _notify_project(session, "PROJECT_REJECTED", project, operator_id, reason)
        return project
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
    """通用状态流转（启动 / 挂起 / 完成 / 验收 / 关闭 / 终止）。

    状态确有变化时写一条「变更项目状态」留痕，`reason` 必填。
    """
    project = await _get_project(session, project_id)
    before_status = project.status
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
    await _log_inline(
        session,
        project_id=project_id,
        title="变更项目状态",
        reason=reason,
        operator_id=operator_id,
        pairs=[("项目状态", _status_text(before_status), _status_text(project.status))],
    )
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
                "ownerId": stage.owner_id,
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


async def set_stage_members(
    session: AsyncSession,
    project_id: int,
    stage_id: int,
    user_ids: list[int],
    operator_id: int = 0,
) -> list[int]:
    """覆盖式设置阶段参与人，并把这些人补进项目组（幂等）。

    返回最终生效的 user_id 列表（去重保序、剔除 0）。负责人不在此表，
    仍记在 `t_prj_stage.owner_id`。
    """
    final: list[int] = []
    for raw in user_ids:
        uid = int(raw or 0)
        if uid > 0 and uid not in final:
            final.append(uid)

    rows = (
        await session.execute(
            select(PrjStageMember)
            .where(PrjStageMember.stage_id == stage_id)
            .order_by(PrjStageMember.id)
        )
    ).scalars()
    keep: dict[int, PrjStageMember] = {}
    for row in rows:
        uid = int(row.user_id)
        if uid in keep:
            # 历史重复行合并，只保留最早一条
            row.deleted = 1
            row.update_by = operator_id
            continue
        keep[uid] = row
    for uid, row in keep.items():
        row.deleted = 0 if uid in final else 1
        row.update_by = operator_id
    for uid in final:
        if uid in keep:
            continue
        session.add(
            PrjStageMember(stage_id=stage_id, user_id=uid, create_by=operator_id)
        )
        await ensure_member(session, project_id, uid, 0, role_in_project="MEMBER")
    await session.flush()
    return final


async def list_stage_members(
    session: AsyncSession, stage_ids: list[int]
) -> dict[int, list[int]]:
    """批量查阶段参与人，返回 `{stage_id: [user_id, ...]}`。"""
    if not stage_ids:
        return {}
    result = await session.execute(
        select(PrjStageMember.stage_id, PrjStageMember.user_id)
        .where(
            PrjStageMember.stage_id.in_(stage_ids),
            PrjStageMember.deleted == 0,
        )
        .order_by(PrjStageMember.id)
    )
    mapping: dict[int, list[int]] = {}
    for stage_id, user_id in result.all():
        mapping.setdefault(int(stage_id), []).append(int(user_id))
    return mapping


async def create_stage(
    session: AsyncSession,
    project_id: int,
    stage_name: str,
    weight: float = 0,
    seq: int = 1,
    owner_id: int = 0,
    plan_start: str | None = None,
    plan_end: str | None = None,
    operator_id: int = 0,
    reason: str = "",
    member_ids: list[int] | None = None,
) -> PrjStage:
    """创建阶段。

    `operator_id` 为空表示系统批量创建（立项建初始阶段），此时不留变更记录。
    """
    stage = PrjStage(
        project_id=project_id,
        stage_name=stage_name,
        weight=weight,
        seq=seq,
        owner_id=owner_id,
        plan_start=plan_start,
        plan_end=plan_end,
    )
    session.add(stage)
    await session.flush()
    if member_ids:
        await set_stage_members(session, project_id, stage.id, member_ids, operator_id)
    if operator_id:
        await _log_inline(
            session,
            project_id=project_id,
            title="新增阶段",
            reason=reason,
            operator_id=operator_id,
            change_type="SCHEDULE",
            biz_type="STAGE",
            biz_id=stage.id,
            pairs=[
                ("阶段名称", "", stage.stage_name),
                ("负责人", "", await _user_label(session, stage.owner_id)),
                ("计划开始", "", _date_text(stage.plan_start)),
                ("计划结束", "", _date_text(stage.plan_end)),
                ("权重", "", f"{float(stage.weight or 0):.0f}"),
            ],
        )
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
    operator_id: int = 0,
    reason: str = "",
) -> PrjMilestone:
    """创建里程碑；`operator_id` 非空时写「新增里程碑」留痕（`reason` 必填）。"""
    milestone = PrjMilestone(
        project_id=project_id,
        milestone_name=milestone_name,
        plan_date=plan_date,
        owner_id=owner_id,
    )
    session.add(milestone)
    await session.flush()
    if operator_id:
        await _log_inline(
            session,
            project_id=project_id,
            title="新增里程碑",
            reason=reason,
            operator_id=operator_id,
            change_type="SCHEDULE",
            biz_type="MILESTONE",
            biz_id=milestone.id,
            pairs=[
                ("里程碑名称", "", milestone.milestone_name),
                ("计划日期", "", _date_text(milestone.plan_date)),
                ("负责人", "", await _user_label(session, milestone.owner_id)),
            ],
        )
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
    owner_id: int = 0,
    operator_id: int = 0,
    reason: str = "",
    member_ids: list[int] | None = None,
) -> PrjStage:
    """编辑阶段（名称/权重/序号/负责人/计划起止/参与人）。

    `member_ids` 为 None 表示本次不改参与人，传空列表则清空。

    字段确有变化时写一条「编辑阶段」留痕，`reason` 必填。
    """
    stage = await _get_stage(session, project_id, stage_id)
    before_name = stage.stage_name
    before_owner = await _user_label(session, stage.owner_id)
    before_start = _date_text(stage.plan_start)
    before_end = _date_text(stage.plan_end)
    before_weight = f"{float(stage.weight or 0):.0f}"
    stage.stage_name = stage_name
    stage.weight = weight
    stage.seq = seq
    stage.owner_id = owner_id
    if owner_id:
        await ensure_member(session, project_id, owner_id, 0, role_in_project="MEMBER")
    stage.plan_start = plan_start
    stage.plan_end = plan_end
    stage.update_by = operator_id
    await session.flush()
    if member_ids is not None:
        await set_stage_members(session, project_id, stage.id, member_ids, operator_id)
    await recalc_progress(session, project_id)
    await _log_inline(
        session,
        project_id=project_id,
        title="编辑阶段",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="STAGE",
        biz_id=stage.id,
        pairs=[
            ("阶段名称", before_name, stage.stage_name),
            ("负责人", before_owner, await _user_label(session, stage.owner_id)),
            ("计划开始", before_start, _date_text(stage.plan_start)),
            ("计划结束", before_end, _date_text(stage.plan_end)),
            ("权重", before_weight, f"{float(stage.weight or 0):.0f}"),
        ],
    )
    return stage


async def delete_stage(
    session: AsyncSession,
    project_id: int,
    stage_id: int,
    operator_id: int = 0,
    reason: str = "",
) -> None:
    """删除阶段（存在关联任务时拒绝，避免任务悬挂）；`reason` 必填。"""
    stage = await _get_stage(session, project_id, stage_id)
    count_stmt = select(func.count(PrjTask.id)).where(
        PrjTask.project_id == project_id,
        PrjTask.stage_id == stage_id,
        PrjTask.deleted == 0,
    )
    if int((await session.execute(count_stmt)).scalar_one()) > 0:
        raise ConflictError("该阶段下仍有任务，请先移出或删除任务")
    stage_name = stage.stage_name
    stage.deleted = 1
    stage.update_by = operator_id
    await session.flush()
    await recalc_progress(session, project_id)
    await _log_inline(
        session,
        project_id=project_id,
        title="删除阶段",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="STAGE",
        biz_id=stage_id,
        pairs=[("阶段", stage_name, "已删除")],
    )


async def change_stage_status(
    session: AsyncSession,
    project_id: int,
    stage_id: int,
    target: str,
    operator_id: int = 0,
    reason: str = "",
) -> PrjStage:
    """推进阶段状态；完成前按参数校验节点交付文档（R-PRJ-06）；`reason` 必填。"""
    stage = await _get_stage(session, project_id, stage_id)
    before_status = stage.status
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
    await _log_inline(
        session,
        project_id=project_id,
        title="变更阶段状态",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="STAGE",
        biz_id=stage_id,
        pairs=[("阶段状态", str(before_status), str(stage.status))],
    )
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
    reason: str = "",
) -> PrjMilestone:
    """编辑里程碑；字段确有变化时写「编辑里程碑」留痕（`reason` 必填）。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    before_name = milestone.milestone_name
    before_date = _date_text(milestone.plan_date)
    before_owner = await _user_label(session, milestone.owner_id)
    milestone.milestone_name = milestone_name
    milestone.plan_date = plan_date
    milestone.owner_id = owner_id
    milestone.update_by = operator_id
    await session.flush()
    await _log_inline(
        session,
        project_id=project_id,
        title="编辑里程碑",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="MILESTONE",
        biz_id=milestone_id,
        pairs=[
            ("里程碑名称", before_name, milestone.milestone_name),
            ("计划日期", before_date, _date_text(milestone.plan_date)),
            ("负责人", before_owner, await _user_label(session, milestone.owner_id)),
        ],
    )
    return milestone


async def delete_milestone(
    session: AsyncSession,
    project_id: int,
    milestone_id: int,
    operator_id: int = 0,
    reason: str = "",
) -> None:
    """删除里程碑（软删）；`reason` 必填。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    milestone_name = milestone.milestone_name
    milestone.deleted = 1
    milestone.update_by = operator_id
    await session.flush()
    await _log_inline(
        session,
        project_id=project_id,
        title="删除里程碑",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="MILESTONE",
        biz_id=milestone_id,
        pairs=[("里程碑", milestone_name, "已删除")],
    )


async def change_milestone_status(
    session: AsyncSession,
    project_id: int,
    milestone_id: int,
    target: str,
    operator_id: int = 0,
    reason: str = "",
) -> PrjMilestone:
    """里程碑达成/延期/取消登记；状态变化写留痕（`reason` 必填）。"""
    milestone = await _get_milestone(session, project_id, milestone_id)
    before_status = milestone.status
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
    await _log_inline(
        session,
        project_id=project_id,
        title="变更里程碑状态",
        reason=reason,
        operator_id=operator_id,
        change_type="SCHEDULE",
        biz_type="MILESTONE",
        biz_id=milestone_id,
        pairs=[("里程碑状态", str(before_status), str(milestone.status))],
    )
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
