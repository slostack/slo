"""Present typed workflow effects without parsing raw results or launching windows.

The app owns scheduling, captured session lifetime and async execution. This
renderer owns per-parent deduplication and shared attached/detached notices.
"""

from __future__ import annotations

from typing import List, Protocol

from src.agents.slo_agent.herdr.dao import VisualizerLaunchOutcomeDAO
from src.tui.workflows.dao import DetachedWorkflowUiEffectDAO

__all__ = ["DetachedWorkflowRenderer", "DetachedWorkflowNoticeSink", "DetachedVisualizerSchedule"]


class DetachedWorkflowNoticeSink(Protocol):
    """Narrow transcript seam the renderer writes notices into."""

    def write(self, *, content: str, classes: str = "") -> None:
        """Write one transcript notice line.

        Args:
            content (str): Notice text.
            classes (str): Semantic render class.
        """
        ...


class DetachedVisualizerSchedule(Protocol):
    """Register work with the app-owned registry without executing a launch."""

    def __call__(self, *, parent_session_id: str) -> None:
        """Schedule the captured workflow parent; return no launch result."""
        ...


class DetachedWorkflowRenderer:
    """Deduplicate typed launch effects and present completed launch outcomes."""

    def __init__(
        self,
        *,
        notice_sink: DetachedWorkflowNoticeSink,
        schedule: DetachedVisualizerSchedule,
    ) -> None:
        """Bind transcript presentation and the app-owned scheduling callback.

        Args:
            notice_sink: Transcript notice surface.
            schedule: Synchronous registration only, never a window launcher.
        """
        self._notice_sink = notice_sink
        self._schedule = schedule
        self._launched_for: set[str] = set()

    def apply_effects(self, *, effects: List[DetachedWorkflowUiEffectDAO]) -> None:
        """Execute every typed UI effect in one lifecycle outcome.

        Args:
            effects (List[DetachedWorkflowUiEffectDAO]): Effects to execute.
        """
        for effect in effects:
            self._apply_effect(effect=effect)

    def _apply_effect(self, *, effect: DetachedWorkflowUiEffectDAO) -> None:
        """Execute one typed UI effect.

        Args:
            effect (DetachedWorkflowUiEffectDAO): Effect under execution.
        """
        if effect.effect == "launch_visualizer":
            self._launch_once(orchestrator_session_id=effect.orchestrator_session_id)
            return
        self._reset_launch_guard(effect=effect)

    def _reset_launch_guard(self, *, effect: DetachedWorkflowUiEffectDAO) -> None:
        """Free the launch guard for one ``reset_launch_guard`` effect.

        The effect's typed ``state`` is recorded for callers/tests that need
        the terminal state; the guard reset itself is unconditional on it —
        the app service only emits this effect for terminal advances.

        Args:
            effect (DetachedWorkflowUiEffectDAO): The reset effect under
                execution. An empty orchestrator session id is a no-op.
        """
        if not effect.orchestrator_session_id:
            return
        self._launched_for.discard(effect.orchestrator_session_id)

    def _launch_once(self, *, orchestrator_session_id: str) -> None:
        """Open the visualizer at most once per orchestrator session id.

        Args:
            orchestrator_session_id (str): Detached orchestrator session id.
        """
        if not orchestrator_session_id:
            return
        if orchestrator_session_id in self._launched_for:
            return
        self._launched_for.add(orchestrator_session_id)
        self._schedule(parent_session_id=orchestrator_session_id)

    def write_launch_outcome(
        self,
        *,
        parent_session_id: str,
        outcome: VisualizerLaunchOutcomeDAO,
    ) -> None:
        """Present a completed request without claiming viewer process liveness.

        Args:
            parent_session_id: Captured request identity.
            outcome: Safe typed execution result, never raw CLI output.
        """
        try:
            self._write_launch_notice(parent_session_id=parent_session_id, outcome=outcome)
        finally:
            if outcome.status == "failed":
                self._launched_for.discard(parent_session_id)

    def _write_launch_notice(
        self,
        *,
        parent_session_id: str,
        outcome: VisualizerLaunchOutcomeDAO,
    ) -> None:
        """Format the shared attached/detached typed completion notice."""
        notices = {
            "opened": "Opened workflow visualizer in a new window.",
            "submitted": "Submitted workflow viewer command to Herdr pane",
            "reused": "Previously attempted viewer; Select the retained Herdr pane if still present",
            "failed": "Workflow viewer launch failed; recover manually",
            "skipped": "Workflow viewer launch skipped; open manually",
        }
        content = notices[outcome.status]
        if outcome.pane_id is not None:
            content += f" ({outcome.pane_id})."
        if outcome.status == "reused":
            content += " Otherwise run in a pane you choose:"
        if outcome.status in ("failed", "skipped", "reused"):
            content += f" slo visualize --session {parent_session_id} --follow"
        self._notice_sink.write(content=f"⊇ {content}", classes="sub-agent-notice")
