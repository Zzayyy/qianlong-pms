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

from pms.common.exceptions import BizRuleError
from pms.common.logging import get_logger
from pms.core.redis import CONFIG_CACHE, cache_delete, cache_get, cache_set
from pms.system.defaults import CONFIG_REMARKS, DEFAULT_CONFIGS, config_type, effective_remark
from pms.system.models import SysConfig

logger = get_logger(__name__)

_LOCAL_TTL: Final[int] = 300
_local_cache: dict[str, tuple[str, float]] = {}

_BOOL_TRUE: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE: Final[frozenset[str]] = frozenset({"false", "0", "no", "off"})
_OPTIONAL_EMPTY: Final[frozenset[str]] = frozenset(
    {
        "notify.mail.smtpHost",
        "notify.mail.smtpUser",
        "notify.mail.smtpFrom",
        "notify.mail.password",
        "notify.mail.testTo",
    }
)


def validate_value(key: str, raw: str) -> str:
    """按参数类型校验并规范化取值。

    Raises:
        BizRuleError: 类型不符、负数、端口越界或必填项为空。
    """
    value = (raw or "").strip()
    if len(value) > 1024:
        raise BizRuleError(f"{key} 取值过长（最多 1024 字符）")
    kind = config_type(key)
    if kind == "BOOL":
        lowered = value.lower()
        if lowered in _BOOL_TRUE:
            return "true"
        if lowered in _BOOL_FALSE:
            return "false"
        raise BizRuleError(f"{key} 只接受 true 或 false")
    if key == "notify.mail.security":
        lowered = value.upper()
        if lowered not in {"SSL", "STARTTLS", "NONE"}:
            raise BizRuleError("notify.mail.security 只接受 SSL / STARTTLS / NONE")
        return lowered
    if kind in {"INT", "FLOAT"}:
        if not value:
            raise BizRuleError(f"{key} 不能为空")
        try:
            number = int(value) if kind == "INT" else float(value)
        except ValueError as exc:
            name = "整数" if kind == "INT" else "数字"
            raise BizRuleError(f"{key} 需要{name}：{value}") from exc
        if number < 0:
            raise BizRuleError(f"{key} 不能为负数")
        if key == "notify.mail.smtpPort" and not 1 <= number <= 65535:
            raise BizRuleError("notify.mail.smtpPort 需在 1~65535 之间")
        return str(number) if kind == "INT" else format(number, "g")
    if not value and key in DEFAULT_CONFIGS and key not in _OPTIONAL_EMPTY:
        raise BizRuleError(f"{key} 不能为空")
    return value


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
