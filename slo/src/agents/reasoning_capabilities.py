"""Reasoning capability catalog and clamping helpers for Slo.

This module is now a compatibility projection over the canonical model catalog
in ``src.agents.model_catalog``. It preserves the historical public helpers
(``capability_for_model``, ``clamp_reasoning_level``, ``resolve_reasoning_config``,
``MODEL_REASONING_CAPABILITIES``) while sourcing truth from the catalog.
"""

from __future__ import annotations

from typing import Optional
from collections.abc import Iterator, Mapping
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO

from pydantic import BaseModel, ConfigDict, Field

from src.agents.model_catalog.dao import CANONICAL_REASONING_LEVEL_ORDER, ReasoningLevel
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


REASONING_LEVELS: tuple[ReasoningLevel, ...] = CANONICAL_REASONING_LEVEL_ORDER
"""Ordered canonical reasoning levels used for clamping.

Derived from the catalog-owned ``CANONICAL_REASONING_LEVEL_ORDER``; this module
never re-declares the order.
"""


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
        provider_reasoning_required (bool): When ``True``, a selected canonical
            ``off`` still resolves to enabled provider reasoning with the mapped
            ``off`` effort while ``active_level`` stays ``"off"``.
        forbid_sampling_parameters_when_enabled (bool): When ``True``, enabled
            reasoning forbids provider sampling inputs at request construction
            (consumed by the LLM factory request policy).
    """

    model_config = ConfigDict(extra="forbid")

    reasoning_supported: bool
    supported_levels: list[ReasoningLevel]
    default_level: ReasoningLevel = "high"
    provider_effort_map: dict[ReasoningLevel, str] = Field(default_factory=dict)
    provider_budget_map: dict[ReasoningLevel, int] = Field(default_factory=dict)
    provider_summary_mode: Optional[str] = None
    provider_reasoning_required: bool = False
    forbid_sampling_parameters_when_enabled: bool = False
    reasoning_controls_available: bool = False
    reasoning_disable_available: bool = False


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


class ReasoningCapabilitiesView(Mapping[str, ModelReasoningCapabilityDAO]):
    """Read-only live capabilities with detached nested values."""

    def __getitem__(self, model_name: str) -> ModelReasoningCapabilityDAO:
        """Project a fresh capability from the current catalog."""
        try:
            return _catalog_entry_to_capability(model_name=model_name)
        except ValueError as error:
            raise KeyError(model_name) from error

    def __iter__(self) -> Iterator[str]:
        """Iterate canonical keys from one generation."""
        return iter(ModelCatalogService.load().entries)

    def __len__(self) -> int:
        """Return the current canonical count."""
        return len(ModelCatalogService.load().entries)


MODEL_REASONING_CAPABILITIES: Mapping[str, ModelReasoningCapabilityDAO] = ReasoningCapabilitiesView()


def _provider_summary_mode_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> Optional[str]:
    """Derive the provider-native summary mode for a model.

    OpenAI reasoning models use ``responses`` API with ``auto`` summary mode.
    Anthropic adaptive thinking and Kimi do not expose this mode.

    Args:
        model_name (str): Canonical model name.

    Returns:
        Optional[str]: Provider summary mode, or ``None`` when not applicable.
    """
    provider = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot).provider
    if provider is ProviderName.OPENAI:
        return "auto"
    return None


def _catalog_entry_to_capability(
    *,
    model_name: str,
    snapshot: Optional[ModelCatalogSnapshotDAO] = None,
) -> ModelReasoningCapabilityDAO:
    """Project one catalog entry into the legacy capability shape.

    Args:
        model_name (str): Canonical model name or known alias.

    Returns:
        ModelReasoningCapabilityDAO: Legacy capability record.
    """
    snapshot = snapshot if snapshot is not None else ModelCatalogService.load()
    entry = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
    profile = entry.reasoning_profile
    capabilities = entry.capabilities
    reasoning_controls_available: bool = capabilities.reasoning_controls_available if capabilities else False
    reasoning_disable_available: bool = capabilities.reasoning_disable_available if capabilities else False
    reasoning_supported = profile.supported_levels != ("off",) or reasoning_disable_available
    return ModelReasoningCapabilityDAO(
        reasoning_supported=reasoning_supported,
        supported_levels=list(profile.supported_levels),
        default_level=profile.default_level,
        provider_effort_map=dict(profile.provider_effort_map),
        provider_budget_map=dict(profile.provider_budget_map),
        provider_summary_mode=_provider_summary_mode_for_model(
            model_name=entry.model_name, snapshot=snapshot
        ),
        provider_reasoning_required=profile.provider_reasoning_required,
        forbid_sampling_parameters_when_enabled=profile.forbid_sampling_parameters_when_enabled,
        reasoning_controls_available=reasoning_controls_available,
        reasoning_disable_available=reasoning_disable_available,
    )


def rebuild_reasoning_capabilities_projection() -> None:
    """Deprecated no-op: capabilities follow catalog publication automatically."""


def capability_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> ModelReasoningCapabilityDAO:
    """Return the reasoning capability record for one supported model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ModelReasoningCapabilityDAO: Capability metadata for the model.

    Raises:
        ValueError: If ``model_name`` is outside Slo's supported
            interactive catalog.
    """
    try:
        return _catalog_entry_to_capability(model_name=model_name, snapshot=snapshot)
    except ValueError as error:
        raise ValueError(f"Unsupported reasoning model '{model_name}'.") from error


def supported_reasoning_levels_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> list[ReasoningLevel]:
    """Return the ordered supported reasoning levels for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        list[ReasoningLevel]: Ordered supported levels.
    """
    snapshot = snapshot if snapshot is not None else ModelCatalogService.load()
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name, snapshot=snapshot)
    return list(capability.supported_levels)


def default_reasoning_level_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> ReasoningLevel:
    """Return the default seeded reasoning level for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ReasoningLevel: The seeded canonical level.
    """
    snapshot = snapshot if snapshot is not None else ModelCatalogService.load()
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name, snapshot=snapshot)
    if not capability.reasoning_supported:
        return "off"
    return clamp_reasoning_level(
        model_name=model_name,
        snapshot=snapshot,
        requested_level=capability.default_level,
    )


def highest_supported_reasoning_level(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> ReasoningLevel:
    """Return the strongest supported reasoning level for one model.

    Args:
        model_name (str): Supported interactive model name.

    Returns:
        ReasoningLevel: Highest supported level, or ``"off"`` when the
            model does not support reasoning.
    """
    supported_levels: list[ReasoningLevel] = supported_reasoning_levels_for_model(
        model_name=model_name,
        snapshot=snapshot,
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
    snapshot: Optional[ModelCatalogSnapshotDAO] = None,
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
        snapshot=snapshot,
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
    snapshot: Optional[ModelCatalogSnapshotDAO] = None,
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
    snapshot = snapshot if snapshot is not None else ModelCatalogService.load()
    capability: ModelReasoningCapabilityDAO = capability_for_model(model_name=model_name, snapshot=snapshot)
    active_level: ReasoningLevel = clamp_reasoning_level(
        model_name=model_name,
        snapshot=snapshot,
        requested_level=requested_level,
    )
    if not capability.reasoning_supported:
        return ResolvedReasoningConfigDAO(
            enabled=False,
            requested_level=requested_level,
            active_level="off",
        )

    provider_reasoning_enabled: bool = active_level != "off" or capability.provider_reasoning_required
    if not provider_reasoning_enabled:
        return ResolvedReasoningConfigDAO(
            enabled=False,
            requested_level=requested_level,
            active_level="off",
        )

    return _resolved_provider_reasoning_config(
        capability=capability,
        model_name=model_name,
        requested_level=requested_level,
        active_level=active_level,
    )


def _resolved_provider_reasoning_config(
    *,
    capability: ModelReasoningCapabilityDAO,
    model_name: str,
    requested_level: ReasoningLevel,
    active_level: ReasoningLevel,
) -> ResolvedReasoningConfigDAO:
    """Translate one enabled canonical level into its provider-ready config.

    A profile that requires provider reasoning may reach this helper with
    ``active_level="off"``; the canonical state is preserved while the mapped
    provider effort is returned.

    Args:
        capability (ModelReasoningCapabilityDAO): Capability record for the model.
        model_name (str): Supported interactive model name (error reporting only).
        requested_level (ReasoningLevel): Requested canonical level.
        active_level (ReasoningLevel): Final clamped canonical level.

    Returns:
        ResolvedReasoningConfigDAO: Enabled provider-ready reasoning config.

    Raises:
        ValueError: If the capability record has no provider translation for
            the enabled level.
    """
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
