"""文档接口：上传、下载、元数据、删除（本地磁盘，按项目分目录）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.response import ok
from pms.core.context import AuthContext
from pms.core.deps import get_session, require_permissions
from pms.file import service as file_service
from pms.project import service as project_service
from pms.project.visibility import (
    ensure_project_participant,
    ensure_project_visible,
)

router = APIRouter(prefix="/api/v1/files", tags=["文档管理"])


async def _ensure_file_visible(
    session: AsyncSession, context: AuthContext, file_id: int
) -> None:
    """文件所属项目可见时才允许访问。"""
    project_id = await file_service.project_of_file(session, file_id)
    if not project_id:
        return
    project = await project_service.get_project(session, project_id)
    await ensure_project_visible(session, context, project)


@router.post("", summary="上传项目文档")
async def upload_file(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:doc:upload"))],
    file: Annotated[UploadFile, File(description="待上传文件")],
    projectId: Annotated[int, Form(description="项目 ID")],
    bizType: Annotated[str, Form(description="归属类型")] = "PROJECT",
    bizId: Annotated[int, Form(description="归属节点/任务 ID")] = 0,
) -> object:
    """上传文档：项目成员均可上传；文件落在 `data/uploads/project_<id>/年/月/`。"""
    project = await project_service.get_project(session, projectId)
    await ensure_project_participant(session, context, project)
    data = await file_service.create_attachment(
        session,
        context,
        upload=file,
        project_id=projectId,
        biz_type=bizType,
        biz_id=bizId,
    )
    await session.commit()
    return ok(data)


@router.get("/{file_id}", summary="文档元数据")
async def file_meta(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """查看文档元数据（受项目可见性约束）。"""
    await _ensure_file_visible(session, context, file_id)
    file = await file_service.get_file(session, file_id)
    return ok(
        {
            "fileId": file.id,
            "fileName": file.origin_name,
            "size": int(file.size),
            "mime": file.mime,
            "uploadTime": file.create_time.isoformat(sep=" ", timespec="seconds")
            if file.create_time
            else "",
        }
    )


@router.get("/{file_id}/download", summary="下载文档")
async def download_file(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> FileResponse:
    """下载文档（浏览器按原文件名保存）。"""
    await _ensure_file_visible(session, context, file_id)
    file, path = await file_service.file_location(session, file_id)
    return FileResponse(path, filename=file.origin_name, media_type=file.mime)


@router.delete("/{file_id}", summary="删除文档")
async def delete_file(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("project:view"))],
) -> object:
    """删除文档（软删）：上传人本人或具备 `project:doc:manage` 的管理者。"""
    await _ensure_file_visible(session, context, file_id)
    await file_service.delete_file(session, file_id, context)
    await session.commit()
    return ok(message="文档已删除")
