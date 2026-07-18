"""Canonical Pydantic DAOs for the unified model catalog."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.auth.credential_dao import ProviderName

ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
"""Slo's canonical provider-neutral reasoning vocabulary."""


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
            Slo exposes for the model.
        default_level (ReasoningLevel): Default seeded level when not explicitly
            overridden.
        provider_effort_map (dict[ReasoningLevel, str]): Provider-native effort
            mapping per canonical level.
        provider_budget_map (dict[ReasoningLevel, int]): Provider-native budget
            mapping per canonical level.
    """

    model_config = ConfigDict(extra="forbid")

    supported_levels: list[ReasoningLevel]
    default_level: ReasoningLevel
    provider_effort_map: dict[ReasoningLevel, str] = Field(default_factory=dict)
    provider_budget_map: dict[ReasoningLevel, int] = Field(default_factory=dict)


class ModelCatalogEntryDAO(BaseModel):
    """One canonical model-support record.

    Attributes:
        model_name (str): Canonical model identifier sent to the provider.
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
