"""Tests for ``provider_for_model`` (02.b.6)."""

import pytest

from src.auth.credential_dao import ProviderName
from src.auth.provider_for_model import provider_for_model


class TestProviderForModel:
    """Pure-function mapping; one test per supported branch."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "claude-sonnet-4-6",
            "claude-opus-4-7",
        ],
    )
    def test_anthropic_models_map_to_anthropic(self, model_name: str) -> None:
        """Any ``claude-*`` model resolves to ``ANTHROPIC``."""
        assert provider_for_model(model_name=model_name) is ProviderName.ANTHROPIC

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-5.5",
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
        ],
    )
    def test_new_openai_models_map_to_openai(self, model_name: str) -> None:
        """Spec-55 OpenAI models resolve to OPENAI."""
        assert provider_for_model(model_name=model_name) is ProviderName.OPENAI

    def test_claude_fable_maps_to_anthropic(self) -> None:
        """``claude-fable`` resolves to ANTHROPIC."""
        assert provider_for_model(model_name="claude-fable") is ProviderName.ANTHROPIC

    def test_claude_mythos_maps_to_anthropic(self) -> None:
        """The conditional entry resolves to ANTHROPIC."""
        assert provider_for_model(model_name="claude-mythos") is ProviderName.ANTHROPIC

    @pytest.mark.parametrize(
        "model_name",
        [
            "kimi-k3",
            "kimi-for-coding-highspeed",
        ],
    )
    def test_new_kimi_models_map_to_kimi_for_coding(self, model_name: str) -> None:
        """Spec-55 Kimi models resolve to KIMI_FOR_CODING."""
        assert provider_for_model(model_name=model_name) is ProviderName.KIMI_FOR_CODING

    def test_legacy_moonshot_alias_resolves_to_kimi_for_coding(self) -> None:
        """``moonshot-for-coding`` resolves to the canonical Kimi provider."""
        assert provider_for_model(model_name="moonshot-for-coding") is ProviderName.KIMI_FOR_CODING

    @pytest.mark.parametrize(
        "model_name",
        [
            "openrouter:anthropic/claude-sonnet-5.5",
            "openrouter:openai/gpt-5.2",
        ],
    )
    def test_qualified_openrouter_models_map_to_openrouter(self, model_name: str) -> None:
        """Qualified OpenRouter routes retain the gateway credential owner."""
        assert provider_for_model(model_name=model_name) is ProviderName.OPENROUTER

    @pytest.mark.parametrize(
        "model_name",
        [
            "openrouter:",
            "openrouter:contains whitespace",
            "openrouter:https://example.test/model",
            "openrouter:" + ("a" * 513),
        ],
    )
    def test_qualified_openrouter_models_reject_invalid_route_syntax(self, model_name: str) -> None:
        """Invalid qualified OpenRouter routes fail before catalog membership checks."""
        with pytest.raises(ValueError, match="Invalid OpenRouter model route"):
            provider_for_model(model_name=model_name)

    def test_unknown_prefix_raises_value_error(self) -> None:
        """Unknown prefix → ``ValueError`` naming both prefix tables."""
        with pytest.raises(ValueError, match="Unsupported model_name"):
            provider_for_model(model_name="mistral-large")

    @pytest.mark.parametrize(
        "model_name",
        [
            "claude-opus-4-8",
            "claude-opus-4-8-1m-context",
            "claude-sonnet-4-6-1m-context",
            "claude-haiku-4-5",
        ],
    )
    def test_spec54_anthropic_models_map_to_anthropic(self, model_name: str) -> None:
        """Spec-54 Claude models resolve to ``ANTHROPIC``."""
        assert provider_for_model(model_name=model_name) is ProviderName.ANTHROPIC
