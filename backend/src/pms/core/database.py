"""数据库会话与声明式基类（SQLAlchemy 2.0 async）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Final

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pms.common.snowflake import next_id
from pms.core.config import get_settings

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """声明式基类，统一索引命名规范。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CommonMixin:
    """业务表公共字段（设计稿 04 §1.2）。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    create_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    create_time: Mapped[DateTime | None] = mapped_column(
        DateTime, server_default=func.now(), default=None
    )
    update_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    update_time: Mapped[DateTime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), default=None
    )
    deleted: Mapped[int] = mapped_column(BigInteger, default=0)
    tenant_id: Mapped[int] = mapped_column(BigInteger, default=1)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """获取（并惰性创建）异步引擎。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取会话工厂。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，结束自动关闭。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """释放引擎（关机钩子调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
