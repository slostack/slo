"""Offline conversion and publication tests for OpenRouter catalog entries."""

from __future__ import annotations

from datetime import datetime, timezone


def test_converter_when_suitable_model_creates_exact_openrouter_entry() -> None:
    """Convert user-filtered wire metadata without inferring the upstream provider."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "anthropic/example-coder",
                "name": "Example Coder",
                "context_length": 200000,
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(tz=timezone.utc))

    assert result.entries[0].model_name == "openrouter:anthropic/example-coder"
    assert result.entries[0].api_model_name == "anthropic/example-coder"
    assert result.entries[0].provider.value == "openrouter"
    assert result.entries[0].visible_in_picker is True


def test_converter_when_label_has_words_keeps_words_intact() -> None:
    """Sanitize external labels without splitting ordinary printable characters."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "vendor/example-coder",
                "name": "Example Coder",
                "context_length": 3,
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(tz=timezone.utc))

    assert result.entries[0].display_name == "Example Coder"
    assert result.entries[0].visible_in_picker is True


def test_converter_when_expired_or_remote_output_cap_is_present_uses_conservative_cap() -> None:
    """Exclude expired routes and retain the smaller advertised output limit."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "vendor/expired",
                "context_length": 100,
                "top_provider": {"max_completion_tokens": 3},
                "expiration_date": "2000-01-01",
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(
        response=response,
        now=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert result.entries[0].visible_in_picker is False
    assert result.entries[0].availability == "expired"
    assert result.entries[0].runtime_profile.max_tokens == 3


def test_converter_when_top_provider_context_is_smaller_uses_smaller_cap() -> None:
    """Use the conservative endpoint context ceiling rather than model context alone."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "vendor/lower-endpoint-context",
                "context_length": 1000,
                "top_provider": {"context_length": 100},
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(tz=timezone.utc))

    assert result.entries[0].runtime_profile.context_window == 100
    assert result.entries[0].runtime_profile.max_tokens == 50


def test_converter_when_context_is_two_keeps_valid_minimum_context_selectable() -> None:
    """Accept the documented inclusive minimum context boundary."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "vendor/minimum-context",
                "context_length": 2,
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(tz=timezone.utc))

    assert result.entries[0].visible_in_picker is True
    assert result.entries[0].runtime_profile.max_tokens == 1


def test_converter_when_model_lacks_tools_keeps_it_unselectable() -> None:
    """Keep valid ineligible records for reconciliation instead of advertising them."""
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO

    response: OpenRouterModelsResponseDAO = OpenRouterModelsResponseDAO(
        data=[
            {
                "id": "vendor/no-tools",
                "context_length": 200000,
                "supported_parameters": [],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ]
    )

    result = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(tz=timezone.utc))

    assert result.entries[0].visible_in_picker is False
