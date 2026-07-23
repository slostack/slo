"""Shared test fixtures.

The transactional ``async_db_session`` fixture is from the bootstrap
scaffolding pattern. It is only useful for tests that actually hit
Postgres; v1 has none, but the fixture is kept so future domain tests
have it available.
"""
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config.cfg import cfg


@pytest.fixture(autouse=True)
def _never_spawn_real_terminals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``VisualizerLauncher._default_spawn`` for every test.

    ``VisualizerLauncher.launch()`` opens a REAL terminal window on the
    developer's machine (``osascript`` → Terminal.app on macOS, a terminal
    emulator on Linux) running ``slo visualize --follow`` — a process that
    never exits on its own. Any test that reaches ``launch()`` without
    patching it (e.g. by streaming a ``sub_agent_spawned`` event or a
    ``launch_workflow`` tool result through ``SloTUI._render_event``) would
    leave a live terminal window behind after the suite finishes.

    This guard replaces only the innermost ``_default_spawn`` seam, so:

    - tests that patch ``VisualizerLauncher.launch`` or inject a ``spawn=``
      callable are unaffected (they never reach ``_default_spawn``);
    - tests exercising the real ``launch()`` path still observe ``True``
      (the stub "succeeds") without any process being created;
    - ``environments/tests.env`` additionally sets ``SLO_AUTO_VISUALIZE=0``
      for ``make test``, but this fixture also covers bare ``pytest`` runs
      that never source that file.
    """

    def _stubbed_spawn(argv: list[str]) -> object:
        """Pretend to spawn ``argv`` without creating any process."""
        return object()

    _stubbed_spawn.__test_stub__ = True  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "src.tui.visualizer_launcher.VisualizerLauncher._default_spawn",
        staticmethod(_stubbed_spawn),
    )


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
