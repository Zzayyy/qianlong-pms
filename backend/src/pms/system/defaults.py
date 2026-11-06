"""系统参数默认值（设计稿 04 §5）。

任何业务规则阈值必须在此登记默认值；运行时以 `t_sys_config` 为准，
后台「系统参数」修改后即时生效（缓存 5 分钟或主动失效）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

type ConfigValue = str

DEFAULT_CONFIGS: Final[Mapping[str, ConfigValue]] = {
    # ---- 定时任务（多实例去重）----
    "job.enabled": "true",
    "job.lock.ttlSeconds": "300",
    # ---- 审计留痕归档 ----
    "audit.keepMonths": "12",
    # ---- 工作日志 ----
    "worklog.daily.deadlineHour": "24",
    "worklog.backfill.maxDays": "5",
    "worklog.late.maxDays": "3",
    "worklog.hours.maxPerDay": "24",
    "worklog.hours.warnPerDay": "8",
    "worklog.hours.step": "0.5",
    "worklog.project.visible": "true",
    "worklog.dept.visible": "false",
    "worklog.confirm.required": "true",
    "worklog.remind.enabled": "true",
    # ---- 项目可见性（需求 3）----
    "project.dept.visible": "true",
    "project.public.visible": "true",
    "project.code.prefix": "PRJ",
    # ---- 项目节点（阶段/里程碑）----
    "project.stage.docRequired": "true",
    # ---- 变更分级（06 §4.2）----
    "change.level.schedulePct": "10",
    "change.level.costPct": "10",
    "change.level.scheduleDays": "3",
    "change.level.costPct5": "5",
    "change.level.scheduleDaysL3": "10",
    "change.sla.daysL1": "2",
    "change.sla.daysL2": "3",
    "change.sla.daysL3": "5",
    "change.emergency.days": "7",
    # ---- 立项审批阈值 ----
    "approval.project.amountL2": "500000",
    "approval.project.amountL3": "2000000",
    # ---- 健康度（08 §2.4）----
    "health.spi.red": "0.8",
    "health.spi.yellow": "0.9",
    "health.cpi.yellow": "0.9",
    "health.delay.redDays": "15",
    "health.delay.yellowDays": "1",
    "health.risk.high.open": "true",
    "health.logFillRate.red": "60",
    "health.logFillRate.yellow": "80",
    "health.openIssue.yellow": "5",
    # ---- 组织 ----
    "org.manager.depth": "1",
    # ---- 客户与商机 ----
    "crm.convert.autoCooperating": "true",
    "crm.opp.winStage": "WON",
    # ---- 通知与导出 ----
    "notify.mail.enabled": "true",
    "notify.mail.smtpHost": "",
    "notify.mail.smtpPort": "465",
    "notify.mail.smtpUser": "",
    "notify.mail.smtpFrom": "",
    "export.watermark": "true",
}

#: 参数中文含义（后台「规则参数」页「说明」列直接展示，必须与实际取值语义一致）。
CONFIG_REMARKS: Final[Mapping[str, str]] = {
    # 定时任务
    "job.enabled": "定时任务总开关；true=启用，多实例通过数据库锁去重执行",
    "job.lock.ttlSeconds": "定时任务锁租期（秒），超时未释放可由其他实例接管",
    # 审计留痕
    "audit.keepMonths": "操作日志/登录日志保留月数，超期数据按月归档到历史表",
    # 工作日志
    "worklog.daily.deadlineHour": "当日提交截止小时；该时刻前提交算「及时」，24=当日 24:00",
    "worklog.backfill.maxDays": "允许补填最近多少天（日志日期选择范围）",
    "worklog.late.maxDays": "超过多少天提交视为逾期，需项目经理补填审批后才计入工时",
    "worklog.hours.maxPerDay": "单人单日工时合计上限（小时），超过拒绝保存与提交",
    "worklog.hours.warnPerDay": "单人单日工时预警线（小时），超过仅提示不禁止",
    "worklog.hours.step": "工时填报的最小粒度（小时），如 0.5 表示半小时",
    "worklog.project.visible": "同项目组成员是否可互相查看工作日志；true=可见",
    "worklog.dept.visible": "同部门但不同项目的成员是否可互看日志；false=默认不可见",
    "worklog.confirm.required": "日志提交后是否需要项目经理确认；false=提交即生效",
    "worklog.remind.enabled": "每日 09:00 未填日志提醒开关；仅提醒，不阻断其他流程",
    # 项目
    "project.dept.visible": "是否允许查看本部门其他成员参与的项目进展；false=仅参与项目可见",
    "project.public.visible": "公开项目是否全员可见；false=仅项目成员与授权角色可见",
    "project.code.prefix": "项目编号前缀，生成规则：前缀-年份-流水号（如 PRJ-2026-001）",
    "project.stage.docRequired": "阶段标记完成前是否必须上传交付文档；false=仅提示不拦截",
    # 变更分级与审批时限
    "change.level.schedulePct": "工期影响超过该百分比（%）时升为 L3 重大变更",
    "change.level.costPct": "成本影响超过该百分比（%）时升为 L3 重大变更",
    "change.level.scheduleDays": "工期影响超过该天数时升为 L2 重要变更",
    "change.level.costPct5": "成本影响超过该百分比（%）时升为 L2 重要变更",
    "change.level.scheduleDaysL3": "工期影响超过该天数时直接升为 L3 重大变更",
    "change.sla.daysL1": "L1 一般变更审批时限（工作日），超时提醒催办",
    "change.sla.daysL2": "L2 重要变更审批时限（工作日），超时提醒并升级",
    "change.sla.daysL3": "L3 重大变更审批时限（工作日），超时提醒并纳入日报",
    "change.emergency.days": "紧急变更补办审批的期限（自然日），逾期上报 PMO",
    # 立项审批
    "approval.project.amountL2": "立项金额达到该值（元）需部门负责人审批（L2）",
    "approval.project.amountL3": "立项金额达到该值（元）需公司领导审批（L3）",
    # 健康度
    "health.spi.red": "进度绩效指数 SPI 低于该值时健康度标红",
    "health.spi.yellow": "进度绩效指数 SPI 低于该值时健康度标黄",
    "health.cpi.yellow": "成本绩效指数 CPI 低于该值时健康度标黄",
    "health.delay.redDays": "进度落后超过该天数时健康度标红",
    "health.delay.yellowDays": "进度落后超过该天数时健康度标黄",
    "health.risk.high.open": "存在未关闭的高等级风险时是否直接标红；true=标红",
    "health.logFillRate.red": "日志填写率低于该百分比（%）时标红",
    "health.logFillRate.yellow": "日志填写率低于该百分比（%）时标黄",
    "health.openIssue.yellow": "未关闭问题数超过该值时健康度标黄",
    # 组织
    "org.manager.depth": "直属上级可查看下级的层数；1=仅直接下级",
    # 客户与商机
    "crm.convert.autoCooperating": "商机转项目后是否自动将客户标记为「合作中」",
    "crm.opp.winStage": "视为赢单的商机阶段编码，转项目前必须处于该阶段",
    # 通知
    "notify.mail.enabled": "邮件通知开关；false=只发站内信",
    "notify.mail.smtpHost": "SMTP 服务器地址；为空则跳过邮件发送",
    "notify.mail.smtpPort": "SMTP 端口，SSL 常用 465，STARTTLS 常用 587",
    "notify.mail.smtpUser": "SMTP 登录账号（通常与发件人邮箱一致）",
    "notify.mail.smtpFrom": "发件人邮箱，可写成「项目管理系统 <no-reply@example.com>」",
    # 导出
    "export.watermark": "导出 Excel/PDF 时是否添加水印（含导出人与时间）",
}


#: 迁移脚本写入的占位说明，视为「未填写」，展示/回填时以登记的中文含义为准。
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^v\d+\.\d+\.\d+ 新增参数$")


def remark_of(key: str) -> str:
    """返回参数的中文说明；未登记时返回空串。"""
    return CONFIG_REMARKS.get(key, "")


def effective_remark(key: str, stored: str = "") -> str:
    """返回最终展示的说明：库值为空或占位时回落到登记的中文含义。"""
    text = (stored or "").strip()
    if not text or _PLACEHOLDER_RE.match(text):
        return remark_of(key)
    return text


CONFIG_GROUPS: Final[Mapping[str, str]] = {
    "job.": "定时任务",
    "audit.": "审计留痕",
    "worklog.": "工作日志",
    "project.": "项目",
    "change.": "变更管理",
    "approval.": "审批",
    "health.": "健康度",
    "org.": "组织",
    "crm.": "客户与商机",
    "notify.": "通知",
    "export.": "导出",
}
