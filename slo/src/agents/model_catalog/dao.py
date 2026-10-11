"""Canonical Pydantic DAOs for the unified model catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Literal, Optional, Self

from pydantic import AfterValidator, PlainSerializer

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.auth.credential_dao import AuthType, ProviderName

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


class FrozenCatalogDAO(BaseModel):
    """Immutable catalog value whose copy updates are validated, not trusted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(self, *, update: Optional[Mapping[str, object]] = None, deep: bool = False) -> Self:
        """Build a validated immutable replacement, retaining JSON compatibility.

        Args:
            update: Fields to replace on the detached value.
            deep: Compatibility flag; reconstruction always detaches containers.

        Returns:
            Self: Validated replacement with immutable nested containers.
        """
        data = self.model_dump()
        data.update(update or {})
        return type(self).model_validate(data)


class ModelRuntimeProfileDAO(FrozenCatalogDAO):
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
    tokens_per_minute: Optional[int]
    automatic_retry_attempts: int
    local_retry_wait_cap_seconds: int


class ModelReasoningProfileDAO(FrozenCatalogDAO):
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

    supported_levels: tuple[ReasoningLevel, ...]
    default_level: ReasoningLevel
    provider_effort_map: Annotated[
        Mapping[ReasoningLevel, str],
        AfterValidator(lambda value: MappingProxyType(dict(value))),
        PlainSerializer(lambda value: dict(value)),
    ] = Field(default_factory=lambda: MappingProxyType({}))
    provider_budget_map: Annotated[
        Mapping[ReasoningLevel, int],
        AfterValidator(lambda value: MappingProxyType(dict(value))),
        PlainSerializer(lambda value: dict(value)),
    ] = Field(default_factory=lambda: MappingProxyType({}))
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
            raise ValueError(f"default_level '{self.default_level}' must be one of supported_levels.")

    def _validate_translation_key_membership(self) -> None:
        """Reject provider translation keys outside the supported levels."""
        for key in self.provider_effort_map:
            if key not in self.supported_levels:
                raise ValueError(f"provider_effort_map key '{key}' must be one of supported_levels.")
        for key in self.provider_budget_map:
            if key not in self.supported_levels:
                raise ValueError(f"provider_budget_map key '{key}' must be one of supported_levels.")

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
            raise ValueError("provider_reasoning_required=True requires 'off' in supported_levels.")
        if "off" not in self.provider_effort_map:
            raise ValueError("provider_reasoning_required=True requires an 'off' provider_effort_map entry.")


class ModelCapabilitiesDAO(FrozenCatalogDAO):
    """Reported provider capabilities attached to one canonical catalog entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_modalities: tuple[str, ...] = Field(
        default_factory=tuple, description="Advertised input modalities."
    )
    output_modalities: tuple[str, ...] = Field(
        default_factory=tuple, description="Advertised output modalities."
    )
    supported_parameters: tuple[str, ...] = Field(
        default_factory=tuple, description="Advertised request parameters."
    )
    reported_output_ceiling: Optional[int] = Field(
        default=None, description="Reported provider output ceiling."
    )
    supports_max_tokens: Optional[bool] = Field(
        default=None,
        strict=True,
        description="Reported reasoning-budget support; evidence only, not a control.",
    )
    expires_at: Optional[str] = Field(default=None, description="UTC expiry evidence, when supplied.")
    reasoning_disable_available: bool = Field(
        default=False, description="Whether explicit non-mandatory metadata permits disabling reasoning."
    )
    reasoning_controls_available: bool = Field(
        default=False, description="Whether configurable reasoning controls are truthfully known."
    )


class ModelBackendEligibilityError(ValueError):
    """Report a static model/backend mismatch without credential material."""


class ModelCatalogEntryDAO(FrozenCatalogDAO):
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
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    api_model_name: Optional[str] = None
    availability: str = "available"
    capabilities: Optional[ModelCapabilitiesDAO] = None
    supports_chatgpt_codex: bool = Field(
        default=True, strict=True, description="Static permission to use the ChatGPT/Codex backend."
    )
    requires_responses_api: bool = Field(
        default=False,
        strict=True,
        description="Requires Responses transport; credential type independently selects Platform or Codex.",
    )

    def require_reasoning_override_compatibility(
        self, *, reasoning_profile: ModelReasoningProfileDAO
    ) -> None:
        """Preserve transport controls before the override service assigns a profile.

        Args:
            reasoning_profile: Candidate profile; default-level changes are allowed.

        Raises:
            ValueError: A required Responses record's fixed controls would change.
        """
        if not self.requires_responses_api:
            return
        expected = self.reasoning_profile.model_dump(exclude={"default_level"})
        proposed = reasoning_profile.model_dump(exclude={"default_level"})
        if expected != proposed:
            raise ValueError("Model catalog overrides cannot change required Responses reasoning controls.")

    def backend_eligibility_message(self, *, auth_type: Optional[AuthType] = None) -> Optional[str]:
        """Describe static compatibility for selection, factory and picker callers.

        Args:
            auth_type: Effective local auth type, or None when unauthenticated.

        Returns:
            Fixed safe guidance, or None when the lane is not rejected.
        """
        rejected: bool = (
            self.provider is ProviderName.OPENAI
            and auth_type is AuthType.OAUTH
            and not self.supports_chatgpt_codex
        )
        if not rejected:
            return None
        return "This model requires an OpenAI Platform API key; unavailable for ChatGPT/Codex. Run /auth."

    def require_backend_eligibility(self, *, auth_type: Optional[AuthType] = None) -> None:
        """Reject an incompatible lane before selection mutation or client build.

        Args:
            auth_type: Type from the caller's effective credential.

        Raises:
            ModelBackendEligibilityError: OpenAI OAuth is statically disallowed.
        """
        message: Optional[str] = self.backend_eligibility_message(auth_type=auth_type)
        if message is not None:
            raise ModelBackendEligibilityError(message)


class ModelAliasDAO(FrozenCatalogDAO):
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


class ProviderModelTemplateDAO(FrozenCatalogDAO):
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

    family_patterns: tuple[str, ...]
    provider: ProviderName
    display_name_template: Optional[str] = None
    runtime_profile: ModelRuntimeProfileDAO
    reasoning_profile: ModelReasoningProfileDAO
    default_visible: bool = False


class ModelCatalogSnapshotDAO(FrozenCatalogDAO):
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
    entries: Annotated[
        Mapping[str, ModelCatalogEntryDAO],
        AfterValidator(lambda value: MappingProxyType(dict(value))),
        PlainSerializer(lambda value: dict(value)),
    ]
    aliases: Annotated[
        Mapping[str, ModelAliasDAO],
        AfterValidator(lambda value: MappingProxyType(dict(value))),
        PlainSerializer(lambda value: dict(value)),
    ]
    templates: tuple[ProviderModelTemplateDAO, ...]
    generation: int = Field(default=0, ge=0, description="Immutable in-process catalog generation.")


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

    provider: ProviderName = Field(description="Provider whose authenticated discovery produced this result.")
    available_model_names: list[str] = Field(
        description="Legacy direct-provider names retained for compatibility."
    )
    metadata: dict[str, ProviderModelMetadataDAO] = Field(
        default_factory=dict,
        description="Legacy safe metadata keyed by canonical model name.",
    )
    entries: list[ModelCatalogEntryDAO] = Field(
        default_factory=list,
        description="Converted canonical entries from the complete provider response.",
    )
    complete: bool = Field(
        default=True, description="Whether the provider list passed completeness validation."
    )
    exclusion_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of conservatively excluded records grouped by safe reason.",
    )


class ProviderCatalogTombstoneDAO(BaseModel):
    """Bounded evidence that a previously listed provider route is unavailable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = Field(description="Canonical route that is no longer selectable.")
    api_model_name: str = Field(description="Exact remote identifier retained for readable history.")
    reason: Literal["removed", "expired", "ineligible"] = Field(
        description="Safe unavailable classification from complete provider reconciliation."
    )
    last_seen_at: str = Field(description="UTC timestamp when the route was last present or evaluated.")


class ProviderCatalogCacheDAO(BaseModel):
    """One private raw provider slice persisted independently from overrides."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = Field(description="Provider that owns this raw discovered slice.")
    credential_fingerprint: Optional[str] = Field(
        default=None,
        repr=False,
        description="Private effective-credential provenance for OpenRouter membership.",
    )
    key_verified_at: Optional[str] = Field(default=None, description="UTC successful key-verification time.")
    last_success_at: Optional[str] = Field(default=None, description="UTC completed-list publication time.")
    entries: list[ModelCatalogEntryDAO] = Field(
        default_factory=list,
        description="Raw converted provider entries before operator overrides.",
    )
    tombstones: list[ProviderCatalogTombstoneDAO] = Field(
        default_factory=list,
        description="Bounded unavailable-route evidence retained across successful refreshes.",
    )


class ModelCatalogCacheDAO(BaseModel):
    """Schema-two raw provider-slice cache envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"] = Field(
        default="2", description="On-disk raw provider-slice schema version."
    )
    provider_slices: list[ProviderCatalogCacheDAO] = Field(
        default_factory=list,
        description="Independent raw discovery slices merged into the in-memory catalog.",
    )


class CatalogLifecycleStatusDAO(BaseModel):
    """Secret-free process-local facts; timestamps never come from snapshot generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int = Field(default=0, ge=0, description="Monotonic process-local lifecycle-status revision.")
    state: Literal[
        "unknown",
        "historical",
        "stale",
        "requires_auth",
        "verified",
        "checked",
        "failed",
        "credential_changed",
    ] = Field(default="unknown", description="Safe lifecycle state for catalog status presentation.")
    key_verified_at: Optional[datetime] = Field(
        default=None, description="Latest successful effective-key verification time."
    )
    catalog_checked_at: Optional[datetime] = Field(
        default=None, description="Latest complete catalog-list check time."
    )


class CatalogRefreshResultDAO(BaseModel):
    """Safe result of one catalog refresh operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["refreshed", "fresh", "failed", "credential_changed"] = Field(
        description="Safe terminal outcome of the coalesced refresh operation."
    )
    catalog_generation: int = Field(ge=0, description="Published in-process generation after this outcome.")
    safe_message: str = Field(description="Fixed non-secret operator-facing refresh result.")


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
