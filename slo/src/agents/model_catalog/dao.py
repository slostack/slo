"""Canonical Pydantic DAOs for the unified model catalog."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.auth.credential_dao import ProviderName

ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
"""Slo's canonical provider-neutral reasoning vocabulary."""

CANONICAL_REASONING_LEVEL_ORDER: tuple[ReasoningLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
"""The single owner of the canonical reasoning-level ordering.

``reasoning_capabilities.REASONING_LEVELS`` derives from this tuple; no other
module re-declares the order.
"""


class ModelRuntimeProfileDAO(BaseModel):
    """Runtime defaults for one model.

    Attributes:
        max_tokens (int): Total output ceiling sent to the provider.
        context_window (int): Total input context window used by compaction.
        streaming (bool): Whether streaming is enabled by default.
        requests_per_minute (int): Local RPM ceiling used by rate-limit policy.
        tokens_per_minute (int): Local TPM ceiling used by rate-limit policy.
        automatic_retry_attempts (int): Session-level retry budget.
        local_retry_wait_cap_seconds (int): Maximum local backoff wait.
    """

    model_config = ConfigDict(extra="forbid")

    max_tokens: int
    context_window: int
    streaming: bool
    requests_per_minute: int
    tokens_per_minute: int
    automatic_retry_attempts: int
    local_retry_wait_cap_seconds: int


class ModelReasoningProfileDAO(BaseModel):
    """Normalized reasoning support for one model.

    Attributes:
        supported_levels (list[ReasoningLevel]): Canonical reasoning levels
            Slo exposes for the model. Must be unique and follow
            ``CANONICAL_REASONING_LEVEL_ORDER``.
        default_level (ReasoningLevel): Default seeded level when not explicitly
            overridden. Must be one of ``supported_levels``.
        provider_effort_map (dict[ReasoningLevel, str]): Provider-native effort
            mapping per canonical level. Keys must be supported levels.
        provider_budget_map (dict[ReasoningLevel, int]): Provider-native budget
            mapping per canonical level. Keys must be supported levels.
        provider_reasoning_required (bool): When ``True``, a selected canonical
            ``off`` still resolves to enabled provider reasoning; the profile
            must then support ``off`` and map it to a provider effort.
        forbid_sampling_parameters_when_enabled (bool): When ``True``, enabled
            reasoning forbids provider sampling inputs (``temperature``,
            ``top_p``, ``top_logprobs``, ``logprobs``) at request construction.
    """

    model_config = ConfigDict(extra="forbid")

    supported_levels: list[ReasoningLevel]
    default_level: ReasoningLevel
    provider_effort_map: dict[ReasoningLevel, str] = Field(default_factory=dict)
    provider_budget_map: dict[ReasoningLevel, int] = Field(default_factory=dict)
    provider_reasoning_required: bool = False
    forbid_sampling_parameters_when_enabled: bool = False

    @model_validator(mode="after")
    def _validate_reasoning_profile_consistency(self) -> "ModelReasoningProfileDAO":
        """Enforce generic profile invariants against the canonical vocabulary.

        Returns:
            ModelReasoningProfileDAO: Self after validation.

        Raises:
            ValueError: When levels are duplicated, out of canonical order,
                the default is unsupported, a translation key is unsupported,
                an enabled level lacks exactly one translation, or
                ``provider_reasoning_required`` lacks an ``off`` effort entry.
        """
        self._validate_supported_levels_shape()
        self._validate_default_level_membership()
        self._validate_translation_key_membership()
        self._validate_enabled_level_translations()
        self._validate_provider_reasoning_required_off_entry()
        return self

    def _validate_supported_levels_shape(self) -> None:
        """Reject duplicate or non-canonically-ordered supported levels."""
        if len(set(self.supported_levels)) != len(self.supported_levels):
            raise ValueError("supported_levels must not contain duplicate reasoning levels.")
        ordered_index: dict[ReasoningLevel, int] = {
            level: index for index, level in enumerate(CANONICAL_REASONING_LEVEL_ORDER)
        }
        indexes: list[int] = [ordered_index[level] for level in self.supported_levels]
        if indexes != sorted(indexes):
            raise ValueError("supported_levels must follow the canonical order of reasoning levels.")

    def _validate_default_level_membership(self) -> None:
        """Reject a default level outside the supported levels."""
        if self.default_level not in self.supported_levels:
            raise ValueError(
                f"default_level '{self.default_level}' must be one of supported_levels."
            )

    def _validate_translation_key_membership(self) -> None:
        """Reject provider translation keys outside the supported levels."""
        for key in self.provider_effort_map:
            if key not in self.supported_levels:
                raise ValueError(
                    f"provider_effort_map key '{key}' must be one of supported_levels."
                )
        for key in self.provider_budget_map:
            if key not in self.supported_levels:
                raise ValueError(
                    f"provider_budget_map key '{key}' must be one of supported_levels."
                )

    def _validate_enabled_level_translations(self) -> None:
        """Require exactly one translation for each reasoning-enabled level."""
        for level in self.supported_levels:
            if level == "off":
                continue
            has_effort: bool = level in self.provider_effort_map
            has_budget: bool = level in self.provider_budget_map
            if has_effort and has_budget:
                raise ValueError(
                    f"Level '{level}' must carry exactly one translation: "
                    "provider effort XOR provider budget."
                )
            if not has_effort and not has_budget:
                raise ValueError(
                    f"Reasoning-enabled level '{level}' is missing a provider translation "
                    "(effort or budget)."
                )

    def _validate_provider_reasoning_required_off_entry(self) -> None:
        """Require an ``off`` effort mapping when provider reasoning is required."""
        if not self.provider_reasoning_required:
            return
        if "off" not in self.supported_levels:
            raise ValueError(
                "provider_reasoning_required=True requires 'off' in supported_levels."
            )
        if "off" not in self.provider_effort_map:
            raise ValueError(
                "provider_reasoning_required=True requires an 'off' provider_effort_map entry."
            )


class ModelCatalogEntryDAO(BaseModel):
    """One canonical model-support record.

    Attributes:
        model_name (str): Canonical model identifier used by Slo for catalog
            lookup, ``MODEL_DEFAULTS``, reasoning resolution, session state,
            and logs. It can differ from the provider API model ID.
        display_name (str): Human-facing name shown in the TUI and docs.
        provider (ProviderName): Provider that owns the model.
        support_tier (str): One of ``first_class``, ``auto_discovered``, or
            ``compatibility_only``.
        visible_in_picker (bool): Whether the model is shown in interactive
            model lists.
        runtime_profile (ModelRuntimeProfileDAO): Runtime defaults for the model.
        reasoning_profile (ModelReasoningProfileDAO): Reasoning support and
            translation metadata.
        aliases (list[str]): Alternate names accepted for backward compatibility.
        api_model_name (Optional[str]): API model ID sent to the provider.
            ``None`` means the canonical ``model_name`` is sent verbatim.
    """

    model_config = ConfigDict(extra="forbid")

    model_name: str
    display_name: str
    provider: ProviderName
    support_tier: str
    visible_in_picker: bool
    runtime_profile: ModelRuntimeProfileDAO
    reasoning_profile: ModelReasoningProfileDAO
    aliases: list[str] = Field(default_factory=list)
    api_model_name: Optional[str] = None


class ModelAliasDAO(BaseModel):
    """One backward-compatible alias mapping.

    Attributes:
        alias (str): Alternate name accepted from preferences, pools, or CLI.
        canonical_model_name (str): Name of the catalog entry it resolves to.
        support_tier (str): One of ``first_class``, ``auto_discovered``, or
            ``compatibility_only``. Legacy aliases are normally
            ``compatibility_only``.
    """

    model_config = ConfigDict(extra="forbid")

    alias: str
    canonical_model_name: str
    support_tier: str


class ProviderModelTemplateDAO(BaseModel):
    """Family-level fallback policy for future or discovered models.

    A template matches a discovered model name by exact prefix or regex family
    and supplies conservative defaults. It lets Slo auto-add models without
    pretending to know undocumented capabilities.

    Attributes:
        family_patterns (list[str]): Prefixes or regex patterns that identify
            the family. Regex entries must start with ``^``.
        provider (ProviderName): Provider that owns matched models.
        display_name_template (Optional[str]): Optional template for deriving a
            display name; ``{model_name}`` is substituted.
        runtime_profile (ModelRuntimeProfileDAO): Conservative runtime defaults.
        reasoning_profile (ModelReasoningProfileDAO): Conservative reasoning
            defaults for the family.
        default_visible (bool): Whether auto-discovered matches are visible in
            the picker by default.
    """

    model_config = ConfigDict(extra="forbid")

    family_patterns: list[str]
    provider: ProviderName
    display_name_template: Optional[str] = None
    runtime_profile: ModelRuntimeProfileDAO
    reasoning_profile: ModelReasoningProfileDAO
    default_visible: bool = False


class ModelCatalogSnapshotDAO(BaseModel):
    """One merged catalog snapshot.

    Attributes:
        schema_version (str): Snapshot schema version; bumped when the on-disk
            format changes. Readers must reject or migrate unknown versions.
        generated_at (str): UTC ISO 8601 timestamp when the snapshot was produced.
        entries (dict[str, ModelCatalogEntryDAO]): Catalog entries keyed by
            canonical model name.
        aliases (dict[str, ModelAliasDAO]): Alias map keyed by alias name.
        templates (list[ProviderModelTemplateDAO]): Family templates used for
            discovery merge.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    generated_at: str
    entries: dict[str, ModelCatalogEntryDAO]
    aliases: dict[str, ModelAliasDAO]
    templates: list[ProviderModelTemplateDAO]


class ProviderModelMetadataDAO(BaseModel):
    """Safe metadata a provider discovery adapter reports for one model name.

    Only fields Slo can use without inference are included. Absent or unknown
    values are represented by ``None`` so the merge layer falls back to family
    templates rather than guessing.

    Attributes:
        max_tokens (Optional[int]): Provider-reported output ceiling, if any.
        context_window (Optional[int]): Provider-reported input context window,
            if any.
    """

    model_config = ConfigDict(extra="forbid")

    max_tokens: Optional[int] = None
    context_window: Optional[int] = None


class ProviderDiscoveryResultDAO(BaseModel):
    """Conservative report from one provider discovery adapter.

    Attributes:
        provider (ProviderName): Provider that was queried.
        available_model_names (list[str]): Names the provider currently lists.
        metadata (dict[str, ProviderModelMetadataDAO]): Optional safe metadata
            keyed by model name.
    """

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    available_model_names: list[str]
    metadata: dict[str, ProviderModelMetadataDAO] = Field(default_factory=dict)


class ModelCatalogOverrideDAO(BaseModel):
    """One operator-supplied patch over the merged catalog.

    Exactly one of ``model_name`` or ``alias`` must be set. Unknown targets are
    ignored during merge.

    Attributes:
        model_name (Optional[str]): Canonical model name to patch.
        alias (Optional[str]): Alias name to patch.
        display_name (Optional[str]): Optional display-name override.
        visible_in_picker (Optional[bool]): Optional visibility override.
        support_tier (Optional[str]): Optional support-tier override.
        runtime_profile (Optional[ModelRuntimeProfileDAO]): Optional runtime
            profile override.
        reasoning_profile (Optional[ModelReasoningProfileDAO]): Optional reasoning
            profile override.
    """

    model_config = ConfigDict(extra="forbid")

    model_name: Optional[str] = None
    alias: Optional[str] = None
    display_name: Optional[str] = None
    visible_in_picker: Optional[bool] = None
    support_tier: Optional[str] = None
    runtime_profile: Optional[ModelRuntimeProfileDAO] = None
    reasoning_profile: Optional[ModelReasoningProfileDAO] = None
