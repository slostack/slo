"""Supported interactive model catalog helpers for the TUI."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from config.ai_model_config import MODEL_DEFAULTS
from src.agents.reasoning_capabilities import capability_for_model
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model

__all__ = [
    "MODEL_CATALOG",
    "ModelCatalogEntryDAO",
    "ModelSuggestionEntryDAO",
    "model_suggestion_entries",
    "supported_models_by_provider",
]


class ModelCatalogEntryDAO(BaseModel):
    """One entry in the static model catalog for the TUI picker.

    Attributes:
        provider (str): Provider group label (e.g. ``"anthropic"``).
        display_name (str): Human-readable label shown in the picker.
        model_name (str): Canonical model identifier passed to LLMFactory.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    display_name: str
    model_name: str


MODEL_CATALOG: list[ModelCatalogEntryDAO] = [
    # ------------------------------------------------------------------
    # Anthropic — Claude 4.x family
    # ------------------------------------------------------------------
    ModelCatalogEntryDAO(
        provider="anthropic",
        display_name="Claude Opus 4.7",
        model_name="claude-opus-4-7",
    ),
    ModelCatalogEntryDAO(
        provider="anthropic",
        display_name="Claude Sonnet 4.6",
        model_name="claude-sonnet-4-6",
    ),
    # ------------------------------------------------------------------
    # OpenAI — Codex-optimized coding models
    # ------------------------------------------------------------------
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5 Codex",
        model_name="gpt-5-codex",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5.3 Codex",
        model_name="gpt-5.3-codex",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5.3 Codex Spark",
        model_name="gpt-5.3-codex-spark",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5.2 Codex",
        model_name="gpt-5.2-codex",
    ),
    # ------------------------------------------------------------------
    # OpenAI — flagship GPT and reasoning models
    # ------------------------------------------------------------------
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5.4",
        model_name="gpt-5.4",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-5",
        model_name="gpt-5",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-4.1",
        model_name="gpt-4.1",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="GPT-4o",
        model_name="gpt-4o",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="o3",
        model_name="o3",
    ),
    ModelCatalogEntryDAO(
        provider="openai",
        display_name="o1",
        model_name="o1",
    ),
    # ------------------------------------------------------------------
    # Kimi For Coding (KFC) — api.kimi.com/coding/v1
    # ------------------------------------------------------------------
    ModelCatalogEntryDAO(
        provider="kimi_for_coding",
        display_name="Kimi For Coding (K2)",
        model_name="kimi-for-coding",
    ),
]


class ModelSuggestionEntryDAO(BaseModel):
    """One supported model row for ``/model`` suggestions."""

    model_config = ConfigDict(extra="forbid")

    model_name: str
    provider: ProviderName
    is_active: bool
    requires_auth: bool
    reasoning_summary: str


def supported_models_by_provider() -> dict[ProviderName, list[str]]:
    """Return the supported interactive model catalog grouped by provider.

    Returns:
        dict[ProviderName, list[str]]: Deterministically sorted model
            names grouped by provider.
    """
    grouped: dict[ProviderName, list[str]] = {
        ProviderName.ANTHROPIC: [],
        ProviderName.OPENAI: [],
        ProviderName.KIMI_FOR_CODING: [],
    }
    for model_name in sorted(MODEL_DEFAULTS.keys()):
        grouped[provider_for_model(model_name=model_name)].append(model_name)
    return grouped


def model_suggestion_entries(*, active_model_name: str) -> list[ModelSuggestionEntryDAO]:
    """Return rich model rows for ``/model`` suggestions.

    Args:
        active_model_name (str): Current session model.

    Returns:
        list[ModelSuggestionEntryDAO]: Deterministically ordered model rows.
    """
    entries: list[ModelSuggestionEntryDAO] = []
    for model_name in sorted(MODEL_DEFAULTS.keys()):
        provider: ProviderName = provider_for_model(model_name=model_name)
        capability = capability_for_model(model_name=model_name)
        entries.append(
            ModelSuggestionEntryDAO(
                model_name=model_name,
                provider=provider,
                is_active=(model_name == active_model_name),
                requires_auth=(CredentialResolver.resolve(provider=provider) is None),
                reasoning_summary=", ".join(capability.supported_levels),
            )
        )
    return entries
