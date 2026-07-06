"""Tests for ``LLMFactory`` Kimi For Coding dispatch (spec 32.a.1).

Covers the four decision points mandated by the test plan:
1. ``kimi-*`` prefix → KFC builder → ``ChatOpenAI`` targeting api.kimi.com
2. ``moonshot-*`` prefix → same KFC builder (legacy model name compat)
3. ``create_pool`` assembles a ``ModelPool`` from a ``ModelPoolDAO``
4. Missing ``SLO_KIMI_FOR_CODING_API_KEY`` → ``ValueError`` with actionable message
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from src.agents.base import LLMFactory
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


def _reload_cfg() -> None:
    """Re-import config.cfg so module-level ``KIMI_FOR_CODING_API_KEY`` picks up env changes."""
    import config.cfg as cfg_module

    importlib.reload(cfg_module)


@pytest.fixture(autouse=True)
def _neutralise_credential_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: __import__("pathlib").Path
) -> None:
    """Remove KFC and Anthropic env keys so tests start from a clean slate.

    Without this, a developer's real ``SLO_KIMI_FOR_CODING_API_KEY`` or a
    pre-stored entry in ``~/.slo/global/authentication.json`` would satisfy
    the resolver in tests that expect the missing-key path to raise.
    """
    from pathlib import Path

    monkeypatch.delenv("SLO_KIMI_FOR_CODING_API_KEY", raising=False)
    monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
    # Point the auth store at an empty tmp directory so stored credentials
    # are invisible to all tests in this module.
    monkeypatch.setenv("SLO_AUTH_FILE", str(tmp_path / "authentication.json"))
    _reload_cfg()
    monkeypatch.setattr(
        CredentialResolver,
        "_CLAUDE_CREDENTIALS_PATH",
        Path("/nonexistent/__neutralised__"),
    )


class TestLLMFactoryKimiForCodingDispatch:
    """``LLMFactory.create`` Kimi For Coding dispatch (spec 32.a.1)."""

    def test_kimi_prefix_dispatches_to_chat_openai_at_kimi_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``kimi-for-coding`` → ``ChatOpenAI`` pointing at api.kimi.com; caching=False."""
        monkeypatch.setenv("SLO_KIMI_FOR_CODING_API_KEY", "sk-kimi-test")
        _reload_cfg()
        with patch("src.agents.base.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value = mock_chat_openai
            result = LLMFactory.create(model_name="kimi-for-coding")
        mock_chat_openai.assert_called_once()
        kwargs: dict = mock_chat_openai.call_args.kwargs
        assert "api.kimi.com" in kwargs.get("base_url", "")
        assert kwargs.get("max_retries") == 0
        assert result.supports_explicit_caching is False

    def test_moonshot_prefix_also_routes_to_kimi_for_coding_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``moonshot-*`` model names route through the same KFC builder (legacy compat)."""
        monkeypatch.setenv("SLO_KIMI_FOR_CODING_API_KEY", "sk-kimi-test")
        _reload_cfg()
        with patch("src.agents.base.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value = mock_chat_openai
            result = LLMFactory.create(model_name="moonshot-v1-8k")
        mock_chat_openai.assert_called_once()
        kwargs: dict = mock_chat_openai.call_args.kwargs
        assert "api.kimi.com" in kwargs.get("base_url", "")
        assert result.supports_explicit_caching is False

    def test_create_pool_assembles_model_pool_from_dao(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``create_pool`` returns a ``ModelPool`` with ``active_model_name``."""
        from langchain_core.messages import AIMessage

        from src.agents.providers.faux import FauxChatModel
        from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO

        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="kimi-for-coding",
                    provider=ProviderName.KIMI_FOR_CODING,
                    priority=1,
                ),
            ]
        )
        faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="ok")])
        with patch.object(LLMFactory, "create", return_value=type("R", (), {"llm": faux})()):
            pool: ModelPool = LLMFactory.create_pool(pool_dao=dao)

        assert hasattr(pool, "active_model_name")
        assert pool.active_model_name == "claude-sonnet-4-6"

    def test_missing_kimi_for_coding_api_key_raises_value_error(self) -> None:
        """Missing ``SLO_KIMI_FOR_CODING_API_KEY`` → ``ValueError`` with actionable message."""
        with pytest.raises(ValueError, match="[Kk]imi"):
            LLMFactory.create(model_name="kimi-for-coding")
