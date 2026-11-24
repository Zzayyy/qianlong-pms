"""问题跟踪枚举：类型、状态、严重程度、优先级。"""

from __future__ import annotations

from typing import Final


class IssueType:
    """问题类型。

    - `BUG`：开发/测试/验收阶段发现的功能缺陷，项目内闭环；
    - `PROD`：上线或交付后在真实环境出现的生产问题，线上闭环。
    """

    BUG: Final[str] = "BUG"
    PROD: Final[str] = "PROD"


class IssueStatus:
    """问题状态：待处理 → 处理中 → 已关闭（可重开）。"""

    OPEN: Final[str] = "OPEN"
    IN_PROGRESS: Final[str] = "IN_PROGRESS"
    CLOSED: Final[str] = "CLOSED"


class Severity:
    """严重程度。"""

    LOW: Final[str] = "LOW"
    MEDIUM: Final[str] = "MEDIUM"
    HIGH: Final[str] = "HIGH"
    URGENT: Final[str] = "URGENT"


class Priority:
    """处理优先级。"""

    LOW: Final[str] = "LOW"
    MEDIUM: Final[str] = "MEDIUM"
    HIGH: Final[str] = "HIGH"


ISSUE_TYPES: Final[tuple[str, ...]] = (IssueType.BUG, IssueType.PROD)
ISSUE_STATUSES: Final[tuple[str, ...]] = (
    IssueStatus.OPEN,
    IssueStatus.IN_PROGRESS,
    IssueStatus.CLOSED,
)
SEVERITIES: Final[tuple[str, ...]] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.URGENT,
)
PRIORITIES: Final[tuple[str, ...]] = (
    Priority.LOW,
    Priority.MEDIUM,
    Priority.HIGH,
)
