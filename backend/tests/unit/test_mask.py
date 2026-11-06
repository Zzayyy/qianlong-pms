"""字段脱敏测试（设计稿 03 §4.4）。"""

from __future__ import annotations

from pms.common.mask import mask_amount, mask_email, mask_mobile, mask_name


def test_mask_mobile() -> None:
    """手机号中间四位脱敏。"""
    assert mask_mobile("13812341234") == "138****1234"
    assert mask_mobile("123") == "****"


def test_mask_email() -> None:
    """邮箱保留首字符与域名。"""
    assert mask_email("zhangsan@qloffice.com") == "z****@qloffice.com"
    assert mask_email("bad") == "****"


def test_mask_name() -> None:
    """姓名保留姓氏。"""
    assert mask_name("张三") == "张*"
    assert mask_name("李") == "李"


def test_mask_amount() -> None:
    """金额不可见时返回掩码。"""
    assert mask_amount(120000) == "***"
    assert mask_amount(0) == "0.00"
    assert mask_amount(None) == "****"
