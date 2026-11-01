"""Real platform continuation barriers; no terminal process is ever created."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.visualizer_launcher import VisualizerLauncher


async def checkpoint() -> None:
    """Yield to already queued cancellation callbacks without a timed sleep."""
    event = asyncio.Event()
    asyncio.get_running_loop().call_soon(event.set)
    await asyncio.wait_for(event.wait(), timeout=2)


@pytest.mark.parametrize("boundary", ["discovery_blocked", "spawn_blocked"])
async def test_platform_launch_join(boundary: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real launch continues once after admission and joins before cancellation escapes."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    spawns: list[list[str]] = []
    guarded_spawn = VisualizerLauncher._default_spawn
    assert getattr(guarded_spawn, "__test_stub__", False)

    def discover(*, parent_session_id: str, platform: str) -> list[str]:
        """Hold discovery after synchronous launch has admitted its policy."""
        assert parent_session_id == "captured-parent"
        if boundary == "discovery_blocked":
            entered.set()
            assert release.wait(timeout=10)
        return ["test-terminal", parent_session_id]

    def spawn(argv: list[str]) -> object:
        """Record one committed submission through the registered root test guard."""
        spawns.append(argv)
        if boundary == "spawn_blocked":
            entered.set()
            assert release.wait(timeout=10)
        result = guarded_spawn(argv)
        finished.set()
        return result

    with (
        patch.object(VisualizerLauncher, "_build_argv", side_effect=discover),
        patch.object(VisualizerLauncher, "_default_spawn", side_effect=spawn),
    ):
        task = asyncio.create_task(
            coro=VisualizerLauncher._launch_platform_joined(parent_session_id="captured-parent")
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert len(spawns) == (boundary == "spawn_blocked")
            monkeypatch.setenv("SLO_AUTO_VISUALIZE", "0")
            for _ in range(3):
                task.cancel()
                await checkpoint()
                assert not task.done() and not finished.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert finished.is_set()
            assert spawns == [["test-terminal", "captured-parent"]]
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)


@pytest.mark.parametrize("boundary", ["discovery_blocked", "spawn_blocked"])
@pytest.mark.parametrize("lifetime", ["replacement", "unmount"])
async def test_platform_commit_joins_app_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str, lifetime: str
) -> None:
    """Captured registry work finishes its real sync continuation before owner teardown."""
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel

    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    draining = asyncio.Event()
    spawns: list[list[str]] = []
    guarded_spawn = VisualizerLauncher._default_spawn
    assert getattr(guarded_spawn, "__test_stub__", False)

    def discover() -> str:
        """Block actual Linux discovery, leaving shell construction and spawn intact."""
        if boundary == "discovery_blocked":
            entered.set()
            assert release.wait(timeout=10)
        return "test-terminal"

    def spawn(argv: list[str]) -> object:
        """Submit only to the installed test guard, never subprocess.Popen."""
        spawns.append(argv)
        if boundary == "spawn_blocked":
            entered.set()
            assert release.wait(timeout=10)
        result = guarded_spawn(argv)
        finished.set()
        return result

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
        original_drain = app._cancel_visualizer_launches

        async def drain() -> None:
            """Signal teardown's real registry drain and preserve its implementation."""
            draining.set()
            await original_drain()
            assert finished.is_set()

        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch("src.tui.visualizer_launcher.sys.platform", "linux"),
                patch.object(VisualizerLauncher, "_resolve_linux_terminal", side_effect=discover),
                patch.object(VisualizerLauncher, "_default_spawn", side_effect=spawn),
                patch.object(app, "_cancel_visualizer_launches", side_effect=drain),
                patch.object(app._ensure_workflow_renderer(), "write_launch_outcome") as notice,
            ):
                app._schedule_visualizer_launch(parent_session_id="captured-parent")
                viewer = app._visualizer_launch_tasks["captured-parent"]
                assert await asyncio.to_thread(entered.wait, 2)
                app._schedule_visualizer_launch(parent_session_id="captured-parent")
                assert app._visualizer_launch_tasks == {"captured-parent": viewer}
                operation = asyncio.create_task(
                    coro=(
                        app._start_new_session(requested_name=None)
                        if lifetime == "replacement"
                        else app.on_unmount()
                    )
                )
                try:
                    await asyncio.wait_for(draining.wait(), timeout=3)
                    app._schedule_visualizer_launch(parent_session_id="rejected-parent")
                    assert "rejected-parent" not in app._visualizer_launch_tasks
                    for _ in range(3):
                        viewer.cancel()
                        operation.cancel()
                        await checkpoint()
                        assert not viewer.done() and not operation.done()
                        assert app._session is old and not finished.is_set()
                    release.set()
                    results = await asyncio.wait_for(
                        asyncio.gather(operation, return_exceptions=True), timeout=5
                    )
                    assert isinstance(results[0], asyncio.CancelledError)
                    assert finished.is_set() and viewer.done()
                    assert app._visualizer_launch_tasks == {}
                    assert len(spawns) == 1 and "captured-parent" in spawns[0][-1]
                    assert "rejected-parent" not in spawns[0][-1]
                    assert (app._session is not old) is (lifetime == "replacement")
                    notice.assert_not_called()
                finally:
                    release.set()
                    await asyncio.wait_for(
                        asyncio.gather(viewer, operation, return_exceptions=True), timeout=5
                    )
