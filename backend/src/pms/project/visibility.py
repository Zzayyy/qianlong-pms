"""项目可见性与项目内管理权判定（设计稿 03 §4.1；供项目与文档模块共用）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError, ForbiddenError
from pms.core.context import AuthContext
from pms.project import service
from pms.project.models import PrjMember, PrjProject
from pms.system.config_service import ConfigService


async def can_view_project(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> bool:
    """项目可见性判定（参数 `project.dept.visible` / `project.public.visible` 可调）。"""
    from pms.org.scope import project_visible

    config = ConfigService(session)
    dept_visible = await config.get_bool("project.dept.visible")
    public_visible = await config.get_bool("project.public.visible")
    return project_visible(
        secret_level=project.secret_level,
        is_member=await service.is_member(session, project.id, context.user_id),
        is_pm=project.pm_id == context.user_id,
        is_dept_visible=dept_visible,
        is_owner_dept_visible=context.can_see_dept(project.dept_id),
        is_all_scope=context.is_all_scope,
        public_visible=public_visible,
    )


async def ensure_project_visible(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> None:
    """不可见时抛数据越权（40302）。"""
    if not await can_view_project(session, context, project):
        raise DataForbiddenError("无该项目访问权限")


async def is_project_manager(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> bool:
    """是否项目经理（负责人或组内 PM 角色）。

    兜底口径：PMO / 公司领导（`is_privileged`）与系统管理员可管理任意项目，
    避免最高权限角色被项目级校验拦住、导致数据无法运维。
    """
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


async def ensure_project_manager(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> None:
    """非项目经理时抛 40301（节点/总监/文档管理用）。"""
    if not await is_project_manager(session, context, project):
        raise ForbiddenError("仅项目经理、PMO 或系统管理员可执行该操作")


async def is_project_participant(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> bool:
    """是否项目参与者（成员/负责人/特权角色/系统管理员），用于文档上传。"""
    if context.is_privileged or context.has_any_role("ADMIN"):
        return True
    if project.pm_id == context.user_id:
        return True
    return await service.is_member(session, project.id, context.user_id)


async def ensure_project_participant(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> None:
    """非项目参与者时抛 40301（文档上传用）。"""
    if not await is_project_participant(session, context, project):
        raise ForbiddenError("仅项目成员可上传该项目文档")
