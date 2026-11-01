"""Tests for ``LLMFactory`` Kimi For Coding dispatch (spec 32.a.1).

Covers the four decision points mandated by the test plan:
1. ``kimi-*`` prefix → KFC builder → ``ChatOpenAI`` targeting api.kimi.com
2. ``moonshot-*`` prefix → same KFC builder (legacy model name compat)
3. ``create_pool`` assembles a ``ModelPool`` from a ``ModelPoolDAO``
4. Missing ``SLO_KIMI_FOR_CODING_API_KEY`` → ``ValueError`` with actionable message
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from src.agents.base import LLMFactory
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from tests.agents.retry_options import SDKRetryOptions


def _reload_cfg() -> None:
    """Re-import config.cfg so module-level ``KIMI_FOR_CODING_API_KEY`` picks up env changes."""
    import config.cfg as cfg_module

    importlib.reload(cfg_module)


@pytest.fixture(autouse=True)
def _neutralise_credential_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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


class TestLLMFactoryKimiReasoning:
    """K3 provider effort construction and K2 no-regression behavior."""

    @pytest.mark.parametrize(
        ("reasoning_level", "provider_effort"),
        [("low", "low"), ("high", "high"), ("xhigh", "max")],
    )
    def test_k3_builder_adds_top_level_reasoning_effort_when_resolved(
        self,
        reasoning_level: str,
        provider_effort: str,
    ) -> None:
        """K3 sends its resolved native effort without Kimi thinking fields."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
        ):
            LLMFactory.create(
                model_name="kimi-k3",
                reasoning_level=reasoning_level,  # type: ignore[arg-type]
            )

        kwargs: dict[str, Any] = dict(mock_chat_openai.call_args.kwargs)
        assert kwargs["reasoning_effort"] == provider_effort
        assert kwargs["max_retries"] == 3
        assert kwargs["default_headers"] == {"User-Agent": "KimiCLI/1.5"}
        for forbidden_key in ("thinking", "reasoning", "use_responses_api", "output_version"):
            assert forbidden_key not in kwargs

    @pytest.mark.parametrize(("reasoning_level", "provider_effort"), [("off", "low"), ("medium", "high")])
    def test_k3_builder_clamps_reasoning_before_sending_provider_effort(
        self,
        reasoning_level: str,
        provider_effort: str,
    ) -> None:
        """K3 resolves unsupported canonical levels before request construction."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
        ):
            LLMFactory.create(
                model_name="kimi-k3",
                reasoning_level=reasoning_level,  # type: ignore[arg-type]
            )

        assert mock_chat_openai.call_args.kwargs["reasoning_effort"] == provider_effort

    @pytest.mark.parametrize("model_name", ["kimi-for-coding", "kimi-for-coding-highspeed"])
    def test_k2_builder_omits_reasoning_fields(self, model_name: str) -> None:
        """Off-only K2 builders keep their legacy constructor field set."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
        ):
            LLMFactory.create(model_name=model_name, reasoning_level="high")

        kwargs: dict[str, Any] = dict(mock_chat_openai.call_args.kwargs)
        for forbidden_key in (
            "reasoning_effort",
            "thinking",
            "reasoning",
            "use_responses_api",
            "output_version",
        ):
            assert forbidden_key not in kwargs

    def test_kimi_builder_rejects_enabled_reasoning_without_provider_effort(self) -> None:
        """Inconsistent enabled resolved reasoning fails before model construction."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        resolved_reasoning: ResolvedReasoningConfigDAO = ResolvedReasoningConfigDAO(
            enabled=True,
            requested_level="high",
            active_level="high",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch(
                "src.agents.base.resolve_reasoning_config",
                return_value=resolved_reasoning,
            ),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
            pytest.raises(ValueError, match="requires a provider effort"),
        ):
            LLMFactory.create(model_name="kimi-k3", reasoning_level="high")

        mock_chat_openai.assert_not_called()

    def test_kimi_builder_surfaces_known_model_reasoning_resolution_error(self) -> None:
        """A malformed known-model profile cannot silently omit K3 provider effort."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch(
                "src.agents.base.resolve_reasoning_config",
                side_effect=ValueError("K3 provider effort map is invalid"),
            ),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
            pytest.raises(ValueError, match="provider effort map is invalid"),
        ):
            LLMFactory.create(model_name="kimi-k3", reasoning_level="high")

        mock_chat_openai.assert_not_called()

    def test_kimi_builder_omits_reasoning_fields_for_unknown_kimi_model(self) -> None:
        """Unknown Kimi prefix compatibility models retain the legacy request shape."""
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            auth_type=AuthType.API_KEY,
            access_token="test-token",
        )
        with (
            patch.object(CredentialResolver, "require", return_value=credential),
            patch("src.agents.base.ChatOpenAI") as mock_chat_openai,
        ):
            LLMFactory.create(model_name="kimi-unverified", reasoning_level="high")

        kwargs: dict[str, Any] = dict(mock_chat_openai.call_args.kwargs)
        assert "reasoning_effort" not in kwargs

    @pytest.mark.parametrize("provider_effort", ["low", "high", "max"])
    def test_chat_openai_serializes_k3_reasoning_effort_as_top_level_field(
        self, provider_effort: str
    ) -> None:
        """Installed ChatOpenAI serializes K3 effort at the chat-completions top level."""
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        chat_model: ChatOpenAI = ChatOpenAI(
            api_key=cast(Any, "test-key"),
            base_url="https://api.kimi.com/coding/v1",
            model="kimi-k3",
            reasoning_effort=provider_effort,
        )
        payload: dict[str, Any] = chat_model._get_request_payload(
            input_=[HumanMessage(content="ok")],
        )

        assert payload["reasoning_effort"] == provider_effort
        for forbidden_key in ("thinking", "reasoning", "use_responses_api", "output_version"):
            assert forbidden_key not in payload

    def test_create_pool_forwards_k3_canonical_reasoning_level_to_each_member(self) -> None:
        """ModelPool forwards one canonical reasoning level to K3 and K2 members."""
        pool_dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="kimi-k3",
                    provider=ProviderName.KIMI_FOR_CODING,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="kimi-for-coding",
                    provider=ProviderName.KIMI_FOR_CODING,
                    priority=1,
                ),
            ]
        )
        faux_build_result: MagicMock = MagicMock()
        faux_build_result.llm = MagicMock()

        with (
            patch.object(LLMFactory, "create", return_value=faux_build_result) as mock_create,
            patch("src.agents.providers.model_pool.ModelPool") as mock_pool,
        ):
            LLMFactory.create_pool(pool_dao=pool_dao, reasoning_level="medium")

        assert [call.kwargs["reasoning_level"] for call in mock_create.call_args_list] == ["medium", "medium"]
        mock_pool.assert_called_once()


class TestLLMFactoryKimiForCodingDispatch:
    """``LLMFactory.create`` Kimi For Coding dispatch (spec 32.a.1)."""

    @pytest.mark.parametrize("retry_options", [{}, {"max_retries": 0}, {"max_retries": 5}])
    def test_kimi_prefix_dispatches_to_chat_openai_at_kimi_url(
        self, monkeypatch: pytest.MonkeyPatch, retry_options: SDKRetryOptions
    ) -> None:
        """``kimi-for-coding`` → ``ChatOpenAI`` pointing at api.kimi.com; caching=False."""
        monkeypatch.setenv("SLO_KIMI_FOR_CODING_API_KEY", "sk-kimi-test")
        _reload_cfg()
        with patch("src.agents.base.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value = mock_chat_openai
            result = LLMFactory.create(model_name="kimi-for-coding", **retry_options)
        mock_chat_openai.assert_called_once()
        kwargs: dict[str, Any] = dict(mock_chat_openai.call_args.kwargs)
        assert "api.kimi.com" in kwargs.get("base_url", "")
        assert kwargs.get("max_retries") == retry_options.get("max_retries", 3)
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
        kwargs: dict[str, Any] = dict(mock_chat_openai.call_args.kwargs)
        assert "api.kimi.com" in kwargs.get("base_url", "")
        assert result.supports_explicit_caching is False

    def test_create_pool_assembles_model_pool_from_dao(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
