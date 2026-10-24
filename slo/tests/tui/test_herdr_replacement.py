"""Mounted irreversible replacement uses actual session lifetime gateways."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.herdr.service import NullHerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@pytest.mark.parametrize("cancel", [False, True])
async def test_new_commit_joins_old_close(tmp_path: Path, cancel: bool) -> None:
    """Old revocation precedes awaits; caller cancellation cannot roll adoption back."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_close = NullHerdrReporter.close

    async def close(self: NullHerdrReporter) -> HerdrReporterCloseOutcomeDAO:
        """Hold the real session's reporter boundary, not the app transaction."""
        if self is old._herdr_reporter:
            entered.set()
            await release.wait()
        return await original_close(self)

    async with app.run_test() as pilot:
        await pilot.pause()
        with patch.object(NullHerdrReporter, "close", new=close):
            task = asyncio.create_task(coro=app._start_new_session(requested_name=None))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert old._herdr_closing
                assert app._session is old
                assert app._render_event in old._subscribers
                retained = app._session_replacement_task
                assert retained is not None and not retained.done()
                if cancel:
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    await asyncio.sleep(0)
                    assert not task.done() and not retained.done()
                release.set()
                if cancel:
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    await task
                assert app._session is not old
                assert app._render_event not in old._subscribers
                assert app._session._subscribers.count(app._render_event) == 1
                assert app._session_replacement_task is None
                assert old._herdr_close_task is not None and old._herdr_close_task.done()
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=old.session_id) is None
                lease = await app._lease_store.read(session_id=app._session.session_id)
                assert lease is not None and lease.owner_id == app._session_owner_id
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", ["preparation", "unsubscribe", "clear", "inbox"])
async def test_new_committed_fault_never_restores_old(tmp_path: Path, failure: str) -> None:
    """Optional cleanup/render faults cannot strand the closed selected owner."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        target, name = {
            "preparation": (app, "_cancel_session_preparation"),
            "unsubscribe": (old, "unsubscribe"),
            "clear": (app, "_clear_transcript_and_prompt_queue"),
            "inbox": (app, "_initialize_session_delivery"),
        }[failure]
        with (
            patch.object(target, name, side_effect=RuntimeError("private defect")),
            patch.object(app, "_write_adapter_line", side_effect=RuntimeError("sink defect")),
        ):
            await app._start_new_session(requested_name=None)
        assert app._session is not old
        assert old._herdr_closing
        assert app._session._subscribers.count(app._render_event) == 1
        assert app._session_replacement_task is None


@pytest.mark.parametrize("retained", [False, True])
async def test_new_uncertainty_is_sticky(tmp_path: Path, retained: bool) -> None:
    """Repeated adoption keeps one explicit owner only for local retention."""
    import gc
    import weakref
    from unittest.mock import PropertyMock

    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    old_ref = weakref.ref(old)
    reporter = old._herdr_reporter
    app = SloTUI(session=old)
    outcome = HerdrReporterCloseOutcomeDAO(
        replacement="uncertain", resources="retained" if retained else "drained"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch.object(reporter, "close", return_value=outcome),
            patch.object(reporter, "close_transport", return_value=outcome),
            patch.object(
                type(reporter), "retains_external_resources", new_callable=PropertyMock, return_value=retained
            ),
        ):
            await app._start_new_session(requested_name=None)
        assert app._herdr_successor_suppressed
        assert app._session._herdr_suppressed
        assert app._session.workflow_visualizer_destination == "unavailable"
        assert app._retired_herdr_session is (old if retained else None)
        del old
        gc.collect()
        assert (old_ref() is not None) is retained
        await app._start_new_session(requested_name=None)
        gc.collect()
        assert app._session._herdr_suppressed
        assert app._retired_herdr_session is (old_ref() if retained else None)
        assert app._session_replacement_task is None


@pytest.mark.parametrize("failure", ["absent", "mismatch", "error"])
async def test_new_failed_release_disables_successor_delivery(tmp_path: Path, failure: str) -> None:
    """Failed captured-ID release never permits another lease or timer renewal."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        store = app._lease_store
        assert store is not None
        if failure == "absent":
            await store.release(session_id=old.session_id)
        if failure == "mismatch":
            await store.acquire(session_id=old.session_id, owner_id="other", ttl_seconds=60)
        original_release = store.release

        async def release(*, session_id: str, owner_id: str | None = None) -> bool:
            """Fail only the captured predecessor release; preserve normal teardown."""
            if failure == "error" and session_id == old.session_id:
                raise RuntimeError("private lease failure")
            return await original_release(session_id=session_id, owner_id=owner_id)

        with patch.object(store, "release", side_effect=release):
            await app._start_new_session(requested_name=None)
        assert not app._replacement_delivery_safe and app._delivery_quiescing
        await app._renew_session_lease()
        await app._poll_session_inbox()
        assert await store.read(session_id=app._session.session_id) is None
        await app._start_new_session(requested_name=None)
        assert await store.read(session_id=app._session.session_id) is None


async def test_retired_owner_final_drain_is_joined(tmp_path: Path) -> None:
    """Unmount joins one local-only drain, including repeated waiter cancellation."""

    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    reporter = old._herdr_reporter
    app = SloTUI(session=old)
    entered = asyncio.Event()
    release = asyncio.Event()
    retained = True
    calls: list[str] = []

    def retains_resources(owner: NullHerdrReporter) -> bool:
        """Keep the synthetic retention on the predecessor, never its null successor."""
        return owner is reporter and retained

    async def close() -> HerdrReporterCloseOutcomeDAO:
        """Return retained local evidence through the actual session close."""
        calls.append("close")
        return HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained")

    async def drain() -> HerdrReporterCloseOutcomeDAO:
        """Resolve the local drain without another remote-close call."""
        nonlocal retained
        calls.append("drain")
        entered.set()
        await release.wait()
        retained = False
        return HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="drained")

    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch.object(reporter, "close", side_effect=close),
            patch.object(
                reporter,
                "close_transport",
                return_value=HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained"),
            ),
            patch.object(reporter, "drain_retained_external_resources", side_effect=drain),
            patch.object(
                type(reporter),
                "retains_external_resources",
                new=property(retains_resources),
            ),
        ):
            await app._start_new_session(requested_name=None)
            task = asyncio.create_task(coro=app.on_unmount())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert app._retired_herdr_session is old
                assert not app._session._herdr_reporter.retains_external_resources
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert app._retired_herdr_session is None
                assert calls == ["close", "drain"]
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


async def test_new_candidate_lease_rollback_failure_keeps_ui_progress(tmp_path: Path) -> None:
    """A failed candidate release after partial setup cannot skip adopted UI cleanup."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._queue_prompt(text="must not cross adoption")
        store = app._lease_store
        assert store is not None
        original_release = store.release
        original_initialize = app._initialize_session_delivery

        async def initialize() -> None:
            """Fail after real acquisition and timers to exercise partial rollback."""
            await original_initialize()
            raise RuntimeError("inbox setup failed")

        async def release(*, session_id: str, owner_id: str | None = None) -> bool:
            """Old release succeeds; candidate rollback fails independently."""
            if session_id != old.session_id:
                raise RuntimeError("candidate release failed")
            return await original_release(session_id=session_id, owner_id=owner_id)

        with (
            patch.object(app, "_initialize_session_delivery", side_effect=initialize),
            patch.object(store, "release", side_effect=release),
        ):
            await app._start_new_session(requested_name=None)
        assert app._session is not old
        assert app._queued_prompt_text is None
        assert app._lease_timer is None and app._inbox_timer is None
        assert app._workflow_app_service is None and app._workflow_renderer is None
        assert not app._replacement_delivery_safe and app._delivery_quiescing
