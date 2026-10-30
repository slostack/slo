"""Offline destination and retained platform-launch lifetime contracts."""

import asyncio
import threading
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.tui.visualizer_launcher import VisualizerLauncher
from src.agents.slo_agent.herdr.dao import VisualizerLaunchOutcomeDAO


@pytest.mark.parametrize("destination", ["platform", "herdr", "unavailable"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_destination_selector(destination: str, enabled: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-off suppresses both destinations; Herdr refusal never falls back."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1" if enabled else "0")
    session = Mock(workflow_visualizer_destination=destination)
    session.open_workflow_visualizer = AsyncMock(return_value=VisualizerLaunchOutcomeDAO(status="skipped"))
    with patch.object(VisualizerLauncher, "_launch_platform_joined", new_callable=AsyncMock) as platform:
        platform.return_value = VisualizerLaunchOutcomeDAO(status="opened")
        outcome = await VisualizerLauncher.launch_async(parent_session_id="requested-parent", session=session)
    expected = (
        "skipped"
        if not enabled or destination == "herdr"
        else ("opened" if destination == "platform" else "failed")
    )
    assert outcome.status == expected
    assert platform.await_count == int(enabled and destination == "platform")
    assert session.open_workflow_visualizer.await_count == int(enabled and destination == "herdr")
    if enabled and destination == "herdr":
        session.open_workflow_visualizer.assert_awaited_once_with(parent_session_id="requested-parent")


async def test_async_platform_keeps_root_spawn_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual async platform path still traverses the suite-wide spawn guard."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    session = Mock(workflow_visualizer_destination="platform")
    with patch.object(VisualizerLauncher, "_build_argv", return_value=["never-real-terminal"]):
        outcome = await VisualizerLauncher.launch_async(parent_session_id="parent", session=session)
    assert outcome.status == "opened"


@pytest.mark.parametrize("opened", [True, False])
async def test_platform_join_reports_terminal_result(opened: bool) -> None:
    """The retained platform operation maps its bool without claiming paint."""
    with patch.object(VisualizerLauncher, "launch", return_value=opened) as launch:
        outcome = await VisualizerLauncher._launch_platform_joined(parent_session_id="parent")
    assert outcome.status == ("opened" if opened else "failed")
    launch.assert_called_once_with(parent_session_id="parent")


async def test_platform_join_retrieves_error() -> None:
    """Discovery errors become fixed failed outcomes, never raw diagnostics."""
    with patch.object(VisualizerLauncher, "launch", side_effect=RuntimeError("private")):
        outcome = await VisualizerLauncher._launch_platform_joined(parent_session_id="parent")
    assert outcome.status == "failed"
    assert "private" not in outcome.model_dump_json()


async def test_platform_join_retains_thread_through_repeated_cancel() -> None:
    """Cancelling the waiter twice cannot abandon committed platform work."""
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()

    def launch(*, parent_session_id: str) -> bool:
        """Hold an offline launch at a deterministic thread barrier."""
        assert parent_session_id == "parent"
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        finished.set()
        return True

    with patch.object(VisualizerLauncher, "launch", side_effect=launch):
        task = asyncio.create_task(VisualizerLauncher._launch_platform_joined(parent_session_id="parent"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
