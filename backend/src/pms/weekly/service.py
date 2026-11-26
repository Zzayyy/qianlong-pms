"""周报服务：取数 → 组装提示词 → 调 AI → 落库 → 编辑/确认。

设计要点：
- **数据来源唯一**：只读 `t_wl_worklog`（含明细项目归属），不重复统计口径；
- **确认前可编辑**：AI 生成后状态为 `GENERATED`，项目经理（或本人）可改正文再确认；
- **AI 失败可降级**：模型不可用时仍生成纯数据模板，保证周报流程不阻塞；
- **自动任务幂等**：同一周同一项目只保留一条记录，已确认的不被自动任务覆盖。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.ai import client as ai_client
from pms.ai.client import AiError
from pms.common.exceptions import BizRuleError, ForbiddenError, NotFoundError, ParamError
from pms.common.logging import get_logger
from pms.core.config import get_settings
from pms.core.context import AuthContext
from pms.notice import service as notice_service
from pms.org.models import SysDept, SysUser
from pms.project.models import PrjMember, PrjProject
from pms.project.visibility import is_project_manager
from pms.system.config_service import ConfigService
from pms.weekly import prompt_service
from pms.weekly.models import WkWeekly
from pms.weekly.rules import (
    WeeklyScope,
    WeeklySource,
    WeeklyStatus,
    next_report_no,
    week_bounds,
    week_label,
)
from pms.worklog import service as worklog_service
from pms.worklog.models import WlItem, WlWorklog
from pms.worklog.rules import WorklogStatus, round_hours

logger = get_logger(__name__)

#: 项目周报查看权限点（仅授予公司领导 / PMO / 部门领导）
PROJECT_WEEKLY_VIEW_PERM: Final[str] = "weekly:project:view"

#: 参与自动生成的活跃项目状态
_ACTIVE_STATUSES: Final[tuple[str, ...]] = (
    "APPROVED",
    "IN_PROGRESS",
    "SUSPENDED",
    "COMPLETED",
)

#: 单条日志正文截断长度（控制提示词体积）
_CONTENT_LIMIT: Final[int] = 400


def _date_text(value: object) -> str:
    """把日期类字段统一转成 `YYYY-MM-DD`（兼容 str / date）。"""
    if not value:
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)


def _time_text(value: object) -> str:
    """把时间类字段统一转成 `YYYY-MM-DD HH:MM:SS`。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else ""


# ---------------------------------------------------------------- 取数


async def _week_logs(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    project_id: int = 0,
    user_id: int = 0,
) -> list[WlWorklog]:
    """取一段周区间内的已生效日志（草稿、已驳回都不参与周报统计）。"""
    conditions = [
        WlWorklog.deleted == 0,
        WlWorklog.log_date >= start.isoformat(),
        WlWorklog.log_date <= end.isoformat(),
        WlWorklog.status.in_(
            [
                WorklogStatus.SUBMITTED,
                WorklogStatus.PENDING_APPROVE,
                WorklogStatus.CONFIRMED,
            ]
        ),
    ]
    if user_id:
        conditions.append(WlWorklog.user_id == user_id)
    if project_id:
        subq = select(WlItem.worklog_id).where(
            WlItem.project_id == project_id, WlItem.deleted == 0
        )
        conditions.append(
            or_(WlWorklog.project_id == project_id, WlWorklog.id.in_(subq))
        )
    result = await session.execute(
        select(WlWorklog)
        .where(*conditions)
        .order_by(WlWorklog.log_date, WlWorklog.id)
    )
    return list(result.scalars().all())


async def _build_snapshot(
    session: AsyncSession,
    *,
    scope: str,
    start: date,
    end: date,
    project: PrjProject | None = None,
    owner_id: int = 0,
    max_logs: int = 150,
) -> dict[str, object]:
    """组装送进 AI / 用于展示的统计快照。"""
    rows = await _week_logs(
        session,
        start=start,
        end=end,
        project_id=project.id if project else 0,
        user_id=0 if project else owner_id,
    )
    users = await worklog_service.user_names(session, {row.user_id for row in rows})
    tasks = await worklog_service.task_names(session, {row.task_id for row in rows})
    # 一条日志可覆盖多个项目：工时按明细归属，避免项目周报整条重复计入
    item_map = await worklog_service.worklog_item_projects(
        session, [int(row.id) for row in rows]
    )
    projects = await worklog_service.project_names(
        session,
        {row.project_id for row in rows}
        | {
            int(entry["projectId"])
            for entries in item_map.values()
            for entry in entries
        },
    )

    def scoped_hours(row: WlWorklog) -> float:
        """当前视角下这条日志贡献的工时：项目周报只取该项目的明细工时。"""
        entries = item_map.get(int(row.id), [])
        if project is None:
            return float(row.total_hours)
        if not entries:
            # 老日志没有明细时回落到主表，避免统计丢数
            return (
                float(row.total_hours)
                if int(row.project_id) == project.id
                else 0.0
            )
        return sum(
            float(entry["hours"])
            for entry in entries
            if int(entry["projectId"]) == project.id
        )

    member_hours: dict[int, float] = {}
    member_counts: dict[int, int] = {}
    member_names: dict[int, str] = {}
    project_hours: dict[str, float] = {}
    project_counts: dict[str, int] = {}
    day_hours: dict[str, float] = {}
    day_counts: dict[str, int] = {}
    late_count = 0
    risk_count = 0
    for row in rows:
        hours = scoped_hours(row)
        _, real_name = users.get(row.user_id, ("", ""))
        member_names[row.user_id] = real_name or users.get(
            row.user_id, ("", "")
        )[0] or f"用户{row.user_id}"
        member_hours[row.user_id] = member_hours.get(row.user_id, 0.0) + hours
        member_counts[row.user_id] = member_counts.get(row.user_id, 0) + 1

        meta = worklog_service.log_type_meta(row.log_type)
        entries = item_map.get(int(row.id), [])
        if meta.requires_project:
            if project is not None:
                label = project.project_name
            else:
                names = [
                    projects.get(int(entry["projectId"]), "") or "未命名项目"
                    for entry in entries
                ]
                label = "、".join(dict.fromkeys(names)) or (
                    projects.get(row.project_id, "") or "未命名项目"
                )
        else:
            label = meta.label
        # 个人周总结展示多项目时按明细拆分；项目周报只统计当前项目
        if project is None and meta.requires_project and entries:
            for entry in entries:
                name = projects.get(int(entry["projectId"]), "") or "未命名项目"
                project_hours[name] = project_hours.get(name, 0.0) + float(
                    entry["hours"]
                )
                project_counts[name] = project_counts.get(name, 0) + 1
        else:
            project_hours[label] = project_hours.get(label, 0.0) + hours
            project_counts[label] = project_counts.get(label, 0) + 1

        day_text = _date_text(row.log_date)
        day_hours[day_text] = day_hours.get(day_text, 0.0) + hours
        day_counts[day_text] = day_counts.get(day_text, 0) + 1

        if row.is_late:
            late_count += 1
        if row.risk_flag or (row.problem or "").strip():
            risk_count += 1

    members = [
        {
            "userId": user_id,
            "name": member_names[user_id],
            "hours": round_hours(hours),
            "logCount": member_counts[user_id],
        }
        for user_id, hours in sorted(member_hours.items(), key=lambda kv: kv[1], reverse=True)
    ]
    by_project = [
        {"name": name, "hours": round_hours(hours), "logCount": project_counts[name]}
        for name, hours in sorted(project_hours.items(), key=lambda kv: kv[1], reverse=True)
    ]
    by_day = [
        {"date": day_text, "hours": round_hours(day_hours[day_text]), "count": day_counts[day_text]}
        for day_text in sorted(day_hours)
    ]

    ordered = rows[-max_logs:] if max_logs > 0 and len(rows) > max_logs else rows

    def entry_project(row: WlWorklog) -> str:
        """日志涉及的项目名：项目视角固定当前项目，个人视角拼接多项目。"""
        meta = worklog_service.log_type_meta(row.log_type)
        if not meta.requires_project:
            return meta.label
        if project is not None:
            return project.project_name
        names = [
            projects.get(int(entry["projectId"]), "") or "未命名项目"
            for entry in item_map.get(int(row.id), [])
        ]
        return "、".join(dict.fromkeys(names)) or (
            projects.get(row.project_id, "") or "未命名项目"
        )

    def scoped_content(row: WlWorklog) -> str:
        """项目视角只取本项目那段内容（用 `@项目名` 分段时），避免串项目。"""
        entries = item_map.get(int(row.id), [])
        if project is None or not entries:
            return (row.content or "").strip()
        # 只要日志按项目拆过内容，就只认本项目那段；未标注的项目不带正文
        if any(str(entry.get("content") or "").strip() for entry in entries):
            for entry in entries:
                if int(entry["projectId"]) == project.id:
                    return str(entry.get("content") or "").strip()
            return ""
        return (row.content or "").strip()

    def related_projects(row: WlWorklog) -> list[str]:
        """该日志涉及的其他项目（项目视角下用于提示 AI 不要串项）。"""
        if project is None:
            return []
        names = [
            projects.get(int(entry["projectId"]), "") or "未命名项目"
            for entry in item_map.get(int(row.id), [])
            if int(entry["projectId"]) != project.id
        ]
        return list(dict.fromkeys(names))

    entries = [
        {
            "date": _date_text(row.log_date),
            "user": member_names.get(row.user_id, ""),
            "project": entry_project(row),
            "task": tasks.get(row.task_id, ""),
            "hours": scoped_hours(row),
            "content": scoped_content(row)[:_CONTENT_LIMIT],
            # 日志同时涉及的其他项目：提示词据此要求 AI 不得写入本报告
            "relatedProjects": related_projects(row),
            "problem": (row.problem or "").strip()[:_CONTENT_LIMIT],
            "plan": (row.plan or "").strip()[:_CONTENT_LIMIT],
        }
        for row in ordered
    ]

    snapshot: dict[str, object] = {
        "scope": scope,
        "weekLabel": week_label(start),
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "totalHours": round_hours(sum(scoped_hours(row) for row in rows)),
        "logCount": len(rows),
        "memberCount": len(member_hours),
        "lateCount": late_count,
        "riskLogCount": risk_count,
        "members": members,
        "byProject": by_project,
        "byDay": by_day,
    }
    if project is not None:
        snapshot.update(
            {
                "projectId": project.id,
                "projectCode": project.project_code,
                "projectName": project.project_name,
                "projectStatus": project.status,
                "progress": float(project.progress or 0),
                "health": project.health,
                "planStart": _date_text(project.plan_start),
                "planEnd": _date_text(project.plan_end),
            }
        )
    else:
        owner = await session.get(SysUser, owner_id) if owner_id else None
        snapshot.update(
            {
                "userId": owner_id,
                "userName": (owner.real_name or owner.username) if owner else "",
            }
        )
    snapshot["entries"] = entries
    return snapshot


# ---------------------------------------------------------------- 提示词
# 提示词已改为「可配置模板」：统一走 `pms.weekly.prompt_service`，
# 按部门逐级匹配（部门 → 上级部门 → 全公司默认 → 代码内置）。


async def _dept_name(session: AsyncSession, dept_id: int) -> str:
    """取部门名称（模板变量 `{{deptName}}`）。"""
    if dept_id <= 0:
        return ""
    dept = await session.get(SysDept, dept_id)
    return dept.dept_name if dept is not None and not dept.deleted else ""


def _fallback_content(snapshot: dict[str, object], scope: str) -> str:
    """AI 不可用时的纯数据模板（保证流程可用，标记为待补充）。"""
    label = str(snapshot["weekLabel"])
    members = snapshot["members"] if isinstance(snapshot["members"], list) else []
    by_project = snapshot["byProject"] if isinstance(snapshot["byProject"], list) else []
    entries = snapshot["entries"] if isinstance(snapshot["entries"], list) else []
    lines: list[str] = []
    if scope == WeeklyScope.PROJECT:
        lines.append(f"# {snapshot.get('projectName', '项目')} 周报（{label}）")
        lines.append(
            f"\n> 本周共 {snapshot['logCount']} 条日志 / {snapshot['totalHours']} 小时 / "
            f"{snapshot['memberCount']} 人参与。以下为数据汇总，AI 生成暂不可用，请人工补充。"
        )
        lines.append("\n## 一、本周进展\n")
        for item in members:
            lines.append(
                f"- {item['name']}：{item['logCount']} 条日志，{item['hours']} 小时"
            )
        if not members:
            lines.append("- 暂无")
        lines.append("\n## 二、工时投入\n")
        for item in by_project:
            lines.append(f"- {item['name']}：{item['hours']} 小时（{item['logCount']} 条）")
        if not by_project:
            lines.append("- 暂无")
        lines.append("\n## 三、问题与风险\n")
        risky = [entry for entry in entries if entry["problem"]]
        for entry in risky[:10]:
            lines.append(f"- {entry['date']} {entry['user']}：{entry['problem']}")
        if not risky:
            lines.append("- 暂无")
        lines.append("\n## 四、下周计划\n")
        plans = [entry for entry in entries if entry["plan"]]
        for entry in plans[-10:]:
            lines.append(f"- {entry['date']} {entry['user']}：{entry['plan']}")
        if not plans:
            lines.append("- 暂无")
        lines.append("\n## 五、需要协调支持\n- 暂无")
    else:
        lines.append(f"# {snapshot.get('userName', '')} 周总结（{label}）")
        lines.append(
            f"\n> 本周共 {snapshot['logCount']} 条日志 / {snapshot['totalHours']} 小时。"
            "AI 生成暂不可用，以下为数据汇总，请人工补充。"
        )
        lines.append("\n## 一、本周工作概览\n")
        for item in by_project:
            lines.append(f"- {item['name']}：{item['hours']} 小时（{item['logCount']} 条）")
        if not by_project:
            lines.append("- 暂无")
        lines.append("\n## 二、主要产出\n")
        contents = [entry["content"] for entry in entries if entry["content"]]
        lines.extend([f"- {text}" for text in contents[-15:]] or ["- 暂无"])
        lines.append("\n## 三、问题与阻塞\n")
        problems = [entry["problem"] for entry in entries if entry["problem"]]
        lines.extend([f"- {text}" for text in problems[:10]] or ["- 暂无"])
        lines.append("\n## 四、下周计划\n")
        plans = [entry["plan"] for entry in entries if entry["plan"]]
        lines.extend([f"- {text}" for text in plans[-10:]] or ["- 暂无"])
        lines.append("\n## 五、复盘与改进\n- 暂无")
    return "\n".join(lines)


# ---------------------------------------------------------------- 生成


async def _find_report(
    session: AsyncSession,
    *,
    scope: str,
    project_id: int,
    user_id: int,
    start: date,
) -> WkWeekly | None:
    """按「范围 + 项目/人 + 周一」定位已有周报。"""
    result = await session.execute(
        select(WkWeekly).where(
            WkWeekly.deleted == 0,
            WkWeekly.scope == scope,
            WkWeekly.project_id == project_id,
            WkWeekly.user_id == user_id,
            WkWeekly.week_start == start.isoformat(),
        )
    )
    return result.scalars().first()


async def _next_serial(session: AsyncSession, *, scope: str, start: date) -> int:
    """同一周的编号流水。"""
    result = await session.execute(
        select(func.count(WkWeekly.id)).where(
            WkWeekly.deleted == 0,
            WkWeekly.scope == scope,
            WkWeekly.week_start == start.isoformat(),
        )
    )
    return int(result.scalar_one() or 0) + 1


async def _load_project(session: AsyncSession, project_id: int) -> PrjProject:
    """读取项目，不存在时抛 404。"""
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        raise NotFoundError("项目不存在")
    return project


async def ensure_can_generate(
    session: AsyncSession,
    context: AuthContext,
    *,
    scope: str,
    project_id: int = 0,
) -> PrjProject | None:
    """生成权限：项目周报需项目经理；个人周总结只能生成自己的。"""
    if scope == WeeklyScope.PROJECT:
        if not project_id:
            raise ParamError("项目周报需指定项目")
        project = await _load_project(session, project_id)
        if not await is_project_manager(session, context, project):
            raise ForbiddenError(
                "仅该项目的项目经理、PMO 或系统管理员可生成项目周报"
            )
        return project
    if scope != WeeklyScope.PERSONAL:
        raise ParamError("scope 只能是 PROJECT / PERSONAL")
    return None


async def preview_snapshot(
    session: AsyncSession,
    context: AuthContext,
    *,
    project_id: int,
    week_start: date | None = None,
    max_logs: int = 300,
) -> dict[str, object]:
    """生成前的依据日志预览：只读，不调 AI、不落库。

    与生成的取数口径完全一致（已生效日志 + 多项目按明细归属），
    便于项目经理点「生成」前先核对数据。
    """
    project = await _load_project(session, project_id)
    if not await can_view_project_weekly(session, context, project):
        raise ForbiddenError("无权查看该项目周报")
    start, end = week_bounds(week_start)
    snapshot = await _build_snapshot(
        session,
        scope=WeeklyScope.PROJECT,
        start=start,
        end=end,
        project=project,
        max_logs=max_logs,
    )
    return {
        "projectId": project.id,
        "projectCode": project.project_code,
        "projectName": project.project_name,
        "weekStart": start.isoformat(),
        "weekEnd": end.isoformat(),
        "weekLabel": snapshot["weekLabel"],
        "dateFrom": snapshot["dateFrom"],
        "dateTo": snapshot["dateTo"],
        "totalHours": snapshot["totalHours"],
        "logCount": snapshot["logCount"],
        "memberCount": snapshot["memberCount"],
        "riskLogCount": snapshot["riskLogCount"],
        "members": snapshot["members"],
        "byDay": snapshot["byDay"],
        "entries": snapshot["entries"],
    }


async def generate(
    session: AsyncSession,
    *,
    scope: str,
    user_id: int,
    operator_id: int = 0,
    project_id: int = 0,
    week_start: date | None = None,
    source: str = WeeklySource.MANUAL,
    notify: bool = True,
) -> WkWeekly:
    """生成（或重新生成）一条周报：取数 → 调 AI → 落库。

    `source=AUTO` 时不覆盖已确认周报，保证人工确认结果不被定时任务冲掉。
    """
    start, end = week_bounds(week_start)
    label = week_label(start)
    project: PrjProject | None = None
    if scope == WeeklyScope.PROJECT:
        if not project_id:
            raise ParamError("项目周报需指定项目")
        project = await _load_project(session, project_id)
        owner_id = project.pm_id or user_id
    else:
        owner_id = user_id
    if not owner_id:
        raise ParamError("周报缺少归属人")

    existing = await _find_report(
        session, scope=scope, project_id=project_id, user_id=owner_id, start=start
    )
    # 自动任务不覆盖人工成果：已确认或人工已生成的周报一律跳过，避免冲掉修订内容
    if (
        existing is not None
        and source == WeeklySource.AUTO
        and (existing.status == WeeklyStatus.CONFIRMED or existing.source == WeeklySource.MANUAL)
    ):
        logger.info("周报已人工生成/确认，自动任务跳过：%s %s", scope, label)
        return existing

    config = ConfigService(session)
    max_logs = await config.get_int("weekly.ai.maxLogs") or 150
    snapshot = await _build_snapshot(
        session,
        scope=scope,
        start=start,
        end=end,
        project=project,
        owner_id=owner_id,
        max_logs=max_logs,
    )

    # 提示词按「部门 → 上级部门 → 全公司默认 → 内置」匹配，部门可各自定制
    owner: SysUser | None = None
    if project is None:
        owner = await session.get(SysUser, owner_id) if owner_id else None
        target_dept_id = int(owner.dept_id or 0) if owner else 0
        title = f"{owner.real_name if owner else ''} 周总结（{label}）"
    else:
        target_dept_id = int(project.dept_id or 0)
        title = f"{project.project_name} 项目周报（{label}）"
    snapshot["deptName"] = await _dept_name(session, target_dept_id)
    template = await prompt_service.resolve(
        session, scope=scope, dept_id=target_dept_id
    )

    content = _fallback_content(snapshot, scope)
    ai_used = 0
    ai_message = ""
    model = ""
    if ai_client.is_configured():
        model = get_settings().deepseek_model or ""
        messages = prompt_service.build_messages(template, snapshot)
        try:
            content = await ai_client.chat(messages)
            ai_used = 1
        except AiError as exc:
            ai_message = str(exc)[:500]
            logger.warning("周报 AI 生成失败，已降级为数据模板：%s", ai_message)
    else:
        ai_message = "未配置 DEEPSEEK_API_KEY，已生成数据模板"

    if existing is None:
        serial = await _next_serial(session, scope=scope, start=start)
        report = WkWeekly(
            report_no=next_report_no(start, scope, serial),
            scope=scope,
            project_id=project_id,
            user_id=owner_id,
            week_start=start,
            week_end=end,
            week_label=label,
            create_by=operator_id or owner_id,
        )
        session.add(report)
    else:
        report = existing
        report.revision = int(report.revision or 1) + 1
        report.update_by = operator_id or owner_id

    report.dept_id = target_dept_id

    report.week_start = start
    report.week_end = end
    report.week_label = label
    report.title = title[:200]
    report.content = content
    report.stats_json = json.dumps(
        {
            **{key: value for key, value in snapshot.items() if key != "entries"},
            # 记录所用提示词，便于事后排查「部门模板是否生效」
            "promptId": template.prompt_id,
            "promptName": template.name,
        },
        ensure_ascii=False,
    )
    report.status = WeeklyStatus.GENERATED
    report.source = source
    report.ai_used = ai_used
    report.ai_model = model
    report.ai_message = ai_message
    report.confirm_by = 0
    report.confirm_time = None
    await session.flush()
    # `create_time` / `update_time` 依赖数据库默认值，INSERT 后不会自动回填；
    # 异步会话里惰性加载会抛 MissingGreenlet，这里显式刷新这两个字段。
    await session.refresh(report, attribute_names=["create_time", "update_time"])

    if notify and project is not None:
        target = project.pm_id or owner_id
        if target:
            await notice_service.create_notice(
                session,
                receiver_id=target,
                title="项目周报待确认",
                content=f"「{project.project_name}」{label} 周报已生成，请确认或编辑后确认。",
                notice_type="SYSTEM",
                biz_type="WEEKLY",
                biz_id=report.id,
            )
    logger.info(
        "周报生成：%s %s 状态=%s AI=%s 日志=%s 提示词=%s",
        scope,
        label,
        report.status,
        "成功" if ai_used else "降级",
        snapshot["logCount"],
        template.name,
    )
    return report


async def auto_generate_weeklies(
    session: AsyncSession, *, week_start: date | None = None
) -> dict[str, int]:
    """定时任务入口：为在建项目批量生成项目周报。"""
    start, _ = week_bounds(week_start)
    result = await session.execute(
        select(PrjProject).where(
            PrjProject.deleted == 0,
            PrjProject.status.in_(_ACTIVE_STATUSES),
            PrjProject.pm_id != 0,
        )
    )
    projects = list(result.scalars().all())
    generated = 0
    skipped = 0
    for project in projects:
        existing = await _find_report(
            session,
            scope=WeeklyScope.PROJECT,
            project_id=project.id,
            user_id=project.pm_id,
            start=start,
        )
        if existing is not None and (
            existing.status == WeeklyStatus.CONFIRMED
            or existing.source == WeeklySource.MANUAL
        ):
            skipped += 1
            continue
        await generate(
            session,
            scope=WeeklyScope.PROJECT,
            project_id=project.id,
            user_id=project.pm_id,
            operator_id=project.pm_id,
            week_start=start,
            source=WeeklySource.AUTO,
        )
        generated += 1
    logger.info("项目周报自动生成完成：生成 %s 个，跳过（已确认）%s 个", generated, skipped)
    return {"generated": generated, "skipped": skipped}


# ---------------------------------------------------------------- 查询与编辑


async def _project_names(
    session: AsyncSession, reports: list[WkWeekly]
) -> dict[int, str]:
    """周报涉及的项目名。"""
    return await worklog_service.project_names(
        session, {report.project_id for report in reports if report.project_id}
    )


async def _user_names(
    session: AsyncSession, reports: list[WkWeekly]
) -> dict[int, str]:
    """周报归属人姓名。"""
    ids = {report.user_id for report in reports if report.user_id}
    ids |= {report.confirm_by for report in reports if report.confirm_by}
    if not ids:
        return {}
    result = await session.execute(
        select(SysUser.id, SysUser.real_name, SysUser.username).where(SysUser.id.in_(ids))
    )
    return {
        int(user_id): (real_name or username)
        for user_id, real_name, username in result.all()
    }


def _out(
    report: WkWeekly,
    *,
    project_name: str = "",
    user_name: str = "",
    confirm_name: str = "",
    with_content: bool = False,
) -> dict[str, object]:
    """周报出参。"""
    payload: dict[str, object] = {
        "id": report.id,
        "reportNo": report.report_no,
        "scope": report.scope,
        "projectId": report.project_id,
        "projectName": project_name,
        "userId": report.user_id,
        "userName": user_name,
        "weekStart": _date_text(report.week_start),
        "weekEnd": _date_text(report.week_end),
        "weekLabel": report.week_label,
        "title": report.title,
        "status": report.status,
        "source": report.source,
        "revision": report.revision,
        "aiUsed": report.ai_used,
        "aiModel": report.ai_model,
        "aiMessage": report.ai_message,
        "confirmBy": report.confirm_by,
        "confirmName": confirm_name,
        "confirmTime": _time_text(report.confirm_time),
        "createTime": _time_text(report.create_time),
    }
    if with_content:
        payload["content"] = report.content
        try:
            payload["stats"] = json.loads(report.stats_json or "{}")
        except ValueError:
            payload["stats"] = {}
    return payload


async def list_reports(
    session: AsyncSession,
    context: AuthContext,
    *,
    scope: str = WeeklyScope.PROJECT,
    week_start: str = "",
    project_id: int = 0,
    status: str = "",
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[dict[str, object]], int]:
    """周报列表：项目周报按「项目经理 + 领导层」口径过滤，个人周总结只返回本人。"""
    conditions = [WkWeekly.deleted == 0, WkWeekly.scope == scope]
    if scope == WeeklyScope.PERSONAL:
        conditions.append(WkWeekly.user_id == context.user_id)
    if project_id:
        conditions.append(WkWeekly.project_id == project_id)
    if week_start:
        conditions.append(WkWeekly.week_start == week_start)
    if status:
        conditions.append(WkWeekly.status == status)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        conditions.append(or_(WkWeekly.title.like(like), WkWeekly.content.like(like)))
    result = await session.execute(
        select(WkWeekly)
        .where(*conditions)
        .order_by(WkWeekly.week_start.desc(), WkWeekly.id.desc())
    )
    candidates = list(result.scalars().all())

    visible: list[WkWeekly] = []
    project_cache: dict[int, bool] = {}
    for report in candidates:
        if scope == WeeklyScope.PROJECT:
            if report.project_id not in project_cache:
                project = await session.get(PrjProject, report.project_id)
                project_cache[report.project_id] = bool(
                    project and not project.deleted
                    and await can_view_project_weekly(session, context, project)
                )
            if not project_cache[report.project_id]:
                continue
        visible.append(report)

    total = len(visible)
    page = visible[offset : offset + limit] if limit > 0 else visible
    names = await _project_names(session, page)
    users = await _user_names(session, page)
    return (
        [
            _out(
                report,
                project_name=names.get(report.project_id, ""),
                user_name=users.get(report.user_id, ""),
                confirm_name=users.get(report.confirm_by, ""),
            )
            for report in page
        ],
        total,
    )


async def list_options(session: AsyncSession, context: AuthContext) -> dict[str, object]:
    """页面初始化数据：默认周、可生成项目、自动任务开关。"""
    start, end = week_bounds()
    config = ConfigService(session)
    if context.is_privileged or context.has_any_role("ADMIN"):
        result = await session.execute(
            select(PrjProject)
            .where(PrjProject.deleted == 0, PrjProject.status.in_(_ACTIVE_STATUSES))
            .order_by(PrjProject.id.desc())
        )
    elif context.has_permission(PROJECT_WEEKLY_VIEW_PERM):
        # 部门领导等领导层：只列自己数据范围内的项目，避免下拉里出现无权查看的项目
        scoped = select(PrjProject).where(
            PrjProject.deleted == 0, PrjProject.status.in_(_ACTIVE_STATUSES)
        )
        if not context.is_all_scope:
            scoped = scoped.where(
                PrjProject.dept_id.in_(sorted(context.visible_dept_ids or {context.dept_id}))
            )
        result = await session.execute(scoped.order_by(PrjProject.id.desc()))
    else:
        pm_member_projects = select(PrjMember.project_id).where(
            PrjMember.user_id == context.user_id,
            PrjMember.role_in_project == "PM",
            PrjMember.deleted == 0,
        )
        result = await session.execute(
            select(PrjProject)
            .where(
                PrjProject.deleted == 0,
                PrjProject.status.in_(_ACTIVE_STATUSES),
                or_(
                    PrjProject.pm_id == context.user_id,
                    PrjProject.id.in_(pm_member_projects),
                ),
            )
            .order_by(PrjProject.id.desc())
        )
    projects = list(result.scalars().all())
    # 每个项目单独标记能否生成：系统角色「项目经理」不等于「该项目的项目经理」
    if context.is_privileged or context.has_any_role("ADMIN"):
        generatable = {int(project.id) for project in projects}
    else:
        pm_rows = await session.execute(
            select(PrjMember.project_id).where(
                PrjMember.user_id == context.user_id,
                PrjMember.role_in_project == "PM",
                PrjMember.deleted == 0,
            )
        )
        pm_project_ids = {int(row[0]) for row in pm_rows.all()}
        generatable = {
            int(project.id)
            for project in projects
            if int(project.pm_id or 0) == context.user_id
            or int(project.id) in pm_project_ids
        }
    return {
        "weekStart": start.isoformat(),
        "weekEnd": end.isoformat(),
        "weekLabel": week_label(start),
        "prevWeekStart": (start - timedelta(days=7)).isoformat(),
        "today": date.today().isoformat(),
        "projects": [
            {
                "id": project.id,
                "projectCode": project.project_code,
                "projectName": project.project_name,
                "status": project.status,
                # 前端据此置灰「生成周报」，避免点了才报 403
                "canGenerate": int(project.id) in generatable,
            }
            for project in projects
        ],
        "autoEnabled": await config.get_bool("weekly.auto.enabled"),
        "aiConfigured": ai_client.is_configured(),
    }


async def get_report(
    session: AsyncSession, context: AuthContext, report_id: int
) -> dict[str, object]:
    """周报详情（含正文与统计快照）。"""
    report = await _get(session, report_id)
    if not await _can_view(session, context, report):
        raise ForbiddenError("无该周报访问权限")
    names = await _project_names(session, [report])
    users = await _user_names(session, [report])
    return _out(
        report,
        project_name=names.get(report.project_id, ""),
        user_name=users.get(report.user_id, ""),
        confirm_name=users.get(report.confirm_by, ""),
        with_content=True,
    )


async def update_content(
    session: AsyncSession,
    context: AuthContext,
    report_id: int,
    *,
    title: str = "",
    content: str = "",
) -> dict[str, object]:
    """编辑正文：确认前允许项目经理 / 本人修改。"""
    report = await _get(session, report_id)
    if not await _can_manage(session, context, report):
        raise ForbiddenError("无该周报编辑权限")
    if report.status == WeeklyStatus.CONFIRMED:
        raise BizRuleError("周报已确认，不能再编辑；如需修改请重新生成")
    text = (content or "").strip()
    if not text:
        raise ParamError("周报正文不能为空")
    report.content = text
    if title.strip():
        report.title = title.strip()[:200]
    report.update_by = context.user_id
    await session.flush()
    return await get_report(session, context, report_id)


async def confirm_report(
    session: AsyncSession, context: AuthContext, report_id: int
) -> dict[str, object]:
    """确认周报：确认后归档，不再随日志变化。"""
    report = await _get(session, report_id)
    if not await _can_manage(session, context, report):
        raise ForbiddenError("无该周报确认权限")
    if report.status == WeeklyStatus.CONFIRMED:
        raise BizRuleError("周报已确认，请勿重复操作")
    if not (report.content or "").strip():
        raise BizRuleError("周报正文为空，无法确认")
    report.status = WeeklyStatus.CONFIRMED
    report.confirm_by = context.user_id
    report.confirm_time = datetime.now()
    report.update_by = context.user_id
    await session.flush()
    return await get_report(session, context, report_id)


async def _get(session: AsyncSession, report_id: int) -> WkWeekly:
    """按 ID 取周报，不存在时抛 404。"""
    report = await session.get(WkWeekly, report_id)
    if report is None or report.deleted:
        raise NotFoundError("周报不存在")
    return report


async def can_view_project_weekly(
    session: AsyncSession, context: AuthContext, project: PrjProject
) -> bool:
    """项目周报可见性：项目经理 + 领导层。

    口径说明：
    - 项目经理（含组内 PM、PMO、公司领导、系统管理员）必须能看，否则自动生成的
      周报没人核对确认；
    - 其他角色需具备 `weekly:project:view`，且项目归属部门在其数据范围内
      （部门领导只看本部门及下级，避免跨部门窥探）；
    - 项目组成员、普通员工不再默认可见。
    """
    if await is_project_manager(session, context, project):
        return True
    if not context.has_permission(PROJECT_WEEKLY_VIEW_PERM):
        return False
    return context.can_see_dept(project.dept_id)


async def _can_manage(
    session: AsyncSession, context: AuthContext, report: WkWeekly
) -> bool:
    """编辑 / 确认权限：个人周总结限本人，项目周报限项目经理。"""
    if report.scope == WeeklyScope.PERSONAL:
        return report.user_id == context.user_id
    project = await session.get(PrjProject, report.project_id)
    if project is None or project.deleted:
        return False
    return await is_project_manager(session, context, project)


async def _can_view(
    session: AsyncSession, context: AuthContext, report: WkWeekly
) -> bool:
    """查看权限：个人总结限本人，项目周报限项目经理与领导层。"""
    if report.scope == WeeklyScope.PERSONAL:
        return report.user_id == context.user_id
    project = await session.get(PrjProject, report.project_id)
    if project is None or project.deleted:
        return False
    return await can_view_project_weekly(session, context, project)
