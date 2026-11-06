"""本地文件存储：按项目分目录、白名单校验、流式落盘（一期不接对象存储）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import UploadFile

from pms.common.exceptions import BizRuleError
from pms.core.config import get_settings

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

# 允许的文档类型（交付文档/设计稿/图纸/压缩包），其余一律拒绝
ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".md",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".dwg",
        ".dxf",
        ".zip",
        ".rar",
        ".7z",
    }
)

_CHUNK_SIZE: Final[int] = 1024 * 1024


@dataclass(slots=True)
class StoredFile:
    """落盘结果。"""

    file_key: str
    origin_name: str
    storage_path: str
    size: int
    mime: str


def upload_root() -> Path:
    """上传根目录（`upload_dir` 支持绝对/相对路径，相对路径以项目根为基准）。"""
    configured = Path(get_settings().upload_dir)
    return configured if configured.is_absolute() else _PROJECT_ROOT / configured


def project_dir(project_id: int) -> Path:
    """项目文档目录：`<upload_dir>/project_<id>/`。"""
    return upload_root() / f"project_{project_id}"


def resolve_storage_path(storage_path: str) -> Path:
    """把数据库中的相对路径还原为绝对路径，并阻止目录穿越。"""
    root = upload_root().resolve()
    if Path(storage_path).is_absolute():
        target = Path(storage_path).resolve()
    else:
        target = (root / storage_path).resolve()
    if not str(target).startswith(str(root)):
        raise BizRuleError("非法的文件路径")
    return target


def _ext_of(name: str) -> str:
    """取小写扩展名。"""
    return Path(name).suffix.lower()


async def save_upload(upload: UploadFile, project_id: int) -> StoredFile:
    """保存上传文件：校验扩展名与大小后写入项目目录。"""
    settings = get_settings()
    origin_name = (upload.filename or "unnamed").strip()
    ext = _ext_of(origin_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise BizRuleError(f"不支持的文件类型：{ext or '未知'}")
    max_bytes = max(int(settings.upload_max_mb), 1) * 1024 * 1024

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise BizRuleError(f"文件超过 {settings.upload_max_mb}MB 上限")
        chunks.append(chunk)
    if total <= 0:
        raise BizRuleError("空文件不允许上传")

    today = date.today()
    relative_dir = Path(f"project_{project_id}") / f"{today.year}" / f"{today.month:02d}"
    target_dir = upload_root() / relative_dir
    file_key = f"{uuid4().hex}{ext}"
    target = target_dir / file_key
    await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, b"".join(chunks))
    return StoredFile(
        file_key=file_key,
        origin_name=origin_name,
        storage_path=str(relative_dir / file_key).replace("\\", "/"),
        size=total,
        mime=upload.content_type or "application/octet-stream",
    )
