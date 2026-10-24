"""Independent observations of the documented session activation contract."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("interactive", [False, True])
async def test_first_eligible_mode_and_failed_start_retention(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, interactive: bool
) -> None:
    """Observe that a noncancelled failed starter retains but does not close its owner."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    reporter = session._herdr_reporter
    with (
        patch.object(session, "_prepare_herdr_reporter", new_callable=AsyncMock, return_value=reporter),
        patch.object(reporter, "start", side_effect=RuntimeError("synthetic activation defect")),
        patch.object(reporter, "close", wraps=reporter.close) as close,
    ):
        await session.start_external_reporting(interactive=interactive)
        await session.start_external_reporting(interactive=not interactive)
        assert session._herdr_interactive is interactive
        assert session._herdr_reporter is reporter
        assert session.workflow_visualizer_destination == "unavailable"
        assert session._herdr_close_uncertain
        assert session._herdr_close_task is None
        close.assert_not_called()
        print("failed_start_returned_without_cleanup", interactive, True)
        await session.close_external_reporting()
        close.assert_awaited_once()
        await session.finish_retired_reporting_cleanup()
