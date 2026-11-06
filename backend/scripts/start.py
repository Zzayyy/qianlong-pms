#!/usr/bin/env python3.12
"""一键启动：纯 Python 拉起后端服务并打开前端页面（无需 Node.js / Nginx）。

设计前提（容量）：面向小企业规模 —— 注册用户 ≤ 300、并发 ≤ 20，
因此默认单进程 Uvicorn 直出「接口 + 前端页面」，同一端口即可访问，
不需要额外部署 Node、Nginx 或多副本。

用法：
  py -3.12 scripts/start.py                 # 启动并自动打开 http://127.0.0.1:8000/
  py -3.12 scripts/start.py --port 8080     # 指定端口
  py -3.12 scripts/start.py --host 0.0.0.0  # 允许局域网访问（同事访问 http://<本机IP>:8000/）
  py -3.12 scripts/start.py --no-open       # 只启动，不自动开浏览器
  py -3.12 scripts/start.py --reload        # 开发模式（代码改动自动重启）
  py -3.12 scripts/start.py --check         # 只做环境自检，不启动服务

实现说明：
  1. 自动把 `backend/src/` 加入 `sys.path`，未执行 `pip install -e .` 也能直接启动；
  2. 前端构建产物 `frontend/dist` 随仓库发布，运行期只由 Python 托管，不依赖 npm；
  3. 启动后轮询 `/api/v1/health`，就绪即调用系统默认浏览器打开首页。
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Sequence
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]
PROJECT_ROOT: Path = BACKEND_ROOT.parent
FRONTEND_DIST: Path = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_HEALTH_PATH = "/api/v1/health"
POLL_INTERVAL = 0.5


class StartError(RuntimeError):
    """启动前置检查失败。"""


def ensure_importable() -> None:
    """把 `backend/src/` 加入模块搜索路径，免除 `pip install -e .` 依赖。"""
    src_dir = BACKEND_ROOT / "src"
    if (src_dir / "pms").is_dir():
        marker = str(src_dir)
        if marker not in sys.path:
            sys.path.insert(0, marker)


def check_python() -> None:
    """校验 Python 版本为 3.12（依赖与语法按 3.12 编写）。"""
    if sys.version_info[:2] != (3, 12):
        raise StartError(f"需要 Python 3.12，当前为 {sys.version.split()[0]}")


def check_env_file() -> bool:
    """检查 `.env` 是否存在；缺失仅告警（可用环境变量替代）。"""
    env_file = BACKEND_ROOT / ".env"
    if env_file.is_file():
        return True
    print("[提示] 未找到 .env，将使用环境变量或默认配置；"
          "请先 `copy backend\\.env.example backend\\.env` 并填写 DB_PASSWORD 等")
    return False


def check_web_dist() -> bool:
    """检查前端产物是否就绪；缺失时给出处理建议。"""
    dist = FRONTEND_DIST
    if (dist / "index.html").is_file():
        return True
    print(f"[提示] 未检测到前端产物 {dist}，`/` 将返回服务根信息；"
          "如需重新构建（需 Node 20）：cd frontend && npm install && npm run build")
    return False


def check_port_free(port: int) -> None:
    """检查端口未被占用，避免启动后才发现冲突。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise StartError(f"端口 {port} 已被占用，请先用 --port 换一个端口或关闭占用进程")


def health_ok(url: str) -> bool:
    """健康检查是否就绪（200 即认为可用）。"""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def open_when_ready(open_url: str, health_url: str, timeout: float) -> None:
    """后台线程：服务就绪后打开浏览器，超时放弃且不中断服务。"""

    def worker() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if health_ok(health_url):
                webbrowser.open(open_url)
                print(f"[就绪] 已打开浏览器：{open_url}")
                return
            time.sleep(POLL_INTERVAL)
        print(f"[提示] {timeout:.0f}s 内未探测到服务就绪，请手动访问 {open_url}")

    threading.Thread(target=worker, name="pms-open-browser", daemon=True).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PMS 一键启动（纯 Python，无需 Node.js）")
    parser.add_argument("--host", default=None, help="监听地址，默认取 APP_HOST（0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认取 APP_PORT（8000）")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启")
    parser.add_argument("--workers", type=int, default=1, help="工作进程数，默认 1 足够")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=60.0,
        help="等待服务就绪的秒数，超时不再自动开浏览器",
    )
    parser.add_argument("--check", action="store_true", help="只做环境自检，不启动服务")
    return parser


def resolve_host_port(args: argparse.Namespace) -> tuple[str, int]:
    """解析监听地址与端口：命令行 > 配置（APP_HOST / APP_PORT）。"""
    from pms.core.config import get_settings

    settings = get_settings()
    host = args.host or settings.app_host
    port = args.port or settings.app_port
    return host, port


def main(argv: Sequence[str] | None = None) -> int:
    """执行前置检查并启动服务。

    Args:
        argv: 命令行参数，缺省取 `sys.argv[1:]`。

    Returns:
        进程退出码：0 正常，1 前置检查失败。
    """
    args = build_parser().parse_args(argv)
    ensure_importable()

    try:
        check_python()
        import uvicorn  # 依赖检查放在版本校验之后
    except StartError as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"[启动失败] 缺少依赖 {exc.name}；请先 `py -3.12 -m pip install -e .`",
              file=sys.stderr)
        return 1

    check_env_file()
    has_web = check_web_dist()

    try:
        host, port = resolve_host_port(args)
    except StartError as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        return 1

    if args.check:
        print("[自检] Python 3.12 / pms / uvicorn 就绪")
        print(f"[自检] 监听 {host}:{port}，前端产物 {'已就绪' if has_web else '缺失'}")
        return 0

    try:
        check_port_free(port)
    except StartError as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        return 1

    visit_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    base = f"http://{visit_host}:{port}"
    print(f"[启动] PMS 服务 {base}  接口文档 {base}/docs  （Ctrl+C 停止）")
    if not args.no_open:
        open_when_ready(f"{base}/", f"{base}{DEFAULT_HEALTH_PATH}", args.health_timeout)

    uvicorn.run(
        "pms.main:app",
        host=host,
        port=port,
        reload=args.reload,
        workers=None if (args.reload or args.workers <= 1) else args.workers,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
