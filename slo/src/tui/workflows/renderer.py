"""Renderer for detached-workflow UI effects (spec 57.a.5).

Consumes the typed effects emitted by ``DetachedWorkflowAppService`` and
executes them: owns the one-window-per-orchestrator-session launch guard,
calls ``VisualizerLauncher``, and writes the success / manual-command
transcript notices. This is the only layer of the receive path allowed to
touch the visualizer launcher and the transcript notice surface.
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from src.tui.visualizer_launcher import VisualizerLauncher
from src.tui.workflows.dao import (
    DetachedWorkflowUiEffectDAO,
    ParsedLaunchResultDAO,
    parse_launch_workflow_result,
)

__all__ = ["DetachedWorkflowRenderer", "DetachedWorkflowNoticeSink", "DetachedVisualizerLaunch"]


class DetachedWorkflowNoticeSink(Protocol):
    """Narrow transcript seam the renderer writes notices into."""

    def write(self, *, content: str, classes: str = "") -> None:
        """Write one transcript notice line.

        Args:
            content (str): Notice text.
            classes (str): Semantic render class.
        """
        ...


class DetachedVisualizerLaunch(Protocol):
    """Narrow launcher seam — satisfied by ``VisualizerLauncher.launch``."""

    def __call__(self, *, parent_session_id: str) -> bool:
        """Open the visualizer window for one orchestrator session.

        Args:
            parent_session_id (str): Detached orchestrator session id.

        Returns:
            bool: ``True`` when a terminal window was spawned.
        """
        ...


class DetachedWorkflowRenderer:
    """Execute detached-workflow UI effects with launch de-duplication.

    The launch guard is keyed by ``orchestrator_session_id`` — not per run —
    so one detached workflow opens at most one visualizer window while it is
    live. The ``reset_launch_guard`` effect (emitted only by terminal
    lifecycle advances) frees the guard so a re-run of the same workflow
    gets a fresh window. Launch is best-effort: a skipped or failed spawn
    writes the manual ``slo visualize`` command to the transcript instead of
    the success line.
    """

    def __init__(
        self,
        *,
        notice_sink: DetachedWorkflowNoticeSink,
        launcher: Optional[DetachedVisualizerLaunch] = None,
    ) -> None:
        """Bind the renderer to its notice sink and launcher.

        Args:
            notice_sink (DetachedWorkflowNoticeSink): Transcript notice surface.
            launcher (Optional[DetachedVisualizerLaunch]): Visualizer launch
                callable for tests. ``None`` resolves to
                ``VisualizerLauncher.launch`` at call time so the class-level
                patch seam used across the suite keeps working.
        """
        self._notice_sink: DetachedWorkflowNoticeSink = notice_sink
        self._launcher: Optional[DetachedVisualizerLaunch] = launcher
        self._launched_for: set[str] = set()

    def handle_launch_result(self, *, result_text: str) -> None:
        """Execute the launch-result path for one ``launch_workflow`` tool result.

        WHAT: re-validates the tool-result text (malformed/error JSON is a
            safe no-op) and asks the visualizer to open for a valid handle.
        WHO: the TUI live render path on ``launch_workflow`` tool results.
        WHEN: during the launch turn, after the app service has seeded the
            live-state cache.

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.
        """
        orchestrator_session_id: str = self._orchestrator_session_id_from_result(
            result_text=result_text,
        )
        self._launch_once(orchestrator_session_id=orchestrator_session_id)

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
        launch: DetachedVisualizerLaunch = self._launcher or VisualizerLauncher.launch
        launched: bool = launch(parent_session_id=orchestrator_session_id)
        self._write_launch_notice(
            launched=launched,
            orchestrator_session_id=orchestrator_session_id,
        )

    def _write_launch_notice(self, *, launched: bool, orchestrator_session_id: str) -> None:
        """Write the success or manual-command transcript notice.

        Args:
            launched (bool): Whether the window spawn succeeded.
            orchestrator_session_id (str): Detached orchestrator session id.
        """
        if launched:
            self._notice_sink.write(
                content=(
                    "⊇ Opened workflow visualizer in a new window " f"(session {orchestrator_session_id})."
                ),
                classes="sub-agent-notice",
            )
            return
        self._notice_sink.write(
            content=(
                "⊇ Watch the workflow live: " f"slo visualize --session {orchestrator_session_id} --follow"
            ),
            classes="sub-agent-notice",
        )

    @staticmethod
    def _orchestrator_session_id_from_result(*, result_text: str) -> str:
        """Re-extract the orchestrator session id from a tool-result text.

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.

        Returns:
            str: The orchestrator session id, or ``""`` for malformed/error
                JSON — the launch guard treats ``""`` as a no-op.
        """
        parsed: ParsedLaunchResultDAO | None = parse_launch_workflow_result(result_text=result_text)
        if parsed is None:
            return ""
        return parsed.orchestrator_session_id
