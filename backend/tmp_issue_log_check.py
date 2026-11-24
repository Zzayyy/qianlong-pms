"""一次性验证：问题历史记录（验证后删除，不落库）。"""

import asyncio

from sqlalchemy import select

from pms.core.context import AuthContext
from pms.core.database import dispose_engine, get_session_factory
from pms.issue import service
from pms.org.models import SysUser
from pms.project.models import PrjProject


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = (
            await session.execute(select(SysUser).where(SysUser.username == "admin"))
        ).scalars().first()
        project = (
            await session.execute(select(PrjProject).where(PrjProject.deleted == 0))
        ).scalars().first()
        if user is None or project is None:
            print("skip: 缺数据")
            return
        ctx = AuthContext(
            user_id=user.id,
            username=user.username,
            real_name=user.real_name or "",
            dept_id=user.dept_id,
            dept_path="/",
            roles=frozenset({"ADMIN"}),
            permissions=frozenset({"issue:view", "issue:manage"}),
            visible_dept_ids=None,
        )
        issue = await service.create_issue(
            session,
            ctx,
            issue_type="BUG",
            project_id=project.id,
            title="历史记录验证",
        )
        await service.update_issue(
            session,
            issue.id,
            ctx,
            can_manage=True,
            title="历史记录验证-改",
            severity="HIGH",
            owner_id=user.id,
        )
        await service.change_status(session, issue.id, ctx, "CLOSED", can_manage=True)
        for log in await service.list_logs(session, issue.id):
            print(f"{log.action:7} {log.field:12} {log.old_value!r} -> {log.new_value!r}")
        await session.rollback()
    await dispose_engine()


asyncio.run(main())
