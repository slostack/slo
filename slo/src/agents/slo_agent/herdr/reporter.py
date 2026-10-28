"""Bounded private publication scheduler; shared transport owns every process."""

from __future__ import annotations

import asyncio
import os
import stat
import shutil
import logging
import time
import unicodedata
from pathlib import Path
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, Optional, get_args

from .dao import (
    HerdrReporterConfigDAO,
    HerdrRestoreStoreProtocol,
    HerdrRestoreResourceOwner,
    HerdrPublicationDAO,
    HerdrSavedRestoreDAO,
    HerdrRemoteBindingDAO,
    HerdrReportTicketDAO,
    HerdrLifecycleAcknowledgementDAO,
    HerdrReporterCloseOutcomeDAO,
    HerdrRestoreCaptureDAO,
    HerdrRestoreUnavailableError,
    HerdrReportOperation,
    HerdrCommandResultDAO,
    HerdrReporterProtocol,
    HerdrDestination,
    HerdrCliCommandDAO,
    HerdrDisplayTokenDAO,
    HerdrDisplayKey,
)
from .sequence_store import HerdrSequenceStore
from ..sessions.identity import is_canonical_uuid_session_id
from .service import HerdrCliTransport, HerdrTaskJoin, HerdrEnvironmentGate

if TYPE_CHECKING:
    from .visualizer import HerdrVisualizerLauncher

HERDR_TOKEN_KEYS: tuple[str, ...] = get_args(HerdrDisplayKey)


class HerdrReporter:
    """Own one publication, save, reservation and remote binding per lifetime."""

    def __init__(
        self,
        *,
        config: HerdrReporterConfigDAO,
        transport: HerdrCliTransport,
        sequence_store: HerdrSequenceStore,
        restore_store: HerdrRestoreStoreProtocol,
    ) -> None:
        """Capture inert collaborators for one session; start acquires resources.

        Args:
            config (HerdrReporterConfigDAO): Validated immutable pane configuration.
            transport (HerdrCliTransport): Shared reporting/viewer process owner.
            sequence_store (HerdrSequenceStore): Exclusive pane counter/lease owner.
            restore_store (HerdrRestoreStoreProtocol): Off-loop immutable save owner;
                optional resource-owner capability participates in final drain.
        """
        self._config = config
        self._transport = transport
        self._sequence_store = sequence_store
        self._restore_store = restore_store
        self._latest: Optional[HerdrPublicationDAO] = None
        self._pending: Optional[HerdrPublicationDAO] = None
        self._saved: Optional[HerdrSavedRestoreDAO] = None
        self._binding: Optional[HerdrRemoteBindingDAO] = None
        self._before_admission_binding: Optional[HerdrRemoteBindingDAO] = None
        self._reserved_ticket: Optional[HerdrReportTicketDAO] = None
        self._admitted_ticket: Optional[HerdrReportTicketDAO] = None
        self._lifecycle_ack: Optional[HerdrLifecycleAcknowledgementDAO] = None
        self._restore_ack: Optional[HerdrSavedRestoreDAO] = None
        self._display_ack_revision: Optional[int] = None
        self._save_task: Optional[asyncio.Task[HerdrSavedRestoreDAO]] = None
        self._reservation_task: Optional[asyncio.Task[int]] = None
        self._start_task: Optional[asyncio.Task[None]] = None
        self._worker: Optional[asyncio.Task[None]] = None
        self._refresh_task: Optional[asyncio.Task[None]] = None
        self._lease_task: Optional[asyncio.Task[None]] = None
        self._close_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._retired_reporter_drain_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._transport_close_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._revision = self._close_token = 0
        self._closing = self._disabled = self._cleanup_failed = False
        self._ordinary_revoked = self._viewer_revoked = self._withdrawal_pending = False
        self._starting = self._activation_attempted = self._activation_admitted = False
        self._activation_released = self._shutdown_admitted = self._shutdown_released = False
        self._lease_held = False
        self._sequence_safe = True
        self._resume_available = False
        self._close_deadline: Optional[float] = None
        self._wake = asyncio.Event()
        self._diagnostic_times: dict[str, float] = {}
        self._diagnostic_failures: set[str] = set()

    def publish(self, *, publication: HerdrPublicationDAO) -> None:
        """Replace pending facts at the session's synchronous commit boundary.

        No I/O or task creation occurs. Revoked/closed/disabled and identical
        publications are ignored; one latest pending value replaces older work.

        Args:
            publication (HerdrPublicationDAO): Frozen snapshot and exact private
                capture; changed configuration requires an increased generation.

        Raises:
            ValueError: Fixed publication_invalid refusal for generation rollback
                or same-generation identity/policy changes; existing facts remain.
        """
        if self._ordinary_revoked or self._closing or self._disabled or publication == self._latest:
            return
        self._validate_publication(publication=publication)
        self._revision += 1
        self._latest = self._pending = publication
        self._wake.set()

    def _validate_publication(self, *, publication: HerdrPublicationDAO) -> None:
        """Refuse generation reuse for changed private policy with fixed diagnostics."""
        latest = self._latest
        if latest is None:
            return
        if publication.configuration_generation < latest.configuration_generation:
            raise ValueError("publication_invalid")
        if (
            publication.configuration_generation == latest.configuration_generation
            and not self._same_configuration(left=publication, right=latest)
        ):
            raise ValueError("publication_invalid")

    @classmethod
    def _same_configuration(cls, *, left: HerdrPublicationDAO, right: HerdrPublicationDAO) -> bool:
        """Compare complete immutable policy independently of display revision."""
        return (
            left.configuration_generation == right.configuration_generation
            and left.snapshot.session_id == right.snapshot.session_id
            and left.restore_capture == right.restore_capture
        )

    def revoke_viewer_admission(self) -> None:
        """Seal ordinary authority before any session teardown await."""
        self._viewer_revoked = self._ordinary_revoked = True
        self._pending = None
        self._wake.set()

    def allows_viewer_admission(self) -> bool:
        """Read live authority under the shared lock, never captured permission."""
        return (
            not self._viewer_revoked
            and not self._closing
            and not self._disabled
            and self._activation_released
            and self._lease_held
            and self._sequence_safe
            and not self._transport.closed
        )

    def _matches_save(self, *, saved: HerdrSavedRestoreDAO) -> bool:
        """Accept only the exact current capture after asynchronous storage."""
        latest = self._latest
        if latest is None or self._ordinary_revoked or self._closing or self._disabled:
            return False
        return (
            latest.configuration_generation == saved.configuration_generation
            and latest.restore_capture == saved.capture
        )

    def _adopt_save(self, *, saved: HerdrSavedRestoreDAO) -> None:
        """Continue using latest display, never the snapshot that started the save."""
        if not self._matches_save(saved=saved):
            return
        self._saved = saved
        self._record_recovery(category="restore_save_unavailable")
        self._pending = self._latest
        self._wake.set()

    async def _save_capture(self, *, publication: HerdrPublicationDAO) -> HerdrSavedRestoreDAO:
        """Save immutable policy off-loop and retain its exact generation association."""
        capture = self._require_capture(publication=publication)
        reference = await asyncio.to_thread(self._restore_store.save, config=capture.config)
        return HerdrSavedRestoreDAO(
            configuration_generation=publication.configuration_generation,
            capture=capture,
            reference=reference,
        )

    @classmethod
    def _require_capture(cls, *, publication: HerdrPublicationDAO) -> HerdrRestoreCaptureDAO:
        """Refuse ineligible input before touching the injected store."""
        if publication.restore_capture is None:
            raise HerdrRestoreUnavailableError()
        return publication.restore_capture

    async def _ensure_saved_restore(self, *, publication: HerdrPublicationDAO) -> None:
        """Reuse one exact save or join one finite write before any next batch."""
        if publication.restore_capture is None:
            self._saved = None
            return
        if self._saved is not None and self._matches_save(saved=self._saved):
            return
        self._saved = None
        self._save_task = asyncio.create_task(coro=self._save_capture(publication=publication))
        saved = await self._join_save()
        self._finish_save(publication=publication, saved=saved)

    async def _join_save(self) -> Optional[HerdrSavedRestoreDAO]:
        """Join even through caller cancellation before clearing the owned slot."""
        task = self._save_task
        if task is None:
            return None
        cancelled = await HerdrTaskJoin.wait(task=task)
        try:
            if cancelled or task.cancelled():
                raise asyncio.CancelledError
            if task.exception() is not None:
                self._log_failure(category="restore_save_unavailable")
                return None
            return task.result()
        finally:
            self._save_task = None

    def _finish_save(
        self, *, publication: HerdrPublicationDAO, saved: Optional[HerdrSavedRestoreDAO] = None
    ) -> None:
        """Adopt success or require withdrawal of a possibly installed reference."""
        if saved is not None:
            self._adopt_save(saved=saved)
            return
        if self._latest is not None and self._same_configuration(left=publication, right=self._latest):
            self._withdrawal_pending = self._binding is not None and self._binding.reference is not None

    async def _reserve_ticket(
        self,
        *,
        operation: HerdrReportOperation,
        publication: Optional[HerdrPublicationDAO] = None,
        revision: int = 0,
        saved: Optional[HerdrSavedRestoreDAO] = None,
        binding: Optional[HerdrRemoteBindingDAO] = None,
        display_final: bool = False,
    ) -> Optional[HerdrReportTicketDAO]:
        """Durably reserve one source number before handing authority to transport."""
        if not self._sequence_safe or not self._lease_held:
            return None
        source: Literal["custom:slo", "custom:slo-display"] = (
            "custom:slo-display" if operation in ("clear", "set", "shutdown_clear") else "custom:slo"
        )
        self._reservation_task = asyncio.create_task(
            coro=asyncio.to_thread(self._sequence_store.reserve, source=source)
        )
        cancelled = await HerdrTaskJoin.wait(task=self._reservation_task)
        try:
            sequence = self._reservation_task.result()
        except Exception:
            self._sequence_safe = False
            self._disabled = True
            self._log_failure(category="sequence_unavailable")
            sequence = None
        finally:
            self._reservation_task = None
        if cancelled:
            raise asyncio.CancelledError
        if sequence is None:
            return None
        ticket = HerdrReportTicketDAO(
            configuration_generation=publication.configuration_generation if publication is not None else 0,
            report_revision=revision,
            operation=operation,
            sequence=sequence,
            publication=publication,
            saved=saved,
            binding=binding,
            display_final=display_final,
            close_token=self._close_token if operation.startswith("shutdown_") else None,
        )
        self._reserved_ticket = ticket
        return ticket

    def _is_current(self, *, configuration_generation: int, revision: int) -> bool:
        """Gate desired facts independently of already admitted remote effects."""
        latest = self._latest
        return (
            latest is not None
            and not self._ordinary_revoked
            and not self._closing
            and not self._disabled
            and latest.configuration_generation == configuration_generation
            and self._revision == revision
        )

    def _needs_release(self, *, publication: HerdrPublicationDAO) -> bool:
        """Require confirmed withdrawal before changing any exact policy association."""
        binding = self._binding
        if binding is None:
            return False
        return self._withdrawal_pending or not (
            binding.configuration_generation == publication.configuration_generation
            and binding.session_id == publication.snapshot.session_id
            and binding.capture == publication.restore_capture
        )

    def _binding_allows(self, *, ticket: HerdrReportTicketDAO) -> bool:
        """Authorize only identity-compatible commands or an exact conflicting release."""
        publication = ticket.publication
        if publication is None:
            return False
        if ticket.operation == "replace_release":
            return (
                self._binding is not None
                and self._binding == ticket.binding
                and self._needs_release(publication=publication)
            )
        if ticket.operation == "claim":
            return not self._needs_release(publication=publication)
        if self._binding is None or self._binding.certainty != "confirmed":
            return False
        if self._needs_release(publication=publication):
            return False
        if ticket.operation != "restore":
            return ticket.operation in ("lifecycle", "clear", "set")
        return (
            ticket.saved is not None
            and ticket.saved == self._saved
            and self._matches_save(saved=ticket.saved)
        )

    def _mark_admitted(self, *, ticket: HerdrReportTicketDAO) -> None:
        """Retain pre-commit knowledge for definitive spawn-failure rollback."""
        self._before_admission_binding = self._binding
        if ticket.operation == "activation_release":
            self._activation_admitted = True
        elif ticket.operation == "shutdown_release":
            self._shutdown_admitted = True
        elif ticket.operation in ("claim", "restore"):
            self._binding = self._possible_binding(ticket=ticket)

    def _possible_binding(self, *, ticket: HerdrReportTicketDAO) -> HerdrRemoteBindingDAO:
        """Preserve confirmed same-capture identity during uncertain reference installation."""
        publication = ticket.publication
        assert publication is not None
        reference = self._binding.reference if self._binding is not None else None
        if ticket.operation == "restore":
            assert ticket.saved is not None
            reference = ticket.saved.reference
        return HerdrRemoteBindingDAO(
            configuration_generation=ticket.configuration_generation,
            session_id=publication.snapshot.session_id,
            capture=publication.restore_capture,
            reference=reference,
            certainty=(
                self._binding.certainty if ticket.operation == "restore" and self._binding else "possible"
            ),
        )

    def _admit_command(self, *, ticket: HerdrReportTicketDAO) -> bool:
        """Consume one exact authority synchronously under the transport lock."""
        if ticket is not self._reserved_ticket or not self._lease_held or not self._sequence_safe:
            return False
        if not self._admission_policy(ticket=ticket):
            return False
        self._reserved_ticket = None
        self._admitted_ticket = ticket
        self._mark_admitted(ticket=ticket)
        return True

    def _admission_policy(self, *, ticket: HerdrReportTicketDAO) -> bool:
        """Separate lifetime cleanup authority from revocable ordinary publication."""
        if ticket.operation == "activation_release":
            return self._starting and not self._closing and not self._activation_admitted
        if ticket.operation in ("shutdown_release", "shutdown_clear"):
            return self._shutdown_allows(ticket=ticket)
        return self._is_current(
            configuration_generation=ticket.configuration_generation, revision=ticket.report_revision
        ) and self._binding_allows(ticket=ticket)

    def _shutdown_allows(self, *, ticket: HerdrReportTicketDAO) -> bool:
        """Enforce one close token and finite CLI budget without renewing authority."""
        if not self._closing or ticket.close_token != self._close_token:
            return False
        if self._close_deadline is None or asyncio.get_running_loop().time() >= self._close_deadline:
            return False
        if ticket.operation == "shutdown_clear":
            return self._shutdown_released
        return not self._shutdown_admitted and self._binding is not None and self._binding == ticket.binding

    def _acknowledge_current(self, *, ticket: HerdrReportTicketDAO) -> None:
        """Never credit stale remote success to newer desired facts."""
        if not self._is_current(
            configuration_generation=ticket.configuration_generation, revision=ticket.report_revision
        ):
            self._invalidate_semantic_acknowledgements(ticket=ticket)
            return
        if ticket.operation in ("claim", "lifecycle", "restore"):
            assert ticket.publication is not None
            snapshot = ticket.publication.snapshot
            self._lifecycle_ack = HerdrLifecycleAcknowledgementDAO(
                configuration_generation=ticket.configuration_generation,
                session_id=snapshot.session_id,
                state=snapshot.state,
                block_reason=snapshot.block_reason,
            )
        if ticket.operation == "restore":
            self._restore_ack = ticket.saved
        if ticket.operation in ("clear", "set") and ticket.display_final:
            self._display_ack_revision = ticket.report_revision

    def _invalidate_semantic_acknowledgements(self, *, ticket: HerdrReportTicketDAO) -> None:
        """Forget uncertain semantic acknowledgements without forgetting binding."""
        if ticket.operation in ("claim", "lifecycle", "restore"):
            self._lifecycle_ack = None
        if ticket.operation == "restore":
            self._restore_ack = None

    def _record_command_result(self, *, ticket: HerdrReportTicketDAO, result: HerdrCommandResultDAO) -> None:
        """Account once under the lock, even when publication has superseded this effect."""
        if ticket is not self._admitted_ticket or not result.admitted:
            return
        self._record_result_diagnostic(ticket=ticket, result=result)
        if result.spawn_failed:
            self._binding = self._before_admission_binding
        elif result.outcome.status == "ok":
            self._record_success(ticket=ticket)
        else:
            self._invalidate_semantic_acknowledgements(ticket=ticket)
        self._admitted_ticket = None
        self._before_admission_binding = None

    def _record_result_diagnostic(
        self, *, ticket: HerdrReportTicketDAO, result: HerdrCommandResultDAO
    ) -> None:
        """Report ordinary failures/recovery without changing episodes on cancellation."""
        category: Literal[
            "publication_failed", "restore_unavailable", "release_unavailable", "activation_unavailable"
        ] = "publication_failed"
        if ticket.operation == "activation_release":
            category = "activation_unavailable"
        elif ticket.operation in ("replace_release", "shutdown_release", "shutdown_clear"):
            category = "release_unavailable"
        elif ticket.operation == "restore":
            category = "restore_unavailable"
        if result.outcome.status == "ok":
            self._record_recovery(category=category)
        elif result.outcome.status not in ("suppressed", "cancelled"):
            self._log_failure(category=category)

    def _record_success(self, *, ticket: HerdrReportTicketDAO) -> None:
        """Update actual remote knowledge before evaluating desired acknowledgements."""
        if ticket.operation == "activation_release":
            self._activation_released = True
        elif ticket.operation in ("replace_release", "shutdown_release"):
            self._record_release(ticket=ticket)
        elif ticket.operation in ("claim", "restore") and self._binding is not None:
            self._binding = self._binding.model_copy(update={"certainty": "confirmed"})
        self._acknowledge_current(ticket=ticket)

    def _record_release(self, *, ticket: HerdrReportTicketDAO) -> None:
        """Clear only the exact released binding and its semantic acknowledgements."""
        if self._binding != ticket.binding:
            return
        self._binding = None
        self._withdrawal_pending = False
        self._lifecycle_ack = None
        self._restore_ack = None
        self._display_ack_revision = None
        if ticket.operation == "shutdown_release":
            self._shutdown_released = True

    def _command_for_ticket(
        self,
        *,
        ticket: HerdrReportTicketDAO,
        keys: tuple[str, ...] = (),
        tokens: tuple[HerdrDisplayTokenDAO, ...] = (),
    ) -> HerdrCliCommandDAO:
        """Build semantic argv exclusively from captured ticket facts, without I/O."""
        if ticket.operation in ("activation_release", "replace_release", "shutdown_release"):
            return HerdrCliCommandDAO(
                argv=(
                    "pane",
                    "release-agent",
                    self._config.pane_id,
                    "--source",
                    "custom:slo",
                    "--agent",
                    "slo",
                    "--seq",
                    str(ticket.sequence),
                )
            )
        if ticket.operation in ("clear", "set", "shutdown_clear"):
            return self._metadata_command(sequence=ticket.sequence, keys=keys, tokens=tokens)
        publication = ticket.publication
        assert publication is not None
        snapshot = publication.snapshot
        argv: tuple[str, ...] = (
            "pane",
            "report-agent",
            self._config.pane_id,
            "--source",
            "custom:slo",
            "--agent",
            "slo",
            "--state",
            snapshot.state,
            "--seq",
            str(ticket.sequence),
            "--agent-session-id",
            snapshot.session_id,
        )
        if snapshot.block_reason is not None:
            argv += ("--message", snapshot.block_reason)
        if ticket.operation == "restore":
            assert ticket.saved is not None
            resume = self._build_resume_argv(publication=publication, saved=ticket.saved)
            if resume:
                argv += ("--", *resume)
        return HerdrCliCommandDAO(argv=argv)

    def _build_resume_argv(
        self, *, publication: HerdrPublicationDAO, saved: HerdrSavedRestoreDAO
    ) -> tuple[str, ...]:
        """Emit only canonical identity and opaque reference from exact saved policy."""
        if (
            not self._resume_available
            or not self._matches_save(saved=saved)
            or publication.snapshot.session_id != saved.capture.config.session_id
            or publication.restore_capture != saved.capture
            or publication.configuration_generation != saved.configuration_generation
            or not is_canonical_uuid_session_id(value=publication.snapshot.session_id)
        ):
            self._withdrawal_pending |= self._binding is not None and self._binding.reference is not None
            return ()
        argv = (
            "slo",
            "--resume",
            publication.snapshot.session_id,
            "--herdr-restore",
            saved.reference.restore_reference,
        )
        if not self._resume_argv_is_safe(argv=argv):
            self._withdrawal_pending |= self._binding is not None and self._binding.reference is not None
            return ()
        return argv

    @classmethod
    def _resume_argv_is_safe(cls, *, argv: tuple[str, ...]) -> bool:
        """Validate the bounded plain-launcher wire contract before advertisement.

        Args:
            argv (tuple[str, ...]): Complete private resume argument vector.

        Returns:
            bool: Whether every argument satisfies the native restore wire limits.
        """
        if not argv or argv[0] != "slo" or len(argv) > 64:
            return False
        if any(
            "'" in word or any(unicodedata.category(char).startswith("C") for char in word) for word in argv
        ):
            return False
        return len(" ".join(argv).encode("utf-8")) <= 8192

    def _metadata_command(
        self, *, sequence: int, keys: tuple[str, ...] = (), tokens: tuple[HerdrDisplayTokenDAO, ...] = ()
    ) -> HerdrCliCommandDAO:
        """Create one bounded explicit patch with five-second expiry."""
        names = keys or tuple(token.key for token in tokens)
        if (
            bool(keys) == bool(tokens)
            or not 1 <= len(names) <= 16
            or len(set(names)) != len(names)
            or any(key not in HERDR_TOKEN_KEYS for key in names)
        ):
            raise ValueError("report_payload_invalid")
        argv: tuple[str, ...] = (
            "pane",
            "report-metadata",
            self._config.pane_id,
            "--source",
            "custom:slo-display",
            "--agent",
            "slo",
            "--applies-to-source",
            "custom:slo",
            "--display-agent",
            "Slo",
        )
        for key in keys:
            argv += ("--clear-token", key)
        for token in tokens:
            argv += ("--token", f"{token.key}={token.value}")
        return HerdrCliCommandDAO(argv=argv + ("--ttl-ms", "5000", "--seq", str(sequence)))

    async def _send_report_operation(
        self,
        *,
        operation: HerdrReportOperation,
        publication: HerdrPublicationDAO,
        revision: int,
        saved: Optional[HerdrSavedRestoreDAO] = None,
        binding: Optional[HerdrRemoteBindingDAO] = None,
        keys: tuple[str, ...] = (),
        tokens: tuple[HerdrDisplayTokenDAO, ...] = (),
        display_final: bool = False,
    ) -> bool:
        """Validate, reserve and send once; lock-held admission remains authoritative."""
        self._validate_report_payload(
            operation=operation, saved=saved, binding=binding, keys=keys, tokens=tokens
        )
        ticket = await self._reserve_ticket(
            operation=operation,
            publication=publication,
            revision=revision,
            saved=saved,
            binding=binding,
            display_final=display_final,
        )
        if ticket is None:
            return False
        result = await self._transport.invoke(
            command=self._command_for_ticket(ticket=ticket, keys=keys, tokens=tokens),
            admission=HerdrReporterAdmission(reporter=self, ticket=ticket),
        )
        return (
            not self._transport.closed
            and result.outcome.status == "ok"
            and self._is_current(
                configuration_generation=publication.configuration_generation, revision=revision
            )
        )

    def _validate_report_payload(
        self,
        *,
        operation: HerdrReportOperation,
        saved: Optional[HerdrSavedRestoreDAO],
        binding: Optional[HerdrRemoteBindingDAO],
        keys: tuple[str, ...],
        tokens: tuple[HerdrDisplayTokenDAO, ...],
    ) -> None:
        """Reject malformed patches before consuming any durable sequence."""
        if operation in ("clear", "set"):
            if (operation == "clear") != bool(keys):
                raise ValueError("report_payload_invalid")
            self._metadata_command(sequence=0, keys=keys, tokens=tokens)
            return
        if keys or tokens or (operation == "restore" and saved is None):
            raise ValueError("report_payload_invalid")
        if operation == "replace_release" and binding is None:
            raise ValueError("report_payload_invalid")

    async def _prepare_binding(self, *, publication: HerdrPublicationDAO, revision: int) -> bool:
        """Stop replacement at uncertain withdrawal; never display on conflicting policy."""
        if self._needs_release(publication=publication):
            if not await self._send_report_operation(
                operation="replace_release", publication=publication, revision=revision, binding=self._binding
            ):
                return False
        if self._binding is not None and self._binding.certainty == "confirmed":
            return self._is_current(
                configuration_generation=publication.configuration_generation, revision=revision
            )
        return await self._send_report_operation(
            operation="claim", publication=publication, revision=revision
        )

    async def _report_lifecycle(self, *, publication: HerdrPublicationDAO, revision: int) -> bool:
        """Send semantic changes only; display-only updates do not announce lifecycle."""
        if not self._is_current(
            configuration_generation=publication.configuration_generation, revision=revision
        ):
            return False
        desired = HerdrLifecycleAcknowledgementDAO(
            configuration_generation=publication.configuration_generation,
            session_id=publication.snapshot.session_id,
            state=publication.snapshot.state,
            block_reason=publication.snapshot.block_reason,
        )
        if desired == self._lifecycle_ack:
            return True
        return await self._send_report_operation(
            operation="lifecycle", publication=publication, revision=revision
        )

    async def _report_resume(self, *, publication: HerdrPublicationDAO, revision: int) -> None:
        """Install exact durable policy once per batch until acknowledged."""
        saved = self._saved
        if (
            saved is None
            or not self._build_resume_argv(publication=publication, saved=saved)
            or saved == self._restore_ack
        ):
            return
        await self._send_report_operation(
            operation="restore", publication=publication, revision=revision, saved=saved
        )

    async def _report_metadata(self, *, publication: HerdrPublicationDAO, revision: int) -> None:
        """Clear all absent inventory first; stop display at the first failed patch."""
        tokens = publication.snapshot.tokens
        present = {token.key for token in tokens}
        absent = tuple(key for key in HERDR_TOKEN_KEYS if key not in present)
        patches = tuple(absent[index : index + 16] for index in range(0, len(absent), 16))
        for index, keys in enumerate(patches):
            if not await self._send_report_operation(
                operation="clear",
                publication=publication,
                revision=revision,
                keys=keys,
                display_final=not tokens and index == len(patches) - 1,
            ):
                return
        if tokens:
            await self._send_report_operation(
                operation="set", publication=publication, revision=revision, tokens=tokens, display_final=True
            )

    async def _publish_batch(self, *, publication: HerdrPublicationDAO, revision: int) -> None:
        """Bootstrap restore first; existing working precedes display, settlement follows it."""
        bootstrap = (
            self._binding is None
            or self._binding.certainty != "confirmed"
            or self._needs_release(publication=publication)
        )
        if not await self._prepare_binding(publication=publication, revision=revision):
            return
        if bootstrap:
            await self._report_resume(publication=publication, revision=revision)
        if publication.snapshot.state == "working":
            if not await self._report_lifecycle(publication=publication, revision=revision):
                return
        await self._report_metadata(publication=publication, revision=revision)
        await self._report_lifecycle(publication=publication, revision=revision)
        if not bootstrap:
            await self._report_resume(publication=publication, revision=revision)

    def _take_pending(self) -> Optional[HerdrPublicationDAO]:
        """Take the newest pointer and clear its wake before any worker await."""
        publication = self._pending
        self._pending = None
        self._wake.clear()
        return publication

    @classmethod
    def _plain_slo_available(cls) -> bool:
        """Probe PATH off-loop; filesystem refusal makes restore unavailable only."""
        try:
            return shutil.which(cmd="slo") is not None
        except OSError:
            return False

    async def _consume_publication(self, *, publication: HerdrPublicationDAO) -> None:
        """Continue with newest display only when the same exact save still applies."""
        await self._ensure_saved_restore(publication=publication)
        self._resume_available = await asyncio.to_thread(self._plain_slo_available)
        if not self._resume_available:
            self._log_failure(category="restore_path_unavailable")
            self._withdrawal_pending |= self._binding is not None and self._binding.reference is not None
        else:
            self._record_recovery(category="restore_path_unavailable")
        latest = self._latest
        if latest is None or not self._same_configuration(left=publication, right=latest):
            return
        if self._pending is latest:
            self._take_pending()
        await self._publish_batch(publication=latest, revision=self._revision)

    async def _consume_pending(self) -> None:
        """Consume one replaceable slot until lifetime revocation or worker cancellation."""
        while not self._ordinary_revoked and not self._closing and not self._disabled:
            if self._pending is None:
                await self._wake.wait()
            publication = self._take_pending()
            if publication is not None:
                await self._consume_publication(publication=publication)

    async def _send_release(self, *, operation: HerdrReportOperation) -> None:
        """Send one lifetime release only with a newly durable reservation."""
        ticket = await self._reserve_ticket(operation=operation, binding=self._binding)
        if ticket is None:
            return
        await self._transport.invoke(
            command=self._command_for_ticket(ticket=ticket),
            admission=HerdrReporterAdmission(reporter=self, ticket=ticket),
        )

    async def _shutdown_release(self) -> None:
        """Clear display only after confirmed remote withdrawal."""
        await self._send_release(operation="shutdown_release")
        if not self._shutdown_released:
            return
        for keys in (HERDR_TOKEN_KEYS[:16], HERDR_TOKEN_KEYS[16:]):
            ticket = await self._reserve_ticket(operation="shutdown_clear")
            if ticket is None:
                return
            result = await self._transport.invoke(
                command=self._command_for_ticket(ticket=ticket, keys=keys),
                admission=HerdrReporterAdmission(reporter=self, ticket=ticket),
            )
            if result.outcome.status != "ok":
                return

    async def close(self) -> HerdrReporterCloseOutcomeDAO:
        """Withdraw remotely after joining producers, retaining the normal pane lease.

        Session calls this after viewer close and before close_transport. The
        two-second remote budget excludes local writes and OS reap latency.

        Returns:
            HerdrReporterCloseOutcomeDAO: Cached remote/sticky-defect evidence;
                default drained resources are NOT permission to discard this owner.

        Raises:
            asyncio.CancelledError: Caller cancellation, only after shutdown joins.
        """
        self.revoke_viewer_admission()
        if self._close_task is None:
            self._closing = True
            self._close_token = 1
            self._close_task = asyncio.create_task(coro=self._close_once())
        cancelled = await HerdrTaskJoin.wait(task=self._close_task)
        outcome = self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _close_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Drain every local producer before starting the remote-only shutdown budget."""
        await self._join_optional_task(task=self._start_task)
        for task in (self._refresh_task, self._worker):
            if task is not None:
                task.cancel()
                await self._join_optional_task(task=task)
        await self._join_optional_task(task=self._save_task)
        await self._join_optional_task(task=self._reservation_task)
        if self._binding is not None and not self._sequence_safe:
            self._log_failure(category="release_unavailable")
        if self._binding is not None and self._sequence_safe:
            self._close_deadline = asyncio.get_running_loop().time() + 2.0
            try:
                async with asyncio.timeout_at(when=self._close_deadline):
                    await self._shutdown_release()
            except Exception:
                self._cleanup_failed = True
                self._log_failure(category="release_unavailable")
        return self._close_outcome()

    async def _join_optional_task(self, *, task: Optional[asyncio.Task[object]] = None) -> None:
        """Retrieve owned failures while allowing all remaining cleanup to proceed."""
        if task is None:
            return
        await HerdrTaskJoin.wait(task=task)
        if not task.cancelled() and task.exception() is not None:
            self._cleanup_failed = True
            self._log_failure(category="cleanup_unavailable")

    def _close_outcome(self) -> HerdrReporterCloseOutcomeDAO:
        """Project remote/sticky defects; normal intermediate lease retention is not a defect."""
        uncertain = (
            self._cleanup_failed
            or self._binding is not None
            or (self._activation_attempted and not self._activation_released)
        )
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain" if uncertain else "safe",
        )

    @property
    def retains_external_resources(self) -> bool:
        """Expose retained local ownership independently of remote uncertainty."""
        return (
            self._sequence_store.retains_external_resources
            or not self._transport.resources_drained
            or (
                isinstance(self._restore_store, HerdrRestoreResourceOwner)
                and self._restore_store.retains_external_resources
            )
        )

    async def _release_restore_lease(self) -> None:
        """Join saves before inspecting retained store ownership off-loop.

        Save-only injected collaborators own no cleanup contract. Concrete stores
        retain ambiguous descriptors; failure is sticky and never grants disposal.
        """
        await self._join_optional_task(task=self._save_task)
        if not isinstance(self._restore_store, HerdrRestoreResourceOwner):
            return
        self._cleanup_failed |= self._restore_store.retains_external_resources
        task = asyncio.create_task(coro=asyncio.to_thread(self._restore_store.close))
        await self._join_optional_task(task=task)

    async def _release_lease(self) -> None:
        """Unlock only after transport is sealed and all owned process handles are drained."""
        if not self._sequence_store.retains_external_resources:
            return
        if not self._transport.closed or not self._transport.resources_drained:
            self._cleanup_failed = True
            return
        self._lease_task = asyncio.create_task(coro=asyncio.to_thread(self._sequence_store.close))
        await self._join_optional_task(task=self._lease_task)
        if self._lease_task.cancelled() or self._lease_task.exception() is not None:
            self._cleanup_failed = True
            return
        self._lease_task = None
        self._lease_held = False

    async def close_transport(self) -> HerdrReporterCloseOutcomeDAO:
        """Drain transport and release local leases after viewer and reporter close.

        Session must retain this reporter if final resources remain retained.
        A successful local drain never erases prior remote or cleanup uncertainty.

        Returns:
            HerdrReporterCloseOutcomeDAO: Cached final replacement and disposal evidence.

        Raises:
            asyncio.CancelledError: Caller cancellation after the owned cleanup joins.
        """
        self.revoke_viewer_admission()
        if self._transport_close_task is None:
            self._transport_close_task = asyncio.create_task(coro=self._close_transport_once())
        cancelled = await HerdrTaskJoin.wait(task=self._transport_close_task)
        outcome = self._transport_close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _close_transport_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Seal and drain shared mechanics before releasing the local pane lease."""
        try:
            outcome = await self._transport.close()
            self._cleanup_failed |= outcome.replacement == "uncertain"
        except Exception:
            self._cleanup_failed = True
            self._log_failure(category="cleanup_unavailable")
        await self._release_restore_lease()
        await self._release_lease()
        if self.retains_external_resources:
            return HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained")
        return self._close_outcome()

    async def drain_retained_external_resources(self) -> HerdrReporterCloseOutcomeDAO:
        """Join one final local-only drain after an incomplete final close.

        Never resend withdrawal or retry an ambiguous descriptor close. The session
        must keep this owner reachable while resources remain retained.

        Returns:
            HerdrReporterCloseOutcomeDAO: Sticky uncertain replacement and actual
                retained/drained local evidence, cached across callers.

        Raises:
            asyncio.CancelledError: Caller cancellation after the drain task joins.
        """
        if self._retired_reporter_drain_task is None:
            self._retired_reporter_drain_task = asyncio.create_task(coro=self._drain_retired_reporter_once())
        cancelled = await HerdrTaskJoin.wait(task=self._retired_reporter_drain_task)
        outcome = self._retired_reporter_drain_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _drain_retired_reporter_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Preserve sticky uncertainty after late transport drain and lease release."""
        self._cleanup_failed = True
        try:
            await self._transport.drain_retained_resources()
        except Exception:
            self._log_failure(category="cleanup_unavailable")
        await self._release_restore_lease()
        await self._release_lease()
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain", resources="retained" if self.retains_external_resources else "drained"
        )

    def build_visualizer(self) -> HerdrVisualizerLauncher:
        """Build the session-owned viewer sharing this transport and live admission.

        Returns:
            HerdrVisualizerLauncher: Inert one-shot viewer, closed by the session
                before reporter withdrawal and final transport close.

        Raises:
            HerdrRestoreUnavailableError: Reporter lacks current viewer authority.
        """
        if not self.allows_viewer_admission():
            raise HerdrRestoreUnavailableError()
        from .visualizer import HerdrVisualizerLauncher

        return HerdrVisualizerLauncher(
            transport=self._transport,
            owner_pane_id=self._config.pane_id,
            authority=self.allows_viewer_admission,
        )

    def record_publication_failure(self) -> None:
        """Report a fixed session-publication boundary failure without caller text."""
        self._log_failure(category="publication_failed")

    def _log_failure(
        self,
        *,
        category: Literal[
            "publication_failed",
            "restore_save_unavailable",
            "restore_path_unavailable",
            "restore_unavailable",
            "sequence_unavailable",
            "activation_unavailable",
            "release_unavailable",
            "cleanup_unavailable",
        ],
    ) -> None:
        """Rate-limit fixed diagnostics; sink failure cannot interrupt resource ownership."""
        self._diagnostic_failures.add(category)
        now = time.monotonic()
        previous = self._diagnostic_times.get(category)
        if previous is not None and now - previous < 60:
            return
        self._diagnostic_times[category] = now
        try:
            logging.getLogger(__name__).warning("herdr_" + category)
        except Exception:
            pass

    def _record_recovery(self, *, category: str) -> None:
        """Emit one fixed recovery after a recorded failure, never caller data.

        Args:
            category (str): Previously recorded internal diagnostic category.
        """
        if category not in self._diagnostic_failures:
            return
        self._diagnostic_failures.remove(category)
        try:
            logging.getLogger(__name__).warning("herdr_" + category + "_recovered")
        except Exception:
            pass

    @classmethod
    def build(
        cls,
        *,
        environment: Mapping[str, str],
        state_root: Path,
        restore_store: Optional[HerdrRestoreStoreProtocol] = None,
    ) -> HerdrReporterProtocol:
        """Build inert reporting for session activation, without filesystem probes.

        Disabled/outside paths return null before constructing stores. Invalid
        enabled configuration returns unavailable, never platform fallback.

        Args:
            environment (Mapping[str, str]): Captured inherited settings; copied
                into validated configuration and a transport allowlist.
            state_root (Path): Private integration state root used only on activation.
            restore_store (Optional[HerdrRestoreStoreProtocol]): Save collaborator;
                defaults to None to construct the concrete private store.

        Returns:
            HerdrReporterProtocol: Inert real or null owner; caller owns start/close.
        """
        config = HerdrEnvironmentGate.build(environment=environment, state_root=state_root)
        if not isinstance(config, HerdrReporterConfigDAO):
            return config
        if restore_store is None:
            from .restore import HerdrRestoreStore

            restore_store = HerdrRestoreStore(state_root=state_root)
        return cls(
            config=config,
            transport=HerdrCliTransport(config=config, environment=environment),
            sequence_store=HerdrSequenceStore(
                state_root=state_root,
                socket_namespace=config.socket_path or "default",
                pane_id=config.pane_id,
            ),
            restore_store=restore_store,
        )

    @property
    def destination(self) -> HerdrDestination:
        """Route only with live pane authority; failed activation never falls back."""
        return "herdr" if self.allows_viewer_admission() else "unavailable"

    def _validate_executable(self) -> None:
        """Check captured executable off-loop without searching PATH for a replacement."""
        path = self._config.binary_path
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or not os.access(path, os.X_OK):
            raise HerdrRestoreUnavailableError()

    async def start(self) -> None:
        """Activate once for the session, acquiring a lease before remote release.

        Worker/refresh begin only after confirmed activation withdrawal. Ordinary
        failures disable integration and drain locally; destination reports failure.
        Repeated calls join the same task; closed/disabled owners do nothing.

        Raises:
            asyncio.CancelledError: After activation and reporter close join.
                Caller still owns final transport close and retained-resource drain.
        """
        if self._closing or self._disabled:
            return
        if self._start_task is None:
            self._start_task = asyncio.create_task(coro=self._activate())
        cancelled = await HerdrTaskJoin.wait(task=self._start_task)
        self._start_task.result()
        if cancelled:
            await self.close()
            raise asyncio.CancelledError

    async def _activate(self) -> None:
        """Acquire secure local ownership, then confirm retained remote withdrawal."""
        self._activation_attempted = self._starting = True
        try:
            await asyncio.to_thread(self._validate_executable)
            self._lease_task = asyncio.create_task(coro=asyncio.to_thread(self._sequence_store.acquire))
            await HerdrTaskJoin.wait(task=self._lease_task)
            self._lease_task.result()
            self._lease_task = None
            self._lease_held = True
            await self._send_release(operation="activation_release")
            if self._ordinary_revoked or self._closing or not self._activation_released:
                self._disabled = True
            else:
                self._worker = asyncio.create_task(coro=self._consume_pending())
                self._refresh_task = asyncio.create_task(coro=self._refresh_publication())
                self._worker.add_done_callback(self._on_background_done)
                self._refresh_task.add_done_callback(self._on_background_done)
        except Exception:
            self._disabled = True
            self._log_failure(category="activation_unavailable")
        finally:
            self._starting = False
            if self._disabled or self._closing:
                await self.close_transport()

    def _on_background_done(self, task: asyncio.Task[None]) -> None:
        """Retrieve producer defects immediately without exposing private exceptions.

        Args:
            task (asyncio.Task[None]): Retained worker or refresh task finishing its lifetime.
        """
        if task.cancelled():
            return
        if task.exception() is not None:
            self._disabled = True
            self._cleanup_failed = True
            self._log_failure(category="cleanup_unavailable")

    async def _refresh_publication(self) -> None:
        """Renew latest display every two seconds without changing its revision."""
        while not self._ordinary_revoked and not self._closing and not self._disabled:
            await asyncio.sleep(delay=2.0)
            if (
                self._latest is not None
                and not self._ordinary_revoked
                and not self._closing
                and not self._disabled
            ):
                self._pending = self._latest
                self._wake.set()


class HerdrReporterAdmission:
    """Bind one immutable reporter ticket to the shared transport's lock boundary."""

    def __init__(self, *, reporter: HerdrReporter, ticket: HerdrReportTicketDAO) -> None:
        """Capture one non-reusable authority before transport lock wait.

        Args:
            reporter (HerdrReporter): Live policy and remote-effect accounting owner.
            ticket (HerdrReportTicketDAO): Exact immutable reservation to admit.
        """
        self._reporter = reporter
        self._ticket = ticket
        self._attempted = self._admitted = self._completed = False

    def try_admit(self) -> bool:
        """Consume one attempt synchronously under the transport lock.

        Returns:
            bool: Whether current reporter policy commits this reserved command;
                false consumes the attempt without permitting spawn.
        """
        if self._attempted:
            return False
        self._attempted = True
        self._admitted = self._reporter._admit_command(ticket=self._ticket)
        return self._admitted

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Account admitted effects once before unlock, including superseded results.

        Args:
            result (HerdrCommandResultDAO): Actual invocation outcome; uncertain
                effects do not acknowledge a newer publication. Unadmitted or
                already-completed attempts are ignored.
        """
        if not self._admitted or self._completed:
            return
        self._completed = True
        self._reporter._record_command_result(ticket=self._ticket, result=result)
