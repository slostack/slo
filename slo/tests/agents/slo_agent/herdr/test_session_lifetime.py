"""Session activation boundaries with fake-only external capabilities."""

import asyncio
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.slo_agent.herdr.service import NullHerdrReporter
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("destination", ["platform", "unavailable"])
def test_null_visualizer_contract(destination: Literal["platform", "unavailable"]) -> None:
    """Null implements the shared viewer contract by fixed refusal, never None."""
    from typing import NoReturn, get_type_hints
    from src.agents.slo_agent.herdr.dao import HerdrReporterProtocol, HerdrRestoreUnavailableError
    from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher

    reporter: HerdrReporterProtocol = NullHerdrReporter(destination=destination)
    with pytest.raises(HerdrRestoreUnavailableError) as caught:
        reporter.build_visualizer()
    assert str(caught.value) == str(HerdrRestoreUnavailableError())
    assert get_type_hints(NullHerdrReporter.build_visualizer)["return"] is NoReturn
    assert (
        get_type_hints(
            HerdrReporterProtocol.build_visualizer,
            localns={"HerdrVisualizerLauncher": HerdrVisualizerLauncher},
        )["return"]
        is HerdrVisualizerLauncher
    )


@pytest.mark.parametrize("phase", ["viewer", "reporter", "transport", "revoke", "evidence"])
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_cleanup_fault_keeps_later_owners(
    tmp_path: Path, phase: str, failure: type[BaseException]
) -> None:
    """Inner faults cannot skip later owners or produce safe replacement evidence."""
    from unittest.mock import Mock, PropertyMock
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
    from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    calls: list[str] = []

    def record(name: str) -> None:
        """Record attempted owner before injecting its defect."""
        calls.append(name)
        if name == phase:
            raise failure()

    async def viewer_close() -> None:
        record("viewer")

    async def reporter_close() -> HerdrReporterCloseOutcomeDAO:
        record("reporter")
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    async def transport_close() -> HerdrReporterCloseOutcomeDAO:
        record("transport")
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    def evidence() -> bool:
        record("evidence")
        return False

    viewer = Mock(spec=HerdrVisualizerLauncher)
    viewer.close = AsyncMock(side_effect=viewer_close)
    session._herdr_visualizer = viewer
    with (
        patch.object(reporter, "revoke_viewer_admission", side_effect=lambda: record("revoke")),
        patch.object(reporter, "close", side_effect=reporter_close),
        patch.object(reporter, "close_transport", side_effect=transport_close),
        patch.object(
            type(reporter), "retains_external_resources", new_callable=PropertyMock, side_effect=evidence
        ),
    ):
        outcome = await session.close_external_reporting()
        assert await session.close_external_reporting() is outcome
    assert calls[:4] == ["revoke", "viewer", "reporter", "transport"]
    assert outcome.replacement == "uncertain"
    assert outcome.resources == ("retained" if phase in ("viewer", "transport", "evidence") else "drained")


@pytest.mark.parametrize("gateway", ["close_transport", "drain_retained_external_resources"])
async def test_null_final_evidence_is_independent_of_intermediate_fault(gateway: str) -> None:
    """An inert owner proves no resources without re-entering remote-close policy."""
    reporter = NullHerdrReporter(destination="platform")
    with patch.object(reporter, "close", side_effect=RuntimeError("intermediate fault")) as close:
        outcome = await getattr(reporter, gateway)()
    close.assert_not_called()
    assert outcome.replacement == "safe" and outcome.resources == "drained"
    assert not reporter.retains_external_resources


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_failed_activation_task_is_accounted_by_close(
    tmp_path: Path, failure: type[BaseException]
) -> None:
    """Defective retained activation cannot produce safe successor evidence."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))

    async def fail() -> None:
        raise failure()

    session._herdr_start_task = asyncio.create_task(fail())
    outcome = await session.close_external_reporting()
    assert outcome.replacement == "uncertain"
    assert outcome.resources == "drained"
    assert session._herdr_start_task.done()


@pytest.mark.parametrize("outside", [False, True])
async def test_prepare_disabled_does_not_prepare_capture(
    tmp_path: Path, outside: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pure classification must precede metadata/path preparation and assembly."""
    if outside:
        monkeypatch.setenv("SLO_HERDR_DISABLED", "0")
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(session, "_prepare_herdr_capture_inputs", new_callable=AsyncMock) as prepare:
        with patch.object(HerdrReporter, "build", side_effect=AssertionError("assembly")):
            reporter = await session._prepare_herdr_reporter()
    assert isinstance(reporter, NullHerdrReporter)
    assert reporter.destination == "platform"
    prepare.assert_not_called()


async def test_suppression_is_permanent(tmp_path: Path, fake_herdr: object) -> None:
    """Suppressed successors never allocate activation, even after close."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session.suppress_external_reporting()
    session.suppress_external_reporting()
    with patch.object(session, "_prepare_herdr_reporter", new_callable=AsyncMock) as prepare:
        await session.start_external_reporting()
        await session.close_external_reporting()
        await session.start_external_reporting(interactive=True)
    prepare.assert_not_called()
    assert session._herdr_start_task is None
    assert session.workflow_visualizer_destination == "unavailable"


async def test_suppression_rejects_attempted_activation(tmp_path: Path, fake_herdr: object) -> None:
    """A failed attempted owner cannot be discarded through suppression."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = NullHerdrReporter(destination="unavailable")
    with patch.object(session, "_prepare_herdr_reporter", new_callable=AsyncMock, return_value=reporter):
        await session.start_external_reporting()
    with pytest.raises(RuntimeError, match="activation already requested"):
        session.suppress_external_reporting()
    assert session._herdr_reporter is reporter
    await session.close_external_reporting()


@pytest.mark.parametrize("failure", [False, True])
async def test_retired_local_drain_cached(tmp_path: Path, failure: bool) -> None:
    """Final drain is one local attempt, never a second remote close."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    await session.close_external_reporting()
    with patch.object(reporter, "drain_retained_external_resources", new_callable=AsyncMock) as drain:
        drain.return_value = HerdrReporterCloseOutcomeDAO(replacement="safe")
        if failure:
            drain.side_effect = RuntimeError("private")
        with patch.object(reporter, "close", side_effect=AssertionError("remote retry")):
            first = await session.drain_retained_external_resources()
            second = await session.drain_retained_external_resources()
    assert first is second
    assert first.replacement == "uncertain"
    assert first.resources == ("retained" if failure else "drained")
    drain.assert_awaited_once()
    assert session._herdr_reporter is reporter


@pytest.mark.parametrize("phase", ["drain", "evidence"])
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_final_drain_fault_is_retained(
    tmp_path: Path, phase: str, failure: type[BaseException]
) -> None:
    """Defective local drain and evidence never escape as successful teardown."""
    from unittest.mock import PropertyMock
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.close_external_reporting()
    reporter = session._herdr_reporter
    with (
        patch.object(reporter, "drain_retained_external_resources", new_callable=AsyncMock) as drain,
        patch.object(type(reporter), "retains_external_resources", new_callable=PropertyMock) as evidence,
    ):
        drain.return_value = HerdrReporterCloseOutcomeDAO(replacement="safe")
        evidence.return_value = False
        (drain if phase == "drain" else evidence).side_effect = failure()
        outcome = await session.drain_retained_external_resources()
        assert await session.drain_retained_external_resources() is outcome
    assert outcome.resources == "retained"
    assert outcome.replacement == "uncertain"
    drain.assert_awaited_once()


@pytest.mark.parametrize("gateway", ["close", "drain"])
async def test_final_outcome_cannot_disagree_with_drained_getter(tmp_path: Path, gateway: str) -> None:
    """A final owner's retained result cannot be erased by a contradictory getter."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    if gateway == "drain":
        await session.close_external_reporting()
    method = "close_transport" if gateway == "close" else "drain_retained_external_resources"
    with patch.object(
        session._herdr_reporter,
        method,
        new_callable=AsyncMock,
        return_value=HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained"),
    ):
        outcome = await (
            session.close_external_reporting()
            if gateway == "close"
            else session.drain_retained_external_resources()
        )
    assert outcome.resources == "retained" and outcome.replacement == "uncertain"


async def test_retired_drain_requires_completed_close(tmp_path: Path) -> None:
    """Final drain cannot bypass normal withdrawal."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with pytest.raises(RuntimeError, match="close must complete"):
        await session.drain_retained_external_resources()
    assert session._herdr_retired_drain_task is None


async def test_finish_retired_cleanup_preserves_safe_close(tmp_path: Path) -> None:
    """A drained ordinary close needs no final attempt and preserves safe evidence."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(
        session._herdr_reporter, "drain_retained_external_resources", new_callable=AsyncMock
    ) as drain:
        first = await session.finish_retired_reporting_cleanup()
        second = await session.finish_retired_reporting_cleanup()
    assert first is second
    assert first.replacement == "safe"
    assert first.resources == "drained"
    drain.assert_not_called()


@pytest.mark.parametrize("retained", [False, True])
async def test_finish_retired_cleanup_single_local_attempt(tmp_path: Path, retained: bool) -> None:
    """Persistent ownership stays pending; successful late drain stays uncertain."""
    from unittest.mock import PropertyMock
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    entered, release = asyncio.Event(), asyncio.Event()

    async def drain() -> HerdrReporterCloseOutcomeDAO:
        entered.set()
        await release.wait()
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain", resources="retained" if retained else "drained"
        )

    with patch.object(type(reporter), "retains_external_resources", new_callable=PropertyMock) as owns:
        owns.return_value = True
        with patch.object(reporter, "drain_retained_external_resources", side_effect=drain) as local:
            waiter = asyncio.create_task(session.finish_retired_reporting_cleanup())
            await entered.wait()
            owner = session._herdr_finish_cleanup_task
            assert owner is not None
            waiter.cancel()
            await asyncio.sleep(0)
            waiter.cancel()
            owns.return_value = retained
            release.set()
            assert session._herdr_retired_drain_task is not None
            await session._herdr_retired_drain_task
            if retained:
                await asyncio.sleep(0)
                assert not owner.done()
                assert not waiter.done()
                assert session._herdr_reporter is reporter
                # Test-only teardown of the intentional never-completing owner.
                owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            local.assert_awaited_once()
            assert session._herdr_finish_cleanup_task is owner
            if not retained:
                assert (await session.finish_retired_reporting_cleanup()).replacement == "uncertain"


@pytest.mark.parametrize("has_pool", [False, True])
async def test_candidate_disposal_only_drains_candidate(tmp_path: Path, has_pool: bool) -> None:
    """Disposal preserves the old pool and candidate rename history."""
    from unittest.mock import Mock
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    candidate = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    old._sub_agent_pool = Mock(spec=SubAgentPool)
    pool = Mock(spec=SubAgentPool)
    candidate._sub_agent_pool = pool if has_pool else None
    await candidate.rename_session(session_name="candidate")
    await candidate.dispose_unmounted_session()
    await candidate.dispose_unmounted_session()
    old._sub_agent_pool.abort_and_drain.assert_not_called()
    assert candidate.session_name == "candidate"
    assert candidate._herdr_closing
    if has_pool:
        pool.abort_and_drain.assert_awaited_once()
    else:
        assert candidate._candidate_pool_cleanup_task is None


@pytest.mark.parametrize("failure", [False, True])
async def test_candidate_pool_cancel_and_failure(tmp_path: Path, failure: bool) -> None:
    """Repeated caller cancellation never transfers to candidate pool cleanup."""
    from unittest.mock import Mock
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def drain() -> None:
        entered.set()
        await release.wait()
        if failure:
            raise RuntimeError("private")

    pool = Mock(spec=SubAgentPool)
    pool.abort_and_drain = AsyncMock(side_effect=drain)
    session._sub_agent_pool = pool
    with patch.object(
        session._herdr_reporter, "record_publication_failure", side_effect=RuntimeError("sink")
    ):
        waiter = asyncio.create_task(session.dispose_unmounted_session())
        await entered.wait()
        waiter.cancel()
        await asyncio.sleep(0)
        waiter.cancel()
        assert session._candidate_pool_cleanup_task is not None
        assert not session._candidate_pool_cleanup_task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await session.dispose_unmounted_session()
    pool.abort_and_drain.assert_awaited_once()
    assert session._candidate_pool_cleanup_task is not None
    assert session._candidate_pool_cleanup_task.done()


@pytest.mark.parametrize("retained", [False, True])
async def test_candidate_pool_disposal_with_reporting_fault(tmp_path: Path, retained: bool) -> None:
    """Candidate pool joins despite reporting faults; persistent ownership stays pending."""
    from unittest.mock import Mock, PropertyMock
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    candidate = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    old._sub_agent_pool = Mock(spec=SubAgentPool)
    pool = Mock(spec=SubAgentPool)
    candidate._sub_agent_pool = pool
    pool_entered, pool_release = asyncio.Event(), asyncio.Event()
    drain_entered = asyncio.Event()

    async def drain_pool() -> None:
        """Expose candidate-pool entry without assuming scheduler turn counts."""
        pool_entered.set()
        await pool_release.wait()

    async def drain_reporting() -> HerdrReporterCloseOutcomeDAO:
        """Expose final reporting entry after the candidate pool has joined."""
        drain_entered.set()
        return HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained")

    pool.abort_and_drain = AsyncMock(side_effect=drain_pool)
    reporter = candidate._herdr_reporter
    with (
        patch.object(reporter, "close", side_effect=RuntimeError("private")),
        patch.object(reporter, "record_publication_failure", side_effect=RuntimeError("sink")),
        patch.object(
            type(reporter), "retains_external_resources", new_callable=PropertyMock, return_value=retained
        ),
        patch.object(
            reporter,
            "drain_retained_external_resources",
            side_effect=drain_reporting,
        ),
    ):
        waiter = asyncio.create_task(candidate.dispose_unmounted_session())
        try:
            await asyncio.wait_for(fut=pool_entered.wait(), timeout=2)
            assert not waiter.done()
            pool_release.set()
            if retained:
                await asyncio.wait_for(fut=drain_entered.wait(), timeout=2)
            pool.abort_and_drain.assert_awaited_once()
            old._sub_agent_pool.abort_and_drain.assert_not_called()
            if retained:
                assert not waiter.done()
                assert candidate._herdr_finish_cleanup_task is not None
                assert not candidate._herdr_finish_cleanup_task.done()
            else:
                await asyncio.wait_for(fut=asyncio.shield(waiter), timeout=2)
                assert not drain_entered.is_set()
                assert candidate._herdr_close_task is not None
                outcome = candidate._herdr_close_task.result()
                assert outcome.replacement == "uncertain" and outcome.resources == "drained"
        finally:
            pool_release.set()
            if retained and candidate._herdr_finish_cleanup_task is not None:
                candidate._herdr_finish_cleanup_task.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


async def test_failed_viewer_close_retains_owner(tmp_path: Path) -> None:
    """Reporter drain alone cannot prove an errored viewer join completed."""
    from unittest.mock import Mock
    from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    viewer = Mock(spec=HerdrVisualizerLauncher)
    viewer.close = AsyncMock(side_effect=RuntimeError("private"))
    session._herdr_visualizer = viewer
    outcome = await session.close_external_reporting()
    assert outcome.resources == "retained"
    assert outcome.replacement == "uncertain"
    assert session._herdr_visualizer is viewer
    final = await session.drain_retained_external_resources()
    assert final.resources == "retained"
    viewer.close.assert_awaited_once()


@pytest.mark.parametrize("phase", ["prepare", "start"])
async def test_close_during_activation(tmp_path: Path, fake_herdr: object, phase: str) -> None:
    """Close revokes synchronously and waits for retained activation before release."""
    entered, release = asyncio.Event(), asyncio.Event()
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = NullHerdrReporter(destination="unavailable")

    async def prepare() -> NullHerdrReporter:
        if phase == "prepare":
            entered.set()
            await release.wait()
        return reporter

    async def start() -> None:
        entered.set()
        await release.wait()

    with patch.object(session, "_prepare_herdr_reporter", side_effect=prepare):
        with patch.object(reporter, "start", side_effect=start) as activation:
            starter = asyncio.create_task(session.start_external_reporting())
            await entered.wait()
            session.begin_external_reporting_close()
            assert not session._herdr_reporting_started
            closer = asyncio.create_task(session.close_external_reporting())
            await asyncio.sleep(0)
            assert not closer.done()
            release.set()
            await starter
            outcome = await closer
    assert outcome.resources == "drained"
    assert session._herdr_reporter is reporter
    assert not session._herdr_reporting_started
    assert activation.await_count == (1 if phase == "start" else 0)


async def test_close_cancel_shares_owner(tmp_path: Path) -> None:
    """Multiple cancelled waiters join one close without cancelling its work."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def close() -> HerdrReporterCloseOutcomeDAO:
        entered.set()
        await release.wait()
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    with (
        patch.object(
            session._herdr_reporter,
            "close_transport",
            new_callable=AsyncMock,
            return_value=HerdrReporterCloseOutcomeDAO(replacement="safe"),
        ),
        patch.object(session._herdr_reporter, "close", side_effect=close) as cleanup,
    ):
        first = asyncio.create_task(session.close_external_reporting())
        await entered.wait()
        second = asyncio.create_task(session.close_external_reporting())
        await asyncio.sleep(0)
        first.cancel()
        second.cancel()
        await asyncio.sleep(0)
        first.cancel()
        assert session._herdr_close_task is not None
        assert not session._herdr_close_task.done()
        release.set()
        for waiter in (first, second):
            with pytest.raises(asyncio.CancelledError):
                await waiter
        assert (await session.close_external_reporting()).resources == "drained"
    cleanup.assert_awaited_once()


@pytest.mark.parametrize("stage", ["factory", "start", "viewer"])
async def test_actual_factory_fault_retains_owner(tmp_path: Path, fake_herdr: object, stage: str) -> None:
    """Assembly failures and a broken diagnostic sink cannot discard ownership."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    target = {"factory": "build", "start": "start", "viewer": "build_visualizer"}[stage]
    with (
        patch.object(HerdrReporter, target, side_effect=RuntimeError("private")),
        patch.object(NullHerdrReporter, "record_publication_failure", side_effect=RuntimeError("sink")),
        patch.object(HerdrReporter, "record_publication_failure", side_effect=RuntimeError("sink")),
    ):
        await session.start_external_reporting()
        owner = session._herdr_reporter
        await session.start_external_reporting()
        assert session._herdr_reporter is owner
        assert isinstance(owner, NullHerdrReporter if stage == "factory" else HerdrReporter)
        assert session.workflow_visualizer_destination == "unavailable"
        assert not session._herdr_reporting_started
        outcome = await session.close_external_reporting()
    assert outcome.replacement == "uncertain"
    assert outcome.resources == "drained"


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_activation_failure_with_public_cancellation(
    tmp_path: Path, fake_herdr: object, failure: type[BaseException]
) -> None:
    """Failed activation still closes its assigned owner before public cancellation escapes."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def fail_start() -> None:
        """Fail only after the public caller has requested cancellation."""
        entered.set()
        await release.wait()
        raise failure()

    with patch.object(HerdrReporter, "start", side_effect=fail_start):
        waiter = asyncio.create_task(session.start_external_reporting())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        waiter.cancel()
        await asyncio.sleep(0)
        waiter.cancel()
        assert not waiter.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert session._herdr_close_task is not None
        assert session._herdr_close_task.done()
        outcome = session._herdr_close_task.result()
        assert outcome.replacement == "uncertain" and outcome.resources == "drained"
        assert session._herdr_reporter is reporter
        assert reporter._transport.closed and reporter._transport.resources_drained
        assert not session._herdr_reporting_started
        assert not reporter.allows_viewer_admission()


async def test_enabled_close_before_start_has_no_commands(tmp_path: Path, fake_herdr: object) -> None:
    """Closing an enabled but inactive lifetime permanently refuses assembly."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(HerdrReporter, "build", side_effect=AssertionError("late build")):
        outcome = await session.close_external_reporting()
        await session.start_external_reporting(interactive=True)
    assert outcome.replacement == "safe" and outcome.resources == "drained"
    assert session._herdr_start_task is None


@pytest.mark.parametrize("gateway", ["start", "drain"])
async def test_public_gateway_repeated_cancel_joins_owner(
    tmp_path: Path, fake_herdr: object, gateway: str
) -> None:
    """Cancellation of public waiters does not cancel activation or final local work."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    entered, release = asyncio.Event(), asyncio.Event()
    reporter = session._herdr_reporter

    async def start() -> None:
        entered.set()
        await release.wait()

    async def drain() -> HerdrReporterCloseOutcomeDAO:
        entered.set()
        await release.wait()
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    if gateway == "drain":
        await session.close_external_reporting()
    with (
        patch.object(session, "_prepare_herdr_reporter", new_callable=AsyncMock, return_value=reporter),
        patch.object(reporter, "start", side_effect=start),
        patch.object(reporter, "drain_retained_external_resources", side_effect=drain),
    ):
        operation = (
            session.start_external_reporting
            if gateway == "start"
            else session.drain_retained_external_resources
        )
        waiter = asyncio.create_task(operation())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        for _ in range(3):
            waiter.cancel()
            await asyncio.sleep(0)
        owner = session._herdr_start_task if gateway == "start" else session._herdr_retired_drain_task
        assert owner is not None and not owner.done() and not waiter.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    assert owner.done() and not owner.cancelled()
    assert session._herdr_close_task is not None and session._herdr_close_task.done()


async def test_disabled_activation_allocates_no_task(tmp_path: Path) -> None:
    """Disabled activation is synchronous classification only, including repeats."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch("asyncio.create_task", side_effect=AssertionError("task")):
        await session.start_external_reporting(interactive=True)
        await session.start_external_reporting(interactive=True)
    assert session._herdr_start_task is None


async def test_activation_is_once_and_retains_attempted_owner(tmp_path: Path, fake_herdr: object) -> None:
    """Repeated startup never replaces an attempted adapter, even on failure."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = NullHerdrReporter(destination="unavailable")
    with patch.object(
        session, "_prepare_herdr_reporter", new_callable=AsyncMock, return_value=reporter
    ) as prepare:
        with patch.object(
            reporter, "start", new_callable=AsyncMock, side_effect=RuntimeError("private")
        ) as start:
            await session.start_external_reporting(interactive=True)
            await session.start_external_reporting(interactive=True)
    prepare.assert_awaited_once()
    start.assert_awaited_once()
    assert session._herdr_reporter is reporter
    assert session.workflow_visualizer_destination == "unavailable"
    assert session._herdr_close_uncertain


async def test_close_revokes_and_joins_once(tmp_path: Path) -> None:
    """Close retains its task and attempts transport after reporter failure."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    calls: list[str] = []

    async def fail_close() -> None:
        calls.append("reporter")
        raise RuntimeError("private")

    with patch.object(reporter, "revoke_viewer_admission", side_effect=lambda: calls.append("revoke")):
        with patch.object(reporter, "close", side_effect=fail_close):
            with patch.object(reporter, "close_transport", new_callable=AsyncMock) as transport:
                from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

                transport.return_value = HerdrReporterCloseOutcomeDAO(replacement="safe")
                first = await session.close_external_reporting()
                second = await session.close_external_reporting()
    assert first is second
    assert first.replacement == "uncertain"
    assert calls == ["revoke", "reporter"]
    transport.assert_awaited_once()


async def test_actual_enabled_activation_publishes_and_closes(tmp_path: Path, fake_herdr: object) -> None:
    """Actual fake-guarded adapter shares viewer transport and publishes private capture."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="persisted")
    try:
        await session.start_external_reporting(interactive=True)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        assert session.workflow_visualizer_destination == "herdr"
        assert session._herdr_reporting_started
        assert session._herdr_visualizer is not None
        assert reporter._latest is not None
        assert session._herdr_visualizer._transport is reporter._transport
        assert reporter._latest.restore_capture is session._herdr_capture
        assert reporter._latest.configuration_generation == session._herdr_configuration_generation
        await session.start_external_reporting(interactive=True)
        assert session._herdr_reporter is reporter
    finally:
        outcome = await session.close_external_reporting()
    assert outcome.resources == "drained"
    assert not reporter.allows_viewer_admission()
    assert reporter._transport.resources_drained


@pytest.mark.parametrize("persistent", [False, True])
async def test_session_retains_real_transport_and_lease_through_gc(
    tmp_path: Path, fake_herdr: "FakeHerdrFixture", monkeypatch: pytest.MonkeyPatch, persistent: bool
) -> None:
    """A retained session keeps the real child/lease reachable until one final drain."""
    import gc
    import weakref
    from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
    from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
    from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    owner = await session._prepare_herdr_reporter()
    assert isinstance(owner, HerdrReporter)
    session._herdr_reporter = owner
    owner._sequence_store.acquire()
    owner._lease_held = True
    transport = owner._transport
    original = transport._terminate_and_reap
    attempts = 0
    entered, release = asyncio.Event(), asyncio.Event()

    async def reap(*, process: asyncio.subprocess.Process) -> None:
        """Hold only this fixture-owned process at the real reap boundary."""
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise OSError("synthetic-reap")
        entered.set()
        await release.wait()
        if persistent:
            raise OSError("synthetic-persistent-reap")
        await original(process=process)

    monkeypatch.setattr(target=transport, name="_terminate_and_reap", value=reap)
    admission = RecordingAdmission()
    contender = HerdrSequenceStore(
        state_root=owner._config.state_root,
        socket_namespace=owner._config.socket_path or "default",
        pane_id=owner._config.pane_id,
    )
    waiter = None
    try:
        await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=admission)
        process = transport._active
        assert process is not None
        outcome = await session.close_external_reporting()
        assert outcome.resources == "retained" and outcome.replacement == "uncertain"
        lease = owner._sequence_store
        session_ref, reporter_ref = weakref.ref(session), weakref.ref(owner)
        retained_sessions = [session]
        del session, owner
        gc.collect()
        retained = retained_sessions[0]
        assert session_ref() is retained and reporter_ref() is retained._herdr_reporter
        assert retained._herdr_reporter._sequence_store is lease
        assert transport._active is process
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        waiter = asyncio.create_task(retained.finish_retired_reporting_cleanup())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        release.set()
        assert retained._herdr_retired_drain_task is not None
        final = await retained._herdr_retired_drain_task
        assert final.replacement == "uncertain"
        assert final.resources == ("retained" if persistent else "drained")
        assert attempts == 3 and len(admission.results) == 1
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
        if persistent:
            await asyncio.sleep(0)
            assert not waiter.done()
            assert transport._active is process
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
        else:
            await waiter
            assert process.returncode is not None and transport.resources_drained
            contender.acquire()
        assert await retained.drain_retained_external_resources() is final
        assert attempts == 3
    finally:
        release.set()
        current = session_ref() if "session_ref" in locals() else session
        if current is not None and current._herdr_finish_cleanup_task is not None and persistent:
            current._herdr_finish_cleanup_task.cancel()
        if waiter is not None:
            await asyncio.gather(waiter, return_exceptions=True)
        monkeypatch.setattr(target=transport, name="_terminate_and_reap", value=original)
        if not transport.resources_drained:
            await transport._drain_quarantined_resources()
        if current is not None and isinstance(current._herdr_reporter, HerdrReporter):
            await current._herdr_reporter._release_lease()
        contender.close()


@pytest.mark.parametrize("persistent", [False, True])
async def test_lease_only_session_quarantine(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, persistent: bool
) -> None:
    """The explicit retained session root preserves a real lease without a child."""
    import gc
    import weakref
    from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = await session._prepare_herdr_reporter()
    assert isinstance(reporter, HerdrReporter)
    session._herdr_reporter = reporter
    lease = reporter._sequence_store
    lease.acquire()
    reporter._lease_held = True
    contender = HerdrSequenceStore(
        state_root=reporter._config.state_root,
        socket_namespace=reporter._config.socket_path or "default",
        pane_id=reporter._config.pane_id,
    )
    original_close = lease.close
    attempts = 0

    def unlock() -> None:
        """Fail actual lease release, not transport evidence or a property getter."""
        nonlocal attempts
        attempts += 1
        if attempts == 1 or persistent:
            raise OSError("synthetic-unlock")
        original_close()

    try:
        with patch.object(lease, "close", side_effect=unlock):
            outcome = await session.close_external_reporting()
            assert outcome.resources == "retained" and outcome.replacement == "uncertain"
            assert reporter._transport.resources_drained and reporter._transport.closed
            retained_sessions = [session]
            session_ref, reporter_ref = weakref.ref(session), weakref.ref(reporter)
            del session, reporter
            gc.collect()
            retained = retained_sessions[0]
            assert session_ref() is retained
            assert reporter_ref() is retained._herdr_reporter
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
            final = await retained.drain_retained_external_resources()
            assert final.replacement == "uncertain"
            assert final.resources == ("retained" if persistent else "drained")
            assert await retained.drain_retained_external_resources() is final
            assert attempts == 2
            if persistent:
                with pytest.raises(HerdrSequenceUnavailableError):
                    contender.acquire()
            else:
                contender.acquire()
            assert fake_herdr.capture.read_text() == ""
    finally:
        original_close()
        contender.close()


async def test_remote_only_uncertainty_is_collectable(tmp_path: Path, fake_herdr: FakeHerdrFixture) -> None:
    """Remote uncertainty alone neither retains a lease nor blocks final session disposal."""
    import gc
    import weakref

    async def retire() -> tuple[weakref.ReferenceType[SloAgentSession], weakref.ReferenceType[HerdrReporter]]:
        """Drop all local strong references after the real cleanup gateways return."""
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        reporter = await session._prepare_herdr_reporter()
        assert isinstance(reporter, HerdrReporter)
        session._herdr_reporter = reporter
        reporter._sequence_store.acquire()
        reporter._lease_held = True
        reporter._cleanup_failed = True
        outcome = await session.finish_retired_reporting_cleanup()
        assert outcome.replacement == "uncertain" and outcome.resources == "drained"
        assert session._herdr_retired_drain_task is None
        assert reporter._transport.closed and reporter._transport.resources_drained
        assert not reporter.retains_external_resources
        return weakref.ref(session), weakref.ref(reporter)

    session_ref, reporter_ref = await retire()
    gc.collect()
    assert session_ref() is None and reporter_ref() is None
    assert fake_herdr.capture.read_text() == ""


async def test_enabled_preparation_assembles_after_capture(tmp_path: Path, fake_herdr: object) -> None:
    """Real factory returns inert shared collaborators after private preparation."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._herdr_interactive = True
    await session.rename_session(session_name="persisted")
    reporter = await session._prepare_herdr_reporter()
    assert isinstance(reporter, HerdrReporter)
    assert session._herdr_capture is not None
    assert reporter._worker is None
    assert reporter._start_task is None
    assert reporter._transport._config is reporter._config


async def test_invalid_identity_never_prepares_capture(tmp_path: Path, fake_herdr: object) -> None:
    """Ordinary slug sessions stay valid but cannot activate Herdr."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", session_id="ordinary-slug")
    )
    with patch.object(session, "_prepare_herdr_capture_inputs", new_callable=AsyncMock) as prepare:
        reporter = await session._prepare_herdr_reporter()
    assert reporter.destination == "unavailable"
    prepare.assert_not_called()


@pytest.mark.parametrize("resources", ["drained", "retained"])
async def test_intermediate_uncertainty_survives_final_safe(
    tmp_path: Path, resources: Literal["drained", "retained"]
) -> None:
    """Final local drain cannot erase earlier remote or cleanup-defect evidence."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    with (
        patch.object(
            reporter,
            "close",
            new_callable=AsyncMock,
            return_value=HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources=resources),
        ),
        patch.object(
            reporter,
            "close_transport",
            new_callable=AsyncMock,
            return_value=HerdrReporterCloseOutcomeDAO(replacement="safe"),
        ),
    ):
        outcome = await session.close_external_reporting()
    assert outcome.replacement == "uncertain"
    assert outcome.resources == "drained"
