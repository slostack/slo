"""Application service for the detached-workflow TUI receive path (spec 57.a.5).

Coordinates durable workflow handle lifecycle for the mounted TUI session:
startup reconcile, inbox lifecycle translation, launch-result translation,
and the live-state cache that backs the exit hint. Emits typed UI effects
from ``dao.py`` — it never renders, never launches windows, and imports no
Textual modules.
"""

from __future__ import annotations

from typing import List, Optional

from config.logger import log_info
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.tui.workflows.dao import (
    DetachedWorkflowUiEffectDAO,
    HandleAdvanceOutcomeDAO,
    LaunchResultOutcome,
    LiveWorkflowLabelDAO,
    ParsedLaunchResultDAO,
    ParsedWorkflowLifecycleMessageDAO,
    parse_launch_workflow_result,
    parse_workflow_lifecycle_message,
)

__all__ = ["DetachedWorkflowAppService"]


class DetachedWorkflowAppService:
    """Coordinate detached-workflow lifecycle for one owning TUI session.

    Owns the ``WorkflowHandleStore`` reconcile/update calls, the legal
    durable transitions, and the ``workflow_id → state`` cache. Every public
    method translates untrusted input (inbox payloads, tool-result JSON) into
    typed domain objects first and returns typed outcomes — the caller never
    parses workflow JSON or lifecycle payloads itself.
    """

    def __init__(
        self,
        *,
        workflow_handle_store: WorkflowHandleStore,
        owner_session_id: str,
    ) -> None:
        """Bind the service to one owning session's handle store.

        Args:
            workflow_handle_store (WorkflowHandleStore): Durable handle store.
            owner_session_id (str): The TUI session that owns the workflows.
        """
        self._store: WorkflowHandleStore = workflow_handle_store
        self._owner_session_id: str = owner_session_id
        self._workflow_states: dict[str, WorkflowState] = {}

    async def reconcile_snapshot(self) -> dict[str, WorkflowState]:
        """Refresh the cached workflow states from a pid-liveness reconcile pass.

        WHAT: re-reads every handle for the owning session and replaces the
            state cache with the reconciled truth.
        WHO: the TUI mount path, via the app's delivery initialization.
        WHEN: once at mount, so a resumed TUI shows accurate states before
            any lifecycle note is claimed.

        Returns:
            dict[str, WorkflowState]: The refreshed cache. The pre-existing
                cache is returned unchanged when the store call fails —
                reconcile failures are logged, never raised.
        """
        try:
            handles: List[WorkflowHandleDAO] = await self._store.reconcile(
                owner_session_id=self._owner_session_id,
            )
        except Exception as exc:  # noqa: BLE001 — mount must not fail on handle errors
            log_info(msg="workflow_reconcile_failed", error=str(exc))
            return self._workflow_states
        self._workflow_states = {handle.workflow_id: handle.state for handle in handles}
        return self._workflow_states

    async def advance_from_inbox_message(
        self,
        *,
        kind: str,
        payload: Optional[dict[str, object]],
    ) -> HandleAdvanceOutcomeDAO:
        """Translate one claimed inbox message into durable and UI effects.

        WHAT: parses the lifecycle payload, advances the durable handle
            through the legal transition table, updates the state cache, and
            emits the typed UI effects (resume-case visualizer launch on
            ``started``, launch-guard reset on ``terminal``).
        WHO: the TUI inbox claim path, for every claimed message.
        WHEN: before the message's delivery-mode rendering runs, so
            ``/workflows`` state stays truthful regardless of delivery mode.

        Args:
            kind (str): Inbox message kind.
            payload (Optional[dict[str, object]]): Raw opaque inbox payload.

        Returns:
            HandleAdvanceOutcomeDAO: Typed outcome. Non-workflow messages,
                invalid payloads, and handle-store failures all produce a
                no-effect outcome — inbox delivery never fails on them.
        """
        parsed: Optional[ParsedWorkflowLifecycleMessageDAO] = parse_workflow_lifecycle_message(
            kind=kind,
            payload=payload,
        )
        if parsed is None:
            return HandleAdvanceOutcomeDAO()
        advanced: bool = await self._advance_durable_handle(parsed=parsed)
        if not advanced:
            return HandleAdvanceOutcomeDAO(workflow_id=parsed.workflow_id)
        self._workflow_states[parsed.workflow_id] = parsed.target_state
        return HandleAdvanceOutcomeDAO(
            effects=self._effects_for_lifecycle(parsed=parsed),
            advanced_handle=True,
            advanced_state=parsed.target_state,
            workflow_id=parsed.workflow_id,
        )

    def advance_from_launch_result(self, *, result_text: str) -> LaunchResultOutcome:
        """Translate one ``launch_workflow`` tool-result text into UI effects.

        WHAT: parses the handle JSON; a valid result seeds the state cache
            (so the exit hint lists the workflow before its ``workflow_started``
            note is claimed) and returns ``launched`` so the caller executes
            the visualizer effect. Anything else is a safe no-op.
        WHO: the TUI live render path on ``launch_workflow`` tool results.
        WHEN: during the launch turn, when the tool result streams through.

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.

        Returns:
            LaunchResultOutcome: ``launched`` for a valid handle payload,
                ``ignored`` for malformed, error, or orchestrator-id-less JSON.
        """
        parsed: Optional[ParsedLaunchResultDAO] = parse_launch_workflow_result(
            result_text=result_text,
        )
        if parsed is None:
            return "ignored"
        if parsed.workflow_id:
            self._workflow_states[parsed.workflow_id] = parsed.state
        return "launched"

    def live_workflow_labels(self) -> List[LiveWorkflowLabelDAO]:
        """Return labels for workflows whose cached state is live.

        Returns:
            List[LiveWorkflowLabelDAO]: One label per ``launching``/``running``
                workflow, sorted by workflow id.
        """
        return [
            LiveWorkflowLabelDAO(workflow_id=workflow_id, state=state)
            for workflow_id, state in sorted(self._workflow_states.items())
            if state in ("launching", "running")
        ]

    def _effects_for_lifecycle(
        self,
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> List[DetachedWorkflowUiEffectDAO]:
        """Build the typed UI effects implied by one lifecycle advance.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            List[DetachedWorkflowUiEffectDAO]: One effect per advance that
                carries an orchestrator session id — ``launch_visualizer``
                for ``started`` advances, ``reset_launch_guard`` for
                ``terminal`` advances; empty when the payload carries no
                orchestrator session id.
        """
        if not parsed.orchestrator_session_id:
            return []
        if parsed.target == "terminal":
            return [self._reset_launch_guard_effect(parsed=parsed)]
        return [self._launch_visualizer_effect(parsed=parsed)]

    @staticmethod
    def _launch_visualizer_effect(
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> DetachedWorkflowUiEffectDAO:
        """Build the launch effect for a ``started`` lifecycle advance.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            DetachedWorkflowUiEffectDAO: The ``launch_visualizer`` effect.
        """
        return DetachedWorkflowUiEffectDAO(
            effect="launch_visualizer",
            orchestrator_session_id=parsed.orchestrator_session_id,
            state=parsed.target_state,
        )

    @staticmethod
    def _reset_launch_guard_effect(
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> DetachedWorkflowUiEffectDAO:
        """Build the reset-only effect for a ``terminal`` lifecycle advance.

        A terminal advance frees the renderer's launch guard so a re-run of
        the workflow opens a fresh window — it never emits a launch effect.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            DetachedWorkflowUiEffectDAO: The ``reset_launch_guard`` effect.
        """
        return DetachedWorkflowUiEffectDAO(
            effect="reset_launch_guard",
            orchestrator_session_id=parsed.orchestrator_session_id,
            state=parsed.target_state,
        )

    async def _advance_durable_handle(self, *, parsed: ParsedWorkflowLifecycleMessageDAO) -> bool:
        """Advance the durable handle, tolerating store failures.

        Unknown workflows and illegal transitions (e.g. a late failure note
        on an aborted handle) are logged, never raised — inbox delivery must
        not fail because a handle file is missing or already terminal.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            bool: ``True`` when the durable handle advanced to the target state.
        """
        try:
            await self._store.update_state(
                owner_session_id=self._owner_session_id,
                workflow_id=parsed.workflow_id,
                state=parsed.target_state,
            )
        except Exception as exc:  # noqa: BLE001 — delivery must not fail on handle errors
            log_info(
                msg="workflow_handle_advance_failed",
                workflow_id=parsed.workflow_id,
                error=str(exc),
            )
            return False
        return True
