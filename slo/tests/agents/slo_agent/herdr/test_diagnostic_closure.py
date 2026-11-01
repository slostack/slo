"""Diagnostic episodes through the real guarded transport, never live Herdr."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrReporterConfigDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("episode", [False, True])
def test_reporter_cancelled_accounting_does_not_change_episode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, episode: bool
) -> None:
    """Cancellation accounts uncertainty but is not an ordinary diagnostic failure."""
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO
    from tests.agents.slo_agent.herdr.test_reporter import publication, reporter

    owner = reporter(root=tmp_path)
    ticket = HerdrReportTicketDAO(
        operation="claim",
        sequence=1,
        configuration_generation=0,
        report_revision=1,
        publication=publication(),
    )
    if episode:
        owner._log_failure(category="restore_unavailable")
    before = list(caplog.messages)
    failures = set(owner._diagnostic_failures)
    owner._admitted_ticket = ticket
    owner._record_command_result(
        ticket=ticket, result=HerdrCliTransport._failure(status="cancelled", admitted=True)
    )
    assert owner._admitted_ticket is None
    assert caplog.messages == before
    assert owner._diagnostic_failures == failures


def build_transport(*, fake: FakeHerdrFixture, root: Path) -> HerdrCliTransport:
    """Build an inert owner whose actual spawn must pass the fixture capability guard."""
    return HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake.executable, state_root=root, metadata_profile="compact"
        ),
        environment={},
    )


@pytest.mark.parametrize("episode", [False, True])
async def test_cancelled_waiter_preserves_episode(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture, episode: bool
) -> None:
    """Cancellation while queued neither starts nor recovers a diagnostic episode."""
    transport = build_transport(fake=fake_herdr, root=tmp_path)
    command = HerdrCliCommandDAO(argv=("pane", "split"))
    try:
        if episode:
            with patch("asyncio.create_subprocess_exec", side_effect=OSError("private")):
                await transport.invoke(command=command, admission=RecordingAdmission())
        before = list(caplog.messages)
        admission = RecordingAdmission()
        async with transport._command_lock:
            task = asyncio.create_task(coro=transport.invoke(command=command, admission=admission))
            await asyncio.sleep(delay=0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert caplog.messages == before
        assert transport._command_failure_active is episode
        assert admission.attempts == 0 and not admission.results
        assert transport.resources_drained
    finally:
        await transport.close()


async def test_transport_sink_failure_and_category_bounds(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Broken sinks cannot escape invoke or multiply independent fixed categories."""
    transport = build_transport(fake=fake_herdr, root=tmp_path)
    command = HerdrCliCommandDAO(argv=("pane", "split"))
    try:
        with patch("logging.Logger.warning", side_effect=RuntimeError("private-sink")) as sink:
            with patch("asyncio.create_subprocess_exec", side_effect=OSError("private-spawn")):
                await transport.invoke(command=command, admission=RecordingAdmission())
            await transport.invoke(command=command, admission=RecordingAdmission())
            assert sink.call_count == 2
        await transport.invoke(command=command, admission=RecordingAdmission())
        assert not caplog.records and not transport._command_failure_active
        for _ in range(100):
            transport._log_failure(category="accounting_failed")
            transport._log_failure(category="cleanup_unavailable")
            transport._log_failure(category="termination_failed")
        assert caplog.messages == [
            "herdr_accounting_failed",
            "herdr_cleanup_unavailable",
            "herdr_termination_failed",
        ]
        assert len(transport._diagnostic_times) == 4
        assert all(isinstance(value, float) for value in transport._diagnostic_times.values())
    finally:
        await transport.close()


@pytest.mark.parametrize("failure", ["spawn", "timeout"])
async def test_invoke_failure_suppression_and_recovery(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    """Spawn refusal or lock timeout opens one episode; refusal cannot recover it."""
    transport = build_transport(fake=fake_herdr, root=tmp_path)
    command = HerdrCliCommandDAO(argv=("pane", "split"))
    admission = RecordingAdmission()
    try:
        if failure == "spawn":
            with patch("asyncio.create_subprocess_exec", side_effect=OSError("private-spawn-sentinel")):
                result = await transport.invoke(command=command, admission=admission)
            assert result.spawn_failed and len(admission.results) == 1
        else:
            async with transport._command_lock:
                result = await transport.invoke(command=command, admission=admission)
            assert not result.admitted and not admission.results
        assert result.outcome.status == ("unavailable" if failure == "spawn" else "timeout")
        refused = await transport.invoke(command=command, admission=RecordingAdmission(allowed=False))
        assert refused.outcome.status == "suppressed" and transport._command_failure_active
        for _ in range(2):
            assert (
                await transport.invoke(command=command, admission=RecordingAdmission())
            ).outcome.status == "ok"
        assert [record.getMessage() for record in caplog.records] == [
            "herdr_command_unavailable",
            "herdr_command_unavailable_recovered",
        ]
        assert transport.resources_drained and not transport._command_lock.locked()
        assert "private" not in caplog.text and str(tmp_path) not in caplog.text
    finally:
        await transport.close()
