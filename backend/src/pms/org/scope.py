"""数据范围求解（设计稿 03 §2、§4.1）。

纯函数实现，不依赖数据库，便于单元测试与越权用例验证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Iterable, Mapping, Sequence


class DataScope(StrEnum):
    """数据范围枚举（字典 `dict_data_scope`）。"""

    ALL = "ALL"
    DEPT_AND_SUB = "DEPT_AND_SUB"
    DEPT = "DEPT"
    PROJECT = "PROJECT"
    SELF = "SELF"
    CUSTOM = "CUSTOM"


@dataclass(slots=True)
class DepartmentIndex:
    """部门树索引：父 -> 子列表。"""

    children: dict[int, list[int]] = field(default_factory=dict)

    @classmethod
    def build(cls, pairs: Iterable[tuple[int, int | None]]) -> DepartmentIndex:
        """由 (部门ID, 父ID) 序列构建索引，根节点父 ID 为 None 或 0。"""
        index = cls()
        for dept_id, parent_id in pairs:
            index.children.setdefault(dept_id, [])
            if parent_id is None or parent_id == 0:
                continue
            index.children.setdefault(parent_id, []).append(dept_id)
        return index

    def subtree(self, dept_id: int) -> set[int]:
        """返回部门及其全部下级部门 ID。"""
        result: set[int] = set()
        stack: list[int] = [dept_id]
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(self.children.get(current, ()))
        return result

    def path_of(self, dept_id: int, parents: Mapping[int, int | None]) -> list[int]:
        """返回从根到该部门的 ID 路径（含自身）。"""
        path: list[int] = []
        current: int | None = dept_id
        seen: set[int] = set()
        while current is not None and current != 0 and current not in seen:
            seen.add(current)
            path.append(current)
            current = parents.get(current)
        path.reverse()
        return path


_ROLE_SCOPE_SEPARATOR: Final[str] = ","


def parse_custom_dept_ids(raw: str | None) -> set[int]:
    """解析 CUSTOM 范围的部门 ID 字符串（逗号分隔）。"""
    if not raw:
        return set()
    return {int(item) for item in raw.split(_ROLE_SCOPE_SEPARATOR) if item.strip().isdigit()}


def visible_dept_ids(
    scopes: Iterable[DataScope | str],
    dept_id: int,
    index: DepartmentIndex,
    custom_dept_ids: Iterable[int] = (),
) -> set[int] | None:
    """求解可见部门集合。

    参数:
        scopes: 用户全部角色的数据范围（取并集）。
        dept_id: 用户所属部门。
        index: 部门树索引。
        custom_dept_ids: CUSTOM 范围指定的部门（含下级）。

    返回:
        `None` 表示「全公司可见」；否则为允许的部门 ID 集合（恒包含本人部门）。
    """
    normalized = {DataScope(item) for item in scopes}
    if DataScope.ALL in normalized:
        return None

    allowed: set[int] = set()
    for scope in normalized:
        match scope:
            case DataScope.DEPT_AND_SUB:
                allowed |= index.subtree(dept_id)
            case DataScope.DEPT:
                allowed.add(dept_id)
            case DataScope.CUSTOM:
                for custom_id in custom_dept_ids:
                    allowed |= index.subtree(custom_id)
            case DataScope.PROJECT | DataScope.SELF:
                # 项目范围与个人范围不通过部门维度放行
                continue
    allowed.add(dept_id)
    return allowed


def can_see_dept(
    visible: set[int] | None,
    target_dept_id: int,
) -> bool:
    """判断目标部门是否在可见集合内。"""
    return visible is None or target_dept_id in visible


def project_visible(
    *,
    secret_level: str,
    is_member: bool,
    is_pm: bool,
    is_dept_visible: bool,
    is_owner_dept_visible: bool,
    is_all_scope: bool,
    public_visible: bool,
) -> bool:
    """项目可见性判定（设计稿 03 §4.1）。

    参数:
        secret_level: 项目密级 PUBLIC / INTERNAL / SECRET。
        is_member: 是否项目成员。
        is_pm: 是否本项目 PM。
        is_dept_visible: 用户是否有「本部门项目进展可见」能力（角色数据范围 DEPT 或参数开启）。
        is_owner_dept_visible: 项目归属部门是否在用户可见部门集合内。
        is_all_scope: 用户是否拥有全部数据范围（EXEC/PMO）。
        public_visible: 参数 `project.public.visible`。
    """
    if secret_level == "SECRET":
        return is_member or is_pm or is_owner_dept_visible or is_all_scope
    if is_all_scope or is_member or is_pm:
        return True
    if is_dept_visible and is_owner_dept_visible:
        return True
    return secret_level == "PUBLIC" and public_visible


def worklog_visible(
    *,
    is_self: bool,
    is_subordinate: bool,
    is_dept_scope: bool,
    is_dept_privileged: bool,
    dept_log_visible: bool,
    same_project: bool,
    project_log_visible: bool,
) -> bool:
    """工作日志可见性判定（设计稿 03 §4.2、07 §5）。

    参数:
        is_self: 是否本人日志。
        is_subordinate: 作者是否为直属下级（层级由 `org.manager.depth` 控制）。
        is_dept_scope: 用户数据范围是否覆盖作者部门。
        is_dept_privileged: 用户是否部门领导 / PMO / 公司领导。
        dept_log_visible: 参数 `worklog.dept.visible`（同部门非同项目互看）。
        same_project: 是否同一项目组成员。
        project_log_visible: 参数 `worklog.project.visible`（项目组互看，需求 3）。
    """
    if is_self or is_subordinate:
        return True
    if is_dept_scope and (is_dept_privileged or dept_log_visible):
        return True
    return same_project and project_log_visible


def manager_within_depth(
    ancestor_ids: Sequence[int],
    manager_chain: Mapping[int, int | None],
    user_id: int,
    depth: int,
) -> bool:
    """判断某用户是否在指定层级内属于另一用户的下级。

    参数:
        ancestor_ids: 目标用户的上级链（由近到远）。
        manager_chain: 全局 用户 -> 直属上级 映射。
        user_id: 判定者（上级）ID。
        depth: 可见层级（`org.manager.depth`）。
    """
    return user_id in ancestor_ids[: max(depth, 0)]
