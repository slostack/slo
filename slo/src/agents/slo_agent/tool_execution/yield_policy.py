"""Loop-owned provider/tool yield phase control (feature 96, sub-spec A.2).

One run-scoped phase owner captures boundary/high-water and arbitrates
provider reservation versus tools. Trusted identity-scoped cancellation owns
both invocation and callback joins; unregistered work always defers.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Literal, Optional
from uuid import UUID
from weakref import WeakSet

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from src.agents.slo_agent.tool_execution.dao import (
    ToolInvocationDAO,
    ToolCancellationRegistrationDAO,
    ToolYieldOutcomeDAO,
    ToolYieldMode,
    ToolCancellationPort,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.messaging.dao import BoundaryDeliveryDAO
    from src.agents.slo_agent.messaging.delivery import AgentMessageSource
    from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO

__all__: list[str] = [
    "CooperativeProviderYield",
    "ToolExecutionControl",
    "ToolYieldCapabilityError",
]

_ToolExecutionPhase = Literal[
    "idle",
    "provider",
    "tools",
    "settling",
    "yielding",
    "settled",
    "closed",
]
_TOOL_CALL_ID_MAX_LENGTH: int = 512


class _CancellationAcknowledgement:
    """Retain temporal callback authority: an ack returned before invocation join is never valid."""

    def __init__(self, *, invocation: ToolInvocationDAO, port: ToolCancellationPort) -> None:
        """Borrow the exact invocation and trusted port without starting callback work."""
        self._invocation = invocation
        self._port = port
        self.after_join = False

    async def invoke(self) -> ToolMessage:
        """Capture join state at callback return rather than infer it from later task completion."""
        result: ToolMessage = await self._port.cancel_and_join(invocation=self._invocation)
        self.after_join = self._invocation.task.done()
        return result


class ToolYieldCapabilityError(RuntimeError):
    """Fixed capability/ownership violation for yield control."""

    def __init__(self) -> None:
        """Raise the fixed ``tool_yield_capability_invalid`` contract error."""
        super().__init__("tool_yield_capability_invalid")


class CooperativeProviderYield(Exception):
    """Provider yield reservation won before tools could enter.

    WHAT: Signals that tool entry must stop before plugin or tool effects.
    WHO: ``ToolExecutionControl.enter_tools`` raises it; only the watchdog
        may handle it when its exact reservation is active.
    WHEN: Between a successful ``reserve_provider_yield`` and tool planning.
    """


class ToolExecutionControl:
    """Own the provider/tools/settling phases and urgency snapshot for one run.

    WHAT: Serializes phase transitions on one owner loop, captures the
        cached delivery boundary/high-water and exposes the provider-exit
        event used to suspend provider timing once tools own work.
    WHO: The session creates one per logical run; the agent/watchdog and
        tool node call it through explicit phases.
    WHEN: From a settled/application boundary through provider, tools,
        settling, one settlement and joined close.
    DATA FLOW: Reads only urgency predicates from ``AgentMessageSource``;
        never claims, acknowledges or mutates queue state.
    LIFETIME: Constructed without tasks; owned until the run owner closes
        it once after provider/executor/history work has joined.
    """

    def __init__(
        self,
        *,
        source: AgentMessageSource,
        on_deferred: Callable[[CooperativeYieldMetadataDAO], None],
        on_requested: Optional[Callable[[CooperativeYieldMetadataDAO], None]] = None,
    ) -> None:
        """Bind the source and deferred sink without starting work.

        Args:
            source (AgentMessageSource): Session-owned urgency source; this
                control only reads its high-water and wait predicate.
            on_requested: Optional non-awaiting reservation observer; publication
                failure is isolated while the canonical diagnostic remains retained.
            on_deferred (Callable[[CooperativeYieldMetadataDAO], None]):
                Non-awaiting best-effort presentation sink. Canonical audit is
                captured separately for transfer at the agent settlement barrier.
        """
        self._source: AgentMessageSource = source
        self._on_requested: Optional[Callable[[CooperativeYieldMetadataDAO], None]] = on_requested
        self._on_deferred: Callable[[CooperativeYieldMetadataDAO], None] = on_deferred
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self._phase: _ToolExecutionPhase = "idle"
        self._delivery: Optional[BoundaryDeliveryDAO] = None
        self._attempt_turn_id: Optional[str] = None
        self._iteration: Optional[int] = None
        self._urgent_high_water: int = 0
        self._tool_call_ids: tuple[str, ...] = ()
        self._provider_exit: asyncio.Event = asyncio.Event()
        self._deferred = False
        self._diagnostics: list[CooperativeYieldMetadataDAO] = []

    def enter_provider(
        self,
        *,
        delivery: BoundaryDeliveryDAO,
        attempt_turn_id: str,
        iteration: int,
    ) -> None:
        """Enter provider work for one applied boundary attempt.

        WHAT: Capture the cached delivery, high-water, attempt identity and
            iteration, reset the provider-exit event and own the provider
            phase. A retry may replace attempt identity only from ``settled``
            with the identical boundary and high-water.
        WHO: ``SloAgent._stream_graph_turn`` after application and before
            the provider request.
        WHEN: Once per attempt; a duplicate active entry is rejected.
        DATA FLOW: Receives the cached A.1 delivery; stores no queue claim.
        LIFETIME: Ends only through tools/settling/settlement/close.

        Args:
            delivery (BoundaryDeliveryDAO): Frozen cached boundary selection.
            attempt_turn_id (str): Canonical session attempt UUID.
            iteration (int): Nonnegative outer ReAct iteration.

        Raises:
            ToolYieldCapabilityError: The phase, identity, iteration or retry
                boundary/high-water is not eligible.
        """
        self._require_owner_loop()
        self._require_canonical_attempt(attempt_turn_id=attempt_turn_id)
        if iteration < 0:
            raise ToolYieldCapabilityError()
        if self._phase not in ("idle", "settled"):
            raise ToolYieldCapabilityError()
        if self._phase == "settled" and not self._is_next_or_retry_boundary(delivery=delivery):
            raise ToolYieldCapabilityError()

        self._delivery = delivery
        self._attempt_turn_id = attempt_turn_id
        self._iteration = iteration
        self._urgent_high_water = delivery.urgent_high_water
        self._tool_call_ids = ()
        self._deferred = False
        self._provider_exit.clear()
        self._phase = "provider"

    def is_provider_active(self) -> bool:
        """Report whether provider timing still owns this pending read."""
        self._require_owner_loop()
        return self._phase == "provider"

    def require_source(self, *, source: AgentMessageSource) -> None:
        """Reject a control borrowed by a different session source."""
        if self._source is not source:
            raise ToolYieldCapabilityError()

    def require_reserved_no_start(self) -> None:
        """Require affirmative reservation before disposing a complete opening."""
        self._require_owner_loop()
        if self._phase != "yielding" or self._tool_call_ids:
            raise ToolYieldCapabilityError()

    def reserve_provider_yield(self) -> bool:
        """Reserve provider yield when newer urgency exists.

        WHAT: Atomically compare the provider phase and newer-urgency
            predicate, then transition to ``yielding``. A failed comparison
            leaves tools/settling ownership untouched.
        WHO: The watchdog immediately before cancelling its owned reader.
        WHEN: Only while the provider phase owns execution.
        DATA FLOW: Reads ``yield_is_requested`` against the captured snapshot.

        Returns:
            bool: True only when this call reserved the provider yield.

        Raises:
            ToolYieldCapabilityError: This control is closed.
        """
        self._require_owner_loop()
        if self._phase == "closed":
            raise ToolYieldCapabilityError()
        if self._phase != "provider":
            return False
        if not self._source.yield_is_requested(after_sequence=self._urgent_high_water):
            return False
        self._phase = "yielding"
        metadata = self._diagnostic(reason="provider", disposition="requested")
        self._diagnostics.append(metadata)
        if self._on_requested is not None:
            try:
                self._on_requested(metadata)
            except Exception:
                pass  # Best-effort observation never owns settlement.
        return True

    def enter_tools(self, *, tool_call_ids: tuple[str, ...]) -> None:
        """Take tools ownership synchronously before plugin or tool effects.

        WHAT: Validate a complete distinct call group, set the tools phase and
            signal provider exit before any awaited effect.
        WHO: ``_make_tool_node.tool_node`` immediately after a provider result.
        WHEN: Only from the provider phase with no active yield reservation.
        DATA FLOW: Stores source-ordered IDs for later dispatch decisions.
        LIFETIME: Ends through ``enter_settling`` or settlement.

        Args:
            tool_call_ids (tuple[str, ...]): Nonempty distinct bounded IDs in
                source order.

        Raises:
            CooperativeProviderYield: This exact attempt already reserved
                provider yield; no tool effect may start.
            ToolYieldCapabilityError: Phase or call-group validation failed.
        """
        self._require_owner_loop()
        if self._phase == "yielding":
            raise CooperativeProviderYield()
        if self._phase != "provider":
            raise ToolYieldCapabilityError()
        self._require_tool_call_ids(tool_call_ids=tool_call_ids)

        self._tool_call_ids = tool_call_ids
        self._phase = "tools"
        self._provider_exit.set()

    def enter_settling(self) -> None:
        """Enter settlement only after all started tool work joined.

        WHAT: Transition tools ownership to settling and keep provider timing
            disabled.
        WHO: The executor/tool node after the exact complete result set exists.
        WHEN: Once, only from the tools phase.
        DATA FLOW: No queue interaction.
        LIFETIME: Ends through ``settle_attempt`` or close.

        Raises:
            ToolYieldCapabilityError: The current phase is not ``tools``.
        """
        self._require_owner_loop()
        if self._phase != "tools":
            raise ToolYieldCapabilityError()
        self._phase = "settling"
        self._provider_exit.set()

    def settle_attempt(self) -> None:
        """Settle one attempt exactly once after read/stream/history barriers.

        WHAT: Mark provider/yielding/settling work settled and keep the
            provider-exit signal set.
        WHO: The agent after read, stream, history and context cleanup settle.
        WHEN: Exactly once per attempt; never in an unconditional finally.
        DATA FLOW: No queue interaction.
        LIFETIME: A later retry may enter the provider from ``settled``.

        Raises:
            ToolYieldCapabilityError: Settlement already happened, tools still
                own work, or this control is closed/idle.
        """
        self._require_owner_loop()
        if self._phase not in ("provider", "yielding", "settling"):
            raise ToolYieldCapabilityError()
        self._phase = "settled"
        self._provider_exit.set()

    def close(self) -> None:
        """Close joined ownership without touching queue state.

        WHAT: Mark the control closed and release phase waiters. Repeating
            close on this exact object is idempotent.
        WHO: The run owner after provider/executor/history work joined.
        WHEN: Finally after release; never before joins are confirmed.
        DATA FLOW: No cancellation, claim or queue clear.
        LIFETIME: Terminal; this object is never reset for reuse.

        Raises:
            ToolYieldCapabilityError: Called from a different owner loop.
        """
        self._require_owner_loop()
        if self._phase == "closed":
            return
        self._phase = "closed"
        self._provider_exit.set()

    async def wait_for_yield(self) -> None:
        """Wait for newer urgency through the source predicate.

        WHAT: Delegate to the session-owned Condition with the captured
            high-water; never claim or clear input.
        WHO: The watchdog's newer-urgency waiter.
        WHEN: While provider work owns execution.
        DATA FLOW: ``AgentMessageSource.wait_for_yield`` may also wake on
            source seal/failure; the caller must recheck the predicate.
        LIFETIME: Cancellation removes only this waiter.

        Raises:
            ToolYieldCapabilityError: Called outside provider ownership.
            MessageStoreError: The session source reports storage failure.
        """
        self._require_owner_loop()
        if self._delivery is None or self._phase in ("idle", "closed"):
            raise ToolYieldCapabilityError()
        await self._source.wait_for_yield(after_sequence=self._urgent_high_water)

    async def wait_for_provider_exit(self) -> None:
        """Wait until provider work no longer owns the attempt.

        WHAT: Return immediately for tools/settling/settled/closed, otherwise
            await the per-attempt provider-exit event.
        WHO: The watchdog phase waiter that must not suspend a pending read
            once tools have taken ownership.
        WHEN: During the provider race.
        DATA FLOW: Reads only the loop-owned event.
        LIFETIME: Event is reset on the next safe attempt entry.
        """
        self._require_owner_loop()
        if self._phase != "provider":
            return
        await self._provider_exit.wait()

    def yield_is_requested(self) -> bool:
        """Recheck actual newer urgency after a source lifecycle wake."""
        self._require_owner_loop()
        return self._source.yield_is_requested(after_sequence=self._urgent_high_water)

    def require_closed(self) -> None:
        """Require joined run retirement before policy can release callback-once records."""
        self._require_owner_loop()
        if self._phase != "closed":
            raise ToolYieldCapabilityError()

    def require_cancellation(self, *, tool_call_id: str) -> None:
        """Reject cancellation outside this exact tools group and newer-urgency phase."""
        self._require_owner_loop()
        if self._phase != "tools" or tool_call_id not in self._tool_call_ids or not self.yield_is_requested():
            raise ToolYieldCapabilityError()

    def before_dispatch(self, *, tool_call_id: str) -> bool:
        """Decide whether one registered call may start without claiming input.

        WHAT: Validate group membership and return False when newer urgency,
            yielding ownership or closure forbids dispatch.
        WHO: ``ToolExecutor._invoke_one`` immediately before task
            registration, with no await before registration.
        WHEN: Only for a call in the current tools group.
        DATA FLOW: Reads the source urgency predicate; never dequeues.

        Args:
            tool_call_id (str): Exact ID from the validated tools group.

        Returns:
            bool: True only if dispatch may start.

        Raises:
            ToolYieldCapabilityError: The ID is blank, unbounded or not in the
                current group.
        """
        self._require_owner_loop()
        self._require_tool_call_id(tool_call_id=tool_call_id)
        if tool_call_id not in self._tool_call_ids:
            raise ToolYieldCapabilityError()
        if self._phase != "tools":
            return False
        return not self._source.yield_is_requested(after_sequence=self._urgent_high_water)

    async def defer(
        self,
        *,
        tool_call_id: str,
        reason: Literal["noninterruptible_tool", "concurrent_batch", "dispatch"] = "noninterruptible_tool",
    ) -> None:
        """Capture and publish one immutable notice without awaiting external observers."""
        from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO

        self._require_owner_loop()
        if tool_call_id not in self._tool_call_ids or self._delivery is None:
            raise ToolYieldCapabilityError()
        if not self.yield_is_requested() or self._deferred:
            return
        if self._attempt_turn_id is None or self._iteration is None:
            raise ToolYieldCapabilityError()
        self._deferred = True
        from uuid import uuid5

        metadata = CooperativeYieldMetadataDAO(
            run_id=self._delivery.boundary.run_id,
            boundary_index=self._delivery.boundary.boundary_index,
            attempt_turn_id=self._attempt_turn_id,
            iteration=self._iteration,
            urgent_high_water=self._urgent_high_water,
            reason=reason,
            disposition="deferred",
            group_id=str(uuid5(namespace=UUID(self._attempt_turn_id), name=f"tool-group:{self._iteration}")),
        )
        self._diagnostics.append(metadata)
        try:
            self._on_deferred(metadata)
        except Exception:
            # Presentation is best-effort; execution/history never depends on it.
            pass

    def take_settlement_diagnostics(self) -> tuple[CooperativeYieldMetadataDAO, ...]:
        """Transfer captured audit to the trusted settlement owner, never observers."""
        self._require_owner_loop()
        diagnostics = tuple(self._diagnostics)
        self._diagnostics.clear()
        return diagnostics

    def _diagnostic(
        self,
        *,
        reason: Literal["provider"],
        disposition: Literal["requested"],
    ) -> CooperativeYieldMetadataDAO:
        """Capture provider reservation correlation exactly when the reservation wins."""
        from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO

        if self._delivery is None or self._attempt_turn_id is None or self._iteration is None:
            raise ToolYieldCapabilityError()
        return CooperativeYieldMetadataDAO(
            run_id=self._delivery.boundary.run_id,
            boundary_index=self._delivery.boundary.boundary_index,
            attempt_turn_id=self._attempt_turn_id,
            iteration=self._iteration,
            urgent_high_water=self._urgent_high_water,
            reason=reason,
            disposition=disposition,
        )

    def _require_owner_loop(self) -> None:
        """Bind the first calling loop and reject all later cross-loop use."""
        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        except RuntimeError as error:
            raise ToolYieldCapabilityError() from error
        if self._owner_loop is None:
            self._owner_loop = loop
            return
        if self._owner_loop is not loop:
            raise ToolYieldCapabilityError()

    def _require_canonical_attempt(self, *, attempt_turn_id: str) -> None:
        """Require a canonical lowercase UUID attempt identity."""
        try:
            parsed: UUID = UUID(attempt_turn_id)
        except (AttributeError, ValueError) as error:
            raise ToolYieldCapabilityError() from error
        if str(parsed) != attempt_turn_id:
            raise ToolYieldCapabilityError()

    def _is_next_or_retry_boundary(self, *, delivery: BoundaryDeliveryDAO) -> bool:
        """Freeze retries; a next selection may lower high-water after backlog consumption."""
        if self._delivery is None:
            return False
        if delivery.boundary == self._delivery.boundary:
            return delivery.urgent_high_water == self._urgent_high_water
        return (
            delivery.boundary.run_id == self._delivery.boundary.run_id
            and delivery.boundary.boundary_index == self._delivery.boundary.boundary_index + 1
        )

    @staticmethod
    def _require_tool_call_ids(*, tool_call_ids: tuple[str, ...]) -> None:
        """Require a nonempty distinct bounded printable call group."""
        if not tool_call_ids or len(set(tool_call_ids)) != len(tool_call_ids):
            raise ToolYieldCapabilityError()
        for tool_call_id in tool_call_ids:
            ToolExecutionControl._require_tool_call_id(tool_call_id=tool_call_id)

    @staticmethod
    def _require_tool_call_id(*, tool_call_id: str) -> None:
        """Require one bounded printable call identity."""
        if not tool_call_id.strip() or not tool_call_id.isprintable():
            raise ToolYieldCapabilityError()
        if len(tool_call_id) > _TOOL_CALL_ID_MAX_LENGTH:
            raise ToolYieldCapabilityError()


class ToolYieldPolicy:
    """Identity-scoped opt-in cancellation with retained port and invocation ownership."""

    def __init__(
        self,
        *,
        cancellations: tuple[ToolCancellationRegistrationDAO, ...] = (),
        acknowledgement_seconds: float = 5.0,
    ) -> None:
        """Retain explicit trusted capabilities; all unregistered tools defer."""
        if acknowledgement_seconds <= 0:
            raise ToolYieldCapabilityError()
        for index, registration in enumerate(cancellations):
            if any(registration.tool is previous.tool for previous in cancellations[:index]):
                raise ToolYieldCapabilityError()
        self._cancellations = cancellations
        self._acknowledgement_seconds = acknowledgement_seconds
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self._settlements: dict[
            asyncio.Task[ToolMessage], tuple[ToolInvocationDAO, asyncio.Task[ToolYieldOutcomeDAO]]
        ] = {}
        self._controls: dict[asyncio.Task[ToolMessage], ToolExecutionControl] = {}
        self._retired_tasks: WeakSet[asyncio.Task[ToolMessage]] = WeakSet()

    def release_run(self, *, control: ToolExecutionControl) -> None:
        """Drop only joined ownership from a closed run; closed control forbids reuse."""
        control.require_closed()
        tasks = [task for task, owner_control in self._controls.items() if owner_control is control]
        if any(not self._settlements[task][1].done() or not task.done() for task in tasks):
            raise ToolYieldCapabilityError()
        for task in tasks:
            self._retired_tasks.add(task)
            del self._controls[task]
            del self._settlements[task]

    def mode_for(self, *, tool: BaseTool) -> ToolYieldMode:
        """Match original concrete identity only; no built-in registration exists."""
        return "cancel_confirmed" if any(item.tool is tool for item in self._cancellations) else "defer"

    async def cancel_and_join(
        self,
        *,
        invocation: ToolInvocationDAO,
        control: ToolExecutionControl,
    ) -> ToolYieldOutcomeDAO:
        """Call a trusted port once and retain both handles until truthful terminal settlement."""
        control.require_cancellation(tool_call_id=invocation.tool_call_id)
        loop = asyncio.get_running_loop()
        if self._owner_loop is not None and self._owner_loop is not loop:
            raise ToolYieldCapabilityError()
        self._owner_loop = loop
        if invocation.task.get_loop() is not loop or invocation.task in self._retired_tasks:
            raise ToolYieldCapabilityError()
        registration = next((item for item in self._cancellations if item.tool is invocation.tool), None)
        if registration is None:
            raise ToolYieldCapabilityError()
        existing = self._settlements.get(invocation.task)
        if existing is not None:
            original, owner = existing
            if (
                self._controls[invocation.task] is not control
                or original.tool is not invocation.tool
                or original.tool_call_id != invocation.tool_call_id
            ):
                raise ToolYieldCapabilityError()
        else:
            owner = asyncio.create_task(
                coro=self._settle(invocation=invocation, control=control, port=registration.port)
            )
            self._settlements[invocation.task] = (invocation, owner)
            self._controls[invocation.task] = control
        cancelled = False
        while not owner.done():
            try:
                await asyncio.shield(owner)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not owner.cancelled():
                owner.exception()
            raise asyncio.CancelledError()
        return owner.result()

    @staticmethod
    def _normal_result(*, invocation: ToolInvocationDAO) -> Optional[ToolMessage]:
        """Read actual normal terminal truth; naked cancellation supplies no result."""
        if not invocation.task.done() or invocation.task.cancelled():
            return None
        if invocation.task.exception() is not None:
            return None
        result = invocation.task.result()
        if not isinstance(result, ToolMessage) or result.tool_call_id != invocation.tool_call_id:
            return None
        return result

    async def _settle(
        self,
        *,
        invocation: ToolInvocationDAO,
        control: ToolExecutionControl,
        port: ToolCancellationPort,
    ) -> ToolYieldOutcomeDAO:
        """Five seconds triggers defer, never abandonment; late valid acknowledgements remain truth."""
        actual = self._normal_result(invocation=invocation)
        if actual is not None:
            return ToolYieldOutcomeDAO(
                tool_call_id=invocation.tool_call_id, disposition="completed", result=actual
            )
        acknowledgement = _CancellationAcknowledgement(invocation=invocation, port=port)
        callback: asyncio.Task[ToolMessage] = asyncio.create_task(coro=acknowledgement.invoke())
        await self._observe_acknowledgement_threshold(
            invocation=invocation, callback=callback, acknowledgement=acknowledgement, control=control
        )
        await self._join_cancellation(invocation=invocation, callback=callback)
        return self._select_joined_outcome(
            invocation=invocation, callback=callback, acknowledgement_after_join=acknowledgement.after_join
        )

    async def _observe_acknowledgement_threshold(
        self,
        *,
        invocation: ToolInvocationDAO,
        callback: asyncio.Task[ToolMessage],
        acknowledgement: _CancellationAcknowledgement,
        control: ToolExecutionControl,
    ) -> None:
        """Defer on missing timely truth without cancelling either invocation or port."""
        deadline: float = asyncio.get_running_loop().time() + self._acknowledgement_seconds
        await asyncio.wait(
            fs={invocation.task, callback},
            timeout=self._acknowledgement_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        actual = self._normal_result(invocation=invocation)
        if invocation.task.done() and actual is None and not callback.done():
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.wait(fs={callback}, timeout=remaining)
        ack = (
            self._valid_ack(callback=callback, invocation=invocation) if acknowledgement.after_join else None
        )
        if actual is None and ack is None:
            await control.defer(tool_call_id=invocation.tool_call_id)

    @staticmethod
    async def _join_cancellation(
        *,
        invocation: ToolInvocationDAO,
        callback: asyncio.Task[ToolMessage],
    ) -> None:
        """Retrieve both terminal outcomes despite repeated cancellation of the waiter."""
        joined = asyncio.gather(invocation.task, callback, return_exceptions=True)
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                continue
        joined.result()

    def _select_joined_outcome(
        self,
        *,
        invocation: ToolInvocationDAO,
        callback: asyncio.Task[ToolMessage],
        acknowledgement_after_join: bool,
    ) -> ToolYieldOutcomeDAO:
        """Prefer actual completion; only a temporally authorized joined ack can cancel."""
        from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError

        actual = self._normal_result(invocation=invocation)
        if actual is not None:
            return ToolYieldOutcomeDAO(
                tool_call_id=invocation.tool_call_id, disposition="completed", result=actual
            )
        ack = (
            self._valid_ack(callback=callback, invocation=invocation) if acknowledgement_after_join else None
        )
        if ack is None:
            raise UnsettledToolGroupError()
        return ToolYieldOutcomeDAO(tool_call_id=invocation.tool_call_id, disposition="cancelled", result=ack)

    @staticmethod
    def _valid_ack(
        *,
        callback: asyncio.Task[ToolMessage],
        invocation: ToolInvocationDAO,
    ) -> Optional[ToolMessage]:
        """Require exact ID/error and joined invocation, not Task.done as leaf proof."""
        if not callback.done() or callback.cancelled() or not invocation.task.done():
            return None
        if callback.exception() is not None:
            return None
        result = callback.result()
        if (
            not isinstance(result, ToolMessage)
            or result.tool_call_id != invocation.tool_call_id
            or result.status != "error"
        ):
            return None
        return result
