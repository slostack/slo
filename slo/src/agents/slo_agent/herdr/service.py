"""Herdr-only transport mechanics and pure observation support; no session assembly."""

from __future__ import annotations

import asyncio
import os
import signal
import math
import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NoReturn, Optional, TypeVar

from .dao import (
    HerdrCliCommandDAO,
    HerdrCommandAdmission,
    HerdrCommandResultDAO,
    HerdrCommandOutcomeDAO,
    HerdrCommandStatus,
    HerdrReporterConfigDAO,
    HerdrReporterCloseOutcomeDAO,
)

from .dao import HerdrDisplayKey, HerdrDisplayTokenDAO, HerdrReportSnapshotDAO
from src.agents.slo_agent.sessions.dao import OperatorAttentionReason
from src.agents.slo_agent.sessions.identity import is_canonical_uuid_session_id
from src.agents.slo_agent.sessions.token_format import CompactTokenFormatter
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO

from .dao import HerdrDestination, HerdrPublicationDAO, HerdrRestoreUnavailableError

T = TypeVar("T")


class NullHerdrReporter:
    """Inert reporting lifetime; never allocates tasks, stores or process resources."""

    def __init__(self, *, destination: HerdrDestination) -> None:
        """Retain the session's inert destination without acquiring resources.

        Args:
            destination (HerdrDestination): Captured routing classification;
                gate callers supply platform or unavailable.
        """
        self.destination = destination

    async def start(self) -> None:
        """Do no activation work."""

    def publish(self, *, publication: HerdrPublicationDAO) -> None:
        """Discard facts without capture, projection, validation or I/O.

        Args:
            publication (HerdrPublicationDAO): Ignored session publication;
                no reference is retained.
        """

    async def close(self) -> HerdrReporterCloseOutcomeDAO:
        """Return safe no-resource evidence."""
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    async def close_transport(self) -> HerdrReporterCloseOutcomeDAO:
        """Prove the inert owner's drain independently of intermediate close faults."""
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    async def drain_retained_external_resources(self) -> HerdrReporterCloseOutcomeDAO:
        """Prove no local work exists without retrying intermediate close."""
        return HerdrReporterCloseOutcomeDAO(replacement="safe")

    @property
    def retains_external_resources(self) -> bool:
        """Never claim external ownership."""
        return False

    def allows_viewer_admission(self) -> bool:
        """Never grant Herdr pane authority."""
        return False

    def revoke_viewer_admission(self) -> None:
        """No permission exists to revoke."""

    def record_publication_failure(self) -> None:
        """Disabled reporting emits no diagnostics."""

    def build_visualizer(self) -> NoReturn:
        """Refuse viewer construction on the inert session path.

        Raises:
            HerdrRestoreUnavailableError: Always; null owners grant no pane authority.
        """
        raise HerdrRestoreUnavailableError


class HerdrEnvironmentGate:
    """Pure capture only; enabled reporter assembly remains with the later reporter."""

    # Gate instances do not survive a refused build. Retain only fixed category
    # timestamps, never configuration or reporter instances, across those builds.
    _failure_times: dict[str, float] = {}

    @classmethod
    def build(
        cls, *, environment: Mapping[str, str], state_root: Path
    ) -> NullHerdrReporter | HerdrReporterConfigDAO:
        """Classify captured settings without filesystem probes or resource acquisition.

        Args:
            environment (Mapping[str, str]): Inherited settings captured by session.
            state_root (Path): Lexically validated private integration root.

        Returns:
            NullHerdrReporter | HerdrReporterConfigDAO: Platform null for outside/
                disabled, unavailable null for invalid enabled settings, otherwise
                immutable config. Invalid metadata profile defaults to compact
                with a fixed diagnostic, never arbitrary public labels.
        """
        disabled = environment.get("SLO_HERDR_DISABLED", "").strip().lower()
        if disabled in ("1", "true", "yes", "on") or environment.get("HERDR_ENV") != "1":
            return NullHerdrReporter(destination="platform")
        if disabled not in ("", "0", "false", "no", "off"):
            cls._log_configuration_failure(category="invalid_configuration")
            return NullHerdrReporter(destination="unavailable")
        profile_value = environment.get("SLO_HERDR_METADATA_PROFILE", "compact")
        if profile_value not in ("compact", "detail"):
            cls._log_configuration_failure(category="invalid_metadata_profile")
        try:
            profile: Literal["compact", "detail"] = (
                "detail" if environment.get("SLO_HERDR_METADATA_PROFILE") == "detail" else "compact"
            )
            config = HerdrReporterConfigDAO(
                pane_id=environment.get("HERDR_PANE_ID", ""),
                binary_path=Path(environment.get("HERDR_BIN_PATH", "")),
                state_root=state_root,
                socket_path=environment.get("HERDR_SOCKET_PATH"),
                metadata_profile=profile,
            )
            cls._record_configuration_recovery(category="invalid_configuration")
            if profile_value in ("compact", "detail"):
                cls._record_configuration_recovery(category="invalid_metadata_profile")
            return config
        except ValueError:
            cls._log_configuration_failure(category="invalid_configuration")
            return NullHerdrReporter(destination="unavailable")

    @classmethod
    def _record_configuration_recovery(
        cls, *, category: Literal["invalid_configuration", "invalid_metadata_profile"]
    ) -> None:
        """End one gate failure episode after valid capture, never on disabled builds."""
        if cls._failure_times.pop(category, None) is None:
            return
        try:
            logging.getLogger(__name__).warning("herdr_" + category + "_recovered")
        except Exception:
            pass

    @classmethod
    def _log_configuration_failure(
        cls, *, category: Literal["invalid_configuration", "invalid_metadata_profile"]
    ) -> None:
        """Emit one fixed diagnostic during capture without exposing configuration.

        Args:
            category: Closed configuration failure vocabulary; never caller text.
        """
        now = time.monotonic()
        previous = cls._failure_times.get(category)
        if previous is not None and now - previous < 60.0:
            return
        cls._failure_times[category] = now
        try:
            logging.getLogger(__name__).warning("herdr_" + category)
        except Exception:
            pass


class HerdrSnapshotProjector:
    """Project numeric session truth without ever inspecting arbitrary labels."""

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        state: Literal["idle", "working", "blocked"],
        history_enabled: bool,
        usage: SessionUsageSnapshotDAO,
        metadata_profile: Literal["compact", "detail"] = "compact",
        block_reason: Optional[OperatorAttentionReason] = None,
    ) -> HerdrReportSnapshotDAO:
        """Project committed session facts without I/O or a second token counter.

        Args:
            session_id (str): Exact canonical UUID identity.
            state (Literal["idle", "working", "blocked"]): Committed lifecycle state.
            history_enabled (bool): Whether cumulative session telemetry is meaningful.
            usage (SessionUsageSnapshotDAO): Existing accounting snapshot; never mutated.
            metadata_profile (Literal["compact", "detail"]): Fixed display policy;
                defaults to compact.
            block_reason (Optional[OperatorAttentionReason]): Required only for
                blocked state; defaults to None.

        Returns:
            HerdrReportSnapshotDAO: Frozen fixed-vocabulary/numeric display; unsafe
                values are omitted, private restore policy remains with the caller.

        Raises:
            ValueError: Invalid identity or inconsistent snapshot lifecycle fields.
        """
        if not is_canonical_uuid_session_id(value=session_id):
            raise ValueError("Invalid Herdr identity.")
        tokens = (
            cls._detail(usage=usage, history_enabled=history_enabled)
            if metadata_profile == "detail"
            else cls._compact(usage=usage, history_enabled=history_enabled)
        )
        return HerdrReportSnapshotDAO(
            session_id=session_id,
            state=state,
            block_reason=block_reason,
            tokens=tuple(token for token in tokens if token is not None),
        )

    @classmethod
    def _detail(
        cls, *, usage: SessionUsageSnapshotDAO, history_enabled: bool
    ) -> tuple[Optional[HerdrDisplayTokenDAO], ...]:
        """Emit fixed reasoning and numeric detail in inventory order, never labels."""
        reasoning = usage.active_reasoning_level
        fixed = next(
            (
                level
                for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max")
                if reasoning == level
            ),
            None,
        )
        turn = usage.latest_turn
        totals = usage.session_totals
        return (
            cls._make_token(key="reasoning", value=fixed) if fixed is not None else None,
            cls._number(key="turn", value=turn.total_tokens) if usage.usage_available else None,
            cls._number(key="in", value=turn.input_tokens) if usage.usage_available else None,
            cls._number(key="out", value=turn.output_tokens) if usage.usage_available else None,
            cls._number(key="cache_read", value=totals.cache_read_input_tokens),
            cls._number(key="cache_write", value=totals.cache_creation_input_tokens),
            cls._context(usage=usage, history_enabled=history_enabled, detail=True, remaining=True),
            (
                cls._make_token(key="rpm", value=str(usage.requests_per_minute_limit))
                if cls._renderable(value=usage.requests_per_minute_limit)
                else None
            ),
            cls._number(key="tpm", value=usage.tokens_per_minute_limit),
            cls._number(key="out_cap", value=usage.output_cap_tokens),
            cls._number(key="budget", value=usage.provider_budget_tokens),
            cls._context(usage=usage, history_enabled=history_enabled, detail=True),
        )

    @classmethod
    def _context(
        cls, *, usage: SessionUsageSnapshotDAO, history_enabled: bool, detail: bool, remaining: bool = False
    ) -> Optional[HerdrDisplayTokenDAO]:
        """Gate estimates on durable history and independently valid numeric values."""
        context = usage.context_window_snapshot
        if not history_enabled or context is None or not context.estimate_available:
            return None
        value = context.available_tokens if remaining else context.consumed_percent
        if not cls._renderable(value=value):
            return None
        text = CompactTokenFormatter.format(count=context.available_tokens) if remaining else f"{value:.1f}%"
        return cls._make_token(
            key="context_left" if remaining else "context", value=text + (" estimated" if detail else "")
        )

    @classmethod
    def _compact(
        cls, *, usage: SessionUsageSnapshotDAO, history_enabled: bool
    ) -> tuple[Optional[HerdrDisplayTokenDAO], ...]:
        """Retain known cumulative zero; omit absent or nonpositive cooldown."""
        cooldown = usage.cooldown_seconds_remaining
        return (
            cls._number(key="session_tokens", value=usage.session_totals.total_tokens),
            cls._context(usage=usage, history_enabled=history_enabled, detail=False),
            (
                cls._make_token(key="cooldown", value=f"{cooldown}s")
                if cls._renderable(value=cooldown) and cooldown is not None and cooldown > 0
                else None
            ),
        )

    @classmethod
    def _number(cls, *, key: HerdrDisplayKey, value: Optional[int]) -> Optional[HerdrDisplayTokenDAO]:
        """Use the existing shared formatter only for known nonnegative counts."""
        if not cls._finite(value=value) or value is None:
            return None
        # Even the largest compact unit cannot fit this count into 80 characters.
        # Check before decimal conversion, which also has an interpreter safety limit.
        if value >= 10**85:
            return None
        return cls._make_token(key=key, value=CompactTokenFormatter.format(count=value))

    @classmethod
    def _renderable(cls, *, value: object) -> bool:
        """Bound conversion before formatting telemetry for the public token guard.

        Args:
            value (object): Optional numeric observation, never a free-text label.

        Returns:
            bool: Whether conversion is safe; the final token guard enforces length.
        """
        return cls._finite(value=value) and isinstance(value, (int, float)) and value < 10**85

    @classmethod
    def _finite(cls, *, value: object) -> bool:
        """Reject unknown, negative, boolean and nonfinite telemetry."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if isinstance(value, int):
            return value >= 0
        return math.isfinite(value) and value >= 0

    @classmethod
    def _make_token(cls, *, key: HerdrDisplayKey, value: str) -> Optional[HerdrDisplayTokenDAO]:
        """Omit one invalid generated value using the shared DAO boundary."""
        if not HerdrDisplayTokenDAO._safe_token_value(value=value):
            return None
        return HerdrDisplayTokenDAO(key=key, value=value)


class HerdrTaskJoin:
    """Join retained work without transferring its cancellation ownership."""

    @classmethod
    async def wait(cls, *, task: asyncio.Task[T]) -> bool:
        """Retrieve terminal work before its owner may release resources.

        Lifecycle owners use this on their own event loop. Caller cancellation
        is consumed while shielding the retained task; the caller decides when
        to re-raise it after cleanup. Task exceptions are retrieved, not raised
        or returned; owners inspect the terminal task separately. There is no
        timeout and this helper never transfers cleanup ownership.

        Args:
            task (asyncio.Task[T]): Retained task; never cancelled here.

        Returns:
            bool: Whether cancellation interrupted this caller while joining.
        """
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(arg=task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        return cancelled


class HerdrTransportAdmission:
    """Retain invocation-local authority without owning reporter/viewer policy."""

    def __init__(self, *, delegate: HerdrCommandAdmission) -> None:
        """Capture mandatory policy for one invocation without transferring ownership.

        Args:
            delegate (HerdrCommandAdmission): Synchronous lock-held owner callbacks.
        """
        self._delegate = delegate
        self._attempted = False
        self._completed = False
        self.admitted = False

    def try_admit(self) -> bool:
        """Consume one attempt under the transport lock before tracked spawn.

        Returns:
            bool: Delegate authority on first attempt, otherwise false.

        Raises:
            Exception: Delegate failure propagates to the transport boundary;
                the attempt remains consumed and must not be retried.
        """
        if self._attempted:
            return False
        self._attempted = True
        self.admitted = self._delegate.try_admit()
        return self.admitted

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Account admitted work at most once before transport unlocks.

        Args:
            result (HerdrCommandResultDAO): Terminal invocation-local evidence.

        Raises:
            Exception: Delegate failure propagates to transport's fixed diagnostic
                boundary; completion remains consumed and is never retried.
        """
        if not self.admitted or self._completed:
            return
        self._completed = True
        self._delegate.complete(result=result)


class HerdrOutputLimitError(Exception):
    """Private empty-message signal; output must never enter diagnostics."""


class HerdrCliTransport:
    """Own the one shared command lock, spawn task and process for a session."""

    def __init__(self, *, config: HerdrReporterConfigDAO, environment: Mapping[str, str]) -> None:
        """Capture transport inputs without I/O for one session-owned lifetime.

        Args:
            config (HerdrReporterConfigDAO): Validated pane/executable/deadline policy.
            environment (Mapping[str, str]): Inherited values copied through the
                fixed non-secret allowlist; captured Herdr values come from config.
        """
        self._config = config
        basics = {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE"}
        self._environment = {key: value for key, value in environment.items() if key in basics}
        self._environment.update(
            HERDR_ENV="1", HERDR_PANE_ID=config.pane_id, HERDR_BIN_PATH=str(config.binary_path)
        )
        if config.socket_path is not None:
            self._environment["HERDR_SOCKET_PATH"] = config.socket_path
        self._command_lock = asyncio.Lock()
        self._spawn_task: Optional[asyncio.Task[asyncio.subprocess.Process]] = None
        self._active: Optional[asyncio.subprocess.Process] = None
        self._closed = False
        self._diagnostic_times: dict[str, float] = {}
        self._command_failure_active = False
        self._cleanup_failure_active = False
        self._cleanup_failed = False
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._transport_close_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._retired_transport_drain_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None

    @property
    def closed(self) -> bool:
        """Expose monotonic admission sealing to the authority owner."""
        return self._closed

    @property
    def resources_drained(self) -> bool:
        """Expose proven local drain, never remote withdrawal evidence."""
        return self._active is None and self._spawn_task is None

    async def close(self) -> HerdrReporterCloseOutcomeDAO:
        """Seal admission before joining one cached local drain attempt.

        Called after viewer/reporter shutdown. This sends no remote withdrawal;
        unresolved process handles remain owned and OS reap has no hard deadline.

        Returns:
            HerdrReporterCloseOutcomeDAO: Local disposal evidence and sticky cleanup
                uncertainty, not confirmation of remote withdrawal.

        Raises:
            asyncio.CancelledError: Caller cancellation after the drain task joins.
        """
        self._closed = True
        if self._transport_close_task is None:
            self._transport_close_task = asyncio.create_task(coro=self._close_transport_once())
        cancelled = await HerdrTaskJoin.wait(task=self._transport_close_task)
        outcome = self._transport_close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def drain_retained_resources(self) -> HerdrReporterCloseOutcomeDAO:
        """Join one final local-only attempt after close retained unresolved handles.

        No owner callback or remote command is repeated. The caller must retain
        this transport if disposal evidence remains retained.

        Returns:
            HerdrReporterCloseOutcomeDAO: Cached local evidence; prior cleanup
                uncertainty remains sticky even when late reap succeeds.

        Raises:
            asyncio.CancelledError: Caller cancellation after the drain task joins.
        """
        self._closed = True
        if self._retired_transport_drain_task is None:
            self._retired_transport_drain_task = asyncio.create_task(coro=self._close_transport_once())
        cancelled = await HerdrTaskJoin.wait(task=self._retired_transport_drain_task)
        outcome = self._retired_transport_drain_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _close_transport_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Wait behind admitted work and retain unresolved handles on drain failure."""
        async with self._command_lock:
            if not self.resources_drained:
                await self._drain_quarantined_resources()
            return HerdrReporterCloseOutcomeDAO(
                replacement="uncertain" if self._cleanup_failed or not self.resources_drained else "safe",
                resources="drained" if self.resources_drained else "retained",
            )

    async def _drain_quarantined_resources(self) -> None:
        """Clear ownership only after a successful reap; never repeat owner callbacks."""
        try:
            await self._drain_admitted(result=self._failure(status="unavailable", admitted=True))
        except Exception:
            self._cleanup_failed = True
            return
        self._active = None
        self._spawn_task = None
        self._record_cleanup_recovery()

    def _record_cleanup_recovery(self) -> None:
        """End the diagnostic episode after proven drain, retaining sticky uncertainty."""
        if not self._cleanup_failure_active:
            return
        self._cleanup_failure_active = False
        try:
            logging.getLogger(__name__).warning("herdr_cleanup_unavailable_recovered")
        except Exception:
            pass

    async def invoke(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Execute one command through lock-held owner admission and tracked cleanup.

        The command deadline includes lock wait, not a hard bound on OS reap.
        A timed-out waiter cannot clean up another invocation's process. Admitted
        work is joined and accounted before unlocking; failed cleanup retains its
        handles for close/final drain. No raw failed output reaches the caller.

        Args:
            command (HerdrCliCommandDAO): Validated argv and optional bounded JSON capture.
            admission (HerdrCommandAdmission): Synchronous owner policy and terminal
                accounting callback; admission runs under the shared command lock.

        Returns:
            HerdrCommandResultDAO: Invocation-local status/admission evidence, not
                proof of remote effect on timeout or cancellation.

        Raises:
            asyncio.CancelledError: Caller cancellation after owned cleanup joins.
        """
        tracked = HerdrTransportAdmission(delegate=admission)
        try:
            async with asyncio.timeout(delay=self._config.command_timeout_seconds):
                result = await self._invoke_locked(command=command, admission=tracked)
        except TimeoutError:
            result = self._failure(status="timeout", admitted=tracked.admitted)
        except Exception:
            result = self._failure(status="unavailable", admitted=tracked.admitted)
        self._record_command_diagnostic(result=result)
        return result

    def _record_command_diagnostic(self, *, result: HerdrCommandResultDAO) -> None:
        """Record bounded invocation failures and one recovery without private output.

        Args:
            result (HerdrCommandResultDAO): Safe terminal facts from this invocation.
        """
        if result.outcome.status == "suppressed":
            return
        if result.outcome.status != "ok":
            self._command_failure_active = True
            self._log_failure(category="command_unavailable")
            return
        if not self._command_failure_active:
            return
        self._command_failure_active = False
        try:
            logging.getLogger(__name__).warning("herdr_command_unavailable_recovered")
        except Exception:
            pass

    async def _invoke_locked(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Commit owner admission and tracked spawn in one uninterrupted event-loop turn."""
        async with self._command_lock:
            if self._closed or not admission.try_admit():
                return self._failure(status="suppressed")
            self._spawn_task = asyncio.create_task(coro=self._spawn(command=command))
            return await self._execute_admitted(command=command, admission=admission)

    async def _execute_admitted(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Keep the command lock until late spawn, reap and accounting all finish."""
        result = self._failure(status="cancelled", admitted=True)
        try:
            result = await self._observe_admitted(command=command)
            return result
        finally:
            self._cleanup_task = asyncio.create_task(
                coro=self._finish_admitted(admission=admission, result=result)
            )
            cancelled = await HerdrTaskJoin.wait(task=self._cleanup_task)
            try:
                self._cleanup_task.result()
            except Exception:
                self._closed = True
                self._cleanup_failed = True
                self._log_failure(category="cleanup_unavailable")
                self._complete_safely(
                    admission=admission, result=self._failure(status="unavailable", admitted=True)
                )
            finally:
                self._cleanup_task = None
            if cancelled:
                raise asyncio.CancelledError

    def _log_failure(
        self,
        *,
        category: Literal[
            "cleanup_unavailable", "accounting_failed", "termination_failed", "command_unavailable"
        ],
    ) -> None:
        """Rate-limit fixed categories; never pass private values or fall back on sink failure."""
        if category == "cleanup_unavailable":
            self._cleanup_failure_active = True
        now = time.monotonic()
        previous = self._diagnostic_times.get(category)
        if previous is not None and now - previous < 60:
            return
        self._diagnostic_times[category] = now
        try:
            logging.getLogger(__name__).warning("herdr_" + category)
        except Exception:
            pass

    async def _finish_admitted(
        self, *, admission: HerdrCommandAdmission, result: HerdrCommandResultDAO
    ) -> None:
        """Drain then account under lock; quarantine handles on an ordinary defect."""
        try:
            terminal = await self._drain_admitted(result=result)
        except Exception:
            self._closed = True
            self._cleanup_failed = True
            self._log_failure(category="cleanup_unavailable")
            self._complete_safely(
                admission=admission, result=self._failure(status="unavailable", admitted=True)
            )
            return
        self._complete_safely(admission=admission, result=terminal)
        self._active = None
        self._spawn_task = None

    def _complete_safely(self, *, admission: HerdrCommandAdmission, result: HerdrCommandResultDAO) -> None:
        """An accounting defect seals admission but cannot prevent resource cleanup."""
        try:
            admission.complete(result=result)
        except Exception:
            self._closed = True
            self._cleanup_failed = True
            self._log_failure(category="accounting_failed")

    async def _observe_admitted(self, *, command: HerdrCliCommandDAO) -> HerdrCommandResultDAO:
        """Translate private spawn/read failures; cancellation remains caller-owned."""
        assert self._spawn_task is not None
        try:
            self._active = await asyncio.shield(arg=self._spawn_task)
            return await self._collect_result(command=command)
        except HerdrOutputLimitError:
            return self._failure(status="malformed", admitted=True)
        except Exception:
            return self._failure(
                status="unavailable",
                admitted=True,
                spawn_failed=self._active is None and self._spawn_task.done(),
            )

    async def _drain_admitted(self, *, result: HerdrCommandResultDAO) -> HerdrCommandResultDAO:
        """Join even a late spawn before relinquishing this invocation's lock."""
        assert self._spawn_task is not None
        await HerdrTaskJoin.wait(task=self._spawn_task)
        if self._spawn_task.exception() is not None:
            return self._failure(status="unavailable", admitted=True, spawn_failed=True)
        self._active = self._spawn_task.result()
        await self._terminate_and_reap(process=self._active)
        return result

    async def _terminate_and_reap(self, *, process: asyncio.subprocess.Process) -> None:
        """Terminate only the owned group, escalate after .25s, and always join exit."""
        if process.returncode is not None:
            await process.wait()
            return
        try:
            self._signal_owned(process=process, force=False)
        except OSError:
            self._log_failure(category="termination_failed")
            self._signal_owned(process=process, force=True)
            await process.wait()
            return
        try:
            async with asyncio.timeout(delay=self._config.terminate_grace_seconds):
                await process.wait()
                return
        except TimeoutError:
            pass
        self._signal_owned(process=process, force=True)
        await process.wait()

    def _signal_owned(self, *, process: asyncio.subprocess.Process, force: bool) -> None:
        """Signal only this child's session; a vanished process is already harmless."""
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    @classmethod
    def _failure(
        cls,
        *,
        status: HerdrCommandStatus,
        exit_code: Optional[int] = None,
        admitted: bool = False,
        spawn_failed: bool = False,
    ) -> HerdrCommandResultDAO:
        """Construct fixed-only failure evidence without retaining private output."""
        return HerdrCommandResultDAO(
            outcome=HerdrCommandOutcomeDAO(status=status, exit_code=exit_code),
            admitted=admitted,
            spawn_failed=spawn_failed,
        )

    async def _collect_result(self, *, command: HerdrCliCommandDAO) -> HerdrCommandResultDAO:
        """Join both bounded pipes and exit before returning private successful output."""
        assert self._active is not None
        output: Optional[bytes] = None
        if command.capture_json:
            output = await self._collect_pipes(process=self._active)
        exit_code = await self._active.wait()
        if exit_code != 0:
            return self._failure(status="rejected", exit_code=exit_code, admitted=True)
        return HerdrCommandResultDAO(
            outcome=HerdrCommandOutcomeDAO(status="ok", exit_code=exit_code), admitted=True, json_bytes=output
        )

    async def _collect_pipes(self, *, process: asyncio.subprocess.Process) -> bytes:
        """Lexically own concurrent readers; join siblings before propagating refusal."""
        assert process.stdout is not None and process.stderr is not None
        try:
            async with asyncio.TaskGroup() as readers:
                stdout = readers.create_task(coro=self._read_bounded(stream=process.stdout))
                readers.create_task(coro=self._read_bounded(stream=process.stderr))
        except* HerdrOutputLimitError:
            raise HerdrOutputLimitError from None
        return stdout.result()

    @classmethod
    async def _read_bounded(cls, *, stream: asyncio.StreamReader) -> bytes:
        """Return at most 16 KiB, refusing the first excess byte.

        Args:
            stream (asyncio.StreamReader): One private child pipe.

        Returns:
            bytes: Complete bounded pipe contents.

        Raises:
            HerdrOutputLimitError: Output exceeds the fixed parser limit.
        """
        output = bytearray()
        while True:
            chunk = await stream.read(n=min(4096, 16385 - len(output)))
            if not chunk:
                return bytes(output)
            output.extend(chunk)
            if len(output) > 16384:
                raise HerdrOutputLimitError

    async def _spawn(self, *, command: HerdrCliCommandDAO) -> asyncio.subprocess.Process:
        """Create only the captured executable, with no shell or inherited output.

        Args:
            command (HerdrCliCommandDAO): Owner-built semantic argv.

        Returns:
            asyncio.subprocess.Process: Child owned exclusively by this transport.
        """
        return await asyncio.create_subprocess_exec(
            str(self._config.binary_path),
            *command.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if command.capture_json else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE if command.capture_json else asyncio.subprocess.DEVNULL,
            env=self._environment,
            start_new_session=os.name == "posix",
        )


def __getattr__(name: str) -> object:
    """Resolve compatibility exports without cycling shared transport imports.

    Args:
        name (str): Module attribute requested by an importer.

    Returns:
        object: Reporter or reporter-admission class; no instance is constructed.

    Raises:
        AttributeError: The name is not a supported compatibility export.
    """
    if name in ("HerdrReporter", "HerdrReporterAdmission"):
        from .reporter import HerdrReporter, HerdrReporterAdmission

        return {"HerdrReporter": HerdrReporter, "HerdrReporterAdmission": HerdrReporterAdmission}[name]
    raise AttributeError(name)
