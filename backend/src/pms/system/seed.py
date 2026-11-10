"""初始化种子数据：字典、权限点、角色、部门、登录账号、系统参数。

设计稿 03（角色与权限点）、04 §5（字典与参数）、00 §3（部门与角色分层）。
**幂等**：已存在的数据按 `*_code` / `username` 跳过，重复执行只会补齐缺失项。

用法（命令行）：

    py -3.12 scripts/seed.py                    # 使用默认密码 Pms@12345
    py -3.12 scripts/seed.py --password Xxx@123 # 指定账号初始密码
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.logging import get_logger
from pms.core.security import hash_password
from pms.org.models import SysDept, SysPermission, SysRole, SysRolePermission, SysUser, SysUserRole
from pms.system.config_service import ConfigService
from pms.system.models import SysDict, SysDictItem

logger = get_logger(__name__)

DEFAULT_PASSWORD: Final[str] = "Pms@12345"

# ---------------- 字典 ----------------
# (字典编码, 字典名称, [(值, 显示名), ...])
DICTS: Final[tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]] = (
    (
        "dict_data_scope",
        "数据范围",
        (
            ("ALL", "全公司"),
            ("DEPT_AND_SUB", "本部门及下级"),
            ("DEPT", "本部门"),
            ("PROJECT", "参与项目"),
            ("SELF", "仅本人"),
            ("CUSTOM", "自定义部门"),
        ),
    ),
    (
        "dict_dept_type",
        "部门类型",
        (("COMPANY", "公司"), ("DEPT", "部门"), ("GROUP", "小组")),
    ),
    (
        "dict_project_type",
        "项目类型",
        (
            ("DEV", "研发项目"),
            ("PRESALE", "售前项目"),
            ("OPS", "运维项目"),
            ("OTHER", "其他"),
        ),
    ),
    (
        "dict_secret_level",
        "项目密级",
        (("PUBLIC", "公开"), ("INTERNAL", "内部"), ("SECRET", "机密")),
    ),
    (
        "dict_project_status",
        "项目状态",
        (
            ("DRAFT", "草稿"),
            ("APPROVING", "立项审批中"),
            ("APPROVED", "已立项"),
            ("IN_PROGRESS", "进行中"),
            ("SUSPENDED", "已挂起"),
            ("COMPLETED", "已完成"),
            ("ACCEPTED", "已验收"),
            ("TERMINATED", "已终止"),
            ("CLOSED", "已关闭"),
        ),
    ),
    (
        "dict_task_status",
        "任务状态",
        (
            ("NOT_STARTED", "未开始"),
            ("IN_PROGRESS", "进行中"),
            ("DONE", "已完成"),
            ("CANCELLED", "已取消"),
        ),
    ),
    (
        "dict_priority",
        "优先级",
        (("HIGH", "高"), ("MEDIUM", "中"), ("LOW", "低")),
    ),
    (
        "dict_risk_level",
        "风险等级",
        (("HIGH", "高"), ("MEDIUM", "中"), ("LOW", "低")),
    ),
    (
        "dict_health",
        "项目健康度",
        (("GREEN", "绿"), ("YELLOW", "黄"), ("RED", "红")),
    ),
    (
        "dict_customer_level",
        "客户等级",
        (("A", "A 类"), ("B", "B 类"), ("C", "C 类")),
    ),
    (
        "dict_customer_status",
        "客户状态",
        (
            ("POTENTIAL", "潜在客户"),
            ("COOPERATING", "合作中"),
            ("LOST", "已流失"),
            ("BLACKLIST", "黑名单"),
        ),
    ),
    (
        "dict_opp_stage",
        "商机阶段",
        (
            ("LEAD", "线索"),
            ("CONTACT", "沟通"),
            ("PROPOSAL", "方案"),
            ("QUOTE", "报价"),
            ("WON", "赢单"),
            ("LOST", "输单"),
        ),
    ),
    (
        "dict_opp_status",
        "商机状态",
        (("OPEN", "进行中"), ("WON", "赢单"), ("LOST", "输单"), ("CLOSED", "已关闭")),
    ),
)

# ---------------- 权限点 ----------------
# (权限编码, 名称, 类型)
PERMISSIONS: Final[tuple[tuple[str, str, str], ...]] = (
    ("org:dept:view", "部门查看", "API"),
    ("org:dept:manage", "部门维护", "API"),
    ("org:user:view", "用户查看", "API"),
    ("org:user:manage", "用户维护", "API"),
    ("org:user:delete", "用户删除", "API"),
    ("org:role:view", "角色查看", "API"),
    ("org:role:manage", "角色授权", "API"),
    ("sys:config", "系统参数", "API"),
    ("sys:dict:manage", "字典维护", "API"),
    ("sys:log:view", "日志审计", "API"),
    ("crm:customer:view", "客户查看", "API"),
    ("crm:customer:manage", "客户维护", "API"),
    ("crm:opp:view", "商机查看", "API"),
    ("crm:opp:manage", "商机维护", "API"),
    ("project:create", "项目立项", "API"),
    ("project:view", "项目查看", "API"),
    ("project:edit", "项目维护", "API"),
    ("project:approve", "立项审批", "API"),
    ("project:baseline", "基线管理", "API"),
    ("project:stage:edit", "阶段与里程碑维护", "API"),
    ("project:doc:upload", "项目文档上传", "API"),
    ("project:doc:manage", "项目文档管理", "API"),
    ("change:create", "变更申请", "API"),
    ("change:view", "变更查看", "API"),
    ("change:approve", "变更审批", "API"),
    ("change:execute", "变更执行", "API"),
    ("worklog:create", "日志填报", "API"),
    ("worklog:view", "日志查看", "API"),
    ("worklog:confirm", "日志确认", "API"),
    ("worklog:manage", "日志管理", "API"),
    ("report:view", "统计查看", "API"),
    ("report:export", "统计导出", "API"),
)

# ---------------- 角色 ----------------
# (角色编码, 名称, 数据范围, 权限编码集合)
_ROLE_VIEW_ALL: Final[tuple[str, ...]] = (
    "org:dept:view",
    "org:user:view",
    "org:role:view",
    "crm:customer:view",
    "crm:opp:view",
    "project:view",
    "change:view",
    "worklog:view",
    "report:view",
)

ROLES: Final[tuple[tuple[str, str, str, tuple[str, ...]], ...]] = (
    (
        "ADMIN",
        "系统管理员",
        "ALL",
        (
            "org:dept:view",
            "org:dept:manage",
            "org:user:view",
            "org:user:manage",
            "org:user:delete",
            "org:role:view",
            "org:role:manage",
            "sys:config",
            "sys:dict:manage",
            "sys:log:view",
            "crm:customer:view",
            "crm:customer:manage",
            "crm:opp:view",
            "crm:opp:manage",
            "project:create",
            "project:view",
            "project:edit",
            "project:approve",
            "project:baseline",
            "project:stage:edit",
            "project:doc:upload",
            "project:doc:manage",
            "change:create",
            "change:view",
            "change:approve",
            "change:execute",
            "worklog:create",
            "worklog:view",
            "worklog:confirm",
            "worklog:manage",
            "report:view",
            "report:export",
        ),
    ),
    (
        "EXEC",
        "公司领导",
        "ALL",
        _ROLE_VIEW_ALL
        + (
            "project:approve",
            # 公司领导可兜底维护项目节点/成员/文档（数据层已视为项目管理者）
            "project:edit",
            "project:stage:edit",
            "project:doc:upload",
            "project:doc:manage",
            "change:approve",
            "worklog:create",
            "report:export",
        ),
    ),
    (
        "PMO",
        "PMO",
        "ALL",
        _ROLE_VIEW_ALL
        + (
            "org:dept:manage",
            "org:user:manage",
            "org:role:manage",
            "sys:config",
            "sys:dict:manage",
            "sys:log:view",
            "project:create",
            "project:edit",
            "project:approve",
            "project:baseline",
            "project:stage:edit",
            "project:doc:upload",
            "project:doc:manage",
            "change:approve",
            "change:execute",
            "worklog:create",
            "worklog:manage",
            "report:export",
        ),
    ),
    (
        "DEPT_HEAD",
        "部门领导",
        "DEPT_AND_SUB",
        _ROLE_VIEW_ALL
        + (
            "worklog:create",
            "worklog:confirm",
            "project:doc:upload",
            "report:export",
            "change:approve",
        ),
    ),
    (
        "SALES",
        "销售",
        "DEPT",
        (
            "crm:customer:view",
            "crm:customer:manage",
            "crm:opp:view",
            "crm:opp:manage",
            "project:view",
            "project:doc:upload",
            "worklog:create",
            "worklog:view",
            "report:view",
        ),
    ),
    (
        "PM",
        "项目经理/产品",
        "PROJECT",
        (
            "org:user:view",
            "project:create",
            "project:view",
            "project:edit",
            "project:baseline",
            "project:stage:edit",
            "project:doc:upload",
            "project:doc:manage",
            "change:create",
            "change:view",
            "change:execute",
            "worklog:create",
            "worklog:view",
            "worklog:confirm",
            "report:view",
            "report:export",
        ),
    ),
    (
        "DEV",
        "开发",
        "SELF",
        (
            "project:view",
            "project:doc:upload",
            "change:view",
            "worklog:create",
            "worklog:view",
            "report:view",
        ),
    ),
    (
        "TEST",
        "测试",
        "SELF",
        (
            "project:view",
            "project:doc:upload",
            "change:view",
            "worklog:create",
            "worklog:view",
            "report:view",
        ),
    ),
    (
        "OPS",
        "运维",
        "SELF",
        (
            "project:view",
            "project:doc:upload",
            "change:view",
            "change:execute",
            "worklog:create",
            "worklog:view",
            "report:view",
        ),
    ),
)

# ---------------- 部门 ----------------
# (部门编码, 名称, 父编码, 类型)
DEPTS: Final[tuple[tuple[str, str, str | None, str], ...]] = (
    ("ROOT", "总公司", None, "COMPANY"),
    ("SALES", "销售部", "ROOT", "DEPT"),
    ("PRODUCT", "产品部", "ROOT", "DEPT"),
    ("DEV", "开发部", "ROOT", "DEPT"),
    ("TEST", "测试部", "ROOT", "DEPT"),
    ("OPS", "运维部", "ROOT", "DEPT"),
    ("PMO", "PMO 项目管理部", "ROOT", "DEPT"),
)

# ---------------- 账号 ----------------
# (登录名, 姓名, 部门编码, 角色编码集合)
USERS: Final[tuple[tuple[str, str, str, tuple[str, ...]], ...]] = (
    ("admin", "系统管理员", "ROOT", ("ADMIN",)),
    ("ceo", "公司领导", "ROOT", ("EXEC",)),
    ("pmo", "PMO 专员", "PMO", ("PMO",)),
    ("sales_lead", "销售部经理", "SALES", ("DEPT_HEAD", "SALES")),
    ("pm_lead", "产品部经理", "PRODUCT", ("DEPT_HEAD", "PM")),
    ("dev_lead", "开发部经理", "DEV", ("DEPT_HEAD", "DEV")),
    ("test_lead", "测试部经理", "TEST", ("DEPT_HEAD", "TEST")),
    ("ops_lead", "运维部经理", "OPS", ("DEPT_HEAD", "OPS")),
    ("sale1", "销售专员1", "SALES", ("SALES",)),
    ("pm1", "产品经理1", "PRODUCT", ("PM",)),
    ("dev1", "开发工程师1", "DEV", ("DEV",)),
    ("dev2", "开发工程师2", "DEV", ("DEV",)),
    ("test1", "测试工程师1", "TEST", ("TEST",)),
    ("ops1", "运维工程师1", "OPS", ("OPS",)),
)


@dataclass(slots=True)
class SeedSummary:
    """种子执行摘要。"""

    dicts: int = 0
    dict_items: int = 0
    permissions: int = 0
    roles: int = 0
    role_permissions: int = 0
    depts: int = 0
    users: int = 0
    user_roles: int = 0
    configs: int = 0
    accounts: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """新增条目总数。"""
        return (
            self.dicts
            + self.dict_items
            + self.permissions
            + self.roles
            + self.role_permissions
            + self.depts
            + self.users
            + self.user_roles
            + self.configs
        )


async def _ensure_dict(
    session: AsyncSession, dict_code: str, dict_name: str, items: tuple[tuple[str, str], ...]
) -> tuple[int, int]:
    """写入字典与字典项，返回 (新增字典数, 新增字典项数)。"""
    result = await session.execute(
        select(SysDict).where(SysDict.dict_code == dict_code, SysDict.deleted == 0)
    )
    dictionary = result.scalar_one_or_none()
    new_dict = 0
    if dictionary is None:
        dictionary = SysDict(dict_code=dict_code, dict_name=dict_name, builtin=1)
        session.add(dictionary)
        await session.flush()
        new_dict = 1

    exist_result = await session.execute(
        select(SysDictItem.item_value).where(
            SysDictItem.dict_code == dict_code, SysDictItem.deleted == 0
        )
    )
    existing = set(exist_result.scalars().all())
    new_items = 0
    for index, (value, label) in enumerate(items, start=1):
        if value in existing:
            continue
        session.add(
            SysDictItem(
                dict_id=dictionary.id,
                dict_code=dict_code,
                item_value=value,
                item_label=label,
                sort=index,
            )
        )
        new_items += 1
    if new_items:
        await session.flush()
    return new_dict, new_items


async def _ensure_permission(session: AsyncSession, perm_code: str, perm_name: str, perm_type: str) -> int:
    """写入权限点，返回新增数量。"""
    result = await session.execute(
        select(SysPermission).where(
            SysPermission.perm_code == perm_code, SysPermission.deleted == 0
        )
    )
    if result.scalar_one_or_none() is not None:
        return 0
    session.add(SysPermission(perm_code=perm_code, perm_name=perm_name, perm_type=perm_type))
    await session.flush()
    return 1


async def _role_permissions(session: AsyncSession, role: SysRole, perm_codes: tuple[str, ...]) -> int:
    """为角色补齐权限点，返回新增数量。"""
    perm_result = await session.execute(
        select(SysPermission.id, SysPermission.perm_code).where(
            SysPermission.perm_code.in_(perm_codes), SysPermission.deleted == 0
        )
    )
    perm_ids = {code: perm_id for perm_id, code in perm_result.all()}

    exist_result = await session.execute(
        select(SysRolePermission.perm_id).where(
            SysRolePermission.role_id == role.id, SysRolePermission.deleted == 0
        )
    )
    existing = set(exist_result.scalars().all())

    added = 0
    for code in perm_codes:
        perm_id = perm_ids.get(code)
        if perm_id is None or perm_id in existing:
            continue
        session.add(SysRolePermission(role_id=role.id, perm_id=perm_id))
        added += 1
    if added:
        await session.flush()
    return added


async def _ensure_role(
    session: AsyncSession, role_code: str, role_name: str, data_scope: str, perm_codes: tuple[str, ...]
) -> tuple[int, int]:
    """写入角色并授权，返回 (新增角色数, 新增授权数)。"""
    result = await session.execute(
        select(SysRole).where(SysRole.role_code == role_code, SysRole.deleted == 0)
    )
    role = result.scalar_one_or_none()
    new_role = 0
    if role is None:
        role = SysRole(role_code=role_code, role_name=role_name, data_scope=data_scope, builtin=1)
        session.add(role)
        await session.flush()
        new_role = 1
    return new_role, await _role_permissions(session, role, perm_codes)


async def _ensure_dept(
    session: AsyncSession, dept_code: str, dept_name: str, parent_id: int, parent_path: str, level: int
) -> SysDept:
    """写入部门并返回实体（不计数，由调用方判断）。"""
    result = await session.execute(
        select(SysDept).where(SysDept.dept_code == dept_code, SysDept.deleted == 0)
    )
    dept = result.scalar_one_or_none()
    if dept is None:
        dept = SysDept(
            dept_code=dept_code,
            dept_name=dept_name,
            parent_id=parent_id,
            level=level,
            path=parent_path,
            dept_type="COMPANY" if parent_id == 0 else "DEPT",
        )
        session.add(dept)
        await session.flush()
    dept.path = f"{parent_path}{dept.id}/"
    dept.level = level
    return dept


async def _ensure_user(
    session: AsyncSession,
    username: str,
    real_name: str,
    dept_id: int,
    manager_id: int | None,
    role_ids: list[int],
    password: str,
) -> tuple[int, int]:
    """写入账号并绑定角色，返回 (新增账号数, 新增关系数)。"""
    result = await session.execute(
        select(SysUser).where(SysUser.username == username, SysUser.deleted == 0)
    )
    user = result.scalar_one_or_none()
    new_user = 0
    if user is None:
        user = SysUser(
            username=username,
            real_name=real_name,
            password_hash=hash_password(password),
            dept_id=dept_id,
            manager_id=manager_id,
            status="ENABLED",
        )
        session.add(user)
        await session.flush()
        new_user = 1

    exist_result = await session.execute(
        select(SysUserRole.role_id).where(
            SysUserRole.user_id == user.id, SysUserRole.deleted == 0
        )
    )
    existing = set(exist_result.scalars().all())
    added = 0
    for role_id in role_ids:
        if role_id in existing:
            continue
        session.add(SysUserRole(user_id=user.id, role_id=role_id))
        added += 1
    if added:
        await session.flush()
    return new_user, added


async def seed_all(session: AsyncSession, password: str = DEFAULT_PASSWORD) -> SeedSummary:
    """执行完整初始化（幂等）。"""
    summary = SeedSummary()

    for dict_code, dict_name, items in DICTS:
        new_dict, new_items = await _ensure_dict(session, dict_code, dict_name, items)
        summary.dicts += new_dict
        summary.dict_items += new_items

    for perm_code, perm_name, perm_type in PERMISSIONS:
        summary.permissions += await _ensure_permission(session, perm_code, perm_name, perm_type)

    for role_code, role_name, data_scope, perm_codes in ROLES:
        new_role, new_links = await _ensure_role(session, role_code, role_name, data_scope, perm_codes)
        summary.roles += new_role
        summary.role_permissions += new_links

    dept_ids: dict[str, SysDept] = {}
    for dept_code, dept_name, parent_code, _dept_type in DEPTS:
        parent = dept_ids.get(parent_code) if parent_code else None
        parent_id = parent.id if parent else 0
        parent_path = parent.path if parent else "/"
        level = (parent.level + 1) if parent else 1
        exist_result = await session.execute(
            select(SysDept.id).where(SysDept.dept_code == dept_code, SysDept.deleted == 0)
        )
        existed = exist_result.scalar_one_or_none() is not None
        dept = await _ensure_dept(session, dept_code, dept_name, parent_id, parent_path, level)
        if not existed:
            summary.depts += 1
        dept_ids[dept_code] = dept

    role_result = await session.execute(
        select(SysRole.id, SysRole.role_code).where(SysRole.deleted == 0)
    )
    role_ids = {code: role_id for role_id, code in role_result.all()}

    lead_by_dept: dict[str, int] = {}
    for username, real_name, dept_code, role_codes in USERS:
        dept = dept_ids[dept_code]
        ids = [role_ids[code] for code in role_codes if code in role_ids]
        is_lead = "DEPT_HEAD" in role_codes
        manager_id = None
        if not is_lead:
            manager_id = lead_by_dept.get(dept_code)
        new_user, new_links = await _ensure_user(
            session, username, real_name, dept.id, manager_id, ids, password
        )
        summary.users += new_user
        summary.user_roles += new_links
        if is_lead:
            lead_by_dept[dept_code] = await _user_id(session, username)
            dept.leader_id = lead_by_dept[dept_code]
        summary.accounts.append(f"{username} / {real_name} / {dept.dept_name} / {','.join(role_codes)}")

    summary.configs += await ConfigService(session).seed_defaults()
    await session.commit()
    logger.info(
        "初始化完成：字典%s项 权限%s 角色%s 部门%s 账号%s 参数%s",
        summary.dict_items,
        summary.permissions,
        summary.roles,
        summary.depts,
        summary.users,
        summary.configs,
    )
    return summary


async def reset_password(session: AsyncSession, username: str, password: str) -> bool:
    """重置指定账号密码（同时解锁），账号不存在返回 False。"""
    result = await session.execute(
        select(SysUser).where(SysUser.username == username, SysUser.deleted == 0)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False
    user.password_hash = hash_password(password)
    user.login_fail_count = 0
    user.locked_until = None
    await session.commit()
    logger.info("已重置密码：%s", username)
    return True


async def _user_id(session: AsyncSession, username: str) -> int:
    """按登录名取用户 ID。"""
    result = await session.execute(
        select(SysUser.id).where(SysUser.username == username, SysUser.deleted == 0)
    )
    value = result.scalar_one_or_none()
    return int(value or 0)
