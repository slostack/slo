"""Attempt-owned canonical cooperative evidence, independent of presentation."""

from typing import Optional
from uuid import UUID, uuid5

from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl


class CooperativeHistoryWriter:
    """Retain exact first-created events and certify complete groups before continuation.

    The session runtime handler owns this writer for one attempt. Storage is
    optional only for explicitly history-disabled sessions; transient validation
    remains identical. No tasks, observers or retry policy are owned here.
    """

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        control: ToolExecutionControl,
        store: Optional[SessionHistoryStoreProtocol],
    ) -> None:
        """Bind exact attempt/control and the existing adapter, starting no work."""
        self._session_id = session_id
        self._turn_id = turn_id
        self._control = control
        self._store = store
        self._groups: dict[int, ToolGroupMetadataDAO] = {}
        self._events: dict[str, SessionHistoryEventDAO] = {}
        self._results: set[str] = set()

    async def persist(self, *, event: AgentRuntimeEventDAO) -> bool:
        """Capture trusted group/diagnostic evidence; return False for ordinary traces.

        Raises:
            CooperativeYieldSettlementError: Invalid, conflicting or uncertain evidence.
        """
        if event.kind in ("tool_call", "tool_result") or event.payload.metadata.get("reserved_no_start"):
            canonical = self._group_event(event=event)
        elif event.kind == "run_retrying" and "cooperative_yield_v1" in event.payload.metadata:
            canonical = self._diagnostic_event(event=event)
        else:
            return False
        retained = self._events.setdefault(canonical.event_id, canonical)
        incoming = canonical.model_copy(update={"recorded_at": retained.recorded_at})
        if retained.application_sha256() != incoming.application_sha256():
            raise CooperativeYieldSettlementError()
        if self._store is not None:
            try:
                await self._store.append_cooperative_event_once(event=retained)
            except Exception as error:
                raise CooperativeYieldSettlementError() from error
        return True

    async def certify_settlement(self) -> None:
        """Read all active raw pages under the caller's history barrier before continuation.

        Both adapters expose the same strict evidence reader. Validation runs
        across pages, never independently per page; transient sessions validate
        their retained exact event set without claiming storage durability.
        """
        self.require_settled()
        if self._store is None:
            return
        try:
            events: list[SessionHistoryEventDAO] = []
            after_sequence = 0
            while True:
                page = await self._store.application_evidence(
                    session_id=self._session_id, after_sequence=after_sequence
                )
                events.extend(page.events)
                if page.next_sequence is None:
                    break
                after_sequence = page.next_sequence
            SessionHistoryProjector.validate_tool_groups(events=events)
            persisted = {event.event_id: event for event in events}
            for event_id, retained in self._events.items():
                actual = persisted.get(event_id)
                if actual is None or actual.application_sha256() != retained.application_sha256():
                    raise CooperativeYieldSettlementError()
        except Exception as error:
            raise CooperativeYieldSettlementError() from error

    def require_settled(self) -> None:
        """Validate produced raw groups before control settlement in both modes."""
        try:
            SessionHistoryProjector.validate_tool_groups(events=list(self._events.values()))
        except Exception as error:
            raise CooperativeYieldSettlementError() from error

    def _group_event(self, *, event: AgentRuntimeEventDAO) -> SessionHistoryEventDAO:
        """Resolve stable group identity, status and affirmative no-start authority."""
        group = self._groups.get(event.iteration)
        if event.kind == "tool_call" and group is None:
            group = ToolGroupMetadataDAO(
                group_id=str(uuid5(namespace=UUID(self._turn_id), name=f"tool-group:{event.iteration}")),
                attempt_turn_id=self._turn_id,
                iteration=event.iteration,
                tool_call_ids=tuple(call.get("id") or "" for call in event.payload.tool_calls or []),
                opened_at=event.recorded_at,
            )
            self._groups[event.iteration] = group
        if group is None:
            raise CooperativeYieldSettlementError()
        marked, suffix = self._mark_event(event=event, group=group)
        payload = SessionHistoryEventPayloadDAO(
            content=event.payload.content,
            tool_name=event.payload.tool_name,
            tool_call_id=event.payload.tool_call_id,
            tool_calls=event.payload.tool_calls,
            tool_input=event.payload.tool_input,
            tool_output=event.payload.tool_output,
            provider_message_extension=event.payload.provider_message_extension,
            metadata={
                "tool_group_v1": marked.model_dump(mode="json"),
                **({"reason": "cooperative_yield"} if suffix == "not-started" else {}),
            },
        )
        return SessionHistoryEventDAO(
            session_id=self._session_id,
            turn_id=self._turn_id,
            kind=event.kind,
            iteration=event.iteration,
            payload=payload,
            recorded_at=event.recorded_at,
            event_id=str(uuid5(namespace=UUID(group.group_id), name=suffix)),
        )

    def _mark_event(
        self,
        *,
        event: AgentRuntimeEventDAO,
        group: ToolGroupMetadataDAO,
    ) -> tuple[ToolGroupMetadataDAO, str]:
        """Keep core status immutable and no-start exclusive of every actual result."""
        call_id = event.payload.tool_call_id
        if event.kind in ("tool_call", "tool_result") and call_id not in group.tool_call_ids:
            raise CooperativeYieldSettlementError()
        if event.kind == "tool_call":
            return group, f"call:{call_id}"
        if event.kind == "tool_result":
            status = event.payload.metadata.get("core_tool_result_status")
            if status not in ("success", "error"):
                raise CooperativeYieldSettlementError()
            self._results.add(group.group_id)
            return group.model_copy(update={"tool_result_status": status}), f"result:{call_id}"
        if group.group_id in self._results:
            raise CooperativeYieldSettlementError()
        self._control.require_reserved_no_start()
        return group.model_copy(update={"disposition": "not_started"}), "not-started"

    def _diagnostic_event(self, *, event: AgentRuntimeEventDAO) -> SessionHistoryEventDAO:
        """Resolve one deterministic audit identity without rebuilding retained timestamps."""
        from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO

        diagnostic = CooperativeYieldMetadataDAO.model_validate(
            event.payload.metadata["cooperative_yield_v1"]
        )
        if diagnostic.attempt_turn_id != self._turn_id or diagnostic.iteration != event.iteration:
            raise CooperativeYieldSettlementError()
        return SessionHistoryEventDAO(
            session_id=self._session_id,
            turn_id=self._turn_id,
            kind="run_retrying",
            iteration=event.iteration,
            payload=SessionHistoryEventPayloadDAO(metadata=dict(event.payload.metadata)),
            recorded_at=event.recorded_at,
            event_id=str(
                uuid5(
                    namespace=UUID(self._turn_id),
                    name=f"cooperative-yield:{event.iteration}:{diagnostic.disposition}",
                )
            ),
        )
