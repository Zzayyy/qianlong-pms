"""FastAPI 应用装配（迭代 I0 + I1）。

启动方式：`py -3.12 -m pms.main`（等价于原 uvicorn 命令，配置取自 APP_HOST / APP_PORT）。
"""

from __future__ import annotations

import argparse
import mimetypes
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pms import __version__
from pms.audit import api as audit_api
from pms.audit.middleware import AuditMiddleware
from pms.change import api as change_api
from pms.common.codes import ErrorCode
from pms.common.exceptions import BizError
from pms.common.logging import get_logger, setup_logging
from pms.common.response import ApiResponse, SafeJSONResponse, now_text, ok
from pms.common.trace import get_trace_id, new_trace_id, set_trace_id
from pms.core.config import get_settings
from pms.core.database import dispose_engine
from pms.core.redis import close_redis
from pms.crm import api as crm_api
from pms.file import api as file_api
from pms.jobs import shutdown_scheduler, start_scheduler
from pms.notice import api as notice_api
from pms.notice import mail_api
from pms.org import api as org_api
from pms.project import api as project_api
from pms.report import api as report_api
from pms.system import api as system_api
from pms.worklog import api as worklog_api

logger = get_logger(__name__)

_TRACE_HEADER: Final[str] = "X-Trace-Id"
_WEB_DIR_ENV: Final[str] = "PMS_WEB_DIR"
_BACKEND_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PROJECT_ROOT: Final[Path] = _BACKEND_ROOT.parent
_MIME_TYPES: Final[dict[str, str]] = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".html": "text/html",
}


def ensure_mime_types() -> None:
    """修正静态资源 MIME 映射，避免浏览器拒绝加载 `type="module"` 脚本。

    实现说明：部分 Windows 机器在注册表把 `.js` 登记为 `text/plain`，Python `mimetypes`
    会沿用该结果。浏览器按 HTML 规范对模块脚本做**严格 MIME 校验**，收到 `text/plain`
    （或 `application/octet-stream`）时直接拒绝执行，表现为前端白屏并报
    `Failed to load module script`。这里显式登记前端产物涉及的扩展名，覆盖系统结果；
    Starlette 的 `FileResponse` / `StaticFiles` 都走 `mimetypes`，故进程启动时调用一次即可。
    """
    for ext, mime in _MIME_TYPES.items():
        mimetypes.add_type(mime, ext)


ensure_mime_types()


def web_dist_dir() -> Path:
    """定位前端构建产物目录。

    实现说明：产物（`frontend/dist`，由 Vite 构建）随仓库发布，运行期只需 Python 托管，
    不依赖 Node.js。按以下顺序探测首个含 `index.html` 的目录：
    环境变量 `PMS_WEB_DIR` → 项目根 `frontend/dist` → 当前工作目录 `frontend/dist`。

    Returns:
        产物目录路径；均未命中时返回项目根下的默认路径。
    """
    default_dir = _PROJECT_ROOT / "frontend" / "dist"
    candidates: list[Path] = []
    env_dir = os.getenv(_WEB_DIR_ENV)
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(default_dir)
    candidates.append(_BACKEND_ROOT / "frontend" / "dist")
    candidates.append(Path.cwd() / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return default_dir


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动初始化与关机释放。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("启动 %s 环境=%s 版本=%s", settings.app_name, settings.app_env, __version__)
    # 测试环境不启动定时任务，避免用例执行期间触发写库
    if settings.app_env not in {"test", "pytest"}:
        start_scheduler()
    yield
    shutdown_scheduler()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    """创建应用实例。"""
    settings = get_settings()
    app = FastAPI(
        title="PMS 项目全周期管理与变更系统",
        version=__version__,
        description="周期管理 / 变更管理 / 工作日志 / 统计看板 / 四维权限",
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
    )
    # 审计留痕中间件（写操作全量 + 读操作异常/拒绝），注册在 CORS 之后、业务之前
    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(org_api.router)
    app.include_router(system_api.router)
    app.include_router(audit_api.router)
    app.include_router(notice_api.router)
    app.include_router(mail_api.router)
    app.include_router(crm_api.router)
    app.include_router(project_api.router)
    app.include_router(change_api.router)
    app.include_router(worklog_api.router)
    app.include_router(report_api.router)
    app.include_router(file_api.router)

    # 前端静态资源：产物随仓库发布，由后端直接托管（单进程即可，无需 Nginx / Node）
    web_dist: Path = web_dist_dir()
    if (web_dist / "index.html").is_file():
        if (web_dist / "assets").is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(web_dist / "assets"), check_dir=False),
                name="web-assets",
            )
        index_file = web_dist / "index.html"

        def render_index() -> FileResponse:
            """返回前端首页；禁用缓存，保证发版后刷新即生效。"""
            return FileResponse(str(index_file), headers={"Cache-Control": "no-cache"})

        @app.get("/", summary="前端入口", tags=["默认"], include_in_schema=False)
        async def index() -> FileResponse:
            """返回前端首页；未检测到产物时回落到根信息接口。"""
            return render_index()

        @app.get(
            "/{full_path:path}",
            summary="前端路由回落",
            tags=["默认"],
            include_in_schema=False,
        )
        async def spa_fallback(full_path: str) -> FileResponse:
            """非接口路径回落首页（兼容 history 路由）；命中真实静态文件则直接返回。"""
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="接口不存在")
            target = (web_dist / full_path).resolve()
            if target.is_file() and str(target).startswith(str(web_dist.resolve())):
                return FileResponse(str(target))
            return render_index()
    else:

        @app.get("/", summary="服务根信息", tags=["默认"])
        async def root() -> ApiResponse[dict[str, str]]:
            """根路径：返回服务名、版本与常用入口。"""
            return ok(
                {
                    "name": settings.app_name,
                    "env": settings.app_env,
                    "version": __version__,
                    "docs": "/docs",
                    "openapi": "/openapi.json",
                    "health": "/api/v1/health",
                    "note": (
                        "未检测到 frontend/dist；产物应随仓库发布，缺失时可 "
                        "`cd web && npm install && npm run build` 重新生成"
                    ),
                }
            )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        """注入 traceId 并记录访问日志。"""
        trace_id = request.headers.get(_TRACE_HEADER) or new_trace_id()
        set_trace_id(trace_id)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("请求异常：%s %s", request.method, request.url.path)
            raise
        response.headers[_TRACE_HEADER] = trace_id
        logger.info(
            "%s %s -> %s", request.method, request.url.path, response.status_code
        )
        return response

    @app.exception_handler(BizError)
    async def biz_error_handler(_: Request, exc: Exception) -> JSONResponse:
        """业务异常统一响应。"""
        assert isinstance(exc, BizError)
        from pms.common.codes import http_status_of

        body = ApiResponse[None](
            code=exc.code,
            message=exc.message,
            data=exc.detail,
            traceId=get_trace_id(),
            timestamp=now_text(),
        )
        return JSONResponse(
            status_code=http_status_of(exc.code), content=body.model_dump()
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        """未处理异常兜底，不泄漏堆栈。"""
        logger.exception("未处理异常：%s", exc)
        body = ApiResponse[None](
            code=ErrorCode.SERVER_ERROR,
            message="服务异常",
            traceId=get_trace_id(),
            timestamp=now_text(),
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    """构建启动参数解析器（缺省值来自配置，命令行可覆盖）。"""
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="pms.main", description="启动 PMS Web 服务（内置 Uvicorn，纯 Python）"
    )
    parser.add_argument("--host", default=settings.app_host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.app_port, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发环境）")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="工作进程数（≤20 并发的小企业规模保持默认 1 即可）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """命令行入口：直接启动 Web 服务（后端接口与前端页面同一端口）。

    Args:
        argv: 命令行参数，缺省取 `sys.argv[1:]`。
    """
    import uvicorn

    settings = get_settings()
    args = build_parser().parse_args(argv)
    setup_logging(settings.log_level)
    visit_host = "127.0.0.1" if args.host in {"0.0.0.0", "::", ""} else args.host
    logger.info(
        "启动服务 http://%s:%s 环境=%s 版本=%s",
        visit_host,
        args.port,
        settings.app_env,
        __version__,
    )
    if (web_dist_dir() / "index.html").is_file():
        logger.info("前端页面 http://%s:%s/ （接口文档 /docs）", visit_host, args.port)
    else:
        logger.warning("未检测到前端产物 frontend/dist，`/` 将返回服务根信息")
    uvicorn.run(
        "pms.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=None if (args.reload or args.workers <= 1) else args.workers,
        log_level=settings.log_level.lower(),
        access_log=False,  # 访问日志已由 traceId 中间件统一记录
    )


if __name__ == "__main__":
    main()
