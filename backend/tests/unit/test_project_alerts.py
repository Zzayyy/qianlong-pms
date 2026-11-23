"""项目预警推导测试（进度延期 / 里程碑逾期 / 日志问题）。

预警是只读计算，不写风险台账；这里只验证规则口径。
"""

from __future__ import annotations

from datetime import date

from pms.project.alerts import build_alerts, log_risk_level, problem_summary
from pms.project.models import PrjMilestone, PrjProject, PrjStage, PrjTask

TODAY = date(2026, 1, 10)


def _project(**kwargs: object) -> PrjProject:
    """构造项目：默认进行中、计划 1 月 1 日结束。"""
    data: dict[str, object] = {
        "id": 1,
        "project_name": "测试项目",
        "status": "IN_PROGRESS",
        "plan_end": "2026-01-01",
        "progress": 40,
        "pm_id": 7,
    }
    data.update(kwargs)
    return PrjProject(**data)


def test_project_delay_alert() -> None:
    """项目超计划结束日 9 天：高风险，负责人取项目经理。"""
    alerts = build_alerts(
        project=_project(),
        stages=[],
        milestones=[],
        tasks=[],
        today=TODAY,
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.key == "PROJECT_DELAY"
    assert alert.level == "HIGH"
    assert alert.owner_id == 7
    assert "9 天" in alert.title


def test_project_delay_skipped_when_not_running() -> None:
    """草稿/已关闭项目不提示项目延期。"""
    alerts = build_alerts(
        project=_project(status="DRAFT"),
        stages=[],
        milestones=[],
        tasks=[],
        today=TODAY,
    )
    assert alerts == []


def test_stage_and_milestone_alerts() -> None:
    """阶段超期按天判级；已完成阶段/已达成里程碑不再提示。"""
    stages = [
        PrjStage(
            id=11,
            stage_name="开发",
            status="IN_PROGRESS",
            plan_end="2026-01-01",
            progress=30,
            owner_id=3,
        ),
        PrjStage(id=12, stage_name="测试", status="DONE", plan_end="2025-12-01"),
    ]
    milestones = [
        PrjMilestone(id=21, milestone_name="上线", status="PENDING", plan_date="2026-01-08"),
        PrjMilestone(id=22, milestone_name="评审", status="REACHED", plan_date="2025-12-01"),
    ]
    alerts = build_alerts(
        project=_project(status="COMPLETED", plan_end=None),
        stages=stages,
        milestones=milestones,
        tasks=[],
        today=TODAY,
    )
    keys = {item.key for item in alerts}
    assert keys == {"STAGE_DELAY:11", "MILESTONE_DELAY:21"}
    stage_alert = next(item for item in alerts if item.key == "STAGE_DELAY:11")
    assert stage_alert.level == "HIGH"
    milestore_alert = next(item for item in alerts if item.key == "MILESTONE_DELAY:21")
    # 1 月 8 日到期，1 月 10 日只逾期 2 天 → 中风险
    assert milestore_alert.level == "MEDIUM"


def test_task_delay_alert_skip_done() -> None:
    """任务超期提示；已完成任务跳过。"""
    tasks = [
        PrjTask(id=31, task_name="联调", status="IN_PROGRESS", plan_end="2026-01-05", progress=50),
        PrjTask(id=32, task_name="上线", status="DONE", plan_end="2026-01-01", progress=100),
    ]
    alerts = build_alerts(
        project=_project(status="COMPLETED", plan_end=None),
        stages=[],
        milestones=[],
        tasks=tasks,
        today=TODAY,
    )
    assert [item.key for item in alerts] == ["TASK_DELAY:31"]


def test_log_problem_alert_uses_issue_type() -> None:
    """日志问题按「问题」类型提示，命中关键词判高风险。"""
    alerts = build_alerts(
        project=_project(status="COMPLETED", plan_end=None),
        stages=[],
        milestones=[],
        tasks=[],
        log_problems=[
            {
                "id": 99,
                "worklogNo": "WL20260109001",
                "logDate": date(2026, 1, 9),
                "problem": "联调环境频繁故障，接口无法访问",
                "userId": 5,
            }
        ],
        today=TODAY,
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.key == "WORKLOG_PROBLEM:99"
    assert alert.risk_type == "ISSUE"
    assert alert.level == "HIGH"
    assert alert.owner_id == 5
    assert "故障" in alert.title


def test_alerts_sorted_by_level() -> None:
    """高风险排在前面。"""
    stages = [
        PrjStage(id=41, stage_name="设计", status="IN_PROGRESS", plan_end="2026-01-09"),
    ]
    alerts = build_alerts(
        project=_project(),
        stages=stages,
        milestones=[],
        tasks=[],
        today=TODAY,
    )
    assert [item.level for item in alerts] == ["HIGH", "MEDIUM"]


def test_log_risk_level_and_summary() -> None:
    """等级关键词与标题摘要。"""
    assert log_risk_level("接口延期两天") == "HIGH"
    assert log_risk_level("按计划推进") == "MEDIUM"
    assert problem_summary("第一行\n第二行") == "第一行 第二行"
    assert len(problem_summary("问题" * 40)) == 41
