"""数据范围与可见性求解测试（对应设计稿 03 §4、07 §5 与需求 3）。"""

from __future__ import annotations

from pms.org.scope import (
    DataScope,
    DepartmentIndex,
    can_see_dept,
    parse_custom_dept_ids,
    project_visible,
    visible_dept_ids,
    worklog_visible,
)

# 部门树：1 公司 -> 10 开发部 -> 101 后端组；20 测试部
DEPTS: list[tuple[int, int | None]] = [
    (1, None),
    (10, 1),
    (101, 10),
    (20, 1),
]
INDEX = DepartmentIndex.build(DEPTS)


def test_all_scope_returns_none() -> None:
    """全公司范围返回 None，表示不做部门过滤。"""
    assert visible_dept_ids([DataScope.ALL], 10, INDEX) is None


def test_dept_scope_only_self_dept() -> None:
    """本部门范围仅含本部门。"""
    assert visible_dept_ids([DataScope.DEPT], 10, INDEX) == {10}


def test_dept_and_sub_includes_children() -> None:
    """本部门及下级包含整棵子树。"""
    assert visible_dept_ids([DataScope.DEPT_AND_SUB], 10, INDEX) == {10, 101}


def test_custom_scope_expand_subtree() -> None:
    """自定义范围按指定部门展开子树。"""
    result = visible_dept_ids([DataScope.CUSTOM], 20, INDEX, custom_dept_ids=[10])
    assert result == {10, 101, 20}


def test_union_of_multi_roles() -> None:
    """多角色数据范围取并集。"""
    result = visible_dept_ids([DataScope.PROJECT, DataScope.CUSTOM], 20, INDEX, [101])
    assert result == {101, 20}


def test_parse_custom_dept_ids() -> None:
    """解析逗号分隔的部门 ID。"""
    assert parse_custom_dept_ids("10,101, bad") == {10, 101}


def test_can_see_dept() -> None:
    """可见判断：None 表示全部放行。"""
    assert can_see_dept(None, 99) is True
    assert can_see_dept({10}, 10) is True
    assert can_see_dept({10}, 20) is False


def test_department_index_path() -> None:
    """部门路径回填（根 -> 自身）。"""
    parents = {1: None, 10: 1, 101: 10, 20: 1}
    assert INDEX.path_of(101, parents) == [1, 10, 101]


def test_project_visible_for_same_dept_member() -> None:
    """需求 3：部门成员可看本部门项目进展。"""
    assert (
        project_visible(
            secret_level="INTERNAL",
            is_member=False,
            is_pm=False,
            is_dept_visible=True,
            is_owner_dept_visible=True,
            is_all_scope=False,
            public_visible=True,
        )
        is True
    )


def test_secret_project_hidden_from_other_dept() -> None:
    """机密项目仅项目组与领导可见。"""
    assert (
        project_visible(
            secret_level="SECRET",
            is_member=False,
            is_pm=False,
            is_dept_visible=True,
            is_owner_dept_visible=False,
            is_all_scope=False,
            public_visible=True,
        )
        is False
    )


def test_project_invisible_for_unrelated_user() -> None:
    """无关人员不可见内部项目。"""
    assert (
        project_visible(
            secret_level="INTERNAL",
            is_member=False,
            is_pm=False,
            is_dept_visible=False,
            is_owner_dept_visible=False,
            is_all_scope=False,
            public_visible=False,
        )
        is False
    )


def test_worklog_visible_for_same_project() -> None:
    """需求 3：项目组成员互看工作日志。"""
    assert (
        worklog_visible(
            is_self=False,
            is_subordinate=False,
            is_dept_scope=False,
            is_dept_privileged=False,
            dept_log_visible=False,
            same_project=True,
            project_log_visible=True,
        )
        is True
    )


def test_worklog_hidden_for_same_dept_other_project() -> None:
    """同部门非同项目成员默认不可见日志。"""
    assert (
        worklog_visible(
            is_self=False,
            is_subordinate=False,
            is_dept_scope=True,
            is_dept_privileged=False,
            dept_log_visible=False,
            same_project=False,
            project_log_visible=True,
        )
        is False
    )


def test_worklog_visible_for_dept_head() -> None:
    """部门领导可见本部门全员日志。"""
    assert (
        worklog_visible(
            is_self=False,
            is_subordinate=False,
            is_dept_scope=True,
            is_dept_privileged=True,
            dept_log_visible=False,
            same_project=False,
            project_log_visible=True,
        )
        is True
    )


def test_worklog_visible_for_manager() -> None:
    """直属上级可见下级日志。"""
    assert (
        worklog_visible(
            is_self=False,
            is_subordinate=True,
            is_dept_scope=False,
            is_dept_privileged=False,
            dept_log_visible=False,
            same_project=False,
            project_log_visible=False,
        )
        is True
    )
