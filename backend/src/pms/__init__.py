"""PMS 项目全周期管理与变更系统。

版本号**唯一来源**是项目根的 `VERSION` 文件（由 `scripts/version.py` 维护），
此处动态读取，避免代码与文档版本漂移。
"""

from __future__ import annotations

from pathlib import Path

_VERSION_FILE: Path = Path(__file__).resolve().parents[3] / "VERSION"


def _read_version() -> str:
    """读取 `VERSION` 文件；缺失时回落 `0.0.0`。"""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


__version__ = _read_version()
