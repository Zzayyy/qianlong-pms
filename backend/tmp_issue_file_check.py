"""一次性验证：问题附件上传与列表（验证后删除脚本与磁盘文件，不落库）。"""

import asyncio
import io

from fastapi import UploadFile
from sqlalchemy import select

from pms.core.context import AuthContext
from pms.core.database import dispose_engine, get_session_factory
from pms.file import service as file_service
from pms.file.storage import resolve_storage_path
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
            title="附件验证",
        )
        upload = UploadFile(filename="check.png", file=io.BytesIO(b"fake-image-bytes"))
        data = await file_service.create_attachment(
            session,
            ctx,
            upload=upload,
            project_id=project.id,
            biz_type="ISSUE",
            biz_id=issue.id,
        )
        print("uploaded:", data["fileName"], data["bizType"], data["uploader"])
        rows = await file_service.list_attachments(
            session, project.id, biz_type="ISSUE", biz_id=issue.id
        )
        print("list:", len(rows))
        file = await file_service.get_file(session, int(str(data["fileId"])))
        path = resolve_storage_path(file.storage_path)
        await session.rollback()
        if path.exists():
            path.unlink()
        print("disk cleaned:", not path.exists())
    await dispose_engine()


asyncio.run(main())
