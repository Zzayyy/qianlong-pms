"""邮件通知管理接口：发件配置、模板、发送记录。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, NotFoundError, ParamError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.notice import mail
from pms.org.models import SysDept, SysRole, SysUser, SysUserRole
from pms.system.config_service import ConfigService, validate_value
from pms.system.models import SysMailLog, SysMailTemplate

router = APIRouter(prefix="/api/v1/mail", tags=["邮件通知"])

_TAG = "sys:config"
#: 富文本正文上限：与数据库 TEXT 列的容量匹配，避免超长正文被截断或写库失败
_MAX_BODY_CHARS = 15000
_CONFIG_KEYS = (
    "notify.mail.enabled",
    "notify.mail.smtpHost",
    "notify.mail.smtpPort",
    "notify.mail.security",
    "notify.mail.smtpUser",
    "notify.mail.password",
    "notify.mail.smtpFrom",
    "notify.mail.fromName",
    "notify.mail.timeoutSeconds",
    "notify.mail.keepDays",
    "notify.mail.excludeOperator",
    "notify.mail.testTo",
)


class MailConfigIn(BaseModel):
    """发件配置保存入参；password 为空表示不修改。"""

    enabled: bool = True
    smtpHost: str = Field(default="", max_length=255)
    smtpPort: int = Field(default=465, ge=1, le=65535)
    security: str = Field(default="SSL", max_length=16)
    smtpUser: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=255)
    smtpFrom: str = Field(default="", max_length=255)
    fromName: str = Field(default="PMS 项目管理", max_length=64)
    timeoutSeconds: int = Field(default=15, ge=3, le=120)
    keepDays: int = Field(default=180, ge=7, le=3650)
    excludeOperator: bool = True
    testTo: str = Field(default="", max_length=255)


class MailTestIn(BaseModel):
    """测试发信入参。"""

    to: str = Field(min_length=3, max_length=255)


class MailSendIn(BaseModel):
    """手动发信入参：按人员 / 角色 / 部门取并集。"""

    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=_MAX_BODY_CHARS)
    #: 正文是否为富文本 HTML（写邮件页面固定传 true，兼容旧的纯文本调用方）
    html: bool = False
    userIds: list[int] = Field(default_factory=list)
    roleCodes: list[str] = Field(default_factory=list)
    deptIds: list[int] = Field(default_factory=list)


class MailRecipientsIn(BaseModel):
    """收件人预统计入参（与发信一致的三种选择方式）。"""

    userIds: list[int] = Field(default_factory=list)
    roleCodes: list[str] = Field(default_factory=list)
    deptIds: list[int] = Field(default_factory=list)


class TemplateIn(BaseModel):
    """模板保存入参。"""

    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)
    receiverRoles: str = Field(default="", max_length=255)
    enabled: bool = True


@router.get("/config", summary="邮件发件配置")
async def get_config(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """返回发件配置（密码脱敏）。"""
    del context
    config = ConfigService(session)
    password = await config.get_str("notify.mail.password")
    return ok(
        {
            "enabled": await config.get_bool("notify.mail.enabled"),
            "smtpHost": await config.get_str("notify.mail.smtpHost"),
            "smtpPort": await config.get_int("notify.mail.smtpPort"),
            "security": await config.get_str("notify.mail.security") or "SSL",
            "smtpUser": await config.get_str("notify.mail.smtpUser"),
            "passwordSet": bool(password),
            "smtpFrom": await config.get_str("notify.mail.smtpFrom"),
            "fromName": await config.get_str("notify.mail.fromName"),
            "timeoutSeconds": await config.get_int("notify.mail.timeoutSeconds"),
            "keepDays": await config.get_int("notify.mail.keepDays"),
            "excludeOperator": await config.get_bool("notify.mail.excludeOperator"),
            "testTo": await config.get_str("notify.mail.testTo"),
        }
    )


@router.put("/config", summary="保存邮件发件配置")
async def save_config(
    body: MailConfigIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """保存发件配置；密码仅在填写新值时覆盖。"""
    security = (body.security or "SSL").upper()
    if security not in {"SSL", "STARTTLS", "NONE"}:
        raise ParamError("加密方式只支持 SSL / STARTTLS / NONE")
    values: dict[str, str] = {
        "notify.mail.enabled": "true" if body.enabled else "false",
        "notify.mail.smtpHost": body.smtpHost.strip(),
        "notify.mail.smtpPort": str(body.smtpPort),
        "notify.mail.security": security,
        "notify.mail.smtpUser": body.smtpUser.strip(),
        "notify.mail.smtpFrom": body.smtpFrom.strip(),
        "notify.mail.fromName": body.fromName.strip(),
        "notify.mail.timeoutSeconds": str(body.timeoutSeconds),
        "notify.mail.keepDays": str(body.keepDays),
        "notify.mail.excludeOperator": "true" if body.excludeOperator else "false",
        "notify.mail.testTo": body.testTo.strip(),
    }
    if body.password and body.password != "******":
        values["notify.mail.password"] = mail.encrypt_secret(body.password)
    config = ConfigService(session)
    for key, raw in values.items():
        await config.set_value(key, validate_value(key, raw), operator_id=context.user_id)
    await session.commit()
    return ok({"saved": len(values)})


@router.get("/options", summary="写邮件收件人选项")
async def recipient_options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """写邮件页面用的人员 / 角色 / 部门选项与邮件通道状态。

    只下发姓名、账号、所属部门与「是否维护了邮箱」，不下发邮箱地址本身。
    """
    del context
    account = await mail.load_account(session)
    users = (
        await session.execute(
            select(
                SysUser.id,
                SysUser.username,
                SysUser.real_name,
                SysUser.dept_id,
                SysUser.email,
            )
            .where(SysUser.deleted == 0, SysUser.status == "ENABLED")
            .order_by(SysUser.dept_id, SysUser.real_name, SysUser.id)
        )
    ).all()
    depts = (
        await session.execute(
            select(SysDept.id, SysDept.parent_id, SysDept.dept_name)
            .where(SysDept.deleted == 0)
            .order_by(SysDept.level, SysDept.sort, SysDept.id)
        )
    ).all()
    roles = (
        await session.execute(
            select(SysRole.id, SysRole.role_code, SysRole.role_name)
            .where(SysRole.deleted == 0, SysRole.status == "ENABLED")
            .order_by(SysRole.sort, SysRole.id)
        )
    ).all()
    role_members = (
        await session.execute(
            select(SysUserRole.role_id, SysUserRole.user_id)
            .join(SysUser, SysUser.id == SysUserRole.user_id)
            .where(
                SysUserRole.deleted == 0,
                SysUser.deleted == 0,
                SysUser.status == "ENABLED",
            )
        )
    ).all()

    active_ids = {int(user_row.id) for user_row in users}
    role_counts: dict[int, int] = {}
    for link in role_members:
        if int(link.user_id) in active_ids:
            role_counts[int(link.role_id)] = role_counts.get(int(link.role_id), 0) + 1
    dept_counts: dict[int, int] = {}
    for user_row in users:
        dept_key = int(user_row.dept_id or 0)
        dept_counts[dept_key] = dept_counts.get(dept_key, 0) + 1

    return ok(
        {
            "ready": bool(account.enabled and account.host and account.sender),
            "sender": account.sender,
            "fromName": account.from_name,
            "testTo": account.test_to,
            "users": [
                {
                    "id": row.id,
                    "username": row.username,
                    "realName": row.real_name,
                    "deptId": row.dept_id,
                    "hasEmail": bool((row.email or "").strip()),
                }
                for row in users
            ],
            "depts": [
                {
                    "id": row.id,
                    "parentId": row.parent_id,
                    "deptName": row.dept_name,
                    "userCount": dept_counts.get(int(row.id), 0),
                }
                for row in depts
            ],
            "roles": [
                {
                    "roleCode": row.role_code,
                    "roleName": row.role_name,
                    "userCount": role_counts.get(int(row.id), 0),
                }
                for row in roles
            ],
        }
    )


async def _resolve_recipient_ids(
    session: AsyncSession,
    *,
    user_ids: list[int],
    role_codes: list[str],
    dept_ids: list[int],
) -> set[int]:
    """人员 / 角色 / 部门三种方式取并集。"""
    ids = {int(uid) for uid in user_ids if uid}
    ids |= await mail.role_user_ids(session, role_codes)
    dept_set = {int(did) for did in dept_ids if did}
    if dept_set:
        result = await session.execute(
            select(SysUser.id).where(
                SysUser.deleted == 0,
                SysUser.status == "ENABLED",
                SysUser.dept_id.in_(dept_set),
            )
        )
        ids |= {int(uid) for uid in result.scalars().all()}
    return ids


@router.post("/recipients", summary="预估收件人")
async def estimate_recipients(
    body: MailRecipientsIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """发送前预统计：实际收件人数、无邮箱跳过人数、前几位收件人姓名。"""
    del context
    ids = await _resolve_recipient_ids(
        session,
        user_ids=body.userIds,
        role_codes=body.roleCodes,
        dept_ids=body.deptIds,
    )
    users = await mail.load_users(session, ids)
    account = await mail.load_account(session)
    no_email = [user for user in users if not (user.email or "").strip()]
    # 配置了测试收件人时，无邮箱人员也会发到测试邮箱，不算跳过
    skipped = 0 if account.test_to else len(no_email)
    names = [user.real_name or user.username for user in users[:8]]
    return ok(
        {
            "recipients": len(users) - skipped,
            "noEmail": skipped,
            "total": len(users),
            "names": names,
            "testTo": account.test_to,
            "ready": bool(account.enabled and account.host and account.sender),
        }
    )



@router.post("/test", summary="发送测试邮件")
async def test_send(
    body: MailTestIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """按当前配置发送一封测试邮件，失败直接返回错误信息。"""
    del context
    try:
        await mail.send_test(session, body.to.strip())
    except Exception as exc:  # noqa: BLE001 - 原样回显 SMTP 错误，便于排查
        raise BizRuleError(f"发送失败：{exc}") from exc
    return ok({"sent": True})


@router.post("/send", summary="手动发送邮件")
async def send_mail(
    body: MailSendIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """按人员 / 角色 / 部门选择收件人，立即发送一封自定义邮件。"""
    ids = await _resolve_recipient_ids(
        session,
        user_ids=body.userIds,
        role_codes=body.roleCodes,
        dept_ids=body.deptIds,
    )
    # 手动发信不排除操作人本人：允许给自己发测试邮件
    if not ids:
        raise ParamError("请至少选择一名收件人")
    users = await mail.load_users(session, ids)
    if not users:
        raise ParamError("收件人不存在或已停用")
    try:
        rows, skipped = await mail.enqueue_manual(
            session,
            subject=body.subject,
            content=body.content,
            users=users,
            operator_id=context.user_id,
            as_html=body.html,
        )
    except ValueError as exc:
        raise BizRuleError(str(exc)) from exc
    await session.commit()
    result = await mail.dispatch_rows(session, rows)
    return ok(
        {
            "recipients": len(users),
            "queued": len(rows),
            "skipped": skipped,
            **result,
        }
    )


@router.get("/templates", summary="邮件模板列表")
async def list_templates(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """内置事件模板 + 库中自定义内容。"""
    del context
    result = await session.execute(
        select(SysMailTemplate).where(SysMailTemplate.deleted == 0)
    )
    stored = {row.event_code: row for row in result.scalars().all()}
    items = []
    for event in mail.EVENTS:
        row = stored.get(event["eventCode"])
        items.append(
            {
                "eventCode": event["eventCode"],
                "name": event["name"],
                "message": event["message"],
                "subject": row.subject if row else event["subject"],
                "body": row.body if row else event["body"],
                "receiverRoles": (
                    row.receiver_roles if row else event["receiverRoles"]
                ),
                "enabled": bool(row.enabled) if row else True,
                "customized": row is not None,
            }
        )
    return ok(items)


@router.put("/templates/{event_code}", summary="保存邮件模板")
async def save_template(
    event_code: str,
    body: TemplateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """按事件编码保存模板（不存在则新建）。"""
    if event_code not in mail.DEFAULT_TEMPLATES:
        raise NotFoundError("事件不存在")
    result = await session.execute(
        select(SysMailTemplate).where(
            SysMailTemplate.deleted == 0, SysMailTemplate.event_code == event_code
        )
    )
    row = result.scalars().first()
    if row is None:
        row = SysMailTemplate(
            event_code=event_code,
            name=mail.DEFAULT_TEMPLATES[event_code]["name"],
            builtin=1,
            create_by=context.user_id,
        )
        session.add(row)
    row.subject = body.subject.strip()
    row.body = body.body
    row.receiver_roles = body.receiverRoles.strip()
    row.enabled = 1 if body.enabled else 0
    row.update_by = context.user_id
    await session.commit()
    return ok({"eventCode": event_code})


@router.post("/templates/{event_code}/reset", summary="恢复默认模板")
async def reset_template(
    event_code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """删除自定义模板，回落到内置模板。"""
    if event_code not in mail.DEFAULT_TEMPLATES:
        raise NotFoundError("事件不存在")
    result = await session.execute(
        select(SysMailTemplate).where(
            SysMailTemplate.deleted == 0, SysMailTemplate.event_code == event_code
        )
    )
    row = result.scalars().first()
    if row is not None:
        row.deleted = 1
        row.update_by = context.user_id
        await session.commit()
    return ok({"eventCode": event_code, "reset": True})


@router.get("/logs", summary="邮件发送记录")
async def list_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    status: Annotated[str, Query(max_length=16)] = "",
    eventCode: Annotated[str, Query(max_length=64)] = "",
    keyword: Annotated[str, Query(max_length=128)] = "",
) -> object:
    """分页查询发送记录。"""
    del context
    conditions = [SysMailLog.deleted == 0]
    if status:
        conditions.append(SysMailLog.status == status.upper())
    if eventCode:
        conditions.append(SysMailLog.event_code == eventCode)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        conditions.append(
            SysMailLog.recipient.like(like) | SysMailLog.subject.like(like)
        )
    total = int(
        (
            await session.execute(
                select(func.count(SysMailLog.id)).where(*conditions)
            )
        ).scalar_one()
        or 0
    )
    result = await session.execute(
        select(SysMailLog)
        .where(*conditions)
        .order_by(SysMailLog.id.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    rows = list(result.scalars().all())
    return paged(
        [
            {
                "id": row.id,
                "eventCode": row.event_code,
                "eventName": "手动发送"
                if row.event_code == "MANUAL"
                else mail.DEFAULT_TEMPLATES.get(row.event_code, {}).get(
                    "name", row.event_code
                ),
                "recipient": row.recipient,
                "recipientName": row.recipient_name,
                "subject": row.subject,
                "status": row.status,
                "retryCount": row.retry_count,
                "error": row.error,
                "bizType": row.biz_type,
                "bizId": row.biz_id,
                "sentAt": row.sent_at.isoformat(sep=" ") if row.sent_at else "",
                "createTime": row.create_time.isoformat(sep=" ") if row.create_time else "",
            }
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/logs/{log_id}", summary="邮件发送记录详情")
async def log_detail(
    log_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """查看单条发送记录（含正文 HTML，用于发送记录里的内容预览）。"""
    del context
    row = await session.get(SysMailLog, log_id)
    if row is None or row.deleted != 0:
        raise NotFoundError("发送记录不存在")
    return ok(
        {
            "id": row.id,
            "eventCode": row.event_code,
            "eventName": "手动发送"
            if row.event_code == "MANUAL"
            else mail.DEFAULT_TEMPLATES.get(row.event_code, {}).get("name", row.event_code),
            "recipient": row.recipient,
            "recipientName": row.recipient_name,
            "subject": row.subject,
            "body": row.body,
            "status": row.status,
            "retryCount": row.retry_count,
            "error": row.error,
            "sentAt": row.sent_at.isoformat(sep=" ") if row.sent_at else "",
            "createTime": row.create_time.isoformat(sep=" ") if row.create_time else "",
        }
    )


@router.post("/logs/{log_id}/resend", summary="重发邮件")
async def resend_log(
    log_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions(_TAG))],
) -> object:
    """手动重发一条失败/已发送记录。"""
    del context
    try:
        await mail.resend(session, log_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise BizRuleError(f"重发失败：{exc}") from exc
    return ok({"resent": True})
