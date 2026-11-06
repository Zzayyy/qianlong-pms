"""雪花 ID 生成器（设计稿 04 §1.1：业务表主键统一雪花 ID）。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

_EPOCH: int = 1_700_000_000_000  # 2023-11-14T22:13:20Z，毫秒
_WORKER_ID_BITS: int = 10
_SEQUENCE_BITS: int = 12
_MAX_WORKER_ID: int = (1 << _WORKER_ID_BITS) - 1
_MAX_SEQUENCE: int = (1 << _SEQUENCE_BITS) - 1
_WORKER_SHIFT: int = _SEQUENCE_BITS
_TIMESTAMP_SHIFT: int = _SEQUENCE_BITS + _WORKER_ID_BITS


@dataclass(slots=True)
class Snowflake:
    """线程安全的雪花 ID 生成器。

    属性:
        worker_id: 节点编号，取值 0~1023。
    """

    worker_id: int = 0
    _lock: threading.Lock = field(init=False, repr=False)
    _sequence: int = field(init=False, default=0, repr=False)
    _last_ms: int = field(init=False, default=0, repr=False)

    def __post_init__(self) -> None:
        """校验节点编号并初始化内部状态。"""
        if not 0 <= self.worker_id <= _MAX_WORKER_ID:
            raise ValueError(f"worker_id 越界：{self.worker_id}")
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_ms = 0

    def next_id(self) -> int:
        """生成下一个 ID（bigint，64 位有符号范围内）。"""
        with self._lock:
            current = self._now_ms()
            if current < self._last_ms:
                # 时钟回拨：等待至上次时间点，避免 ID 重复
                current = self._wait_until(self._last_ms)
            if current == self._last_ms:
                self._sequence = (self._sequence + 1) & _MAX_SEQUENCE
                if self._sequence == 0:
                    current = self._wait_until(self._last_ms + 1)
            else:
                self._sequence = 0
            self._last_ms = current
            return (current - _EPOCH) << _TIMESTAMP_SHIFT | (
                self.worker_id << _WORKER_SHIFT
            ) | self._sequence

    @staticmethod
    def _now_ms() -> int:
        """当前毫秒时间戳。"""
        return int(time.time() * 1000)

    @staticmethod
    def _wait_until(target_ms: int) -> int:
        """自旋等待到目标毫秒。"""
        while True:
            now = Snowflake._now_ms()
            if now >= target_ms:
                return now


_DEFAULT = Snowflake(worker_id=1)


def next_id() -> int:
    """使用默认生成器获取下一个 ID。"""
    return _DEFAULT.next_id()
