"""FastAPI 依赖：当前用户、功能权限校验、分页参数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import ForbiddenError, UnauthorizedError
from pms.core.context import AuthContext
from pms.core.database import get_session
from pms.core.redis import blacklist_contains
from pms.core.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

TOKEN_SEPARATOR = " "


async def _extract_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """从 Authorization 头或 `X-Access-Token` 取出令牌。"""
    if credentials is not None and credentials.credentials:
        return credentials.credentials
    header_token = request.headers.get("X-Access-Token")
    if header_token:
        return header_token
    raise UnauthorizedError()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AuthContext:
    """解析令牌并构造身份上下文。"""
    token = await _extract_token(request, credentials)
    if await blacklist_contains(token):
        raise UnauthorizedError("登录已失效")
    payload = decode_access_token(token)
    user_id = int(str(payload.get("sub", "0")))
    roles = frozenset(str(item) for item in payload.get("roles", []) or [])
    dept_id = int(str(payload.get("dept", "0")))
    dept_path = str(payload.get("deptPath", ""))
    raw_visible = payload.get("vdepts")
    visible: frozenset[int] | None = None
    if isinstance(raw_visible, list):
        visible = frozenset(int(item) for item in raw_visible)
    context = AuthContext(
        user_id=user_id,
        username=str(payload.get("username", "")),
        real_name=str(payload.get("realName", "")),
        dept_id=dept_id,
        dept_path=dept_path,
        roles=roles,
        permissions=frozenset(),
        visible_dept_ids=visible,
        manager_depth=int(str(payload.get("mdepth", "1"))),
    )
    request.state.auth = context
    return context


async def load_permissions(
    context: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    """加载权限点（Redis 缓存 + 数据库兜底），返回带权限的上下文。"""
    from pms.org.service import resolve_user_permissions  # 延迟导入避免循环依赖

    permissions = await resolve_user_permissions(session, context.user_id)
    return AuthContext(
        user_id=context.user_id,
        username=context.username,
        real_name=context.real_name,
        dept_id=context.dept_id,
        dept_path=context.dept_path,
        roles=context.roles,
        permissions=frozenset(permissions),
        visible_dept_ids=context.visible_dept_ids,
        manager_depth=context.manager_depth,
    )


def require_permissions(*codes: str):
    """生成「功能权限」校验依赖（设计稿 03 维度 ①）。

    用法：`Depends(require_permissions("project:edit"))`
    """

    async def _guard(
        context: Annotated[AuthContext, Depends(load_permissions)],
    ) -> AuthContext:
        missing = [code for code in codes if not context.has_permission(code)]
        if missing:
            raise ForbiddenError(f"缺少权限：{', '.join(missing)}")
        return context

    return _guard


@dataclass(slots=True)
class Pagination:
    """分页参数（设计稿 09 §1：pageNum 从 1 开始）。"""

    page_num: int
    page_size: int

    @property
    def offset(self) -> int:
        """SQL 偏移量。"""
        return (self.page_num - 1) * self.page_size

    @property
    def limit(self) -> int:
        """SQL 取数条数。"""
        return self.page_size


async def get_pagination(
    page_num: Annotated[int, Query(ge=1, alias="pageNum")] = 1,
    page_size: Annotated[int, Query(ge=1, le=200, alias="pageSize")] = 20,
) -> Pagination:
    """分页依赖。"""
    return Pagination(page_num=page_num, page_size=page_size)
