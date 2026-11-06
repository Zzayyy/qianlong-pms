"""变更定级、审批链与状态机测试（设计稿 06 §3 / §4.2 / §4.3）。"""

from __future__ import annotations

import pytest

from pms.change.rules import (
    ApprovalNode,
    ChangeLevel,
    ImpactInput,
    LevelThresholds,
    build_chain,
    cost_pct,
    evaluate_level,
    next_pending,
    schedule_pct,
)
from pms.change.state import ChangeStatus, assert_transit, can_transit
from pms.common.exceptions import StateInvalidError


def _impact(**kwargs: object) -> ImpactInput:
    """构造定级输入，默认「无影响」。"""
    defaults: dict[str, object] = {
        "scope_expanded": False,
        "schedule_impact_days": 0,
        "plan_total_days": 100,
        "cost_impact_amount": 0,
        "contract_amount": 100000,
        "contract_commitment": False,
        "need_new_resource": False,
        "tech_architecture": False,
        "high_risk": False,
    }
    defaults.update(kwargs)
    return ImpactInput(**defaults)  # type: ignore[arg-type]


def test_l1_when_no_material_impact() -> None:
    """影响轻微 → L1。"""
    assert evaluate_level(_impact(schedule_impact_days=2)) is ChangeLevel.L1


def test_l3_by_scope_expanded() -> None:
    """范围扩大 → L3。"""
    assert evaluate_level(_impact(scope_expanded=True)) is ChangeLevel.L3


def test_l3_by_schedule_ratio() -> None:
    """工期影响超过 10% → L3。"""
    assert evaluate_level(_impact(schedule_impact_days=15)) is ChangeLevel.L3


def test_l3_by_cost_ratio() -> None:
    """成本影响超过 10% → L3。"""
    assert evaluate_level(_impact(cost_impact_amount=20000)) is ChangeLevel.L3


def test_l3_by_contract_commitment() -> None:
    """涉及合同/客户承诺 → L3。"""
    assert evaluate_level(_impact(contract_commitment=True)) is ChangeLevel.L3


def test_l2_by_schedule_days() -> None:
    """工期影响 3~10 天且占比不超阈值 → L2。"""
    assert evaluate_level(_impact(schedule_impact_days=5)) is ChangeLevel.L2


def test_l2_by_new_resource_or_risk() -> None:
    """新增资源或引入高风险 → L2。"""
    assert evaluate_level(_impact(need_new_resource=True)) is ChangeLevel.L2
    assert evaluate_level(_impact(high_risk=True)) is ChangeLevel.L2
    assert evaluate_level(_impact(tech_architecture=True)) is ChangeLevel.L2


def test_ratio_helpers() -> None:
    """占比计算与 0 值保护。"""
    assert schedule_pct(_impact(schedule_impact_days=10, plan_total_days=100)) == 10.0
    assert cost_pct(_impact(cost_impact_amount=10000, contract_amount=100000)) == 10.0
    assert schedule_pct(_impact(schedule_impact_days=0, plan_total_days=0)) == 0.0
    assert cost_pct(_impact(cost_impact_amount=0, contract_amount=0)) == 0.0


def test_thresholds_configurable() -> None:
    """阈值放宽后同一影响由 L3 降为 L2。"""
    relaxed = LevelThresholds(schedule_pct=50, cost_pct=50, schedule_days_l3=30)
    assert evaluate_level(_impact(schedule_impact_days=15), relaxed) is ChangeLevel.L2


def test_chain_by_level() -> None:
    """审批链：第一节点为项目总监会签，L2/L3 保留 PMO/公司领导。"""
    l1 = build_chain("L1", directors=[11, 12])
    assert [node.node_role for node in l1] == ["DIRECTOR", "DIRECTOR"]
    assert {node.seq for node in l1} == {1}, "同序号表示会签"

    l2 = build_chain("L2", directors=[11, 12], pmo_id=3)
    assert [node.node_role for node in l2] == ["DIRECTOR", "DIRECTOR", "PMO"]
    assert [node.seq for node in l2] == [1, 1, 2]

    l3 = build_chain("L3", directors=[11], pmo_id=3, exec_id=4)
    assert [node.node_role for node in l3] == ["DIRECTOR", "PMO", "EXEC"]
    assert l3[0].sla_days == 2, "总监节点沿用一级审批时效"
    assert l3[2].sla_days == 5


def test_chain_requires_director() -> None:
    """未指派项目总监时不得生成审批链。"""
    with pytest.raises(ValueError):
        build_chain("L1", directors=[])


def test_next_pending_is_serial() -> None:
    """串行审批：每次只推进最小未完成序号。"""
    nodes = [
        ApprovalNode(1, "DEPT_HEAD", 2, 3),
        ApprovalNode(2, "PMO", 3, 3),
    ]
    assert next_pending(nodes, set()) is nodes[0]
    assert next_pending(nodes, {1}) is nodes[1]
    assert next_pending(nodes, {1, 2}) is None


def test_change_state_machine() -> None:
    """变更状态流转与终态。"""
    assert assert_transit("DRAFT", "SUBMITTED") is ChangeStatus.SUBMITTED
    assert assert_transit("SUBMITTED", "ASSESSED") is ChangeStatus.ASSESSED
    assert assert_transit("ASSESSED", "APPROVED") is ChangeStatus.APPROVED
    assert can_transit("APPROVED", "EXECUTING") is True
    assert can_transit("CLOSED", "EXECUTING") is False
    with pytest.raises(StateInvalidError):
        assert_transit("DRAFT", "APPROVED")
