"""Load and project the merged model catalog for the current process."""

# Admission security is intentionally separate from the offline snapshot validator:
# callers with a supplied snapshot can validate its immutable membership without
# resolving credentials or starting I/O; runtime preparation passes no snapshot.

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Optional, Protocol

if TYPE_CHECKING:
    from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO

from config.logger import log_error
from src.agents.model_catalog.dao import (
    CatalogRefreshResultDAO,
    CatalogLifecycleStatusDAO,
    ModelAliasDAO,
    ModelCatalogCacheDAO,
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
    ProviderCatalogCacheDAO,
    ProviderCatalogTombstoneDAO,
)
from src.agents.model_catalog.discovery import (
    ModelCatalogOverrideService,
)
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.store import ModelCatalogRefreshLeaseUnavailableError, ModelCatalogStore
from src.auth.credential_dao import CredentialDAO, ProviderName, ResolvedCredentialDAO
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)
from src.integrations.openrouter.exceptions import (
    OpenRouterAPIError,
    OpenRouterAuthenticationError,
    OpenRouterDiscoveryIncompleteError,
    OpenRouterProtocolError,
)


class ModelPreparationRequiredError(ValueError):
    """The exact requested route requires catalog preparation before use."""


class OpenRouterCatalogClientProtocol(Protocol):
    """Describe the injected authenticated metadata client used by catalog refreshes."""

    async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
        """Return fingerprint-bound successful key-verification evidence."""

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Return the authenticated user-model response for conversion."""


class ModelCatalogService:
    """Load and project the merged model catalog for one process.

    The rest of the codebase calls this service instead of reading several
    independent model tables.
    """

    _lifecycle_status = CatalogLifecycleStatusDAO()
    _status_operation: ContextVar[Optional[int]] = ContextVar("catalog_status_operation", default=None)
    _status_fingerprint: ContextVar[Optional[str]] = ContextVar("catalog_status_fingerprint", default=None)

    @classmethod
    def lifecycle_status(cls) -> CatalogLifecycleStatusDAO:
        """Return immutable public evidence without resolver, persistence or network I/O."""
        return cls._lifecycle_status

    @classmethod
    def _publish_status(cls, *, status: CatalogLifecycleStatusDAO) -> None:
        """Advance status independently of entry equality at an actual lifecycle boundary."""
        operation = cls._status_operation.get()
        if operation is not None and operation != cls._current_openrouter_operation:
            return
        fingerprint = cls._status_fingerprint.get()
        if fingerprint is not None:
            current = cls._effective_fingerprint_for_resolved_credential()
            if current != fingerprint:
                status = CatalogLifecycleStatusDAO(
                    state="requires_auth" if current is None else "credential_changed"
                )
        cls._lifecycle_status = status.model_copy(update={"revision": cls._lifecycle_status.revision + 1})

    _snapshot: Optional[ModelCatalogSnapshotDAO] = None
    _key_verification: Optional[OpenRouterKeyVerificationDAO] = None
    _active_openrouter_fingerprint: Optional[str] = None
    _cached_openrouter_fingerprint: Optional[str] = None
    _rejected_openrouter_fingerprints: set[str] = set()
    _refresh_tasks: dict[tuple[ProviderName, str, int, str], asyncio.Task[CatalogRefreshResultDAO]] = {}
    _refresh_waiters: dict[asyncio.Task[CatalogRefreshResultDAO], int] = {}
    _current_openrouter_operation: int = 0
    _lease_cache_path: Optional[Path] = None
    _retiring_refresh_tasks: set[asyncio.Task[CatalogRefreshResultDAO]] = set()

    @classmethod
    def load(
        cls,
        *,
        enable_discovery: bool = False,
        now: Optional[datetime] = None,
        lifecycle_ttl: timedelta = timedelta(hours=1),
    ) -> ModelCatalogSnapshotDAO:
        """Return the merged catalog snapshot for the current process.

        Cold reads merge seed, raw cache and overrides. Warm reads project the
        last publication using only retained lifecycle provenance; they never
        resolve credentials, construct clients, or write persistence. Mismatch
        filtering does not replace the committed snapshot or its generation.

        Args:
            enable_discovery (bool): Deprecated action flag; True raises and
                directs callers to the asynchronous refresh gateway.
            now (Optional[datetime]): Aware clock for cold-cache lifecycle projection.
            lifecycle_ttl (timedelta): Positive freshness duration for persisted lifecycle evidence.

        Returns:
            ModelCatalogSnapshotDAO: Seed, cache, discovery, and override data
                merged into one consistent snapshot.
        """
        if enable_discovery:
            raise ValueError("Catalog discovery is asynchronous; call ModelCatalogService.refresh().")
        if lifecycle_ttl <= timedelta(0):
            raise ValueError("Lifecycle TTL must be positive.")
        read_time = now if now is not None else datetime.now(tz=timezone.utc)
        if read_time.tzinfo is None:
            raise ValueError("Lifecycle status time must be timezone-aware.")
        if cls._snapshot is None:
            cls._load_snapshot(
                active_openrouter_fingerprint=cls._active_openrouter_fingerprint,
                now=read_time,
                lifecycle_ttl=lifecycle_ttl,
            )
        assert cls._snapshot is not None
        return cls._visible_snapshot(snapshot=cls._snapshot)

    @classmethod
    def _visible_snapshot(cls, *, snapshot: ModelCatalogSnapshotDAO) -> ModelCatalogSnapshotDAO:
        """Hide mismatched rows for offline readers without replacing committed state.

        Args:
            snapshot: Last published immutable view, retained until successful publication.

        Returns:
            ModelCatalogSnapshotDAO: Same view for matching/unknown lifecycle provenance;
                otherwise a pure filtered projection with the committed generation.
        """
        if cls._active_openrouter_fingerprint in (None, cls._cached_openrouter_fingerprint):
            return snapshot
        entries = {
            name: entry
            for name, entry in snapshot.entries.items()
            if entry.provider is not ProviderName.OPENROUTER
        }
        return snapshot.model_copy(update={"entries": entries})

    @classmethod
    def _load_snapshot(
        cls,
        *,
        active_openrouter_fingerprint: Optional[str],
        now: datetime,
        lifecycle_ttl: timedelta,
    ) -> ModelCatalogSnapshotDAO:
        """Build and publish one offline snapshot using optional lifecycle provenance.

        WHAT: Reads only the seed, raw cache, and overrides; it never resolves a
            credential, opens a client, or writes persistence.
        WHO: ``load`` uses retained lifecycle provenance for ordinary read views;
            credential-aware refresh/admission passes its private capture directly.
        WHEN: Only at cold process reads; lifecycle captures never invalidate
            the last successful publication.

        Args:
            active_openrouter_fingerprint: Private identity captured by a prior
                lifecycle operation, if any.
            now: Aware cold-read clock used only to validate persisted timestamps.
            lifecycle_ttl: Positive freshness duration for persisted lifecycle evidence.

        Returns:
            ModelCatalogSnapshotDAO: The resulting immutable offline projection.
        """
        seed_snapshot: ModelCatalogSnapshotDAO = SeedModelCatalog.load()
        provider_cache: Optional[ModelCatalogCacheDAO] = ModelCatalogStore.load_provider_cache()
        cache_fingerprint: Optional[str] = cls._openrouter_cache_fingerprint(cache=provider_cache)
        merged_snapshot: ModelCatalogSnapshotDAO = cls._merge_seed_and_provider_cache(
            seed_snapshot=seed_snapshot,
            provider_cache=provider_cache,
            active_openrouter_fingerprint=active_openrouter_fingerprint or cache_fingerprint,
        )
        cls._cached_openrouter_fingerprint = cache_fingerprint
        cls._snapshot = cls._apply_manual_overrides(snapshot=merged_snapshot)
        cls._hydrate_cold_lifecycle_status(
            slice=cls._openrouter_slice(cache=provider_cache), now=now, lifecycle_ttl=lifecycle_ttl
        )
        return cls._snapshot

    @classmethod
    def _hydrate_cold_lifecycle_status(
        cls,
        *,
        slice: Optional[ProviderCatalogCacheDAO],
        now: datetime,
        lifecycle_ttl: timedelta,
    ) -> None:
        """Separate historical cache evidence from lifecycle-qualified current status.

        Args:
            slice: Raw offline OpenRouter provider cache slice, if persisted.
            now: Aware cold-read clock.
            lifecycle_ttl: Positive maximum age for both persisted timestamps.
        """
        if cls._lifecycle_status.state != "unknown" or slice is None:
            return
        key_verified_at = cls._parse_lifecycle_timestamp(value=slice.key_verified_at, now=now)
        catalog_checked_at = cls._parse_lifecycle_timestamp(value=slice.last_success_at, now=now)
        if key_verified_at is None and catalog_checked_at is None:
            return
        status = CatalogLifecycleStatusDAO(
            state="historical",
            key_verified_at=key_verified_at,
            catalog_checked_at=catalog_checked_at,
        )
        if not cls._active_openrouter_fingerprint or (
            cls._active_openrouter_fingerprint != slice.credential_fingerprint
        ):
            cls._publish_status(status=status)
            return
        fresh = all(
            recorded_at is not None and now - recorded_at < lifecycle_ttl
            for recorded_at in (key_verified_at, catalog_checked_at)
        )
        cls._publish_status(
            status=CatalogLifecycleStatusDAO(
                state="checked" if fresh else "stale",
                key_verified_at=key_verified_at,
                catalog_checked_at=catalog_checked_at,
            )
        )

    @staticmethod
    def _parse_lifecycle_timestamp(*, value: Optional[str], now: datetime) -> Optional[datetime]:
        """Preserve valid historical success times independently of freshness."""
        if value is None:
            return None
        try:
            recorded_at = datetime.fromisoformat(value)
        except ValueError:
            return None
        if recorded_at.tzinfo is None:
            return None
        normalized_at = recorded_at.astimezone(timezone.utc)
        age = now.astimezone(timezone.utc) - normalized_at
        if age >= timedelta(0):
            return normalized_at
        return None

    @classmethod
    async def prepare_models(
        cls,
        *,
        model_names: tuple[str, ...],
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
        now: Optional[datetime] = None,
    ) -> ModelCatalogSnapshotDAO:
        """Validate credential evidence and route membership before new execution.

        Session preparation and selection call this before adopting any state.
        Synchronous catalog reads remain a separate, offline browsing surface.

        Args:
            model_names: Exact configured names or direct-provider aliases.
            snapshot: Optional pinned generation; otherwise capture current catalog.
            now: Aware admission clock; defaults to current UTC time.

        Returns:
            ModelCatalogSnapshotDAO: Immutable generation containing every admitted
                entry after effective-credential validation.

        Raises:
            ModelPreparationRequiredError: A qualified route is absent.
            ValueError: A direct-provider name is unknown.
        """
        uses_supplied_snapshot: bool = snapshot is not None
        snapshot = snapshot if snapshot is not None else cls.load()
        if cls._requires_credential_aware_admission(
            model_names=model_names,
            uses_supplied_snapshot=uses_supplied_snapshot,
        ):
            snapshot = await cls._prepare_openrouter_admission(
                snapshot=snapshot,
                model_names=model_names,
            )
        admission_time = now if now is not None else datetime.now(tz=timezone.utc)
        if admission_time.tzinfo is None:
            raise ValueError("Admission time must be timezone-aware.")
        for model_name in model_names:
            try:
                entry = cls.entry_for_model(model_name=model_name, snapshot=snapshot)
                cls._validate_admission(entry=entry, now=admission_time)
            except ValueError as error:
                if model_name.startswith("openrouter:"):
                    raise ModelPreparationRequiredError(
                        f"Catalog preparation required for '{model_name}'; "
                        "unsupported variant; choose a catalog entry or /model refresh"
                    ) from error
                raise
        return snapshot

    @staticmethod
    def _requires_credential_aware_admission(
        *,
        model_names: tuple[str, ...],
        uses_supplied_snapshot: bool,
    ) -> bool:
        """Choose the runtime admission gateway without contaminating offline validation.

        WHAT: Identifies unpinned OpenRouter runtime requests that must establish
            effective-credential evidence before use.
        WHO: ``prepare_models`` calls this before its pure membership loop.
        WHEN: Only at admission; a caller-provided immutable snapshot is already
            a pinned offline/read-model input and must not resolve credentials.

        Args:
            model_names (tuple[str, ...]): Exact routes the caller wants to validate.
            uses_supplied_snapshot (bool): Whether the caller supplied the immutable
                snapshot rather than requesting runtime admission from current state.

        Returns:
            bool: Whether credential-aware asynchronous admission is required.
        """
        return not uses_supplied_snapshot and any(name.startswith("openrouter:") for name in model_names)

    @classmethod
    async def _prepare_openrouter_admission(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        model_names: tuple[str, ...],
    ) -> ModelCatalogSnapshotDAO:
        """Require current effective-key evidence before a session can adopt a catalog.

        Args:
            snapshot: Candidate read view, which alone is not authentication evidence.

        Returns:
            ModelCatalogSnapshotDAO: The authenticated candidate or refreshed view.

        Raises:
            ModelPreparationRequiredError: Credentials cannot authorize new execution.
        """
        fingerprint = cls._effective_fingerprint_for_resolved_credential()
        if fingerprint is None:
            cls._current_openrouter_operation += 1
            cls._key_verification = None
            cls._publish_status(status=CatalogLifecycleStatusDAO(state="requires_auth"))
            raise ModelPreparationRequiredError("OpenRouter credentials are unavailable; run /auth.")
        if cls._active_openrouter_fingerprint not in (None, fingerprint):
            cls._current_openrouter_operation += 1
            cls._key_verification = None
            cls._publish_status(status=CatalogLifecycleStatusDAO(state="credential_changed"))
        cls._active_openrouter_fingerprint = fingerprint
        snapshot = cls.load()
        cache = await asyncio.to_thread(ModelCatalogStore.load_provider_cache)
        existing = cls._openrouter_slice(cache=cache)
        snapshot = await cls._adopt_current_openrouter_slice(
            snapshot=snapshot,
            cache=cache,
            fingerprint=fingerprint,
        )
        route_membership_is_present: bool = cls._all_openrouter_routes_are_present(
            snapshot=snapshot,
            model_names=model_names,
        )
        if (
            cls._admission_evidence_is_usable(slice=existing, fingerprint=fingerprint)
            and route_membership_is_present
        ):
            return snapshot
        result = await cls.refresh(
            provider=ProviderName.OPENROUTER,
            force=not route_membership_is_present,
        )
        refreshed_snapshot: ModelCatalogSnapshotDAO = cls.load()
        if cls._effective_fingerprint_for_resolved_credential() != fingerprint:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        if result.status in {"fresh", "refreshed"} and cls._all_openrouter_routes_are_present(
            snapshot=refreshed_snapshot,
            model_names=model_names,
        ):
            return refreshed_snapshot
        if cls._stale_same_key_membership_is_admissible(
            snapshot=refreshed_snapshot,
            model_names=model_names,
            fingerprint=fingerprint,
        ):
            return refreshed_snapshot
        raise ModelPreparationRequiredError(
            "OpenRouter verification is unavailable; run /auth or /model refresh."
        )

    @classmethod
    async def _adopt_current_openrouter_slice(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        cache: Optional[ModelCatalogCacheDAO],
        fingerprint: str,
    ) -> ModelCatalogSnapshotDAO:
        """Adopt a fresh same-key durable catalog slice before route admission.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Current in-memory read view.
            cache (Optional[ModelCatalogCacheDAO]): Newly read durable provider cache.
            fingerprint (str): Effective credential identity for this admission.

        Returns:
            ModelCatalogSnapshotDAO: The existing snapshot or a coherent projection
            built from the durable matching slice.
        """
        durable_fingerprint = cls._openrouter_cache_fingerprint(cache=cache)
        if durable_fingerprint != fingerprint:
            return snapshot
        if cache is None:
            return snapshot
        current_slice = cls._openrouter_slice(cache=cache)
        snapshot_slice = cls._openrouter_slice(
            cache=ModelCatalogCacheDAO(
                provider_slices=[
                    ProviderCatalogCacheDAO(
                        provider=ProviderName.OPENROUTER,
                        credential_fingerprint=cls._cached_openrouter_fingerprint,
                        entries=[
                            entry
                            for entry in snapshot.entries.values()
                            if entry.provider is ProviderName.OPENROUTER
                        ],
                    )
                ]
            )
        )
        if cls._provider_slices_match(left=current_slice, right=snapshot_slice):
            return await cls._revalidate_unchanged_admission_snapshot(
                snapshot=snapshot,
                fingerprint=fingerprint,
                cache=cache,
            )
        candidate = await cls._build_publication_candidate(cache=cache)
        return await cls._publish_admission_candidate_if_current(
            candidate=candidate,
            fingerprint=fingerprint,
            cache=cache,
        )

    @classmethod
    async def _revalidate_unchanged_admission_snapshot(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        fingerprint: str,
        cache: ModelCatalogCacheDAO,
    ) -> ModelCatalogSnapshotDAO:
        """Revalidate an equal durable slice after the initial asynchronous admission read.

        WHAT: Confirms that the read whose entries matched the supplied view did
            not become stale before control returned to admission.
        WHO: ``_adopt_current_openrouter_slice`` calls this for its equal-slice
            fast path.
        WHEN: After every asynchronous cache read that could otherwise return a
            stale unpinned snapshot to the next prompt admission.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Snapshot that matched the first durable read.
            fingerprint (str): Effective OpenRouter credential identity for this admission.
            cache (ModelCatalogCacheDAO): First durable cache value that matched ``snapshot``.

        Returns:
            ModelCatalogSnapshotDAO: The current matching snapshot or a freshly adopted view.

        Raises:
            ModelPreparationRequiredError: If the effective credential changes during revalidation.
        """
        if cls._effective_fingerprint_for_resolved_credential() != fingerprint:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        observed_snapshot = cls._snapshot
        current_cache = await asyncio.to_thread(ModelCatalogStore.load_provider_cache)
        if cls._effective_fingerprint_for_resolved_credential() != fingerprint:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        if cls._snapshot is not observed_snapshot:
            return cls.load()
        if current_cache == cache:
            return snapshot
        return await cls._adopt_current_openrouter_slice(
            snapshot=cls.load(),
            cache=current_cache,
            fingerprint=fingerprint,
        )

    @classmethod
    async def _publish_admission_candidate_if_current(
        cls,
        *,
        candidate: ModelCatalogSnapshotDAO,
        fingerprint: str,
        cache: ModelCatalogCacheDAO,
    ) -> ModelCatalogSnapshotDAO:
        """Publish an admission candidate only while its durable identity remains current.

        WHAT: Re-reads the effective credential and raw cache after asynchronous
            candidate construction, then retries adoption when a newer publication won.
        WHO: ``_adopt_current_openrouter_slice`` calls this at the admission boundary.
        WHEN: Immediately before a global catalog reference swap, so an old candidate
            cannot overwrite a newer same-process or external publication.

        Args:
            candidate (ModelCatalogSnapshotDAO): Projection built from one durable cache read.
            fingerprint (str): Effective credential identity captured for this admission.
            cache (ModelCatalogCacheDAO): Durable cache used to construct ``candidate``.

        Returns:
            ModelCatalogSnapshotDAO: The safely published current candidate or a retry result.

        Raises:
            ModelPreparationRequiredError: If the effective credential changes while adoption waits.
        """
        current_fingerprint = cls._effective_fingerprint_for_resolved_credential()
        if current_fingerprint != fingerprint:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        observed_snapshot = cls._snapshot
        current_cache = await asyncio.to_thread(ModelCatalogStore.load_provider_cache)
        if cls._effective_fingerprint_for_resolved_credential() != fingerprint:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        if cls._snapshot is not observed_snapshot:
            return cls.load()
        if current_cache == cache:
            cls._publish_candidate(candidate=candidate, fingerprint=fingerprint)
            return cls.load()
        return await cls._adopt_current_openrouter_slice(
            snapshot=cls.load(),
            cache=current_cache,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _provider_slices_match(
        *,
        left: Optional[ProviderCatalogCacheDAO],
        right: Optional[ProviderCatalogCacheDAO],
    ) -> bool:
        """Compare the provider membership/capability data used by admission.

        Args:
            left (Optional[ProviderCatalogCacheDAO]): Fresh durable provider slice.
            right (Optional[ProviderCatalogCacheDAO]): Current in-memory provider projection.

        Returns:
            bool: Whether both slices carry identical admission-relevant entries.
        """
        if left is None or right is None:
            return left is right
        return left.entries == right.entries

    @classmethod
    def _stale_same_key_membership_is_admissible(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        model_names: tuple[str, ...],
        fingerprint: str,
    ) -> bool:
        """Allow a verified same-key stale listing after a transient list failure.

        WHAT: Separates credential verification freshness from listing freshness.
        WHO: ``_prepare_openrouter_admission`` calls this after its one refresh attempt.
        WHEN: A transient listing failure must preserve an already verified, exact
            same-key route rather than converting a safe stale cache into an outage.

        Args:
            snapshot: Current offline projection after the attempted refresh.
            model_names: Exact routes this admission must validate.
            fingerprint: Effective private credential identity for this admission.

        Returns:
            bool: Whether the cache retains fresh matching key evidence and at
            least one OpenRouter route. Explicitly rejected fingerprints remain blocked.
        """
        if fingerprint in cls._rejected_openrouter_fingerprints:
            return False
        cache: Optional[ModelCatalogCacheDAO] = ModelCatalogStore.load_provider_cache()
        provider_slice: Optional[ProviderCatalogCacheDAO] = cls._openrouter_slice(cache=cache)
        evidence = cls._usable_key_verification(
            evidence=cls._key_verification or cls._key_verification_from_slice(slice=provider_slice),
            fingerprint=fingerprint,
        )
        return evidence is not None and cls._all_openrouter_routes_are_present(
            snapshot=snapshot,
            model_names=model_names,
        )

    @staticmethod
    def _all_openrouter_routes_are_present(
        *, snapshot: ModelCatalogSnapshotDAO, model_names: tuple[str, ...]
    ) -> bool:
        """Require exact membership for every requested OpenRouter route.

        Args:
            snapshot: Candidate catalog view for the current admission.
            model_names: Full configured direct-route or pool-member set.

        Returns:
            bool: Whether every OpenRouter route in the request is present.
        """
        return all(
            not model_name.startswith("openrouter:") or model_name in snapshot.entries
            for model_name in model_names
        )

    @classmethod
    def _openrouter_cache_fingerprint(cls, *, cache: Optional[ModelCatalogCacheDAO]) -> Optional[str]:
        """Return private persisted OpenRouter provenance without resolving credentials.

        Args:
            cache: Raw provider cache already read by the offline snapshot owner.

        Returns:
            Optional[str]: Persisted OpenRouter fingerprint when exactly available.
        """
        provider_slice: Optional[ProviderCatalogCacheDAO] = cls._openrouter_slice(cache=cache)
        if provider_slice is None:
            return None
        return provider_slice.credential_fingerprint

    @staticmethod
    def _openrouter_slice(*, cache: Optional[ModelCatalogCacheDAO]) -> Optional[ProviderCatalogCacheDAO]:
        """Select the sole raw OpenRouter slice without mutating persisted state."""
        if cache is None:
            return None
        return next(
            (item for item in cache.provider_slices if item.provider is ProviderName.OPENROUTER), None
        )

    @classmethod
    def _admission_evidence_is_usable(
        cls, *, slice: Optional[ProviderCatalogCacheDAO], fingerprint: str
    ) -> bool:
        """Reject stale or explicitly rejected verification independently of listing age."""
        if fingerprint in cls._rejected_openrouter_fingerprints:
            return False
        evidence = cls._usable_key_verification(
            evidence=cls._key_verification_from_slice(slice=slice), fingerprint=fingerprint
        )
        return evidence is not None and cls._provider_slice_is_fresh(slice=slice, fingerprint=fingerprint)

    @classmethod
    def _validate_admission(cls, *, entry: ModelCatalogEntryDAO, now: datetime) -> None:
        """Reject unavailable records and re-evaluate advertised expiry offline."""
        if entry.availability != "available":
            raise ValueError("Model is unavailable or ineligible.")
        if entry.provider is not ProviderName.OPENROUTER:
            return
        from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter

        capabilities = entry.capabilities
        if capabilities is None:
            raise ValueError("OpenRouter capability evidence is missing.")
        if not (
            "text" in capabilities.input_modalities
            and "text" in capabilities.output_modalities
            and "tools" in capabilities.supported_parameters
        ):
            raise ValueError("OpenRouter text/tool capability evidence is missing.")
        if OpenRouterCatalogConverter.is_expired(expires_at=capabilities.expires_at, now=now):
            raise ValueError("OpenRouter route has expired.")

    @classmethod
    async def refresh(
        cls,
        *,
        provider: ProviderName,
        force: bool = False,
        resolved_credential: Optional[ResolvedCredentialDAO] = None,
        key_verification: Optional[OpenRouterKeyVerificationDAO] = None,
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]] = None,
        cache_path: Optional[Path] = None,
    ) -> CatalogRefreshResultDAO:
        """Refresh one provider slice and publish only after durable persistence.

        Args:
            provider (ProviderName): Provider slice to refresh.
            force (bool): Whether to bypass a same-key fresh slice.
            resolved_credential (Optional[ResolvedCredentialDAO]): Captured credential seam.
            key_verification (Optional[OpenRouterKeyVerificationDAO]): Matching prior verification.
            client_factory (Optional[Callable[[CredentialDAO], OpenRouterAPIClient]]): Injected client builder.
            cache_path (Optional[Path]): Explicit private test cache path.

        Returns:
            CatalogRefreshResultDAO: Safe refresh outcome.
        """
        from src.agents.model_catalog.dao import ProviderCatalogCacheDAO

        if provider is not ProviderName.OPENROUTER:
            return CatalogRefreshResultDAO(
                status="failed",
                catalog_generation=cls._generation(),
                safe_message="Provider refresh is unavailable.",
            )
        supplied_credential: bool = resolved_credential is not None
        effective: Optional[ResolvedCredentialDAO] = (
            resolved_credential or CredentialResolver.resolve_with_source(provider=provider)
        )
        if effective is None:
            cls._current_openrouter_operation += 1
            cls._key_verification = None
            cls._publish_status(status=CatalogLifecycleStatusDAO(state="requires_auth"))
            return CatalogRefreshResultDAO(
                status="failed",
                catalog_generation=cls._generation(),
                safe_message="OpenRouter credentials are unavailable.",
            )
        fingerprint: str = credential_fingerprint(access_token=effective.credential.access_token)
        task_key = (
            provider,
            fingerprint,
            id(asyncio.get_running_loop()),
            str(cache_path) if cache_path else "default",
        )
        task = cls._refresh_tasks.get(task_key)
        if task is None:
            cls._current_openrouter_operation += 1
            if cls._active_openrouter_fingerprint not in (None, fingerprint):
                cls._publish_status(status=CatalogLifecycleStatusDAO(state="credential_changed"))
            cls._active_openrouter_fingerprint = fingerprint
            task = asyncio.create_task(
                cls._refresh_openrouter(
                    effective=effective,
                    fingerprint=fingerprint,
                    force=force,
                    credential_was_supplied=supplied_credential,
                    supplied_effective_fingerprint=cls._effective_fingerprint_for_resolved_credential(),
                    key_verification=key_verification,
                    client_factory=client_factory,
                    cache_path=cache_path,
                    operation_token=cls._current_openrouter_operation,
                )
            )
            cls._refresh_tasks[task_key] = task
            task.add_done_callback(cls._build_refresh_task_cleanup_callback(key=task_key))
        cls._refresh_waiters[task] = cls._refresh_waiters.get(task, 0) + 1
        try:
            result = await asyncio.shield(task)
            return result
        except asyncio.CancelledError:
            if client_factory is None and cls._refresh_waiters.get(task) == 1:
                await cls._cancel_refresh_owner(task=task)
            raise
        except (
            ModelCatalogRefreshLeaseUnavailableError,
            OpenRouterAPIError,
            OpenRouterProtocolError,
            OpenRouterDiscoveryIncompleteError,
            OSError,
            RuntimeError,
            TimeoutError,
            ValueError,
        ):
            return CatalogRefreshResultDAO(
                status="failed",
                catalog_generation=cls._generation(),
                safe_message="OpenRouter catalog refresh is unavailable.",
            )

        finally:
            remaining = cls._refresh_waiters[task] - 1
            if remaining:
                cls._refresh_waiters[task] = remaining
            else:
                cls._refresh_waiters.pop(task)

    @classmethod
    def _publish_refresh_failure(cls, *, status: str) -> None:
        """Publish fixed failure facts and clear evidence invalidated by rejection.

        Args:
            status: Safe terminal lifecycle outcome for the current owner.
        """
        previous = cls._lifecycle_status
        if (
            status == "credential_changed"
            or cls._active_openrouter_fingerprint in cls._rejected_openrouter_fingerprints
        ):
            previous = CatalogLifecycleStatusDAO()
        cls._publish_status(status=previous.model_copy(update={"state": status}))

    @classmethod
    def _publish_checked_status(cls, *, slice: ProviderCatalogCacheDAO, operation_token: int) -> None:
        """Project timestamps only when this refresh remains the current operation.

        Args:
            slice: Successfully published raw provider slice.
            operation_token: Monotonic refresh identity captured before the owner starts.
        """
        if operation_token != cls._current_openrouter_operation:
            return
        cls._publish_status(
            status=CatalogLifecycleStatusDAO.model_validate(
                {
                    "state": "checked",
                    "key_verified_at": slice.key_verified_at,
                    "catalog_checked_at": slice.last_success_at,
                }
            )
        )

    @staticmethod
    async def _cancel_refresh_owner(*, task: asyncio.Task[CatalogRefreshResultDAO]) -> None:
        """Cancel and drain a service-owned refresh before propagating caller cancellation.

        WHAT: Ensures an owned metadata client leaves its async context before
            the cancelling caller regains control.
        WHO: ``refresh`` invokes this only when its outer waiter is cancelled.
        WHEN: The last default-client waiter is cancelled. A waiter leaving a
            shared flight with other subscribers never invokes this cleanup.

        Args:
            task (asyncio.Task[CatalogRefreshResultDAO]): Shared refresh owner to drain.
        """
        task.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        await asyncio.gather(task, return_exceptions=True)

    @classmethod
    def _build_refresh_task_cleanup_callback(
        cls,
        *,
        key: tuple[ProviderName, str, int, str],
    ) -> Callable[[asyncio.Task[CatalogRefreshResultDAO]], None]:
        """Build the typed terminal callback for one registered refresh flight.

        WHAT: Captures a task key without an untyped inline callback.
        WHO: Called by ``refresh()`` immediately after owner registration.
        WHEN: The returned callback runs when that owner reaches a terminal state.

        Args:
            key (tuple[ProviderName, str, int, str]): Identity of the shared flight.

        Returns:
            Callable[[asyncio.Task[CatalogRefreshResultDAO]], None]: Callback that
                conditionally removes only its own completed task.
        """

        def discard(completed: asyncio.Task[CatalogRefreshResultDAO]) -> None:
            """Discard this owner only if a newer owner did not replace it."""
            cls._discard_completed_refresh_task(key=key, completed=completed)

        return discard

    @classmethod
    def _discard_completed_refresh_task(
        cls,
        *,
        key: tuple[ProviderName, str, int, str],
        completed: asyncio.Task[CatalogRefreshResultDAO],
    ) -> None:
        """Remove a completed owner only when it is still the registered flight.

        WHAT: Protects a replacement refresh registered after ``reset()`` from a
            cancelled predecessor's delayed done callback.
        WHO: Registered by ``refresh()`` for every shared in-process owner.
        WHEN: Runs when the owner task reaches a terminal state.

        Args:
            key (tuple[ProviderName, str, int, str]): Identity of the coalesced flight.
            completed (asyncio.Task[CatalogRefreshResultDAO]): Owner that just completed.
        """
        if cls._refresh_tasks.get(key) is completed:
            cls._refresh_tasks.pop(key, None)

    @classmethod
    async def _refresh_openrouter(
        cls,
        *,
        effective: ResolvedCredentialDAO,
        fingerprint: str,
        force: bool,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]],
        cache_path: Optional[Path],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Execute the coalesced OpenRouter refresh owner path."""
        token = cls._status_operation.set(operation_token)
        fingerprint_token = cls._status_fingerprint.set(fingerprint)
        try:
            result = await cls._refresh_openrouter_owned(
                effective=effective,
                fingerprint=fingerprint,
                force=force,
                credential_was_supplied=credential_was_supplied,
                supplied_effective_fingerprint=supplied_effective_fingerprint,
                key_verification=key_verification,
                client_factory=client_factory,
                cache_path=cache_path,
                operation_token=operation_token,
            )
            if result.status in {"failed", "credential_changed"}:
                cls._publish_refresh_failure(status=result.status)
            return result
        except Exception:
            cls._publish_refresh_failure(status="failed")
            raise
        finally:
            cls._status_fingerprint.reset(fingerprint_token)
            cls._status_operation.reset(token)

    @classmethod
    async def _refresh_openrouter_owned(
        cls,
        *,
        effective: ResolvedCredentialDAO,
        fingerprint: str,
        force: bool,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]],
        cache_path: Optional[Path],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Acquire one lease and delegate the complete refresh lifecycle.

        WHAT: Captures pre-lease cache state, then runs the existing catalog refresh
            lifecycle while the store lease and deadline remain active.
        WHO: ``_refresh_openrouter`` calls this after single-flight coalescing.
        WHEN: Runs once per coalesced owner; helpers preserve freshness, verification,
            conversion, reconciliation, persistence, and publication ordering.

        Args:
            effective: Credential captured for this owner.
            fingerprint: Private identity of the captured credential.
            force: Whether a fresh cache may be bypassed.
            credential_was_supplied: Whether an auth flow supplied the credential.
            supplied_effective_fingerprint: Resolver identity captured at admission.
            key_verification: Optional matching verification evidence.
            client_factory: Optional injected metadata-client constructor.
            cache_path: Optional private cache destination.
            operation_token: Monotonic lifecycle identity.

        Returns:
            CatalogRefreshResultDAO: Safe lifecycle outcome from the leased helper.
        """
        observed_cache = await asyncio.to_thread(
            ModelCatalogStore.load_provider_cache, override_path=cache_path
        )
        async with asyncio.timeout(30.0), ModelCatalogStore.refresh_lease(cache_path=cache_path):
            return await cls._refresh_openrouter_under_lease(
                observed_cache=observed_cache,
                effective=effective,
                fingerprint=fingerprint,
                force=force,
                credential_was_supplied=credential_was_supplied,
                supplied_effective_fingerprint=supplied_effective_fingerprint,
                key_verification=key_verification,
                client_factory=client_factory,
                cache_path=cache_path,
                operation_token=operation_token,
            )

    @classmethod
    async def _refresh_openrouter_under_lease(
        cls,
        *,
        observed_cache: Optional[ModelCatalogCacheDAO],
        effective: ResolvedCredentialDAO,
        fingerprint: str,
        force: bool,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]],
        cache_path: Optional[Path],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Run freshness, discovery, commit, and publication under an acquired lease.

        WHAT: Coordinates lifecycle steps without duplicating their decisions.
        WHO: ``_refresh_openrouter_owned`` calls this while it owns the store lease.
        WHEN: After the lease re-reads current cache state and before it releases the
            lease, so a committed candidate is saved before publication.

        Args:
            observed_cache: Cache read before lease acquisition.
            effective: Credential captured for this owner.
            fingerprint: Private identity of the captured credential.
            force: Whether a fresh cache may be bypassed.
            credential_was_supplied: Whether an auth flow supplied the credential.
            supplied_effective_fingerprint: Resolver identity captured at admission.
            key_verification: Optional matching verification evidence.
            client_factory: Optional injected metadata-client constructor.
            cache_path: Optional private cache destination.
            operation_token: Monotonic lifecycle identity.

        Returns:
            CatalogRefreshResultDAO: Safe result of the selected lifecycle branch.
        """
        cache = await cls._load_refresh_cache(cache_path=cache_path)
        existing = cls._openrouter_slice(cache=cache)
        if cls._can_publish_fresh_cache(
            observed_cache=observed_cache,
            existing=existing,
            fingerprint=fingerprint,
            force=force,
        ):
            return await cls._publish_fresh_cache(
                cache=cache,
                existing=existing,
                fingerprint=fingerprint,
                credential_was_supplied=credential_was_supplied,
                supplied_effective_fingerprint=supplied_effective_fingerprint,
                operation_token=operation_token,
            )
        return await cls._refresh_stale_openrouter_cache(
            existing=existing,
            effective=effective,
            fingerprint=fingerprint,
            force=force,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
            key_verification=key_verification,
            client_factory=client_factory,
            cache_path=cache_path,
            operation_token=operation_token,
        )

    @classmethod
    async def _load_refresh_cache(cls, *, cache_path: Optional[Path]) -> ModelCatalogCacheDAO:
        """Load the current raw cache after lease acquisition.

        WHAT: Reads the replacement envelope used by the lease owner.
        WHO: ``_refresh_openrouter_under_lease`` calls this before freshness checks.
        WHEN: Runs inside the lease so the lifecycle evaluates the latest persisted
            raw slice rather than its pre-wait observation.

        Args:
            cache_path: Optional private cache destination.

        Returns:
            ModelCatalogCacheDAO: Current raw cache or an empty replacement envelope.
        """
        loaded_cache = await asyncio.to_thread(
            ModelCatalogStore.load_provider_cache, override_path=cache_path
        )
        return loaded_cache or ModelCatalogCacheDAO()

    @classmethod
    def _can_publish_fresh_cache(
        cls,
        *,
        observed_cache: Optional[ModelCatalogCacheDAO],
        existing: Optional[ProviderCatalogCacheDAO],
        fingerprint: str,
        force: bool,
    ) -> bool:
        """Choose whether existing same-key evidence may be republished.

        Args:
            observed_cache: Cache state observed before lease acquisition.
            existing: Current OpenRouter raw slice under the lease.
            fingerprint: Private identity of the captured credential.
            force: Whether the caller requires fresh discovery unless another owner won.

        Returns:
            bool: Whether the fresh-cache publication branch is safe.
        """
        newer = cls._has_newer_success(observed=observed_cache, existing=existing, fingerprint=fingerprint)
        return (not force or newer) and cls._admission_evidence_is_usable(
            slice=existing, fingerprint=fingerprint
        )

    @classmethod
    async def _publish_fresh_cache(
        cls,
        *,
        cache: ModelCatalogCacheDAO,
        existing: Optional[ProviderCatalogCacheDAO],
        fingerprint: str,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Publish a verified current cache without changing durable bytes.

        Args:
            cache: Raw cache that already contains the verified slice.
            existing: Matching verified OpenRouter slice.
            fingerprint: Private identity of the captured credential.
            credential_was_supplied: Whether an auth flow supplied the credential.
            supplied_effective_fingerprint: Resolver identity captured at admission.
            operation_token: Monotonic lifecycle identity.

        Returns:
            CatalogRefreshResultDAO: Fresh or credential-changed safe outcome.
        """
        candidate = await cls._build_publication_candidate(cache=cache)
        if cls._effective_fingerprint_changed(
            fingerprint=fingerprint,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
        ):
            return cls._credential_changed_result()
        assert existing is not None
        cls._publish_candidate(candidate=candidate, fingerprint=fingerprint)
        cls._publish_checked_status(slice=existing, operation_token=operation_token)
        return CatalogRefreshResultDAO(
            status="fresh",
            catalog_generation=cls._generation(),
            safe_message="OpenRouter catalog is current.",
        )

    @classmethod
    async def _refresh_stale_openrouter_cache(
        cls,
        *,
        existing: Optional[ProviderCatalogCacheDAO],
        effective: ResolvedCredentialDAO,
        fingerprint: str,
        force: bool,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]],
        cache_path: Optional[Path],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Verify, convert, reconcile, persist, and publish a stale OpenRouter slice.

        Args:
            existing: Current OpenRouter raw slice, if any.
            effective: Credential captured for this owner.
            fingerprint: Private identity of the captured credential.
            force: Whether existing evidence may be reused for verification.
            credential_was_supplied: Whether an auth flow supplied the credential.
            supplied_effective_fingerprint: Resolver identity captured at admission.
            key_verification: Optional matching verification evidence.
            client_factory: Optional injected metadata-client constructor.
            cache_path: Optional private cache destination.
            operation_token: Monotonic lifecycle identity.

        Returns:
            CatalogRefreshResultDAO: Safe result after the replacement lifecycle.
        """
        if cls._key_verification_mismatches(key_verification=key_verification, fingerprint=fingerprint):
            return cls._credential_changed_result()
        evidence, response = await cls._discover_refresh_response(
            effective=effective,
            fingerprint=fingerprint,
            key_verification=key_verification,
            existing=existing,
            force=force,
            client_factory=client_factory,
        )
        if evidence.credential_fingerprint != fingerprint:
            return cls._credential_changed_result()
        refreshed_cache = await cls._build_refreshed_cache(
            existing=existing,
            fingerprint=fingerprint,
            evidence=evidence,
            response=response,
        )
        if refreshed_cache is None:
            return CatalogRefreshResultDAO(
                status="failed",
                catalog_generation=cls._generation(),
                safe_message="OpenRouter catalog refresh was incomplete.",
            )
        return await cls._persist_and_publish_refreshed_cache(
            cache=refreshed_cache,
            fingerprint=fingerprint,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
            cache_path=cache_path,
            operation_token=operation_token,
        )

    @staticmethod
    def _key_verification_mismatches(
        *, key_verification: Optional[OpenRouterKeyVerificationDAO], fingerprint: str
    ) -> bool:
        """Return whether supplied verification belongs to another credential.

        Args:
            key_verification: Optional auth-flow verification evidence.
            fingerprint: Private identity of the refresh credential.

        Returns:
            bool: Whether supplied evidence cannot authorize this refresh.
        """
        return key_verification is not None and key_verification.credential_fingerprint != fingerprint

    @classmethod
    async def _discover_refresh_response(
        cls,
        *,
        effective: ResolvedCredentialDAO,
        fingerprint: str,
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        existing: Optional[ProviderCatalogCacheDAO],
        force: bool,
        client_factory: Optional[Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]],
    ) -> tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
        """Construct one client and fetch matching verification plus metadata.

        Args:
            effective: Credential captured for this owner.
            fingerprint: Private identity of the captured credential.
            key_verification: Optional matching auth-flow verification evidence.
            existing: Current OpenRouter raw slice, if any.
            force: Whether existing evidence may be reused.
            client_factory: Optional injected metadata-client constructor.

        Returns:
            tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
                Verified evidence and the complete authenticated response.
        """
        client = (client_factory or (lambda credential: OpenRouterAPIClient(credential=credential)))(
            effective.credential
        )
        return await cls._discover_openrouter_models(
            client=client,
            client_is_service_owned=client_factory is None,
            fingerprint=fingerprint,
            key_verification=key_verification,
            existing=existing,
            force=force,
        )

    @classmethod
    async def _build_refreshed_cache(
        cls,
        *,
        existing: Optional[ProviderCatalogCacheDAO],
        fingerprint: str,
        evidence: OpenRouterKeyVerificationDAO,
        response: OpenRouterModelsResponseDAO,
    ) -> Optional[ModelCatalogCacheDAO]:
        """Convert and reconcile a complete metadata response into a raw replacement cache.

        Args:
            existing: Current OpenRouter raw slice, if any.
            fingerprint: Private identity of the captured credential.
            evidence: Matching successful key-verification evidence.
            response: Authenticated metadata response to convert.

        Returns:
            Optional[ModelCatalogCacheDAO]: Complete raw replacement cache, or None
                when conversion reports incomplete metadata.
        """
        from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter

        result = await asyncio.to_thread(
            OpenRouterCatalogConverter.invoke, response=response, now=datetime.now(tz=timezone.utc)
        )
        if not result.complete:
            return None
        refreshed_slice = cls._reconcile_openrouter_slice(
            existing=existing,
            fingerprint=fingerprint,
            evidence=evidence,
            entries=result.entries,
        )
        return ModelCatalogCacheDAO(provider_slices=[refreshed_slice])

    @classmethod
    async def _persist_and_publish_refreshed_cache(
        cls,
        *,
        cache: ModelCatalogCacheDAO,
        fingerprint: str,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
        cache_path: Optional[Path],
        operation_token: int,
    ) -> CatalogRefreshResultDAO:
        """Recheck identity, durably save a replacement cache, then publish it.

        Args:
            cache: Complete raw replacement cache.
            fingerprint: Private identity of the captured credential.
            credential_was_supplied: Whether an auth flow supplied the credential.
            supplied_effective_fingerprint: Resolver identity captured at admission.
            cache_path: Optional private cache destination.
            operation_token: Monotonic lifecycle identity.

        Returns:
            CatalogRefreshResultDAO: Refreshed, failed, or credential-changed outcome.
        """
        if cls._effective_fingerprint_changed(
            fingerprint=fingerprint,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
        ):
            return cls._credential_changed_result()
        candidate = await cls._build_publication_candidate(cache=cache)
        if cls._effective_fingerprint_changed(
            fingerprint=fingerprint,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
        ):
            return cls._credential_changed_result()
        outcome = await cls._write_cache_under_lease(cache=cache, cache_path=cache_path)
        if not outcome.committed:
            return CatalogRefreshResultDAO(
                status="failed",
                catalog_generation=cls._generation(),
                safe_message="OpenRouter catalog could not be saved.",
            )
        if cls._effective_fingerprint_changed(
            fingerprint=fingerprint,
            credential_was_supplied=credential_was_supplied,
            supplied_effective_fingerprint=supplied_effective_fingerprint,
        ):
            return cls._credential_changed_result()
        refreshed_slice = cls._openrouter_slice(cache=cache)
        assert refreshed_slice is not None
        cls._publish_candidate(candidate=candidate, fingerprint=fingerprint)
        cls._publish_checked_status(slice=refreshed_slice, operation_token=operation_token)
        return CatalogRefreshResultDAO(
            status="refreshed",
            catalog_generation=cls._generation(),
            safe_message="OpenRouter catalog refreshed.",
        )

    @classmethod
    async def _discover_openrouter_models(
        cls,
        *,
        client: OpenRouterCatalogClientProtocol,
        client_is_service_owned: bool,
        fingerprint: str,
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        existing: Optional[ProviderCatalogCacheDAO],
        force: bool,
    ) -> tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
        """Fetch verified discovery data and close only service-created clients.

        WHAT: Owns default-client lifetime around the key/list sequence while
            leaving injected test/application clients entirely caller-owned.
        WHO: ``_refresh_openrouter`` calls this after cache freshness requires a
            remote discovery attempt.
        WHEN: Runs under the catalog lease; cancellation exits the owned context
            before propagating so the refresh cannot report false success.

        Args:
            client (OpenRouterCatalogClientProtocol): Captured-credential metadata client.
            fingerprint (str): Private identity used to validate verification evidence.
            key_verification (Optional[OpenRouterKeyVerificationDAO]): Reusable matching proof.
            existing (Optional[ProviderCatalogCacheDAO]): Current same-provider raw slice.
            force (bool): Whether existing verification evidence may be reused.

        Returns:
            tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
                Matching verification evidence and one complete wire response.
        """
        if not client_is_service_owned:
            return await cls._fetch_openrouter_models(
                client=client,
                fingerprint=fingerprint,
                key_verification=key_verification,
                existing=existing,
                force=force,
            )
        if hasattr(client, "__aenter__") and hasattr(client, "__aexit__"):
            async with client:  # type: ignore[union-attr]
                return await cls._fetch_openrouter_models(
                    client=client,
                    fingerprint=fingerprint,
                    key_verification=key_verification,
                    existing=existing,
                    force=force,
                )
        return await cls._fetch_openrouter_models(
            client=client,
            fingerprint=fingerprint,
            key_verification=key_verification,
            existing=existing,
            force=force,
        )

    @classmethod
    async def _fetch_openrouter_models(
        cls,
        *,
        client: OpenRouterCatalogClientProtocol,
        fingerprint: str,
        key_verification: Optional[OpenRouterKeyVerificationDAO],
        existing: Optional[ProviderCatalogCacheDAO],
        force: bool,
    ) -> tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
        """Fetch one key/list pair without assigning client lifetime to injected callers.

        Args:
            client (OpenRouterCatalogClientProtocol): Captured-credential metadata client.
            fingerprint (str): Private identity used to validate verification evidence.
            key_verification (Optional[OpenRouterKeyVerificationDAO]): Reusable matching proof.
            existing (Optional[ProviderCatalogCacheDAO]): Current same-provider raw slice.
            force (bool): Whether existing verification evidence may be reused.

        Returns:
            tuple[OpenRouterKeyVerificationDAO, OpenRouterModelsResponseDAO]:
                Matching verification evidence and the fetched model response.
        """
        evidence: OpenRouterKeyVerificationDAO = cls._usable_key_verification(
            evidence=key_verification
            or (
                None
                if force or fingerprint in cls._rejected_openrouter_fingerprints
                else cls._key_verification_from_slice(slice=existing)
            ),
            fingerprint=fingerprint,
        ) or await cls._verify_openrouter_key(client=client, fingerprint=fingerprint)
        if (
            evidence.credential_fingerprint == fingerprint
            and cls._status_operation.get() == cls._current_openrouter_operation
        ):
            cls._key_verification = evidence
            cls._publish_status(
                status=cls._lifecycle_status.model_copy(
                    update={
                        "state": "verified",
                        "key_verified_at": evidence.verified_at,
                    }
                )
            )
        try:
            response: OpenRouterModelsResponseDAO = await client.list_user_models()
        except OpenRouterAuthenticationError:
            cls._invalidate_rejected_openrouter_credential(fingerprint=fingerprint)
            raise
        return evidence, response

    @classmethod
    async def _verify_openrouter_key(
        cls, *, client: OpenRouterCatalogClientProtocol, fingerprint: str
    ) -> OpenRouterKeyVerificationDAO:
        """Invalidate rejected verification without deleting the browsable raw cache.

        Args:
            client: Metadata boundary bound to the captured operation credential.
            fingerprint: Private identity whose evidence is being checked.

        Returns:
            OpenRouterKeyVerificationDAO: Successful evidence from the existing client.

        Raises:
            OpenRouterAuthenticationError: An explicit key rejection blocks admission.
        """
        try:
            evidence = await client.get_current_key()
        except OpenRouterAuthenticationError:
            cls._invalidate_rejected_openrouter_credential(fingerprint=fingerprint)
            raise
        cls._rejected_openrouter_fingerprints.discard(fingerprint)
        return evidence

    @classmethod
    def _invalidate_rejected_openrouter_credential(cls, *, fingerprint: str) -> None:
        """Invalidate all private and public evidence for one explicitly rejected key.

        Args:
            fingerprint: Private captured credential identity rejected by either metadata endpoint.
        """
        cls._rejected_openrouter_fingerprints.add(fingerprint)
        if cls._status_operation.get() != cls._current_openrouter_operation:
            return
        cls._key_verification = None
        cls._publish_status(status=CatalogLifecycleStatusDAO(state="failed"))

    @classmethod
    def _credential_changed_result(cls) -> CatalogRefreshResultDAO:
        """Return fixed public failure copy without exposing the compared identities.

        Returns:
            CatalogRefreshResultDAO: Rejection retaining the currently published generation.
        """
        return CatalogRefreshResultDAO(
            status="credential_changed",
            catalog_generation=cls._generation(),
            safe_message="OpenRouter credential changed during refresh.",
        )

    @classmethod
    async def _build_publication_candidate(cls, *, cache: ModelCatalogCacheDAO) -> ModelCatalogSnapshotDAO:
        """Validate the complete merged override view before the refresh owner persists.

        Args:
            cache: Raw candidate; overrides never enter this durable envelope.

        Returns:
            ModelCatalogSnapshotDAO: Validated immutable candidate, not yet published.

        Raises:
            ValueError: An override broadens provider capabilities or limits.
        """
        merged = cls._merge_seed_and_provider_cache(
            seed_snapshot=SeedModelCatalog.load(),
            provider_cache=cache,
            active_openrouter_fingerprint=cls._active_openrouter_fingerprint,
        )
        return await asyncio.to_thread(cls._apply_manual_overrides, snapshot=merged)

    @classmethod
    def _publish_candidate(cls, *, candidate: ModelCatalogSnapshotDAO, fingerprint: str) -> None:
        """Swap one validated snapshot after persistence without an intervening await.

        Args:
            candidate: Complete immutable view owned by the refresh holding the lease.
            fingerprint: Private provenance of this successfully committed candidate.
        """
        cls._snapshot = candidate.model_copy(update={"generation": cls._generation() + 1})
        cls._cached_openrouter_fingerprint = fingerprint

    @staticmethod
    def _has_newer_success(
        *,
        observed: Optional[ModelCatalogCacheDAO],
        existing: Optional[ProviderCatalogCacheDAO],
        fingerprint: str,
    ) -> bool:
        """Compare same-key successful listing evidence across lease acquisition.

        Args:
            observed: Cache read before waiting.
            existing: Slice reread under the lease.
            fingerprint: Captured credential identity.

        Returns:
            bool: Whether a newer successful same-key listing won the lease.
        """
        if existing is None or existing.credential_fingerprint != fingerprint or not existing.last_success_at:
            return False
        previous = (
            next(
                (
                    item
                    for item in observed.provider_slices
                    if item.provider is ProviderName.OPENROUTER and item.credential_fingerprint == fingerprint
                ),
                None,
            )
            if observed
            else None
        )
        if previous is None or previous.last_success_at is None:
            return True
        try:
            return datetime.fromisoformat(existing.last_success_at) > datetime.fromisoformat(
                previous.last_success_at
            )
        except (ValueError, TypeError):
            return False

    @classmethod
    async def _write_cache_under_lease(
        cls, *, cache: ModelCatalogCacheDAO, cache_path: Optional[Path]
    ) -> "AtomicWriteOutcomeDAO":
        """Drain an atomic writer before cancellation releases its enclosing lease.

        Args:
            cache: Complete replacement envelope.
            cache_path: Optional private destination.

        Returns:
            AtomicWriteOutcomeDAO: The existing writer's commit outcome.
        """
        task = asyncio.create_task(
            asyncio.to_thread(ModelCatalogStore.write_provider_cache, cache=cache, override_path=cache_path)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
            raise

    @classmethod
    def _reconcile_openrouter_slice(
        cls,
        *,
        existing: Optional[ProviderCatalogCacheDAO],
        fingerprint: str,
        evidence: OpenRouterKeyVerificationDAO,
        entries: list[ModelCatalogEntryDAO],
    ) -> ProviderCatalogCacheDAO:
        """Build a complete replacement slice and retain bounded removal evidence.

        Args:
            existing (Optional[ProviderCatalogCacheDAO]): Prior same-provider slice.
            fingerprint (str): Private credential provenance for the replacement.
            evidence (OpenRouterKeyVerificationDAO): Matching key-verification evidence.
            entries (list[ModelCatalogEntryDAO]): Complete converted current listing.

        Returns:
            ProviderCatalogCacheDAO: Replacement membership plus removal tombstones.
        """
        tombstones: list[ProviderCatalogTombstoneDAO] = cls._retained_tombstones(
            existing=existing,
            entries=entries,
        )
        timestamp: str = datetime.now(tz=timezone.utc).isoformat()
        return ProviderCatalogCacheDAO(
            provider=ProviderName.OPENROUTER,
            credential_fingerprint=fingerprint,
            key_verified_at=evidence.verified_at.isoformat(),
            last_success_at=timestamp,
            entries=entries,
            tombstones=tombstones,
        )

    @classmethod
    def _retained_tombstones(
        cls,
        *,
        existing: Optional[ProviderCatalogCacheDAO],
        entries: list[ModelCatalogEntryDAO],
    ) -> list[ProviderCatalogTombstoneDAO]:
        """Retain recent evidence and append removals from a complete replacement.

        Args:
            existing (Optional[ProviderCatalogCacheDAO]): Previous persisted slice.
            entries (list[ModelCatalogEntryDAO]): Complete replacement entries.

        Returns:
            list[ProviderCatalogTombstoneDAO]: Recent prior evidence plus new removals.
        """
        if existing is None:
            return []
        current_names: set[str] = {entry.model_name for entry in entries}
        now: datetime = datetime.now(tz=timezone.utc)
        retained: dict[str, ProviderCatalogTombstoneDAO] = {
            tombstone.model_name: tombstone
            for tombstone in existing.tombstones
            if cls._tombstone_is_recent(tombstone=tombstone, now=now)
        }
        for entry in existing.entries:
            if entry.model_name in current_names:
                continue
            retained[entry.model_name] = ProviderCatalogTombstoneDAO(
                model_name=entry.model_name,
                api_model_name=entry.api_model_name or entry.model_name,
                reason=cls._tombstone_reason_for_entry(entry=entry),
                last_seen_at=now.isoformat(),
            )
        return list(retained.values())

    @staticmethod
    def _tombstone_reason_for_entry(
        *, entry: ModelCatalogEntryDAO
    ) -> Literal["removed", "expired", "ineligible"]:
        """Preserve the last complete-list availability classification as tombstone evidence."""
        if entry.availability == "expired":
            return "expired"
        if entry.availability == "ineligible":
            return "ineligible"
        return "removed"

    @staticmethod
    def _tombstone_is_recent(*, tombstone: ProviderCatalogTombstoneDAO, now: datetime) -> bool:
        """Return whether persisted removal evidence is within the thirty-day retention window."""
        try:
            recorded_at: datetime = datetime.fromisoformat(tombstone.last_seen_at)
        except ValueError:
            return False
        if recorded_at.tzinfo is None:
            return False
        age: timedelta = now - recorded_at.astimezone(timezone.utc)
        return timedelta(0) <= age < timedelta(days=30)

    @classmethod
    def _key_verification_from_slice(
        cls, *, slice: Optional[ProviderCatalogCacheDAO]
    ) -> Optional[OpenRouterKeyVerificationDAO]:
        """Rehydrate private verification evidence owned by a persisted provider slice.

        Args:
            slice: Raw persisted OpenRouter provider slice, if one was loaded.

        Returns:
            Optional[OpenRouterKeyVerificationDAO]: Parsed fingerprint-bound evidence,
            or None for missing or malformed persisted fields.
        """
        if slice is None or slice.credential_fingerprint is None or slice.key_verified_at is None:
            return None
        try:
            verified_at: datetime = datetime.fromisoformat(slice.key_verified_at)
        except ValueError:
            return None
        if verified_at.tzinfo is None:
            return None
        return OpenRouterKeyVerificationDAO(
            credential_fingerprint=slice.credential_fingerprint,
            verified_at=verified_at,
        )

    @classmethod
    def _usable_key_verification(
        cls,
        *,
        evidence: Optional[OpenRouterKeyVerificationDAO],
        fingerprint: str,
    ) -> Optional[OpenRouterKeyVerificationDAO]:
        """Return fresh matching private evidence or force one key verification.

        Args:
            evidence: Optional prior successful verification bound to a credential.
            fingerprint: Private fingerprint for the captured effective credential.

        Returns:
            Optional[OpenRouterKeyVerificationDAO]: Reusable evidence when it is
            matching and younger than the one-hour verification TTL.
        """
        if evidence is None or evidence.credential_fingerprint != fingerprint:
            return None
        age: timedelta = datetime.now(tz=timezone.utc) - evidence.verified_at.astimezone(timezone.utc)
        if timedelta(0) <= age < timedelta(hours=1):
            return evidence
        return None

    @classmethod
    def _effective_fingerprint_for_resolved_credential(cls) -> Optional[str]:
        """Return the current effective credential identity without exposing the key.

        WHAT: Captures resolver precedence as a private fingerprint.
        WHO: ``refresh()`` and pre-publication validation use it.
        WHEN: A supplied credential path captures a baseline before its shared task starts.

        Returns:
            Optional[str]: Private effective fingerprint, or None when no credential is effective.
        """
        effective: Optional[ResolvedCredentialDAO] = CredentialResolver.resolve_with_source(
            provider=ProviderName.OPENROUTER
        )
        if effective is None:
            return None
        return credential_fingerprint(access_token=effective.credential.access_token)

    @classmethod
    def _effective_fingerprint_changed(
        cls,
        *,
        fingerprint: str,
        credential_was_supplied: bool,
        supplied_effective_fingerprint: Optional[str],
    ) -> bool:
        """Return whether resolver precedence changed during a refresh operation.

        WHAT: Rechecks identity before durable commit and publication.
        WHO: The coalesced catalog owner calls this after creating a complete candidate.
        WHEN: Supplied candidates compare against their admission baseline; ordinary
            refreshes require the captured credential to remain effective.

        Args:
            fingerprint (str): Private fingerprint captured for the operation credential.
            credential_was_supplied (bool): Whether an auth caller supplied that credential.
            supplied_effective_fingerprint (Optional[str]): Effective identity at supplied-operation admission.

        Returns:
            bool: Whether effective resolver identity changed or disappeared.
        """
        current_fingerprint: Optional[str] = cls._effective_fingerprint_for_resolved_credential()
        if not credential_was_supplied:
            return current_fingerprint != fingerprint
        if supplied_effective_fingerprint is None:
            return current_fingerprint is not None
        return current_fingerprint != fingerprint

    @classmethod
    def _provider_slice_is_fresh(
        cls, *, slice: Optional["ProviderCatalogCacheDAO"], fingerprint: str
    ) -> bool:
        """Return whether a matching provider slice has a current successful listing."""
        if slice is None or slice.credential_fingerprint != fingerprint or slice.last_success_at is None:
            return False
        try:
            recorded_at = datetime.fromisoformat(slice.last_success_at)
        except ValueError:
            return False
        return 0 <= (datetime.now(tz=timezone.utc) - recorded_at).total_seconds() < 3_600

    @classmethod
    def _generation(cls) -> int:
        """Return the currently published generation or the seeded baseline."""
        return cls._snapshot.generation if cls._snapshot is not None else 0

    @classmethod
    def reset(cls) -> None:
        """Clear published state and cancel owned refresh tasks for test isolation.

        The application shutdown owner must await tasks before process teardown;
        this synchronous test seam only requests cancellation and removes the
        registry references so a later event loop cannot reuse a stale task.
        """
        cls._publish_status(status=CatalogLifecycleStatusDAO())
        cls._key_verification = None
        cls._active_openrouter_fingerprint = None
        cls._cached_openrouter_fingerprint = None
        cls._rejected_openrouter_fingerprints.clear()
        cls._current_openrouter_operation += 1
        tasks: tuple[asyncio.Task[CatalogRefreshResultDAO], ...] = tuple(cls._refresh_tasks.values())
        cls._refresh_tasks.clear()
        for task in tasks:
            cls._retiring_refresh_tasks.add(task)
            task.add_done_callback(cls._retiring_refresh_tasks.discard)
            task.cancel()
        cls._snapshot = None

    @classmethod
    async def shutdown(cls) -> None:
        """Cancel and await this loop's owned refresh work before application teardown.

        Includes work retired by synchronous test reset. Callers must stop new
        refresh admission before shutdown; other event loops retain their owners.
        """
        loop = asyncio.get_running_loop()
        tasks = tuple(
            task
            for task in set(cls._refresh_tasks.values()) | cls._retiring_refresh_tasks
            if task.get_loop() is loop
        )
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        cls._retiring_refresh_tasks.difference_update(tasks)
        for key, task in tuple(cls._refresh_tasks.items()):
            if task in tasks:
                cls._refresh_tasks.pop(key, None)

    @classmethod
    def supported_models_by_provider(
        cls, *, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> dict[ProviderName, list[str]]:
        """Return visible supported models grouped by provider.

        Returns:
            dict[ProviderName, list[str]]: Picker-visible model names grouped by provider.
        """
        snapshot = snapshot if snapshot is not None else cls.load()
        return cls._group_visible_entries(snapshot=snapshot)

    @classmethod
    def entry_for_model(
        cls,
        *,
        model_name: str,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> ModelCatalogEntryDAO:
        """Return the canonical entry for one model or alias.

        Args:
            model_name (str): Canonical model name or known alias.

        Returns:
            ModelCatalogEntryDAO: Matching catalog entry.

        Raises:
            ValueError: When the model name or alias is not known.
        """
        snapshot = snapshot if snapshot is not None else cls.load()
        return cls._resolve_entry(snapshot=snapshot, model_name=model_name)

    @classmethod
    def api_model_name_for(
        cls,
        *,
        model_name: str,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
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
        entry: ModelCatalogEntryDAO = cls.entry_for_model(model_name=model_name, snapshot=snapshot)
        if entry.api_model_name is None:
            return entry.model_name
        return entry.api_model_name

    @classmethod
    def _merge_seed_and_provider_cache(
        cls,
        *,
        seed_snapshot: ModelCatalogSnapshotDAO,
        provider_cache: Optional[ModelCatalogCacheDAO],
        active_openrouter_fingerprint: Optional[str] = None,
    ) -> ModelCatalogSnapshotDAO:
        """Merge seed identity with raw provider slices without baking overrides.

        Args:
            seed_snapshot (ModelCatalogSnapshotDAO): Committed seed catalog.
            provider_cache (Optional[ModelCatalogCacheDAO]): Raw schema-two cache.

        Returns:
            ModelCatalogSnapshotDAO: One offline immutable merged read snapshot.
        """
        merged_entries: dict[str, ModelCatalogEntryDAO] = dict(seed_snapshot.entries)
        if provider_cache is not None:
            for provider_slice in provider_cache.provider_slices:
                if provider_slice.credential_fingerprint is None:
                    continue
                if not cls._provider_slice_is_visible(
                    provider_slice=provider_slice,
                    effective_fingerprint=active_openrouter_fingerprint,
                ):
                    continue
                for entry in provider_slice.entries:
                    cls._merge_provider_cache_entry(entries=merged_entries, entry=entry)
        return ModelCatalogSnapshotDAO(
            schema_version="2",
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            entries=merged_entries,
            aliases=dict(seed_snapshot.aliases),
            templates=seed_snapshot.templates,
            generation=seed_snapshot.generation,
        )

    @staticmethod
    def _provider_slice_is_visible(
        *,
        provider_slice: ProviderCatalogCacheDAO,
        effective_fingerprint: Optional[str],
    ) -> bool:
        """Return whether a raw provider slice matches current credential provenance.

        A mismatched or absent OpenRouter credential may retain its raw durable
        cache for future matching-key reuse, but it cannot populate a new
        picker, selection, or factory preparation read.
        """
        if provider_slice.provider is not ProviderName.OPENROUTER:
            return True
        return (
            effective_fingerprint is not None
            and provider_slice.credential_fingerprint == effective_fingerprint
        )

    @classmethod
    def _merge_provider_cache_entry(
        cls,
        *,
        entries: dict[str, ModelCatalogEntryDAO],
        entry: ModelCatalogEntryDAO,
    ) -> None:
        """Merge one raw entry while keeping direct seed identity authoritative."""
        seed_entry: Optional[ModelCatalogEntryDAO] = entries.get(entry.model_name)
        if seed_entry is None:
            entries[entry.model_name] = entry
            return
        entries[entry.model_name] = cls._merge_entry(seed_entry=seed_entry, cached_entry=entry)

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
        grouped: dict[ProviderName, list[str]] = {provider: [] for provider in ProviderName}
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
