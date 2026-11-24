"""一次性验证脚本：问题跟踪服务链路（验证后删除，不落库）。"""

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
            print("skip: 缺 admin 或项目数据")
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
        bug = await service.create_issue(
            session,
            ctx,
            issue_type="BUG",
            project_id=project.id,
            title="联调验证 Bug",
            severity="HIGH",
            owner_id=user.id,
        )
        prod = await service.create_issue(
            session,
            ctx,
            issue_type="PROD",
            project_id=project.id,
            title="联调验证生产问题",
        )
        print("created:", bug.issue_no, prod.issue_no)
        print(
            "list:",
            len(await service.list_issues(session, issue_type="BUG")),
            len(await service.list_issues(session, issue_type="PROD")),
        )
        print("count PROD:", await service.count_issues(session, issue_type="PROD"))
        await service.change_status(session, bug.id, ctx, "IN_PROGRESS", can_manage=True)
        await service.change_status(session, bug.id, ctx, "CLOSED", can_manage=True)
        print("closed:", bug.status, bug.close_date)
        await service.change_status(session, bug.id, ctx, "OPEN", can_manage=True)
        print("reopen:", bug.status, bug.close_date)
        await service.delete_issue(session, bug.id, ctx, can_manage=True)
        print("open_count BUG:", await service.open_count(session, "BUG"))
        await session.rollback()
    await dispose_engine()


asyncio.run(main())
