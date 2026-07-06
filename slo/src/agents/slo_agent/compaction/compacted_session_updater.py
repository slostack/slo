"""Writer for compaction summary events (sub-spec 01.a.8).

After ``Compacter.compact()`` returns a ``CompactionResult``, this class
builds and persists the corresponding ``compaction_summary`` event via the
store's ``append_event`` interface.

The store is append-only. ``CompactedSessionUpdater`` never deletes or
modifies existing events. The ``first_kept_entry_id`` written into the new
event tells the projector where to begin replaying on the next turn — it is
a pointer, not a rewrite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.compaction.compacter import CompactionResult
    from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol

__all__ = ["CompactedSessionUpdater"]


class CompactedSessionUpdater:
    """Translate a ``CompactionResult`` into a persisted ``compaction_summary`` event.

    Stateless: no constructor arguments, no instance state, no side effects
    beyond the single ``store.append_event`` call. Safe to call from any
    async context.

    Usage::

        stamped = await CompactedSessionUpdater.update(
            session_id=session_id,
            result=compaction_result,
            store=store,
            turn_id=current_turn_id,
        )
    """

    @classmethod
    async def update(
        cls,
        *,
        session_id: str,
        result: "CompactionResult",
        store: "SessionHistoryStoreProtocol",
        turn_id: Optional[str] = None,
    ) -> SessionHistoryEventDAO:
        """Build and persist a ``compaction_summary`` event for ``session_id``.

        Constructs a ``SessionHistoryEventDAO`` with ``kind="compaction_summary"``,
        populates ``payload.content`` with the LLM-generated summary text, and
        stores the four compaction identifiers in ``payload.metadata``. Delegates
        the actual write to ``store.append_event``, which assigns the final
        ``sequence`` value.

        Args:
            session_id (str): The session that owns this compaction event.
            result (CompactionResult): The output of ``Compacter.compact()``.
                Provides the summary text and all four compaction identifiers.
            store (SessionHistoryStoreProtocol): The store to write into.
                Must already have the session ensured (``ensure_session`` called).
            turn_id (Optional[str]): The agent turn during which compaction ran.
                ``None`` when compaction occurs outside a named turn.

        Returns:
            SessionHistoryEventDAO: The persisted compaction summary event,
                with the store-assigned ``sequence`` and the pre-generated
                ``event_id``.

        Raises:
            FileNotFoundError: Propagated from ``store.append_event`` when the
                session was never ensured.
        """
        payload: SessionHistoryEventPayloadDAO = cls._build_payload(result=result)
        compaction_event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id=session_id,
            turn_id=turn_id,
            kind="compaction_summary",
            iteration=0,
            payload=payload,
        )
        stamped: SessionHistoryEventDAO = await store.append_event(
            event=compaction_event,
        )
        return stamped

    @classmethod
    def _build_payload(
        cls,
        *,
        result: "CompactionResult",
    ) -> SessionHistoryEventPayloadDAO:
        """Construct the event payload from a ``CompactionResult``.

        Args:
            result (CompactionResult): Compaction output to convert.

        Returns:
            SessionHistoryEventPayloadDAO: Populated payload with ``content``
                set to the summary text and ``metadata`` carrying the four
                compaction identifiers.
        """
        return SessionHistoryEventPayloadDAO(
            content=result.summary_text,
            metadata={
                "first_kept_entry_id": result.first_kept_entry_id,
                "cut_point_entry_id": result.cut_point_entry_id,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
            },
        )
