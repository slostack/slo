"""Tests for ``config.model_pool_config.parse_model_pool_config`` (spec 37.a.4)."""

from __future__ import annotations

import pytest

from config.model_pool_config import parse_model_pool_config
from src.auth.credential_dao import ProviderName


class TestParseModelPoolConfig:
    def test_two_names_build_priority_ordered_pool(self) -> None:
        """Two comma-separated names become priority-ordered pool entries."""
        dao = parse_model_pool_config(raw_value="gpt-5.4,claude-sonnet-4-6")
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["gpt-5.4", "claude-sonnet-4-6"]
        assert [e.priority for e in dao.entries] == [0, 1]

    def test_infers_provider_per_member(self) -> None:
        """Each member's provider is inferred via provider_for_model."""
        dao = parse_model_pool_config(raw_value="gpt-5.4,claude-sonnet-4-6,kimi-for-coding")
        assert dao is not None
        assert dao.entries[0].provider is ProviderName.OPENAI
        assert dao.entries[1].provider is ProviderName.ANTHROPIC
        assert dao.entries[2].provider is ProviderName.KIMI_FOR_CODING

    def test_strips_whitespace_around_names(self) -> None:
        """Surrounding whitespace is stripped from each model name."""
        dao = parse_model_pool_config(raw_value=" gpt-5.4 , claude-sonnet-4-6 ")
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["gpt-5.4", "claude-sonnet-4-6"]

    def test_single_member_returns_none(self) -> None:
        """A single member is not a pool (needs >= 2); returns None."""
        assert parse_model_pool_config(raw_value="gpt-5.4") is None

    def test_empty_returns_none(self) -> None:
        """An empty value returns None (single-model path)."""
        assert parse_model_pool_config(raw_value="") is None

    def test_preference_value_used_when_no_raw_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The preference fallback is parsed when no raw value / env is set."""
        monkeypatch.setattr("config.model_pool_config.cfg", lambda key: None)
        dao = parse_model_pool_config(raw_value=None, preference_value="gpt-5.4,claude-sonnet-4-6")
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["gpt-5.4", "claude-sonnet-4-6"]

    def test_latest_model_pool_parses(self) -> None:
        """Spec-55 latest models can be combined in a pool."""
        dao = parse_model_pool_config(raw_value="gpt-5.5,claude-fable,kimi-k3")
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["gpt-5.5", "claude-fable", "kimi-k3"]
        assert dao.entries[0].provider is ProviderName.OPENAI
        assert dao.entries[1].provider is ProviderName.ANTHROPIC
        assert dao.entries[2].provider is ProviderName.KIMI_FOR_CODING

    def test_claude_mythos_allowed_in_pool(self) -> None:
        """The conditional entry can be explicitly named in a pool."""
        dao = parse_model_pool_config(raw_value="claude-mythos,gpt-5.5")
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["claude-mythos", "gpt-5.5"]
        assert dao.entries[0].provider is ProviderName.ANTHROPIC

    def test_unknown_model_raises(self) -> None:
        """A model name matching no provider prefix surfaces as a ValueError."""
        with pytest.raises(ValueError):
            parse_model_pool_config(raw_value="gpt-5.4,not-a-real-model")


class TestParseModelPoolConfigJsonArrayForm:
    """JSON-array form for SLO_MODEL_POOL."""

    def test_json_string_array_builds_pool(self) -> None:
        """A JSON array of strings is parsed identically to the comma-list form."""
        dao = parse_model_pool_config(raw_value='["gpt-5.4", "claude-sonnet-4-6"]')
        assert dao is not None
        assert [e.model_name for e in dao.entries] == ["gpt-5.4", "claude-sonnet-4-6"]
        assert [e.priority for e in dao.entries] == [0, 1]

    def test_json_string_array_infers_provider(self) -> None:
        """JSON array string form infers providers exactly as the comma-list form does."""
        from src.auth.credential_dao import ProviderName

        dao = parse_model_pool_config(raw_value='["gpt-5.4", "claude-opus-4-8"]')
        assert dao is not None
        assert dao.entries[0].provider is ProviderName.OPENAI
        assert dao.entries[1].provider is ProviderName.ANTHROPIC

    def test_json_object_array_builds_pool_with_explicit_fields(self) -> None:
        """A JSON array of objects passes through explicit priority and cooldown."""
        dao = parse_model_pool_config(
            raw_value=(
                '[{"model_name":"gpt-5.4","priority":0},' '{"model_name":"claude-sonnet-4-6","priority":1}]'
            )
        )
        assert dao is not None
        assert dao.entries[0].model_name == "gpt-5.4"
        assert dao.entries[1].model_name == "claude-sonnet-4-6"

    def test_json_object_array_infers_missing_provider(self) -> None:
        """JSON objects without 'provider' get it inferred from the model name."""
        from src.auth.credential_dao import ProviderName

        dao = parse_model_pool_config(raw_value='[{"model_name":"gpt-5.4"},{"model_name":"claude-opus-4-8"}]')
        assert dao is not None
        assert dao.entries[0].provider is ProviderName.OPENAI

    def test_json_object_array_defaults_missing_priority_to_index(self) -> None:
        """JSON objects without 'priority' receive the element's zero-based index."""
        dao = parse_model_pool_config(
            raw_value='[{"model_name":"gpt-5.4"},{"model_name":"claude-sonnet-4-6"}]'
        )
        assert dao is not None
        assert dao.entries[0].priority == 0
        assert dao.entries[1].priority == 1

    def test_json_object_array_rejects_mismatched_provider(self) -> None:
        """An explicit provider cannot contradict canonical route ownership."""
        with pytest.raises(ValueError, match="provider does not match"):
            parse_model_pool_config(
                raw_value=(
                    '[{"model_name":"openrouter:anthropic/claude-sonnet-5.5",'
                    '"provider":"anthropic"},{"model_name":"gpt-5.4"}]'
                )
            )

    def test_json_single_element_returns_none(self) -> None:
        """A JSON array with one element is treated as a single-model path (None)."""
        result = parse_model_pool_config(raw_value='["gpt-5.4"]')
        assert result is None

    def test_json_empty_array_returns_none(self) -> None:
        """An empty JSON array returns None."""
        assert parse_model_pool_config(raw_value="[]") is None

    def test_invalid_json_raises_value_error(self) -> None:
        """A string starting with '[' that is not valid JSON raises ValueError."""
        with pytest.raises(ValueError, match="could not be parsed"):
            parse_model_pool_config(raw_value="[gpt-5.4, claude]")

    def test_json_nested_array_raises_value_error(self) -> None:
        """A JSON array whose elements are nested arrays raises ValueError."""
        with pytest.raises(ValueError, match="must be a string or object"):
            parse_model_pool_config(raw_value='[["gpt-5.4"], ["claude-sonnet-4-6"]]')

    def test_json_object_missing_model_name_raises(self) -> None:
        """A JSON object without 'model_name' raises ValueError with index."""
        with pytest.raises(ValueError, match="missing 'model_name'"):
            parse_model_pool_config(raw_value='[{"priority":0},{"model_name":"claude-sonnet-4-6"}]')

    def test_json_unknown_type_element_raises(self) -> None:
        """A JSON array containing a non-string, non-dict element raises ValueError."""
        with pytest.raises(ValueError, match="must be a string or object"):
            parse_model_pool_config(raw_value="[42, 99]")
