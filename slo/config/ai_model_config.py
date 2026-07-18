"""Per-model default options for the LLM factory.

``MODEL_DEFAULTS`` and provider landing-model helpers are now projections over
``ModelCatalogService``. Existing imports continue to work; the values are rebuilt
in place whenever the catalog snapshot changes so callers holding a reference see
updated values.
"""

from __future__ import annotations

from typing import Optional, TypedDict

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
    tokens_per_minute: int
    automatic_retry_attempts: int
    local_retry_wait_cap_seconds: int


__all__ = [
    "MODEL_DEFAULTS",
    "default_model_for_provider",
    "rebuild_model_defaults_projection",
    "resolve_model_name_with_fallback",
]


MODEL_DEFAULTS: dict[str, ModelDefaults] = {}
_PROVIDER_DEFAULT_MODELS: dict[ProviderName, str] = SeedModelCatalog.provider_default_models()


def rebuild_model_defaults_projection() -> None:
    """Rebuild legacy config maps from the canonical catalog in place."""
    snapshot = ModelCatalogService.load()
    projected_defaults: dict[str, ModelDefaults] = {}
    for entry in snapshot.entries.values():
        projected_defaults[entry.model_name] = {
            "max_tokens": entry.runtime_profile.max_tokens,
            "context_window": entry.runtime_profile.context_window,
            "streaming": entry.runtime_profile.streaming,
            "requests_per_minute": entry.runtime_profile.requests_per_minute,
            "tokens_per_minute": entry.runtime_profile.tokens_per_minute,
            "automatic_retry_attempts": entry.runtime_profile.automatic_retry_attempts,
            "local_retry_wait_cap_seconds": entry.runtime_profile.local_retry_wait_cap_seconds,
        }
        # Kimi For Coding family models require ``temperature=1``. Preserve
        # that provider-level constraint for every canonical Kimi entry,
        # including newer variants such as ``kimi-k3`` and
        # ``kimi-for-coding-highspeed``.
        if entry.provider is ProviderName.KIMI_FOR_CODING:
            projected_defaults[entry.model_name]["temperature"] = 1.0
        else:
            projected_defaults[entry.model_name]["temperature"] = 0.1
    MODEL_DEFAULTS.clear()
    MODEL_DEFAULTS.update(projected_defaults)


rebuild_model_defaults_projection()


def default_model_for_provider(*, provider: ProviderName) -> str:
    """Return the recommended landing model for one provider.

    Args:
        provider (ProviderName): Provider whose default model is needed.

    Returns:
        str: The recommended default model name.
    """
    return _PROVIDER_DEFAULT_MODELS[provider]


def resolve_model_name_with_fallback(*, model_name: str) -> tuple[str, Optional[str]]:
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
        ModelCatalogService.entry_for_model(model_name=model_name)
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
