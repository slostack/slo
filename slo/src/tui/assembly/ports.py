"""Typed Slo-owned collaboration ports for current TUI assembly."""

from __future__ import annotations

from typing import Protocol

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.assembly.dao import SloTuiAssemblyConfigDAO
from src.tui.workflows.renderer import (
    DetachedWorkflowNoticeSink,
    DetachedWorkflowRenderer,
)

__all__ = [
    "SloAgentSessionFactory",
    "SloClipboardPort",
    "SloDetachedVisualizerLauncher",
    "SloDetachedWorkflowRendererFactory",
    "SloOsc52ClipboardPort",
    "SloTuiApplication",
    "SloTuiApplicationFactory",
    "SloTuiAssemblyFactory",
    "SloTuiRunner",
    "SloTuiSessionFactory",
]


class SloTuiSessionFactory(Protocol):
    """Build a lazy-session configuration from resolved interactive facts."""

    def build_config(self, *, config: SloTuiAssemblyConfigDAO) -> SessionConfigDAO:
        """Build the session configuration without credential or provider activity.

        WHAT: Translates resolved interactive facts into Slo's existing session DAO.
        WHO: The assembly factory calls this before constructing its lazy session.
        WHEN: After closed-scenario validation and before all provider-facing work.

        Args:
            config (SloTuiAssemblyConfigDAO): Immutable resolved interactive inputs.

        Returns:
            SessionConfigDAO: Configuration retained by the lazy agent session.
        """
        ...


class SloAgentSessionFactory(Protocol):
    """Build Slo's lazy agent-session wrapper from existing session configuration."""

    def build_session(self, *, config: SessionConfigDAO) -> SloAgentSession:
        """Create a session without invocation or credential refresh.

        WHAT: Delegates to Slo's lazy session builder.
        WHO: The assembly factory calls this once for each initial session.
        WHEN: After session configuration and before orchestrator promotion.

        Args:
            config (SessionConfigDAO): Valid existing session configuration.

        Returns:
            SloAgentSession: A session that has not invoked its provider path.
        """
        ...


class SloClipboardPort(Protocol):
    """Deliver already-selected text through Slo's clipboard transport funnel."""

    def copy(self, *, text: str) -> None:
        """Deliver selected text without choosing it.

        WHAT: Performs Slo's best-effort copy transport for one selected value.
        WHO: Current SloTUI calls this after its existing selection policy resolves text.
        WHEN: During an operator copy action with non-empty selected text.

        Args:
            text (str): The selected text to deliver unchanged.
        """
        ...


class SloOsc52ClipboardPort(Protocol):
    """Write selected text through Textual's terminal OSC-52 clipboard seam."""

    def copy_to_clipboard(self, text: str) -> None:
        """Write selected text to the terminal clipboard transport.

        WHAT: Delegates the terminal-native OSC-52 delivery owned by the current app.
        WHO: DefaultSloClipboardPort calls this after its local best-effort copy attempt.
        WHEN: During every current copy action, including local-copy failure.

        Args:
            text (str): Selected text to emit through the terminal clipboard path.
        """
        ...


class SloDetachedVisualizerLauncher(Protocol):
    """Launch Slo's detached-workflow visualizer with a best-effort result."""

    def launch(self, *, parent_session_id: str) -> bool:
        """Attempt one visualizer launch without changing workflow state.

        WHAT: Delegates to Slo's concrete platform-aware visualizer launcher.
        WHO: Current Slo TUI paths and its workflow renderer consume this port.
        WHEN: After Slo workflow policy asks for a visualizer window.

        Args:
            parent_session_id (str): Detached orchestrator session to visualize.

        Returns:
            bool: True only if a visualizer window was launched.
        """
        ...


class SloDetachedWorkflowRendererFactory(Protocol):
    """Construct Slo's existing detached-workflow effect renderer."""

    def build_renderer(
        self,
        *,
        notice_sink: DetachedWorkflowNoticeSink,
        visualizer_launcher: SloDetachedVisualizerLauncher,
    ) -> DetachedWorkflowRenderer:
        """Build the current workflow renderer from its narrow Slo collaborators.

        WHAT: Supplies a transcript notice sink and visualizer launch port to Slo's renderer.
        WHO: SloTUI composes this after its transcript sink exists.
        WHEN: Lazily on the first detached-workflow UI effect.

        Args:
            notice_sink (DetachedWorkflowNoticeSink): Current transcript notice surface.
            visualizer_launcher (SloDetachedVisualizerLauncher): Best-effort visualizer port.

        Returns:
            DetachedWorkflowRenderer: Current renderer retaining launch-guard ownership.
        """
        ...


class SloTuiApplication(Protocol):
    """Represent the synchronous runner surface of the current Slo application."""

    def run(self, *, mouse: bool) -> None:
        """Run the current terminal application once.

        WHAT: Enters the application's synchronous event-loop boundary.
        WHO: The current assembly runner calls this as its final assembly action.
        WHEN: After all local collaborators have been constructed successfully.

        Args:
            mouse (bool): Whether mouse support is enabled for the current TUI.
        """
        ...


class SloTuiApplicationFactory(Protocol):
    """Construct current Slo presentation from fully assembled Slo collaborators."""

    def build_application(
        self,
        *,
        session: SloAgentSession,
        clipboard: SloClipboardPort,
        detached_workflow_renderer_factory: SloDetachedWorkflowRendererFactory,
        visualizer_launcher: SloDetachedVisualizerLauncher,
        session_factory: SloAgentSessionFactory,
    ) -> SloTuiApplication:
        """Build the current application without running it.

        WHAT: Injects explicit Slo presentation collaborators into the current TUI.
        WHO: The assembly factory calls this after session construction and promotion.
        WHEN: Once per selected interactive process before its sole runner call.

        Args:
            session (SloAgentSession): Promoted lazy interactive session.
            clipboard (SloClipboardPort): Slo clipboard delivery port.
            detached_workflow_renderer_factory (SloDetachedWorkflowRendererFactory): Renderer builder.
            visualizer_launcher (SloDetachedVisualizerLauncher): Best-effort visualizer port.
            session_factory (SloAgentSessionFactory): Factory retained for current `/new` replacement.

        Returns:
            SloTuiApplication: Current application before event-loop startup.
        """
        ...


class SloTuiRunner(Protocol):
    """Run the assembled current application exactly once."""

    def run(self, *, application: SloTuiApplication, mouse: bool) -> None:
        """Enter the current application's event loop.

        WHAT: Invokes the selected application's synchronous run entry point.
        WHO: The assembly factory calls this as its final successful step.
        WHEN: After local assembly completes without credentials or provider work.

        Args:
            application (SloTuiApplication): Fully constructed current application.
            mouse (bool): Existing Textual mouse-mode setting.
        """
        ...


class SloTuiAssemblyFactory(Protocol):
    """Assemble and run one closed-scenario Slo interactive process."""

    def run(self, *, config: SloTuiAssemblyConfigDAO) -> None:
        """Assemble and start the selected Slo TUI.

        WHAT: Validates local facts, composes current Slo collaborators, then starts one app.
        WHO: A future CLI caller will invoke this after resolving command-line facts.
        WHEN: Only on the interactive TUI path, never headless or visualizer routes.

        Args:
            config (SloTuiAssemblyConfigDAO): Closed scenario plus resolved interactive facts.
        """
        ...
