"""站内通知服务（`t_sys_notice`）。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import NotFoundError
from pms.system.models import SysNotice


async def create_notice(
    session: AsyncSession,
    *,
    receiver_id: int,
    title: str,
    content: str,
    notice_type: str = "SYSTEM",
    biz_type: str = "",
    biz_id: int = 0,
) -> SysNotice | None:
    """给指定用户生成一条站内通知（接收人为空时忽略）。"""
    if not receiver_id:
        return None
    notice = SysNotice(
        title=title[:256],
        content=content,
        notice_type=notice_type,
        receiver_id=receiver_id,
        biz_type=biz_type,
        biz_id=biz_id,
        read_status=0,
        channel="INBOX",
    )
    session.add(notice)
    await session.flush()
    return notice


async def list_notices(
    session: AsyncSession,
    user_id: int,
    *,
    unread_only: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> list[SysNotice]:
    """当前用户的通知列表。"""
    stmt = select(SysNotice).where(
        SysNotice.deleted == 0, SysNotice.receiver_id == user_id
    )
    if unread_only:
        stmt = stmt.where(SysNotice.read_status == 0)
    stmt = stmt.order_by(SysNotice.id.desc())
    if limit > 0:
        stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_notices(
    session: AsyncSession, user_id: int, *, unread_only: bool = False
) -> int:
    """当前用户通知数量。"""
    stmt = select(func.count(SysNotice.id)).where(
        SysNotice.deleted == 0, SysNotice.receiver_id == user_id
    )
    if unread_only:
        stmt = stmt.where(SysNotice.read_status == 0)
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def unread_count(session: AsyncSession, user_id: int) -> int:
    """当前用户未读通知数。"""
    return await count_notices(session, user_id, unread_only=True)


async def mark_read(
    session: AsyncSession, notice_id: int, user_id: int
) -> SysNotice:
    """标记本人一条通知已读。"""
    notice = await session.get(SysNotice, notice_id)
    if notice is None or notice.deleted or notice.receiver_id != user_id:
        raise NotFoundError("通知不存在")
    if notice.read_status != 1:
        notice.read_status = 1
        notice.update_by = user_id
        await session.flush()
    return notice


async def mark_all_read(session: AsyncSession, user_id: int) -> int:
    """标记本人全部未读通知已读。"""
    result = await session.execute(
        update(SysNotice)
        .where(
            SysNotice.receiver_id == user_id,
            SysNotice.read_status == 0,
            SysNotice.deleted == 0,
        )
        .values(read_status=1, update_by=user_id)
    )
    await session.flush()
    return int(result.rowcount or 0)
