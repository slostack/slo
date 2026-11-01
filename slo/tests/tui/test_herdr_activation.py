"""Canonical app runtime ordering before mounted reporting acceptance."""

from pathlib import Path
from unittest.mock import patch

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_shared_runtime_activates_before_context_and_title(tmp_path: Path) -> None:
    """Record the shared mount/adoption seam without external reporting I/O.

    This orchestration test establishes ordering only. Mounted real-adapter,
    cancellation and native-capture acceptance require separate tests.
    """
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    calls: list[str] = []

    async def delivery() -> None:
        """Record delivery before the reporting activation boundary."""
        calls.append("delivery")

    async def reporting(*, interactive: bool = False) -> None:
        """Require the explicit interactive eligibility input from the app."""
        assert interactive is True
        calls.append("reporting")

    async def context() -> None:
        """Record the context snapshot before either presentation refresh."""
        calls.append("context")

    with (
        patch.object(app, "_initialize_session_delivery", side_effect=delivery),
        patch.object(session, "start_external_reporting", side_effect=reporting),
        patch.object(session, "refresh_context_window_snapshot", side_effect=context),
        patch.object(app, "_refresh_title_bar", side_effect=lambda: calls.append("title")),
        patch.object(app, "_refresh_usage_status_bar", side_effect=lambda: calls.append("usage")),
    ):
        await app._finish_replacement_runtime()

    assert calls == ["delivery", "reporting", "context", "title", "usage"]
