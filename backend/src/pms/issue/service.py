"""问题跟踪服务：Bug 与生产问题的登记、指派、状态流转与查询。"""

from __future__ import annotations

from datetime import date
from typing import Final

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, DataForbiddenError, NotFoundError
from pms.core.context import AuthContext
from pms.issue.models import IssIssue, IssLog
from pms.issue.state import ISSUE_STATUSES, ISSUE_TYPES, IssueStatus
from pms.project.models import PrjProject

#: 编号前缀：Bug 用 BUG，生产问题用 PRD
_NO_PREFIX: Final[dict[str, str]] = {"BUG": "BUG", "PROD": "PRD"}


def _normalize_type(value: str | None) -> str:
    """归一化问题类型，未知类型按 Bug 兜底。"""
    text = (value or "").strip().upper()
    return text if text in ISSUE_TYPES else "BUG"


async def _next_no(session: AsyncSession, issue_type: str) -> str:
    """生成问题编号（按类型各自计数 +1，如 BUG-0001 / PRD-0001）。"""
    prefix = _NO_PREFIX.get(issue_type, "ISS")
    result = await session.execute(
        select(func.count(IssIssue.id)).where(
            IssIssue.deleted == 0,
            IssIssue.issue_type == issue_type,
        )
    )
    return f"{prefix}-{int(result.scalar_one() or 0) + 1:04d}"


async def _ensure_project(session: AsyncSession, project_id: int) -> None:
    """校验问题关联的项目存在。"""
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        raise NotFoundError("项目不存在")


def _date_text(value: object) -> str:
    """日期列值统一转成 ISO 文本（`date` 对象与字符串都能比）。"""
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)


async def _display_name(session: AsyncSession, user_id: int) -> str:
    """取人员显示名（历史记录里「指派给谁」用）。"""
    if not user_id:
        return "未指派"
    from pms.org.models import SysUser

    user = await session.get(SysUser, user_id)
    if user is None:
        return f"用户{user_id}"
    return str(user.real_name or user.username or user_id)


def _add_log(
    session: AsyncSession,
    issue_id: int,
    operator_id: int,
    action: str,
    field: str = "",
    old_value: object = "",
    new_value: object = "",
) -> None:
    """写一条操作历史（字段级留痕，便于详情页「历史记录」展示）。"""
    session.add(
        IssLog(
            issue_id=issue_id,
            action=action,
            field=field,
            old_value=str(old_value)[:500],
            new_value=str(new_value)[:500],
            operator_id=operator_id,
            create_by=operator_id,
        )
    )


async def create_issue(
    session: AsyncSession,
    context: AuthContext,
    *,
    issue_type: str,
    project_id: int,
    title: str,
    description: str = "",
    severity: str = "MEDIUM",
    priority: str = "MEDIUM",
    owner_id: int = 0,
    found_date: str | None = None,
    remark: str = "",
) -> IssIssue:
    """登记一条问题（所有人可提，类型决定进 Bug 列表还是生产问题列表）。"""
    text = (title or "").strip()
    if not text:
        raise BizRuleError("请填写问题标题")
    if project_id <= 0:
        raise BizRuleError("请选择项目")
    await _ensure_project(session, project_id)
    kind = _normalize_type(issue_type)
    issue = IssIssue(
        issue_no=await _next_no(session, kind),
        issue_type=kind,
        project_id=project_id,
        title=text,
        description=description or "",
        severity=(severity or "MEDIUM").upper(),
        priority=(priority or "MEDIUM").upper(),
        status=IssueStatus.OPEN,
        owner_id=owner_id,
        reporter_id=context.user_id,
        found_date=found_date or date.today().isoformat(),
        remark=remark or "",
        create_by=context.user_id,
    )
    session.add(issue)
    await session.flush()
    _add_log(
        session,
        issue.id,
        context.user_id,
        "CREATE",
        new_value=f"{issue.issue_no} {issue.title}",
    )
    await session.flush()
    return issue


async def get_issue(session: AsyncSession, issue_id: int) -> IssIssue:
    """按 ID 取问题单。"""
    issue = await session.get(IssIssue, issue_id)
    if issue is None or issue.deleted:
        raise NotFoundError("问题不存在")
    return issue


def _ensure_can_edit(
    issue: IssIssue, context: AuthContext, can_manage: bool
) -> None:
    """编辑口径：提报人 / 负责人 / 具备问题维护权限。"""
    if can_manage:
        return
    if context.user_id in {int(issue.reporter_id or 0), int(issue.owner_id or 0)}:
        return
    raise DataForbiddenError("仅提报人、负责人或问题管理员可修改")


async def update_issue(
    session: AsyncSession,
    issue_id: int,
    context: AuthContext,
    *,
    can_manage: bool = False,
    title: str | None = None,
    description: str | None = None,
    severity: str | None = None,
    priority: str | None = None,
    owner_id: int | None = None,
    found_date: str | None = None,
    remark: str | None = None,
    project_id: int | None = None,
) -> IssIssue:
    """编辑问题内容与指派（项目可改，类型不可改）。"""
    issue = await get_issue(session, issue_id)
    _ensure_can_edit(issue, context, can_manage)
    changes: list[tuple[str, object, object]] = []
    if title is not None:
        text = title.strip()
        if not text:
            raise BizRuleError("请填写问题标题")
        if text != issue.title:
            changes.append(("title", issue.title, text))
            issue.title = text
    if project_id is not None and project_id != int(issue.project_id or 0):
        if project_id <= 0:
            raise BizRuleError("请选择项目")
        await _ensure_project(session, project_id)
        changes.append(("projectId", issue.project_id, project_id))
        issue.project_id = project_id
    if description is not None and description != issue.description:
        changes.append(("description", issue.description, description))
        issue.description = description
    if severity is not None and severity.upper() != issue.severity:
        changes.append(("severity", issue.severity, severity.upper()))
        issue.severity = severity.upper()
    if priority is not None and priority.upper() != issue.priority:
        changes.append(("priority", issue.priority, priority.upper()))
        issue.priority = priority.upper()
    if owner_id is not None and owner_id != int(issue.owner_id or 0):
        old_name = await _display_name(session, int(issue.owner_id or 0))
        new_name = await _display_name(session, owner_id)
        changes.append(("ownerId", old_name, new_name))
        issue.owner_id = owner_id
    if found_date is not None:
        # 列值可能已从库里取成 date 对象，入参是字符串，统一按 ISO 文本比较
        old_found = _date_text(issue.found_date)
        new_found = _date_text(found_date)
        if new_found != old_found:
            changes.append(("foundDate", old_found, new_found))
            issue.found_date = found_date or None
    if remark is not None and remark != issue.remark:
        changes.append(("remark", issue.remark, remark))
        issue.remark = remark
    if changes:
        for field, old_value, new_value in changes:
            _add_log(
                session,
                issue.id,
                context.user_id,
                "UPDATE",
                field,
                old_value,
                new_value,
            )
        issue.update_by = context.user_id
    await session.flush()
    return issue


async def change_status(
    session: AsyncSession,
    issue_id: int,
    context: AuthContext,
    status: str,
    *,
    can_manage: bool = False,
) -> IssIssue:
    """流转状态：待处理 / 处理中 / 已关闭（关闭记关闭日期，重开清空）。"""
    value = (status or "").strip().upper()
    if value not in ISSUE_STATUSES:
        raise BizRuleError("问题状态无效")
    issue = await get_issue(session, issue_id)
    _ensure_can_edit(issue, context, can_manage)
    old_status = issue.status
    issue.status = value
    issue.close_date = date.today().isoformat() if value == IssueStatus.CLOSED else None
    issue.update_by = context.user_id
    if value != old_status:
        _add_log(session, issue.id, context.user_id, "STATUS", "status", old_status, value)
    await session.flush()
    return issue


async def delete_issue(
    session: AsyncSession,
    issue_id: int,
    context: AuthContext,
    *,
    can_manage: bool = False,
) -> None:
    """软删除问题（仅提报人 / 负责人 / 问题管理员）。"""
    issue = await get_issue(session, issue_id)
    _ensure_can_edit(issue, context, can_manage)
    issue.deleted = 1
    issue.update_by = context.user_id
    _add_log(session, issue.id, context.user_id, "DELETE", new_value=issue.issue_no)
    await session.flush()


def _filters(
    *,
    issue_type: str = "",
    project_id: int = 0,
    status: str = "",
    severity: str = "",
    keyword: str = "",
    owner_id: int = 0,
    reporter_id: int = 0,
) -> list[ColumnElement[bool]]:
    """构造查询条件（列表与计数共用）。"""
    conditions: list[ColumnElement[bool]] = [IssIssue.deleted == 0]
    if issue_type:
        conditions.append(IssIssue.issue_type == issue_type.upper())
    if project_id:
        conditions.append(IssIssue.project_id == project_id)
    if status:
        conditions.append(IssIssue.status == status.upper())
    if severity:
        conditions.append(IssIssue.severity == severity.upper())
    if owner_id:
        conditions.append(IssIssue.owner_id == owner_id)
    if reporter_id:
        conditions.append(IssIssue.reporter_id == reporter_id)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        conditions.append(
            or_(
                IssIssue.title.like(like),
                IssIssue.description.like(like),
                IssIssue.issue_no.like(like),
            )
        )
    return conditions


async def list_issues(
    session: AsyncSession,
    *,
    issue_type: str = "",
    project_id: int = 0,
    status: str = "",
    severity: str = "",
    keyword: str = "",
    owner_id: int = 0,
    reporter_id: int = 0,
    offset: int = 0,
    limit: int = 10,
) -> list[IssIssue]:
    """分页查询问题列表（未关闭优先，其次按创建时间倒序）。"""
    stmt = (
        select(IssIssue)
        .where(
            *_filters(
                issue_type=issue_type,
                project_id=project_id,
                status=status,
                severity=severity,
                keyword=keyword,
                owner_id=owner_id,
                reporter_id=reporter_id,
            )
        )
        .order_by(IssIssue.status == IssueStatus.CLOSED, IssIssue.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_issues(
    session: AsyncSession,
    *,
    issue_type: str = "",
    project_id: int = 0,
    status: str = "",
    severity: str = "",
    keyword: str = "",
    owner_id: int = 0,
    reporter_id: int = 0,
) -> int:
    """问题条数（与列表条件一致）。"""
    result = await session.execute(
        select(func.count(IssIssue.id)).where(
            *_filters(
                issue_type=issue_type,
                project_id=project_id,
                status=status,
                severity=severity,
                keyword=keyword,
                owner_id=owner_id,
                reporter_id=reporter_id,
            )
        )
    )
    return int(result.scalar_one() or 0)


async def open_count(session: AsyncSession, issue_type: str = "") -> int:
    """未关闭问题数（菜单角标用）。"""
    conditions: list[ColumnElement[bool]] = [
        IssIssue.deleted == 0,
        IssIssue.status != IssueStatus.CLOSED,
    ]
    if issue_type:
        conditions.append(IssIssue.issue_type == issue_type.upper())
    result = await session.execute(select(func.count(IssIssue.id)).where(*conditions))
    return int(result.scalar_one() or 0)


async def list_logs(session: AsyncSession, issue_id: int) -> list[IssLog]:
    """问题操作历史（新的在前）。"""
    result = await session.execute(
        select(IssLog)
        .where(IssLog.issue_id == issue_id, IssLog.deleted == 0)
        .order_by(IssLog.id.desc())
    )
    return list(result.scalars().all())
