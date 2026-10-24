"""Independent review probe: configured detail must reach real session publication."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture


async def test_detail_profile_reaches_session_publication(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activate with the registered fake and inspect actual published facts."""
    monkeypatch.setenv(name="SLO_HERDR_METADATA_PROFILE", value="detail")
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="high",
            enable_history=False,
        )
    )
    try:
        await session.start_external_reporting(interactive=True)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        assert reporter._config.metadata_profile == "detail"
        assert reporter._latest is not None
        tokens = {token.key: token.value for token in reporter._latest.snapshot.tokens}
        assert tokens.get("reasoning") == "high", tokens
    finally:
        await session.close_external_reporting()
        await session.finish_retired_reporting_cleanup()
