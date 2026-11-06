"""项目节点与文档集成测试：总监指派、阶段完成需文档、文档上传/删除权限。"""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path
from typing import Final

import pytest
from fastapi import UploadFile
from sqlalchemy import delete

from pms.common.exceptions import BizRuleError, ConflictError, ForbiddenError
from pms.core.context import AuthContext
from pms.core.database import get_session_factory
from pms.file import service as file_service
from pms.file.storage import upload_root
from pms.org.models import SysDept, SysUser
from pms.project import service as project_service
from pms.project.models import (
    PrjAttachment,
    PrjDirector,
    PrjMember,
    PrjProject,
    PrjStage,
    PrjTask,
)
from pms.system.models import SysFile

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time() * 1000) % 100000)


def _context(user: SysUser, dept_id: int, permissions: set[str] | None = None) -> AuthContext:
    """构造服务层身份上下文。"""
    return AuthContext(
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        dept_id=dept_id,
        dept_path=f"/{dept_id}/",
        roles=frozenset(),
        permissions=frozenset(permissions or set()),
        visible_dept_ids=None,
    )


async def test_stage_documents_and_directors() -> None:
    """阶段完成前必须有交付文档；总监可多人且被指派者自动入组。"""
    factory = get_session_factory()
    created: dict[type, list[int]] = {
        SysDept: [],
        SysUser: [],
        PrjProject: [],
        PrjDirector: [],
        PrjMember: [],
        PrjStage: [],
        PrjTask: [],
        PrjAttachment: [],
        SysFile: [],
    }
    stored_paths: list[str] = []
    async with factory() as session:
        try:
            dept = SysDept(dept_name=f"文档部{_SUFFIX}", dept_code=f"DOC{_SUFFIX}", parent_id=0)
            session.add(dept)
            await session.flush()
            created[SysDept].append(dept.id)

            pm = SysUser(username=f"doc_pm_{_SUFFIX}", real_name="项目经理", dept_id=dept.id)
            dev = SysUser(username=f"doc_dev_{_SUFFIX}", real_name="开发甲", dept_id=dept.id)
            other = SysUser(username=f"doc_oth_{_SUFFIX}", real_name="路人乙", dept_id=dept.id)
            director = SysUser(
                username=f"doc_dir_{_SUFFIX}", real_name="项目总监", dept_id=dept.id
            )
            session.add_all([pm, dev, other, director])
            await session.flush()
            created[SysUser].extend([pm.id, dev.id, other.id, director.id])

            context = _context(pm, dept.id, {"project:stage:edit", "project:doc:manage"})
            project = await project_service.create_project(
                session,
                context,
                project_name=f"文档项目{_SUFFIX}",
                dept_id=dept.id,
                pm_id=pm.id,
                plan_start="2026-11-01",
                plan_end="2027-01-31",
                members=[
                    {"userId": dev.id, "deptId": dept.id},
                    {"userId": other.id, "deptId": dept.id},
                ],
            )
            created[PrjProject].append(project.id)
            member_rows = await project_service.list_members(session, project.id)
            created[PrjMember].extend(row.id for row in member_rows)

            # 1. 指派两名总监 → 自动入组 DIRECTOR
            directors = await project_service.set_directors(
                session, project.id, [director.id, other.id], operator_id=pm.id
            )
            created[PrjDirector].extend(row.id for row in directors)
            assert len(await project_service.director_ids(session, project.id)) == 2
            assert await project_service.is_director(session, project.id, other.id)
            members = await project_service.list_members(session, project.id)
            director_member = next(row for row in members if row.user_id == director.id)
            assert director_member.role_in_project == "DIRECTOR"

            # 2. 覆盖式设置：移除 other 的总监身份
            await project_service.set_directors(
                session, project.id, [director.id], operator_id=pm.id
            )
            assert await project_service.director_ids(session, project.id) == [director.id]

            # 3. 阶段完成前必须有节点文档
            stage = await project_service.create_stage(
                session, project.id, "需求", weight=0.3, seq=1
            )
            created[PrjStage].append(stage.id)
            await project_service.change_stage_status(
                session, project.id, stage.id, "IN_PROGRESS", pm.id
            )
            with pytest.raises(BizRuleError):
                await project_service.change_stage_status(
                    session, project.id, stage.id, "DONE", pm.id
                )

            # 4. 项目成员上传文档到该阶段（落盘 + 附件记录）
            dev_ctx = _context(dev, dept.id, {"project:doc:upload"})
            upload = UploadFile(file=BytesIO(b"%PDF-1.4 stage doc"), filename="需求规格说明书.pdf")
            attachment = await file_service.create_attachment(
                session,
                dev_ctx,
                upload=upload,
                project_id=project.id,
                biz_type="STAGE",
                biz_id=stage.id,
            )
            file_id = int(attachment["fileId"])  # type: ignore[arg-type]
            file_row = await session.get(SysFile, file_id)
            assert file_row is not None
            stored_paths.append(str(upload_root() / file_row.storage_path))
            created[SysFile].append(file_id)
            assert attachment["bizType"] == "STAGE"
            assert attachment["bizId"] == stage.id
            assert await project_service.count_attachments(
                session, project.id, biz_type="STAGE", biz_id=stage.id
            ) == 1

            # 5. 有文档后阶段可完成
            done = await project_service.change_stage_status(
                session, project.id, stage.id, "DONE", pm.id
            )
            assert done.status == "DONE"
            assert done.progress == 100

            # 6. 删除权限：路人不能删，上传人本人可以
            with pytest.raises(ForbiddenError):
                await file_service.delete_file(
                    session, int(attachment["fileId"]), _context(other, dept.id)
                )
            await file_service.delete_file(
                session, int(attachment["fileId"]), _context(dev, dept.id)
            )
            assert await project_service.count_attachments(session, project.id) == 0

            # 7. 阶段有任务时不允许删除
            task = await project_service.create_task(
                session, project.id, "写文档", stage_id=stage.id, plan_hours=8
            )
            created[PrjTask].append(task.id)
            with pytest.raises(ConflictError):
                await project_service.delete_stage(session, project.id, stage.id, pm.id)
            task.deleted = 1
            await session.flush()
            await project_service.delete_stage(session, project.id, stage.id, pm.id)
            await session.commit()
        finally:
            for model, ids in created.items():
                if ids:
                    await session.execute(delete(model).where(model.id.in_(ids)))
            await session.commit()
    for absolute in stored_paths:
        Path(absolute).unlink(missing_ok=True)
