"""本地文档存储单元测试：按项目分目录、扩展名白名单、目录穿越防护。"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import UploadFile

from pms.common.exceptions import BizRuleError
from pms.file.storage import resolve_storage_path, save_upload, upload_root


def _upload(name: str, payload: bytes = b"%PDF-1.4 demo") -> UploadFile:
    """构造内存中的上传文件。"""
    return UploadFile(file=BytesIO(payload), filename=name)


async def test_save_upload_into_project_directory() -> None:
    """缺少项目编号时回落到 `project_<id>/<归属>/年/月/`。"""
    stored = await save_upload(_upload("需求规格说明书.pdf"), 987654321)
    target = upload_root() / stored.storage_path
    try:
        assert stored.storage_path.startswith("project_987654321/project/")
        assert stored.origin_name == "需求规格说明书.pdf"
        assert stored.size > 0
        assert target.is_file()
        assert target.read_bytes().startswith(b"%PDF")
    finally:
        target.unlink(missing_ok=True)


async def test_save_upload_uses_project_code_and_category() -> None:
    """有项目编号与节点名时，按 `编号/归属/节点/年/月/` 分目录。"""
    stored = await save_upload(
        _upload("设计稿.pdf"),
        987654321,
        project_code="PRJ-2026-0001",
        biz_type="STAGE",
        biz_label="需求阶段",
    )
    target = upload_root() / stored.storage_path
    try:
        assert stored.storage_path.startswith("PRJ-2026-0001/stage/需求阶段/")
        assert target.is_file()
    finally:
        target.unlink(missing_ok=True)


async def test_sanitize_illegal_segment() -> None:
    """项目编号/节点名里的非法字符会被替换，避免建目录失败。"""
    stored = await save_upload(
        _upload("日志.pdf"),
        1,
        project_code='PRJ/2026:01*?',
        biz_type="OTHER",
    )
    assert stored.storage_path.startswith("PRJ_2026_01__/other/")
    (upload_root() / stored.storage_path).unlink(missing_ok=True)


async def test_reject_disallowed_extension() -> None:
    """不在白名单内的扩展名直接拒绝。"""
    with pytest.raises(BizRuleError):
        await save_upload(_upload("virus.exe"), 1)


async def test_reject_empty_file() -> None:
    """空文件拒绝上传。"""
    with pytest.raises(BizRuleError):
        await save_upload(_upload("empty.pdf", b""), 1)


def test_storage_path_cannot_escape_root() -> None:
    """数据库中的路径不能穿越出上传根目录。"""
    with pytest.raises(BizRuleError):
        resolve_storage_path("../../Windows/System32/drivers/etc/hosts")
