"""App-owned viewer task registration and identity cleanup contracts."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_registry_captures_owner_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration captures the owner synchronously and keeps one pending parent."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    entered = asyncio.Event()
    release = asyncio.Event()
    owners: list[SloAgentSession] = []

    async def run(*, parent_session_id: str, session: SloAgentSession) -> None:
        """Hold the registered worker without performing external operations."""
        assert parent_session_id == "parent"
        owners.append(session)
        entered.set()
        await release.wait()

    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "_run_visualizer_launch", side_effect=run):
                app._schedule_visualizer_launch(parent_session_id="parent")
                task = app._visualizer_launch_tasks["parent"]
                app._schedule_visualizer_launch(parent_session_id="parent")
                assert app._visualizer_launch_tasks["parent"] is task
                await asyncio.wait_for(entered.wait(), timeout=2)
                assert owners == [session]
                release.set()
                await task
                await asyncio.sleep(0)
                assert app._visualizer_launch_tasks == {}


async def test_shutdown_joins_viewer_before_reporter_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown waits outside the submission gate for a cancelled worker finalizer."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    entered, finalizing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    closed: list[bool] = []
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), supports_explicit_caching=False
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)

        async def run(*, parent_session_id: str, session: SloAgentSession) -> None:
            """Require the submission gate during cleanup to expose lock inversion."""
            entered.set()
            try:
                await asyncio.Future()
            finally:
                async with app._prompt_submission_lock:
                    finalizing.set()
                    await release.wait()

        original_close = session.close_external_reporting

        async def close() -> object:
            """Assert registry termination at the real reporter close boundary."""
            closed.append(not app._visualizer_launch_tasks)
            return await original_close()

        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch.object(app, "_run_visualizer_launch", side_effect=run),
                patch.object(session, "close_external_reporting", side_effect=close),
            ):
                app._schedule_visualizer_launch(parent_session_id="parent")
                task = app._visualizer_launch_tasks["parent"]
                await asyncio.wait_for(entered.wait(), timeout=2)
                shutdown = asyncio.create_task(app.on_unmount())
                try:
                    await asyncio.wait_for(finalizing.wait(), timeout=2)
                    assert not closed
                    shutdown.cancel()
                    shutdown.cancel()
                    release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(shutdown, timeout=2)
                    assert task.done() and app._visualizer_launch_tasks == {}
                    assert closed == [True, True]  # Initial close and the session's final drain attempt.
                finally:
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, shutdown, return_exceptions=True)


async def test_registry_auto_off_refuses_before_task_registration(tmp_path: Path) -> None:
    """The shared scheduler rejects auto-off before creating either destination task."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "_run_visualizer_launch") as worker:
                app._schedule_visualizer_launch(parent_session_id="parent")
                tasks = tuple(app._visualizer_launch_tasks.values())
                await asyncio.gather(*tasks, return_exceptions=True)
                worker.assert_not_called()
                assert app._visualizer_launch_tasks == {}


async def test_drain_attempts_all_workers_after_completion_fault(tmp_path: Path) -> None:
    """Completion-helper failure retains handles and cannot skip the next join."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
    app = SloTUI(session=session)
    tasks = [asyncio.create_task(coro=asyncio.sleep(0)) for _ in range(2)]
    app._visualizer_launch_tasks = dict(zip(("first", "second"), tasks))
    with patch.object(app, "_on_visualizer_launch_done", side_effect=RuntimeError("private")) as done:
        with pytest.raises(RuntimeError):
            await app._cancel_visualizer_launches()
    assert done.call_count == 2
    assert all(task.done() for task in tasks)
    assert list(app._visualizer_launch_tasks.values()) == tasks
