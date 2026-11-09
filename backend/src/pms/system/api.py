"""系统接口：系统参数（后台可调）、字典、健康检查（设计稿 09 §2.6）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import ParamError
from pms.common.response import ok
from pms.core.context import AuthContext
from pms.core.deps import get_session, require_permissions
from pms.system.config_service import ConfigService, validate_value
from pms.system.defaults import CONFIG_GROUPS, DEFAULT_CONFIGS, config_type, effective_remark
from pms.system.models import SysConfig, SysDictItem

router = APIRouter(prefix="/api/v1", tags=["系统管理"])


class ConfigUpdateIn(BaseModel):
    """参数更新入参。"""

    configValue: str = Field(max_length=1024)
    remark: str = ""


class ConfigOut(BaseModel):
    """参数出参。"""

    configKey: str
    configValue: str
    valueType: str
    groupName: str
    defaultValue: str
    remark: str
    builtin: int


class ConfigBatchItem(BaseModel):
    """批量更新单项。"""

    configKey: str = Field(min_length=1, max_length=128)
    configValue: str = Field(max_length=1024)


class ConfigBatchIn(BaseModel):
    """批量更新入参。"""

    items: list[ConfigBatchItem] = Field(default_factory=list)


class ConfigResetIn(BaseModel):
    """恢复默认入参。"""

    configKeys: list[str] = Field(default_factory=list)


def _group_of(key: str) -> str:
    """按前缀推断分组。"""
    for prefix, group in CONFIG_GROUPS.items():
        if key.startswith(prefix):
            return group
    return "DEFAULT"


@router.get("/configs", summary="系统参数列表")
async def list_configs(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """返回全部参数（库值覆盖默认值），说明列统一给出中文含义。"""
    result = await session.execute(select(SysConfig).where(SysConfig.deleted == 0))
    stored = {item.config_key: item for item in result.scalars().all()}
    items: list[ConfigOut] = []
    for key, default_value in DEFAULT_CONFIGS.items():
        row = stored.get(key)
        items.append(
            ConfigOut(
                configKey=key,
                configValue=row.config_value if row else default_value,
                valueType=config_type(key),
                groupName=row.group_name if row else _group_of(key),
                defaultValue=default_value,
                remark=effective_remark(key, row.remark if row else ""),
                builtin=row.builtin if row else 1,
            )
        )
    for key, row in stored.items():
        if key not in DEFAULT_CONFIGS:
            items.append(
                ConfigOut(
                    configKey=key,
                    configValue=row.config_value,
                    valueType=config_type(key),
                    groupName=row.group_name,
                    defaultValue="",
                    remark=effective_remark(key, row.remark) or "自定义参数（未登记中文说明）",
                    builtin=row.builtin,
                )
            )
    del context
    return ok([item.model_dump() for item in items])


async def _known_config_keys(session: AsyncSession) -> set[str]:
    """已登记或已入库的参数键集合。"""
    result = await session.execute(
        select(SysConfig.config_key).where(SysConfig.deleted == 0)
    )
    return set(DEFAULT_CONFIGS) | {str(key) for key in result.scalars().all()}


@router.put("/configs", summary="批量修改系统参数")
async def update_configs(
    body: ConfigBatchIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """一次性保存多个参数：先整体校验，再统一写库并失效缓存。"""
    if not body.items:
        return ok({"updated": 0})
    known = await _known_config_keys(session)
    unknown = [item.configKey for item in body.items if item.configKey not in known]
    if unknown:
        raise ParamError(f"未知参数：{', '.join(unknown)}")
    prepared = [
        (item.configKey, validate_value(item.configKey, item.configValue))
        for item in body.items
    ]
    service = ConfigService(session)
    for key, value in prepared:
        await service.set_value(key, value, operator_id=context.user_id)
    await session.commit()
    return ok({"updated": len(prepared)})


@router.post("/configs/reset", summary="恢复参数默认值")
async def reset_configs(
    body: ConfigResetIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """把指定参数恢复为代码登记的默认值。"""
    if not body.configKeys:
        return ok({"reset": 0})
    invalid = [key for key in body.configKeys if key not in DEFAULT_CONFIGS]
    if invalid:
        raise ParamError(f"参数没有默认值：{', '.join(invalid)}")
    service = ConfigService(session)
    for key in dict.fromkeys(body.configKeys):
        await service.set_value(key, DEFAULT_CONFIGS[key], operator_id=context.user_id)
    await session.commit()
    return ok({"reset": len(dict.fromkeys(body.configKeys))})


@router.put("/configs/{config_key}", summary="修改系统参数")
async def update_config(
    config_key: str,
    body: ConfigUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """修改单个参数：校验类型后写库，缓存立即失效。"""
    known = await _known_config_keys(session)
    if config_key not in known:
        raise ParamError(f"未知参数：{config_key}")
    value = validate_value(config_key, body.configValue)
    service = ConfigService(session)
    config = await service.set_value(config_key, value, operator_id=context.user_id)
    if body.remark:
        config.remark = body.remark
    await session.commit()
    return ok({"configKey": config.config_key, "configValue": config.config_value})


@router.post("/configs/seed", summary="补齐默认参数")
async def seed_configs(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """将缺失的默认参数写入数据库（初始化/升级后调用）。"""
    count = await ConfigService(session).seed_defaults(operator_id=context.user_id)
    await session.commit()
    return ok({"seeded": count})


@router.get("/dicts/{dict_code}", summary="字典项")
async def dict_items(
    dict_code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> object:
    """按字典编码返回字典项。"""
    result = await session.execute(
        select(SysDictItem)
        .where(
            SysDictItem.dict_code == dict_code,
            SysDictItem.deleted == 0,
            SysDictItem.status == "ENABLED",
        )
        .order_by(SysDictItem.sort, SysDictItem.id)
    )
    items = result.scalars().all()
    return ok(
        [{"value": item.item_value, "label": item.item_label} for item in items]
    )


@router.get("/health", summary="健康检查")
async def health() -> object:
    """存活探针。"""
    return ok({"status": "UP"})
