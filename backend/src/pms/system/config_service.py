"""系统参数服务：**业务规则阈值的唯一读取入口**（设计稿 00 §4、02 §5）。

约定：
- 业务代码禁止硬编码阈值，一律通过 `ConfigService.get_*` 读取；
- 后台修改参数后写入 `t_sys_config` 并使缓存失效，立即生效；
- 参数缺失时回落到 `defaults.DEFAULT_CONFIGS`，避免上线即报错。
"""

from __future__ import annotations

import time
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.logging import get_logger
from pms.core.redis import CONFIG_CACHE, cache_delete, cache_get, cache_set
from pms.system.defaults import CONFIG_REMARKS, DEFAULT_CONFIGS, effective_remark
from pms.system.models import SysConfig

logger = get_logger(__name__)

_LOCAL_TTL: Final[int] = 300
_local_cache: dict[str, tuple[str, float]] = {}


def _cache_key(key: str) -> str:
    """缓存键。"""
    return f"{CONFIG_CACHE}{key}"


def invalidate(key: str | None = None) -> None:
    """失效参数缓存（进程内）。"""
    if key is None:
        _local_cache.clear()
        return
    _local_cache.pop(key, None)


class ConfigService:
    """系统参数读写服务。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定数据库会话。"""
        self._session = session

    async def get_raw(self, key: str) -> str:
        """读取原始字符串值。"""
        cached = _local_cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]

        remote = await cache_get(_cache_key(key))
        if remote is not None:
            _local_cache[key] = (remote, now + _LOCAL_TTL)
            return remote

        value = await self._query_db(key)
        _local_cache[key] = (value, now + _LOCAL_TTL)
        await cache_set(_cache_key(key), value, ttl=_LOCAL_TTL)
        return value

    async def _query_db(self, key: str) -> str:
        """从数据库读取，缺失时回落默认值。"""
        stmt = select(SysConfig.config_value).where(
            SysConfig.config_key == key, SysConfig.deleted == 0
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        if value is None:
            fallback = DEFAULT_CONFIGS.get(key, "")
            if fallback == "":
                logger.warning("参数缺失且无默认值：%s", key)
            return fallback
        return value

    async def get_str(self, key: str) -> str:
        """读取字符串参数。"""
        return await self.get_raw(key)

    async def get_int(self, key: str) -> int:
        """读取整数参数。"""
        raw = await self.get_raw(key)
        try:
            return int(raw)
        except ValueError:
            logger.warning("参数类型转换失败，回落默认值：%s=%s", key, raw)
            return int(DEFAULT_CONFIGS.get(key, "0"))

    async def get_float(self, key: str) -> float:
        """读取浮点参数。"""
        raw = await self.get_raw(key)
        try:
            return float(raw)
        except ValueError:
            logger.warning("参数类型转换失败，回落默认值：%s=%s", key, raw)
            return float(DEFAULT_CONFIGS.get(key, "0"))

    async def get_bool(self, key: str) -> bool:
        """读取布尔参数（`true/1/yes/on` 视为真）。"""
        raw = (await self.get_raw(key)).strip().lower()
        return raw in {"true", "1", "yes", "on"}

    async def set_value(self, key: str, value: str, operator_id: int = 0) -> SysConfig:
        """写入参数（存在则更新），并失效缓存。"""
        stmt = select(SysConfig).where(SysConfig.config_key == key, SysConfig.deleted == 0)
        result = await self._session.execute(stmt)
        config = result.scalar_one_or_none()
        if config is None:
            config = SysConfig(config_key=key, config_value=value, create_by=operator_id)
            self._session.add(config)
        else:
            config.config_value = value
            config.update_by = operator_id
        await self._session.flush()
        invalidate(key)
        await cache_delete(_cache_key(key))
        return config

    async def seed_defaults(self, operator_id: int = 0) -> int:
        """补齐缺失的默认参数，并为已有参数回填中文说明（初始化与升级时调用）。"""
        stmt = select(SysConfig).where(SysConfig.deleted == 0)
        result = await self._session.execute(stmt)
        stored = {item.config_key: item for item in result.scalars().all()}
        count = 0
        changed = False
        for key, value in DEFAULT_CONFIGS.items():
            remark = CONFIG_REMARKS.get(key, "")
            row = stored.get(key)
            if row is None:
                self._session.add(
                    SysConfig(
                        config_key=key,
                        config_value=value,
                        group_name=_group_of(key),
                        remark=remark,
                        builtin=1,
                        create_by=operator_id,
                    )
                )
                count += 1
                continue
            if remark and effective_remark(key, row.remark) != (row.remark or ""):
                row.remark = remark
                changed = True
        if count or changed:
            await self._session.flush()
            invalidate()
        return count


def _group_of(key: str) -> str:
    """按前缀推断参数分组。"""
    from pms.system.defaults import CONFIG_GROUPS

    for prefix, group in CONFIG_GROUPS.items():
        if key.startswith(prefix):
            return group
    return "DEFAULT"
