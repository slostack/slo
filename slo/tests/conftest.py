"""Shared test fixtures.

The transactional ``async_db_session`` fixture is from the bootstrap
scaffolding pattern. It is only useful for tests that actually hit
Postgres; v1 has none, but the fixture is kept so future domain tests
have it available.
"""
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config.cfg import cfg


@pytest_asyncio.fixture(scope="function")
async def async_db_session():
    """Yield an AsyncSession bound to a savepoint that rolls back after the test."""
    db_url = cfg("DB_URL_ASYNC")
    if not db_url:
        import pytest
        pytest.skip("SLO_DB_URL_ASYNC is not set; skipping DB-bound test.")

    async_engine = create_async_engine(
        db_url,
        pool_size=5,
        echo=False,
        max_overflow=5,
        pool_use_lifo=True,
        pool_recycle=100,
    )
    TestingAsyncSessionLocal = sessionmaker(
        async_engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        class_=AsyncSession,
    )  # type: ignore

    async with async_engine.connect() as connection:
        trans = await connection.begin()
        async_session = TestingAsyncSessionLocal(bind=connection)
        nested = await connection.begin_nested()

        @event.listens_for(async_session.sync_session, "after_transaction_end")
        def end_savepoint(session, transaction):
            nonlocal nested
            if connection.closed:
                return
            if not connection.in_nested_transaction():
                nested = connection.sync_connection.begin_nested()

        yield async_session
        await trans.rollback()
        await async_session.close()
        await connection.close()
