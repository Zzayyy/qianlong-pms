"""组织权限域服务：登录、权限解析、部门与用户维护（设计稿 03）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import (
    BizRuleError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)
from pms.common.logging import get_logger
from pms.core.config import get_settings
from pms.core.redis import (
    PERM_CACHE,
    bump_user_epoch,
    cache_delete,
    cache_get,
    cache_set,
    get_user_epoch,
)
from pms.core.security import create_access_token, hash_password, verify_password
from pms.org.models import (
    SysDept,
    SysPermission,
    SysRole,
    SysRolePermission,
    SysUser,
    SysUserRole,
)
from pms.org.scope import (
    DataScope,
    DepartmentIndex,
    parse_custom_dept_ids,
    visible_dept_ids,
)
from pms.system.config_service import ConfigService

logger = get_logger(__name__)

PERM_CACHE_TTL: Final[int] = 600
MAX_LOGIN_FAIL: Final[int] = 5
LOCK_MINUTES: Final[int] = 15
_USER_STATUS: Final[frozenset[str]] = frozenset({"ENABLED", "DISABLED"})
_DATETIME_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


@dataclass(slots=True)
class LoginResult:
    """登录结果。"""

    token: str
    expires_in: int
    user_id: int
    username: str
    real_name: str
    dept_id: int
    dept_name: str
    roles: list[str]
    permissions: list[str]


async def resolve_user_permissions(session: AsyncSession, user_id: int) -> set[str]:
    """解析用户权限点（缓存 → 数据库）。"""
    cached = await cache_get(f"{PERM_CACHE}{user_id}")
    if cached is not None:
        try:
            return set(json.loads(cached))
        except json.JSONDecodeError:
            logger.warning("权限缓存解析失败，回源数据库：user=%s", user_id)

    stmt = (
        select(SysPermission.perm_code)
        .join(SysRolePermission, SysRolePermission.perm_id == SysPermission.id)
        .join(SysRole, SysRole.id == SysRolePermission.role_id)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(
            SysUserRole.user_id == user_id,
            SysUserRole.deleted == 0,
            SysRolePermission.deleted == 0,
            SysRole.deleted == 0,
            SysRole.status == "ENABLED",
            SysPermission.deleted == 0,
        )
    )
    result = await session.execute(stmt)
    permissions = set(result.scalars().all())
    await cache_set(
        f"{PERM_CACHE}{user_id}", json.dumps(sorted(permissions)), ttl=PERM_CACHE_TTL
    )
    return permissions


async def invalidate_user_permissions(user_id: int | None = None) -> None:
    """失效权限缓存（角色/授权变更后调用）。"""
    if user_id is None:
        return
    await cache_delete(f"{PERM_CACHE}{user_id}")


async def load_user_roles(session: AsyncSession, user_id: int) -> list[SysRole]:
    """查询用户生效角色。"""
    stmt = (
        select(SysRole)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(
            SysUserRole.user_id == user_id,
            SysUserRole.deleted == 0,
            SysRole.deleted == 0,
            SysRole.status == "ENABLED",
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def build_department_index(session: AsyncSession) -> DepartmentIndex:
    """构建部门树索引。"""
    stmt = select(SysDept.id, SysDept.parent_id).where(SysDept.deleted == 0)
    result = await session.execute(stmt)
    return DepartmentIndex.build(result.all())


async def build_auth_payload(
    session: AsyncSession, user: SysUser
) -> tuple[dict[str, object], set[str], set[int] | None]:
    """构造令牌声明、权限点与可见部门集合。"""
    roles = await load_user_roles(session, user.id)
    role_codes = [role.role_code for role in roles]
    permissions = await resolve_user_permissions(session, user.id)

    index = await build_department_index(session)
    custom: set[int] = set()
    for role in roles:
        custom |= parse_custom_dept_ids(role.custom_dept_ids)
    visible = visible_dept_ids(
        [DataScope(role.data_scope) for role in roles],
        user.dept_id,
        index,
        custom,
    )
    config = ConfigService(session)
    manager_depth = await config.get_int("org.manager.depth")

    payload: dict[str, object] = {
        "sub": str(user.id),
        "username": user.username,
        "realName": user.real_name,
        "dept": user.dept_id,
        "roles": role_codes,
        "mdepth": manager_depth,
    }
    if visible is not None:
        payload["vdepts"] = sorted(visible)
    return payload, permissions, visible


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
) -> LoginResult:
    """账号密码登录（含失败锁定，设计稿 09 §4 C9）。"""
    stmt = select(SysUser).where(SysUser.username == username, SysUser.deleted == 0)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError("用户名或密码错误")

    if user.locked_until:
        locked_at = datetime.strptime(user.locked_until, _DATETIME_FORMAT)
        if locked_at > datetime.now():
            raise BizRuleError(f"账号已锁定，请在 {user.locked_until} 后重试")

    if user.status != "ENABLED":
        raise UnauthorizedError("账号已停用")

    if not verify_password(password, user.password_hash):
        user.login_fail_count += 1
        if user.login_fail_count >= MAX_LOGIN_FAIL:
            user.locked_until = (
                datetime.now() + timedelta(minutes=LOCK_MINUTES)
            ).strftime(_DATETIME_FORMAT)
            user.login_fail_count = 0
        await session.flush()
        raise UnauthorizedError("用户名或密码错误")

    user.login_fail_count = 0
    user.locked_until = None
    await session.flush()

    payload, permissions, _visible = await build_auth_payload(session, user)
    payload["epoch"] = await get_user_epoch(user.id)
    token = create_access_token(str(user.id), payload)

    dept_name = ""
    if user.dept_id:
        dept_stmt = select(SysDept.dept_name).where(SysDept.id == user.dept_id)
        dept_result = await session.execute(dept_stmt)
        dept_name = dept_result.scalar_one_or_none() or ""

    return LoginResult(
        token=token,
        expires_in=get_settings().jwt_expire_minutes * 60,
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        dept_id=user.dept_id,
        dept_name=dept_name,
        roles=list(payload.get("roles", [])),  # type: ignore[arg-type]
        permissions=sorted(permissions),
    )


async def list_dept_tree(session: AsyncSession) -> list[SysDept]:
    """部门列表（按层级与排序）。"""
    stmt = (
        select(SysDept)
        .where(SysDept.deleted == 0)
        .order_by(SysDept.level, SysDept.sort, SysDept.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _user_filters(
    visible: set[int] | None, keyword: str, dept_id: int
) -> list[ColumnElement[bool]]:
    """组装用户列表过滤条件（数据范围 / 关键字 / 部门）。"""
    filters: list[ColumnElement[bool]] = [SysUser.deleted == 0]
    if visible is not None:
        filters.append(SysUser.dept_id.in_(visible))
    if dept_id:
        filters.append(SysUser.dept_id == dept_id)
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(SysUser.real_name.like(pattern) | SysUser.username.like(pattern))
    return filters


async def count_users(
    session: AsyncSession,
    visible: set[int] | None,
    keyword: str,
    dept_id: int = 0,
) -> int:
    """统计用户数（受数据范围约束）。"""
    stmt = select(func.count(SysUser.id)).where(*_user_filters(visible, keyword, dept_id))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_users(
    session: AsyncSession,
    visible: set[int] | None,
    keyword: str,
    offset: int,
    limit: int,
    dept_id: int = 0,
) -> list[SysUser]:
    """分页查询用户（受数据范围约束）。"""
    stmt = (
        select(SysUser)
        .where(*_user_filters(visible, keyword, dept_id))
        .order_by(SysUser.id)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_user_role_names(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, list[str]]:
    """批量查询用户角色名称（列表页展示用，避免 N+1）。"""
    if not user_ids:
        return {}
    stmt = (
        select(SysUserRole.user_id, SysRole.role_name)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysUserRole.user_id.in_(user_ids),
            SysUserRole.deleted == 0,
            SysRole.deleted == 0,
        )
        .order_by(SysRole.sort, SysRole.id)
    )
    result: dict[int, list[str]] = {}
    for user_id, role_name in (await session.execute(stmt)).all():
        result.setdefault(int(user_id), []).append(str(role_name))
    return result


async def count_users_by_dept(session: AsyncSession) -> dict[int, int]:
    """按部门统计在职人数（用于组织树展示）。"""
    result = await session.execute(
        select(SysUser.dept_id, func.count(SysUser.id))
        .where(SysUser.deleted == 0)
        .group_by(SysUser.dept_id)
    )
    return {int(dept_id): int(count) for dept_id, count in result.all()}


async def create_dept(
    session: AsyncSession,
    *,
    dept_code: str,
    dept_name: str,
    parent_id: int = 0,
    dept_type: str = "DEPT",
    leader_id: int | None = None,
    sort: int = 0,
    status: str = "ENABLED",
    operator_id: int = 0,
) -> SysDept:
    """新增部门并按父节点推导 `path` / `level`。

    实现说明：`path` 形如 `/1/12/`，与 `system/seed.py` 的初始化逻辑保持一致；
    部门编码全局唯一（软删标记不占用编码）。

    Raises:
        NotFoundError: 父部门不存在。
        ConflictError: 部门编码重复。
    """
    exists = await session.execute(
        select(SysDept.id).where(SysDept.dept_code == dept_code, SysDept.deleted == 0)
    )
    if exists.scalar_one_or_none() is not None:
        raise ConflictError(f"部门编码已存在：{dept_code}")

    parent_path = "/"
    level = 1
    if parent_id:
        parent = await session.get(SysDept, parent_id)
        if parent is None or parent.deleted != 0:
            raise NotFoundError("上级部门不存在")
        parent_path = parent.path or "/"
        level = parent.level + 1

    dept = SysDept(
        parent_id=parent_id,
        dept_code=dept_code,
        dept_name=dept_name,
        dept_type="COMPANY" if parent_id == 0 else dept_type,
        leader_id=leader_id,
        level=level,
        sort=sort,
        status=status,
        path=parent_path,
        create_by=operator_id,
    )
    session.add(dept)
    await session.flush()
    dept.path = f"{parent_path}{dept.id}/"
    await session.flush()
    return dept


async def update_dept(
    session: AsyncSession,
    dept_id: int,
    *,
    dept_name: str | None = None,
    dept_type: str | None = None,
    leader_id: int | None = None,
    sort: int | None = None,
    status: str | None = None,
    parent_id: int | None = None,
    operator_id: int = 0,
) -> SysDept:
    """修改部门（改名 / 负责人 / 排序 / 启停 / 调整上级）。

    Raises:
        NotFoundError: 部门不存在。
        BizRuleError: 上级不能是自身或自己的下级（成环）。
    """
    dept = await session.get(SysDept, dept_id)
    if dept is None or dept.deleted != 0:
        raise NotFoundError("部门不存在")

    if parent_id is not None and parent_id != dept.parent_id:
        if parent_id == dept_id:
            raise BizRuleError("上级部门不能是自身")
        children = await _descendant_ids(session, dept_id)
        if parent_id in children:
            raise BizRuleError("不能把部门移动到自己的下级")
        parent = await session.get(SysDept, parent_id) if parent_id else None
        if parent_id and (parent is None or parent.deleted != 0):
            raise NotFoundError("上级部门不存在")
        dept.parent_id = parent_id
        base_path = parent.path if parent else "/"
        base_level = parent.level if parent else 0
        dept.path = f"{base_path}{dept.id}/"
        dept.level = base_level + 1
        await _rebuild_subtree(session, dept_id, dept.path, dept.level)

    if dept_name is not None:
        dept.dept_name = dept_name
    if dept_type is not None:
        dept.dept_type = dept_type
    if leader_id is not None:
        dept.leader_id = leader_id
    if sort is not None:
        dept.sort = sort
    if status is not None:
        dept.status = status
    dept.update_by = operator_id
    await session.flush()
    return dept


async def delete_dept(session: AsyncSession, dept_id: int, operator_id: int = 0) -> None:
    """删除部门（软删）；有下级或在职人员时拒绝。

    Raises:
        NotFoundError: 部门不存在。
        BizRuleError: 存在下级部门或在职人员。
    """
    dept = await session.get(SysDept, dept_id)
    if dept is None or dept.deleted != 0:
        raise NotFoundError("部门不存在")

    children = await _descendant_ids(session, dept_id)
    if children:
        raise BizRuleError("请先删除或迁移下级部门")

    user_count = await session.execute(
        select(func.count(SysUser.id)).where(
            SysUser.dept_id == dept_id, SysUser.deleted == 0, SysUser.status == "ENABLED"
        )
    )
    if int(user_count.scalar_one() or 0) > 0:
        raise BizRuleError("部门下仍存在在职人员，请先调整人员部门")

    dept.deleted = 1
    dept.update_by = operator_id
    await session.flush()


async def _descendant_ids(session: AsyncSession, dept_id: int) -> set[int]:
    """按 `path` 前缀求全部下级部门 ID（含间接下级）。"""
    dept = await session.get(SysDept, dept_id)
    if dept is None:
        return set()
    result = await session.execute(
        select(SysDept.id, SysDept.parent_id).where(SysDept.deleted == 0)
    )
    rows = result.all()
    children_map: dict[int, list[int]] = {}
    for row_id, parent_id in rows:
        children_map.setdefault(parent_id, []).append(row_id)

    found: set[int] = set()
    stack = list(children_map.get(dept_id, []))
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(children_map.get(current, []))
    return found


async def _rebuild_subtree(
    session: AsyncSession, dept_id: int, parent_path: str, parent_level: int
) -> None:
    """调整上级后重建子树的 `path` / `level`，保证数据范围求解正确。"""
    children = await session.execute(
        select(SysDept)
        .where(SysDept.parent_id == dept_id, SysDept.deleted == 0)
        .order_by(SysDept.sort, SysDept.id)
    )
    for child in children.scalars().all():
        child.path = f"{parent_path}{child.id}/"
        child.level = parent_level + 1
        await _rebuild_subtree(session, child.id, child.path, child.level)
    await session.flush()


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    real_name: str,
    dept_id: int,
    manager_id: int | None = None,
    mobile: str = "",
    email: str = "",
    operator_id: int = 0,
) -> SysUser:
    """创建用户（用户名唯一校验）。"""
    exists = await session.execute(
        select(SysUser.id).where(SysUser.username == username, SysUser.deleted == 0)
    )
    if exists.scalar_one_or_none() is not None:
        raise BizRuleError(f"用户名已存在：{username}")

    user = SysUser(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        dept_id=dept_id,
        manager_id=manager_id,
        mobile=mobile,
        email=email,
        create_by=operator_id,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user(session: AsyncSession, user_id: int) -> SysUser:
    """取用户；不存在或已删除抛 `NotFoundError`。"""
    user = await session.get(SysUser, user_id)
    if user is None or user.deleted != 0:
        raise NotFoundError("用户不存在")
    return user


async def update_user(
    session: AsyncSession,
    user_id: int,
    *,
    real_name: str | None = None,
    dept_id: int | None = None,
    manager_id: int | None = None,
    mobile: str | None = None,
    email: str | None = None,
    employee_no: str | None = None,
    cost_rate: float | None = None,
    operator_id: int = 0,
) -> SysUser:
    """修改人员档案（含部门调整）。

    Raises:
        NotFoundError: 用户不存在或目标部门不存在。
    """
    user = await get_user(session, user_id)
    scope_changed = False
    if dept_id is not None:
        dept = await session.get(SysDept, dept_id) if dept_id else None
        if dept_id and (dept is None or dept.deleted != 0):
            raise NotFoundError("部门不存在")
        scope_changed = dept_id != user.dept_id
        user.dept_id = dept_id
    if real_name is not None:
        user.real_name = real_name
    if manager_id is not None:
        scope_changed = scope_changed or manager_id != user.manager_id
        user.manager_id = manager_id
    if mobile is not None:
        user.mobile = mobile
    if email is not None:
        user.email = email
    if employee_no is not None:
        user.employee_no = employee_no
    if cost_rate is not None:
        user.cost_rate = cost_rate
    user.update_by = operator_id
    await session.flush()
    if scope_changed:
        # 部门/上级变化会影响数据范围，旧令牌需重新登录以刷新
        await bump_user_epoch(user_id)
    return user


async def change_user_status(
    session: AsyncSession, user_id: int, status: str, operator_id: int = 0
) -> SysUser:
    """启用 / 停用账号（停用后立即无法登录）。

    Raises:
        NotFoundError: 用户不存在。
        BizRuleError: 状态取值非法。
    """
    if status not in _USER_STATUS:
        raise BizRuleError(f"非法的账号状态：{status}")
    user = await get_user(session, user_id)
    user.status = status
    user.update_by = operator_id
    if status == "ENABLED":
        user.login_fail_count = 0
        user.locked_until = None
    await session.flush()
    if status == "DISABLED":
        # 停用后立即踢下线，不等令牌过期
        await bump_user_epoch(user_id)
    return user


async def reset_user_password(
    session: AsyncSession, user_id: int, password: str, operator_id: int = 0
) -> None:
    """管理员重置指定账号密码（同时解锁）。

    Raises:
        NotFoundError: 用户不存在。
        BizRuleError: 口令为空。
    """
    if not password:
        raise BizRuleError("密码不能为空")
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    user.login_fail_count = 0
    user.locked_until = None
    user.update_by = operator_id
    await session.flush()
    await bump_user_epoch(user_id)
    logger.info("管理员重置密码：user=%s operator=%s", user_id, operator_id)


async def change_password(
    session: AsyncSession,
    user_id: int,
    old_password: str,
    new_password: str,
) -> None:
    """用户自助修改密码（校验原密码，成功后旧令牌全部失效）。

    Raises:
        NotFoundError: 用户不存在。
        BizRuleError: 原密码错误、新密码为空或与原密码相同。
    """
    user = await get_user(session, user_id)
    if not verify_password(old_password, user.password_hash):
        raise BizRuleError("原密码不正确")
    if not new_password:
        raise BizRuleError("新密码不能为空")
    if old_password == new_password:
        raise BizRuleError("新密码不能与原密码相同")
    user.password_hash = hash_password(new_password)
    user.login_fail_count = 0
    user.locked_until = None
    user.update_by = user_id
    await session.flush()
    await bump_user_epoch(user_id)
    logger.info("用户修改密码：user=%s", user_id)


async def unlock_user(session: AsyncSession, user_id: int, operator_id: int = 0) -> SysUser:
    """解除登录失败锁定。

    Raises:
        NotFoundError: 用户不存在。
    """
    user = await get_user(session, user_id)
    user.login_fail_count = 0
    user.locked_until = None
    user.update_by = operator_id
    await session.flush()
    logger.info("账号已解锁：user=%s operator=%s", user_id, operator_id)
    return user


async def list_user_role_ids(session: AsyncSession, user_id: int) -> list[int]:
    """查询用户当前角色 ID（用于授权界面回显）。"""
    result = await session.execute(
        select(SysUserRole.role_id).where(
            SysUserRole.user_id == user_id, SysUserRole.deleted == 0
        )
    )
    return [int(row) for row in result.scalars().all()]


async def assign_roles(
    session: AsyncSession, user_id: int, role_ids: list[int], operator_id: int = 0
) -> None:
    """为用户分配角色（全量覆盖，并使权限缓存失效）。"""
    current = await session.execute(
        select(SysUserRole).where(SysUserRole.user_id == user_id, SysUserRole.deleted == 0)
    )
    for relation in current.scalars().all():
        relation.deleted = 1
        relation.update_by = operator_id
    for role_id in role_ids:
        session.add(SysUserRole(user_id=user_id, role_id=role_id, create_by=operator_id))
    await session.flush()
    await invalidate_user_permissions(user_id)
    # 角色变化会同时影响权限点与数据范围，强制重新登录
    await bump_user_epoch(user_id)


async def set_role_permissions(
    session: AsyncSession, role_id: int, perm_ids: list[int], operator_id: int = 0
) -> None:
    """为角色授权（全量覆盖），并失效相关用户权限缓存。"""
    role = await session.get(SysRole, role_id)
    if role is None:
        raise NotFoundError("角色不存在")

    current = await session.execute(
        select(SysRolePermission).where(
            SysRolePermission.role_id == role_id, SysRolePermission.deleted == 0
        )
    )
    for relation in current.scalars().all():
        relation.deleted = 1
        relation.update_by = operator_id
    for perm_id in perm_ids:
        session.add(SysRolePermission(role_id=role_id, perm_id=perm_id, create_by=operator_id))
    await session.flush()

    users = await session.execute(
        select(SysUserRole.user_id).where(
            SysUserRole.role_id == role_id, SysUserRole.deleted == 0
        )
    )
    for user_id in users.scalars().all():
        await invalidate_user_permissions(user_id)


# ---------------- 角色管理 ----------------
_ROLE_STATUS: Final[frozenset[str]] = frozenset({"ENABLED", "DISABLED"})
_DATA_SCOPES: Final[frozenset[str]] = frozenset(item.value for item in DataScope)


def _normalize_data_scope(scope: str) -> str:
    """校验并规范化数据范围。

    Raises:
        BizRuleError: 取值不在枚举内。
    """
    value = (scope or "").strip().upper()
    if value not in _DATA_SCOPES:
        raise BizRuleError(f"非法的数据范围：{scope}")
    return value


async def get_role(session: AsyncSession, role_id: int) -> SysRole:
    """取角色；不存在或已删除抛 `NotFoundError`。"""
    role = await session.get(SysRole, role_id)
    if role is None or role.deleted != 0:
        raise NotFoundError("角色不存在")
    return role


async def list_roles_with_stats(session: AsyncSession) -> list[dict[str, object]]:
    """角色列表（附用户数与权限数，供管理页展示）。"""
    roles = list(
        (
            await session.execute(
                select(SysRole).where(SysRole.deleted == 0).order_by(SysRole.sort, SysRole.id)
            )
        )
        .scalars()
        .all()
    )
    user_counts = {
        int(role_id): int(count)
        for role_id, count in (
            await session.execute(
                select(SysUserRole.role_id, func.count(SysUserRole.id))
                .where(SysUserRole.deleted == 0)
                .group_by(SysUserRole.role_id)
            )
        ).all()
    }
    perm_counts = {
        int(role_id): int(count)
        for role_id, count in (
            await session.execute(
                select(SysRolePermission.role_id, func.count(SysRolePermission.id))
                .where(SysRolePermission.deleted == 0)
                .group_by(SysRolePermission.role_id)
            )
        ).all()
    }
    return [
        {
            "id": role.id,
            "roleCode": role.role_code,
            "roleName": role.role_name,
            "dataScope": role.data_scope,
            "customDeptIds": role.custom_dept_ids,
            "builtin": role.builtin,
            "sort": role.sort,
            "status": role.status,
            "userCount": user_counts.get(role.id, 0),
            "permCount": perm_counts.get(role.id, 0),
        }
        for role in roles
    ]


async def create_role(
    session: AsyncSession,
    *,
    role_code: str,
    role_name: str,
    data_scope: str = "SELF",
    custom_dept_ids: str = "",
    sort: int = 0,
    operator_id: int = 0,
) -> SysRole:
    """新增角色（编码唯一）。

    Raises:
        BizRuleError: 编码为空/重复或数据范围非法。
    """
    code = role_code.strip().upper()
    name = role_name.strip()
    if not code:
        raise BizRuleError("角色编码不能为空")
    if not name:
        raise BizRuleError("角色名称不能为空")
    exists = await session.execute(
        select(SysRole.id).where(SysRole.role_code == code, SysRole.deleted == 0)
    )
    if exists.scalar_one_or_none() is not None:
        raise BizRuleError(f"角色编码已存在：{code}")
    scope = _normalize_data_scope(data_scope)
    role = SysRole(
        role_code=code,
        role_name=name,
        data_scope=scope,
        custom_dept_ids=custom_dept_ids if scope == DataScope.CUSTOM else "",
        sort=sort,
        status="ENABLED",
        builtin=0,
        create_by=operator_id,
    )
    session.add(role)
    await session.flush()
    return role


async def update_role(
    session: AsyncSession,
    role_id: int,
    *,
    role_name: str | None = None,
    data_scope: str | None = None,
    custom_dept_ids: str | None = None,
    sort: int | None = None,
    status: str | None = None,
    operator_id: int = 0,
) -> SysRole:
    """修改角色（内置角色不允许改数据范围）。

    Raises:
        NotFoundError: 角色不存在。
        BizRuleError: 数据范围非法或修改内置角色的数据范围。
    """
    role = await get_role(session, role_id)
    scope_changed = False
    if data_scope is not None:
        scope = _normalize_data_scope(data_scope)
        if role.builtin and scope != role.data_scope:
            raise BizRuleError("内置角色的数据范围不允许修改")
        scope_changed = scope != role.data_scope
        role.data_scope = scope
    if role_name is not None and role_name.strip():
        role.role_name = role_name.strip()
    if custom_dept_ids is not None:
        scope_changed = scope_changed or custom_dept_ids != role.custom_dept_ids
        role.custom_dept_ids = custom_dept_ids
    if sort is not None:
        role.sort = sort
    if status is not None:
        if status not in _ROLE_STATUS:
            raise BizRuleError(f"非法的角色状态：{status}")
        if role.builtin and status != "ENABLED":
            raise BizRuleError("内置角色不允许停用")
        role.status = status
    role.update_by = operator_id
    await session.flush()

    if scope_changed or status is not None:
        # 数据范围/启停变化会影响该角色下所有用户，强制刷新权限与登录态
        await _refresh_role_users(session, role_id, force_relogin=scope_changed)
    return role


async def delete_role(session: AsyncSession, role_id: int, operator_id: int = 0) -> None:
    """删除角色（内置角色不可删；仍有用户使用时拒绝）。

    Raises:
        NotFoundError: 角色不存在。
        BizRuleError: 内置角色或仍有用户关联。
    """
    role = await get_role(session, role_id)
    if role.builtin:
        raise BizRuleError("内置角色不允许删除")
    count = (
        await session.execute(
            select(func.count(SysUserRole.id)).where(
                SysUserRole.role_id == role_id, SysUserRole.deleted == 0
            )
        )
    ).scalar_one()
    if int(count):
        raise BizRuleError(f"仍有 {int(count)} 个用户使用该角色，请先解除关联")
    role.deleted = 1
    role.update_by = operator_id
    relations = (
        await session.execute(
            select(SysRolePermission).where(
                SysRolePermission.role_id == role_id, SysRolePermission.deleted == 0
            )
        )
    ).scalars()
    for relation in relations.all():
        relation.deleted = 1
        relation.update_by = operator_id
    await session.flush()
    logger.info("角色已删除：role=%s operator=%s", role_id, operator_id)


async def list_role_permission_ids(session: AsyncSession, role_id: int) -> list[int]:
    """查询角色已授权的权限点 ID（授权页回显）。"""
    await get_role(session, role_id)
    result = await session.execute(
        select(SysRolePermission.perm_id).where(
            SysRolePermission.role_id == role_id, SysRolePermission.deleted == 0
        )
    )
    return [int(perm_id) for perm_id in result.scalars().all()]


async def _refresh_role_users(
    session: AsyncSession, role_id: int, *, force_relogin: bool
) -> int:
    """刷新角色下所有用户的权限缓存，必要时使其重新登录。"""
    result = await session.execute(
        select(SysUserRole.user_id).where(
            SysUserRole.role_id == role_id, SysUserRole.deleted == 0
        )
    )
    user_ids = [int(user_id) for user_id in result.scalars().all()]
    for user_id in user_ids:
        await invalidate_user_permissions(user_id)
        if force_relogin:
            await bump_user_epoch(user_id)
    return len(user_ids)
