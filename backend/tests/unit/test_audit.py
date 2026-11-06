"""审计留痕纯函数测试：脱敏、模块归类、结果分类。"""

from __future__ import annotations

import json

from pms.audit.service import module_of, result_of, sanitize_params


def test_sanitize_params_masks_password() -> None:
    """口令与令牌不得进入审计库。"""
    raw = json.dumps({"username": "admin", "password": "Pms@12345", "token": "abc.def"})
    text = sanitize_params(raw)
    assert "Pms@12345" not in text
    assert "abc.def" not in text
    assert json.loads(text)["password"] == "******"
    assert json.loads(text)["username"] == "admin"


def test_sanitize_params_masks_nested_and_non_json() -> None:
    """嵌套结构与非 JSON 文本同样处理。"""
    raw = json.dumps({"items": [{"password": "x"}], "keep": 1})
    assert json.loads(sanitize_params(raw))["items"][0]["password"] == "******"
    assert sanitize_params("name=1&password=2") == "name=1&password=2"
    assert sanitize_params("") == ""


def test_sanitize_params_truncates() -> None:
    """超长入参被裁剪，避免审计表膨胀。"""
    assert len(sanitize_params("x" * 5000)) <= 2000


def test_module_of() -> None:
    """URL 首段映射为模块名（复数归并为单数，CRM 两个资源合并）。"""
    assert module_of("/api/v1/projects/1") == "project"
    assert module_of("/api/v1/changes/2/approve") == "change"
    assert module_of("/api/v1/auth/login") == "auth"
    assert module_of("/api/v1/users") == "org"
    assert module_of("/api/v1/customers") == "crm"
    assert module_of("/api/v1/configs") == "system"
    assert module_of("/unknown") == "system"


def test_result_of() -> None:
    """状态码分类：2xx 成功、401/403 拒绝、4xx 失败、5xx 错误。"""
    assert result_of(200) == "SUCCESS"
    assert result_of(401) == "DENIED"
    assert result_of(403) == "DENIED"
    assert result_of(409) == "FAIL"
    assert result_of(500) == "ERROR"
