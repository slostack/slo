"""Captured profile reaches the shared interactive/headless publication seam."""

import asyncio
import json
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.reporter import HERDR_TOKEN_KEYS, HerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO
from src.auth.credential_resolver import CredentialResolver
from unittest.mock import patch
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("interactive", [True, False])
@pytest.mark.parametrize("profile", ["compact", "detail", "invalid-private-profile"])
async def test_profile_reaches_executable(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    interactive: bool,
    profile: str,
) -> None:
    """Exercise both activation modes through actual publication and registered CLI."""
    monkeypatch.setenv(name="SLO_HERDR_METADATA_PROFILE", value=profile)
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="high",
            enable_history=False,
        )
    )
    try:
        await session.start_external_reporting(interactive=interactive)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        assert reporter._latest is not None
        tokens = {token.key: token.value for token in reporter._latest.snapshot.tokens}
        assert tokens.get("reasoning") == ("high" if profile == "detail" else None)
        async with asyncio.timeout(5):
            while reporter._display_ack_revision != reporter._revision:
                await asyncio.sleep(0.01)
        initial_command_count = len(fake_herdr.capture.read_text().splitlines())
        monkeypatch.setenv(
            name="SLO_HERDR_METADATA_PROFILE", value="compact" if profile == "detail" else "detail"
        )
        session._usage_snapshot = SessionUsageSnapshotDAO(
            active_model_name="private-model-sentinel",
            active_reasoning_level="high",
            provider_effort="private-effort-sentinel",
            usage_available=True,
            latest_turn=TokenUsageTotalsDAO(input_tokens=1000, output_tokens=200, total_tokens=1200),
            session_totals=TokenUsageTotalsDAO(
                total_tokens=2400, cache_read_input_tokens=300, cache_creation_input_tokens=40
            ),
            requests_per_minute_limit=60,
            tokens_per_minute_limit=10000,
            output_cap_tokens=2000,
            provider_budget_tokens=4000,
        )
        with (
            patch.object(CredentialResolver, "require", side_effect=AssertionError("credential lookup")),
            patch.object(CredentialResolver, "resolve", side_effect=AssertionError("credential lookup")),
        ):
            token = session.set_operator_attention(reason="Authentication required")
            async with asyncio.timeout(5):
                while reporter._display_ack_revision != reporter._revision:
                    await asyncio.sleep(0.01)
            assert reporter._latest is not None
            expected = (
                {
                    "reasoning": "high",
                    "turn": "1.2k",
                    "in": "1.0k",
                    "out": "200",
                    "cache_read": "300",
                    "cache_write": "40",
                    "rpm": "60",
                    "tpm": "10k",
                    "out_cap": "2.0k",
                    "budget": "4.0k",
                }
                if profile == "detail"
                else {"session_tokens": "2.4k"}
            )
            assert {item.key: item.value for item in reporter._latest.snapshot.tokens} == expected
            assert reporter._latest.snapshot.state == "blocked"
            session.clear_operator_attention(token=token)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        values = [
            command[index + 1]
            for command in commands
            for index, word in enumerate(command)
            if word == "--token"
        ]
        assert ("reasoning=high" in values) is (profile == "detail")
        metadata = [
            command
            for command in commands[initial_command_count:]
            if command[:2] == ["pane", "report-metadata"]
        ]
        last_set = next(index for index in reversed(range(len(metadata))) if "--token" in metadata[index])
        clears: list[str] = []
        for command in reversed(metadata[:last_set]):
            if "--token" in command:
                break
            clears[0:0] = [
                command[index + 1] for index, word in enumerate(command) if word == "--clear-token"
            ]
        assert clears == [key for key in HERDR_TOKEN_KEYS if key not in expected]
        for sentinel in (
            "invalid-private-profile",
            "private-model-sentinel",
            "private-effort-sentinel",
            str(tmp_path),
        ):
            assert sentinel not in fake_herdr.capture.read_text()
        assert all(f"{key}={value}" in values for key, value in expected.items())
    finally:
        await session.close_external_reporting()
        await session.finish_retired_reporting_cleanup()
        assert not session._herdr_reporter.retains_external_resources


@pytest.mark.parametrize("interactive", [True, False])
async def test_disabled_profile_does_no_activation_work(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    interactive: bool,
) -> None:
    """Even detail opt-in cannot bypass disabled task, projection or CLI cutoffs."""
    monkeypatch.setenv(name="SLO_HERDR_METADATA_PROFILE", value="detail")
    monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, enable_history=False))
    with patch.object(session, "_prepare_herdr_reporter", side_effect=AssertionError("assembly")):
        await session.start_external_reporting(interactive=interactive)
        token = session.set_operator_attention(reason="Authentication required")
        session.clear_operator_attention(token=token)
        assert session._herdr_start_task is None
        assert not session._herdr_reporting_started
        assert fake_herdr.capture.read_text() == ""
        await session.close_external_reporting()
        await session.finish_retired_reporting_cleanup()
