"""Committed seed data and family templates for the canonical model catalog."""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.model_catalog.dao import (
    ModelAliasDAO,
    ModelCatalogEntryDAO,
    ModelCatalogSnapshotDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
    ProviderModelTemplateDAO,
    ReasoningLevel,
)
from src.auth.credential_dao import ProviderName


def _openai_flagship_reasoning_profile() -> ModelReasoningProfileDAO:
    """Return the OpenAI flagship reasoning profile with xhigh support."""
    return ModelReasoningProfileDAO(
        supported_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
        default_level="high",
        provider_effort_map={
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh",
        },
    )


def _openai_flagship_runtime_profile() -> ModelRuntimeProfileDAO:
    """Return the conservative OpenAI flagship runtime profile."""
    return ModelRuntimeProfileDAO(
        max_tokens=8_192,
        context_window=1_050_000,
        streaming=True,
        requests_per_minute=30,
        tokens_per_minute=500_000,
        automatic_retry_attempts=2,
        local_retry_wait_cap_seconds=30,
    )


def _openai_astra_reasoning_profile() -> ModelReasoningProfileDAO:
    """Return the gpt-6-astra reasoning profile (feature 83).

    Astra supports every canonical level, requires provider reasoning for every
    request (a selected Slo ``off`` resolves to enabled provider effort ``low``;
    the provider rejects ``none`` with HTTP 400), and forbids sampling inputs on
    reasoning/tool requests.

    Returns:
        ModelReasoningProfileDAO: Seven-level Astra reasoning profile.
    """
    return ModelReasoningProfileDAO(
        supported_levels=["off", "minimal", "low", "medium", "high", "xhigh", "max"],
        default_level="high",
        provider_effort_map={
            "off": "low",
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh",
            "max": "max",
        },
        provider_reasoning_required=True,
        forbid_sampling_parameters_when_enabled=True,
    )


def _openai_astra_runtime_profile() -> ModelRuntimeProfileDAO:
    """Return the gpt-6-astra runtime profile.

    Rate values are Slo's conservative local Tier-1 baseline, not a discovered
    account entitlement. Documented maximum input is 922,000 tokens; it is
    evidence prose only, not a separate runtime field.

    Returns:
        ModelRuntimeProfileDAO: Evidence-backed Astra runtime profile.
    """
    return ModelRuntimeProfileDAO(
        max_tokens=128_000,
        context_window=1_050_000,
        streaming=True,
        requests_per_minute=500,
        tokens_per_minute=500_000,
        automatic_retry_attempts=2,
        local_retry_wait_cap_seconds=30,
    )


def _anthropic_adaptive_reasoning_profile(
    *,
    supports_xhigh: bool,
) -> ModelReasoningProfileDAO:
    """Return the Anthropic adaptive reasoning profile.

    Args:
        supports_xhigh (bool): Whether the model supports Slo's xhigh tier.

    Returns:
        ModelReasoningProfileDAO: Anthropic reasoning profile.
    """
    supported_levels: list[ReasoningLevel] = [
        "off",
        "minimal",
        "low",
        "medium",
        "high",
    ]
    provider_effort_map: dict[ReasoningLevel, str] = {
        "minimal": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    if supports_xhigh:
        supported_levels.append("xhigh")
        provider_effort_map["xhigh"] = "high"
    return ModelReasoningProfileDAO(
        supported_levels=supported_levels,
        default_level="high",
        provider_effort_map=provider_effort_map,
    )


def _anthropic_adaptive_runtime_profile() -> ModelRuntimeProfileDAO:
    """Return the conservative Anthropic adaptive runtime profile."""
    return ModelRuntimeProfileDAO(
        max_tokens=64_000,
        context_window=200_000,
        streaming=True,
        requests_per_minute=60,
        tokens_per_minute=200_000,
        automatic_retry_attempts=2,
        local_retry_wait_cap_seconds=30,
    )


def _kimi_family_reasoning_profile() -> ModelReasoningProfileDAO:
    """Return the off-only reasoning profile for K2 and unverified Kimi models.

    K2 coding models do not expose a user-configurable reasoning field. The
    conservative ``kimi-`` discovery template also uses this profile until a
    model has an independently verified provider contract.

    Returns:
        ModelReasoningProfileDAO: Off-only reasoning configuration.
    """
    return ModelReasoningProfileDAO(
        supported_levels=["off"],
        default_level="off",
    )


def _kimi_k3_reasoning_profile() -> ModelReasoningProfileDAO:
    """Return K3's verified provider-effort reasoning profile.

    K3 always reasons and exposes top-level ``reasoning_effort`` instead of a
    disable switch. Only the first-class ``kimi-k3`` catalog entry uses this
    profile; K2 coding models retain the off-only family profile.

    Returns:
        ModelReasoningProfileDAO: K3 canonical levels and provider-effort map.
    """
    return ModelReasoningProfileDAO(
        supported_levels=["low", "high", "xhigh"],
        default_level="xhigh",
        provider_effort_map={
            "low": "low",
            "high": "high",
            "xhigh": "max",
        },
    )


def _kimi_family_runtime_profile(
    *,
    requests_per_minute: int,
) -> ModelRuntimeProfileDAO:
    """Return the conservative Kimi family runtime profile.

    Args:
        requests_per_minute (int): Provider-family RPM ceiling.

    Returns:
        ModelRuntimeProfileDAO: Kimi runtime profile.
    """
    return ModelRuntimeProfileDAO(
        max_tokens=32_768,
        context_window=262_144,
        streaming=True,
        requests_per_minute=requests_per_minute,
        tokens_per_minute=200_000,
        automatic_retry_attempts=3,
        local_retry_wait_cap_seconds=30,
    )


class SeedModelCatalog:
    """Committed first-class catalog data and family templates."""

    @classmethod
    def load(cls) -> ModelCatalogSnapshotDAO:
        """Return the seed-only catalog snapshot.

        Returns:
            ModelCatalogSnapshotDAO: Validated seed catalog with first-class
                entries, aliases, and family templates.
        """
        return ModelCatalogSnapshotDAO(
            schema_version="1",
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            entries=cls._build_entries(),
            aliases=cls._build_aliases(),
            templates=cls._build_templates(),
        )

    @classmethod
    def _build_entries(cls) -> dict[str, ModelCatalogEntryDAO]:
        """Return the canonical first-class model entries."""
        entries: list[ModelCatalogEntryDAO] = [
            # OpenAI flagship GPT-5.x family
            ModelCatalogEntryDAO(
                model_name="gpt-5.5",
                display_name="GPT-5.5",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.6-luna",
                display_name="GPT-5.6 Luna",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.6-sol",
                display_name="GPT-5.6 Sol",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.6-terra",
                display_name="GPT-5.6 Terra",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            # OpenAI gpt-6-astra (feature 83): canonical identity equals API ID
            ModelCatalogEntryDAO(
                model_name="gpt-6-astra",
                display_name="GPT-6 Astra",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_astra_runtime_profile(),
                reasoning_profile=_openai_astra_reasoning_profile(),
            ),
            # Anthropic Claude family
            ModelCatalogEntryDAO(
                model_name="claude-opus-4-8",
                display_name="Claude Opus 4.8",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=128_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=True,
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="claude-opus-4-8-1m-context",
                display_name="Claude Opus 4.8 (1M context)",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=128_000,
                    context_window=1_000_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=True,
                ),
                api_model_name="claude-opus-4-8",
            ),
            ModelCatalogEntryDAO(
                model_name="claude-sonnet-4-6-1m-context",
                display_name="Claude Sonnet 4.6 (1M context)",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=64_000,
                    context_window=1_000_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
                api_model_name="claude-sonnet-4-6",
            ),
            ModelCatalogEntryDAO(
                model_name="claude-haiku-4-5",
                display_name="Claude Haiku 4.5",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=64_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
                api_model_name="claude-haiku-4-5-20251001",
            ),
            ModelCatalogEntryDAO(
                model_name="claude-fable",
                display_name="Claude Fable",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=64_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
                api_model_name="claude-fable-5",
            ),
            ModelCatalogEntryDAO(
                model_name="claude-mythos",
                display_name="Claude Mythos",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=False,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=128_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
            ),
            # Kimi For Coding family
            ModelCatalogEntryDAO(
                model_name="kimi-k3",
                display_name="Kimi K3",
                provider=ProviderName.KIMI_FOR_CODING,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_kimi_family_runtime_profile(
                    requests_per_minute=20,
                ),
                reasoning_profile=_kimi_k3_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="kimi-for-coding-highspeed",
                display_name="Kimi For Coding Highspeed",
                provider=ProviderName.KIMI_FOR_CODING,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_kimi_family_runtime_profile(
                    requests_per_minute=40,
                ),
                reasoning_profile=_kimi_family_reasoning_profile(),
            ),
            # Existing curated models retained for compatibility
            ModelCatalogEntryDAO(
                model_name="claude-opus-4-7",
                display_name="Claude Opus 4.7",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=128_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=True,
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="claude-sonnet-4-6",
                display_name="Claude Sonnet 4.6",
                provider=ProviderName.ANTHROPIC,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=64_000,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=60,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5-codex",
                display_name="GPT-5 Codex",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.3-codex",
                display_name="GPT-5.3 Codex",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.3-codex-spark",
                display_name="GPT-5.3 Codex Spark",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.2-codex",
                display_name="GPT-5.2 Codex",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=400_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off", "minimal", "low", "medium", "high"],
                    default_level="high",
                    provider_effort_map={
                        "minimal": "low",
                        "low": "low",
                        "medium": "medium",
                        "high": "high",
                    },
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5.4",
                display_name="GPT-5.4",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-5",
                display_name="GPT-5",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=400_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off", "minimal", "low", "medium", "high"],
                    default_level="high",
                    provider_effort_map={
                        "minimal": "minimal",
                        "low": "low",
                        "medium": "medium",
                        "high": "high",
                    },
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-4.1",
                display_name="GPT-4.1",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=1_000_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=1,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off"],
                    default_level="off",
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="gpt-4o",
                display_name="GPT-4o",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=128_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=1,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off"],
                    default_level="off",
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="o3",
                display_name="o3",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off", "minimal", "low", "medium", "high"],
                    default_level="high",
                    provider_effort_map={
                        "minimal": "minimal",
                        "low": "low",
                        "medium": "medium",
                        "high": "high",
                    },
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="o1",
                display_name="o1",
                provider=ProviderName.OPENAI,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=8_192,
                    context_window=200_000,
                    streaming=True,
                    requests_per_minute=30,
                    tokens_per_minute=500_000,
                    automatic_retry_attempts=2,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off", "minimal", "low", "medium", "high"],
                    default_level="high",
                    provider_effort_map={
                        "minimal": "minimal",
                        "low": "low",
                        "medium": "medium",
                        "high": "high",
                    },
                ),
            ),
            ModelCatalogEntryDAO(
                model_name="kimi-for-coding",
                display_name="Kimi For Coding (K2)",
                provider=ProviderName.KIMI_FOR_CODING,
                support_tier="first_class",
                visible_in_picker=True,
                runtime_profile=ModelRuntimeProfileDAO(
                    max_tokens=32_768,
                    context_window=262_144,
                    streaming=True,
                    requests_per_minute=20,
                    tokens_per_minute=200_000,
                    automatic_retry_attempts=3,
                    local_retry_wait_cap_seconds=30,
                ),
                reasoning_profile=ModelReasoningProfileDAO(
                    supported_levels=["off"],
                    default_level="off",
                ),
                aliases=["kimi-k2", "moonshot-k2"],
            ),
        ]
        return {entry.model_name: entry for entry in entries}

    @classmethod
    def _build_aliases(cls) -> dict[str, ModelAliasDAO]:
        """Return backward-compatible aliases as explicit catalog data."""
        aliases: list[ModelAliasDAO] = [
            ModelAliasDAO(
                alias="kimi-k2",
                canonical_model_name="kimi-for-coding",
                support_tier="compatibility_only",
            ),
            ModelAliasDAO(
                alias="moonshot-k2",
                canonical_model_name="kimi-for-coding",
                support_tier="compatibility_only",
            ),
            ModelAliasDAO(
                alias="moonshot-for-coding",
                canonical_model_name="kimi-for-coding",
                support_tier="compatibility_only",
            ),
        ]
        return {alias.alias: alias for alias in aliases}

    @classmethod
    def provider_default_models(cls) -> dict[ProviderName, str]:
        """Return committed provider landing models.

        These are intentionally stable. New first-class models do not
        automatically become the default; default promotion is a product
        decision.

        Returns:
            dict[ProviderName, str]: Provider → canonical default model name.
        """
        return {
            ProviderName.ANTHROPIC: "claude-opus-4-8-1m-context",
            ProviderName.OPENAI: "gpt-5.4",
            ProviderName.KIMI_FOR_CODING: "kimi-for-coding",
        }

    @classmethod
    def _build_templates(cls) -> list[ProviderModelTemplateDAO]:
        """Return family templates for future or discovered models."""
        return [
            ProviderModelTemplateDAO(
                family_patterns=["gpt-5."],
                provider=ProviderName.OPENAI,
                display_name_template="{model_name}",
                runtime_profile=_openai_flagship_runtime_profile(),
                reasoning_profile=_openai_flagship_reasoning_profile(),
                default_visible=True,
            ),
            ProviderModelTemplateDAO(
                family_patterns=["claude-"],
                provider=ProviderName.ANTHROPIC,
                display_name_template="{model_name}",
                runtime_profile=_anthropic_adaptive_runtime_profile(),
                reasoning_profile=_anthropic_adaptive_reasoning_profile(
                    supports_xhigh=False,
                ),
                default_visible=True,
            ),
            ProviderModelTemplateDAO(
                family_patterns=["kimi-"],
                provider=ProviderName.KIMI_FOR_CODING,
                display_name_template="{model_name}",
                runtime_profile=_kimi_family_runtime_profile(
                    requests_per_minute=20,
                ),
                reasoning_profile=_kimi_family_reasoning_profile(),
                default_visible=True,
            ),
        ]
