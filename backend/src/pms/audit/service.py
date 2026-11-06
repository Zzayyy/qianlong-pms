"""审计留痕（设计稿 03 §7 / 11 §4）。

要点：
1. 审计写入使用**独立会话**，业务事务回滚不影响留痕，业务异常也不丢失审计；
2. 审计失败**绝不冒泡**（只记日志），避免留痕逻辑把正常业务拖垮；
3. 入参统一脱敏（口令 / 令牌不入审计库）；
4. 覆盖：登录（成功/失败/锁定/登出）、写操作全量、读操作异常与权限拒绝。
"""

from __future__ import annotations

import json
from typing import Final, Mapping

from pms.common.logging import get_logger
from pms.common.trace import get_trace_id
from pms.core.database import get_session_factory
from pms.org.models import SysOperateLog
from pms.system.models import SysLoginLog

logger = get_logger(__name__)

_MAX_PARAM_LEN: Final[int] = 2000
_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "oldPassword", "newPassword", "confirmPassword", "token", "secret", "secretKey"}
)
_MASK: Final[str] = "******"

# 结果分类
RESULT_SUCCESS: Final[str] = "SUCCESS"
RESULT_DENIED: Final[str] = "DENIED"
RESULT_FAIL: Final[str] = "FAIL"
RESULT_ERROR: Final[str] = "ERROR"


def sanitize_params(raw: str) -> str:
    """对入参做敏感字段脱敏与长度裁剪。"""
    if not raw:
        return ""
    text = raw[:_MAX_PARAM_LEN]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text
    return json.dumps(_mask_tree(payload), ensure_ascii=False)[:_MAX_PARAM_LEN]


def _mask_tree(node: object) -> object:
    """递归脱敏（dict / list / 标量）。"""
    if isinstance(node, dict):
        return {
            key: (_MASK if str(key).lower() in _SENSITIVE_KEYS else _mask_tree(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_mask_tree(item) for item in node]
    return node


_MODULE_ALIASES: Final[Mapping[str, str]] = {
    "projects": "project",
    "changes": "change",
    "worklogs": "worklog",
    "reports": "report",
    "customers": "crm",
    "opportunities": "crm",
    "users": "org",
    "depts": "org",
    "roles": "org",
    "permissions": "org",
    "configs": "system",
    "dicts": "system",
    "files": "system",
    "notices": "system",
}


def module_of(path: str) -> str:
    """由 URL 推断业务模块（`/api/v1/projects/1` → `project`）。"""
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 3:
        return "system"
    return _MODULE_ALIASES.get(segments[2], segments[2])


def result_of(status_code: int) -> str:
    """由 HTTP 状态码判定留痕结果。"""
    if 200 <= status_code < 300:
        return RESULT_SUCCESS
    if status_code in {401, 403}:
        return RESULT_DENIED
    if 400 <= status_code < 500:
        return RESULT_FAIL
    return RESULT_ERROR


async def record_login(
    *,
    username: str,
    ip: str = "",
    user_agent: str = "",
    status: str = RESULT_SUCCESS,
    message: str = "",
) -> None:
    """写登录日志（成功/失败/锁定/登出），失败不影响业务。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                SysLoginLog(
                    username=username[:64],
                    ip=ip[:64],
                    user_agent=user_agent[:500],
                    status=status,
                    message=message[:250],
                    trace_id=get_trace_id(),
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001  审计不得影响业务
        logger.exception("写登录日志失败：%s", username)


async def record_operate(
    *,
    user_id: int = 0,
    module: str = "",
    operation: str = "",
    method: str = "",
    url: str = "",
    params: str = "",
    result: str = RESULT_SUCCESS,
    ip: str = "",
    cost_ms: int = 0,
) -> None:
    """写操作审计（独立事务），失败不影响业务。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                SysOperateLog(
                    module=module[:64],
                    operation=operation[:128],
                    method=method[:16],
                    url=url[:512],
                    params=sanitize_params(params),
                    result=result,
                    ip=ip[:64],
                    user_id=user_id,
                    cost_ms=cost_ms,
                    trace_id=get_trace_id(),
                    create_by=user_id or None,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001  审计不得影响业务
        logger.exception("写操作审计失败：%s %s", method, url)
