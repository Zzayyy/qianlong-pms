"""客户与商机数据可见性测试（对应设计稿 03 §4 数据范围与需求 3）。"""

from __future__ import annotations

import pytest

from pms.common.exceptions import DataForbiddenError
from pms.core.context import AuthContext
from pms.crm.models import CrmCustomer, CrmOpportunity
from pms.crm.visibility import (
    can_view_customer,
    can_view_opportunity,
    ensure_customer_visible,
    ensure_dept_assignable,
    ensure_opportunity_visible,
)

DEPT_ID = 10
OTHER_DEPT = 20


def _context(
    *, user_id: int = 1, dept_id: int = DEPT_ID, visible: set[int] | None = None
) -> AuthContext:
    """构造身份上下文；`visible` 为 None 表示全公司范围。"""
    return AuthContext(
        user_id=user_id,
        username=f"u{user_id}",
        real_name=f"用户{user_id}",
        dept_id=dept_id,
        dept_path=f"/{dept_id}/",
        roles=frozenset(),
        permissions=frozenset(),
        visible_dept_ids=None if visible is None else frozenset(visible),
    )


def _customer(owner_user_id: int = 99, owner_dept_id: int = DEPT_ID) -> CrmCustomer:
    return CrmCustomer(owner_user_id=owner_user_id, owner_dept_id=owner_dept_id)


def test_owner_sees_customer_outside_dept_scope() -> None:
    """本人负责的客户始终可见，不受部门范围影响。"""
    context = _context(user_id=9, visible={OTHER_DEPT})
    assert can_view_customer(context, _customer(owner_user_id=9, owner_dept_id=DEPT_ID)) is True


def test_dept_scope_sees_same_dept_customer() -> None:
    """负责人部门在数据范围内即可见。"""
    context = _context(visible={DEPT_ID})
    assert can_view_customer(context, _customer()) is True


def test_other_dept_customer_raises() -> None:
    """跨部门客户不可见，抛数据越权（40302）。"""
    context = _context(visible={DEPT_ID})
    with pytest.raises(DataForbiddenError):
        ensure_customer_visible(context, _customer(owner_dept_id=OTHER_DEPT))


def test_all_scope_sees_every_customer() -> None:
    """全公司范围不做部门过滤。"""
    context = _context(visible=None)
    assert can_view_customer(context, _customer(owner_dept_id=OTHER_DEPT)) is True


def test_opportunity_visibility_matches_owner_dept() -> None:
    """商机可见性口径与客户一致。"""
    context = _context(user_id=5, visible={DEPT_ID})
    assert can_view_opportunity(context, CrmOpportunity(owner_user_id=9, owner_dept_id=DEPT_ID))
    with pytest.raises(DataForbiddenError):
        ensure_opportunity_visible(
            context, CrmOpportunity(owner_user_id=9, owner_dept_id=OTHER_DEPT)
        )


def test_dept_assignable_blocks_out_of_scope() -> None:
    """写入时负责人部门不可越界；0 表示未指定，不校验。"""
    context = _context(visible={DEPT_ID})
    ensure_dept_assignable(context, 0)
    ensure_dept_assignable(context, DEPT_ID)
    with pytest.raises(DataForbiddenError):
        ensure_dept_assignable(context, OTHER_DEPT)
