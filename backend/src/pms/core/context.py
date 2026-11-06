"""请求级身份上下文（设计稿 03 §7）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_PRIVILEGED_ROLES: Final[frozenset[str]] = frozenset({"EXEC", "PMO"})
_DEPT_HEAD_ROLE: Final[str] = "DEPT_HEAD"


@dataclass(slots=True, frozen=True)
class AuthContext:
    """当前用户身份与可见范围。

    属性:
        user_id: 用户 ID。
        username: 登录名。
        real_name: 姓名。
        dept_id: 所属部门。
        dept_path: 部门层级路径，如 `/1/10/101/`。
        roles: 角色代码集合。
        permissions: 权限点集合。
        visible_dept_ids: 可见部门集合；`None` 表示全公司可见。
        manager_depth: 直属上级可见层级。
    """

    user_id: int
    username: str
    real_name: str
    dept_id: int
    dept_path: str
    roles: frozenset[str]
    permissions: frozenset[str]
    visible_dept_ids: frozenset[int] | None
    manager_depth: int = 1

    @property
    def is_all_scope(self) -> bool:
        """是否拥有全公司数据范围。"""
        return self.visible_dept_ids is None

    @property
    def is_dept_head(self) -> bool:
        """是否部门领导。"""
        return _DEPT_HEAD_ROLE in self.roles

    @property
    def is_privileged(self) -> bool:
        """是否公司领导或 PMO。"""
        return bool(self.roles & _PRIVILEGED_ROLES)

    def has_permission(self, code: str) -> bool:
        """判断是否具备指定功能权限点。"""
        return code in self.permissions

    def has_any_role(self, *codes: str) -> bool:
        """判断是否具备任一指定角色。"""
        return bool(self.roles.intersection(codes))

    def can_see_dept(self, dept_id: int) -> bool:
        """判断部门数据是否可见。"""
        return self.visible_dept_ids is None or dept_id in self.visible_dept_ids
