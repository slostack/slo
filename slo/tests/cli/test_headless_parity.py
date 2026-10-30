"""Whole-stream headless parity through real config-backed Faux sessions."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.cli.headless import HeadlessRunner
from tests.state_isolation import FakeHerdrFixture


async def test_enabled_disabled_whole_jsonl_parity(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compare every event field, retaining ordering and all metadata."""
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-parity-secret"
    )
    monkeypatch.setattr(
        target=CredentialResolver, name="resolve", value=classmethod(lambda cls, **kw: credential)
    )
    streams: list[list[dict[str, object]]] = []
    for disabled in (False, True):
        monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1" if disabled else "0")
        runner = HeadlessRunner(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        before = fake_herdr.capture.read_bytes()
        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="parity answer")]),
                supports_explicit_caching=False,
            ),
        ) as factory:
            assert await runner.invoke(prompt="parity question") == 0
        factory.assert_called_once()
        captured = capsys.readouterr()
        events = [json.loads(line) for line in captured.out.splitlines()]
        assert events and events[-1]["kind"] == "run_completed"
        assert runner._session is not None and not runner._session._agent_is_injected
        assert runner._session._herdr_capture is None and not runner._session._herdr_interactive
        assert runner._operation_credential is None
        wire = fake_herdr.capture.read_bytes()
        assert (wire == before) is disabled
        assert "--herdr-restore" not in wire.decode()
        assert "synthetic-parity-secret" not in captured.out + captured.err + wire.decode()
        streams.append(events)
    assert streams[0] == streams[1]
