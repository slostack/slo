"""Supported interactive model catalog helpers for the TUI."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Optional, overload
from src.agents.model_catalog import dao as catalog_dao
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO

from pydantic import BaseModel, ConfigDict

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver

__all__ = [
    "MODEL_CATALOG",
    "ModelPickerRowDAO",
    "ModelSuggestionEntryDAO",
    "model_suggestion_entries",
    "supported_models_by_provider",
]


class ModelPickerRowDAO(BaseModel):
    """One entry in the model catalog for the TUI picker.

    Attributes:
        provider (str): Provider group label (e.g. ``"anthropic"``).
        display_name (str): Human-readable label shown in the picker.
        model_name (str): Canonical model identifier passed to LLMFactory.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    display_name: str
    model_name: str


class ModelSuggestionEntryDAO(BaseModel):
    """One supported model row for ``/model`` suggestions.

    Attributes:
        model_name (str): Canonical model identifier.
        display_name (str): Human-readable label for the model.
        provider (ProviderName): Owning provider.
        is_active (bool): Whether this is the current session model.
        requires_auth (bool): Whether the provider lacks credentials.
        reasoning_summary (str): Supported reasoning levels, comma-joined.
        support_tier_label (str): Non-standard support-tier label, or ``""``.
    """

    model_config = ConfigDict(extra="forbid")

    model_name: str
    display_name: str
    provider: ProviderName
    is_active: bool
    requires_auth: bool
    reasoning_summary: str
    support_tier_label: str
    reasoning_controls_available: bool = True
    reasoning_disable_available: bool = False
    status_summary: str = ""
    context_window: int = 0
    catalog_generation: int = 0


class ModelCatalogView(Sequence[ModelPickerRowDAO]):
    """Read-only live picker sequence; each operation captures one generation."""

    @staticmethod
    def _rows() -> list[ModelPickerRowDAO]:
        """Project detached visible rows without authentication or network I/O."""
        snapshot = ModelCatalogService.load()
        return [
            ModelPickerRowDAO(
                provider=entry.provider.value, display_name=entry.display_name, model_name=entry.model_name
            )
            for entry in sorted(
                snapshot.entries.values(), key=lambda item: (item.provider.value, item.model_name)
            )
            if entry.visible_in_picker
        ]

    @overload
    def __getitem__(self, index: int) -> ModelPickerRowDAO: ...

    @overload
    def __getitem__(self, index: slice) -> list[ModelPickerRowDAO]: ...

    def __getitem__(self, index: int | slice) -> ModelPickerRowDAO | list[ModelPickerRowDAO]:
        """Read an index or slice from one current projection."""
        return self._rows()[index]

    def __len__(self) -> int:
        """Return the current visible count."""
        return len(self._rows())

    def __iter__(self) -> Iterator[ModelPickerRowDAO]:
        """Iterate one captured projection, not shifting global indices."""
        return iter(self._rows())


MODEL_CATALOG: Sequence[ModelPickerRowDAO] = ModelCatalogView()


def _rebuild_model_catalog() -> None:
    """Deprecated no-op: the view follows publication automatically."""


def supported_models_by_provider(
    *, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> dict[ProviderName, list[str]]:
    """Return the supported interactive model catalog grouped by provider.

    Returns:
        dict[ProviderName, list[str]]: Deterministically sorted model
            names grouped by provider.
    """
    return ModelCatalogService.supported_models_by_provider(snapshot=snapshot)


def model_suggestion_entries(
    *, active_model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> list[ModelSuggestionEntryDAO]:
    """Return rich model rows for ``/model`` suggestions.

    Args:
        active_model_name (str): Current session model.

    Returns:
        list[ModelSuggestionEntryDAO]: Deterministically ordered model rows.
    """
    snapshot = snapshot if snapshot is not None else ModelCatalogService.load()
    return ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=active_model_name)


def _project_rows(
    *,
    snapshot: ModelCatalogSnapshotDAO,
    active_model_name: str,
    statuses: dict[ProviderName, str],
    auth_types: Optional[dict[ProviderName, AuthType]] = None,
) -> list[ModelSuggestionEntryDAO]:
    """Delegate the existing compatibility entry point to its lifecycle projection owner.

    Args:
        snapshot: Immutable row view.
        active_model_name: Selected route.
        statuses: Cached safe statuses.
        auth_types: Cached types; absent means unchecked.

    Returns:
        Ordered detached rows with no credential or network access.
    """
    return ModelSuggestionProjection._build_rows(
        snapshot=snapshot,
        active_model_name=active_model_name,
        statuses=statuses,
        auth_types=auth_types or {},
    )


class ModelSuggestionProjection:
    """Bounded presentation cache; lifecycle refresh owns all credential reads."""

    _revision: int = 0
    _statuses: dict[ProviderName, str] = {}
    _auth_types: dict[ProviderName, AuthType] = {}
    _key: tuple[int, int, int, str] | None = None
    _snapshot: Optional[ModelCatalogSnapshotDAO] = None
    _rows: list[ModelSuggestionEntryDAO] = []

    @classmethod
    def reset(cls) -> None:
        """Clear process-local picker projection state between independent app lifecycles."""
        cls._revision = 0
        cls._statuses = {}
        cls._auth_types = {}
        cls._key = None
        cls._snapshot = None
        cls._rows = []

    @classmethod
    def refresh_authentication(cls, *, verified_credential: Optional[CredentialDAO] = None) -> None:
        """Project lifecycle evidence once, without retaining credentials.

        Args:
            verified_credential: Private successful modal dismissal capture. Only
                OpenRouter's dismissal contract proves key verification. The
                capture is compared at this lifecycle boundary, never on typing.
        """
        statuses: dict[ProviderName, str] = {}
        auth_types: dict[ProviderName, AuthType] = {}
        for provider in ProviderName:
            current = CredentialResolver.resolve(provider=provider)
            statuses[provider] = cls._authentication_status(
                provider=provider, current=current, verified_credential=verified_credential
            )
            if current is not None:
                auth_types[provider] = current.auth_type
        cls._statuses = statuses
        cls._auth_types = auth_types
        cls._revision += 1

    @classmethod
    def _build_rows(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        active_model_name: str,
        statuses: dict[ProviderName, str],
        auth_types: dict[ProviderName, AuthType],
    ) -> list[ModelSuggestionEntryDAO]:
        """Project visible entries for the compatibility bridge on cache invalidation.

        Args:
            snapshot: Immutable source view.
            active_model_name: Selected identity.
            statuses: Safe lifecycle evidence.
            auth_types: Effective types captured at refresh only.

        Returns:
            Deterministically ordered visible rows.
        """
        return [
            cls._build_row(
                entry=entry,
                generation=snapshot.generation,
                active_model_name=active_model_name,
                statuses=statuses,
                auth_types=auth_types,
            )
            for entry in cls._visible_entries(snapshot=snapshot)
        ]

    @staticmethod
    def _visible_entries(*, snapshot: ModelCatalogSnapshotDAO) -> list[catalog_dao.ModelCatalogEntryDAO]:
        """Filter and order catalog membership for _build_rows before formatting.

        Args:
            snapshot: Immutable catalog view.

        Returns:
            Visible entries ordered by provider then canonical name.
        """
        return sorted(
            (entry for entry in snapshot.entries.values() if entry.visible_in_picker),
            key=lambda entry: (entry.provider.value, entry.model_name),
        )

    @classmethod
    def _build_row(
        cls,
        *,
        entry: catalog_dao.ModelCatalogEntryDAO,
        generation: int,
        active_model_name: str,
        statuses: dict[ProviderName, str],
        auth_types: dict[ProviderName, AuthType],
    ) -> ModelSuggestionEntryDAO:
        """Assemble one presentation row for _build_rows without resolving credentials.

        Args:
            entry: Canonical record, never mutated.
            generation: Source generation.
            active_model_name: Selected identity.
            statuses: Cached status evidence.
            auth_types: Cached types only, never tokens.

        Returns:
            Presentation-only row.
        """
        return ModelSuggestionEntryDAO(
            model_name=entry.model_name,
            display_name=entry.display_name,
            provider=entry.provider,
            is_active=entry.model_name == active_model_name,
            requires_auth=statuses.get(entry.provider) == "requires /auth",
            status_summary=cls._row_status(entry=entry, statuses=statuses, auth_types=auth_types),
            context_window=entry.runtime_profile.context_window,
            catalog_generation=generation,
            reasoning_summary=cls._row_reasoning_summary(entry=entry),
            support_tier_label=cls._row_support_tier(entry=entry),
            reasoning_controls_available=cls._row_controls_available(entry=entry),
            reasoning_disable_available=cls._row_disable_available(entry=entry),
        )

    @classmethod
    def _row_reasoning_summary(cls, *, entry: catalog_dao.ModelCatalogEntryDAO) -> str:
        """Format advertised levels for _build_row, excluding unadvertised gateway off.

        Args:
            entry: Pinned profile and capability evidence.

        Returns:
            Comma-separated levels, preserving direct-row layout.
        """
        return ", ".join(
            level
            for level in entry.reasoning_profile.supported_levels
            if level != "off" or cls._row_shows_off(entry=entry)
        )

    @staticmethod
    def _row_shows_off(*, entry: catalog_dao.ModelCatalogEntryDAO) -> bool:
        """Decide off visibility for row summary without inventing gateway disable permission.

        Args:
            entry: Pinned capability evidence.

        Returns:
            Whether the compatibility off level belongs in the summary.
        """
        return (
            entry.capabilities is None
            or entry.provider is not ProviderName.OPENROUTER
            or entry.capabilities.reasoning_disable_available
        )

    @staticmethod
    def _row_support_tier(*, entry: catalog_dao.ModelCatalogEntryDAO) -> str:
        """Format the existing tier badge during one-row construction.

        Args:
            entry: Canonical support classification.

        Returns:
            Existing auto-discovered label or empty text.
        """
        return "auto-discovered" if entry.support_tier == "auto_discovered" else ""

    @staticmethod
    def _row_controls_available(*, entry: catalog_dao.ModelCatalogEntryDAO) -> bool:
        """Project control-or-disable evidence during one-row construction.

        Args:
            entry: Canonical capability evidence.

        Returns:
            Existing default True for absent capabilities, otherwise advertised control.
        """
        if entry.capabilities is None:
            return True
        return (
            entry.capabilities.reasoning_controls_available or entry.capabilities.reasoning_disable_available
        )

    @staticmethod
    def _row_disable_available(*, entry: catalog_dao.ModelCatalogEntryDAO) -> bool:
        """Project explicit disable evidence during one-row construction.

        Args:
            entry: Canonical capability evidence.

        Returns:
            False when capabilities are absent, otherwise advertised disable permission.
        """
        return entry.capabilities.reasoning_disable_available if entry.capabilities is not None else False

    @staticmethod
    def _row_status(
        *,
        entry: catalog_dao.ModelCatalogEntryDAO,
        statuses: dict[ProviderName, str],
        auth_types: dict[ProviderName, AuthType],
    ) -> str:
        """Apply record-owned compatibility using lifecycle evidence, never live auth.

        Args:
            entry: Pinned policy owner.
            statuses: Safe cached status strings.
            auth_types: Cached types, not credential objects.

        Returns:
            Local incompatibility guidance or the existing authentication status.
        """
        if entry.backend_eligibility_message(auth_type=auth_types.get(entry.provider)) is not None:
            return "unavailable for ChatGPT/Codex; Platform API key required"
        return statuses.get(entry.provider, "authentication not checked")

    @staticmethod
    def _authentication_status(
        *,
        provider: ProviderName,
        current: Optional[CredentialDAO],
        verified_credential: Optional[CredentialDAO],
    ) -> str:
        """Project only matching OpenRouter dismissal evidence; never infer timestamps."""
        if current is None:
            return "requires /auth"
        if provider is ProviderName.OPENAI and current.auth_type is AuthType.OAUTH:
            return "subscription configured; not checked"
        if provider is not ProviderName.OPENROUTER or verified_credential is None:
            return "key configured; not checked"
        if verified_credential.provider is not provider:
            return "key configured; not checked"
        if current.access_token != verified_credential.access_token:
            return "credential changed; refresh required"
        return "key verified; verification time unavailable; catalog status unknown"

    @staticmethod
    def _catalog_status_summary() -> Optional[str]:
        """Render only safe lifecycle facts; never substitute snapshot generation time."""
        status = ModelCatalogService.lifecycle_status()
        if status.state == "historical":
            return "cached history; current key not checked"
        if status.state == "stale":
            if status.catalog_checked_at is not None:
                return f"stale catalog {status.catalog_checked_at.isoformat()}"
            return "catalog status unknown; refresh required"
        if status.state == "requires_auth":
            return "requires /auth"
        if status.state == "credential_changed":
            return "credential changed; refresh required"
        if status.state == "failed" and status.catalog_checked_at is not None:
            return "refresh failed; using stale catalog"
        if status.state == "checked" and status.catalog_checked_at is not None:
            return f"catalog checked {status.catalog_checked_at.isoformat()}"
        if status.key_verified_at is not None:
            return "key verified"
        return None

    @classmethod
    def current_revision(cls) -> tuple[int, int]:
        """Return the cache invalidation revision without resolver or network I/O.

        Returns:
            tuple[int, int]: Authentication and public catalog-status revisions.
        """
        return cls._revision, ModelCatalogService.lifecycle_status().revision

    @classmethod
    def rows(
        cls, *, snapshot: ModelCatalogSnapshotDAO, active_model_name: str
    ) -> list[ModelSuggestionEntryDAO]:
        """Return cached rows keyed by generation, status revision and active route."""
        lifecycle = ModelCatalogService.lifecycle_status()
        key = (snapshot.generation, cls._revision, lifecycle.revision, active_model_name)
        if key != cls._key or snapshot is not cls._snapshot:
            statuses = dict(cls._statuses)
            summary = cls._catalog_status_summary()
            if summary is not None:
                statuses[ProviderName.OPENROUTER] = summary
            cls._rows = _project_rows(
                snapshot=snapshot,
                active_model_name=active_model_name,
                statuses=statuses,
                auth_types=cls._auth_types,
            )
            cls._key, cls._snapshot = key, snapshot
        return list(cls._rows)
