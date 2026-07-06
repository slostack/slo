"""Async PostgreSQL connector for SQLAlchemy.

v1 does not actually use the database — sessions are in-memory — but the
scaffolding follows the standard pattern so future domain modules can plug
in without infrastructure work.
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import sqlalchemy
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from config.cfg import cfg


metadata = sqlalchemy.MetaData()

pool_size: int = 8 if cfg("ENV") == "staging" else 10
max_overflow: int = 2 if cfg("ENV") == "staging" else 10

_db_url = cfg("DB_URL_ASYNC")


def _build_engine() -> AsyncEngine | None:
    """Lazily build the engine; returns ``None`` when no DB_URL_ASYNC is set.

    Allows the rest of the app to import this module without a Postgres
    running locally.
    """
    if not _db_url:
        return None
    return create_async_engine(
        _db_url,
        pool_size=pool_size,
        echo=False,
        max_overflow=max_overflow,
        pool_use_lifo=True,
        pool_recycle=1300,
        echo_pool=True,
    )


async_engine: AsyncEngine | None = _build_engine()

AsyncSessionLocal = (
    sessionmaker(
        async_engine,  # type: ignore[arg-type]
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        class_=AsyncSession,
    )
    if async_engine is not None
    else None
)


async def get_async_session() -> AsyncSession:
    """Return a new AsyncSession instance. Caller owns the lifecycle."""
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Database is not configured (SLO_DB_URL_ASYNC is unset). "
            "Set it in environments/local.env to use the async session."
        )
    return AsyncSessionLocal()  # type: ignore[return-value]


@asynccontextmanager
async def get_async_sessionmaker() -> AsyncIterator[AsyncSession]:
    """Context manager that yields an AsyncSession and closes it on exit."""
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Database is not configured (SLO_DB_URL_ASYNC is unset). "
            "Set it in environments/local.env to use the async session."
        )
    session: AsyncSession = AsyncSessionLocal()  # type: ignore[assignment]
    try:
        yield session
    finally:
        if session.is_active:
            await session.close()
