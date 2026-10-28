"""One mounted stale-release boundary beyond T2's accounting matrix."""

from pathlib import Path
from unittest.mock import MagicMock

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory


async def test_mounted_stale_release_clears_old_binding_without_acknowledging_new_policy(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: MagicMock
) -> None:
    """An admitted release finishes after policy changes; the newest batch alone resumes."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="release fixture")
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._restore_ack is not None)
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        old_binding = reporter._binding
        assert old_binding is not None
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        script = fake_herdr.executable.read_text()
        fake_herdr.executable.write_text(
            script
            + "\nif sys.argv[2] == 'release-agent':\n import time\n"
            + f" while not Path({str(fake_herdr.barrier)!r}).read_text(): time.sleep(0.005)\n"
        )
        boundary = len(commands(fake_herdr))
        try:
            session.switch_model(model_name="gpt-4.1")
            await eventually(
                predicate=lambda: any(row[1] == "release-agent" for row in commands(fake_herdr)[boundary:])
            )
            ticket = reporter._admitted_ticket
            assert ticket is not None and ticket.operation == "replace_release"
            assert ticket.binding == old_binding
            session.switch_model(model_name="gpt-5.4")
            latest = reporter._latest
            assert latest is not None and latest.configuration_generation > ticket.configuration_generation
            # Freeze follow-ups so terminal evidence cannot be confused with a later acknowledgement.
            reporter.revoke_viewer_admission()
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.barrier.write_text("release")
            await eventually(predicate=lambda: reporter._admitted_ticket is None)
            assert reporter._binding is None
            assert reporter._restore_ack is None and reporter._lifecycle_ack is None
            assert reporter._display_ack_revision is None
            assert reporter._transport.resources_drained
            assert [row[1] for row in commands(fake_herdr)[boundary:]] == ["release-agent"]
            await app._dispatch_slash_command(line="/new")
            assert session._herdr_close_task is not None
            assert session._herdr_close_task.result().replacement == "safe"
            assert not app._session._herdr_suppressed
        finally:
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.barrier.write_text("release")
            fake_herdr.executable.write_text(script)
