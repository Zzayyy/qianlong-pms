"""Alembic 迁移环境（异步引擎）。

连接串来自 `.env`（`DB_*`），密码不写入本文件。
用法：
    py -3.12 -m alembic revision --autogenerate -m "初始化"
    py -3.12 -m alembic upgrade head
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from pms.change import models as change_models  # noqa: F401  注册变更域模型
from pms.core.config import get_settings
from pms.core.database import Base
from pms.crm import models as crm_models  # noqa: F401  注册 CRM 域模型
from pms.org import models as org_models  # noqa: F401  注册组织域模型
from pms.project import models as project_models  # noqa: F401  注册项目域模型
from pms.report import models as report_models  # noqa: F401  注册统计域模型
from pms.worklog import models as worklog_models  # noqa: F401  注册日志域模型
from pms.system import models as system_models  # noqa: F401  注册系统域模型

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    """在同步连接上执行迁移。"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建异步引擎并执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations() -> None:
    """入口。"""
    asyncio.run(run_async_migrations())


run_migrations()
