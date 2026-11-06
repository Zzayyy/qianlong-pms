"""定时任务分布式锁（多实例部署只执行一次，设计稿 11 §4）。

基于 `t_sys_job_lock` 表实现「抢占 + 续期 + 过期接管」：

1. 无记录 → 插入抢占（唯一索引冲突视为被其他实例抢到）
2. 记录属本进程 → 续期
3. 记录属他人且未过期 → 放弃执行（返回 False）
4. 记录属他人且已过期 → CAS 抢占（持有者崩溃后可由其他实例接管）
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.logging import get_logger
from pms.system.models import SysJobLock

logger = get_logger(__name__)

# 进程身份：主机名 + PID + 随机串，保证同进程续期、跨进程互斥
OWNER_TOKEN: Final[str] = f"{socket.gethostname()}#{os.getpid()}#{uuid.uuid4().hex[:8]}"

DEFAULT_TTL_SECONDS: Final[int] = 300

# MySQL DATETIME 为秒精度且**四舍五入**，释放后读回的时间可能比 now 大约 0.5s；
# 过期判断需留出容差，否则刚释放的锁会被误判为「他人持有中」
_EXPIRE_TOLERANCE: Final[timedelta] = timedelta(seconds=1)


async def acquire(
    session: AsyncSession,
    lock_name: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    owner: str = OWNER_TOKEN,
) -> bool:
    """抢占锁：成功返回 True，被其他实例持有返回 False。"""
    now = datetime.now()
    expire_at = now + timedelta(seconds=ttl_seconds)
    row = (
        await session.execute(
            select(SysJobLock).where(SysJobLock.lock_name == lock_name, SysJobLock.deleted == 0)
        )
    ).scalar_one_or_none()

    if row is None:
        session.add(
            SysJobLock(
                lock_name=lock_name,
                owner_token=owner,
                expire_at=expire_at,
                create_time=now,
                update_time=now,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info("任务 %s 被其他实例抢占", lock_name)
            return False
        return True

    if row.owner_token == owner:
        row.expire_at = expire_at
        row.update_time = now
        await session.commit()
        return True

    if row.expire_at is not None and row.expire_at > now + _EXPIRE_TOLERANCE:
        logger.info("任务 %s 由实例 %s 持有，本实例跳过", lock_name, row.owner_token)
        return False

    # 过期接管：CAS 更新，避免两个实例同时抢到
    result = await session.execute(
        update(SysJobLock)
        .where(
            SysJobLock.id == row.id,
            SysJobLock.owner_token == row.owner_token,
            SysJobLock.deleted == 0,
        )
        .values(owner_token=owner, expire_at=expire_at, update_time=now)
    )
    if result.rowcount != 1:
        await session.rollback()
        return False
    await session.commit()
    logger.warning("任务 %s 锁已过期，由本实例接管", lock_name)
    return True


async def release(session: AsyncSession, lock_name: str, owner: str = OWNER_TOKEN) -> None:
    """释放本进程持有的锁（他人持有的锁不释放）。"""
    await session.execute(
        update(SysJobLock)
        .where(
            SysJobLock.lock_name == lock_name,
            SysJobLock.owner_token == owner,
            SysJobLock.deleted == 0,
        )
        .values(expire_at=datetime.now())
    )
    await session.commit()
