"""问题跟踪接口：Bug 列表与生产问题列表共用一套接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError, NotFoundError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.file import service as file_service
from pms.issue import service
from pms.issue.models import IssIssue
from pms.issue.state import ISSUE_STATUSES, ISSUE_TYPES, PRIORITIES, SEVERITIES
from pms.org.models import SysUser
from pms.project import service as project_service
from pms.project.models import PrjProject

router = APIRouter(prefix="/api/v1/issues", tags=["问题跟踪"])


class IssueIn(BaseModel):
    """新建问题入参。"""

    issueType: str = "BUG"
    projectId: int
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    severity: str = "MEDIUM"
    priority: str = "MEDIUM"
    ownerId: int = 0
    foundDate: str | None = None
    remark: str = ""


class IssueUpdateIn(BaseModel):
    """编辑问题入参（字段为空表示不修改）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    severity: str | None = None
    priority: str | None = None
    ownerId: int | None = None
    foundDate: str | None = None
    remark: str | None = None
    projectId: int | None = None


class StatusIn(BaseModel):
    """状态流转入参。"""

    status: str


async def _project_names(
    session: AsyncSession, project_ids: set[int]
) -> dict[int, str]:
    """批量取项目名称。"""
    ids = {int(item) for item in project_ids if item}
    if not ids:
        return {}
    result = await session.execute(
        select(PrjProject.id, PrjProject.project_name).where(PrjProject.id.in_(ids))
    )
    return {int(project_id): str(name) for project_id, name in result.all()}


async def _user_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """批量取人员显示名（真实姓名优先）。"""
    ids = {int(item) for item in user_ids if item}
    if not ids:
        return {}
    result = await session.execute(
        select(SysUser.id, SysUser.username, SysUser.real_name).where(
            SysUser.id.in_(ids)
        )
    )
    return {
        int(user_id): str(real_name or username)
        for user_id, username, real_name in result.all()
    }


def _out(
    issue: IssIssue,
    project_name: str,
    owner_name: str,
    reporter_name: str,
) -> dict[str, object]:
    """问题出参。"""
    return {
        "id": issue.id,
        "issueNo": issue.issue_no,
        "issueType": issue.issue_type,
        "projectId": issue.project_id,
        "projectName": project_name,
        "title": issue.title,
        "description": issue.description,
        "severity": issue.severity,
        "priority": issue.priority,
        "status": issue.status,
        "ownerId": issue.owner_id,
        "ownerName": owner_name,
        "reporterId": issue.reporter_id,
        "reporterName": reporter_name,
        "foundDate": issue.found_date,
        "closeDate": issue.close_date,
        "remark": issue.remark,
        "createTime": issue.create_time,
    }


@router.get("", summary="问题列表")
async def list_issues(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    issueType: Annotated[str, Query()] = "",
    projectId: Annotated[int, Query()] = 0,
    status: Annotated[str, Query()] = "",
    severity: Annotated[str, Query()] = "",
    keyword: Annotated[str, Query()] = "",
    ownerId: Annotated[int, Query()] = 0,
    reporterId: Annotated[int, Query()] = 0,
) -> object:
    """分页查询问题；`issueType` 区分 Bug（BUG）与生产问题（PROD）。"""
    filters = {
        "issue_type": issueType,
        "project_id": projectId,
        "status": status,
        "severity": severity,
        "keyword": keyword,
        "owner_id": ownerId,
        "reporter_id": reporterId,
    }
    rows = await service.list_issues(
        session,
        **filters,
        offset=(pagination.page_num - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    total = await service.count_issues(session, **filters)
    projects = await _project_names(session, {row.project_id for row in rows})
    names = await _user_names(
        session, {row.owner_id for row in rows} | {row.reporter_id for row in rows}
    )
    return paged(
        [
            _out(
                row,
                projects.get(int(row.project_id), ""),
                names.get(int(row.owner_id), ""),
                names.get(int(row.reporter_id), ""),
            )
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/options", summary="问题页面选项")
async def issue_options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """新建/筛选用的项目、人员与枚举选项。"""
    rows = (
        await session.execute(
            select(PrjProject.id, PrjProject.project_code, PrjProject.project_name)
            .where(PrjProject.deleted == 0)
            .order_by(PrjProject.id.desc())
            .limit(500)
        )
    ).all()
    users = (
        await session.execute(
            select(SysUser.id, SysUser.username, SysUser.real_name)
            .where(SysUser.deleted == 0, SysUser.status == "ENABLED")
            .order_by(SysUser.id)
            .limit(500)
        )
    ).all()
    return ok(
        {
            "projects": [
                {
                    "id": int(project_id),
                    "projectCode": str(code or ""),
                    "projectName": str(name or ""),
                }
                for project_id, code, name in rows
            ],
            "users": [
                {
                    "id": int(user_id),
                    "name": str(real_name or username),
                }
                for user_id, username, real_name in users
            ],
            "types": list(ISSUE_TYPES),
            "statuses": list(ISSUE_STATUSES),
            "severities": list(SEVERITIES),
            "priorities": list(PRIORITIES),
            "canManage": context.has_permission("issue:manage"),
        }
    )


@router.post("", summary="登记问题")
async def create_issue(
    body: IssueIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """登记一条问题：有查看权限即可提交（所有人可提）。"""
    issue = await service.create_issue(
        session,
        context,
        issue_type=body.issueType,
        project_id=body.projectId,
        title=body.title,
        description=body.description,
        severity=body.severity,
        priority=body.priority,
        owner_id=body.ownerId,
        found_date=body.foundDate,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": issue.id, "issueNo": issue.issue_no})


@router.get("/{issue_id}", summary="问题详情")
async def issue_detail(
    issue_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """问题详情：基础信息 + 历史记录 + 附件。"""
    issue = await service.get_issue(session, issue_id)
    projects = await _project_names(session, {issue.project_id})
    names = await _user_names(session, {issue.owner_id, issue.reporter_id})
    logs = await service.list_logs(session, issue_id)
    log_names = await _user_names(session, {log.operator_id for log in logs})
    attachments = await file_service.list_attachments(
        session, issue.project_id, biz_type="ISSUE", biz_id=issue.id
    )
    data = _out(
        issue,
        projects.get(int(issue.project_id), ""),
        names.get(int(issue.owner_id), ""),
        names.get(int(issue.reporter_id), ""),
    )
    data["logs"] = [
        {
            "id": log.id,
            "action": log.action,
            "field": log.field,
            "oldValue": log.old_value,
            "newValue": log.new_value,
            "operatorId": log.operator_id,
            "operatorName": log_names.get(int(log.operator_id), ""),
            "createTime": log.create_time,
        }
        for log in logs
    ]
    data["attachments"] = attachments
    # 前端据此隐藏上传入口：项目成员、提报人、负责人或问题管理员才可传
    data["canUpload"] = await _can_upload(session, context, issue)
    return ok(data)


async def _can_upload(
    session: AsyncSession, context: AuthContext, issue: IssIssue
) -> bool:
    """附件上传口径：与问题相关的项目成员 / 提报人 / 负责人 / 问题管理员。"""
    if context.has_permission("issue:manage"):
        return True
    if context.user_id in {int(issue.reporter_id or 0), int(issue.owner_id or 0)}:
        return True
    return await project_service.is_member(
        session, int(issue.project_id or 0), context.user_id
    )


@router.post("/{issue_id}/attachments", summary="上传问题附件")
async def upload_attachment(
    issue_id: int,
    file: Annotated[UploadFile, File(description="附件或截图")],
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """上传图片/附件：文件挂在问题项目下，`biz_type=ISSUE`。

    权限：项目成员、提报人、负责人或问题管理员，避免全公司任何人往任意问题传文件。
    """
    issue = await service.get_issue(session, issue_id)
    if not await _can_upload(session, context, issue):
        raise DataForbiddenError("仅项目成员、提报人、负责人或问题管理员可上传附件")
    data = await file_service.create_attachment(
        session,
        context,
        upload=file,
        project_id=issue.project_id,
        biz_type="ISSUE",
        biz_id=issue.id,
    )
    await session.commit()
    return ok(data)


@router.get("/{issue_id}/attachments", summary="问题附件列表")
async def list_attachments(
    issue_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """问题附件列表（含上传人与上传时间）。"""
    issue = await service.get_issue(session, issue_id)
    return ok(
        await file_service.list_attachments(
            session, issue.project_id, biz_type="ISSUE", biz_id=issue.id
        )
    )


@router.get("/{issue_id}/attachments/{file_id}/download", summary="下载问题附件")
async def download_attachment(
    issue_id: int,
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> FileResponse:
    """下载附件/图片。

    权限与问题本身一致（有 `issue:view` 即可），**不校验项目可见性**：
    问题提报人可能不是项目成员，按项目口径会把提报人自己的截图挡掉。
    """
    issue = await service.get_issue(session, issue_id)
    attachment = await file_service.get_attachment(session, file_id)
    if (
        attachment is None
        or attachment.biz_type != "ISSUE"
        or int(attachment.biz_id) != issue.id
    ):
        raise NotFoundError("附件不存在")
    file, path = await file_service.file_location(session, file_id)
    return FileResponse(path, filename=file.origin_name, media_type=file.mime)


@router.delete("/{issue_id}/attachments/{file_id}", summary="删除问题附件")
async def delete_attachment(
    issue_id: int,
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """软删除附件：上传人、提报人、负责人或问题管理员。"""
    issue = await service.get_issue(session, issue_id)
    attachment = await file_service.get_attachment(session, file_id)
    if (
        attachment is None
        or attachment.biz_type != "ISSUE"
        or int(attachment.biz_id) != issue.id
    ):
        raise NotFoundError("附件不存在")
    file = await file_service.get_file(session, file_id)
    allowed = (
        int(file.create_by or 0) == context.user_id
        or context.has_permission("issue:manage")
        or context.user_id in {int(issue.reporter_id or 0), int(issue.owner_id or 0)}
    )
    if not allowed:
        raise DataForbiddenError("仅上传人、提报人、负责人或问题管理员可删除附件")
    file.deleted = 1
    file.update_by = context.user_id
    attachment.deleted = 1
    attachment.update_by = context.user_id
    await session.flush()
    await session.commit()
    return ok({"id": file_id})


@router.put("/{issue_id}", summary="编辑问题")
async def update_issue(
    issue_id: int,
    body: IssueUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """编辑问题（提报人 / 负责人 / 问题管理员）。"""
    # 入参是 camelCase、服务层参数是 snake_case，必须显式映射，不能直接 **model_dump()
    data = body.model_dump()
    issue = await service.update_issue(
        session,
        issue_id,
        context,
        can_manage=context.has_permission("issue:manage"),
        title=data["title"],
        description=data["description"],
        severity=data["severity"],
        priority=data["priority"],
        owner_id=data["ownerId"],
        found_date=data["foundDate"],
        remark=data["remark"],
        project_id=data["projectId"],
    )
    await session.commit()
    return ok({"id": issue.id})


@router.post("/{issue_id}/status", summary="流转问题状态")
async def change_status(
    issue_id: int,
    body: StatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """待处理 / 处理中 / 已关闭 互切；关闭自动记关闭日期，重开清空。"""
    issue = await service.change_status(
        session,
        issue_id,
        context,
        body.status,
        can_manage=context.has_permission("issue:manage"),
    )
    await session.commit()
    return ok({"id": issue.id, "status": issue.status, "closeDate": issue.close_date})


@router.delete("/{issue_id}", summary="删除问题")
async def delete_issue(
    issue_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("issue:view"))],
) -> object:
    """软删除问题（提报人 / 负责人 / 问题管理员）。"""
    await service.delete_issue(
        session,
        issue_id,
        context,
        can_manage=context.has_permission("issue:manage"),
    )
    await session.commit()
    return ok({"id": issue_id})
