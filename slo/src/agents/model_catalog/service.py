"""Load and project the merged model catalog for the current process."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config.logger import log_error, log_info
from src.agents.model_catalog.dao import (
    ModelAliasDAO,
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.discovery import (
    ModelCatalogOverrideService,
    ProviderModelDiscoveryService,
)
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import ProviderName


class ModelCatalogService:
    """Load and project the merged model catalog for one process.

    The rest of the codebase calls this service instead of reading several
    independent model tables.
    """

    _snapshot: Optional[ModelCatalogSnapshotDAO] = None

    @classmethod
    def load(
        cls,
        *,
        enable_discovery: bool = False,
    ) -> ModelCatalogSnapshotDAO:
        """Return the merged catalog snapshot for the current process.

        The snapshot is computed once per process and memoized. This prevents
        concurrent consumers from triggering multiple discovery calls and
        guarantees that one process sees one consistent view of the catalog.

        Args:
            enable_discovery (bool): When ``True``, stale cache triggers a
                discovery refresh. Default is ``False`` so ordinary startup stays
                synchronous and offline-safe.

        Returns:
            ModelCatalogSnapshotDAO: Seed, cache, discovery, and override data
                merged into one consistent snapshot.
        """
        if cls._snapshot is not None:
            return cls._snapshot
        log_info(msg="model_catalog_load_started")
        seed_snapshot: ModelCatalogSnapshotDAO = SeedModelCatalog.load()
        log_info(msg="model_catalog_seed_loaded", entry_count=len(seed_snapshot.entries))
        cached_snapshot: Optional[ModelCatalogSnapshotDAO] = ModelCatalogStore.load_cache()
        if cached_snapshot is not None:
            log_info(
                msg="model_catalog_cache_loaded",
                entry_count=len(cached_snapshot.entries),
            )
        merged_snapshot: ModelCatalogSnapshotDAO = cls._merge_seed_and_cache(
            seed_snapshot=seed_snapshot,
            cached_snapshot=cached_snapshot,
        )
        if enable_discovery and cls._should_refresh_discovery(cached_snapshot=cached_snapshot):
            refreshed_snapshot: ModelCatalogSnapshotDAO = ProviderModelDiscoveryService.refresh(
                base_snapshot=merged_snapshot,
            )
            merged_snapshot = cls._apply_manual_overrides(snapshot=refreshed_snapshot)
            ModelCatalogStore.write_cache(snapshot=merged_snapshot)
        else:
            merged_snapshot = cls._apply_manual_overrides(snapshot=merged_snapshot)
        cls._snapshot = merged_snapshot
        return merged_snapshot

    @classmethod
    def reset(cls) -> None:
        """Clear the process-local snapshot cache.

        Used by tests and by any caller that has applied overrides and needs
        a fresh load.
        """
        cls._snapshot = None

    @classmethod
    def supported_models_by_provider(cls) -> dict[ProviderName, list[str]]:
        """Return visible supported models grouped by provider.

        Returns:
            dict[ProviderName, list[str]]: Picker-visible model names grouped by provider.
        """
        snapshot: ModelCatalogSnapshotDAO = cls.load()
        return cls._group_visible_entries(snapshot=snapshot)

    @classmethod
    def entry_for_model(
        cls,
        *,
        model_name: str,
    ) -> ModelCatalogEntryDAO:
        """Return the canonical entry for one model or alias.

        Args:
            model_name (str): Canonical model name or known alias.

        Returns:
            ModelCatalogEntryDAO: Matching catalog entry.

        Raises:
            ValueError: When the model name or alias is not known.
        """
        snapshot: ModelCatalogSnapshotDAO = cls.load()
        return cls._resolve_entry(snapshot=snapshot, model_name=model_name)

    @classmethod
    def api_model_name_for(
        cls,
        *,
        model_name: str,
    ) -> str:
        """Return the API model ID to send to the provider for one model or alias.

        Aliases resolve to their canonical entry first. When the entry carries
        an ``api_model_name`` override it wins; otherwise the canonical
        ``model_name`` is returned verbatim (identity mapping).

        Args:
            model_name (str): Canonical model name or known alias.

        Returns:
            str: The API model ID to pass to the provider.

        Raises:
            ValueError: When the model name or alias is not known.
        """
        entry: ModelCatalogEntryDAO = cls.entry_for_model(model_name=model_name)
        if entry.api_model_name is None:
            return entry.model_name
        return entry.api_model_name

    @classmethod
    def _merge_seed_and_cache(
        cls,
        *,
        seed_snapshot: ModelCatalogSnapshotDAO,
        cached_snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> ModelCatalogSnapshotDAO:
        """Merge seed and cached snapshots into one consistent view.

        Cache entries refresh seed entries without replacing them wholesale, and
        seed aliases/templates always win unless the cache introduces new ones.

        Args:
            seed_snapshot (ModelCatalogSnapshotDAO): Committed seed snapshot.
            cached_snapshot (Optional[ModelCatalogSnapshotDAO]): Cached snapshot, if any.

        Returns:
            ModelCatalogSnapshotDAO: Merged snapshot.
        """
        if cached_snapshot is None:
            return seed_snapshot
        merged_entries: dict[str, ModelCatalogEntryDAO] = dict(seed_snapshot.entries)
        for model_name, cached_entry in cached_snapshot.entries.items():
            if model_name in merged_entries:
                merged_entries[model_name] = cls._merge_entry(
                    seed_entry=merged_entries[model_name],
                    cached_entry=cached_entry,
                )
            else:
                merged_entries[model_name] = cached_entry
        merged_aliases: dict[str, ModelAliasDAO] = dict(seed_snapshot.aliases)
        merged_aliases.update(cached_snapshot.aliases)
        return ModelCatalogSnapshotDAO(
            schema_version="1",
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            entries=merged_entries,
            aliases=merged_aliases,
            templates=seed_snapshot.templates,
        )

    @classmethod
    def _merge_entry(
        cls,
        *,
        seed_entry: ModelCatalogEntryDAO,
        cached_entry: ModelCatalogEntryDAO,
    ) -> ModelCatalogEntryDAO:
        """Refresh a seed entry with cached visibility and metadata.

        Args:
            seed_entry (ModelCatalogEntryDAO): Committed seed entry.
            cached_entry (ModelCatalogEntryDAO): Cached entry.

        Returns:
            ModelCatalogEntryDAO: Entry with cache visibility/metadata applied.
        """
        data: dict = seed_entry.model_dump()
        data["visible_in_picker"] = cached_entry.visible_in_picker
        if cached_entry.support_tier != "first_class":
            data["support_tier"] = cached_entry.support_tier
        return ModelCatalogEntryDAO.model_validate(data)

    @classmethod
    def _should_refresh_discovery(
        cls,
        *,
        cached_snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> bool:
        """Return whether discovery should run to refresh the cache.

        Discovery refreshes when the cache is missing, stale, older than the TTL,
        or has a schema version mismatch.

        Args:
            cached_snapshot (Optional[ModelCatalogSnapshotDAO]): Loaded cache.

        Returns:
            bool: True when discovery should refresh.
        """
        if cached_snapshot is None:
            return True
        if cached_snapshot.schema_version != "1":
            return True
        return not ModelCatalogStore.is_cache_fresh(snapshot=cached_snapshot)

    @classmethod
    def _apply_manual_overrides(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
    ) -> ModelCatalogSnapshotDAO:
        """Load and apply operator overrides to the merged snapshot.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Merged snapshot.

        Returns:
            ModelCatalogSnapshotDAO: Snapshot with overrides applied.
        """
        overrides: list[ModelCatalogOverrideDAO] = ModelCatalogStore.load_overrides()
        if not overrides:
            return snapshot
        return ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=overrides,
        )

    @classmethod
    def _group_visible_entries(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
    ) -> dict[ProviderName, list[str]]:
        """Group picker-visible entries by provider.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Merged snapshot.

        Returns:
            dict[ProviderName, list[str]]: Visible model names grouped by provider.
        """
        grouped: dict[ProviderName, list[str]] = {
            ProviderName.ANTHROPIC: [],
            ProviderName.OPENAI: [],
            ProviderName.KIMI_FOR_CODING: [],
        }
        for entry in snapshot.entries.values():
            if not entry.visible_in_picker:
                continue
            grouped[entry.provider].append(entry.model_name)
        for provider in grouped:
            grouped[provider].sort()
        return grouped

    @classmethod
    def _resolve_entry(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        model_name: str,
    ) -> ModelCatalogEntryDAO:
        """Resolve a canonical name or alias to its catalog entry.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Merged snapshot.
            model_name (str): Canonical model name or alias.

        Returns:
            ModelCatalogEntryDAO: Matching entry.

        Raises:
            ValueError: When the name cannot be resolved.
        """
        if model_name in snapshot.entries:
            return snapshot.entries[model_name]
        alias = snapshot.aliases.get(model_name)
        if alias is not None and alias.canonical_model_name in snapshot.entries:
            return snapshot.entries[alias.canonical_model_name]
        supported_models: str = ", ".join(sorted(snapshot.entries))
        raise ValueError(f"Unsupported model_name '{model_name}'. Supported models: {supported_models}")
