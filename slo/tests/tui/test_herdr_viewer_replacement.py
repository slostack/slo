"""Mounted replacement drains viewer workers without holding their finalizer gate."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@pytest.mark.parametrize("cancel", [False, True])
async def test_replacement_drains_gate_using_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """Close follows terminal registry cleanup even after repeated public cancellation."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    entered, finalizing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    closed: list[bool] = []
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), supports_explicit_caching=False
        ),
    ):
        old = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=old)
        original_close = old.close_external_reporting

        async def worker(*, parent_session_id: str, session: SloAgentSession) -> None:
            """Require the real submission gate during viewer cancellation cleanup."""
            assert session is old
            entered.set()
            try:
                await asyncio.Future()
            finally:
                async with app._prompt_submission_lock:
                    finalizing.set()
                    await release.wait()

        async def close() -> HerdrReporterCloseOutcomeDAO:
            """Record registry termination at the actual old-session close boundary."""
            closed.append(not app._visualizer_launch_tasks)
            return await original_close()

        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch.object(app, "_run_visualizer_launch", side_effect=worker),
                patch.object(old, "close_external_reporting", side_effect=close),
            ):
                app._schedule_visualizer_launch(parent_session_id="parent")
                viewer = app._visualizer_launch_tasks["parent"]
                await asyncio.wait_for(entered.wait(), timeout=2)
                replacement = asyncio.create_task(coro=app._start_new_session(requested_name=None))
                try:
                    await asyncio.wait_for(finalizing.wait(), timeout=2)
                    assert old._herdr_closing and app._session is old
                    assert not closed
                    if cancel:
                        replacement.cancel()
                        await asyncio.sleep(0)
                        replacement.cancel()
                        await asyncio.sleep(0)
                        assert not replacement.done()
                    release.set()
                    results = await asyncio.wait_for(
                        asyncio.gather(replacement, return_exceptions=True), timeout=5
                    )
                    assert isinstance(results[0], asyncio.CancelledError) if cancel else results == [None]
                    assert viewer.done() and app._visualizer_launch_tasks == {}
                    assert closed == [True]
                    assert app._session is not old
                    assert app._session_replacement_task is None
                finally:
                    release.set()
                    viewer.cancel()
                    await asyncio.gather(viewer, replacement, return_exceptions=True)


@pytest.mark.parametrize("entry", ["submit", "accepted", "register", "queue", "handoff", "inbox", "viewer"])
async def test_transition_refuses_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    """Transition alone blocks each entry even if successor delivery is already initialized."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._queued_prompt_text = "preserve"
        app._session_transitioning = True
        app._delivery_quiescing = False
        with (
            patch.object(app, "_run_prompt") as run,
            patch.object(app._chat_transcript, "echo_user") as echo,
            patch.object(app, "_run_visualizer_launch") as viewer,
            patch.object(app._inbox_store, "claim_next", return_value=None) as claim,
        ):
            async with app._prompt_submission_lock:
                if entry == "accepted":
                    await app._start_accepted_prompt(text="refused")
                elif entry == "register":
                    app._register_prompt_task(text="refused")
                elif entry == "queue":
                    await app._queue_prompt(text="refused")
                elif entry == "handoff":
                    task = asyncio.current_task()
                    assert task is not None
                    app._in_flight_task = task
                    await app._start_queued_prompt_if_idle(completed_task=task)
                    app._in_flight_task = None
                elif entry == "inbox":
                    await app._claim_and_handle_idle_inbox_message()
                elif entry == "viewer":
                    app._schedule_visualizer_launch(parent_session_id="refused")
            if entry == "submit":
                await app._submit_or_queue_prompt(text="refused")
            tasks = list(app._visualizer_launch_tasks.values())
            if app._in_flight_task is not None:
                tasks.append(app._in_flight_task)
            await asyncio.gather(*tasks, return_exceptions=True)
            app._in_flight_task = None
            app._session_transitioning = False
            run.assert_not_called()
            echo.assert_not_called()
            viewer.assert_not_called()
            claim.assert_not_called()
            assert app._queued_prompt_text == "preserve"


@pytest.mark.parametrize("shutdown", [False, True])
async def test_replacement_joins_actual_platform_thread(tmp_path: Path, shutdown: bool) -> None:
    """Real async selector joins a committed fake platform thread before adoption."""
    import threading

    from src.tui.visualizer_launcher import VisualizerLauncher

    entered, release = threading.Event(), threading.Event()
    old = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
    )
    app = SloTUI(session=old)

    def launch(*, parent_session_id: str) -> bool:
        """Stand in for window creation inside the actual retained thread."""
        entered.set()
        assert release.wait(timeout=10)
        return True

    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch.object(VisualizerLauncher, "_auto_visualize_enabled", return_value=True),
            patch.object(VisualizerLauncher, "launch", side_effect=launch),
            patch.object(app._ensure_workflow_renderer(), "write_launch_outcome") as notice,
        ):
            app._schedule_visualizer_launch(parent_session_id="parent")
            viewer = app._visualizer_launch_tasks["parent"]
            assert await asyncio.to_thread(entered.wait, 2)
            replacement = asyncio.create_task(coro=app._start_new_session(requested_name=None))
            unmount = None
            try:
                # Gate acquisition is the deterministic commit-registration boundary.
                async with app._prompt_submission_lock:
                    pass
                while not app._session_transitioning:
                    await asyncio.sleep(0)
                replacement.cancel()
                await asyncio.sleep(0)
                replacement.cancel()
                if shutdown:
                    unmount = asyncio.create_task(coro=app.on_unmount())
                    await asyncio.sleep(0)
                assert app._session is old and not viewer.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(replacement, timeout=5)
                if unmount is not None:
                    await asyncio.wait_for(unmount, timeout=5)
                assert viewer.done() and app._visualizer_launch_tasks == {}
                assert app._session is not old
                assert app._session._herdr_closing is shutdown
                notice.assert_not_called()
            finally:
                release.set()
                await asyncio.gather(viewer, replacement, return_exceptions=True)
                if unmount is not None:
                    await asyncio.gather(unmount, return_exceptions=True)


async def test_viewer_cleanup_error_still_commits(tmp_path: Path) -> None:
    """A throwing viewer helper and notice cannot strand real close or lease release."""
    old = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
    )
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        store = app._lease_store
        assert store is not None
        assert await store.read(session_id=old.session_id) is not None
        with (
            patch.object(app, "_cancel_visualizer_launches", side_effect=RuntimeError("private fault")),
            patch.object(
                app._chat_transcript, "write_transcript_line", side_effect=RuntimeError("notice fault")
            ),
            patch.object(old, "close_external_reporting", wraps=old.close_external_reporting) as close,
        ):
            await app._start_new_session(requested_name=None)
        close.assert_awaited_once()
        assert old._herdr_close_task is not None and old._herdr_close_task.done()
        assert app._session is not old
        assert not app._session_transitioning
        assert not app._replacement_delivery_safe and app._delivery_quiescing
        assert await store.read(session_id=old.session_id) is None
        assert await store.read(session_id=app._session.session_id) is None
        assert app._render_event not in old._subscribers
        assert app._render_event in app._session._subscribers
