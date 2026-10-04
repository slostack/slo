"""Map a model name to its ``ProviderName`` (02.b.6)."""

from __future__ import annotations

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName

__all__ = [
    "ANTHROPIC_PREFIXES",
    "KIMI_FOR_CODING_PREFIXES",
    "OPENAI_PREFIXES",
    "OPENROUTER_PREFIX",
    "provider_for_model",
]


ANTHROPIC_PREFIXES: tuple[str, ...] = ("claude-",)
OPENAI_PREFIXES: tuple[str, ...] = ("gpt-", "o1", "o3")
KIMI_FOR_CODING_PREFIXES: tuple[str, ...] = ("kimi-", "moonshot-")
OPENROUTER_PREFIX: str = "openrouter:"
_OPENROUTER_MAX_ROUTE_LENGTH: int = 512


def provider_for_model(*, model_name: str) -> ProviderName:
    """Return the provider that owns ``model_name``.

    Resolution order:

    1. Exact canonical catalog entry or explicit alias.
    2. Provider prefix fallback for compatibility-only or not-yet-seeded names.

    Args:
        model_name (str): A model identifier from ``cfg("DEFAULT_MODEL_NAME")``.

    Returns:
        ProviderName: The owning provider.

    Raises:
        ValueError: When ``model_name`` matches no known catalog entry or prefix.
    """
    if model_name.startswith(OPENROUTER_PREFIX):
        _validate_openrouter_route(model_name=model_name)
        return ProviderName.OPENROUTER
    try:
        entry = ModelCatalogService.entry_for_model(model_name=model_name)
        return entry.provider
    except ValueError:
        pass
    if model_name.startswith(ANTHROPIC_PREFIXES):
        return ProviderName.ANTHROPIC
    if model_name.startswith(OPENAI_PREFIXES):
        return ProviderName.OPENAI
    if model_name.startswith(KIMI_FOR_CODING_PREFIXES):
        return ProviderName.KIMI_FOR_CODING
    raise ValueError(
        f"Unsupported model_name '{model_name}'. "
        f"Expected one of: {ANTHROPIC_PREFIXES + OPENAI_PREFIXES + KIMI_FOR_CODING_PREFIXES}."
    )


def _validate_openrouter_route(*, model_name: str) -> None:
    """Reject malformed OpenRouter route syntax before catalog membership checks.

    Args:
        model_name (str): Qualified route supplied by the caller.

    Raises:
        ValueError: The route has an empty, unsafe, or oversized API identifier.
    """
    api_model_name: str = model_name.removeprefix(OPENROUTER_PREFIX)
    if not api_model_name or len(api_model_name) > _OPENROUTER_MAX_ROUTE_LENGTH:
        raise ValueError("Invalid OpenRouter model route.")
    if api_model_name.startswith(("http://", "https://")):
        raise ValueError("Invalid OpenRouter model route.")
    if any(
        not character.isascii() or not character.isprintable() or character.isspace()
        for character in api_model_name
    ):
        raise ValueError("Invalid OpenRouter model route.")
