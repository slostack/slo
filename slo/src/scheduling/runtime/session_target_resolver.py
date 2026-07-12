"""Resolve the effective target session for a continuous schedule."""

from __future__ import annotations

import re

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.scheduling.dao import ScheduleDefinitionDAO, ScheduleStateDAO
from src.scheduling.runtime.dao import ResolvedSessionTargetDAO

__all__ = ["SessionTargetResolver"]


_SESSION_ID_SLUG_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")


class SessionTargetResolver:
    """Apply continuous-session target-resolution rules in one place."""

    def __init__(self, *, history_store: FilesystemSessionHistoryStore | None = None) -> None:
        """Bind the resolver to the canonical history store.

        Args:
            history_store (FilesystemSessionHistoryStore | None): Optional injected
                history store for tests.
        """
        self._history_store: FilesystemSessionHistoryStore = history_store or FilesystemSessionHistoryStore()

    async def resolve(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        state: ScheduleStateDAO,
    ) -> ResolvedSessionTargetDAO:
        """Resolve the effective session target for one fire.

        Args:
            definition (ScheduleDefinitionDAO): Loaded schedule definition.
            state (ScheduleStateDAO): Current mutable schedule state.

        Returns:
            ResolvedSessionTargetDAO: Existing or seed target-session info.
        """
        if definition.session_mode == "fresh":
            return ResolvedSessionTargetDAO()
        if definition.session_policy is None:
            return ResolvedSessionTargetDAO()
        explicit_reference = definition.session_policy.session_reference
        if explicit_reference is not None:
            return await self._resolve_explicit_reference(
                definition=definition,
                explicit_reference=explicit_reference,
            )
        if state.last_session_id is not None:
            return ResolvedSessionTargetDAO(
                resolved_reference=state.last_session_id,
                target_session_id=state.last_session_id,
                explicit_session_id=None,
            )
        seeded_session_id: str = f"schedule-{definition.schedule_id}"
        return ResolvedSessionTargetDAO(
            resolved_reference=None,
            target_session_id=seeded_session_id,
            explicit_session_id=seeded_session_id,
        )

    async def _resolve_explicit_reference(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        explicit_reference: str,
    ) -> ResolvedSessionTargetDAO:
        """Resolve an operator-supplied session reference.

        Args:
            definition (ScheduleDefinitionDAO): Loaded schedule definition.
            explicit_reference (str): Raw persisted reference.

        Returns:
            ResolvedSessionTargetDAO: Resolved target-session info.
        """
        try:
            resolved_session_id: str = await self._history_store.resolve_session_reference(
                reference=explicit_reference,
            )
        except ValueError:
            if _SESSION_ID_SLUG_RE.match(explicit_reference):
                return ResolvedSessionTargetDAO(
                    resolved_reference=None,
                    target_session_id=explicit_reference,
                    explicit_session_id=explicit_reference,
                )
            raise ValueError(
                f"Continuous schedule '{definition.name}' references an unknown session: "
                f"{explicit_reference}",
            )
        return ResolvedSessionTargetDAO(
            resolved_reference=explicit_reference,
            target_session_id=resolved_session_id,
            explicit_session_id=None,
        )
