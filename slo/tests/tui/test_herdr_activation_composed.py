"""Mounted native activation through real stores and registered fake CLI processes."""

import asyncio
import gc
import json
import os
import weakref
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrReporterProtocol
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture


@pytest.fixture
def native_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Install Faux before construction and a contained regular plain-slo candidate."""
    executable = tmp_path / "slo"
    assert executable.resolve().parent == tmp_path.resolve() and not executable.is_symlink()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv(name="PATH", value=str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value="synthetic-offline-key")
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline answer")] * 8),
            supports_explicit_caching=False,
        ),
    ) as factory:
        yield factory


def commands(fake: FakeHerdrFixture) -> list[list[str]]:
    """Read complete argv records from the identity-guarded temporary capture."""
    return [json.loads(line) for line in fake.capture.read_text().splitlines()]


async def eventually(predicate: Callable[[], bool]) -> None:
    """Wait boundedly for actual asynchronous process/file completion."""
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_mount_native_save_display_and_new_lease_order(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: object
) -> None:
    """Actual mount and slash replacement use one captured inbox owner and ordered CLI."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await old.rename_session(session_name="original")
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        await eventually(predicate=lambda: any("--herdr-restore" in row for row in commands(fake_herdr)))
        reporter = old._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        assert old._herdr_visualizer is not None
        assert old._herdr_visualizer._transport is reporter._transport
        assert not old._agent_is_injected
        assert app._render_event in old._subscribers
        assert reporter._saved is not None
        records = list((reporter._config.state_root / "restore-v1").glob("*.json"))
        assert records and json.loads(records[0].read_text())["config"]["session_id"] == old.session_id
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        owner = app._session_owner_id
        store = app._lease_store
        assert store is not None
        old_lease = await store.read(session_id=old.session_id)
        assert old_lease is not None and old_lease.owner_id == owner
        boundary = len(commands(fake_herdr))
        await app._dispatch_slash_command(line="/new")
        new = app._session
        assert new is not old and app._session_owner_id == owner
        assert await store.read(session_id=old.session_id) is None
        new_lease = await store.read(session_id=new.session_id)
        assert new_lease is not None and new_lease.owner_id == owner
        # Intermediate close reports remote evidence only; its default drained
        # field is not disposal permission. Final transport close proves drain.
        assert reporter._close_task is not None
        assert reporter._transport_close_task is not None
        assert old._herdr_close_task is not None
        assert reporter._close_task.result().resources == "drained"
        assert reporter._close_task.result().replacement == "safe"
        assert reporter._transport_close_task.result().replacement == "safe"
        assert not new._herdr_suppressed, old._herdr_close_task.result()
        await eventually(predicate=lambda: any(new.session_id in row for row in commands(fake_herdr)))
        later = commands(fake_herdr)[boundary:]
        first_claim = next(index for index, row in enumerate(later) if new.session_id in row)
        assert any(row[1] == "release-agent" for row in later[:first_claim])
        assert not any(old.session_id in row for row in later[first_claim:])
        assert app._render_event not in old._subscribers
        assert app._render_event in new._subscribers
    assert not reporter.retains_external_resources


@pytest.mark.parametrize("mode", ["disabled", "outside"])
async def test_mount_inactive_has_zero_integration_io_and_faux_parity(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Inactive mount/new still deliver Faux answers and preserve ordinary history."""
    if mode == "disabled":
        monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    else:
        monkeypatch.delenv(name="HERDR_ENV")
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    root = Path(os.environ["SLO_HOME"]) / "integrations"
    app = SloTUI(session=session)
    with patch.object(session, "_prepare_herdr_reporter", side_effect=AssertionError("inactive assembly")):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert session._herdr_start_task is None
            assert app._lease_store is not None and app._inbox_store is not None
            assert session.workflow_visualizer_destination == "platform"
            assert app._input is not None
            app._input.load_text("offline request")
            await pilot.press("enter")
            await eventually(predicate=lambda: native_factory.called and not session.is_running)
            await pilot.pause()
            assert app._chat_transcript._adapter is not None
            assert "offline answer" in str(app._chat_transcript._adapter.lines)
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=session.session_id)
            assert any(event.kind == "user_message" for event in events)
            await app._dispatch_slash_command(line="/new")
            assert app._session is not session
            assert app._session._herdr_start_task is None
    assert commands(fake_herdr) == []
    assert not root.exists()


@pytest.mark.parametrize("phase", ["assembly", "activation"])
async def test_mounted_activation_unmount_joins_repeated_cancel_without_late_claim(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, phase: str
) -> None:
    """Shutdown joins the actual mount owner across preparation or reporter start."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=session)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_prepare = session._prepare_herdr_reporter
    original_start = HerdrReporter.start

    async def prepare() -> HerdrReporterProtocol:
        """Pause after real filesystem assembly, before ownership is returned."""
        reporter = await original_prepare()
        entered.set()
        await release.wait()
        return reporter

    async def start(reporter: HerdrReporter) -> None:
        """Pause at the real reporter activation boundary before any CLI claim."""
        entered.set()
        await release.wait()
        await original_start(reporter)

    async def shutdown_during_mount() -> None:
        """Drive shutdown independently because Textual awaits on_mount before yielding."""
        await asyncio.wait_for(entered.wait(), timeout=5)
        shutdown = asyncio.create_task(coro=app.on_unmount())
        try:
            await eventually(predicate=lambda: app._app_closing)
            for _ in range(3):
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
            assert session._herdr_start_task is not None and not session._herdr_start_task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(shutdown, timeout=10)

    driver = asyncio.create_task(coro=shutdown_during_mount())
    seam: AbstractContextManager[object] = patch.object(
        session, "_prepare_herdr_reporter", side_effect=prepare
    )
    if phase == "activation":
        seam = patch.object(HerdrReporter, "start", new=start)
    try:
        with seam:
            async with app.run_test() as pilot:
                await driver
                await pilot.pause()
                assert app._delivery_quiescing
                assert not session._herdr_reporting_started
                assert app._preparation_task is None
                assert app._lease_timer is None and app._inbox_timer is None
                assert session._herdr_start_task is not None and session._herdr_start_task.done()
                assert not session._herdr_reporter.retains_external_resources
                assert not any(row[1] == "report-agent" for row in commands(fake_herdr))
    finally:
        release.set()
        await driver


@pytest.mark.parametrize("failure", ["remote", "cleanup"])
async def test_mounted_drained_uncertainty_suppresses_successors_and_allows_gc(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, failure: str
) -> None:
    """Final local drain cannot erase remote withdrawal or producer-cleanup failure."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = old._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        retained = weakref.ref(old)
        if failure == "remote":
            seam = patch.object(reporter, "_shutdown_release", side_effect=RuntimeError("withdrawal"))
        else:
            reporter._cleanup_failed = True
            seam = patch.object(reporter, "_log_failure")
        with seam:
            await app._dispatch_slash_command(line="/new")
        assert old._herdr_close_task is not None
        outcome = old._herdr_close_task.result()
        assert outcome.replacement == "uncertain" and outcome.resources == "drained"
        assert reporter._transport.closed and reporter._transport.resources_drained
        assert not reporter._lease_held
        assert app._retired_herdr_session is None
        assert app._session._herdr_suppressed and app._session._herdr_start_task is None
        count = len(commands(fake_herdr))
        del old
        gc.collect()
        assert retained() is None
        await app._dispatch_slash_command(line="/new")
        assert app._session._herdr_suppressed and app._session._herdr_start_task is None
        assert len(commands(fake_herdr)) == count


async def test_mounted_contender_refuses_real_lease_without_commands(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock
) -> None:
    """A mounted competitor cannot claim or unlock another reporter's pane lease."""
    from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError

    owner = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await owner.start_external_reporting(interactive=True)
    reporter = owner._herdr_reporter
    assert isinstance(reporter, HerdrReporter)
    try:
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        # Stop refresh admissions, not the lease or transport, to make capture exact.
        reporter.revoke_viewer_admission()
        async with reporter._transport._command_lock:
            boundary = len(commands(fake_herdr))
        contender = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        app = SloTUI(session=contender)
        async with app.run_test() as pilot:
            await pilot.pause()
            refused = contender._herdr_reporter
            assert isinstance(refused, HerdrReporter)
            assert refused is not reporter and refused._activation_attempted
            assert not refused._lease_held and not refused._activation_released
            assert contender.workflow_visualizer_destination == "unavailable"
            assert not contender._herdr_reporting_started
            outcome = await contender.close_external_reporting()
            assert outcome.replacement == "uncertain" and outcome.resources == "drained"
            assert commands(fake_herdr)[boundary:] == []
            probe = HerdrSequenceStore(
                state_root=reporter._config.state_root,
                socket_namespace=reporter._config.socket_path or "default",
                pane_id=reporter._config.pane_id,
            )
            with pytest.raises(HerdrSequenceUnavailableError):
                probe.acquire()
            await app._dispatch_slash_command(line="/new")
            assert app._session._herdr_suppressed
            assert app._session._herdr_start_task is None
            assert commands(fake_herdr)[boundary:] == []
    finally:
        await owner.close_external_reporting()
    probe.acquire()
    probe.close()


async def test_mounted_uncertain_unlock_retains_one_owner_and_suppresses_successors(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock
) -> None:
    """A real held pane lease survives two replacements and GC until final local drain."""
    from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError

    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = old._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        lease = reporter._sequence_store
        contender = HerdrSequenceStore(
            state_root=reporter._config.state_root,
            socket_namespace=reporter._config.socket_path or "default",
            pane_id=reporter._config.pane_id,
        )
        retained = weakref.ref(old)
        with patch.object(lease, "close", side_effect=OSError("synthetic unlock refusal")):
            await app._dispatch_slash_command(line="/new")
            first = app._session
            assert first._herdr_suppressed and first._herdr_start_task is None
            assert app._session_replacement_task is None
            del old
            gc.collect()
            assert retained() is app._retired_herdr_session
            count = len(commands(fake_herdr))
            await app._dispatch_slash_command(line="/new")
            assert app._session is not first
            assert app._session._herdr_suppressed and app._session._herdr_start_task is None
            assert app._retired_herdr_session is retained()
            assert reporter._sequence_store is lease and reporter._lease_held
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
            assert len(commands(fake_herdr)) == count
        await app.on_unmount()
        assert app._retired_herdr_session is None
        assert not reporter.retains_external_resources
        contender.acquire()
        contender.close()
