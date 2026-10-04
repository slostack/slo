"""Pure Context Window Snapshot projection for durable session history (spec 62)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.agents.model_catalog.dao import ModelCatalogEntryDAO, ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.compaction.constants import DEFAULT_CONTEXT_WINDOW
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.projector import SessionHistoryProjector

__all__ = ["ContextWindowSnapshotDAO", "ContextWindowSnapshotService"]


class ResolvedContextWindowDAO(BaseModel):
    """Internal canonical model identity and resolved context capacity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    context_window_tokens: int


class ContextWindowSnapshotDAO(BaseModel):
    """Immutable Context Window Snapshot for selected durable replay history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    context_window_tokens: int
    estimated_used_tokens: int
    available_tokens: int
    consumed_percent: float
    estimate_available: bool


class ContextWindowSnapshotService:
    """Build Context Window Snapshots without I/O, LLM calls, or session state."""

    @classmethod
    def build(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        model_name: str,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> ContextWindowSnapshotDAO:
        """Build an available estimate from one loaded durable event list.

        Args:
            events (list[SessionHistoryEventDAO]): Events in durable append order.
            model_name (str): Routed model name or catalog alias.

        Returns:
            ContextWindowSnapshotDAO: Projector-faithful replay estimate.
        """
        resolved: ResolvedContextWindowDAO = cls._resolve_context_window(
            model_name=model_name, snapshot=snapshot
        )
        context_events: list[SessionHistoryEventDAO] = SessionHistoryProjector.context_events(events=events)
        return cls._snapshot(
            model_name=resolved.model_name,
            context_window_tokens=resolved.context_window_tokens,
            estimated_used_tokens=sum(event.payload.token_usage or 0 for event in context_events),
            estimate_available=True,
        )

    @classmethod
    def without_history(
        cls, *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> ContextWindowSnapshotDAO:
        """Build a capacity-only snapshot when durable history cannot be read.

        Args:
            model_name (str): Routed model name or catalog alias.

        Returns:
            ContextWindowSnapshotDAO: Capacity with an unavailable estimate.
        """
        resolved: ResolvedContextWindowDAO = cls._resolve_context_window(
            model_name=model_name, snapshot=snapshot
        )
        return cls._snapshot(
            model_name=resolved.model_name,
            context_window_tokens=resolved.context_window_tokens,
            estimated_used_tokens=0,
            estimate_available=False,
        )

    @classmethod
    def resolve_model_identity(
        cls, *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> str:
        """Resolve a routed identifier to its canonical cache identity.

        Args:
            model_name (str): Routed model name, alias, or unknown identifier.

        Returns:
            str: Canonical catalog name when known, otherwise the supplied name.
        """
        return cls._resolve_context_window(model_name=model_name, snapshot=snapshot).model_name

    @staticmethod
    def _resolve_context_window(
        *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> ResolvedContextWindowDAO:
        """Resolve catalog capacity and canonical identity in one lookup.

        Args:
            model_name (str): Model identifier to resolve.

        Returns:
            ResolvedContextWindowDAO: Catalog-backed or conservative fallback capacity.
        """
        try:
            entry: ModelCatalogEntryDAO = ModelCatalogService.entry_for_model(
                model_name=model_name, snapshot=snapshot
            )
        except ValueError:
            return ResolvedContextWindowDAO(
                model_name=model_name,
                context_window_tokens=DEFAULT_CONTEXT_WINDOW,
            )
        context_window_tokens: int = entry.runtime_profile.context_window
        if context_window_tokens <= 0:
            context_window_tokens = DEFAULT_CONTEXT_WINDOW
        return ResolvedContextWindowDAO(
            model_name=entry.model_name,
            context_window_tokens=context_window_tokens,
        )

    @classmethod
    def _snapshot(
        cls,
        *,
        model_name: str,
        context_window_tokens: int,
        estimated_used_tokens: int,
        estimate_available: bool,
    ) -> ContextWindowSnapshotDAO:
        """Derive a Context Window Snapshot from resolved capacity and use.

        Args:
            model_name (str): Canonical model identity.
            context_window_tokens (int): Input capacity in tokens.
            estimated_used_tokens (int): Raw durable replay estimate.
            estimate_available (bool): Whether the event list was readable.

        Returns:
            ContextWindowSnapshotDAO: Snapshot with clamped display derivations.
        """
        return ContextWindowSnapshotDAO(
            model_name=model_name,
            context_window_tokens=context_window_tokens,
            estimated_used_tokens=estimated_used_tokens,
            available_tokens=max(0, context_window_tokens - estimated_used_tokens),
            consumed_percent=cls._consumed_percent(
                context_window_tokens=context_window_tokens,
                estimated_used_tokens=estimated_used_tokens,
            ),
            estimate_available=estimate_available,
        )

    @staticmethod
    def _consumed_percent(*, context_window_tokens: int, estimated_used_tokens: int) -> float:
        """Calculate the clamped Context Consumed Percentage.

        Args:
            context_window_tokens (int): Input capacity.
            estimated_used_tokens (int): Raw replay estimate.

        Returns:
            float: Display percentage in the inclusive range 0.0 through 100.0.
        """
        if context_window_tokens <= 0:
            return 100.0
        return min(100.0, max(0.0, estimated_used_tokens / context_window_tokens * 100.0))
