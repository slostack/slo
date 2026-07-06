"""Map a model name to its ``ProviderName`` (02.b.6)."""
from __future__ import annotations

from src.agents.base import ANTHROPIC_PREFIXES, KIMI_FOR_CODING_PREFIXES, OPENAI_PREFIXES
from src.auth.credential_dao import ProviderName


__all__ = ["provider_for_model"]


def provider_for_model(*, model_name: str) -> ProviderName:
    """Return the provider that owns ``model_name``.

    Reads the canonical prefix tables from ``src.agents.base`` so the
    auth layer never duplicates them. ``src.agents.base`` is import-safe
    (it doesn't transitively pull the auth layer back).

    Args:
        model_name (str): A model identifier from ``cfg("DEFAULT_MODEL_NAME")``.

    Returns:
        ProviderName: The owning provider.

    Raises:
        ValueError: When ``model_name`` matches no known prefix.
    """
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
