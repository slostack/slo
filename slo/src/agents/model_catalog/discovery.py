"""Provider discovery adapters and merge helpers for the model catalog."""

from __future__ import annotations

import re
from typing import Optional

from config.logger import log_error, log_info
from src.agents.model_catalog.dao import (
    CatalogRefreshResultDAO,
    ModelAliasDAO,
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
    ProviderDiscoveryResultDAO,
    ProviderModelMetadataDAO,
    ProviderModelTemplateDAO,
)
from src.auth.credential_dao import ProviderName


class ProviderModelDiscoveryService:
    """Compatibility discovery gateway and pure legacy direct-family merge helpers."""

    @classmethod
    async def refresh(cls, *, provider: ProviderName, force: bool = False) -> CatalogRefreshResultDAO:
        """Delegate explicit discovery to the sole raw-state/publication owner.

        Args:
            provider: Provider requested by the caller, never an all-provider scan.
            force: Whether the existing owner should bypass freshness.

        Returns:
            CatalogRefreshResultDAO: The catalog owner's safe outcome.
        """
        from src.agents.model_catalog.service import ModelCatalogService

        return await ModelCatalogService.refresh(provider=provider, force=force)

    @classmethod
    def _merge_provider_result(
        cls,
        *,
        entries: dict[str, ModelCatalogEntryDAO],
        templates: tuple[ProviderModelTemplateDAO, ...],
        result: ProviderDiscoveryResultDAO,
    ) -> dict[str, ModelCatalogEntryDAO]:
        """Merge discovered model names into the entry map.

        Args:
            entries (dict[str, ModelCatalogEntryDAO]): Current entry map.
            templates (list[ProviderModelTemplateDAO]): Family templates to apply.
            result (ProviderDiscoveryResultDAO): One provider discovery result.

        Returns:
            dict[str, ModelCatalogEntryDAO]: Entry map with discovered entries.
        """
        merged_entries: dict[str, ModelCatalogEntryDAO] = dict(entries)
        for model_name in result.available_model_names:
            if model_name in merged_entries:
                merged_entries[model_name] = cls._refresh_existing_entry(
                    entry=merged_entries[model_name],
                    metadata=result.metadata.get(model_name),
                )
                continue
            discovered_entry: Optional[ModelCatalogEntryDAO] = cls._build_discovered_entry(
                model_name=model_name,
                templates=templates,
                metadata=result.metadata.get(model_name),
            )
            if discovered_entry is not None:
                merged_entries[model_name] = discovered_entry
                log_info(
                    msg="model_catalog_entry_auto_added",
                    model_name=model_name,
                    support_tier=discovered_entry.support_tier,
                )
        return merged_entries

    @classmethod
    def _refresh_existing_entry(
        cls,
        *,
        entry: ModelCatalogEntryDAO,
        metadata: Optional[ProviderModelMetadataDAO],
    ) -> ModelCatalogEntryDAO:
        """Refresh a seeded entry with any safe discovered metadata.

        Args:
            entry (ModelCatalogEntryDAO): Existing catalog entry.
            metadata (Optional[ProviderModelMetadataDAO]): Discovered metadata.

        Returns:
            ModelCatalogEntryDAO: Entry with visibility and metadata refreshed.
        """
        if entry.model_name == "claude-mythos":
            return entry.model_copy(update={"visible_in_picker": True})
        if metadata is None:
            return entry
        return cls._patch_entry_from_metadata(entry=entry, metadata=metadata)

    @classmethod
    def _build_discovered_entry(
        cls,
        *,
        model_name: str,
        templates: tuple[ProviderModelTemplateDAO, ...],
        metadata: Optional[ProviderModelMetadataDAO],
    ) -> Optional[ModelCatalogEntryDAO]:
        """Build an auto-discovered entry from the first matching family template.

        Args:
            model_name (str): Discovered model name.
            templates (list[ProviderModelTemplateDAO]): Family templates.
            metadata (Optional[ProviderModelMetadataDAO]): Optional metadata.

        Returns:
            Optional[ModelCatalogEntryDAO]: Auto-discovered entry, or ``None`` when
                no template matches.
        """
        template: Optional[ProviderModelTemplateDAO] = cls._matching_template(
            model_name=model_name,
            templates=templates,
        )
        if template is None:
            return None
        display_name: str = (
            template.display_name_template.format(model_name=model_name)
            if template.display_name_template
            else model_name
        )
        entry: ModelCatalogEntryDAO = ModelCatalogEntryDAO(
            model_name=model_name,
            display_name=display_name,
            provider=template.provider,
            support_tier="auto_discovered",
            visible_in_picker=template.default_visible,
            runtime_profile=template.runtime_profile,
            reasoning_profile=template.reasoning_profile,
        )
        if metadata is not None:
            entry = cls._patch_entry_from_metadata(entry=entry, metadata=metadata)
        return entry

    @classmethod
    def _matching_template(
        cls,
        *,
        model_name: str,
        templates: tuple[ProviderModelTemplateDAO, ...],
    ) -> Optional[ProviderModelTemplateDAO]:
        """Return the first template that matches the discovered model name.

        Args:
            model_name (str): Discovered model name.
            templates (list[ProviderModelTemplateDAO]): Family templates.

        Returns:
            Optional[ProviderModelTemplateDAO]: Matching template, or ``None``.
        """
        for template in templates:
            for pattern in template.family_patterns:
                if pattern.startswith("^"):
                    if re.search(pattern, model_name):
                        return template
                    continue
                if model_name.startswith(pattern):
                    return template
        return None

    @classmethod
    def _patch_entry_from_metadata(
        cls,
        *,
        entry: ModelCatalogEntryDAO,
        metadata: ProviderModelMetadataDAO,
    ) -> ModelCatalogEntryDAO:
        """Patch safe discovered metadata into an entry without inference.

        Args:
            entry (ModelCatalogEntryDAO): Entry to patch.
            metadata (ProviderModelMetadataDAO): Safe discovered metadata.

        Returns:
            ModelCatalogEntryDAO: Entry with explicitly reported values applied.
        """
        runtime_profile: ModelRuntimeProfileDAO = entry.runtime_profile
        if metadata.max_tokens is not None or metadata.context_window is not None:
            runtime_profile = ModelRuntimeProfileDAO(
                max_tokens=metadata.max_tokens or runtime_profile.max_tokens,
                context_window=metadata.context_window or runtime_profile.context_window,
                streaming=runtime_profile.streaming,
                requests_per_minute=runtime_profile.requests_per_minute,
                tokens_per_minute=runtime_profile.tokens_per_minute,
                automatic_retry_attempts=runtime_profile.automatic_retry_attempts,
                local_retry_wait_cap_seconds=runtime_profile.local_retry_wait_cap_seconds,
            )
        return entry.model_copy(update={"runtime_profile": runtime_profile})


class ModelCatalogOverrideService:
    """Apply operator overrides to a merged catalog snapshot."""

    @classmethod
    def apply_overrides(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        overrides: list[ModelCatalogOverrideDAO],
    ) -> ModelCatalogSnapshotDAO:
        """Apply override rows last, after seed/cache/discovery merge.

        Unknown targets are logged and ignored.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Snapshot to patch.
            overrides (list[ModelCatalogOverrideDAO]): Operator overrides.

        Returns:
            ModelCatalogSnapshotDAO: Snapshot with overrides applied.
        """
        entries: dict[str, ModelCatalogEntryDAO] = dict(snapshot.entries)
        aliases: dict[str, ModelAliasDAO] = dict(snapshot.aliases)
        for override in overrides:
            cls._apply_one_override(
                entries=entries,
                aliases=aliases,
                override=override,
            )
        return ModelCatalogSnapshotDAO(
            schema_version=snapshot.schema_version,
            generated_at=snapshot.generated_at,
            entries=entries,
            aliases=aliases,
            templates=snapshot.templates,
        )

    @classmethod
    def _apply_one_override(
        cls,
        *,
        entries: dict[str, ModelCatalogEntryDAO],
        aliases: dict[str, ModelAliasDAO],
        override: ModelCatalogOverrideDAO,
    ) -> None:
        """Apply one override to the entry or alias map in place.

        Args:
            entries (dict[str, ModelCatalogEntryDAO]): Mutable entry map.
            aliases (dict[str, ModelAliasDAO]): Mutable alias map.
            override (ModelCatalogOverrideDAO): One override row.
        """
        target_name: Optional[str] = override.model_name or override.alias
        if target_name is None:
            log_error(
                msg="model_catalog_override_ignored_no_target",
                override=override.model_dump(),
            )
            return

        if override.model_name is not None:
            if override.model_name not in entries:
                log_error(
                    msg="model_catalog_override_ignored_unknown_model",
                    model_name=override.model_name,
                )
                return
            entries[override.model_name] = cls._patch_entry(
                entry=entries[override.model_name],
                override=override,
            )
            log_info(
                msg="model_catalog_override_applied",
                model_name=override.model_name,
            )
            return

        if override.alias is not None:
            if override.alias not in aliases:
                log_error(
                    msg="model_catalog_override_ignored_unknown_alias",
                    alias=override.alias,
                )
                return
            existing_alias: ModelAliasDAO = aliases[override.alias]
            aliases[override.alias] = cls._patch_alias(
                alias=existing_alias,
                override=override,
            )
            log_info(
                msg="model_catalog_override_applied",
                alias=override.alias,
            )

    @classmethod
    def _patch_entry(
        cls,
        *,
        entry: ModelCatalogEntryDAO,
        override: ModelCatalogOverrideDAO,
    ) -> ModelCatalogEntryDAO:
        """Return a copy of ``entry`` with override fields applied.

        Args:
            entry (ModelCatalogEntryDAO): Original entry.
            override (ModelCatalogOverrideDAO): Override row.

        Returns:
            ModelCatalogEntryDAO: Patched entry.
        """
        data: dict = entry.model_dump()
        if override.display_name is not None:
            data["display_name"] = override.display_name
        if entry.provider is not ProviderName.OPENROUTER and override.visible_in_picker is not None:
            data["visible_in_picker"] = override.visible_in_picker
        if entry.provider is ProviderName.OPENROUTER and override.visible_in_picker is False:
            data["visible_in_picker"] = False
        if override.support_tier is not None:
            data["support_tier"] = override.support_tier
        if override.runtime_profile is not None:
            runtime_profile: ModelRuntimeProfileDAO = override.runtime_profile
            if entry.provider is ProviderName.OPENROUTER:
                runtime_profile = cls._restricted_runtime_profile(
                    base=entry.runtime_profile,
                    override=override.runtime_profile,
                )
            data["runtime_profile"] = runtime_profile.model_dump()
        if override.reasoning_profile is not None:
            entry.require_reasoning_override_compatibility(reasoning_profile=override.reasoning_profile)
            reasoning_profile: ModelReasoningProfileDAO = override.reasoning_profile
            if entry.provider is ProviderName.OPENROUTER:
                reasoning_profile = cls._restricted_reasoning_profile(
                    base=entry.reasoning_profile,
                    override=override.reasoning_profile,
                )
            data["reasoning_profile"] = reasoning_profile.model_dump()
        return ModelCatalogEntryDAO.model_validate(data)

    @classmethod
    def _restricted_runtime_profile(
        cls,
        *,
        base: ModelRuntimeProfileDAO,
        override: ModelRuntimeProfileDAO,
    ) -> ModelRuntimeProfileDAO:
        """Reject an override that broadens runtime limits.

        Args:
            base (ModelRuntimeProfileDAO): Provider-established profile.
            override (ModelRuntimeProfileDAO): Operator requested profile.

        Returns:
            ModelRuntimeProfileDAO: Restrictive operator profile.

        Raises:
            ValueError: When an override increases a remote or local limit.
        """
        if override.max_tokens > base.max_tokens or override.context_window > base.context_window:
            raise ValueError("Model catalog overrides cannot increase provider limits.")
        if override.requests_per_minute > base.requests_per_minute:
            raise ValueError("Model catalog overrides cannot increase provider rates.")
        if cls._increases_optional_limit(base=base.tokens_per_minute, override=override.tokens_per_minute):
            raise ValueError("Model catalog overrides cannot increase provider rates.")
        return override

    @staticmethod
    def _increases_optional_limit(*, base: Optional[int], override: Optional[int]) -> bool:
        """Return whether an optional limit becomes less restrictive.

        Args:
            base (Optional[int]): Provider-established optional limit.
            override (Optional[int]): Operator requested optional limit.

        Returns:
            bool: Whether the override broadens the allowed rate.
        """
        if base is None:
            return False
        if override is None:
            return True
        return override > base

    @staticmethod
    def _restricted_reasoning_profile(
        *,
        base: ModelReasoningProfileDAO,
        override: ModelReasoningProfileDAO,
    ) -> ModelReasoningProfileDAO:
        """Reject an override that introduces unsupported reasoning controls.

        Args:
            base (ModelReasoningProfileDAO): Provider-established reasoning profile.
            override (ModelReasoningProfileDAO): Operator requested profile.

        Returns:
            ModelReasoningProfileDAO: Restrictive operator profile.

        Raises:
            ValueError: When an override unlocks a reasoning level.
        """
        if not set(override.supported_levels).issubset(set(base.supported_levels)):
            raise ValueError("Model catalog overrides cannot unlock reasoning controls.")
        if base.provider_reasoning_required and not override.provider_reasoning_required:
            raise ValueError("Model catalog overrides cannot remove mandatory reasoning.")
        if (
            base.forbid_sampling_parameters_when_enabled
            and not override.forbid_sampling_parameters_when_enabled
        ):
            raise ValueError("Model catalog overrides cannot relax reasoning request restrictions.")
        for level, effort in override.provider_effort_map.items():
            if base.provider_effort_map.get(level) != effort:
                raise ValueError("Model catalog overrides cannot change provider reasoning effort mappings.")
        for level, budget in override.provider_budget_map.items():
            if base.provider_budget_map.get(level) != budget:
                raise ValueError("Model catalog overrides cannot change provider reasoning budget mappings.")
        return override

    @classmethod
    def _patch_alias(
        cls,
        *,
        alias: ModelAliasDAO,
        override: ModelCatalogOverrideDAO,
    ) -> ModelAliasDAO:
        """Return a copy of ``alias`` with override fields applied.

        Args:
            alias (ModelAliasDAO): Original alias.
            override (ModelCatalogOverrideDAO): Override row.

        Returns:
            ModelAliasDAO: Patched alias.
        """
        data: dict = alias.model_dump()
        if override.support_tier is not None:
            data["support_tier"] = override.support_tier
        return ModelAliasDAO.model_validate(data)
