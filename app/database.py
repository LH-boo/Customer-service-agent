"""数据库连接与会话管理（默认 SQLite，可切换 MySQL）。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    metadata = metadata


def _engine_kwargs() -> dict:
    if settings.database_is_sqlite:
        return {"connect_args": {"timeout": 30}}
    return {"pool_pre_ping": True, "pool_recycle": 1800, "pool_size": 10, "max_overflow": 20}


engine = create_async_engine(settings.database_url, echo=False, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db(seed: bool = True) -> None:
    """建表并按需写入演示数据。"""
    from app import models  # noqa: F401  确保模型已注册

    if settings.database_is_sqlite:
        db_file = settings.database_url.split("///")[-1]
        path = Path(db_file)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if seed:
        from app.seed import seed_demo_data

        async with SessionLocal() as session:
            await seed_demo_data(session)
    logger.info("数据库初始化完成: %s", settings.database_url.split("@")[-1])
