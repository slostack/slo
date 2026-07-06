"""Tests for ``provider_for_model`` (02.b.6)."""
import pytest

from src.auth.credential_dao import ProviderName
from src.auth.provider_for_model import provider_for_model


class TestProviderForModel:
    """Pure-function mapping; one test per supported branch."""

    @pytest.mark.parametrize("model_name", [
        "claude-sonnet-4-6",
        "claude-opus-4-7",
    ])
    def test_anthropic_models_map_to_anthropic(self, model_name: str) -> None:
        """Any ``claude-*`` model resolves to ``ANTHROPIC``."""
        assert provider_for_model(model_name=model_name) is ProviderName.ANTHROPIC

    @pytest.mark.parametrize("model_name", [
        "gpt-5.4",
        "gpt-4.1",
        "o1",
        "o3-mini",
        "gpt-5-codex",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.3-codex-spark",
    ])
    def test_openai_models_map_to_openai(self, model_name: str) -> None:
        """``gpt-*``, ``o1*``, ``o3*`` resolve to ``OPENAI``."""
        assert provider_for_model(model_name=model_name) is ProviderName.OPENAI

    def test_unknown_prefix_raises_value_error(self) -> None:
        """Unknown prefix → ``ValueError`` naming both prefix tables."""
        with pytest.raises(ValueError, match="Unsupported model_name"):
            provider_for_model(model_name="mistral-large")
