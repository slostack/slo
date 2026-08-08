"""Tests for ``src.agents.base.LLMFactory`` (sub-spec 01.b §5.1; 01.n / 02.b.2 auth).

We do NOT actually call the providers — just verify the factory returns
the right class and surfaces missing keys as ValueError.

02.b.2 changes:
- ``LLMFactory.create`` now delegates credential lookup to
  ``CredentialResolver.require`` for both providers. The
  ``_resolve_anthropic_key`` / ``_read_claude_oauth_token`` helpers and
  the ``_CLAUDE_CREDENTIALS_PATH`` constant on ``LLMFactory`` are gone;
  their bodies live in ``CredentialResolver`` and are covered by
  ``tests/auth/test_credential_resolver.py``.
- The autouse fixture that pointed ``_CLAUDE_CREDENTIALS_PATH`` at a
  non-existent path now patches the same attribute on
  ``CredentialResolver`` so we don't pick up the developer's real
  ``~/.claude/.credentials.json`` on local runs.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

from langchain_anthropic import ChatAnthropic

from src.agents.base import LLMFactory
from src.agents.providers.anthropic_claude_code import (
    ClaudeCodeChatAnthropic,
    _ThinkingPatchedChatAnthropic,
)
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


def _reload_cfg() -> None:
    """Re-import config.cfg so module-level ``ANTHROPIC_API_KEY`` etc. pick up env changes."""
    import config.cfg as cfg_module

    importlib.reload(cfg_module)


@pytest.fixture(autouse=True)
def _neutralise_claude_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point credential sources at a non-existent ``tmp_path``.

    Without this, tests that delete ``SLO_ANTHROPIC_API_KEY`` would pick up
    the developer's real ``~/.claude/.credentials.json`` and
    ``~/.slo/global/authentication.json`` and silently fall through to a
    different code path than intended.

    02.b.2: the legacy-Claude constant moved from ``LLMFactory`` to
    ``CredentialResolver``. We also re-root ``CredentialStore`` for the
    same reason — the resolver instantiates one internally on every
    ``_from_store`` call.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest's monkeypatch fixture.
        tmp_path (Path): The test's temp dir; never exists on disk.
    """
    from src.auth.credential_store import CredentialStore

    monkeypatch.setattr(CredentialResolver, "_CLAUDE_CREDENTIALS_PATH", tmp_path / "no-credentials.json")
    monkeypatch.setattr(
        "src.auth.credential_resolver.CredentialStore",
        lambda: CredentialStore(path=tmp_path / "no-store.json"),
    )


def test_create_llm_anthropic_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic claude-sonnet-4-6 → ChatAnthropic subclass; SLO_ANTHROPIC_API_KEY wins over store."""
    monkeypatch.setenv("SLO_ANTHROPIC_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="claude-sonnet-4-6")
    assert isinstance(result.llm, ChatAnthropic)
    assert result.supports_explicit_caching is True


def test_create_llm_openai_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI gpt-4.1 → ChatOpenAI; SLO_OPENAI_API_KEY wins over store."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="gpt-4.1")
    assert result.llm.__class__.__name__ == "ChatOpenAI"
    assert result.supports_explicit_caching is False


def test_create_llm_openai_o3_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI bare ``o3`` (no hyphen) → ChatOpenAI; SLO_OPENAI_API_KEY wins over store."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="o3")
    assert result.llm.__class__.__name__ == "ChatOpenAI"
    assert result.supports_explicit_caching is False


def test_create_llm_openai_o1_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI bare ``o1`` (no hyphen) → ChatOpenAI; SLO_OPENAI_API_KEY wins over store."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="o1")
    assert result.llm.__class__.__name__ == "ChatOpenAI"
    assert result.supports_explicit_caching is False


def test_create_llm_openai_gpt5_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI gpt-5 → ChatOpenAI; SLO_OPENAI_API_KEY wins over store."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="gpt-5")
    assert result.llm.__class__.__name__ == "ChatOpenAI"
    assert result.supports_explicit_caching is False


@pytest.mark.parametrize("model_name", [
    "gpt-5-codex",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.3-codex-spark",
])
def test_create_llm_openai_codex_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
) -> None:
    """OpenAI Codex variants → ChatOpenAI; SLO_OPENAI_API_KEY wins over store."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name=model_name)
    assert result.llm.__class__.__name__ == "ChatOpenAI"
    assert result.supports_explicit_caching is False


def test_create_llm_anthropic_opus_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic claude-opus-4-7 → ChatAnthropic subclass; SLO_ANTHROPIC_API_KEY wins over store."""
    monkeypatch.setenv("SLO_ANTHROPIC_API_KEY", "sk-test")
    _reload_cfg()
    result = LLMFactory.create(model_name="claude-opus-4-7")
    assert isinstance(result.llm, ChatAnthropic)
    assert result.supports_explicit_caching is True


def test_create_llm_unsupported_prefix_raises() -> None:
    """Unknown prefix ``palm-2`` → ValueError; the dispatcher's table-of-contents."""
    with pytest.raises(ValueError, match="Unsupported model_name"):
        LLMFactory.create(model_name="palm-2")


def test_create_llm_missing_anthropic_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """02.b.2: missing env + missing legacy file → clear ValueError from the resolver."""
    monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
    _reload_cfg()
    with pytest.raises(ValueError, match="No Anthropic credentials found"):
        LLMFactory.create(model_name="claude-sonnet-4-6")


def test_create_llm_missing_openai_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """02.b.2: the OpenAI missing-credentials path now flows through the resolver."""
    monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
    _reload_cfg()
    with pytest.raises(ValueError, match="No OpenAI credentials found"):
        LLMFactory.create(model_name="gpt-4.1")


class TestLLMFactoryDelegatesToResolver:
    """``LLMFactory.create`` delegates credential lookup to ``CredentialResolver``."""

    def test_create_anthropic_calls_resolver_with_anthropic_provider(self) -> None:
        """Anthropic model → ``require(provider=ANTHROPIC)``."""
        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=CredentialDAO(
                    provider=ProviderName.ANTHROPIC,
                    auth_type=AuthType.API_KEY,
                    access_token="sk-stub",
                ),
            ) as mock_require,
            patch("src.agents.base._ThinkingPatchedChatAnthropic"),
        ):
            LLMFactory.create(model_name="claude-sonnet-4-6")

        mock_require.assert_called_once_with(provider=ProviderName.ANTHROPIC)

    def test_create_openai_calls_resolver_with_openai_provider(self) -> None:
        """OpenAI model → ``require(provider=OPENAI)``."""
        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=CredentialDAO(
                    provider=ProviderName.OPENAI,
                    auth_type=AuthType.API_KEY,
                    access_token="sk-stub",
                ),
            ) as mock_require,
            patch("src.agents.base.ChatOpenAI"),
        ):
            LLMFactory.create(model_name="gpt-5.4")

        mock_require.assert_called_once_with(provider=ProviderName.OPENAI)

    def test_create_propagates_resolver_value_error(self) -> None:
        """``ValueError`` from ``require`` flows out of ``create`` unchanged."""
        with patch(
            "src.agents.base.CredentialResolver.require",
            side_effect=ValueError("No OpenAI credentials found."),
        ):
            with pytest.raises(ValueError, match="No OpenAI credentials found"):
                LLMFactory.create(model_name="gpt-5.4")


class TestLLMFactoryAnthropicRouting:
    """``_build_anthropic`` routes OAuth credentials to the Claude Code lane."""

    def test_oauth_credential_routes_to_claude_code_builder(self) -> None:
        """Anthropic OAuth ``CredentialDAO`` → Claude Code-backed builder is used."""
        cred = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token="sk-ant-oat01-route",
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_claude_code_backed_chat_anthropic") as mock_builder,
        ):
            LLMFactory.create(model_name="claude-sonnet-4-6")

        mock_builder.assert_called_once()
        kwargs: dict = mock_builder.call_args.kwargs
        assert kwargs["model_name"] == "claude-sonnet-4-6"
        assert kwargs["cred"].auth_type is AuthType.OAUTH

    def test_api_key_credential_stays_on_thinking_patched_anthropic(self) -> None:
        """Anthropic API-key credentials use ``_ThinkingPatchedChatAnthropic``, not the Claude Code builder."""
        cred = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="sk-ant-api",
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_claude_code_backed_chat_anthropic") as mock_builder,
        ):
            result = LLMFactory.create(model_name="claude-sonnet-4-6")

        mock_builder.assert_not_called()
        assert isinstance(result.llm, _ThinkingPatchedChatAnthropic)
        assert not isinstance(result.llm, ClaudeCodeChatAnthropic)

    def test_legacy_oauth_fallback_uses_claude_code_lane(self) -> None:
        """Any Anthropic ``AuthType.OAUTH`` credential uses the Claude Code lane."""
        cred = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token="legacy-oauth-token",
        )

        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=cred,
        ):
            result = LLMFactory.create(model_name="claude-sonnet-4-6")

        assert isinstance(result.llm, ClaudeCodeChatAnthropic)


class TestLLMFactoryOpenAIRouting:
    """``_build_openai`` routes OAuth credentials to the ChatGPT-backend lane (feature 07)."""

    def _oauth_cred(self) -> CredentialDAO:
        """Build an OAuth credential carrying a JWT with the required claim."""
        import base64
        import json
        from datetime import datetime, timedelta, timezone

        payload: dict = {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-route-test",
                "chatgpt_plan_type": "business",
            },
        }
        payload_b64: str = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")
        )
        header_b64: str = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode("ascii")
        jwt: str = f"{header_b64}.{payload_b64}.sig"
        return CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token=jwt,
            refresh_token="rt-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def test_oauth_credential_routes_to_chatgpt_backend(self) -> None:
        """OAuth ``CredentialDAO`` → ChatGPT-backend ``ChatOpenAI`` is built."""
        cred = self._oauth_cred()

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_chatgpt_backed_chat_openai") as mock_builder,
        ):
            LLMFactory.create(
                model_name="gpt-5",
                session_id="sess-routed",
            )

        mock_builder.assert_called_once()
        kwargs: dict = mock_builder.call_args.kwargs
        assert kwargs["model_name"] == "gpt-5"
        assert kwargs["cred"].auth_type is AuthType.OAUTH
        assert kwargs["session_id"] == "sess-routed"
        assert kwargs["reasoning"].enabled is False

    def test_api_key_credential_does_not_touch_chatgpt_backend(self) -> None:
        """API-key ``CredentialDAO`` → stock ``ChatOpenAI``; codex builder untouched."""
        cred = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="sk-platform",
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_chatgpt_backed_chat_openai") as mock_builder,
        ):
            LLMFactory.create(model_name="gpt-5")

        mock_builder.assert_not_called()


class TestLLMFactoryReasoningRouting:
    """Resolved reasoning config reaches both provider lanes deterministically."""

    def test_oauth_openai_builder_receives_resolved_reasoning_config(self) -> None:
        """OpenAI OAuth routing passes the resolved config into the codex builder."""
        cred: CredentialDAO = TestLLMFactoryOpenAIRouting()._oauth_cred()

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_chatgpt_backed_chat_openai") as mock_builder,
        ):
            LLMFactory.create(
                model_name="gpt-5.4",
                reasoning_level="minimal",
            )

        reasoning = mock_builder.call_args.kwargs["reasoning"]
        assert reasoning.active_level == "minimal"
        assert reasoning.provider_effort == "low"

    def test_api_key_openai_path_sets_responses_reasoning_payload(self) -> None:
        """OpenAI API-key reasoning builds emit Responses config and omit temperature."""
        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="sk-platform",
        )

        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=cred,
        ):
            result = LLMFactory.create(
                model_name="gpt-5.4",
                reasoning_level="xhigh",
            )

        assert result.llm.reasoning == {"effort": "xhigh", "summary": "auto"}
        assert result.llm.use_responses_api is True
        assert result.llm.output_version == "responses/v1"
        assert result.llm.temperature is None

    def test_api_key_anthropic_path_sets_clamped_thinking_payload(self) -> None:
        """Anthropic API-key builds carry the resolved ``thinking`` payload."""
        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="sk-ant-api",
        )

        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=cred,
        ):
            result = LLMFactory.create(
                model_name="claude-sonnet-4-6",
                reasoning_level="xhigh",
            )

        assert result.llm.thinking == {"type": "adaptive"}
        assert result.llm.model_kwargs.get("output_config") == {"effort": "high"}
        assert result.llm.temperature is None

    def test_api_key_anthropic_path_patches_signature_only_thinking_blocks(self) -> None:
        """API-key Anthropic builds patch incomplete thinking blocks just like the OAuth path."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="sk-ant-api",
        )

        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=cred,
        ):
            result = LLMFactory.create(model_name="claude-sonnet-4-6")

        ai_msg = AIMessage(
            content=[
                {"type": "thinking", "signature": "sig-abc", "index": 0},
                {"type": "tool_use", "id": "call_1", "name": "bash", "input": {"cmd": "ls"}},
            ],
            tool_calls=[{"id": "call_1", "name": "bash", "args": {"cmd": "ls"}, "type": "tool_call"}],
        )
        tool_msg = ToolMessage(content="file.txt", tool_call_id="call_1", name="bash")

        payload = result.llm._get_request_payload(
            input_=[HumanMessage(content="go"), ai_msg, tool_msg],
        )

        assistant_blocks = [m["content"] for m in payload["messages"] if m.get("role") == "assistant"][0]
        thinking_block = next(b for b in assistant_blocks if b.get("type") == "thinking")
        assert "thinking" in thinking_block
        assert thinking_block["thinking"] == ""


class TestLLMFactoryAnthropicApiModelNameResolution:
    """``_build_anthropic`` passes the catalog-resolved API model ID to the provider (spec 54)."""

    def _api_key_cred(self) -> CredentialDAO:
        """Build an Anthropic API-key credential.

        Returns:
            CredentialDAO: API-key credential for the Anthropic provider.
        """
        return CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="sk-ant-api",
        )

    def _oauth_cred(self) -> CredentialDAO:
        """Build an Anthropic OAuth credential.

        Returns:
            CredentialDAO: OAuth credential for the Anthropic provider.
        """
        return CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token="sk-ant-oat01-api-model-name",
        )

    def test_api_key_lane_1m_variant_sends_base_api_model_id(self) -> None:
        """claude-opus-4-8-1m-context builds the chat with model == 'claude-opus-4-8'."""
        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=self._api_key_cred(),
        ):
            result = LLMFactory.create(model_name="claude-opus-4-8-1m-context")

        assert result.llm.model == "claude-opus-4-8"

    def test_api_key_lane_haiku_sends_dated_api_model_id(self) -> None:
        """claude-haiku-4-5 builds the chat with model == 'claude-haiku-4-5-20251001'."""
        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=self._api_key_cred(),
        ):
            result = LLMFactory.create(model_name="claude-haiku-4-5")

        assert result.llm.model == "claude-haiku-4-5-20251001"

    def test_api_key_lane_sonnet_1m_sends_base_api_model_id(self) -> None:
        """claude-sonnet-4-6-1m-context builds the chat with model == 'claude-sonnet-4-6'."""
        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=self._api_key_cred(),
        ):
            result = LLMFactory.create(model_name="claude-sonnet-4-6-1m-context")

        assert result.llm.model == "claude-sonnet-4-6"

    def test_api_key_lane_identity_entry_sends_canonical_name(self) -> None:
        """claude-opus-4-8 (no override) builds the chat with the canonical name verbatim."""
        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=self._api_key_cred(),
        ):
            result = LLMFactory.create(model_name="claude-opus-4-8")

        assert result.llm.model == "claude-opus-4-8"

    def test_oauth_lane_1m_variant_sends_base_api_model_id(self) -> None:
        """Claude Code OAuth lane receives the same resolved API model name."""
        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=self._oauth_cred(),
            ),
            patch("src.agents.base.build_claude_code_backed_chat_anthropic") as mock_builder,
        ):
            LLMFactory.create(model_name="claude-opus-4-8-1m-context")

        mock_builder.assert_called_once()
        assert mock_builder.call_args.kwargs["model_name"] == "claude-opus-4-8"

    def test_oauth_lane_identity_entry_sends_canonical_name(self) -> None:
        """Claude Code OAuth lane keeps identity entries on the canonical name."""
        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=self._oauth_cred(),
            ),
            patch("src.agents.base.build_claude_code_backed_chat_anthropic") as mock_builder,
        ):
            LLMFactory.create(model_name="claude-sonnet-4-6")

        mock_builder.assert_called_once()
        assert mock_builder.call_args.kwargs["model_name"] == "claude-sonnet-4-6"


class TestSessionIdThreading:
    """``session_id`` flows from caller → ``_resolved_defaults`` → builder."""

    def test_session_id_kwarg_lands_in_chatgpt_backend_builder(self) -> None:
        """``LLMFactory.create(session_id=...)`` reaches the codex builder."""
        from datetime import datetime, timedelta, timezone

        cred = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token=(
                "header."
                "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdC10aHJlYWRlZCJ9fQ"
                ".sig"
            ),
            refresh_token="rt-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_chatgpt_backed_chat_openai") as mock_builder,
        ):
            LLMFactory.create(
                model_name="gpt-5",
                session_id="threaded-session-id",
            )

        assert mock_builder.call_args.kwargs["session_id"] == "threaded-session-id"

    def test_session_id_defaults_to_model_name_when_caller_omits_it(self) -> None:
        """No ``session_id`` kwarg → builder receives the model name as fallback.

        This keeps the prompt-cache key non-empty even on direct LLMFactory
        invocations that bypass ``SloAgentSession`` (e.g. ad-hoc scripts).
        """
        from datetime import datetime, timedelta, timezone

        cred = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token=(
                "header."
                "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdC10aHJlYWRlZCJ9fQ"
                ".sig"
            ),
            refresh_token="rt-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=cred,
            ),
            patch("src.agents.base.build_chatgpt_backed_chat_openai") as mock_builder,
        ):
            LLMFactory.create(model_name="gpt-5")

        assert mock_builder.call_args.kwargs["session_id"] == "gpt-5"



class TestLLMFactoryCreatePool:
    """``LLMFactory.create_pool`` assembles a ``ModelPool`` from a ``ModelPoolDAO``."""

    def test_create_pool_returns_model_pool(self) -> None:
        """``create_pool`` returns an object with ``active_model_name`` (duck-type pool)."""
        from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
        from src.agents.providers.faux import FauxChatModel
        from langchain_core.messages import AIMessage

        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-4o",
                    provider=ProviderName.OPENAI,
                    priority=1,
                ),
            ]
        )
        faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="ok")])
        with patch.object(LLMFactory, "create", return_value=type("R", (), {"llm": faux})()):
            pool = LLMFactory.create_pool(pool_dao=dao)

        assert hasattr(pool, "active_model_name")

    def test_create_pool_builds_one_model_per_entry(self) -> None:
        """``create_pool`` calls ``LLMFactory.create`` once per pool entry."""
        from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
        from src.agents.providers.faux import FauxChatModel
        from langchain_core.messages import AIMessage

        faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="ok")])
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
        with patch.object(
            LLMFactory,
            "create",
            return_value=type("R", (), {"llm": faux})(),
        ) as mock_create:
            LLMFactory.create_pool(pool_dao=dao)

        assert mock_create.call_count == 2


def _two_member_dao() -> "ModelPoolDAO":  # type: ignore[name-defined] # noqa: F821
    """Build a two-member pool DAO (gpt-5.4 OpenAI, claude-sonnet-4-6 Anthropic).

    Returns:
        ModelPoolDAO: A validated two-entry pool config.
    """
    from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO

    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
            ),
        ]
    )


def _capturing_create(captured: list[dict]):
    """Return a stand-in for ``LLMFactory.create`` that records its kwargs.

    Args:
        captured (list[dict]): List the stand-in appends each call's kwargs to.

    Returns:
        Callable: A function with ``create``'s keyword surface returning a
            credential-free ``LLMBuildResult`` wrapping a ``FauxChatModel``.
    """
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel

    def _create(**kwargs: object) -> LLMBuildResult:
        captured.append(dict(kwargs))
        return LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)

    return _create


class TestCreatePoolForwardsKnobs:
    """``create_pool`` forwards every build knob to every member (37.a.3)."""

    def test_forwards_streaming_and_reasoning_to_every_member(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_pool passes streaming/reasoning/session_id to each member build."""
        captured: list[dict] = []
        monkeypatch.setattr(LLMFactory, "create", _capturing_create(captured))
        LLMFactory.create_pool(
            pool_dao=_two_member_dao(),
            streaming=False,
            reasoning_level="high",
            session_id="s1",
        )
        assert len(captured) == 2
        assert all(
            c["streaming"] is False
            and c["reasoning_level"] == "high"
            and c["session_id"] == "s1"
            for c in captured
        )

    def test_injects_request_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_pool wires the ChatGPT-backend adapter as the pool's request_adapter."""
        monkeypatch.setattr(LLMFactory, "create", _capturing_create([]))
        from src.agents.slo_agent.graph import adapt_chatgpt_backend_request

        pool = LLMFactory.create_pool(pool_dao=_two_member_dao())
        assert pool._request_adapter is adapt_chatgpt_backend_request


class TestBuildProductProtocol:
    """``LLMBuildProduct`` is satisfied by both the single-model result and the pool (37.a.3)."""

    def test_model_pool_satisfies_llm_build_product(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A constructed ModelPool structurally satisfies LLMBuildProduct."""
        from src.agents.base import LLMBuildProduct

        monkeypatch.setattr(LLMFactory, "create", _capturing_create([]))
        pool = LLMFactory.create_pool(pool_dao=_two_member_dao())
        assert isinstance(pool, LLMBuildProduct)

    def test_llm_build_result_satisfies_llm_build_product(self) -> None:
        """An LLMBuildResult structurally satisfies LLMBuildProduct."""
        from src.agents.base import LLMBuildProduct, LLMBuildResult
        from src.agents.providers.faux import FauxChatModel

        result = LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)
        assert isinstance(result, LLMBuildProduct)


class TestAnthropicMaxTokens:
    """``LLMFactory._anthropic_max_tokens`` treats ``max_tokens`` as the total cap (spec 02.a §8)."""

    @staticmethod
    def _adaptive(*, budget: int | None = None) -> ResolvedReasoningConfigDAO:
        """Build an enabled (adaptive) resolved reasoning config.

        Args:
            budget (int | None): Optional explicit provider thinking budget.

        Returns:
            ResolvedReasoningConfigDAO: Enabled config with the given budget.
        """
        return ResolvedReasoningConfigDAO(
            enabled=True,
            requested_level="high",
            active_level="high",
            provider_effort="high",
            provider_budget_tokens=budget,
        )

    @staticmethod
    def _disabled() -> ResolvedReasoningConfigDAO:
        """Build a reasoning-disabled resolved config.

        Returns:
            ResolvedReasoningConfigDAO: Disabled config.
        """
        return ResolvedReasoningConfigDAO(enabled=False, requested_level="off", active_level="off")

    def test_anthropic_max_tokens_adaptive_returns_ceiling(self) -> None:
        """Adaptive thinking (no budget) → the ceiling is sent unchanged."""
        assert (
            LLMFactory._anthropic_max_tokens(
                base_max_tokens=64_000,
                resolved_reasoning=self._adaptive(),
            )
            == 64_000
        )

    def test_anthropic_max_tokens_reasoning_disabled_returns_ceiling(self) -> None:
        """Reasoning disabled → the ceiling is sent unchanged."""
        assert (
            LLMFactory._anthropic_max_tokens(
                base_max_tokens=128_000,
                resolved_reasoning=self._disabled(),
            )
            == 128_000
        )

    def test_anthropic_max_tokens_never_adds_budget_on_top(self) -> None:
        """An explicit thinking budget is NOT added on top of the ceiling (exact equality).

        Asserting equality (not ``<=``) makes the no-add-on-top contract explicit: a
        32K budget alongside a 64K ceiling must still resolve to exactly 64K, never
        96K (which would 400 against the model's hard limit).
        """
        result = LLMFactory._anthropic_max_tokens(
            base_max_tokens=64_000,
            resolved_reasoning=self._adaptive(budget=32_000),
        )
        assert result == 64_000

    def test_build_anthropic_sends_64000_for_sonnet(self) -> None:
        """A built ``ChatAnthropic`` for sonnet-4-6 carries the 64K ceiling."""
        cred = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="sk-ant-api",
        )

        with patch(
            "src.agents.base.CredentialResolver.require",
            return_value=cred,
        ):
            result = LLMFactory.create(model_name="claude-sonnet-4-6")

        assert isinstance(result.llm, ChatAnthropic)
        assert result.llm.max_tokens == 64_000

    def test_absent_model_falls_back_to_4096(self) -> None:
        """An unlisted model resolves to the factory's 4096 fallback."""
        resolved = LLMFactory._resolved_defaults(
            model_name="claude-some-future-model",
            temperature=None,
            streaming=None,
            max_retries=3,
            max_tokens=None,
            model_kwargs=None,
        )
        assert resolved["max_tokens"] == 4096
