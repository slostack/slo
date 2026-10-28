"""Mounted fault composition; errno mechanics remain in the T2 adapter matrix."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory


@pytest.mark.parametrize("seam", ["_prepare_herdr_parent", "_validate_executable"])
async def test_mounted_probe_fault_preserves_original_prompt_and_suppresses_new(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, seam: str
) -> None:
    """A failed local activation probe is not evidence that the remote pane is empty."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    owner = SloAgentSession if seam == "_prepare_herdr_parent" else HerdrReporter
    app = SloTUI(session=session)
    with patch.object(owner, seam, side_effect=OSError("synthetic probe failure")):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert session.workflow_visualizer_destination == "unavailable"
            assert not session._herdr_reporting_started
            assert app._input is not None
            app._input.load_text("original session remains usable")
            await pilot.press("enter")
            await eventually(predicate=lambda: native_factory.called and not session.is_running)
            await pilot.pause()
            assert app._session is session
            assert app._chat_transcript._adapter is not None and "offline answer" in str(
                app._chat_transcript._adapter.lines
            )
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=session.session_id)
            assert any(event.kind == "run_completed" for event in events)
            await app._dispatch_slash_command(line="/new")
            assert session._herdr_close_task is not None
            outcome = session._herdr_close_task.result()
            assert outcome.replacement == "uncertain" and outcome.resources == "drained"
            assert app._session._herdr_suppressed
            assert app._session._herdr_start_task is None
            assert app._retired_herdr_session is None
            assert commands(fake_herdr) == []


@pytest.mark.parametrize("phase", ["activation", "claim", "restore", "shutdown", "clear"])
@pytest.mark.parametrize("effect", ["reject", "timeout"])
async def test_mounted_wire_fault_close_authority(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, phase: str, effect: str
) -> None:
    """Real ambiguous CLI completion differs from confirmed release and display failure."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    target = {
        "activation": "release-agent",
        "claim": "report-agent",
        "restore": "report-agent",
        "shutdown": "release-agent",
        "clear": "report-metadata",
    }[phase]
    condition = "'--herdr-restore' in sys.argv" if phase == "restore" else f"sys.argv[2] == {target!r}"
    fault = f"\nif {condition}:\n"
    fault += " sys.exit(7)\n" if effect == "reject" else " import time\n time.sleep(30)\n"
    if phase in ("activation", "claim", "restore"):
        fake_herdr.executable.write_text(script + fault)
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="fault fixture")
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        if phase == "claim":
            await eventually(
                predicate=lambda: reporter._binding is not None and reporter._admitted_ticket is None
            )
        elif phase == "restore":
            await eventually(
                predicate=lambda: any("--herdr-restore" in row for row in commands(fake_herdr))
                and reporter._admitted_ticket is None
            )
            assert reporter._binding is not None and reporter._binding.certainty == "confirmed"
            assert reporter._restore_ack is None
        elif phase != "activation":
            await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        assert app._input is not None
        app._input.load_text("original session survives optional wire failure")
        await pilot.press("enter")
        await eventually(predicate=lambda: native_factory.called and not session.is_running)
        await pilot.pause()
        assert app._session is session
        assert app._chat_transcript._adapter is not None and "offline answer" in str(
            app._chat_transcript._adapter.lines
        )
        assert session._history_store is not None
        events = await session._history_store.load_events(session_id=session.session_id)
        assert any(event.kind == "run_completed" for event in events)
        reporter.revoke_viewer_admission()
        async with reporter._transport._command_lock:
            boundary = len(commands(fake_herdr))
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.executable.write_text(script + fault if phase in ("shutdown", "clear") else script)
        await app._dispatch_slash_command(line="/new")
        assert session._herdr_close_task is not None
        outcome = session._herdr_close_task.result()
        uncertain = phase in ("activation", "shutdown")
        assert outcome.replacement == ("uncertain" if uncertain else "safe")
        assert outcome.resources == "drained" and not reporter.retains_external_resources
        assert app._session._herdr_suppressed is uncertain
        assert app._retired_herdr_session is None
        later = commands(fake_herdr)[boundary:]
        if uncertain:
            assert app._session._herdr_start_task is None
            assert not any(row[1] == "report-metadata" for row in later)
        else:
            await eventually(
                predicate=lambda: any(app._session.session_id in row for row in commands(fake_herdr))
            )
            assert reporter._close_task is not None and reporter._transport_close_task is not None
            assert reporter._close_task.result().resources == "drained"
            assert reporter._close_task.result().replacement == "safe"
            assert reporter._transport_close_task.result().replacement == "safe"
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)


@pytest.mark.parametrize("phase", ["activation", "claim", "restore", "shutdown"])
async def test_mounted_definitive_spawn_failure_preserves_prior_binding(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, phase: str
) -> None:
    """A refused spawn rolls back admission, not previously known remote ownership."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="spawn fixture")
    original_spawn = HerdrCliTransport._spawn
    refused = asyncio.Event()

    async def spawn(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO
    ) -> asyncio.subprocess.Process:
        """Fail only the selected command after the real admission commit."""
        fake_herdr.guard.require_registered(path=transport._config.binary_path)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        ticket = reporter._admitted_ticket
        operation = {"activation": "activation_release", "shutdown": "shutdown_release"}.get(phase, phase)
        if ticket is not None and ticket.operation == operation:
            refused.set()
            raise FileNotFoundError("synthetic definitive spawn refusal")
        return await original_spawn(transport, command=command)

    app = SloTUI(session=session)
    with patch.object(HerdrCliTransport, "_spawn", new=spawn):
        async with app.run_test() as pilot:
            await pilot.pause()
            reporter = session._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            if phase == "shutdown":
                await eventually(predicate=lambda: reporter._display_ack_revision is not None)
            else:
                await eventually(predicate=lambda: refused.is_set() and reporter._admitted_ticket is None)
                if phase == "claim":
                    assert reporter._binding is None
                if phase == "restore":
                    assert reporter._binding is not None and reporter._binding.certainty == "confirmed"
                    assert reporter._binding.reference is None and reporter._restore_ack is None
            await app._dispatch_slash_command(line="/new")
            assert refused.is_set() and session._herdr_close_task is not None
            outcome = session._herdr_close_task.result()
            assert outcome.resources == "drained"
            assert outcome.replacement == ("uncertain" if phase in ("activation", "shutdown") else "safe")
            assert app._session._herdr_suppressed is (phase in ("activation", "shutdown"))
            assert app._retired_herdr_session is None


@pytest.mark.parametrize("completion", ["success", "cancel"])
async def test_mounted_admitted_restore_cannot_acknowledge_new_generation(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, completion: str
) -> None:
    """Real old install effects survive supersession without crediting new policy."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    fake_herdr.executable.write_text(
        script
        + "\nif '--herdr-restore' in sys.argv:\n import time\n"
        + f" while not Path({str(fake_herdr.barrier)!r}).read_text(): time.sleep(0.005)\n"
    )
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="stale install fixture")
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: any("--herdr-restore" in row for row in commands(fake_herdr)))
        ticket = reporter._admitted_ticket
        assert ticket is not None and ticket.operation == "restore"
        session.switch_model(model_name="gpt-4.1")
        assert reporter._latest is not None
        assert reporter._latest.configuration_generation > ticket.configuration_generation
        reporter.revoke_viewer_admission()
        if completion == "cancel":
            assert reporter._worker is not None
            reporter._worker.cancel()
        else:
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.barrier.write_text("release")
        await eventually(predicate=lambda: reporter._admitted_ticket is None)
        assert reporter._restore_ack is None and reporter._lifecycle_ack is None
        assert reporter._binding is not None
        assert reporter._binding.configuration_generation == ticket.configuration_generation
        assert ticket.saved is not None
        assert reporter._binding.reference == ticket.saved.reference
        assert reporter._transport.resources_drained
        boundary = len(commands(fake_herdr))
        await app._dispatch_slash_command(line="/new")
        assert session._herdr_close_task is not None
        assert session._herdr_close_task.result().replacement == "safe"
        later = commands(fake_herdr)[boundary:]
        assert later and later[0][1] == "release-agent"


@pytest.mark.parametrize("seam", ["close", "close_transport"])
async def test_mounted_close_fault_after_real_drain_stays_uncertain(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock, seam: str
) -> None:
    """An optional cleanup exception cannot become safe merely because local drain succeeds."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        original = getattr(reporter, seam)

        async def close_then_fail() -> None:
            """Perform actual owned cleanup before injecting a gateway failure."""
            await original()
            raise OSError("synthetic close fault")

        with patch.object(reporter, seam, side_effect=close_then_fail):
            await app._dispatch_slash_command(line="/new")
        assert session._herdr_close_task is not None
        outcome = session._herdr_close_task.result()
        assert outcome.replacement == "uncertain"
        # A throwing final gateway supplies no disposal evidence: intermediate
        # default drained cannot authorize disposal before explicit local drain.
        assert outcome.resources == ("retained" if seam == "close_transport" else "drained")
        assert reporter._transport.closed and reporter._transport.resources_drained
        assert not reporter._lease_held
        assert app._retired_herdr_session is (session if seam == "close_transport" else None)
        assert app._session._herdr_suppressed
        boundary = len(commands(fake_herdr))
        await app._dispatch_slash_command(line="/new")
        assert app._session._herdr_suppressed and app._session._herdr_start_task is None
        assert len(commands(fake_herdr)) == boundary
    assert app._retired_herdr_session is None
    assert not reporter.retains_external_resources
    if seam == "close_transport":
        assert session._herdr_retired_drain_task is not None
        drained = session._herdr_retired_drain_task.result()
        assert drained.replacement == "uncertain" and drained.resources == "drained"
    assert len(commands(fake_herdr)) == boundary
