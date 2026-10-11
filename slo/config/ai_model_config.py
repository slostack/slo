"""Per-model default options for the LLM factory.

``MODEL_DEFAULTS`` and provider landing-model helpers are now projections over
``ModelCatalogService``. Existing imports continue to work; the read-only views follow catalog publication without rebuild callbacks.
"""

from __future__ import annotations

from typing import Optional, TypedDict
from collections.abc import Iterator, Mapping
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO

from config.cfg import cfg
from config.logger import log_warning
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName


class ModelDefaults(TypedDict, total=False):
    temperature: float
    max_tokens: int
    context_window: int
    streaming: bool
    requests_per_minute: int
    tokens_per_minute: Optional[int]
    automatic_retry_attempts: int
    local_retry_wait_cap_seconds: int


__all__ = [
    "MODEL_DEFAULTS",
    "defaults_for_model",
    "default_model_for_provider",
    "rebuild_model_defaults_projection",
    "resolve_model_name_with_fallback",
]


class ModelDefaultsView(Mapping[str, ModelDefaults]):
    """Read-only live compatibility mapping; values are detached projections."""

    def __getitem__(self, model_name: str) -> ModelDefaults:
        """Read defaults from the currently published catalog."""
        try:
            return defaults_for_model(model_name=model_name)
        except ValueError as error:
            raise KeyError(model_name) from error

    def __iter__(self) -> Iterator[str]:
        """Iterate canonical keys from one generation."""
        return iter(ModelCatalogService.load().entries)

    def __len__(self) -> int:
        """Return the current canonical entry count."""
        return len(ModelCatalogService.load().entries)


def defaults_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> ModelDefaults:
    """Project detached defaults, using only snapshot when supplied."""
    entry = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
    profile = entry.runtime_profile
    return ModelDefaults(
        max_tokens=profile.max_tokens,
        context_window=profile.context_window,
        streaming=profile.streaming,
        requests_per_minute=profile.requests_per_minute,
        tokens_per_minute=profile.tokens_per_minute,
        automatic_retry_attempts=profile.automatic_retry_attempts,
        local_retry_wait_cap_seconds=profile.local_retry_wait_cap_seconds,
        temperature=1.0 if entry.provider is ProviderName.KIMI_FOR_CODING else 0.1,
    )


MODEL_DEFAULTS: Mapping[str, ModelDefaults] = ModelDefaultsView()


def rebuild_model_defaults_projection() -> None:
    """Deprecated no-op: compatibility reads now follow catalog publication."""


def default_model_for_provider(*, provider: ProviderName) -> Optional[str]:
    """Return the recommended landing model for one provider.

    Args:
        provider (ProviderName): Provider whose default model is needed.

    Returns:
        Optional[str]: Stable landing model, or None when explicit selection is required.
    """
    return SeedModelCatalog.provider_default_models()[provider]


def resolve_model_name_with_fallback(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> tuple[str, Optional[str]]:
    """Resolve a model name, falling back to defaults when it is invalid.

    Resolution order:
        1. Exact canonical catalog entry or alias.
        2. Provider prefix compatibility path.
        3. Global default model (``DEFAULT_MODEL_NAME``).

    Args:
        model_name (str): Requested model name from preferences or env.

    Returns:
        tuple[str, Optional[str]]: The resolved model name and an optional
            operator-visible notice when a fallback was used.
    """
    # Deferred import avoids a circular module dependency with
    # ``src.agents.base`` via ``src.auth.provider_for_model``.
    from src.auth.provider_for_model import provider_for_model

    try:
        ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
        return model_name, None
    except ValueError:
        pass
    try:
        provider_for_model(model_name=model_name)
        log_warning(
            msg="model_catalog_fallback_used",
            requested_model=model_name,
            notice=(
                f"Model '{model_name}' is not in the canonical catalog; "
                "using provider prefix compatibility path."
            ),
        )
        return (
            model_name,
            f"Model '{model_name}' is not in the catalog; it may use compatibility-only defaults.",
        )
    except ValueError:
        pass
    fallback_model_name: str = cfg("DEFAULT_MODEL_NAME") or "gpt-5.4"
    log_warning(
        msg="model_catalog_preference_invalid_fallback",
        requested_model=model_name,
        fallback_model=fallback_model_name,
    )
    return (
        fallback_model_name,
        f"Model '{model_name}' is not supported; falling back to {fallback_model_name}.",
    )
