"""周报提示词模板服务：模板解析、变量渲染与后台维护。

设计要点：
- **分层匹配**：本部门 → 上级部门 → 全公司默认（`dept_id=0`）→ 代码内置；
  这样「一个部门一套」的差异化需求可用覆盖实现，不必给每个部门都配置；
- **变量占位符**：`{{stats}}` / `{{entries}}` 承载取数结果，其余为标量字段；
  渲染时若模板漏配数据占位符会自动追加，避免模板改坏后 AI 拿不到数据；
- **兜底不依赖数据**：库里没有任何模板时直接用代码内置提示词，功能照常可用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ForbiddenError, ParamError
from pms.core.context import AuthContext
from pms.org.models import SysDept
from pms.weekly.models import WkPrompt

#: 模板作用范围（与周报表 `scope` 一致）
SCOPE_PROJECT: Final[str] = "PROJECT"
SCOPE_PERSONAL: Final[str] = "PERSONAL"
SCOPES: Final[tuple[str, ...]] = (SCOPE_PROJECT, SCOPE_PERSONAL)
SCOPE_LABELS: Final[dict[str, str]] = {
    SCOPE_PROJECT: "项目周报",
    SCOPE_PERSONAL: "个人周总结",
}

#: 可维护全公司默认模板的角色
_GLOBAL_ROLES: Final[frozenset[str]] = frozenset({"ADMIN", "PMO"})

#: 模板字段长度上限
_SYSTEM_MAX: Final[int] = 4000
_USER_MAX: Final[int] = 20000

DEFAULT_SYSTEM_PROMPT: Final[str] = (
    "你是资深项目管理助理，擅长把零散的工作日志整理成条理清晰、可直接汇报的中文周报。"
    "只使用给定数据，禁止编造人名、数字和结论。"
)

DEFAULT_PROJECT_PROMPT: Final[str] = (
    "请基于以下项目工作日志生成 {{weekLabel}} 周的项目周报（Markdown）。\n\n"
    "结构固定为：\n"
    "## 一、本周进展\n## 二、工时投入\n## 三、问题与风险\n"
    "## 四、下周计划\n## 五、需要协调支持\n\n"
    "要求：\n"
    "1. 只使用给定数据，禁止编造人名、数字、结论；缺失信息写「暂无」；\n"
    "2. 进展按人员或任务归并，每条要点不超过 60 字，不要逐条罗列日志；\n"
    "3. 问题与风险优先列出阻塞项、风险标记与延期情况；\n"
    "4. 下周计划依据日志中「明日计划」归纳；\n"
    "5. 语气客观简洁，可直接发给项目干系人；\n"
    "6. 一条日志可能同时记录多个项目（条目里的 relatedProjects 字段）："
    "只提取与本项目「{{projectName}}」相关的内容，"
    "relatedProjects 或其他项目的进展、问题、计划一律不得写入本报告；"
    "无法区分归属时按本项目工时客观描述，禁止臆造。\n\n"
    "## 项目与统计\n```json\n{{stats}}\n```\n\n"
    "## 本周工作日志\n```json\n{{entries}}\n```\n"
)

DEFAULT_PERSONAL_PROMPT: Final[str] = (
    "请基于以下个人工作日志生成 {{weekLabel}} 周的个人周总结（Markdown）。\n\n"
    "结构固定为：\n"
    "## 一、本周工作概览\n## 二、主要产出\n## 三、问题与阻塞\n"
    "## 四、下周计划\n## 五、复盘与改进\n\n"
    "要求：\n"
    "1. 只使用给定数据，禁止编造；数据缺失写「暂无」；\n"
    "2. 按项目/事务归并要点，突出可量化产出（工时、条数、完成事项）；\n"
    "3. 「复盘与改进」给出 2-3 条基于日志的具体建议，避免空话；\n"
    "4. 全文控制在 600 字以内，语气平实。\n\n"
    "## 统计\n```json\n{{stats}}\n```\n\n"
    "## 本周工作日志\n```json\n{{entries}}\n```\n"
)

#: 代码内置模板（库里无可用模板时兜底）
BUILTIN_PROMPTS: Final[dict[str, tuple[str, str]]] = {
    SCOPE_PROJECT: ("系统内置 · 项目周报", DEFAULT_PROJECT_PROMPT),
    SCOPE_PERSONAL: ("系统内置 · 个人周总结", DEFAULT_PERSONAL_PROMPT),
}

#: 模板可用变量（前端说明用）
VARIABLES: Final[tuple[tuple[str, str], ...]] = (
    ("weekLabel", "周标签，如 2026-W48"),
    ("dateFrom", "本周周一（YYYY-MM-DD）"),
    ("dateTo", "本周周日（YYYY-MM-DD）"),
    ("totalHours", "本周总工时"),
    ("logCount", "日志条数"),
    ("memberCount", "参与人数"),
    ("lateCount", "迟填日志条数"),
    ("riskLogCount", "带风险标记的日志条数"),
    ("byProject", "按项目汇总的工时分布（JSON）"),
    ("byDay", "按天汇总的工时分布（JSON）"),
    ("members", "按人员汇总的工时分布（JSON）"),
    ("projectName", "项目名称（仅项目周报）"),
    ("projectCode", "项目编号（仅项目周报）"),
    ("projectStatus", "项目状态（仅项目周报）"),
    ("progress", "项目进度百分比（仅项目周报）"),
    ("health", "项目健康度（仅项目周报）"),
    ("planStart", "计划开始日期（仅项目周报）"),
    ("planEnd", "计划结束日期（仅项目周报）"),
    ("userName", "填报人姓名（仅个人周总结）"),
    ("deptName", "目标部门名称"),
    ("stats", "统计快照 JSON 块（未使用时自动追加）"),
    ("entries", "工作日志明细 JSON 块（未使用时自动追加）"),
)

_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")


@dataclass(slots=True)
class PromptTemplate:
    """解析后的可用模板（可能是库内记录，也可能是代码内置）。"""

    prompt_id: int
    name: str
    system_prompt: str
    user_prompt: str
    dept_id: int
    builtin: int

    @property
    def from_db(self) -> bool:
        """是否来自数据库记录。"""
        return self.prompt_id > 0


# ---------------------------------------------------------------- 解析与渲染


async def _dept_chain(session: AsyncSession, dept_id: int) -> list[int]:
    """部门 ID 链（根 → 自身），取不到路径时只返回自身。"""
    if dept_id <= 0:
        return []
    dept = await session.get(SysDept, dept_id)
    if dept is None or dept.deleted:
        return [dept_id]
    chain = [int(part) for part in (dept.path or "").split("/") if part.isdigit()]
    return chain or [dept_id]


async def resolve(
    session: AsyncSession, *, scope: str, dept_id: int = 0
) -> PromptTemplate:
    """按部门逐级向上匹配提示词模板，最终回落到代码内置。"""
    if scope not in SCOPES:
        raise ParamError("scope 只能是 PROJECT / PERSONAL")
    chain = await _dept_chain(session, dept_id)
    # 自身部门优先，其后逐级向上，最后是全公司默认
    candidates = [*reversed(chain), 0]
    if candidates:
        result = await session.execute(
            select(WkPrompt)
            .where(
                WkPrompt.deleted == 0,
                WkPrompt.scope == scope,
                WkPrompt.enabled == 1,
                WkPrompt.dept_id.in_(candidates),
            )
            .order_by(WkPrompt.id)
        )
        index: dict[int, WkPrompt] = {}
        for row in result.scalars().all():
            index.setdefault(int(row.dept_id), row)
        for candidate in candidates:
            row = index.get(candidate)
            if row is not None:
                return PromptTemplate(
                    prompt_id=int(row.id),
                    name=row.name or SCOPE_LABELS[scope],
                    system_prompt=row.system_prompt or DEFAULT_SYSTEM_PROMPT,
                    user_prompt=row.user_prompt or BUILTIN_PROMPTS[scope][1],
                    dept_id=int(row.dept_id),
                    builtin=int(row.builtin),
                )
    name, prompt = BUILTIN_PROMPTS[scope]
    return PromptTemplate(
        prompt_id=0,
        name=name,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        user_prompt=prompt,
        dept_id=0,
        builtin=1,
    )


def _text(value: object) -> str:
    """占位符取值统一转字符串。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render(template: str, snapshot: dict[str, object]) -> str:
    """渲染用户提示词：替换已知占位符，并补齐遗漏的数据块。"""
    stats = json.dumps(
        {key: value for key, value in snapshot.items() if key != "entries"},
        ensure_ascii=False,
        indent=1,
    )
    entries = json.dumps(
        snapshot.get("entries", []), ensure_ascii=False, indent=1
    )
    values: dict[str, str] = {
        key: _text(value) for key, value in snapshot.items() if key != "entries"
    }
    values.setdefault("weekStart", values.get("dateFrom", ""))
    values.setdefault("weekEnd", values.get("dateTo", ""))
    values["stats"] = stats
    values["entries"] = entries

    used = {match.group(1) for match in _PLACEHOLDER.finditer(template)}
    text = _PLACEHOLDER.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
    missing: list[str] = []
    if "stats" not in used:
        missing.append(f"## 统计数据\n```json\n{stats}\n```")
    if "entries" not in used:
        missing.append(f"## 工作日志明细\n```json\n{entries}\n```")
    if missing:
        text = f"{text.rstrip()}\n\n" + "\n\n".join(missing) + "\n"
    return text


def build_messages(
    template: PromptTemplate, snapshot: dict[str, object]
) -> list[dict[str, str]]:
    """组装送进大模型的 messages。"""
    return [
        {"role": "system", "content": template.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": render(template.user_prompt, snapshot)},
    ]


# ---------------------------------------------------------------- 权限


def can_manage_global(context: AuthContext) -> bool:
    """是否可维护全公司默认模板。"""
    return context.has_any_role(*_GLOBAL_ROLES)


def ensure_can_manage(context: AuthContext, dept_id: int) -> None:
    """维护权限：系统管理员/PMO 管全局，部门领导管可见部门。

    Raises:
        ForbiddenError: 越权维护全局模板或非本部门模板。
    """
    if can_manage_global(context):
        return
    if dept_id <= 0:
        raise ForbiddenError("只有系统管理员或 PMO 可维护全公司默认提示词")
    if not context.is_dept_head:
        raise ForbiddenError("只有部门领导可维护部门提示词")
    if not context.can_see_dept(dept_id):
        raise ForbiddenError("只能维护本部门及下级部门的提示词")


def visible_dept_ids(context: AuthContext) -> frozenset[int] | None:
    """可维护的部门范围（`None` 表示不限）。"""
    return None if can_manage_global(context) else context.visible_dept_ids


# ---------------------------------------------------------------- 维护


def _normalize(
    *, scope: str, name: str, system_prompt: str, user_prompt: str
) -> tuple[str, str, str]:
    """校验并规范化模板字段。"""
    if scope not in SCOPES:
        raise ParamError("scope 只能是 PROJECT / PERSONAL")
    title = (name or "").strip()
    if not title:
        raise ParamError("模板名称不能为空")
    system_text = (system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
    user_text = (user_prompt or "").strip()
    if not user_text:
        raise ParamError("用户提示词不能为空")
    if len(system_text) > _SYSTEM_MAX:
        raise ParamError(f"系统提示词最多 {_SYSTEM_MAX} 字")
    if len(user_text) > _USER_MAX:
        raise ParamError(f"用户提示词最多 {_USER_MAX} 字")
    return title[:100], system_text, user_text


async def _ensure_unique(
    session: AsyncSession, *, scope: str, dept_id: int, exclude_id: int = 0
) -> None:
    """同一「范围 + 部门」只允许一条模板。"""
    stmt = select(WkPrompt.id).where(
        WkPrompt.deleted == 0,
        WkPrompt.scope == scope,
        WkPrompt.dept_id == dept_id,
    )
    if exclude_id:
        stmt = stmt.where(WkPrompt.id != exclude_id)
    if (await session.execute(stmt)).scalars().first() is not None:
        target = "全公司默认" if dept_id <= 0 else "该部门"
        raise BizRuleError(f"{target}已有同范围提示词，请直接编辑或复制后修改")


async def ensure_defaults(session: AsyncSession, operator_id: int = 0) -> int:
    """补齐全公司默认模板（幂等），返回新增条数。"""
    added = 0
    for scope, (name, prompt) in BUILTIN_PROMPTS.items():
        exists = (
            await session.execute(
                select(WkPrompt.id).where(
                    WkPrompt.deleted == 0,
                    WkPrompt.scope == scope,
                    WkPrompt.dept_id == 0,
                )
            )
        ).scalars().first()
        if exists is not None:
            continue
        session.add(
            WkPrompt(
                scope=scope,
                dept_id=0,
                name=name,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                user_prompt=prompt,
                enabled=1,
                builtin=1,
                remark="系统初始化生成，可编辑或停用，停用后回落到内置提示词",
                create_by=operator_id,
            )
        )
        added += 1
    if added:
        await session.flush()
    return added


async def list_prompts(
    session: AsyncSession, context: AuthContext, *, scope: str = ""
) -> list[dict[str, object]]:
    """模板列表（含部门名与是否当前生效）。"""
    if scope and scope not in SCOPES:
        raise ParamError("scope 只能是 PROJECT / PERSONAL")
    stmt = select(WkPrompt).where(WkPrompt.deleted == 0)
    if scope:
        stmt = stmt.where(WkPrompt.scope == scope)
    result = await session.execute(stmt.order_by(WkPrompt.scope, WkPrompt.dept_id))
    rows = list(result.scalars().all())
    allowed = visible_dept_ids(context)
    dept_names = await _dept_names(session, {int(row.dept_id) for row in rows})
    # 每个 scope 的当前生效模板：按「全公司默认」与调用者本人部门各算一次
    effective: dict[str, int] = {}
    for item in SCOPES:
        template = await resolve(session, scope=item, dept_id=context.dept_id)
        effective[item] = template.prompt_id
    manage_global = can_manage_global(context)
    items: list[dict[str, object]] = []
    for row in rows:
        dept_id = int(row.dept_id)
        if allowed is not None and dept_id > 0 and dept_id not in allowed:
            continue
        items.append(
            {
                "id": int(row.id),
                "scope": row.scope,
                "scopeLabel": SCOPE_LABELS.get(row.scope, row.scope),
                "deptId": dept_id,
                "deptName": (
                    "全公司默认"
                    if dept_id <= 0
                    else dept_names.get(dept_id, f"部门{dept_id}")
                ),
                "name": row.name,
                "systemPrompt": row.system_prompt,
                "userPrompt": row.user_prompt,
                "enabled": int(row.enabled),
                "builtin": int(row.builtin),
                "remark": row.remark,
                "effective": int(row.id) == effective.get(row.scope, -1),
                # 部门领导只能改自己部门的模板，全局默认可看不可改
                "canEdit": manage_global
                or (dept_id > 0 and context.is_dept_head and context.can_see_dept(dept_id)),
                "updateBy": int(row.update_by or 0),
                "updateTime": row.update_time.strftime("%Y-%m-%d %H:%M:%S")
                if row.update_time
                else "",
            }
        )
    return items


async def _dept_names(session: AsyncSession, dept_ids: set[int]) -> dict[int, str]:
    """批量取部门名称。"""
    targets = {item for item in dept_ids if item > 0}
    if not targets:
        return {}
    result = await session.execute(
        select(SysDept.id, SysDept.dept_name).where(SysDept.id.in_(targets))
    )
    return {int(dept_id): str(name) for dept_id, name in result.all()}


async def get_prompt(session: AsyncSession, prompt_id: int) -> WkPrompt:
    """按 ID 取模板，不存在抛业务异常。"""
    row = await session.get(WkPrompt, prompt_id)
    if row is None or row.deleted:
        raise BizRuleError("提示词模板不存在")
    return row


async def create_prompt(
    session: AsyncSession,
    context: AuthContext,
    *,
    scope: str,
    dept_id: int = 0,
    name: str = "",
    system_prompt: str = "",
    user_prompt: str = "",
    enabled: int = 1,
    remark: str = "",
) -> WkPrompt:
    """新建模板（部门范围受权限约束）。"""
    ensure_can_manage(context, dept_id)
    title, system_text, user_text = _normalize(
        scope=scope, name=name, system_prompt=system_prompt, user_prompt=user_prompt
    )
    await _ensure_unique(session, scope=scope, dept_id=dept_id)
    row = WkPrompt(
        scope=scope,
        dept_id=dept_id,
        name=title,
        system_prompt=system_text,
        user_prompt=user_text,
        enabled=1 if enabled else 0,
        builtin=0,
        remark=(remark or "").strip()[:200],
        create_by=context.user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def update_prompt(
    session: AsyncSession,
    context: AuthContext,
    prompt_id: int,
    *,
    name: str,
    system_prompt: str,
    user_prompt: str,
    enabled: int = 1,
    remark: str = "",
) -> WkPrompt:
    """编辑模板内容（部门归属不可改，需要换部门请复制新建）。"""
    row = await get_prompt(session, prompt_id)
    ensure_can_manage(context, int(row.dept_id))
    title, system_text, user_text = _normalize(
        scope=row.scope, name=name, system_prompt=system_prompt, user_prompt=user_prompt
    )
    row.name = title
    row.system_prompt = system_text
    row.user_prompt = user_text
    row.enabled = 1 if enabled else 0
    row.remark = (remark or "").strip()[:200]
    row.update_by = context.user_id
    await session.flush()
    return row


async def delete_prompt(
    session: AsyncSession, context: AuthContext, prompt_id: int
) -> None:
    """删除模板；内置默认模板不可删除（可停用）。"""
    row = await get_prompt(session, prompt_id)
    ensure_can_manage(context, int(row.dept_id))
    if int(row.builtin):
        raise BizRuleError("系统内置默认模板不可删除，可改为停用")
    row.deleted = 1
    row.update_by = context.user_id
    await session.flush()


async def copy_prompt(
    session: AsyncSession,
    context: AuthContext,
    prompt_id: int,
    *,
    dept_id: int,
    name: str = "",
) -> WkPrompt:
    """以现有模板为蓝本复制一份到指定部门（常用：从全公司默认复制出部门版）。"""
    source = await get_prompt(session, prompt_id)
    ensure_can_manage(context, dept_id)
    await _ensure_unique(session, scope=source.scope, dept_id=dept_id)
    title = (name or f"{source.name}（部门版）").strip()[:100]
    row = WkPrompt(
        scope=source.scope,
        dept_id=dept_id,
        name=title,
        system_prompt=source.system_prompt,
        user_prompt=source.user_prompt,
        enabled=1,
        builtin=0,
        remark=f"复制自：{source.name}",
        create_by=context.user_id,
    )
    session.add(row)
    await session.flush()
    return row
