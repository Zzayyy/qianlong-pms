"""项目与任务状态机（设计稿 05 §3 / §5）。

纯函数实现，便于单元测试；状态流转非法时抛 `StateInvalidError`。
"""

from __future__ import annotations

from enum import StrEnum

from pms.common.exceptions import StateInvalidError


class ProjectStatus(StrEnum):
    """项目状态。"""

    DRAFT = "DRAFT"
    APPROVING = "APPROVING"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class TaskStatus(StrEnum):
    """任务状态。"""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class MilestoneStatus(StrEnum):
    """里程碑状态。"""

    PENDING = "PENDING"
    DELAYED = "DELAYED"
    REACHED = "REACHED"
    CANCELLED = "CANCELLED"


PROJECT_TRANSITIONS: dict[ProjectStatus, tuple[ProjectStatus, ...]] = {
    ProjectStatus.DRAFT: (ProjectStatus.APPROVING, ProjectStatus.TERMINATED),
    ProjectStatus.APPROVING: (
        ProjectStatus.APPROVED,
        ProjectStatus.DRAFT,
        ProjectStatus.TERMINATED,
    ),
    ProjectStatus.APPROVED: (ProjectStatus.IN_PROGRESS, ProjectStatus.TERMINATED),
    ProjectStatus.IN_PROGRESS: (
        ProjectStatus.SUSPENDED,
        ProjectStatus.COMPLETED,
        ProjectStatus.TERMINATED,
    ),
    ProjectStatus.SUSPENDED: (ProjectStatus.IN_PROGRESS, ProjectStatus.TERMINATED),
    ProjectStatus.COMPLETED: (ProjectStatus.ACCEPTED, ProjectStatus.IN_PROGRESS),
    ProjectStatus.ACCEPTED: (ProjectStatus.CLOSED,),
    ProjectStatus.TERMINATED: (),
    ProjectStatus.CLOSED: (),
}

TASK_TRANSITIONS: dict[TaskStatus, tuple[TaskStatus, ...]] = {
    TaskStatus.NOT_STARTED: (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED),
    TaskStatus.IN_PROGRESS: (
        TaskStatus.DONE,
        TaskStatus.NOT_STARTED,
        TaskStatus.CANCELLED,
    ),
    TaskStatus.DONE: (TaskStatus.IN_PROGRESS,),
    TaskStatus.CANCELLED: (TaskStatus.NOT_STARTED,),
}


def can_transit(current: ProjectStatus | str, target: ProjectStatus | str) -> bool:
    """判断项目状态是否允许流转。"""
    return ProjectStatus(target) in PROJECT_TRANSITIONS[ProjectStatus(current)]


def assert_transit(current: ProjectStatus | str, target: ProjectStatus | str) -> ProjectStatus:
    """校验项目状态流转，非法时抛异常并返回目标状态。"""
    next_status = ProjectStatus(target)
    if next_status not in PROJECT_TRANSITIONS[ProjectStatus(current)]:
        raise StateInvalidError(f"{ProjectStatus(current)} 不允许流转到 {next_status}")
    return next_status


def assert_task_transit(current: TaskStatus | str, target: TaskStatus | str) -> TaskStatus:
    """校验任务状态流转，非法时抛异常并返回目标状态。"""
    next_status = TaskStatus(target)
    if next_status not in TASK_TRANSITIONS[TaskStatus(current)]:
        raise StateInvalidError(f"{TaskStatus(current)} 不允许流转到 {next_status}")
    return next_status
