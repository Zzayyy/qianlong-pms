"""项目与任务状态机测试（设计稿 05 §3 / §5）。"""

from __future__ import annotations

import pytest

from pms.common.exceptions import StateInvalidError
from pms.project.state import (
    ProjectStatus,
    TaskStatus,
    assert_task_transit,
    assert_transit,
    can_transit,
)


def test_draft_to_approving() -> None:
    """草稿可提交审批。"""
    assert can_transit(ProjectStatus.DRAFT, ProjectStatus.APPROVING) is True
    assert assert_transit("DRAFT", "APPROVING") is ProjectStatus.APPROVING


def test_approved_to_in_progress() -> None:
    """立项通过后可启动。"""
    assert can_transit(ProjectStatus.APPROVED, ProjectStatus.IN_PROGRESS) is True


def test_illegal_transition_raises() -> None:
    """草稿不可直接完成。"""
    with pytest.raises(StateInvalidError):
        assert_transit(ProjectStatus.DRAFT, ProjectStatus.COMPLETED)


def test_terminated_is_terminal() -> None:
    """终止后不可再流转。"""
    assert can_transit(ProjectStatus.TERMINATED, ProjectStatus.IN_PROGRESS) is False


def test_task_transitions() -> None:
    """任务状态流转与非法回退。"""
    assert assert_task_transit("NOT_STARTED", "IN_PROGRESS") is TaskStatus.IN_PROGRESS
    with pytest.raises(StateInvalidError):
        assert_task_transit(TaskStatus.DONE, TaskStatus.CANCELLED)
