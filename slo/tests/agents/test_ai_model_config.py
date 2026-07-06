"""Tests for ``config.ai_model_config.MODEL_DEFAULTS`` (spec 02.a §8).

These lock in the per-model output ceilings introduced by spec
``specifications/02-output-token-limits-and-truncation/02.a-per-model-output-ceilings.md``.
The flat 8192 cap truncated large tool calls (the ``WriteSchemaDAO`` failure);
the Anthropic models now carry their real ceilings, mirroring pi.
"""

from __future__ import annotations

from config.ai_model_config import MODEL_DEFAULTS


def test_sonnet_4_6_default_max_tokens_is_64000() -> None:
    """``claude-sonnet-4-6`` uses its real 64K output ceiling, not the old 8192."""
    assert MODEL_DEFAULTS["claude-sonnet-4-6"]["max_tokens"] == 64_000


def test_opus_4_7_default_max_tokens_is_128000() -> None:
    """``claude-opus-4-7`` uses its real 128K output ceiling, not the old 8192."""
    assert MODEL_DEFAULTS["claude-opus-4-7"]["max_tokens"] == 128_000


def test_anthropic_models_keep_streaming_true() -> None:
    """Large ``max_tokens`` requires streaming (Anthropic SDK refuses non-streaming)."""
    assert MODEL_DEFAULTS["claude-sonnet-4-6"]["streaming"] is True
    assert MODEL_DEFAULTS["claude-opus-4-7"]["streaming"] is True


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
