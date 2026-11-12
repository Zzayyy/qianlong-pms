"""操作审计中间件（设计稿 03 §7 / 11 §4）。

规则：
- 只审计 `/api/v1/**`（健康检查、静态资源不审计）
- **写操作（POST/PUT/PATCH/DELETE）全量留痕**
- 读操作仅在异常（4xx/5xx，含 401/403 权限拒绝）时留痕
- 入参脱敏（口令、令牌不入审计库），异常照常抛出
"""

from __future__ import annotations

import time
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from pms.audit.service import module_of, record_operate, result_of
from pms.common.logging import get_logger
from pms.common.net import client_ip
from pms.core.security import decode_access_token

logger = get_logger(__name__)

_API_PREFIX: Final[str] = "/api/v1"
_WRITE_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_BODY: Final[int] = 4000


def _client_ip(request: Request) -> str:
    """取客户端 IP（可信代理后解析 X-Forwarded-For，规则见 `pms.common.net`）。"""
    return client_ip(request)


def _user_id(request: Request) -> int:
    """从 Authorization 头解析用户 ID（无需完整鉴权，失败返回 0）。"""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return 0
    try:
        payload = decode_access_token(header[7:])
    except Exception:  # noqa: BLE001  审计上下文中令牌可能已过期
        return 0
    try:
        return int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        return 0


class AuditMiddleware(BaseHTTPMiddleware):
    """写操作与拒绝访问的审计留痕中间件。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """执行请求并在结束后落审计。"""
        if not request.url.path.startswith(_API_PREFIX):
            return await call_next(request)

        method = request.method
        need_body = method in _WRITE_METHODS
        body_text = ""
        if need_body:
            try:
                raw = await request.body()
                body_text = raw.decode("utf-8", errors="ignore")[:_MAX_BODY]
            except Exception:  # noqa: BLE001  读体失败不阻断
                body_text = ""

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            if need_body or status_code >= 400:
                cost_ms = int((time.perf_counter() - started) * 1000)
                path = request.url.path
                try:
                    await record_operate(
                        user_id=_user_id(request),
                        module=module_of(path),
                        operation=f"{method} {path}",
                        method=method,
                        url=str(request.url),
                        params=body_text,
                        result=result_of(status_code),
                        ip=_client_ip(request),
                        cost_ms=cost_ms,
                    )
                except Exception:  # noqa: BLE001  审计失败不影响响应
                    logger.exception("审计留痕异常：%s %s", method, path)
