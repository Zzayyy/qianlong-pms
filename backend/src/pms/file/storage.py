"""本地文件存储：按项目分目录、白名单校验、流式落盘（一期不接对象存储）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from datetime import date, datetime
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


_ILLEGAL_SEGMENT = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_segment(value: str, fallback: str = "") -> str:
    """目录名安全化：去掉路径分隔符与 Windows 非法字符，超长截断。"""
    text = _ILLEGAL_SEGMENT.sub("_", (value or "").strip()).strip(" .")
    return text[:48] or fallback


def project_folder(project_code: str, project_id: int) -> str:
    """项目文件夹名：优先用可读的项目编号，缺失时回落到 `project_<id>`。"""
    return _safe_segment(project_code, f"project_{project_id}")


def project_dir(project_code: str, project_id: int) -> Path:
    """项目文档目录：`<upload_dir>/<项目编号>/`。"""
    return upload_root() / project_folder(project_code, project_id)


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


async def save_upload(
    upload: UploadFile,
    project_id: int,
    *,
    project_code: str = "",
    biz_type: str = "PROJECT",
    biz_label: str = "",
) -> StoredFile:
    """保存上传文件：校验扩展名与大小后写入项目目录。

    目录结构（便于管理员直接在磁盘上按项目、按归属翻阅）：:

        <upload_dir>/<项目编号>/<归属类型>/[<阶段或里程碑名>/]<年>/<月>/<时间戳_随机串>.<ext>
    """
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
    kind = _safe_segment((biz_type or "OTHER").lower(), "other")
    label = _safe_segment(biz_label, "")
    segments = [project_folder(project_code, project_id), kind]
    if label:
        segments.append(label)
    segments += [str(today.year), f"{today.month:02d}"]
    relative_dir = Path(*segments)
    target_dir = upload_root() / relative_dir
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_key = f"{stamp}_{uuid4().hex[:8]}{ext}"
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
