"""Reasoning capability catalog and clamping helpers for Slo.

This module is now a compatibility projection over the canonical model catalog
in ``src.agents.model_catalog``. It preserves the historical public helpers
(``capability_for_model``, ``clamp_reasoning_level``, ``resolve_reasoning_config``,
``MODEL_REASONING_CAPABILITIES``) while sourcing truth from the catalog.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.model_catalog.dao import ReasoningLevel
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName

__all__ = [
    "MODEL_REASONING_CAPABILITIES",
    "ModelReasoningCapabilityDAO",
    "REASONING_LEVELS",
    "ReasoningLevel",
    "ResolvedReasoningConfigDAO",
    "capability_for_model",
    "clamp_reasoning_level",
    "default_reasoning_level_for_model",
    "highest_supported_reasoning_level",
    "parse_reasoning_level",
    "resolve_reasoning_config",
    "supported_reasoning_levels_for_model",
]


ReasoningLevel = ReasoningLevel


REASONING_LEVELS: tuple[ReasoningLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
"""Ordered canonical reasoning levels used for clamping."""


class ModelReasoningCapabilityDAO(BaseModel):
    """Reasoning support metadata for one supported interactive model.

    Attributes:
        reasoning_supported (bool): True when the model accepts a
            provider-native reasoning or thinking payload.
        supported_levels (list[ReasoningLevel]): Ordered canonical
            levels Slo exposes for this model.
        default_level (ReasoningLevel): Default seeded level when the
            caller does not supply an explicit override.
        provider_effort_map (dict[ReasoningLevel, str]): Optional
            per-level provider-native effort mapping.
        provider_budget_map (dict[ReasoningLevel, int]): Optional
            per-level provider-native thinking-budget mapping.
        provider_summary_mode (Optional[str]): Optional provider-native
            reasoning summary mode.
    """

    model_config = ConfigDict(extra="forbid")

    reasoning_supported: bool
    supported_levels: list[ReasoningLevel]
    default_level: ReasoningLevel = "high"
    provider_effort_map: dict[ReasoningLevel, str] = Field(default_factory=dict)
    provider_budget_map: dict[ReasoningLevel, int] = Field(default_factory=dict)
    provider_summary_mode: Optional[str] = None


class ResolvedReasoningConfigDAO(BaseModel):
    """Provider-ready reasoning configuration after clamping.

    Attributes:
        enabled (bool): False when reasoning is off or unsupported.
        requested_level (ReasoningLevel): Requested canonical level.
        active_level (ReasoningLevel): Final clamped canonical level.
        provider_effort (Optional[str]): Provider-native effort string.
        provider_budget_tokens (Optional[int]): Provider-native thinking
            budget in tokens.
        provider_summary_mode (Optional[str]): Provider-native summary mode.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    requested_level: ReasoningLevel
    active_level: ReasoningLevel
    provider_effort: Optional[str] = None
    provider_budget_tokens: Optional[int] = None
    provider_summary_mode: Optional[str] = None


MODEL_REASONING_CAPABILITIES: dict[str, ModelReasoningCapabilityDAO] = {}
"""Compatibility projection from the canonical model catalog."""


def _provider_summary_mode_for_model(*, model_name: str) -> Optional[str]:
    """Derive the provider-native summary mode for a model.

    OpenAI reasoning models use ``responses`` API with ``auto`` summary mode.
    Anthropic adaptive thinking and Kimi do not expose this mode.

    Args:
        model_name (str): Canonical model name.

    Returns:
        Optional[str]: Provider summary mode, or ``None`` when not applicable.
    """
    provider = ModelCatalogService.entry_for_model(model_name=model_name).provider
    if provider is ProviderName.OPENAI:
        return "auto"
    return None


def _catalog_entry_to_capability(
    *,
    model_name: str,
) -> ModelReasoningCapabilityDAO:
    """Project one catalog entry into the legacy capability shape.

    Args:
        model_name (str): Canonical model name or known alias.

    Returns:
        ModelReasoningCapabilityDAO: Legacy capability record.
    """
    entry = ModelCatalogService.entry_for_model(model_name=model_name)
    profile = entry.reasoning_profile
    reasoning_supported = profile.supported_levels != ["off"]
    return ModelReasoningCapabilityDAO(
        reasoning_supported=reasoning_supported,
        supported_levels=list(profile.supported_levels),
        default_level=profile.default_level,
        provider_effort_map=dict(profile.provider_effort_map),
        provider_budget_map=dict(profile.provider_budget_map),
        provider_summary_mode=_provider_summary_mode_for_model(model_name=entry.model_name),
    )


def rebuild_reasoning_capabilities_projection() -> None:
    """Rebuild the legacy capability map in place from the canonical catalog."""
    snapshot = ModelCatalogService.load()
    projected: dict[str, ModelReasoningCapabilityDAO] = {}
    for model_name in snapshot.entries:
        projected[model_name] = _catalog_entry_to_capability(model_name=model_name)
    MODEL_REASONING_CAPABILITIES.clear()
    MODEL_REASONING_CAPABILITIES.update(projected)


rebuild_reasoning_capabilities_projection()


def capability_for_model(*, model_name: str) -> ModelReasoningCapabilityDAO:
    """Return the reasoning capability record for one supported model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ModelReasoningCapabilityDAO: Capability metadata for the model.

    Raises:
        ValueError: If ``model_name`` is outside Slo's supported
            interactive catalog.
    """
    capability: Optional[ModelReasoningCapabilityDAO] = MODEL_REASONING_CAPABILITIES.get(
        model_name,
    )
    if capability is None:
        supported_models: str = ", ".join(sorted(MODEL_REASONING_CAPABILITIES))
        raise ValueError(f"Unsupported reasoning model '{model_name}'. Supported models: {supported_models}")
    return capability


def supported_reasoning_levels_for_model(*, model_name: str) -> list[ReasoningLevel]:
    """Return the ordered supported reasoning levels for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        list[ReasoningLevel]: Ordered supported levels.
    """
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name)
    return list(capability.supported_levels)


def default_reasoning_level_for_model(*, model_name: str) -> ReasoningLevel:
    """Return the default seeded reasoning level for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ReasoningLevel: The seeded canonical level.
    """
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name)
    if not capability.reasoning_supported:
        return "off"
    if "high" in capability.supported_levels:
        return "high"
    return clamp_reasoning_level(
        model_name=model_name,
        requested_level=capability.default_level,
    )


def highest_supported_reasoning_level(*, model_name: str) -> ReasoningLevel:
    """Return the strongest supported reasoning level for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ReasoningLevel: Highest supported level, or ``"off"`` when the
            model does not support reasoning.
    """
    supported_levels: list[ReasoningLevel] = supported_reasoning_levels_for_model(
        model_name=model_name,
    )
    for reasoning_level in reversed(REASONING_LEVELS):
        if reasoning_level in supported_levels:
            return reasoning_level
    return "off"


def parse_reasoning_level(*, token: str) -> ReasoningLevel:
    """Parse one slash-command token into a canonical reasoning level.

    Args:
        token (str): User-supplied slash-command token.

    Returns:
        ReasoningLevel: Canonical reasoning level.

    Raises:
        ValueError: If ``token`` is not one of Slo's canonical levels.
    """
    normalized_token: str = token.strip().lower()
    if normalized_token in REASONING_LEVELS:
        return normalized_token  # type: ignore[return-value]
    expected: str = ", ".join(REASONING_LEVELS)
    raise ValueError(f"unknown reasoning level: {token}. expected one of: {expected}")


def clamp_reasoning_level(
    *,
    model_name: str,
    requested_level: ReasoningLevel,
) -> ReasoningLevel:
    """Clamp one requested level to the model's supported range.

    Clamping order mirrors pi:

    1. exact match,
    2. nearest stronger supported level,
    3. otherwise nearest weaker supported level,
    4. otherwise ``off``.

    Args:
        model_name (str): Supported interactive model name.
        requested_level (ReasoningLevel): Requested canonical level.

    Returns:
        ReasoningLevel: Final clamped level.
    """
    supported_levels: list[ReasoningLevel] = supported_reasoning_levels_for_model(
        model_name=model_name,
    )
    if requested_level in supported_levels:
        return requested_level

    requested_index: int = REASONING_LEVELS.index(requested_level)
    for index in range(requested_index, len(REASONING_LEVELS)):
        candidate: ReasoningLevel = REASONING_LEVELS[index]
        if candidate in supported_levels:
            return candidate
    for index in range(requested_index - 1, -1, -1):
        candidate = REASONING_LEVELS[index]
        if candidate in supported_levels:
            return candidate
    return "off"


def resolve_reasoning_config(
    *,
    model_name: str,
    requested_level: ReasoningLevel,
) -> ResolvedReasoningConfigDAO:
    """Resolve one provider-ready reasoning configuration.

    Args:
        model_name (str): Supported interactive model name.
        requested_level (ReasoningLevel): Requested canonical level.

    Returns:
        ResolvedReasoningConfigDAO: Final clamped provider-ready config.

    Raises:
        ValueError: If the capability record is inconsistent with the
            requested model.
    """
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name)
    active_level: ReasoningLevel = clamp_reasoning_level(
        model_name=model_name,
        requested_level=requested_level,
    )
    if not capability.reasoning_supported or active_level == "off":
        return ResolvedReasoningConfigDAO(
            enabled=False,
            requested_level=requested_level,
            active_level="off",
        )

    provider_effort: Optional[str] = capability.provider_effort_map.get(active_level)
    provider_budget_tokens: Optional[int] = capability.provider_budget_map.get(active_level)
    if provider_effort is None and provider_budget_tokens is None:
        raise ValueError(
            f"Model '{model_name}' is marked reasoning-capable but has no provider translation for '{active_level}'."
        )
    return ResolvedReasoningConfigDAO(
        enabled=True,
        requested_level=requested_level,
        active_level=active_level,
        provider_effort=provider_effort,
        provider_budget_tokens=provider_budget_tokens,
        provider_summary_mode=capability.provider_summary_mode,
    )
