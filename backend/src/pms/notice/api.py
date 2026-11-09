"""站内通知接口：列表、未读数、已读。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_current_user, get_pagination, get_session
from pms.notice import service

router = APIRouter(prefix="/api/v1/notices", tags=["消息通知"])


@router.get("", summary="通知列表")
async def list_notices(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(get_current_user)],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    unreadOnly: Annotated[bool, Query()] = False,
) -> object:
    """当前用户的通知，按时间倒序。"""
    total = await service.count_notices(
        session, context.user_id, unread_only=unreadOnly
    )
    rows = await service.list_notices(
        session,
        context.user_id,
        unread_only=unreadOnly,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return paged(
        [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "noticeType": row.notice_type,
                "bizType": row.biz_type,
                "bizId": row.biz_id,
                "readStatus": row.read_status,
                "createTime": row.create_time.isoformat() if row.create_time else "",
            }
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/unread-count", summary="未读通知数")
async def get_unread_count(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(get_current_user)],
) -> object:
    """当前用户未读通知数。"""
    return ok({"count": await service.unread_count(session, context.user_id)})


@router.post("/read-all", summary="全部通知已读")
async def read_all(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(get_current_user)],
) -> object:
    """标记当前用户全部通知已读。"""
    count = await service.mark_all_read(session, context.user_id)
    await session.commit()
    return ok({"count": count})


@router.post("/{notice_id}/read", summary="通知已读")
async def read_notice(
    notice_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(get_current_user)],
) -> object:
    """标记当前用户某条通知已读。"""
    notice = await service.mark_read(session, notice_id, context.user_id)
    await session.commit()
    return ok({"id": notice.id, "readStatus": notice.read_status})
