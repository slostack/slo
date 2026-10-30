"""Tests for ``config.ai_model_config.MODEL_DEFAULTS`` (spec 02.a §8).

These lock in the per-model output ceilings introduced by spec
``specifications/02-output-token-limits-and-truncation/02.a-per-model-output-ceilings.md``.
The flat 8192 cap truncated large tool calls (the ``WriteSchemaDAO`` failure);
the Anthropic models now carry their real ceilings, mirroring pi.
"""

from __future__ import annotations

from config.ai_model_config import (
    MODEL_DEFAULTS,
    default_model_for_provider,
    resolve_model_name_with_fallback,
)
from src.auth.credential_dao import ProviderName
import pytest


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
def test_gpt6_defaults_are_catalog_projection(model_name: str) -> None:
    """Pinned projection includes every runtime field and restores seed after removal."""
    from unittest.mock import patch
    from config.ai_model_config import defaults_for_model
    from src.agents.model_catalog.dao import ModelCatalogOverrideDAO
    from src.agents.model_catalog.discovery import ModelCatalogOverrideService
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.model_catalog.service import ModelCatalogService

    seed = SeedModelCatalog.load()
    expected = dict(
        max_tokens=128000,
        context_window=1050000,
        streaming=True,
        requests_per_minute=500,
        tokens_per_minute=500000,
        automatic_retry_attempts=2,
        local_retry_wait_cap_seconds=30,
        temperature=0.1,
    )
    override = ModelCatalogOverrideDAO(
        model_name=model_name,
        runtime_profile=seed.entries[model_name].runtime_profile.model_copy(update={"max_tokens": 1234}),
    )
    changed = ModelCatalogOverrideService.apply_overrides(snapshot=seed, overrides=[override])
    removed = ModelCatalogOverrideService.apply_overrides(snapshot=seed, overrides=[])
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load")):
        assert defaults_for_model(model_name=model_name, snapshot=seed) == expected
        assert defaults_for_model(model_name=model_name, snapshot=changed) == {**expected, "max_tokens": 1234}
        assert defaults_for_model(model_name=model_name, snapshot=removed) == expected


def test_sonnet_4_6_default_max_tokens_is_64000() -> None:
    """``claude-sonnet-4-6`` uses its real 64K output ceiling, not the old 8192."""
    assert MODEL_DEFAULTS["claude-sonnet-4-6"]["max_tokens"] == 64_000


def test_opus_4_7_default_max_tokens_is_128000() -> None:
    """``claude-opus-4-7`` uses its real 128K output ceiling, not the old 8192."""
    assert MODEL_DEFAULTS["claude-opus-4-7"]["max_tokens"] == 128_000


class TestLatestModelDefaults:
    """Runtime defaults for spec-55 first-class models."""

    def test_gpt_5_5_default_max_tokens_is_8192(self) -> None:
        """``gpt-5.5`` carries the standard OpenAI 8K output ceiling."""
        assert MODEL_DEFAULTS["gpt-5.5"]["max_tokens"] == 8192

    def test_gpt_5_5_context_window_is_1_050_000(self) -> None:
        """``gpt-5.5`` exposes the wide 1.05M input context window."""
        assert MODEL_DEFAULTS["gpt-5.5"]["context_window"] == 1_050_000

    def test_claude_fable_max_tokens_is_64000(self) -> None:
        """``claude-fable`` uses the 64K output ceiling."""
        assert MODEL_DEFAULTS["claude-fable"]["max_tokens"] == 64_000

    def test_kimi_k3_context_window_is_262144(self) -> None:
        """``kimi-k3`` carries the 262K context window."""
        assert MODEL_DEFAULTS["kimi-k3"]["context_window"] == 262_144

    def test_kimi_for_coding_highspeed_requests_per_minute_is_40(self) -> None:
        """``kimi-for-coding-highspeed`` has a higher RPM ceiling."""
        assert MODEL_DEFAULTS["kimi-for-coding-highspeed"]["requests_per_minute"] == 40


class TestClaude48ModelDefaults:
    """Runtime defaults for spec-54 first-class Claude entries."""

    def test_opus_4_8_1m_context_window_is_1_000_000(self) -> None:
        """``claude-opus-4-8-1m-context`` exposes the 1M input context window."""
        assert MODEL_DEFAULTS["claude-opus-4-8-1m-context"]["context_window"] == 1_000_000

    def test_opus_4_8_context_window_is_200_000(self) -> None:
        """``claude-opus-4-8`` keeps the 200K input context window."""
        assert MODEL_DEFAULTS["claude-opus-4-8"]["context_window"] == 200_000

    def test_opus_4_8_default_max_tokens_is_128000(self) -> None:
        """``claude-opus-4-8`` uses the 128K output ceiling."""
        assert MODEL_DEFAULTS["claude-opus-4-8"]["max_tokens"] == 128_000

    def test_sonnet_4_6_1m_context_window_is_1_000_000(self) -> None:
        """``claude-sonnet-4-6-1m-context`` exposes the 1M input context window."""
        assert MODEL_DEFAULTS["claude-sonnet-4-6-1m-context"]["context_window"] == 1_000_000

    def test_haiku_4_5_default_max_tokens_is_64000(self) -> None:
        """``claude-haiku-4-5`` uses the 64K output ceiling."""
        assert MODEL_DEFAULTS["claude-haiku-4-5"]["max_tokens"] == 64_000

    @pytest.mark.parametrize(
        "model_name",
        ["kimi-for-coding", "kimi-k3", "kimi-for-coding-highspeed"],
    )
    def test_kimi_family_models_require_temperature_one(self, model_name: str) -> None:
        """Every canonical Kimi family model keeps the required temperature=1."""
        assert MODEL_DEFAULTS[model_name]["temperature"] == 1


class TestProviderDefaultModels:
    """Provider landing models are derived from the catalog seed."""

    def test_default_model_for_provider_anthropic(self) -> None:
        """Anthropic landing model is the spec-54 Claude Opus 4.8 1M-context entry."""
        assert default_model_for_provider(provider=ProviderName.ANTHROPIC) == "claude-opus-4-8-1m-context"

    def test_default_model_for_provider_openai(self) -> None:
        """OpenAI landing model remains stable."""
        assert default_model_for_provider(provider=ProviderName.OPENAI) == "gpt-5.4"

    def test_default_model_for_provider_kimi_for_coding(self) -> None:
        """Kimi For Coding landing model remains stable."""
        assert default_model_for_provider(provider=ProviderName.KIMI_FOR_CODING) == "kimi-for-coding"


class TestResolveModelNameWithFallback:
    """Invalid saved preferences fall back safely."""

    def test_resolves_canonical_model_without_notice(self) -> None:
        """A known canonical model resolves unchanged."""
        resolved, notice = resolve_model_name_with_fallback(model_name="gpt-5.5")
        assert resolved == "gpt-5.5"
        assert notice is None

    def test_resolves_legacy_alias_without_notice(self) -> None:
        """A known alias resolves to its canonical entry without a fallback notice."""
        resolved, notice = resolve_model_name_with_fallback(model_name="moonshot-for-coding")
        assert resolved == "moonshot-for-coding"
        assert notice is None

    def test_compatibility_prefix_path_returns_notice(self) -> None:
        """A recognized prefix that is not in the catalog uses the compatibility path."""
        resolved, notice = resolve_model_name_with_fallback(model_name="claude-legacy-model")
        assert resolved == "claude-legacy-model"
        assert notice is not None
        assert "compatibility-only" in notice

    def test_unrecognized_model_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unrecognizable model falls back to the global default."""
        # cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
        # is captured at config.cfg import, before this test's patch.
        monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
        resolved, notice = resolve_model_name_with_fallback(model_name="mistral-large")
        assert resolved == "gpt-5.4"
        assert notice is not None
        assert "falling back" in notice


class TestCodexModelDefaults:
    """Lock tests for the OpenAI Codex model defaults (spec 47)."""

    def test_gpt_5_codex_max_tokens_is_8192(self) -> None:
        """``gpt-5-codex`` carries the standard OpenAI 8K output ceiling."""
        assert MODEL_DEFAULTS["gpt-5-codex"]["max_tokens"] == 8192

    def test_gpt_5_codex_context_window_is_1_050_000(self) -> None:
        """``gpt-5-codex`` exposes the wide 1.05M input context window."""
        assert MODEL_DEFAULTS["gpt-5-codex"]["context_window"] == 1_050_000

    def test_gpt_5_3_codex_context_window_is_1_050_000(self) -> None:
        """``gpt-5.3-codex`` mirrors the 1.05M context window of the flagship variant."""
        assert MODEL_DEFAULTS["gpt-5.3-codex"]["context_window"] == 1_050_000

    def test_gpt_5_3_codex_spark_context_window_is_1_050_000(self) -> None:
        """``gpt-5.3-codex-spark`` retains the wide 1.05M context window."""
        assert MODEL_DEFAULTS["gpt-5.3-codex-spark"]["context_window"] == 1_050_000

    def test_gpt_5_2_codex_context_window_is_400_000(self) -> None:
        """``gpt-5.2-codex`` uses the compact 400K context window."""
        assert MODEL_DEFAULTS["gpt-5.2-codex"]["context_window"] == 400_000

    def test_codex_models_keep_streaming_true(self) -> None:
        """All Codex variants stream by default."""
        assert MODEL_DEFAULTS["gpt-5-codex"]["streaming"] is True
        assert MODEL_DEFAULTS["gpt-5.3-codex"]["streaming"] is True
        assert MODEL_DEFAULTS["gpt-5.3-codex-spark"]["streaming"] is True
        assert MODEL_DEFAULTS["gpt-5.2-codex"]["streaming"] is True


class TestAstraModelDefaults:
    """Feature 83.a.1: MODEL_DEFAULTS projects the Astra seed runtime policy."""

    def test_astra_defaults_project_seed_runtime_policy(self) -> None:
        """The projection carries every documented/runtime value and no invented field."""
        defaults = MODEL_DEFAULTS["gpt-6-astra"]

        assert defaults["max_tokens"] == 128_000
        assert defaults["context_window"] == 1_050_000
        assert defaults["streaming"] is True
        assert defaults["requests_per_minute"] == 500
        assert defaults["tokens_per_minute"] == 500_000
        assert defaults["automatic_retry_attempts"] == 2
        assert defaults["local_retry_wait_cap_seconds"] == 30
        assert defaults["temperature"] == 0.1
        assert "max_input" not in defaults
