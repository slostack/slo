"""Supported interactive model catalog helpers for the TUI."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver

__all__ = [
    "MODEL_CATALOG",
    "ModelCatalogEntryDAO",
    "ModelSuggestionEntryDAO",
    "model_suggestion_entries",
    "supported_models_by_provider",
]


class ModelCatalogEntryDAO(BaseModel):
    """One entry in the model catalog for the TUI picker.

    Attributes:
        provider (str): Provider group label (e.g. ``"anthropic"``).
        display_name (str): Human-readable label shown in the picker.
        model_name (str): Canonical model identifier passed to LLMFactory.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    display_name: str
    model_name: str


class ModelSuggestionEntryDAO(BaseModel):
    """One supported model row for ``/model`` suggestions."""

    model_config = ConfigDict(extra="forbid")

    model_name: str
    provider: ProviderName
    is_active: bool
    requires_auth: bool
    reasoning_summary: str
    support_tier_label: str


MODEL_CATALOG: list[ModelCatalogEntryDAO] = []
"""Compatibility re-export of the visible catalog entries."""


def _rebuild_model_catalog() -> None:
    """Populate the legacy ``MODEL_CATALOG`` list from the canonical catalog."""
    snapshot = ModelCatalogService.load()
    entries: list[ModelCatalogEntryDAO] = []
    for entry in sorted(snapshot.entries.values(), key=lambda item: (item.provider.value, item.model_name)):
        if not entry.visible_in_picker:
            continue
        entries.append(
            ModelCatalogEntryDAO(
                provider=entry.provider.value,
                display_name=entry.display_name,
                model_name=entry.model_name,
            )
        )
    MODEL_CATALOG.clear()
    MODEL_CATALOG.extend(entries)


_rebuild_model_catalog()


def supported_models_by_provider() -> dict[ProviderName, list[str]]:
    """Return the supported interactive model catalog grouped by provider.

    Returns:
        dict[ProviderName, list[str]]: Deterministically sorted model
            names grouped by provider.
    """
    return ModelCatalogService.supported_models_by_provider()


def model_suggestion_entries(*, active_model_name: str) -> list[ModelSuggestionEntryDAO]:
    """Return rich model rows for ``/model`` suggestions.

    Args:
        active_model_name (str): Current session model.

    Returns:
        list[ModelSuggestionEntryDAO]: Deterministically ordered model rows.
    """
    snapshot = ModelCatalogService.load()
    entries: list[ModelSuggestionEntryDAO] = []
    for entry in sorted(snapshot.entries.values(), key=lambda item: (item.provider.value, item.model_name)):
        if not entry.visible_in_picker:
            continue
        support_tier_label: str = ""
        if entry.support_tier == "auto_discovered":
            support_tier_label = "auto-discovered"
        entries.append(
            ModelSuggestionEntryDAO(
                model_name=entry.model_name,
                provider=entry.provider,
                is_active=(entry.model_name == active_model_name),
                requires_auth=(CredentialResolver.resolve(provider=entry.provider) is None),
                reasoning_summary=", ".join(entry.reasoning_profile.supported_levels),
                support_tier_label=support_tier_label,
            )
        )
    return entries
