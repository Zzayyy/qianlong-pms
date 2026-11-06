"""变更状态机（设计稿 06 §3）。

纯函数实现：非法流转抛 `StateInvalidError`（错误码 40901）。
"""

from __future__ import annotations

from enum import StrEnum

from pms.common.exceptions import StateInvalidError


class ChangeStatus(StrEnum):
    """变更状态。"""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSESSED = "ASSESSED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ApprovalStatus(StrEnum):
    """审批节点状态。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TRANSFERRED = "TRANSFERRED"


class ChangeNode(StrEnum):
    """审批节点角色（串行顺序由 `seq` 决定；同 `seq` 多行表示会签）。"""

    PM = "PM"
    DIRECTOR = "DIRECTOR"
    DEPT_HEAD = "DEPT_HEAD"
    PMO = "PMO"
    EXEC = "EXEC"


CHANGE_TRANSITIONS: dict[ChangeStatus, tuple[ChangeStatus, ...]] = {
    ChangeStatus.DRAFT: (ChangeStatus.SUBMITTED, ChangeStatus.WITHDRAWN),
    ChangeStatus.SUBMITTED: (
        ChangeStatus.ASSESSED,
        ChangeStatus.REJECTED,
        ChangeStatus.WITHDRAWN,
    ),
    ChangeStatus.ASSESSED: (
        ChangeStatus.APPROVED,
        ChangeStatus.REJECTED,
        ChangeStatus.DRAFT,
        ChangeStatus.WITHDRAWN,
    ),
    ChangeStatus.APPROVED: (ChangeStatus.EXECUTING, ChangeStatus.WITHDRAWN),
    ChangeStatus.EXECUTING: (
        ChangeStatus.VERIFIED,
        ChangeStatus.WITHDRAWN,
    ),
    ChangeStatus.VERIFIED: (ChangeStatus.CLOSED, ChangeStatus.EXECUTING),
    ChangeStatus.CLOSED: (),
    ChangeStatus.REJECTED: (),
    ChangeStatus.WITHDRAWN: (),
}


def can_transit(current: ChangeStatus | str, target: ChangeStatus | str) -> bool:
    """判断变更状态是否允许流转。"""
    return ChangeStatus(target) in CHANGE_TRANSITIONS[ChangeStatus(current)]


def assert_transit(current: ChangeStatus | str, target: ChangeStatus | str) -> ChangeStatus:
    """校验变更状态流转，非法时抛异常并返回目标状态。"""
    next_status = ChangeStatus(target)
    if next_status not in CHANGE_TRANSITIONS[ChangeStatus(current)]:
        raise StateInvalidError(f"{ChangeStatus(current)} 不允许流转到 {next_status}")
    return next_status
