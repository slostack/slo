"""Engine wiring tests (111.a.2 A9–A11) on the real Honker engine."""

import ast
import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import honker
import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.workflows import ScheduleEngine, ScheduleEngineServices


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


def test_only_worker_modules_import_honker() -> None:
    """A9: only src/schedules/workflows.py and src/schedules/worker.py import honker."""
    importers: set[str] = set()
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "honker" or alias.name.startswith("honker.") for alias in node.names):
                    importers.add(path.as_posix())
            elif isinstance(node, ast.ImportFrom):
                if node.module == "honker" or (node.module or "").startswith("honker."):
                    importers.add(path.as_posix())
    assert importers == {"src/schedules/workflows.py", "src/schedules/worker.py"}


class EngineStoresDAO(BaseModel):
    """The disposable stores one engine wiring test runs against."""

    model_config = ConfigDict(frozen=True)

    schedules_db_path: Path = Field(description="The schedules database the engine opens.")
    channel_db_path: Path = Field(description="The channels database deliveries write to.")


@pytest.fixture
def engine_stores(tmp_path: Path) -> EngineStoresDAO:
    """Name the tmp schedules and channels databases one engine test uses."""
    return EngineStoresDAO(
        schedules_db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
    )


def _worker_subprocess_env(tmp_path: Path) -> dict[str, str]:
    """Build one real worker subprocess environment rooted in a tmp home."""
    home: Path = tmp_path / "home"
    schedules: Path = tmp_path / "schedules"
    home.mkdir()
    schedules.mkdir()
    return {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "SLO_HOME": str(home),
        "SLO_SCHEDULES_DIR": str(schedules),
        "SLO_ENV": "test",
        "SLO_HERDR_DISABLED": "1",
        "SLO_PLUGINS_DISABLED": "1",
    }


def _wait_for_registered_tick(db_path: Path) -> None:
    """Wait, with a bound, until the worker's scheduler registration is visible.

    Args:
        db_path (Path): The engine's own database file, read from this process.
    """
    deadline: float = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            connection: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            try:
                row: tuple[int] | None = connection.execute(
                    "SELECT count(*) FROM _honker_scheduler_tasks WHERE name = 'schedule-tick'"
                ).fetchone()
            finally:
                connection.close()
            if row is not None and row[0] >= 1:
                return
        except sqlite3.Error as error:
            last_error = error
        time.sleep(0.2)
    raise AssertionError(f"worker never registered its tick within the wait bound ({last_error})")


class CloseFailingChannelGateway(ChannelGateway):
    """Real channel gateway whose close fails after its repository closed."""

    async def close(self) -> None:
        """Close the repository, then fail like a gateway teardown error.

        Raises:
            RuntimeError: Always, after the repository is closed.
        """
        await super().close()
        raise RuntimeError("gateway close failed")


class OpenFailingChannelGateway(ChannelGateway):
    """Channel gateway whose open fails before any connection exists."""

    async def open(self) -> None:
        """Fail like a channels store that cannot be opened.

        Raises:
            OSError: Always.
        """
        raise OSError("channels store unavailable")


async def test_engine_services_close_closes_the_database_when_the_gateway_close_fails(
    tmp_path: Path,
) -> None:
    """A failure-safe close: a gateway close error still closes the schedules
    database and propagates the gateway error."""
    schedules_path: Path = tmp_path / "schedules.db"
    services = ScheduleEngineServices(
        db_path=schedules_path,
        channel_db_path=tmp_path / "channels.db",
        history_root=None,
        channel_gateway=CloseFailingChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        ),
    )

    with pytest.raises(RuntimeError, match="gateway close failed"):
        async with services as opened:
            async with opened.database.transaction():
                pass
            assert (tmp_path / "schedules.db-wal").exists(), "the schedules database is open"
    assert not (tmp_path / "schedules.db-wal").exists(), "the database close ran despite the gateway error"


async def test_engine_services_open_failure_closes_the_database(tmp_path: Path) -> None:
    """A gateway that cannot open leaves no schedules connection behind."""
    services = ScheduleEngineServices(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        history_root=None,
        channel_gateway=OpenFailingChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        ),
    )

    with pytest.raises(OSError, match="channels store unavailable"):
        async with services:
            raise AssertionError("the body never runs when opening failed")
    assert not (tmp_path / "schedules.db-wal").exists()


def test_worker_starts_and_sigterm_stops(tmp_path: Path) -> None:
    """A10: `slo schedule worker` starts, registers the tick, and SIGTERM stops it cleanly."""
    environment: dict[str, str] = _worker_subprocess_env(tmp_path)
    db_path: Path = tmp_path / "schedules" / "schedules.db"
    worker: subprocess.Popen[bytes] = subprocess.Popen(
        [sys.executable, "-m", "src.cli", "schedule", "worker"],
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_registered_tick(
            ScheduleEngine(db_path=db_path, channel_db_path=tmp_path / "channels.db").engine_db_path
        )
        worker.terminate()
        output, _ = worker.communicate(timeout=30)
        assert worker.returncode == 0, f"worker did not stop cleanly: {output!r}"
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=10)


async def test_worker_start_failure_releases_resources_and_exits(tmp_path: Path) -> None:
    """A10: a start failure releases the engine's resources and raises for exit 1."""
    from src.schedules.dao import ScheduleEngineReadinessDAO
    from src.schedules.exceptions import ScheduleWorkerStartError
    from src.schedules.worker import ScheduleWorker

    class LeaderLockHeldEngine:
        """Injected engine stub whose start fails like a held leader lock."""

        def __init__(self) -> None:
            """Start with nothing opened or closed."""
            self.opened: bool = False
            self.closed: bool = False
            self.run_timeout_seconds: int = 3600

        async def run(self, *, stop_event: asyncio.Event) -> None:
            """Never reached: the start fails first."""
            raise AssertionError("a failed start never runs the engine")

        def open(self) -> None:
            """Record the open, then fail like honker does when the lock is held."""
            self.opened = True
            raise honker.LockHeld("schedule worker")

        def release_predecessor_locks(self) -> int:
            """Never reached: the start fails first."""
            raise AssertionError("a failed open releases no engine locks")

        def readiness(self) -> ScheduleEngineReadinessDAO:
            """Never reached: the start fails first."""
            raise AssertionError("a failed open never answers health")

        def close(self) -> None:
            """Record that the worker still released the engine."""
            self.closed = True

    engine: LeaderLockHeldEngine = LeaderLockHeldEngine()
    worker: ScheduleWorker = ScheduleWorker(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        engine=engine,
    )
    with pytest.raises(ScheduleWorkerStartError):
        worker.run_foreground()
    assert engine.opened and engine.closed


async def test_scheduled_tick_delivers_under_engine(engine_stores: EngineStoresDAO) -> None:
    """A11: the real engine fires its tick and the invocation reaches the channel.

    The recipient is a registered agent participant, so the delivery succeeds
    and the channel row is accepted-free (the poller's job); this test proves
    the engine path only: scheduler fire → tick handler → delivery queue →
    channel row (real-run evidence, not a stub).
    """
    recipient: UUID = UUID("01234567-89ab-cdef-0123-456789abcdef")
    # A schedule due within the engine's 15-second tick cadence.
    schedules_db = ScheduleDatabase(db_path=engine_stores.schedules_db_path)
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name="Engine tick target",
                prompt="engine tick prompt",
                trigger=IntervalTriggerDAO(every_seconds=15),
                session_mode="continuous",
                session_reference=str(recipient),
            ),
            now=_utc_now(),
        )
    finally:
        await service.close()
        await schedules_db.close()

    gateway = ChannelGateway(repository=ChannelRepository(db_path=engine_stores.channel_db_path))
    await gateway.open()
    engine = ScheduleEngine(
        db_path=engine_stores.schedules_db_path, channel_db_path=engine_stores.channel_db_path
    )
    try:
        await gateway.register_agent(session_id=recipient, name="engine acceptance agent")
        engine.open()
        stop_event: asyncio.Event = asyncio.Event()
        engine_task: asyncio.Task[None] = asyncio.create_task(engine.run(stop_event=stop_event))
        try:
            row = None
            for _ in range(120):
                await asyncio.sleep(0.5)
                rows = await gateway.pending_inbound(recipient_id=recipient)
                if rows:
                    row = rows[0]
                    break
            assert row is not None, "the engine tick never delivered within the wait bound"
            assert row.message_contents == "engine tick prompt"
            assert row.sender_name == "scheduler Engine tick target"
        finally:
            stop_event.set()
            await asyncio.wait_for(engine_task, timeout=15)
    finally:
        engine.close()
        await gateway.close()

    schedules_db = ScheduleDatabase(db_path=engine_stores.schedules_db_path)
    try:
        async with schedules_db.transaction() as transaction:
            invocation_rows: list[sqlite3.Row] = await transaction.fetch_all(
                sql="SELECT status FROM schedule_invocations WHERE schedule_id = ?",
                parameters=(str(created.id),),
            )
            statuses = {str(invocation_row["status"]) for invocation_row in invocation_rows}
    finally:
        await schedules_db.close()
    assert "delivered" in statuses, statuses


async def test_engine_reopened_after_close_can_enqueue_deliveries(tmp_path: Path) -> None:
    """FIR111-03: a second engine opened after the first closed owns its own
    delivery task; registration is per engine, not a process-global flag."""
    first = ScheduleEngine(db_path=tmp_path / "one.db", channel_db_path=tmp_path / "channels.db")
    first.open()
    first.close()

    second = ScheduleEngine(db_path=tmp_path / "two.db", channel_db_path=tmp_path / "channels.db")
    second.open()
    try:
        await second.enqueue_delivery(
            invocation_id=UUID("01234567-89ab-cdef-0123-456789abcdef"),
            schedule_id=UUID("01234567-89ab-cdef-0123-456789abcdef"),
        )
    finally:
        second.close()


async def test_closed_engine_rejects_delivery_enqueue(tmp_path: Path) -> None:
    """FIR111-03: an engine that never opened (or was closed) states that in
    its error instead of silently using another engine's task."""
    engine = ScheduleEngine(db_path=tmp_path / "late.db", channel_db_path=tmp_path / "channels.db")
    try:
        await engine.enqueue_delivery(
            invocation_id=UUID("01234567-89ab-cdef-0123-456789abcdef"),
            schedule_id=UUID("01234567-89ab-cdef-0123-456789abcdef"),
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("enqueue on an unopened engine must fail loudly")
    finally:
        engine.close()


async def test_worker_delivery_resolves_session_name_and_persists_recipient(
    tmp_path: Path,
) -> None:
    """FIR111-04: the production engine resolves a saved session name through
    its own history store and persists the recipient on the invocation."""
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    session_id = "01234567-89ab-cdef-0123-456789abcdef"
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
    await history.rename_session(session_id=session_id, session_name="worker target")

    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name="Named worker target",
                prompt="named delivery prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
                session_reference="worker target",
            ),
            now=_utc_now(),
        )
        invocation = await service.trigger_now(reference=str(created.id), now=_utc_now())
    finally:
        await service.close()
        await schedules_db.close()

    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(session_id), name="slo worker target")
    await gateway.close()
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        history_root=tmp_path / "history",
    )
    engine.open()
    try:
        await engine.deliver_one(invocation_id=str(invocation.id), schedule_id=str(created.id))
    finally:
        engine.close()

    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    try:
        rows = await gateway.pending_inbound(recipient_id=UUID(session_id))
        assert len(rows) == 1
        assert rows[0].message_contents == "named delivery prompt"
    finally:
        await gateway.close()

    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    try:
        async with schedules_db.transaction() as transaction:
            stored = await ScheduleInvocationRepository().get(
                invocation_id=invocation.id, transaction=transaction
            )
    finally:
        await schedules_db.close()
    assert stored is not None
    assert stored.status == "delivered"
    assert stored.recipient_session_id == session_id


async def test_worker_delivery_fails_unknown_name_and_slug_without_sending(
    tmp_path: Path,
) -> None:
    """FIR111-04: an unknown spaced name and an unknown slug each fail through
    the engine without a channel row."""
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        history_root=tmp_path / "history",
    )
    engine.open()
    try:
        spaced = await service.create(
            new_schedule=NewScheduleDAO(
                name="Spaced reference",
                prompt="spaced prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
                session_reference="no such session",
            ),
            now=_utc_now(),
        )
        spaced_invocation = await service.trigger_now(reference=str(spaced.id), now=_utc_now())
        slug = await service.create(
            new_schedule=NewScheduleDAO(
                name="Slug reference",
                prompt="slug prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
                session_reference="ghost-session",
            ),
            now=_utc_now(),
        )
        slug_invocation = await service.trigger_now(reference=str(slug.id), now=_utc_now())
        await engine.deliver_one(invocation_id=str(spaced_invocation.id), schedule_id=str(spaced.id))
        await engine.deliver_one(invocation_id=str(slug_invocation.id), schedule_id=str(slug.id))
    finally:
        engine.close()
        await service.close()
        await schedules_db.close()

    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    try:
        async with schedules_db.transaction() as transaction:
            spaced_row = await ScheduleInvocationRepository().get(
                invocation_id=spaced_invocation.id, transaction=transaction
            )
            slug_row = await ScheduleInvocationRepository().get(
                invocation_id=slug_invocation.id, transaction=transaction
            )
            channel_rows = await transaction.fetch_all(
                sql="SELECT COUNT(*) AS n FROM schedule_invocations WHERE status = 'delivered'", parameters=()
            )
    finally:
        await schedules_db.close()
    assert spaced_row is not None and spaced_row.status == "failed"
    assert spaced_row.failure_reason == "unknown_session_reference"
    assert slug_row is not None and slug_row.status == "failed"
    assert slug_row.failure_reason == "unknown_recipient"
    assert int(channel_rows[0]["n"]) == 0


def test_worker_forwards_the_run_timeout_to_the_engine() -> None:
    """D24: the run timeout is configurable at the worker boundary."""
    from src.schedules.worker import ScheduleWorker

    worker = ScheduleWorker(
        db_path=Path("unused.db"),
        channel_db_path=Path("unused-channels.db"),
        run_timeout_seconds=1234,
    )
    assert worker.run_timeout_seconds == 1234


def test_worker_command_exposes_the_run_timeout_option() -> None:
    """D24: `slo schedule worker --run-timeout-seconds` exists."""
    from typer.testing import CliRunner

    from src.cli.app import app

    result = CliRunner().invoke(app, ["schedule", "worker", "--help"])
    assert result.exit_code == 0
    assert "--run-timeout-seconds" in result.output
