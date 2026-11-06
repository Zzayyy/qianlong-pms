"""变更自动定级与审批链生成（设计稿 06 §4.2 / §4.3）。

阈值全部由入参传入，业务侧从 `ConfigService` 读取（`change.level.*`），
**禁止在业务代码中硬编码阈值**。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pms.change.state import ChangeNode


class ChangeLevel(StrEnum):
    """变更级别。"""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ChangeType(StrEnum):
    """变更类型。"""

    SCOPE = "SCOPE"
    SCHEDULE = "SCHEDULE"
    COST = "COST"
    RESOURCE = "RESOURCE"
    TECH = "TECH"
    OTHER = "OTHER"


class ImpactDimension(StrEnum):
    """六维评估维度（06 §5.1）。"""

    SCOPE = "SCOPE"
    SCHEDULE = "SCHEDULE"
    COST = "COST"
    RESOURCE = "RESOURCE"
    RISK = "RISK"
    QUALITY = "QUALITY"


@dataclass(slots=True, frozen=True)
class LevelThresholds:
    """定级阈值（对应系统参数 `change.level.*`）。"""

    schedule_pct: float = 10.0
    cost_pct: float = 10.0
    schedule_days: int = 3
    cost_pct5: float = 5.0
    schedule_days_l3: int = 10
    # 超过审批 SLA（工作日）后自动升级提醒
    sla_days_l1: int = 2
    sla_days_l2: int = 3
    sla_days_l3: int = 5


@dataclass(slots=True, frozen=True)
class ImpactInput:
    """定级输入（来自六维评估）。"""

    scope_expanded: bool = False
    schedule_impact_days: float = 0
    plan_total_days: float = 0
    cost_impact_amount: float = 0
    contract_amount: float = 0
    contract_commitment: bool = False
    need_new_resource: bool = False
    tech_architecture: bool = False
    high_risk: bool = False


@dataclass(slots=True, frozen=True)
class ApprovalNode:
    """审批链节点。"""

    seq: int
    node_role: str
    approver_id: int
    sla_days: int


_DEFAULT_APPROVER: Final[int] = 0


def schedule_pct(impact: ImpactInput) -> float:
    """工期影响占比（%）；无计划总天数且有影响时按 100% 计。"""
    if impact.plan_total_days > 0:
        return impact.schedule_impact_days / impact.plan_total_days * 100
    return 100.0 if impact.schedule_impact_days > 0 else 0.0


def cost_pct(impact: ImpactInput) -> float:
    """成本影响占比（%）；无合同额且有影响时按 100% 计。"""
    if impact.contract_amount > 0:
        return impact.cost_impact_amount / impact.contract_amount * 100
    return 100.0 if impact.cost_impact_amount > 0 else 0.0


def evaluate_level(
    impact: ImpactInput, thresholds: LevelThresholds | None = None
) -> ChangeLevel:
    """按六维评估结果自动定级（L3 重大 / L2 重要 / L1 一般）。"""
    rule = thresholds or LevelThresholds()
    days = impact.schedule_impact_days
    sched_pct = schedule_pct(impact)
    amount_pct = cost_pct(impact)

    # L3：范围扩大 / 工期 > 阈值% 或 > 10 工作日 / 成本 > 阈值% / 涉及合同承诺
    if impact.scope_expanded:
        return ChangeLevel.L3
    if sched_pct > rule.schedule_pct or days > rule.schedule_days_l3:
        return ChangeLevel.L3
    if amount_pct > rule.cost_pct:
        return ChangeLevel.L3
    if impact.contract_commitment:
        return ChangeLevel.L3

    # L2：工期 > 3 天 / 成本 > 5% / 需新增资源 / 影响架构 / 引入高风险
    if days > rule.schedule_days:
        return ChangeLevel.L2
    if amount_pct > rule.cost_pct5:
        return ChangeLevel.L2
    if impact.need_new_resource:
        return ChangeLevel.L2
    if impact.tech_architecture:
        return ChangeLevel.L2
    if impact.high_risk:
        return ChangeLevel.L2

    return ChangeLevel.L1


def build_chain(
    level: ChangeLevel | str,
    *,
    directors: Sequence[int],
    pmo_id: int = _DEFAULT_APPROVER,
    exec_id: int = _DEFAULT_APPROVER,
    thresholds: LevelThresholds | None = None,
) -> list[ApprovalNode]:
    """按级别生成串行审批链（R-CHG-04：链生成后固定，人员变动走转办）。

    第一节点为**项目总监会签**：每个总监一行，`seq` 相同，全部通过后进入下一节点。
    L2 保留 PMO 节点，L3 再追加公司领导节点。
    """
    rule = thresholds or LevelThresholds()
    chain = ChangeLevel(level)
    if not directors:
        raise ValueError("项目总监不能为空")
    nodes = [
        ApprovalNode(1, ChangeNode.DIRECTOR, director_id, rule.sla_days_l1)
        for director_id in directors
    ]
    if chain is ChangeLevel.L1:
        return nodes

    if chain is ChangeLevel.L2:
        nodes.append(ApprovalNode(2, ChangeNode.PMO, pmo_id, rule.sla_days_l2))
        return nodes

    nodes.append(ApprovalNode(2, ChangeNode.PMO, pmo_id, rule.sla_days_l3))
    nodes.append(ApprovalNode(3, ChangeNode.EXEC, exec_id, rule.sla_days_l3))
    return nodes


def next_pending(nodes: list[ApprovalNode], done_seqs: set[int]) -> ApprovalNode | None:
    """取当前待审批节点（串行：序号最小且未完成）。"""
    for node in sorted(nodes, key=lambda item: item.seq):
        if node.seq not in done_seqs:
            return node
    return None
