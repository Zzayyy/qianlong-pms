"""文件与项目文档服务：落库（`t_sys_file` + `t_prj_attachment`）、列表、删除。"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ForbiddenError, NotFoundError
from pms.core.context import AuthContext
from pms.file.storage import StoredFile, resolve_storage_path, save_upload
from pms.org.models import SysUser
from pms.project import service as project_service
from pms.project.models import PrjAttachment, PrjMilestone, PrjStage, PrjTask
from pms.system.models import SysFile

BIZ_TYPES: Final[frozenset[str]] = frozenset(
    {"PROJECT", "STAGE", "MILESTONE", "TASK", "CHANGE"}
)


async def create_attachment(
    session: AsyncSession,
    context: AuthContext,
    *,
    upload: UploadFile,
    project_id: int,
    biz_type: str = "PROJECT",
    biz_id: int = 0,
) -> dict[str, object]:
    """保存上传文件并写入附件关联，返回附件出参。"""
    kind = (biz_type or "PROJECT").upper()
    if kind not in BIZ_TYPES:
        raise BizRuleError(f"不支持的文档归属类型：{kind}")
    await _ensure_biz_owner(session, project_id, kind, biz_id)

    stored: StoredFile = await save_upload(upload, project_id)
    file = SysFile(
        file_key=stored.file_key,
        origin_name=stored.origin_name,
        storage_path=stored.storage_path,
        size=stored.size,
        mime=stored.mime,
        bucket="local",
        biz_type=kind,
        biz_id=biz_id,
        create_by=context.user_id,
    )
    session.add(file)
    await session.flush()
    await session.refresh(file)  # 取回 server_default 生成的 create_time

    attachment = PrjAttachment(
        project_id=project_id,
        biz_type=kind,
        biz_id=biz_id,
        file_id=file.id,
        file_name=stored.origin_name,
        size=stored.size,
        create_by=context.user_id,
    )
    session.add(attachment)
    await session.flush()
    return _attachment_out(attachment, file, context.real_name)


async def _ensure_biz_owner(
    session: AsyncSession, project_id: int, biz_type: str, biz_id: int
) -> None:
    """校验节点/任务归属当前项目，避免把文档挂到别的项目节点。"""
    if biz_type == "PROJECT":
        return
    if biz_id <= 0:
        raise BizRuleError("请选择文档所属节点")
    if biz_type == "STAGE":
        stage = await session.get(PrjStage, biz_id)
        if stage is None or stage.deleted or stage.project_id != project_id:
            raise NotFoundError("阶段不存在")
        return
    if biz_type == "MILESTONE":
        milestone = await session.get(PrjMilestone, biz_id)
        if milestone is None or milestone.deleted or milestone.project_id != project_id:
            raise NotFoundError("里程碑不存在")
        return
    if biz_type == "TASK":
        task = await session.get(PrjTask, biz_id)
        if task is None or task.deleted or task.project_id != project_id:
            raise NotFoundError("任务不存在")


async def list_attachments(
    session: AsyncSession,
    project_id: int,
    *,
    biz_type: str = "",
    biz_id: int = 0,
) -> list[dict[str, object]]:
    """项目文档列表（含上传人姓名与时间）。"""
    stmt = (
        select(PrjAttachment, SysFile)
        .join(SysFile, SysFile.id == PrjAttachment.file_id)
        .where(PrjAttachment.project_id == project_id, PrjAttachment.deleted == 0)
        .order_by(PrjAttachment.id.desc())
    )
    if biz_type:
        stmt = stmt.where(PrjAttachment.biz_type == biz_type.upper())
    if biz_id:
        stmt = stmt.where(PrjAttachment.biz_id == biz_id)
    rows = (await session.execute(stmt)).all()
    uploader_ids = {file.create_by for _, file in rows if file.create_by}
    names = await _user_names(session, uploader_ids)
    return [
        _attachment_out(attachment, file, names.get(file.create_by or 0, ""))
        for attachment, file in rows
    ]


async def _user_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """批量取姓名。"""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(user_ids))
    )
    return {row[0]: row[1] for row in rows.all()}


def _attachment_out(
    attachment: PrjAttachment, file: SysFile, uploader: str = ""
) -> dict[str, object]:
    """附件出参。"""
    return {
        "id": attachment.id,
        "fileId": attachment.file_id,
        "fileName": attachment.file_name,
        "size": int(attachment.size),
        "mime": file.mime,
        "bizType": attachment.biz_type,
        "bizId": attachment.biz_id,
        "uploader": uploader,
        "uploadTime": file.create_time.isoformat(sep=" ", timespec="seconds")
        if file.create_time
        else "",
    }


async def get_file(session: AsyncSession, file_id: int) -> SysFile:
    """取文件记录（含软删校验）。"""
    file = await session.get(SysFile, file_id)
    if file is None or file.deleted:
        raise NotFoundError("文件不存在")
    return file


async def get_attachment(session: AsyncSession, file_id: int) -> PrjAttachment | None:
    """取文件对应的项目附件关联。"""
    stmt = select(PrjAttachment).where(
        PrjAttachment.file_id == file_id, PrjAttachment.deleted == 0
    )
    return (await session.execute(stmt)).scalars().first()


async def file_location(session: AsyncSession, file_id: int) -> tuple[SysFile, Path]:
    """返回文件记录与磁盘路径（下载前校验存在性）。"""
    file = await get_file(session, file_id)
    path = resolve_storage_path(file.storage_path)
    if not path.is_file():
        raise NotFoundError("文件已丢失，请联系管理员")
    return file, path


async def delete_file(
    session: AsyncSession, file_id: int, context: AuthContext
) -> None:
    """删除文档：上传人本人或具备 `project:doc:manage` 的管理者。"""
    file = await get_file(session, file_id)
    attachment = await get_attachment(session, file_id)
    is_owner = file.create_by == context.user_id
    if not is_owner and not context.has_permission("project:doc:manage"):
        raise ForbiddenError("仅上传人本人或文档管理员可删除")
    file.deleted = 1
    file.update_by = context.user_id
    if attachment is not None:
        attachment.deleted = 1
        attachment.update_by = context.user_id
    await session.flush()


async def project_of_file(session: AsyncSession, file_id: int) -> int:
    """文件所属项目 ID（无关联返回 0）。"""
    attachment = await get_attachment(session, file_id)
    return attachment.project_id if attachment is not None else 0


async def stage_doc_count(session: AsyncSession, project_id: int, stage_id: int) -> int:
    """某阶段的文档数量（阶段完成校验用）。"""
    return await project_service.count_attachments(
        session, project_id, biz_type="STAGE", biz_id=stage_id
    )
