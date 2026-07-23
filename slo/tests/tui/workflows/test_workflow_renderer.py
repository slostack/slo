"""Tests for ``DetachedWorkflowRenderer`` with fake sink and launcher (spec 57.a.5)."""

from __future__ import annotations

from typing import List, Tuple

from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowState
from src.tui.workflows.dao import DetachedWorkflowUiEffectDAO
from src.tui.workflows.renderer import DetachedWorkflowRenderer


class _FakeNoticeSink:
    """In-memory notice sink recording every written line."""

    def __init__(self) -> None:
        """Start with an empty notice log."""
        self.lines: List[Tuple[str, str]] = []

    def write(self, content: str, classes: str = "") -> None:
        """Record one notice line.

        Args:
            content (str): Notice text.
            classes (str): Semantic render class.
        """
        self.lines.append((content, classes))


class _FakeLauncher:
    """Scriptable launcher recording calls and returning a fixed outcome."""

    def __init__(self, *, launched: bool) -> None:
        """Fix the launch outcome.

        Args:
            launched (bool): Value every launch call returns.
        """
        self._launched: bool = launched
        self.calls: List[str] = []

    def __call__(self, *, parent_session_id: str) -> bool:
        """Record one launch call and return the scripted outcome.

        Args:
            parent_session_id (str): Detached orchestrator session id.

        Returns:
            bool: The scripted launch outcome.
        """
        self.calls.append(parent_session_id)
        return self._launched


def _launch_effect(*, orchestrator_session_id: str = "orch-1") -> DetachedWorkflowUiEffectDAO:
    """Build one launch-visualizer effect.

    Args:
        orchestrator_session_id (str): Effect target session id.

    Returns:
        DetachedWorkflowUiEffectDAO: The typed effect.
    """
    return DetachedWorkflowUiEffectDAO(
        effect="launch_visualizer",
        orchestrator_session_id=orchestrator_session_id,
        state="running",
    )


def _reset_effect(
    *,
    orchestrator_session_id: str = "orch-1",
    state: WorkflowState = "completed",
) -> DetachedWorkflowUiEffectDAO:
    """Build one reset-launch-guard effect.

    Args:
        orchestrator_session_id (str): Effect target session id.
        state (WorkflowState): Typed terminal state the effect carries.

    Returns:
        DetachedWorkflowUiEffectDAO: The typed reset effect.
    """
    return DetachedWorkflowUiEffectDAO(
        effect="reset_launch_guard",
        orchestrator_session_id=orchestrator_session_id,
        state=state,
    )


def _build_renderer(
    *,
    launched: bool = True,
) -> tuple[DetachedWorkflowRenderer, _FakeNoticeSink, _FakeLauncher]:
    """Build a renderer wired to fresh fakes.

    Args:
        launched (bool): Scripted launcher outcome.

    Returns:
        tuple: ``(renderer, notice_sink, launcher)``.
    """
    sink: _FakeNoticeSink = _FakeNoticeSink()
    launcher: _FakeLauncher = _FakeLauncher(launched=launched)
    renderer: DetachedWorkflowRenderer = DetachedWorkflowRenderer(
        notice_sink=sink,
        launcher=launcher,
    )
    return renderer, sink, launcher


class TestLaunchDeDuplication:
    """One visualizer window per orchestrator session id while live."""

    def test_first_effect_launches_and_writes_success_notice(self) -> None:
        """A fresh launch effect opens the window and writes the success line."""
        renderer, sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1"]
        assert sink.lines == [
            (
                "⊇ Opened workflow visualizer in a new window (session orch-1).",
                "sub-agent-notice",
            )
        ]

    def test_duplicate_effect_launches_only_once(self) -> None:
        """A second effect for the same session id is guarded out."""
        renderer, sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_launch_effect()])
        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1"]
        assert len(sink.lines) == 1

    def test_distinct_session_ids_each_launch(self) -> None:
        """The guard is per orchestrator session id, not global."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(
            effects=[_launch_effect(), _launch_effect(orchestrator_session_id="orch-2")],
        )

        assert launcher.calls == ["orch-1", "orch-2"]


class TestFallbackNotice:
    """A skipped/failed spawn writes the manual visualize command."""

    def test_failed_launch_writes_manual_command_hint(self) -> None:
        """A ``False`` launch writes the ``slo visualize`` fallback line."""
        renderer, sink, launcher = _build_renderer(launched=False)

        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1"]
        assert sink.lines == [
            (
                "⊇ Watch the workflow live: slo visualize --session orch-1 --follow",
                "sub-agent-notice",
            )
        ]


class TestHandleLaunchResult:
    """The launch-result path re-validates before launching."""

    def test_valid_result_launches(self) -> None:
        """A valid handle JSON opens the visualizer."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.handle_launch_result(
            result_text='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"}',
        )

        assert launcher.calls == ["orch-1"]

    def test_malformed_json_never_launches(self) -> None:
        """Malformed tool-result text is a safe no-op."""
        renderer, sink, launcher = _build_renderer(launched=True)

        renderer.handle_launch_result(result_text="not json {")

        assert launcher.calls == []
        assert sink.lines == []

    def test_error_json_never_launches(self) -> None:
        """Error JSON carries no orchestrator id and never launches."""
        renderer, sink, launcher = _build_renderer(launched=True)

        renderer.handle_launch_result(result_text='{"error": "workflow cap reached"}')

        assert launcher.calls == []
        assert sink.lines == []

    def test_result_shares_guard_with_lifecycle_effects(self) -> None:
        """A launch result and a later started note launch only once."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.handle_launch_result(result_text='{"orchestrator_session_id": "orch-1"}')
        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1"]


class TestTerminalReset:
    """Typed ``reset_launch_guard`` effects free the launch guard."""

    def test_reset_effect_allows_relaunch(self) -> None:
        """A completed workflow's re-run opens a fresh window."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_launch_effect()])
        renderer.apply_effects(effects=[_reset_effect(state="completed")])
        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1", "orch-1"]

    def test_failed_state_reset_also_allows_relaunch(self) -> None:
        """A ``failed`` reset effect frees the guard just like ``completed``."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_launch_effect()])
        renderer.apply_effects(effects=[_reset_effect(state="failed")])
        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1", "orch-1"]

    def test_reset_effect_never_launches_or_writes_notices(self) -> None:
        """A reset effect is guard-reset only: no launch, no transcript line."""
        renderer, sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_reset_effect(state="completed")])

        assert launcher.calls == []
        assert sink.lines == []

    def test_without_reset_effect_the_guard_stays_held(self) -> None:
        """Back-to-back launch effects open exactly one window."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_launch_effect()])
        renderer.apply_effects(effects=[_launch_effect()])

        assert launcher.calls == ["orch-1"]

    def test_empty_orchestrator_id_reset_is_a_noop(self) -> None:
        """A reset effect without an orchestrator id touches no guard entry."""
        renderer, _sink, launcher = _build_renderer(launched=True)

        renderer.apply_effects(effects=[_reset_effect(orchestrator_session_id="")])

        assert launcher.calls == []
