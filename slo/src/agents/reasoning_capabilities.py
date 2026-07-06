"""Reasoning capability catalog and clamping helpers for Slo.

This module owns Slo's provider-neutral reasoning vocabulary plus the
supported interactive model capability table. The session, TUI, and LLM
factory all consume these helpers so default seeding, clamping, and
provider translation stay deterministic.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

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


ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
"""Slo's canonical provider-neutral reasoning vocabulary."""


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


def _anthropic_capability(*, supports_xhigh: bool) -> ModelReasoningCapabilityDAO:
    """Build the Anthropic capability record for one supported model.

    Args:
        supports_xhigh (bool): True when the model supports Slo's
            highest reasoning tier.

    Returns:
        ModelReasoningCapabilityDAO: Anthropic capability metadata.
    """
    supported_levels: list[ReasoningLevel] = [
        "off",
        "minimal",
        "low",
        "medium",
        "high",
    ]
    # Anthropic adaptive thinking uses output_config.effort ("low"/"medium"/"high").
    # Minimal and low both map to "low"; xhigh has no Anthropic tier above "high".
    provider_effort_map: dict[ReasoningLevel, str] = {
        "minimal": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    if supports_xhigh:
        supported_levels.append("xhigh")
        provider_effort_map["xhigh"] = "high"
    return ModelReasoningCapabilityDAO(
        reasoning_supported=True,
        supported_levels=supported_levels,
        default_level="high",
        provider_effort_map=provider_effort_map,
    )


def _openai_capability(
    *,
    supports_xhigh: bool,
    minimal_maps_to_low: bool,
) -> ModelReasoningCapabilityDAO:
    """Build the OpenAI capability record for one supported model.

    Args:
        supports_xhigh (bool): True when the model supports Slo's
            highest reasoning tier.
        minimal_maps_to_low (bool): True when provider-native minimal
            requests must be translated to ``low``.

    Returns:
        ModelReasoningCapabilityDAO: OpenAI capability metadata.
    """
    supported_levels: list[ReasoningLevel] = [
        "off",
        "minimal",
        "low",
        "medium",
        "high",
    ]
    provider_effort_map: dict[ReasoningLevel, str] = {
        "minimal": "low" if minimal_maps_to_low else "minimal",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    if supports_xhigh:
        supported_levels.append("xhigh")
        provider_effort_map["xhigh"] = "xhigh"
    return ModelReasoningCapabilityDAO(
        reasoning_supported=True,
        supported_levels=supported_levels,
        default_level="high",
        provider_effort_map=provider_effort_map,
        provider_summary_mode="auto",
    )


def _non_reasoning_capability() -> ModelReasoningCapabilityDAO:
    """Build the capability record for a non-reasoning model.

    Returns:
        ModelReasoningCapabilityDAO: Off-only capability metadata.
    """
    return ModelReasoningCapabilityDAO(
        reasoning_supported=False,
        supported_levels=["off"],
        default_level="off",
    )


MODEL_REASONING_CAPABILITIES: dict[str, ModelReasoningCapabilityDAO] = {
    "claude-opus-4-7": _anthropic_capability(supports_xhigh=True),
    "claude-sonnet-4-6": _anthropic_capability(supports_xhigh=False),
    "gpt-5.4": _openai_capability(
        supports_xhigh=True,
        minimal_maps_to_low=True,
    ),
    "gpt-5-codex": _openai_capability(
        supports_xhigh=True,
        minimal_maps_to_low=True,
    ),
    "gpt-5.3-codex": _openai_capability(
        supports_xhigh=True,
        minimal_maps_to_low=True,
    ),
    "gpt-5.3-codex-spark": _openai_capability(
        supports_xhigh=True,
        minimal_maps_to_low=True,
    ),
    "gpt-5.2-codex": _openai_capability(
        supports_xhigh=False,
        minimal_maps_to_low=True,
    ),
    "gpt-5": _openai_capability(
        supports_xhigh=False,
        minimal_maps_to_low=False,
    ),
    "gpt-4.1": _non_reasoning_capability(),
    "gpt-4o": _non_reasoning_capability(),
    "o3": _openai_capability(
        supports_xhigh=False,
        minimal_maps_to_low=False,
    ),
    "o1": _openai_capability(
        supports_xhigh=False,
        minimal_maps_to_low=False,
    ),
    # Kimi For Coding (KFC) always reasons internally
    # (supports_thinking_type="only"); Slo treats it as non-reasoning since
    # the reasoning level cannot be controlled via the API.
    "kimi-for-coding": _non_reasoning_capability(),
}
"""Versioned capability table for Slo's supported interactive models."""


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
