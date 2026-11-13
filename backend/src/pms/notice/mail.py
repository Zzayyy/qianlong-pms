"""邮件通知：发件配置、模板渲染、待发队列（outbox）与异步发送。

设计要点：
- 业务事务内只写 `t_sys_mail_log`（PENDING），不直接连 SMTP，避免拖慢业务；
- 定时任务 `mail_dispatch` 抢占待发记录并发送，失败按指数退避重试；
- SMTP 密码使用 Fernet（密钥由 `APP_SECRET_KEY` 派生）加密后存入 `t_sys_config`；
- 模板按事件编码存库，未自定义时回落到内置模板。
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from typing import Final

import aiosmtplib
from cryptography.fernet import Fernet, InvalidToken
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.logging import get_logger
from pms.core.config import get_settings
from pms.org.models import SysRole, SysUser, SysUserRole
from pms.project.models import PrjMember
from pms.system.config_service import ConfigService
from pms.system.models import SysMailLog, SysMailTemplate

logger = get_logger(__name__)

MAIL_PENDING: Final[str] = "PENDING"
MAIL_SENDING: Final[str] = "SENDING"
MAIL_SENT: Final[str] = "SENT"
MAIL_FAILED: Final[str] = "FAILED"
MAIL_SKIPPED: Final[str] = "SKIPPED"

#: 重试间隔（秒）：1 / 5 / 15 / 60 / 120 分钟，最多 5 次
RETRY_DELAYS: Final[tuple[int, ...]] = (60, 300, 900, 3600, 7200)
DISPATCH_BATCH: Final[int] = 20

_BASE_HTML: Final[str] = """<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f4f6fb;">
<div style="max-width:640px;margin:0 auto;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2328;">
  <div style="padding:16px 20px;background:linear-gradient(120deg,#eef4ff,#f8faff);border-radius:10px 10px 0 0;border:1px solid #e2eaf8;border-bottom:0;">
    <span style="font-size:16px;font-weight:600;color:#1f4fd8;">{title}</span>
  </div>
  <div style="padding:20px;background:#fff;border:1px solid #e2eaf8;border-radius:0 0 10px 10px;font-size:14px;line-height:1.75;">
    {body}
  </div>
  <p style="margin:14px 0 0;text-align:center;font-size:12px;color:#93a0b5;">
    本邮件由 PMS 项目全生命周期管理系统自动发送，请勿直接回复。
  </p>
</div>
</body></html>"""

#: 内置事件与默认模板（可在后台「邮件通知 - 模板」中修改）。
EVENTS: Final[tuple[dict[str, str], ...]] = (
    {
        "eventCode": "PROJECT_SUBMITTED",
        "name": "项目立项待审批",
        "message": "项目提交立项审批后触发，收件人为审批人与 PMO",
        "receiverRoles": "PMO,ADMIN",
        "subject": "【PMS】立项待审批：{{ project.name }}（{{ project.code }}）",
        "body": (
            "<p>{{ operator.name }} 提交了项目立项申请，请及时审批。</p>"
            "<p><b>项目：</b>{{ project.name }}（{{ project.code }}）<br>"
            "<b>合同金额：</b>{{ project.amount }} 元<br>"
            "<b>审批层级：</b>{{ project.approvalLevel }}<br>"
            "<b>提交时间：</b>{{ time }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">前往系统处理</a></p>'
        ),
    },
    {
        "eventCode": "PROJECT_APPROVED",
        "name": "项目立项通过",
        "message": "立项审批通过后触发，收件人为项目负责人与成员",
        "receiverRoles": "PROJECT_PM,PROJECT_MEMBER",
        "subject": "【PMS】立项已通过：{{ project.name }}",
        "body": (
            "<p>项目 <b>{{ project.name }}</b>（{{ project.code }}）已通过立项审批。</p>"
            "<p><b>审批人：</b>{{ operator.name }}<br><b>时间：</b>{{ time }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看项目详情</a></p>'
        ),
    },
    {
        "eventCode": "PROJECT_REJECTED",
        "name": "项目立项驳回",
        "message": "立项被驳回后触发，收件人为项目负责人",
        "receiverRoles": "PROJECT_PM",
        "subject": "【PMS】立项被驳回：{{ project.name }}",
        "body": (
            "<p>项目 <b>{{ project.name }}</b>（{{ project.code }}）的立项申请被驳回。</p>"
            "<p><b>审批人：</b>{{ operator.name }}<br><b>原因：</b>{{ reason or '未填写' }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看并修改</a></p>'
        ),
    },
    {
        "eventCode": "PROJECT_STATUS_CHANGED",
        "name": "项目状态变更",
        "message": "项目启动/挂起/完成/终止后触发，收件人为负责人与成员",
        "receiverRoles": "PROJECT_PM,PROJECT_MEMBER",
        "subject": "【PMS】项目状态变更：{{ project.name }} → {{ project.status }}",
        "body": (
            "<p>项目 <b>{{ project.name }}</b>（{{ project.code }}）状态变更为 "
            "<b>{{ project.status }}</b>。</p>"
            "<p><b>操作人：</b>{{ operator.name }}<br><b>原因：</b>{{ reason or '—' }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看项目</a></p>'
        ),
    },
    {
        "eventCode": "CHANGE_SUBMITTED",
        "name": "变更申请提交",
        "message": "变更提交后触发，收件人为 PMO 与项目负责人",
        "receiverRoles": "PMO,ADMIN,PROJECT_PM",
        "subject": "【PMS】变更待处理：{{ change.code }} {{ change.title }}",
        "body": (
            "<p>收到新的变更申请，请评估并生成审批链。</p>"
            "<p><b>变更编号：</b>{{ change.code }}<br><b>标题：</b>{{ change.title }}<br>"
            "<b>级别：</b>{{ change.level or '待评估' }}<br>"
            "<b>申请人：</b>{{ operator.name }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">前往处理</a></p>'
        ),
    },
    {
        "eventCode": "CHANGE_APPROVED",
        "name": "变更审批通过",
        "message": "变更审批全部通过后触发，收件人为申请人与项目负责人",
        "receiverRoles": "CHANGE_SUBMITTER,PROJECT_PM",
        "subject": "【PMS】变更已通过：{{ change.code }} {{ change.title }}",
        "body": (
            "<p>变更 <b>{{ change.code }}</b>（{{ change.title }}）已审批通过。</p>"
            "<p><b>审批人：</b>{{ operator.name }}<br><b>时间：</b>{{ time }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看变更</a></p>'
        ),
    },
    {
        "eventCode": "CHANGE_REJECTED",
        "name": "变更审批驳回",
        "message": "变更被驳回后触发，收件人为申请人与项目负责人",
        "receiverRoles": "CHANGE_SUBMITTER,PROJECT_PM",
        "subject": "【PMS】变更被驳回：{{ change.code }} {{ change.title }}",
        "body": (
            "<p>变更 <b>{{ change.code }}</b>（{{ change.title }}）被驳回。</p>"
            "<p><b>审批人：</b>{{ operator.name }}<br><b>意见：</b>{{ reason or '未填写' }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看详情</a></p>'
        ),
    },
    {
        "eventCode": "TASK_ASSIGNED",
        "name": "任务指派",
        "message": "任务创建或负责人变更后触发，收件人为任务负责人",
        "receiverRoles": "TASK_OWNER",
        "subject": "【PMS】新任务：{{ task.name }}",
        "body": (
            "<p>你被指派了新的任务。</p>"
            "<p><b>任务：</b>{{ task.name }}<br><b>项目：</b>{{ project.name }}<br>"
            "<b>计划完成：</b>{{ task.endDate or '未设置' }}</p>"
            '<p><a href="{{ link }}" style="color:#1f4fd8;">查看任务</a></p>'
        ),
    },
)

DEFAULT_TEMPLATES: Final[dict[str, dict[str, str]]] = {
    item["eventCode"]: item for item in EVENTS
}

_template_env: Final[SandboxedEnvironment] = SandboxedEnvironment(autoescape=True)


@dataclass(frozen=True)
class MailAccount:
    """发件账户配置快照。"""

    enabled: bool
    host: str
    port: int
    security: str
    user: str
    password: str
    sender: str
    from_name: str
    timeout: int
    test_to: str
    exclude_operator: bool


def _fernet() -> Fernet:
    """由应用密钥派生的对称加密器（变更密钥后旧密码需重新填写）。"""
    digest = hashlib.sha256(get_settings().app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(raw: str) -> str:
    """加密 SMTP 密码；空值原样返回，避免误覆盖。"""
    text = (raw or "").strip()
    if not text:
        return ""
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """解密 SMTP 密码；非密文（历史明文）原样返回。"""
    text = (token or "").strip()
    if not text:
        return ""
    try:
        return _fernet().decrypt(text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return text


async def load_account(session: AsyncSession) -> MailAccount:
    """读取发件账户配置。"""
    config = ConfigService(session)
    user = await config.get_str("notify.mail.smtpUser")
    sender = await config.get_str("notify.mail.smtpFrom") or user
    return MailAccount(
        enabled=await config.get_bool("notify.mail.enabled"),
        host=(await config.get_str("notify.mail.smtpHost")).strip(),
        port=await config.get_int("notify.mail.smtpPort") or 465,
        security=(await config.get_str("notify.mail.security") or "SSL").upper(),
        user=user.strip(),
        password=decrypt_secret(await config.get_str("notify.mail.password")),
        sender=sender.strip(),
        from_name=(await config.get_str("notify.mail.fromName") or "PMS 项目管理").strip(),
        timeout=await config.get_int("notify.mail.timeoutSeconds") or 15,
        test_to=(await config.get_str("notify.mail.testTo")).strip(),
        exclude_operator=await config.get_bool("notify.mail.excludeOperator"),
    )


async def mail_ready(session: AsyncSession) -> MailAccount | None:
    """邮件通道是否可用；不可用返回 None（调用方据此跳过）。"""
    account = await load_account(session)
    if not account.enabled or not account.host or not account.sender:
        return None
    return account


async def _template_of(session: AsyncSession, event_code: str) -> dict[str, str]:
    """取事件模板：库中自定义优先，否则回落内置模板。"""
    result = await session.execute(
        select(SysMailTemplate).where(
            SysMailTemplate.deleted == 0,
            SysMailTemplate.event_code == event_code,
        )
    )
    row = result.scalars().first()
    default = DEFAULT_TEMPLATES.get(event_code, {})
    if row is None:
        return {
            "subject": default.get("subject", ""),
            "body": default.get("body", ""),
            "receiverRoles": default.get("receiverRoles", ""),
            "enabled": "1",
        }
    return {
        "subject": row.subject or default.get("subject", ""),
        "body": row.body or default.get("body", ""),
        "receiverRoles": row.receiver_roles or default.get("receiverRoles", ""),
        "enabled": "1" if row.enabled else "0",
    }


def render_mail(subject_tpl: str, body_tpl: str, context: dict[str, object]) -> tuple[str, str]:
    """渲染主题与正文；变量缺失渲染为空串，不影响发送。"""
    title = str(context.get("title") or "PMS 通知")
    subject = _template_env.from_string(subject_tpl or "").render(**context).strip()
    body = _template_env.from_string(body_tpl or "").render(**context)
    html = _BASE_HTML.replace("{title}", title).replace("{body}", body)
    return subject, html


def _plain_text(html: str) -> str:
    """从 HTML 粗略提取纯文本，作为不支持 HTML 的邮件客户端兜底。"""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _send(account: MailAccount, to: str, subject: str, html: str) -> None:
    """单封邮件投递（失败抛异常，由调用方记录）。"""
    message = EmailMessage()
    message["From"] = formataddr((account.from_name, account.sender))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(_plain_text(html))
    message.add_alternative(html, subtype="html")
    await aiosmtplib.send(
        message,
        hostname=account.host,
        port=account.port,
        username=account.user or None,
        password=account.password or None,
        timeout=account.timeout,
        use_tls=account.security == "SSL",
        start_tls=account.security == "STARTTLS",
    )


async def send_test(session: AsyncSession, to: str) -> None:
    """发送测试邮件（校验发件配置是否可用）。"""
    account = await load_account(session)
    if not account.host or not account.sender:
        raise ValueError("请先填写 SMTP 服务器与发件人邮箱")
    subject, html = render_mail(
        "【PMS】邮件通知测试",
        "<p>这是一封测试邮件，说明当前 SMTP 配置可用。</p>"
        "<p><b>服务器：</b>{{ host }}:{{ port }}（{{ security }}）<br>"
        "<b>发件人：</b>{{ sender }}</p>",
        {
            "title": "邮件通知测试",
            "host": account.host,
            "port": account.port,
            "security": account.security,
            "sender": account.sender,
        },
    )
    await _send(account, to, subject, html)


async def _load_users(session: AsyncSession, user_ids: Iterable[int]) -> list[SysUser]:
    ids = {int(uid) for uid in user_ids if uid}
    if not ids:
        return []
    result = await session.execute(
        select(SysUser).where(
            SysUser.deleted == 0,
            SysUser.status == "ENABLED",
            SysUser.id.in_(ids),
        )
    )
    return [user for user in result.scalars().all() if (user.email or "").strip()]


async def role_user_ids(session: AsyncSession, role_codes: Iterable[str]) -> set[int]:
    """按角色编码取用户 id。"""
    codes = [code.strip().upper() for code in role_codes if code and code.strip()]
    if not codes:
        return set()
    result = await session.execute(
        select(SysUserRole.user_id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysUserRole.deleted == 0,
            SysRole.deleted == 0,
            SysRole.status == "ENABLED",
            SysRole.role_code.in_(codes),
        )
    )
    return {int(uid) for uid in result.scalars().all()}


async def project_member_ids(session: AsyncSession, project_id: int) -> set[int]:
    """项目成员（含负责人）用户 id。"""
    if not project_id:
        return set()
    result = await session.execute(
        select(PrjMember.user_id).where(
            PrjMember.deleted == 0, PrjMember.project_id == project_id
        )
    )
    return {int(uid) for uid in result.scalars().all()}


async def user_name(session: AsyncSession, user_id: int) -> str:
    """取用户展示名，用于邮件正文。"""
    if not user_id:
        return "系统"
    user = await session.get(SysUser, user_id)
    if user is None:
        return "系统"
    return user.real_name or user.username or "系统"


async def project_recipients(session: AsyncSession, project_id: int) -> set[int]:
    """项目通知收件人：负责人 + 成员。"""
    if not project_id:
        return set()
    ids = await project_member_ids(session, project_id)
    from pms.project.models import PrjProject

    project = await session.get(PrjProject, project_id)
    if project is not None and project.pm_id:
        ids.add(int(project.pm_id))
    return ids


async def notify_event(
    session: AsyncSession,
    event_code: str,
    *,
    biz_type: str,
    biz_id: int,
    context: dict[str, object],
    user_ids: Iterable[int],
    operator_id: int = 0,
) -> int:
    """写入待发邮件（与业务同事务），返回入队条数。

    注意：调用方负责 `commit`；SMTP 不可用或未配置时不产生任何记录。
    """
    account = await mail_ready(session)
    if account is None:
        return 0
    template = await _template_of(session, event_code)
    if template["enabled"] != "1":
        return 0
    ids = {int(uid) for uid in user_ids if uid}
    if operator_id and account.exclude_operator:
        ids.discard(int(operator_id))
    users = await _load_users(session, ids)
    if not users:
        return 0
    default = DEFAULT_TEMPLATES.get(event_code, {})
    payload = {"title": default.get("name", "PMS 通知"), **context}
    count = 0
    for user in users:
        target = account.test_to or (user.email or "").strip()
        if not target:
            continue
        subject, html = render_mail(template["subject"], template["body"], payload)
        session.add(
            SysMailLog(
                event_code=event_code,
                biz_type=biz_type,
                biz_id=biz_id,
                recipient=target,
                recipient_name=user.real_name or user.username,
                subject=subject[:500],
                body=html,
                status=MAIL_PENDING,
                retry_count=0,
                next_retry_at=datetime.now(),
            )
        )
        count += 1
    if count:
        await session.flush()
    return count


async def dispatch_pending(session: AsyncSession, limit: int = DISPATCH_BATCH) -> dict[str, int]:
    """发送待发邮件：成功置 SENT，失败按指数退避重试。"""
    account = await mail_ready(session)
    if account is None:
        return {"sent": 0, "failed": 0, "retry": 0}
    now = datetime.now()
    result = await session.execute(
        select(SysMailLog)
        .where(
            SysMailLog.deleted == 0,
            SysMailLog.status == MAIL_PENDING,
            SysMailLog.next_retry_at <= now,
        )
        .order_by(SysMailLog.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars().all())
    sent = failed = retry = 0
    for row in rows:
        try:
            await _send(account, row.recipient, row.subject, row.body)
        except Exception as exc:  # noqa: BLE001 - 记录任意发送异常
            row.retry_count += 1
            row.error = str(exc)[:500]
            if row.retry_count > len(RETRY_DELAYS):
                row.status = MAIL_FAILED
                failed += 1
                logger.warning("邮件发送失败（已达重试上限）：%s %s", row.recipient, exc)
            else:
                delay = RETRY_DELAYS[row.retry_count - 1]
                row.status = MAIL_PENDING
                row.next_retry_at = now + timedelta(seconds=delay)
                retry += 1
        else:
            row.status = MAIL_SENT
            row.sent_at = datetime.now()
            row.error = ""
            sent += 1
    if rows:
        await session.commit()
    return {"sent": sent, "failed": failed, "retry": retry}


async def resend(session: AsyncSession, log_id: int) -> None:
    """手动重发指定记录：立即发送一次并更新状态。"""
    row = await session.get(SysMailLog, log_id)
    if row is None or row.deleted != 0:
        raise ValueError("发送记录不存在")
    account = await mail_ready(session)
    if account is None:
        raise ValueError("邮件通道未启用或配置不完整")
    try:
        await _send(account, row.recipient, row.subject, row.body)
    except Exception as exc:
        row.status = MAIL_FAILED
        row.error = str(exc)[:500]
        await session.commit()
        raise
    row.status = MAIL_SENT
    row.sent_at = datetime.now()
    row.error = ""
    await session.commit()
