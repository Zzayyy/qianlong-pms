"""雪花 ID 测试。"""

from __future__ import annotations

import pytest

from pms.common.snowflake import Snowflake


def test_ids_unique_and_monotonic() -> None:
    """同节点生成的 ID 唯一且递增。"""
    generator = Snowflake(worker_id=1)
    ids = [generator.next_id() for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)


def test_worker_id_boundary() -> None:
    """节点编号越界时报错。"""
    with pytest.raises(ValueError):
        Snowflake(worker_id=1 << 11)
