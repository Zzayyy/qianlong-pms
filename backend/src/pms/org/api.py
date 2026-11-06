"""组织权限接口（设计稿 09 §2.1）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.audit.service import record_login
from pms.common.exceptions import BizRuleError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import (
    Pagination,
    get_current_user,
    get_pagination,
    get_session,
    require_permissions,
)
from pms.core.redis import blacklist_add
from pms.core.security import decode_access_token
from pms.org import service
from pms.org.models import SysDept, SysRole, SysUser

router = APIRouter(prefix="/api/v1", tags=["组织与权限"])


class LoginIn(BaseModel):
    """登录入参。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserBrief(BaseModel):
    """用户概要。"""

    id: int
    username: str
    realName: str
    deptId: int
    status: str


class LoginOut(BaseModel):
    """登录出参。"""

    token: str
    expiresIn: int
    user: UserBrief
    roles: list[str]
    permissions: list[str]


class UserCreateIn(BaseModel):
    """创建用户入参。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    realName: str = Field(min_length=1, max_length=64)
    deptId: int
    managerId: int | None = None
    mobile: str = ""
    email: str = ""


class AssignRolesIn(BaseModel):
    """分配角色入参。"""

    roleIds: list[int] = Field(default_factory=list)


class RolePermissionIn(BaseModel):
    """角色授权入参。"""

    permIds: list[int] = Field(default_factory=list)


class DeptCreateIn(BaseModel):
    """新增部门入参。"""

    deptCode: str = Field(min_length=1, max_length=64)
    deptName: str = Field(min_length=1, max_length=128)
    parentId: int = 0
    deptType: str = "DEPT"
    leaderId: int | None = None
    sort: int = 0


class DeptUpdateIn(BaseModel):
    """修改部门入参（仅传需要改的字段）。"""

    deptName: str | None = Field(default=None, max_length=128)
    deptType: str | None = None
    leaderId: int | None = None
    sort: int | None = None
    status: str | None = None
    parentId: int | None = None


class UserUpdateIn(BaseModel):
    """修改人员入参（仅传需要改的字段）。"""

    realName: str | None = Field(default=None, max_length=64)
    deptId: int | None = None
    managerId: int | None = None
    mobile: str | None = None
    email: str | None = None
    employeeNo: str | None = None
    costRate: float | None = None


class UserStatusIn(BaseModel):
    """账号启停入参。"""

    status: str = Field(min_length=4, max_length=16)


class PasswordIn(BaseModel):
    """管理员重置密码入参。"""

    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/login", summary="登录")
async def login(
    body: LoginIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> object:
    """账号密码登录，返回 JWT 与权限点（成功与失败均写登录日志）。"""
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:500]
    try:
        result = await service.authenticate(session, body.username, body.password)
    except Exception as exc:  # noqa: BLE001  失败原因统一留痕后继续抛出
        await record_login(
            username=body.username,
            ip=ip,
            user_agent=user_agent,
            status="FAIL",
            message=str(exc)[:250],
        )
        raise
    await record_login(
        username=body.username,
        ip=ip,
        user_agent=user_agent,
        status="SUCCESS",
        message="登录成功",
    )
    payload = LoginOut(
        token=result.token,
        expiresIn=result.expires_in,
        user=UserBrief(
            id=result.user_id,
            username=result.username,
            realName=result.real_name,
            deptId=result.dept_id,
            status="ENABLED",
        ),
        roles=result.roles,
        permissions=result.permissions,
    )
    return ok(payload)


class LogoutIn(BaseModel):
    """登出入参（令牌不放 URL，避免泄漏）。"""

    token: str = Field(min_length=8, max_length=2048)


@router.post("/auth/logout", summary="登出")
async def logout(body: LogoutIn, request: Request) -> object:
    """将令牌加入黑名单（踢下线）并记录登出日志。"""
    decode_access_token(body.token)
    await blacklist_add(body.token, ttl=7 * 24 * 3600)
    await record_login(
        username=str(decode_access_token(body.token).get("sub") or ""),
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")[:500],
        status="LOGOUT",
        message="主动登出",
    )
    return ok(message="已登出")


@router.get("/auth/profile", summary="当前用户")
async def profile(
    context: Annotated[AuthContext, Depends(require_permissions())],
) -> object:
    """返回当前用户的身份、部门、角色与权限。"""
    return ok(
        {
            "id": context.user_id,
            "username": context.username,
            "realName": context.real_name,
            "deptId": context.dept_id,
            "roles": sorted(context.roles),
            "permissions": sorted(context.permissions),
            "allScope": context.is_all_scope,
        }
    )


@router.get("/depts/tree", summary="部门树")
async def dept_tree(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:dept:view"))],
) -> object:
    """返回全部部门（含人数，前端自行组装树）。"""
    depts: list[SysDept] = await service.list_dept_tree(session)
    counts = await service.count_users_by_dept(session)
    return ok(
        [
            {
                "id": dept.id,
                "parentId": dept.parent_id,
                "deptName": dept.dept_name,
                "deptCode": dept.dept_code,
                "deptType": dept.dept_type,
                "leaderId": dept.leader_id,
                "level": dept.level,
                "sort": dept.sort,
                "status": dept.status,
                "userCount": counts.get(dept.id, 0),
            }
            for dept in depts
        ]
    )


@router.post("/depts", summary="新增部门")
async def dept_create(
    body: DeptCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:dept:manage"))],
) -> object:
    """新增部门（`org:dept:manage`）。"""
    dept = await service.create_dept(
        session,
        dept_code=body.deptCode,
        dept_name=body.deptName,
        parent_id=body.parentId,
        dept_type=body.deptType,
        leader_id=body.leaderId,
        sort=body.sort,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": dept.id, "deptCode": dept.dept_code})


@router.put("/depts/{dept_id}", summary="修改部门")
async def dept_update(
    dept_id: int,
    body: DeptUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:dept:manage"))],
) -> object:
    """改名 / 换负责人 / 调排序 / 启停 / 调整上级。"""
    dept = await service.update_dept(
        session,
        dept_id,
        dept_name=body.deptName,
        dept_type=body.deptType,
        leader_id=body.leaderId,
        sort=body.sort,
        status=body.status,
        parent_id=body.parentId,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": dept.id, "deptName": dept.dept_name, "level": dept.level})


@router.delete("/depts/{dept_id}", summary="删除部门")
async def dept_delete(
    dept_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:dept:manage"))],
) -> object:
    """删除部门；存在下级或在职人员时拒绝。"""
    await service.delete_dept(session, dept_id, operator_id=context.user_id)
    await session.commit()
    return ok(message="部门已删除")


@router.get("/users", summary="用户列表")
async def user_list(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    keyword: Annotated[str, Query()] = "",
) -> object:
    """分页查询用户，**结果受数据范围约束**（设计稿 03 维度 ②）。"""
    visible = (
        None if context.visible_dept_ids is None else set(context.visible_dept_ids)
    )
    total = await service.count_users(session, visible, keyword)
    users: list[SysUser] = await service.list_users(
        session, visible, keyword, pagination.offset, pagination.limit
    )
    items = [
        {
            "id": user.id,
            "username": user.username,
            "realName": user.real_name,
            "deptId": user.dept_id,
            "mobile": user.mobile,
            "email": user.email,
            "status": user.status,
        }
        for user in users
    ]
    return paged(items, total, pagination.page_num, pagination.page_size)


@router.post("/users", summary="创建用户")
async def user_create(
    body: UserCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:manage"))],
) -> object:
    """创建用户并校验用户名唯一。"""
    user = await service.create_user(
        session,
        username=body.username,
        password=body.password,
        real_name=body.realName,
        dept_id=body.deptId,
        manager_id=body.managerId,
        mobile=body.mobile,
        email=body.email,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": user.id})


@router.get("/users/{user_id}/roles", summary="用户角色")
async def user_roles(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:view"))],
) -> object:
    """返回用户当前角色 ID 列表（授权界面回显）。"""
    return ok({"userId": user_id, "roleIds": await service.list_user_role_ids(session, user_id)})


@router.put("/users/{user_id}", summary="修改人员")
async def user_update(
    user_id: int,
    body: UserUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:manage"))],
) -> object:
    """修改人员档案（姓名 / 部门 / 上级 / 联系方式 / 工号 / 成本费率）。"""
    user = await service.update_user(
        session,
        user_id,
        real_name=body.realName,
        dept_id=body.deptId,
        manager_id=body.managerId,
        mobile=body.mobile,
        email=body.email,
        employee_no=body.employeeNo,
        cost_rate=body.costRate,
        operator_id=context.user_id,
    )
    await session.commit()
    return ok({"id": user.id, "realName": user.real_name, "deptId": user.dept_id})


@router.put("/users/{user_id}/status", summary="启停账号")
async def user_status(
    user_id: int,
    body: UserStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:manage"))],
) -> object:
    """启用 / 停用账号（停用后立即无法登录）。"""
    user = await service.change_user_status(
        session, user_id, body.status, operator_id=context.user_id
    )
    await session.commit()
    return ok({"id": user.id, "status": user.status})


@router.put("/users/{user_id}/password", summary="重置密码")
async def user_password(
    user_id: int,
    body: PasswordIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:user:manage"))],
) -> object:
    """管理员重置指定账号密码并解锁。"""
    await service.reset_user_password(
        session, user_id, body.password, operator_id=context.user_id
    )
    await session.commit()
    return ok(message="密码已重置")


@router.post("/users/{user_id}/roles", summary="分配角色")
async def assign_roles(
    user_id: int,
    body: AssignRolesIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:role:manage"))],
) -> object:
    """全量覆盖用户角色并使权限缓存失效。"""
    await service.assign_roles(session, user_id, body.roleIds, operator_id=context.user_id)
    await session.commit()
    return ok(message="角色已更新")


@router.get("/roles", summary="角色列表")
async def role_list(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:role:view"))],
) -> object:
    """返回角色及其数据范围配置。"""
    from sqlalchemy import select

    result = await session.execute(
        select(SysRole).where(SysRole.deleted == 0).order_by(SysRole.sort, SysRole.id)
    )
    roles = result.scalars().all()
    return ok(
        [
            {
                "id": role.id,
                "roleCode": role.role_code,
                "roleName": role.role_name,
                "dataScope": role.data_scope,
                "customDeptIds": role.custom_dept_ids,
                "builtin": role.builtin,
            }
            for role in roles
        ]
    )


@router.put("/roles/{role_id}/permissions", summary="角色授权")
async def role_permissions(
    role_id: int,
    body: RolePermissionIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:role:manage"))],
) -> object:
    """为角色配置权限点，并失效相关用户权限缓存。"""
    await service.set_role_permissions(
        session, role_id, body.permIds, operator_id=context.user_id
    )
    await session.commit()
    return ok(message="授权已更新")


@router.get("/permissions/tree", summary="权限点树")
async def permission_tree(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("org:role:view"))],
) -> object:
    """返回全部权限点（菜单/按钮/接口）。"""
    from sqlalchemy import select

    from pms.org.models import SysPermission

    result = await session.execute(
        select(SysPermission)
        .where(SysPermission.deleted == 0)
        .order_by(SysPermission.sort, SysPermission.id)
    )
    permissions = result.scalars().all()
    return ok(
        [
            {
                "id": perm.id,
                "permCode": perm.perm_code,
                "permName": perm.perm_name,
                "permType": perm.perm_type,
                "parentId": perm.parent_id,
            }
            for perm in permissions
        ]
    )


@router.get("/auth/demo", summary="演示守卫（无权限点要求）")
async def demo_guard(
    context: Annotated[AuthContext, Depends(get_current_user)],
) -> object:
    """仅校验登录态，用于联调。"""
    if not context.user_id:
        raise BizRuleError("无效的令牌")
    return ok({"userId": context.user_id})
