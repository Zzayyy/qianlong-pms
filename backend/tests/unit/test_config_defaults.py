"""系统参数默认值测试：**业务规则必须可后台调整**（用户反馈第 2 点）。"""

from __future__ import annotations

import re

from pms.system.defaults import CONFIG_REMARKS, DEFAULT_CONFIGS, effective_remark, remark_of

REQUIRED_KEYS: tuple[str, ...] = (
    "worklog.backfill.maxDays",
    "worklog.late.maxDays",
    "worklog.hours.warnPerDay",
    "worklog.hours.step",
    "worklog.project.visible",
    "worklog.dept.visible",
    "project.dept.visible",
    "change.level.schedulePct",
    "change.level.costPct",
    "change.level.scheduleDays",
    "health.spi.red",
    "health.spi.yellow",
    "health.delay.redDays",
    "health.logFillRate.red",
    "org.manager.depth",
    "crm.opp.winStage",
)


def test_required_keys_present() -> None:
    """关键阈值均在默认表中登记。"""
    missing = [key for key in REQUIRED_KEYS if key not in DEFAULT_CONFIGS]
    assert not missing, f"缺少默认参数：{missing}"


def test_default_values_parseable() -> None:
    """数值型默认值可被解析。"""
    assert float(DEFAULT_CONFIGS["change.level.schedulePct"]) == 10.0
    assert float(DEFAULT_CONFIGS["health.spi.red"]) == 0.8
    assert int(DEFAULT_CONFIGS["worklog.late.maxDays"]) == 3
    assert int(DEFAULT_CONFIGS["worklog.backfill.maxDays"]) == 5
    assert float(DEFAULT_CONFIGS["worklog.hours.warnPerDay"]) == 8.0
    assert DEFAULT_CONFIGS["worklog.project.visible"] == "true"


def test_every_config_has_chinese_remark() -> None:
    """每个参数都登记了中文含义，且说明中确实包含中文。"""
    missing = [key for key in DEFAULT_CONFIGS if not remark_of(key)]
    assert not missing, f"缺少中文说明：{missing}"
    extra = [key for key in CONFIG_REMARKS if key not in DEFAULT_CONFIGS]
    assert not extra, f"说明表存在未登记的默认参数：{extra}"
    blank = [key for key, text in CONFIG_REMARKS.items() if not re.search(r"[\u4e00-\u9fa5]", text)]
    assert not blank, f"说明缺少中文：{blank}"


def test_remark_of_returns_meaning() -> None:
    """说明可读且包含关键业务含义。"""
    assert "工时" in remark_of("worklog.hours.warnPerDay")
    assert "会签" in remark_of("change.sla.daysL1") or "审批" in remark_of("change.sla.daysL1")
    assert remark_of("not.exist.key") == ""


def test_placeholder_remark_falls_back_to_meaning() -> None:
    """迁移占位说明（vX.Y.Z 新增参数）不再展示，改用登记的中文含义。"""
    assert "阶段" in effective_remark("project.stage.docRequired", "v1.1.16 新增参数")
    assert "提醒" in effective_remark("worklog.remind.enabled", "")
    assert effective_remark("worklog.remind.enabled", "自定义说明") == "自定义说明"
    assert effective_remark("unknown.key", "v1.0.0 新增参数") == ""
