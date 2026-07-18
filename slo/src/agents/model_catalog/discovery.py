"""Provider discovery adapters and merge helpers for the model catalog."""

from __future__ import annotations

import re
from typing import Optional

from config.logger import log_error, log_info
from src.agents.model_catalog.dao import (
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
from src.auth.credential_resolver import CredentialResolver


class ProviderModelDiscoveryService:
    """Best-effort provider discovery and merge into a catalog snapshot."""

    @classmethod
    def refresh(
        cls,
        *,
        base_snapshot: ModelCatalogSnapshotDAO,
    ) -> ModelCatalogSnapshotDAO:
        """Run discovery for providers with credentials and merge the results.

        Discovery never mutates ``base_snapshot`` in place. A failed discovery
        call returns the base snapshot unchanged.

        Args:
            base_snapshot (ModelCatalogSnapshotDAO): Seed+cache merged snapshot.

        Returns:
            ModelCatalogSnapshotDAO: Snapshot with discovered entries merged in.
        """
        log_info(msg="model_catalog_discovery_started")
        providers: list[ProviderName] = cls._providers_with_credentials()
        if not providers:
            log_info(msg="model_catalog_discovery_skipped_no_credentials")
            return base_snapshot

        refreshed_entries: dict[str, ModelCatalogEntryDAO] = dict(base_snapshot.entries)
        for provider in providers:
            result: ProviderDiscoveryResultDAO = cls._discover_provider(provider=provider)
            refreshed_entries = cls._merge_provider_result(
                entries=refreshed_entries,
                templates=base_snapshot.templates,
                result=result,
            )
        log_info(msg="model_catalog_discovery_succeeded")
        return ModelCatalogSnapshotDAO(
            schema_version=base_snapshot.schema_version,
            generated_at=base_snapshot.generated_at,
            entries=refreshed_entries,
            aliases=base_snapshot.aliases,
            templates=base_snapshot.templates,
        )

    @classmethod
    def _providers_with_credentials(cls) -> list[ProviderName]:
        """Return providers for which a credential can be resolved.

        Returns:
            list[ProviderName]: Providers with credentials.
        """
        providers: list[ProviderName] = []
        for provider in ProviderName:
            if CredentialResolver.resolve(provider=provider) is not None:
                providers.append(provider)
        return providers

    @classmethod
    def _discover_provider(
        cls,
        *,
        provider: ProviderName,
    ) -> ProviderDiscoveryResultDAO:
        """Return a conservative discovery result for one provider.

        v1 adapters are placeholders: they return an empty list so the default
        gate stays offline-safe. Live-provider probes can be added behind
        credential-gated e2e tests without changing this contract.

        Args:
            provider (ProviderName): Provider to query.

        Returns:
            ProviderDiscoveryResultDAO: Conservative discovery result.
        """
        log_info(msg="model_catalog_provider_discovery", provider=provider.value)
        return ProviderDiscoveryResultDAO(provider=provider, available_model_names=[])

    @classmethod
    def _merge_provider_result(
        cls,
        *,
        entries: dict[str, ModelCatalogEntryDAO],
        templates: list[ProviderModelTemplateDAO],
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
        templates: list[ProviderModelTemplateDAO],
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
        templates: list[ProviderModelTemplateDAO],
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
        if override.visible_in_picker is not None:
            data["visible_in_picker"] = override.visible_in_picker
        if override.support_tier is not None:
            data["support_tier"] = override.support_tier
        if override.runtime_profile is not None:
            data["runtime_profile"] = override.runtime_profile.model_dump()
        if override.reasoning_profile is not None:
            data["reasoning_profile"] = override.reasoning_profile.model_dump()
        return ModelCatalogEntryDAO.model_validate(data)

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
