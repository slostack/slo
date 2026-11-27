"""Operational schedule worker journeys (OPS111-01 to OPS111-09, OPS111-11).

Every test runs real processes against real SQLite stores, the real Honker
engine and real channel stores inside its own temporary roots. The only
substitutes are launchers injected at the runtime's public launch seam to
produce a child that never becomes healthy or a launch that fails; they stand
in for a broken installation, not for the worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import pytest

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository

from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.operational_app_service import (
    CreateOperationalScheduleAppService,
    OperationalScheduleDAO,
    ScheduleNotOperationalError,
    StartOperationalScheduleAppService,
)
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.worker_runtime import (
    ScheduleWorkerHealthDAO,
    ScheduleWorkerLocationDAO,
    ScheduleWorkerRuntime,
    ScheduleWorkerUnavailableError,
    SubprocessScheduleWorkerLauncher,
)
from tests.schedules.worker_processes import (
    TUNED_WORKER_MODULE,
    cli_environment,
    live_worker_pids,
    location_for,
    read_worker_metadata,
    run_cli,
)

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


@pytest.fixture(autouse=True)
def _pin_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point this process at the test roots, so in-process launches serve the same stores as CLI children."""
    monkeypatch.setenv("SLO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))


class _Roots:
    """The test's private schedules directory, SLO_HOME and two unrelated cwds."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Create the roots inside the test's temporary directory.

        Args:
            tmp_path (Path): The test's temporary directory.
        """
        self.schedules_dir: Path = tmp_path / "schedules"
        self.home: Path = tmp_path / "home"
        self.first_cwd: Path = tmp_path / "terminal-one"
        self.second_cwd: Path = tmp_path / "terminal-two"
        for directory in (self.home, self.first_cwd, self.second_cwd):
            directory.mkdir(parents=True)
        self.environment: dict[str, str] = cli_environment(
            schedules_dir=self.schedules_dir, slo_home=self.home
        )
        self.location: ScheduleWorkerLocationDAO = location_for(
            schedules_dir=self.schedules_dir, slo_home=self.home
        )

    def runtime(self, **tuning: Any) -> ScheduleWorkerRuntime:
        """Build a runtime for this test's location.

        Args:
            **tuning (Any): Constructor overrides (launcher, deadlines).

        Returns:
            ScheduleWorkerRuntime: The runtime.
        """
        return ScheduleWorkerRuntime(location=self.location, **tuning)

    def cli(self, *arguments: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
        """Run one CLI command as its own process.

        Args:
            *arguments (str): The arguments after ``slo``.
            cwd (Optional[Path]): The working directory; the first terminal by default.

        Returns:
            subprocess.CompletedProcess[str]: The finished command.
        """
        return run_cli(arguments=list(arguments), environment=self.environment, cwd=cwd or self.first_cwd)


def _add_json(
    *, roots: _Roots, name: str, cwd: Optional[Path] = None, extra: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Add one interval schedule through the CLI and return its parsed JSON.

    Args:
        roots (_Roots): The test roots.
        name (str): The schedule name.
        cwd (Optional[Path]): The working directory of the creating command.
        extra (tuple[str, ...]): Additional add flags.

    Returns:
        dict[str, Any]: The printed JSON object.
    """
    completed = roots.cli(
        "schedule",
        "add",
        "--name",
        name,
        "--prompt",
        "Summarise",
        "--interval-seconds",
        "3600",
        *extra,
        "--json",
        cwd=cwd,
    )
    assert completed.returncode == 0, completed.stderr
    return dict(json.loads(completed.stdout))


def _instant(value: str) -> datetime:
    """Parse one printed ISO instant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _health(*, roots: _Roots) -> ScheduleWorkerHealthDAO:
    """Observe the worker's health once."""
    return asyncio.run(roots.runtime().inspect_health())


def _schedule_rows(*, schedules_dir: Path) -> int:
    """Count every schedule row, deleted or not."""
    connection = sqlite3.connect(schedules_dir / "schedules.db")
    try:
        return int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
    finally:
        connection.close()


def _wait_for(*, predicate: Any, timeout_seconds: float, message: str) -> None:
    """Poll a synchronous predicate with a bound."""
    deadline: float = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(message)


# OPS111-01, OPS111-02, OPS111-07 -------------------------------------------------


def test_add_starts_one_healthy_shared_worker_that_later_commands_reuse(tmp_path: Path) -> None:
    """OPS111-01/02/07: add saves the schedule, starts a detached worker and
    proves it healthy; status from another terminal and a later start reuse
    the very same worker generation."""
    roots = _Roots(tmp_path=tmp_path)

    created: dict[str, Any] = _add_json(roots=roots, name="Daily Summary")

    assert created["name"] == "Daily Summary" and created["enabled"] is True
    assert created["next_due_at"] is not None
    assert created["operational"] is True
    assert created["worker"]["state"] == "healthy"
    launch_id: str = created["worker"]["launch_id"]
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == [created["worker"]["pid"]]

    status = roots.cli("schedule", "status", "--schedule", "Daily Summary", "--json", cwd=roots.second_cwd)
    assert status.returncode == 0, status.stderr
    observed: dict[str, Any] = json.loads(status.stdout)
    assert observed["worker"]["state"] == "healthy"
    assert observed["worker"]["launch_id"] == launch_id
    assert observed["schedule"]["id"] == created["id"]
    # The store keeps milliseconds; add prints the value before that rounding.
    assert abs(_instant(observed["next_due_at"]) - _instant(created["next_due_at"])).total_seconds() < 0.001

    assert roots.cli("schedule", "stop", "--schedule", created["id"], cwd=roots.second_cwd).returncode == 0
    restarted = roots.cli("schedule", "start", "--schedule", created["id"], "--json", cwd=roots.second_cwd)
    assert restarted.returncode == 0, restarted.stderr
    started: dict[str, Any] = json.loads(restarted.stdout)
    assert started["enabled"] is True and started["next_due_at"] is not None
    assert started["worker"]["state"] == "healthy"
    assert started["worker"]["launch_id"] == launch_id, "start reused the running worker"
    assert len(live_worker_pids(schedules_dir=roots.schedules_dir)) == 1

    text = roots.cli("schedule", "status")
    assert text.returncode == 0
    assert "Worker: healthy" in text.stdout
    assert "Next Due:" in text.stdout


def test_text_add_reports_the_operational_worker(tmp_path: Path) -> None:
    """OPS111-01: the text form keeps the schedule detail and adds the worker line."""
    roots = _Roots(tmp_path=tmp_path)

    completed = roots.cli("schedule", "add", "--name", "Text", "--prompt", "P", "--interval-seconds", "3600")

    assert completed.returncode == 0, completed.stderr
    lines: list[str] = completed.stdout.splitlines()
    UUID(lines[0].strip())
    assert "Name: Text" in completed.stdout and "Next Due:" in completed.stdout
    assert "Worker: healthy" in completed.stdout


def test_concurrent_creators_and_a_manual_worker_share_one_owner(tmp_path: Path) -> None:
    """OPS111-02: four creators in different terminals plus a manual worker,
    all started together, end with exactly one worker generation."""
    roots = _Roots(tmp_path=tmp_path)
    roots.schedules_dir.mkdir(parents=True)
    terminals: list[Path] = []
    for index in range(4):
        terminal = tmp_path / f"concurrent-{index}"
        terminal.mkdir()
        terminals.append(terminal)
    creators = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.cli",
                "schedule",
                "add",
                "--name",
                f"Concurrent {index}",
                "--prompt",
                "P",
                "--interval-seconds",
                "3600",
                "--json",
            ],
            cwd=terminal,
            env=roots.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index, terminal in enumerate(terminals)
    ]
    manual = subprocess.Popen(
        [sys.executable, "-m", "src.cli", "schedule", "worker"],
        cwd=roots.second_cwd,
        env=roots.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        outputs = [creator.communicate(timeout=120) for creator in creators]
        for creator, (stdout, stderr) in zip(creators, outputs):
            assert creator.returncode == 0, stderr
        launch_ids: set[str] = {json.loads(stdout)["worker"]["launch_id"] for stdout, _stderr in outputs}
        assert len(launch_ids) == 1, f"one worker generation, got {launch_ids}"
        assert len(live_worker_pids(schedules_dir=roots.schedules_dir)) == 1
        metadata = read_worker_metadata(schedules_dir=roots.schedules_dir)
        assert metadata is not None and metadata["launch_id"] in launch_ids
        if manual.poll() is not None:
            _out, manual_err = manual.communicate(timeout=10)
            assert manual.returncode == 1
            assert "already running" in manual_err
        else:
            assert metadata["pid"] == manual.pid, "the live manual worker is the one shared owner"
        assert _schedule_rows(schedules_dir=roots.schedules_dir) == 4
    finally:
        if manual.poll() is None:
            manual.terminate()
            manual.communicate(timeout=30)


def _open_paths(*, pid: int) -> set[str]:
    """Return the files one live process holds open (empty once it exited)."""
    paths: set[str] = set()
    with_fds: Path = Path(f"/proc/{pid}/fd")
    try:
        descriptors: list[Path] = list(with_fds.iterdir())
    except OSError:
        return paths
    for descriptor in descriptors:
        try:
            paths.add(os.readlink(descriptor))
        except OSError:
            continue
    return paths


def _start_manual_worker(*, roots: _Roots) -> subprocess.Popen[str]:
    """Start ``slo schedule worker`` in the foreground as an operator would."""
    return subprocess.Popen(
        [sys.executable, "-m", "src.cli", "schedule", "worker"],
        cwd=roots.second_cwd,
        env=roots.environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _await_manual_refusal(*, manual: subprocess.Popen[str]) -> str:
    """Wait (bounded) for a manual worker to give up on its own and return its stderr."""
    _stdout, stderr = manual.communicate(timeout=90)
    return stderr


def _stop_manual_worker(*, manual: subprocess.Popen[str]) -> str:
    """Stop a manual worker that still runs (SIGTERM) and return its stderr."""
    if manual.poll() is None:
        manual.terminate()
    _stdout, stderr = manual.communicate(timeout=60)
    return stderr


async def test_manual_worker_at_the_spawn_boundary_waits_and_never_owns_beside_the_launch(
    tmp_path: Path,
) -> None:
    """OPS111-02 (R02): a manual worker that arrives after the automatic
    start's last check and before its spawn waits at the shared startup
    admission instead of taking ownership; the one launch becomes the owner and
    the manual worker is refused."""
    roots = _Roots(tmp_path=tmp_path)
    roots.schedules_dir.mkdir(parents=True, mode=0o700)
    launch_lock: str = os.path.realpath(roots.schedules_dir / ".schedule-worker-launch.lock")
    lifetime_lock: str = os.path.realpath(roots.schedules_dir / ".schedule-worker.lock")
    arrived: list[subprocess.Popen[str]] = []

    def manual_arrives_at_the_boundary() -> None:
        manual = _start_manual_worker(roots=roots)
        arrived.append(manual)
        deadline: float = time.monotonic() + 60
        while launch_lock not in _open_paths(pid=manual.pid):
            assert lifetime_lock not in _open_paths(pid=manual.pid), "the manual worker took ownership"
            assert manual.poll() is None and time.monotonic() < deadline, "the manual worker never arrived"
            time.sleep(0.02)
        time.sleep(0.5)
        assert lifetime_lock not in _open_paths(pid=manual.pid), "it waits at startup admission"

    launcher = _RecordingLauncher(before_launch=manual_arrives_at_the_boundary)
    try:
        healthy: ScheduleWorkerHealthDAO = await roots.runtime(launcher=launcher).start_or_reuse()
        manual_stderr: str = await asyncio.to_thread(_await_manual_refusal, manual=arrived[0])
    finally:
        for manual in arrived:
            await asyncio.to_thread(_stop_manual_worker, manual=manual)

    assert launcher.launch_ids == [healthy.launch_id], "one launch attempt, and it is the owner"
    assert arrived[0].returncode == 1 and "already running" in manual_stderr
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == [healthy.pid]


def _schedule_service(*, roots: _Roots) -> ScheduleService:
    """Build one schedule service on the test's schedules database."""
    return ScheduleService(
        database=ScheduleDatabase(db_path=roots.schedules_dir / "schedules.db"),
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )


def _create_in_own_loop(
    *, roots: _Roots, launcher: _RecordingLauncher, barrier: threading.Barrier, new_schedule: NewScheduleDAO
) -> OperationalScheduleDAO:
    """Wait at the barrier, then create one schedule operationally in this thread's own loop."""

    async def create() -> OperationalScheduleDAO:
        service: ScheduleService = _schedule_service(roots=roots)
        try:
            return await CreateOperationalScheduleAppService(
                schedules=service,
                runtime=roots.runtime(launcher=launcher),
                new_schedule=new_schedule,
                now=datetime.now(timezone.utc),
            ).invoke()
        finally:
            await service.close()

    barrier.wait(timeout=60)
    return asyncio.run(create())


def _enable_in_own_loop(
    *, roots: _Roots, launcher: _RecordingLauncher, barrier: threading.Barrier, reference: str
) -> OperationalScheduleDAO:
    """Wait at the barrier, then enable one schedule operationally in this thread's own loop."""

    async def enable() -> OperationalScheduleDAO:
        service: ScheduleService = _schedule_service(roots=roots)
        try:
            return await StartOperationalScheduleAppService(
                schedules=service,
                runtime=roots.runtime(launcher=launcher),
                reference=reference,
                now=datetime.now(timezone.utc),
            ).invoke()
        finally:
            await service.close()

    barrier.wait(timeout=60)
    return asyncio.run(enable())


async def _concurrent_activations(
    *, roots: _Roots, launcher: _RecordingLauncher, names: list[str], references: list[str]
) -> list[OperationalScheduleDAO]:
    """Release creates and enables together, each in its own thread and event loop."""
    barrier = threading.Barrier(parties=len(names) + len(references))
    creates = [
        asyncio.to_thread(
            _create_in_own_loop,
            roots=roots,
            launcher=launcher,
            barrier=barrier,
            new_schedule=NewScheduleDAO(
                name=name,
                prompt="P",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
                session_reference=_SESSION_ID,
            ),
        )
        for name in names
    ]
    enables = [
        asyncio.to_thread(
            _enable_in_own_loop, roots=roots, launcher=launcher, barrier=barrier, reference=reference
        )
        for reference in references
    ]
    return list(await asyncio.gather(*creates, *enables))


async def test_concurrent_creates_enables_and_a_manual_worker_spawn_at_most_one_worker(
    tmp_path: Path,
) -> None:
    """OPS111-02 (R02): on an empty scope, creators and enables released
    together beside a starting manual worker make at most one launch attempt,
    and the one owner is the manual worker exactly when nothing was launched.
    On the occupied scope, repeated creates and starts launch nothing. The one
    owner delivers a trigger exactly once."""
    roots = _Roots(tmp_path=tmp_path)
    gateway = await _closed_durable_session(roots=roots)
    service: ScheduleService = _schedule_service(roots=roots)
    try:
        paused: list[str] = []
        for name in ("Paused one", "Paused two"):
            created = await service.create(
                new_schedule=NewScheduleDAO(
                    name=name, prompt="P", trigger=IntervalTriggerDAO(every_seconds=3600)
                ),
                now=datetime.now(timezone.utc),
            )
            await service.stop(reference=str(created.id), now=datetime.now(timezone.utc))
            paused.append(str(created.id))
    finally:
        await service.close()
    manual = _start_manual_worker(roots=roots)
    try:
        empty_scope = _RecordingLauncher()
        first = await _concurrent_activations(
            roots=roots,
            launcher=empty_scope,
            names=["Create one", "Create two", "Create three"],
            references=paused,
        )
        owners: set[Optional[str]] = {result.worker.launch_id for result in first}
        assert len(owners) == 1 and all(result.worker.is_healthy for result in first)
        metadata = read_worker_metadata(schedules_dir=roots.schedules_dir)
        assert metadata is not None and metadata["launch_id"] in owners
        manual_owns: bool = metadata["pid"] == manual.pid
        assert len(empty_scope.launch_ids) == (0 if manual_owns else 1), empty_scope.launch_ids
        assert manual_owns or empty_scope.launch_ids == list(owners)
        if not manual_owns:
            refusal: str = await asyncio.to_thread(_await_manual_refusal, manual=manual)
            assert manual.returncode == 1 and "already running" in refusal

        occupied_scope = _RecordingLauncher()
        second = await _concurrent_activations(
            roots=roots, launcher=occupied_scope, names=["Create four", "Create five"], references=paused
        )
        assert occupied_scope.launch_ids == [], "a healthy owner is reused, never joined"
        assert {result.worker.launch_id for result in second} == owners
        assert len(live_worker_pids(schedules_dir=roots.schedules_dir)) == 1
        assert _schedule_rows(schedules_dir=roots.schedules_dir) == 7

        triggered = await asyncio.to_thread(roots.cli, "schedule", "trigger", "--schedule", "Create one")
        assert triggered.returncode == 0, triggered.stderr
        participant: UUID = channel_participant_id_for_session(session_id=_SESSION_ID)
        async with asyncio.timeout(60):
            while not await gateway.pending_inbound(recipient_id=participant):
                await asyncio.sleep(0.2)
        await asyncio.sleep(1.0)
        assert [row.id for row in await gateway.pending_inbound(recipient_id=participant)] == [
            UUID(triggered.stdout.strip())
        ], "delivered exactly once"
    finally:
        await asyncio.to_thread(_stop_manual_worker, manual=manual)
        await gateway.close()


def test_independent_homes_started_together_each_get_their_own_single_worker(tmp_path: Path) -> None:
    """OPS111-02 (R02): two isolated homes created concurrently each end with
    one healthy worker of their own; neither reuses nor blocks the other."""
    homes: list[_Roots] = [_Roots(tmp_path=tmp_path / "home-a"), _Roots(tmp_path=tmp_path / "home-b")]
    creators: list[tuple[_Roots, subprocess.Popen[str]]] = [
        (
            roots,
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.cli",
                    "schedule",
                    "add",
                    "--name",
                    f"Home {index}",
                    "--prompt",
                    "P",
                    "--interval-seconds",
                    "3600",
                    "--json",
                ],
                cwd=roots.first_cwd,
                env=roots.environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ),
        )
        for roots in homes
        for index in range(2)
    ]
    launch_ids: dict[Path, set[str]] = {roots.schedules_dir: set() for roots in homes}
    for roots, creator in creators:
        stdout, stderr = creator.communicate(timeout=120)
        assert creator.returncode == 0, stderr
        launch_ids[roots.schedules_dir].add(json.loads(stdout)["worker"]["launch_id"])

    assert all(len(ids) == 1 for ids in launch_ids.values()), launch_ids
    assert launch_ids[homes[0].schedules_dir].isdisjoint(launch_ids[homes[1].schedules_dir])
    for roots in homes:
        assert len(live_worker_pids(schedules_dir=roots.schedules_dir)) == 1
        status = json.loads(roots.cli("schedule", "status", "--json").stdout)
        assert {status["worker"]["launch_id"]} == launch_ids[roots.schedules_dir]


def test_manual_worker_is_refused_while_the_shared_worker_runs(tmp_path: Path) -> None:
    """OPS111-02: the foreground worker uses the same admission; it never runs beside the shared one."""
    roots = _Roots(tmp_path=tmp_path)
    _add_json(roots=roots, name="Shared")

    manual = roots.cli("schedule", "worker", cwd=roots.second_cwd)

    assert manual.returncode == 1
    assert "already running" in manual.stderr
    assert "slo schedule status" in manual.stderr
    assert len(live_worker_pids(schedules_dir=roots.schedules_dir)) == 1


# OPS111-04, OPS111-08 -------------------------------------------------------------


async def test_worker_survives_its_creator_and_queues_for_a_closed_session_until_it_reopens(
    tmp_path: Path,
) -> None:
    """OPS111-04/08: the creating terminal exits, the detached worker keeps
    running, delivers the due prompt into the closed session's durable inbox
    without a headless run, and the reopened session accepts it once."""
    from langchain_core.messages import AIMessage

    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
    from src.agents.slo_agent.channel_delivery.poller import ChannelPoller, channel_participant_id_for_session
    from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.channels.gateway import ChannelGateway
    from src.channels.repository import ChannelRepository
    from tests.schedules.test_closed_session_delivery import RecordingTurnRunner

    roots = _Roots(tmp_path=tmp_path)
    channels_db: Path = roots.home / "channels" / "channels.db"
    gateway = ChannelGateway(repository=ChannelRepository(db_path=channels_db))
    await gateway.open()
    try:
        await gateway.register_agent(session_id=UUID(_SESSION_ID), name="target", durable_inbox=True)
        await gateway.close_agent(session_id=UUID(_SESSION_ID), reason="session_closed")

        terminal = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "src.cli",
            "schedule",
            "add",
            "--name",
            "Closed target",
            "--prompt",
            "queued prompt",
            "--interval-seconds",
            "3600",
            "--session-mode",
            "continuous",
            "--session-reference",
            _SESSION_ID,
            "--json",
            cwd=roots.first_cwd,
            env=roots.environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = await asyncio.wait_for(terminal.communicate(), timeout=120)
        assert terminal.returncode == 0, stderr.decode()
        created: dict[str, Any] = json.loads(stdout)
        worker_pid: int = created["worker"]["pid"]
        assert worker_pid != terminal.pid
        assert os.getsid(worker_pid) == worker_pid, "the worker leads its own session"

        triggered = await asyncio.to_thread(roots.cli, "schedule", "trigger", "--schedule", "Closed target")
        assert triggered.returncode == 0, triggered.stderr
        invocation_id = UUID(triggered.stdout.strip())

        participant = channel_participant_id_for_session(session_id=_SESSION_ID)
        async with asyncio.timeout(60):
            while not await gateway.pending_inbound(recipient_id=participant):
                await asyncio.sleep(0.2)
        pending = await gateway.pending_inbound(recipient_id=participant)
        assert [row.id for row in pending] == [invocation_id]
        assert pending[0].accepted_at is None
        assert (await asyncio.to_thread(_health, roots=roots)).state == "healthy"

        schedules_db = ScheduleDatabase(db_path=roots.schedules_dir / "schedules.db")
        try:
            async with schedules_db.transaction() as transaction:
                stored = await ScheduleInvocationRepository().get(
                    invocation_id=invocation_id, transaction=transaction
                )
        finally:
            await schedules_db.close()
        assert stored is not None and stored.status == "delivered"
        assert stored.recipient_session_id == _SESSION_ID, "no headless fresh session was minted"

        await gateway.register_agent(session_id=UUID(_SESSION_ID), name="target", durable_inbox=True)
        session = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
            ),
            workdir=tmp_path,
            session_id=_SESSION_ID,
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        runner = RecordingTurnRunner()
        poller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=participant),
            interval=0.02,
        )
        await poller.start()
        try:
            async with asyncio.timeout(10):
                while len(runner.ran) < 1:
                    await asyncio.sleep(0.02)
            await asyncio.sleep(0.3)
        finally:
            await poller.stop(reason="test finished")
        assert runner.ran == [invocation_id], "accepted exactly once on reopening"
        assert await gateway.pending_inbound(recipient_id=participant) == []
    finally:
        await gateway.close()


# OPS111-03, OPS111-05 -------------------------------------------------------------


async def test_stalled_worker_is_unresponsive_and_never_replaced(tmp_path: Path) -> None:
    """OPS111-03/05: a live owner that stops answering is reported
    unresponsive; start fails explicitly without launching a competitor and
    the worker is healthy again once it resumes."""
    roots = _Roots(tmp_path=tmp_path)
    runtime = roots.runtime(probe_timeout_seconds=0.5)
    healthy: ScheduleWorkerHealthDAO = await runtime.start_or_reuse()
    assert healthy.state == "healthy" and healthy.pid is not None

    os.kill(healthy.pid, signal.SIGSTOP)
    try:
        stalled = await runtime.inspect_health()
        assert stalled.state == "unresponsive"
        assert stalled.launch_id == healthy.launch_id
        with pytest.raises(ScheduleWorkerUnavailableError) as refused:
            await runtime.start_or_reuse()
        assert refused.value.health.state == "unresponsive"
        assert live_worker_pids(schedules_dir=roots.schedules_dir) == [healthy.pid]
        metadata = read_worker_metadata(schedules_dir=roots.schedules_dir)
        assert metadata is not None and metadata["launch_id"] == healthy.launch_id
    finally:
        os.kill(healthy.pid, signal.SIGCONT)
    resumed = await runtime.inspect_health()
    assert resumed.state == "healthy" and resumed.launch_id == healthy.launch_id


async def test_killed_worker_is_reported_stopped_and_restarted_without_waiting_for_its_engine_locks(
    tmp_path: Path,
) -> None:
    """OPS111-05: a SIGKILLed worker leaves stale metadata and an unexpired
    engine leader lock; status reports it stopped and the next start launches
    a new generation within the startup deadline."""
    roots = _Roots(tmp_path=tmp_path)
    runtime = roots.runtime()
    first = await runtime.start_or_reuse()
    assert first.pid is not None
    os.kill(first.pid, signal.SIGKILL)
    _wait_for(
        predicate=lambda: not live_worker_pids(schedules_dir=roots.schedules_dir),
        timeout_seconds=10,
        message="the killed worker never exited",
    )

    stopped = await runtime.inspect_health()
    assert stopped.state == "stopped"
    assert (
        read_worker_metadata(schedules_dir=roots.schedules_dir) is not None
    ), "stale metadata stays until cleanup"

    started_at = time.monotonic()
    second = await runtime.start_or_reuse()
    assert second.state == "healthy"
    assert second.launch_id != first.launch_id
    assert time.monotonic() - started_at < 30, "a dead predecessor's leader lock does not delay the restart"
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == [second.pid]


async def test_stale_metadata_naming_a_live_unrelated_process_is_cleaned_without_signalling_it(
    tmp_path: Path,
) -> None:
    """OPS111-05: PID reuse — the metadata names a live process that is not a
    worker and holds no lifetime lock; it is never signalled and a new worker starts."""
    roots = _Roots(tmp_path=tmp_path)
    roots.schedules_dir.mkdir(parents=True, mode=0o700)
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        (roots.schedules_dir / ".schedule-worker.json").write_text(
            json.dumps(
                {"launch_id": "stale", "pid": bystander.pid, "schedules_dir": str(roots.schedules_dir)}
            ),
            encoding="utf-8",
        )
        (roots.schedules_dir / ".schedule-worker.lock").touch()
        stopped = await roots.runtime().inspect_health()
        assert stopped.state == "stopped"

        started = await roots.runtime().start_or_reuse()

        assert started.state == "healthy" and started.launch_id != "stale"
        assert bystander.poll() is None, "the unrelated process was never signalled"
    finally:
        bystander.kill()
        bystander.wait(timeout=10)


async def test_worker_serving_a_different_channel_store_is_blocked_not_reused(tmp_path: Path) -> None:
    """OPS111-03: a healthy worker for this schedules directory that routes to
    another channel store is refused, and no second worker starts."""
    roots = _Roots(tmp_path=tmp_path)
    created = _add_json(roots=roots, name="Home A")
    other_home = tmp_path / "other-home"
    other_home.mkdir()
    mismatched = ScheduleWorkerRuntime(
        location=location_for(schedules_dir=roots.schedules_dir, slo_home=other_home)
    )

    observed = await mismatched.inspect_health()

    assert observed.state == "blocked"
    assert observed.reason is not None and "different" in observed.reason
    with pytest.raises(ScheduleWorkerUnavailableError):
        await mismatched.start_or_reuse()
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == [created["worker"]["pid"]]


class _NeverHealthyLauncher:
    """Launch seam substitute: a real child process that never answers health."""

    def __init__(self) -> None:
        """Start with no child."""
        self.children: list[subprocess.Popen[bytes]] = []

    def launch(self, *, launch_id: str, location: ScheduleWorkerLocationDAO) -> subprocess.Popen[bytes]:
        """Start a sleeping child that ignores SIGTERM, so the reap must escalate.

        Args:
            launch_id (str): The generation id (unused by the child).
            location (ScheduleWorkerLocationDAO): The worker location.

        Returns:
            subprocess.Popen[bytes]: The child.
        """
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)",
            ],
            start_new_session=True,
        )
        self.children.append(child)
        return child


class _FailingLauncher:
    """Launch seam substitute: the installation cannot start a worker at all."""

    def launch(self, *, launch_id: str, location: ScheduleWorkerLocationDAO) -> subprocess.Popen[bytes]:
        """Fail like an installation without a resolvable `slo` executable."""
        raise FileNotFoundError("Could not resolve the slo executable.")


async def test_startup_deadline_reaps_only_the_unadopted_child(tmp_path: Path) -> None:
    """OPS111-05: a child that never becomes healthy is reaped (escalating to
    SIGKILL) when the startup deadline passes; nothing is left running."""
    roots = _Roots(tmp_path=tmp_path)
    launcher = _NeverHealthyLauncher()

    with pytest.raises(ScheduleWorkerUnavailableError) as failed:
        await roots.runtime(launcher=launcher, startup_timeout_seconds=1.0).start_or_reuse()

    assert "did not become healthy" in (failed.value.health.reason or "")
    assert [child.poll() is not None for child in launcher.children] == [True]


async def test_cancelled_launch_reaps_the_child_even_when_cancelled_again(tmp_path: Path) -> None:
    """OPS111-05: cancelling the creator while it waits (twice) reaps the just-launched child."""
    roots = _Roots(tmp_path=tmp_path)
    launcher = _NeverHealthyLauncher()
    starting = asyncio.create_task(roots.runtime(launcher=launcher).start_or_reuse())
    async with asyncio.timeout(10):
        while not launcher.children:
            await asyncio.sleep(0.02)

    starting.cancel()
    await asyncio.sleep(0)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting

    assert launcher.children[0].poll() is not None


async def test_cancelled_reuse_never_stops_the_healthy_shared_worker(tmp_path: Path) -> None:
    """OPS111-05: only an unadopted child is ever reaped; cancelling a reuse leaves the worker running."""
    roots = _Roots(tmp_path=tmp_path)
    healthy = await roots.runtime().start_or_reuse()
    for _attempt in range(5):
        reuse = asyncio.create_task(roots.runtime().start_or_reuse())
        await asyncio.sleep(0)
        reuse.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reuse
    assert (await roots.runtime().inspect_health()).launch_id == healthy.launch_id


async def test_retire_stops_only_its_generation_and_keeps_every_store(tmp_path: Path) -> None:
    """OPS111-05/11: graceful retirement removes the worker's own metadata and
    socket, releases the lock and leaves schedules and engine data untouched."""
    roots = _Roots(tmp_path=tmp_path)
    _add_json(roots=roots, name="Kept")

    await roots.runtime().retire()

    _wait_for(
        predicate=lambda: not live_worker_pids(schedules_dir=roots.schedules_dir),
        timeout_seconds=20,
        message="the retired worker never exited",
    )
    names: set[str] = {entry.name for entry in roots.schedules_dir.iterdir()}
    assert ".schedule-worker.json" not in names and ".schedule-worker.sock" not in names
    assert {"schedules.db", ".schedule-engine.db", ".schedule-worker.lock"} <= names
    assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1
    assert (await roots.runtime().inspect_health()).state == "stopped"


async def test_worker_retires_itself_when_its_lifetime_lock_file_disappears(tmp_path: Path) -> None:
    """A removed schedules directory never keeps an orphaned worker alive."""
    roots = _Roots(tmp_path=tmp_path)
    healthy = await roots.runtime().start_or_reuse()

    (roots.schedules_dir / ".schedule-worker.lock").unlink()

    _wait_for(
        predicate=lambda: healthy.pid not in live_worker_pids(schedules_dir=roots.schedules_dir),
        timeout_seconds=20,
        message="the worker kept running without its lock file",
    )


# OPS111-06, OPS111-09 -------------------------------------------------------------

_PRIOR_HIDDEN_ENGINE_WORKER: str = """
import sys
import honker
db = honker.open(sys.argv[1])
db.queue("prior-queue").enqueue({"kept": True})
leader = db.lock("honker-scheduler", ttl=60)
leader.__enter__()
delivery = db.lock("schedule-prior", ttl=60)
delivery.__enter__()
print("held", flush=True)
sys.stdin.read()
delivery.__exit__(None, None, None)
leader.__exit__(None, None, None)
db.close()
"""
"""The previous build's worker as it ran: engine state in the hidden engine file,
its leader and a delivery lock held there, and no worker lifetime lock at all."""


class _RecordingLauncher:
    """Launch seam wrapper: records every launch attempt, then launches the real detached worker."""

    def __init__(self, *, before_launch: Optional[Callable[[], None]] = None) -> None:
        """Start with no attempts.

        Args:
            before_launch (Optional[Callable[[], None]]): Runs at the spawn
                boundary, after the runtime's last check and before the spawn.
        """
        self.launch_ids: list[str] = []
        self._attempts_lock: threading.Lock = threading.Lock()
        self._before_launch: Optional[Callable[[], None]] = before_launch
        self._real: SubprocessScheduleWorkerLauncher = SubprocessScheduleWorkerLauncher()

    def launch(self, *, launch_id: str, location: ScheduleWorkerLocationDAO) -> subprocess.Popen[bytes]:
        """Record the attempt, run the boundary hook, then launch for real.

        Args:
            launch_id (str): The generation id.
            location (ScheduleWorkerLocationDAO): The worker location.

        Returns:
            subprocess.Popen[bytes]: The real detached worker.
        """
        with self._attempts_lock:
            self.launch_ids.append(launch_id)
        if self._before_launch is not None:
            self._before_launch()
        return self._real.launch(launch_id=launch_id, location=location)


async def _closed_durable_session(*, roots: _Roots) -> ChannelGateway:
    """Register the target session's durable inbox and close it, as a closed terminal leaves it.

    Args:
        roots (_Roots): The test roots.

    Returns:
        ChannelGateway: The open gateway over the test's channel store; the caller closes it.
    """
    gateway = ChannelGateway(repository=ChannelRepository(db_path=roots.home / "channels" / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="target", durable_inbox=True)
    await gateway.close_agent(session_id=UUID(_SESSION_ID), reason="session_closed")
    return gateway


def _engine_locks(*, schedules_dir: Path) -> list[tuple[str, str, int]]:
    """Read the hidden engine file's lock rows read-only (this process never opens honker on it)."""
    connection = sqlite3.connect(f"file:{schedules_dir / '.schedule-engine.db'}?mode=ro", uri=True)
    try:
        return [
            (str(name), str(owner), int(expires_at))
            for name, owner, expires_at in connection.execute(
                "SELECT name, owner, expires_at FROM _honker_locks ORDER BY name"
            )
        ]
    finally:
        connection.close()


def _engine_queue_rows(*, schedules_dir: Path, queue: str) -> int:
    """Count the hidden engine file's live jobs of one queue, read-only."""
    connection = sqlite3.connect(f"file:{schedules_dir / '.schedule-engine.db'}?mode=ro", uri=True)
    try:
        return int(
            connection.execute("SELECT count(*) FROM _honker_live WHERE queue = ?", (queue,)).fetchone()[0]
        )
    finally:
        connection.close()


async def test_prior_hidden_engine_worker_is_never_joined_or_robbed_until_confirmed_stopped(
    tmp_path: Path,
) -> None:
    """OPS111-09 (R01): a running worker of the previous build holds its locks
    in the hidden engine file but no lifetime lock. add and start keep the
    schedule saved but do not launch a competitor or touch its locks, and even
    a confirmed manual start is refused while its locks are visible. Once it
    stopped, start still needs the procedural confirmation; the confirmed
    worker keeps every row, does work, and later starts need nothing."""
    roots = _Roots(tmp_path=tmp_path)
    roots.schedules_dir.mkdir(parents=True, mode=0o700)
    gateway = await _closed_durable_session(roots=roots)
    prior = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            _PRIOR_HIDDEN_ENGINE_WORKER,
            str(roots.schedules_dir / ".schedule-engine.db"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert prior.stdout is not None and prior.stdout.readline().strip() == "held"
        held_locks = _engine_locks(schedules_dir=roots.schedules_dir)
        assert [name for name, _owner, _expiry in held_locks] == ["honker-scheduler", "schedule-prior"]

        added = roots.cli(
            "schedule",
            "add",
            "--name",
            "Upgrade",
            "--prompt",
            "P",
            "--interval-seconds",
            "3600",
            "--session-mode",
            "continuous",
            "--session-reference",
            _SESSION_ID,
            "--json",
        )
        assert added.returncode == 1, added.stderr
        reported: dict[str, Any] = json.loads(added.stdout)
        assert reported["operational"] is False and reported["worker"]["state"] == "blocked"
        assert "earlier version is still running" in reported["worker"]["reason"]
        launcher = _RecordingLauncher()
        with pytest.raises(ScheduleWorkerUnavailableError) as refused:
            await roots.runtime(launcher=launcher).start_or_reuse()
        assert refused.value.health.state == "blocked"
        assert launcher.launch_ids == [], "no competitor was spawned"
        confirmed_beside_it = roots.cli("schedule", "worker", "--earlier-workers-stopped")
        assert confirmed_beside_it.returncode == 1
        assert "earlier version is still running" in confirmed_beside_it.stderr
        assert _engine_locks(schedules_dir=roots.schedules_dir) == held_locks, "its locks were never erased"
        assert prior.poll() is None and live_worker_pids(schedules_dir=roots.schedules_dir) == []
        assert not (roots.schedules_dir / ".schedule-worker.log").exists()
    finally:
        assert prior.stdin is not None
        prior.stdin.close()
        prior.wait(timeout=30)

    unconfirmed = roots.cli("schedule", "start", "--schedule", reported["id"])
    assert unconfirmed.returncode == 1
    assert "--earlier-workers-stopped" in unconfirmed.stderr, "missing locks never prove it stopped"
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == []

    manual = subprocess.Popen(
        [sys.executable, "-m", "src.cli", "schedule", "worker", "--earlier-workers-stopped"],
        cwd=roots.second_cwd,
        env=roots.environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        async with asyncio.timeout(60):
            while not (await roots.runtime().inspect_health()).is_healthy:
                await asyncio.sleep(0.2)
        started = roots.cli("schedule", "start", "--schedule", reported["id"], "--json")
        assert started.returncode == 0, started.stderr
        assert json.loads(started.stdout)["worker"]["pid"] == manual.pid, "start reused the confirmed worker"
        assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1
        assert _engine_queue_rows(schedules_dir=roots.schedules_dir, queue="prior-queue") == 1
        triggered = roots.cli("schedule", "trigger", "--schedule", reported["id"])
        assert triggered.returncode == 0, triggered.stderr
        participant: UUID = channel_participant_id_for_session(session_id=_SESSION_ID)
        async with asyncio.timeout(60):
            while not await gateway.pending_inbound(recipient_id=participant):
                await asyncio.sleep(0.2)
        assert [row.id for row in await gateway.pending_inbound(recipient_id=participant)] == [
            UUID(triggered.stdout.strip())
        ], "the confirmed worker delivered the work exactly once"
    finally:
        manual.terminate()
        manual.communicate(timeout=30)
        await gateway.close()
    assert manual.returncode == 0

    later = roots.cli("schedule", "start", "--schedule", reported["id"], "--json")
    assert later.returncode == 0, later.stderr
    assert json.loads(later.stdout)["worker"]["state"] == "healthy", "the admission is durable"


def _write_earlier_layout(*, schedules_dir: Path, held_lock: bool) -> None:
    """Give schedules.db the earlier development layout's engine tables.

    Args:
        schedules_dir (Path): The schedules directory.
        held_lock (bool): Also record an unexpired earlier-layout lock.
    """
    schedules_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(schedules_dir / "schedules.db")
    try:
        connection.execute(
            "CREATE TABLE _honker_locks (name TEXT PRIMARY KEY, owner TEXT, expires_at INTEGER)"
        )
        if held_lock:
            connection.execute(
                "INSERT INTO _honker_locks VALUES ('honker-scheduler', 'earlier', ?)",
                (int(time.time()) + 3600,),
            )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("held_lock", "expected_cause"),
    [(False, "--earlier-workers-stopped"), (True, "earlier version is still running")],
)
def test_add_beside_an_unadmitted_upgrade_is_saved_but_not_operational(
    tmp_path: Path, held_lock: bool, expected_cause: str
) -> None:
    """OPS111-06/09: automatic startup never bypasses upgrade admission. The
    schedule is saved once, both output forms say it is not operational with
    the cause and the id, the exit is 1, no engine file is created, and a
    retry through start reports the same blocker without a second row."""
    roots = _Roots(tmp_path=tmp_path)
    _write_earlier_layout(schedules_dir=roots.schedules_dir, held_lock=held_lock)

    as_json = roots.cli(
        "schedule", "add", "--name", "Blocked", "--prompt", "P", "--interval-seconds", "3600", "--json"
    )

    assert as_json.returncode == 1
    reported: dict[str, Any] = json.loads(as_json.stdout)
    assert reported["operational"] is False
    assert reported["error"].startswith("schedule saved, but not operational")
    assert expected_cause in reported["worker"]["reason"]
    assert reported["worker"]["state"] in {"stopped", "blocked"}
    assert "schedule saved, but not operational" in as_json.stderr
    assert reported["id"] in as_json.stderr
    assert not (roots.schedules_dir / ".schedule-engine.db").exists()
    assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1

    retried = roots.cli("schedule", "start", "--schedule", reported["id"])
    assert retried.returncode == 1
    assert "schedule saved, but not operational" in retried.stderr
    assert expected_cause in retried.stderr
    assert reported["id"] in retried.stderr
    assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1
    assert not (roots.schedules_dir / ".schedule-engine.db").exists()
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == []
    assert "--earlier-workers-stopped" not in " ".join(
        open(f"/proc/{os.getpid()}/cmdline", "rb").read().decode().split("\0")
    )


async def test_failed_launch_keeps_the_committed_schedule_and_its_id(tmp_path: Path) -> None:
    """OPS111-06: the definition is committed before activation; a launch
    failure is a typed partial success carrying the saved schedule."""
    roots = _Roots(tmp_path=tmp_path)
    database = ScheduleDatabase(db_path=roots.schedules_dir / "schedules.db")
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        with pytest.raises(ScheduleNotOperationalError) as partial:
            await CreateOperationalScheduleAppService(
                schedules=service,
                runtime=roots.runtime(launcher=_FailingLauncher()),
                new_schedule=NewScheduleDAO(
                    name="Saved", prompt="P", trigger=IntervalTriggerDAO(every_seconds=3600)
                ),
                now=datetime.now(timezone.utc),
            ).invoke()
        saved = partial.value.schedule
        assert (await service.show(reference=str(saved.id))).id == saved.id
        assert "Could not resolve the slo executable" in (partial.value.health.reason or "")
    finally:
        await service.close()


def _make_control_path_unusable(*, schedules_dir: Path, kind: str, decoy: Path) -> Path:
    """Plant an unusable worker control path that no command may follow or replace.

    Args:
        schedules_dir (Path): The schedules directory.
        kind (str): ``launch-lock-symlink`` or ``lifetime-lock-directory``.
        decoy (Path): A file a followed symlink would reach; it must stay untouched.

    Returns:
        Path: The planted path, removed later to recover.
    """
    if kind == "launch-lock-symlink":
        planted: Path = schedules_dir / ".schedule-worker-launch.lock"
        planted.symlink_to(decoy)
        return planted
    planted = schedules_dir / ".schedule-worker.lock"
    planted.mkdir()
    return planted


@pytest.mark.parametrize(
    ("kind", "as_json"), [("launch-lock-symlink", True), ("lifetime-lock-directory", False)]
)
def test_unusable_worker_control_path_leaves_the_schedule_saved_but_not_operational(
    tmp_path: Path, kind: str, as_json: bool
) -> None:
    """OPS111-06 (R04): a control path the runtime cannot use is a typed
    partial success, never a raw traceback. The row is committed once, the
    saved id and the cause are reported, the exit is 1, nothing is spawned or
    followed, status reports blocked, and recovery is start, not a second add."""
    roots = _Roots(tmp_path=tmp_path)
    roots.schedules_dir.mkdir(parents=True, mode=0o700)
    decoy: Path = tmp_path / "decoy"
    decoy.write_text("untouched", encoding="utf-8")
    planted: Path = _make_control_path_unusable(schedules_dir=roots.schedules_dir, kind=kind, decoy=decoy)

    added = roots.cli(
        "schedule",
        "add",
        "--name",
        "Unusable",
        "--prompt",
        "P",
        "--interval-seconds",
        "3600",
        *(["--json"] if as_json else []),
    )

    assert added.returncode == 1, added.stderr
    assert "Traceback" not in added.stderr
    assert "schedule saved, but not operational" in added.stderr
    if as_json:
        reported: dict[str, Any] = json.loads(added.stdout)
        saved_id: str = reported["id"]
        assert reported["operational"] is False
        assert reported["worker"]["state"] == "blocked"
        assert "unusable" in reported["worker"]["reason"]
    else:
        saved_id = added.stdout.splitlines()[0].strip()
        assert "Worker: blocked" in added.stdout and "unusable" in added.stdout
    assert saved_id in added.stderr and f"slo schedule start --schedule {saved_id}" in added.stderr
    assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == []
    assert not (roots.schedules_dir / ".schedule-worker.log").exists(), "no worker was launched"
    assert decoy.read_text(encoding="utf-8") == "untouched"

    observed = roots.cli("schedule", "status", "--json")
    assert observed.returncode == 1 and "Traceback" not in observed.stderr
    if kind == "lifetime-lock-directory":
        assert json.loads(observed.stdout)["worker"]["state"] == "blocked"

    planted.unlink() if planted.is_symlink() else planted.rmdir()
    recovered = roots.cli("schedule", "start", "--schedule", saved_id, "--json")
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["worker"]["state"] == "healthy"
    assert _schedule_rows(schedules_dir=roots.schedules_dir) == 1


# OPS111-07, OPS111-11 -------------------------------------------------------------


def test_status_observes_without_starting_a_worker_or_creating_files(tmp_path: Path) -> None:
    """OPS111-07: status on an untouched directory reports stopped, exits 1
    and creates nothing; an unknown schedule is a clean domain failure."""
    roots = _Roots(tmp_path=tmp_path)

    observed = roots.cli("schedule", "status", "--json")

    assert observed.returncode == 1
    reported: dict[str, Any] = json.loads(observed.stdout)
    assert reported["worker"]["state"] == "stopped"
    assert reported["schedule"] is None and reported["next_due_at"] is None
    assert not roots.schedules_dir.exists()
    unknown = roots.cli("schedule", "status", "--schedule", "ghost")
    assert unknown.returncode == 1
    assert "No active schedule" in unknown.stderr
    assert live_worker_pids(schedules_dir=roots.schedules_dir) == []


def test_status_of_a_disabled_schedule_shows_no_next_due_while_the_worker_stays_healthy(
    tmp_path: Path,
) -> None:
    """OPS111-07: health is about the worker; a disabled schedule has no next due."""
    roots = _Roots(tmp_path=tmp_path)
    created = _add_json(roots=roots, name="Paused")
    assert roots.cli("schedule", "stop", "--schedule", "Paused").returncode == 0

    observed = roots.cli("schedule", "status", "--schedule", "Paused", "--json")

    assert observed.returncode == 0, observed.stderr
    reported: dict[str, Any] = json.loads(observed.stdout)
    assert reported["worker"]["state"] == "healthy"
    assert reported["schedule"]["id"] == created["id"]
    assert reported["schedule"]["enabled"] is False
    assert reported["next_due_at"] is None


def test_operator_output_never_names_internal_engine_or_worker_files(tmp_path: Path) -> None:
    """OPS111-11: hidden engine and worker control files stay out of normal output."""
    roots = _Roots(tmp_path=tmp_path)
    created = _add_json(roots=roots, name="Quiet")
    outputs: list[str] = [json.dumps(created)]
    for arguments in (
        ("schedule", "list"),
        ("schedule", "show", "--schedule", "Quiet"),
        ("schedule", "status"),
        ("schedule", "status", "--json"),
        ("schedule", "report", "--schedule", "Quiet"),
    ):
        completed = roots.cli(*arguments)
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout + completed.stderr)
    for output in outputs:
        assert ".schedule-engine" not in output
        assert ".schedule-worker" not in output


# Engine readiness ------------------------------------------------------------------


async def test_engine_run_stops_and_reports_not_ready_when_a_loop_fails(tmp_path: Path) -> None:
    """A failed scheduler loop (leader lock held elsewhere) ends the whole run
    promptly with that error and the engine is never reported ready."""
    import honker

    from src.schedules.workflows import ScheduleEngine

    engine = ScheduleEngine(db_path=tmp_path / "schedules.db", channel_db_path=tmp_path / "channels.db")
    engine.open()
    try:
        foreign = honker.open(str(engine.engine_db_path))
        held = foreign.lock("honker-scheduler", ttl=600)
        held.__enter__()
        try:
            with pytest.raises(honker.LockHeld):
                await asyncio.wait_for(engine.run(stop_event=asyncio.Event()), timeout=20)
            assert engine.readiness().ready is False
        finally:
            held.__exit__(None, None, None)
            foreign.close()
    finally:
        engine.close()


async def test_engine_readiness_needs_leadership_and_recent_tick_progress(tmp_path: Path) -> None:
    """OPS111-03 (R03): the engine is ready only while it leads and its ticks
    progress. Starting before its loops run, ready as soon as it leads (no tick
    needed within the progress limit), stalled once no tick finished within
    the limit although both loops still run, ready again after a tick, and
    retiring once asked to stop."""
    from src.schedules.workflows import ScheduleEngine

    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        progress_limit_seconds=1.0,
    )
    assert engine.readiness().phase == "starting"
    engine.open()
    stop_event = asyncio.Event()
    running = asyncio.create_task(engine.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(20):
            while engine.readiness().phase != "ready":
                await asyncio.sleep(0.02)
        async with asyncio.timeout(30):
            while engine.readiness().phase != "stalled":
                await asyncio.sleep(0.05)
        stalled = engine.readiness()
        assert not running.done(), "both loops still run; only progress stopped"
        assert stalled.reason is not None and "tick" in stalled.reason
        await engine.tick_once()
        assert engine.readiness().phase == "ready"
        stop_event.set()
        assert engine.readiness().phase == "retiring"
        await asyncio.wait_for(running, timeout=20)
    finally:
        stop_event.set()
        if not running.done():
            await asyncio.wait_for(running, timeout=20)
        engine.close()


def _start_tuned_worker(
    *, roots: _Roots, progress_limit_seconds: float, fresh_run_seconds: float
) -> subprocess.Popen[str]:
    """Start a real foreground worker with a one-second tick and a test-sized progress limit.

    Args:
        roots (_Roots): The test roots.
        progress_limit_seconds (float): The engine's tick progress limit.
        fresh_run_seconds (float): How long each fresh-run child runs.

    Returns:
        subprocess.Popen[str]: The worker process.
    """
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            TUNED_WORKER_MODULE,
            "schedule",
            "worker",
            str(roots.schedules_dir),
            str(roots.home),
            "1",
            str(progress_limit_seconds),
            str(fresh_run_seconds),
        ],
        cwd=roots.second_cwd,
        env=roots.environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


async def _await_worker_state(
    *, roots: _Roots, state: str, timeout_seconds: float
) -> ScheduleWorkerHealthDAO:
    """Poll the worker's health until it reports one state (bounded)."""
    async with asyncio.timeout(timeout_seconds):
        while True:
            observed: ScheduleWorkerHealthDAO = await roots.runtime().inspect_health()
            if observed.state == state:
                return observed
            await asyncio.sleep(0.2)


def _invocation_status(*, schedules_dir: Path, invocation_id: str) -> str:
    """Read one invocation's stored status read-only."""
    connection = sqlite3.connect(f"file:{schedules_dir / 'schedules.db'}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT status FROM schedule_invocations WHERE id = ?", (invocation_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


async def test_responsive_worker_whose_engine_stopped_progressing_is_unresponsive_and_never_replaced(
    tmp_path: Path,
) -> None:
    """OPS111-03/05 (R03): a worker whose control channel answers at once but
    whose ticks can no longer finish (the schedules database is held by
    another writer) stops being healthy within its progress limit; start
    refuses without a launch attempt while it still owns the directory, and it
    is healthy again once its ticks progress."""
    roots = _Roots(tmp_path=tmp_path)
    worker = _start_tuned_worker(roots=roots, progress_limit_seconds=3.0, fresh_run_seconds=0.0)
    try:
        healthy = await _await_worker_state(roots=roots, state="healthy", timeout_seconds=60)
        writer = sqlite3.connect(roots.schedules_dir / "schedules.db", isolation_level=None, timeout=10)
        try:
            writer.execute("BEGIN IMMEDIATE")
            stalled = await _await_worker_state(roots=roots, state="unresponsive", timeout_seconds=30)
            assert stalled.launch_id == healthy.launch_id, "the worker itself answered"
            assert stalled.reason is not None and "tick" in stalled.reason
            launcher = _RecordingLauncher()
            with pytest.raises(ScheduleWorkerUnavailableError) as refused:
                await roots.runtime(launcher=launcher).start_or_reuse()
            assert refused.value.health.state == "unresponsive"
            assert launcher.launch_ids == [], "an owned worker is never replaced"
            assert worker.poll() is None
        finally:
            writer.rollback()
            writer.close()
        resumed = await _await_worker_state(roots=roots, state="healthy", timeout_seconds=30)
        assert resumed.launch_id == healthy.launch_id
    finally:
        await asyncio.to_thread(_stop_manual_worker, manual=worker)


async def test_long_fresh_work_never_makes_a_progressing_worker_unhealthy(tmp_path: Path) -> None:
    """OPS111-03 (R03): a fresh run that lasts longer than the progress limit
    keeps the worker healthy, because ticks keep progressing beside it; a
    healthy answer does not mean the run finished."""
    roots = _Roots(tmp_path=tmp_path)
    worker = _start_tuned_worker(roots=roots, progress_limit_seconds=3.0, fresh_run_seconds=8.0)
    try:
        healthy = await _await_worker_state(roots=roots, state="healthy", timeout_seconds=60)
        created = await asyncio.to_thread(_add_json, roots=roots, name="Long run")
        assert created["worker"]["launch_id"] == healthy.launch_id, "add reused the running worker"
        triggered = await asyncio.to_thread(roots.cli, "schedule", "trigger", "--schedule", "Long run")
        assert triggered.returncode == 0, triggered.stderr
        invocation_id: str = triggered.stdout.strip()
        async with asyncio.timeout(30):
            while (
                _invocation_status(schedules_dir=roots.schedules_dir, invocation_id=invocation_id)
                != "running"
            ):
                await asyncio.sleep(0.1)
        observed: list[tuple[str, str]] = []
        for _sample in range(14):
            sample = await roots.runtime().inspect_health()
            observed.append(
                (
                    sample.state,
                    _invocation_status(schedules_dir=roots.schedules_dir, invocation_id=invocation_id),
                )
            )
            await asyncio.sleep(0.5)
        assert all(state == "healthy" for state, _status in observed), observed
        assert sum(status == "running" for _state, status in observed) >= 8, "the run outlasted the limit"
        async with asyncio.timeout(30):
            while (
                _invocation_status(schedules_dir=roots.schedules_dir, invocation_id=invocation_id)
                == "running"
            ):
                await asyncio.sleep(0.2)
        assert (
            _invocation_status(schedules_dir=roots.schedules_dir, invocation_id=invocation_id) == "completed"
        )
    finally:
        await asyncio.to_thread(_stop_manual_worker, manual=worker)


async def test_engine_run_ends_after_every_stop_even_when_a_loop_absorbs_a_cancellation(
    tmp_path: Path,
) -> None:
    """OPS111-05: a stopped engine run always ends. Python 3.11's wait_for
    absorbs a cancellation that lands as its inner wait completes; Honker's
    drain loops wait for jobs through it, so a drain can keep waiting for its
    next job after the stop. Stopping while commits keep waking every drain
    loop exposes that window; every stop must still join both loops."""
    import honker

    from src.schedules.workflows import ScheduleEngine

    hung: list[int] = []
    for cycle in range(12):
        engine = ScheduleEngine(db_path=tmp_path / "schedules.db", channel_db_path=tmp_path / "channels.db")
        engine.open()
        committer = honker.open(str(engine.engine_db_path))
        stop_event = asyncio.Event()
        running = asyncio.create_task(engine.run(stop_event=stop_event))
        try:
            await asyncio.sleep(0.5)
            for _commit in range(50 + cycle * 7):
                committer.queue("unrelated-noise").enqueue({"cycle": cycle})
                await asyncio.sleep(0.002)
            stop_event.set()
            for _commit in range(200):
                committer.queue("unrelated-noise").enqueue({"cycle": cycle})
                await asyncio.sleep(0.002)
            done, _pending = await asyncio.wait({running}, timeout=10)
            if not done:
                hung.append(cycle)
                for _attempt in range(40):
                    running.cancel()
                    done, _pending = await asyncio.wait({running}, timeout=0.5)
                    if done:
                        break
        finally:
            committer.close()
            engine.close()
    assert hung == [], f"stopped runs that never ended: cycles {hung}"
