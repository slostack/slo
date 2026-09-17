"""Focused collaborator-propagation tests for the current Textual Slo TUI."""

from __future__ import annotations

from typing import cast

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.assembly.factory import (
    DefaultSloClipboardPort,
    DefaultSloDetachedWorkflowRendererFactory,
)
from src.tui.assembly.ports import SloDetachedVisualizerLauncher
from src.tui.workflows.renderer import DetachedWorkflowNoticeSink


class _NoopSessionFactory:
    """Prevent direct test construction from promoting an incomplete fake session."""

    def build_session(self, *, config: object) -> SloAgentSession:
        """Reject an unexpected `/new` replacement in a copy-only test.

        Args:
            config (object): Unused replacement configuration.

        Raises:
            AssertionError: The copy test must not construct a replacement session.
        """
        del config
        raise AssertionError("copy test must not build a replacement session")


class _RecordingOsc52Clipboard:
    """Record the Textual OSC-52 fallback call without a live application."""

    def __init__(self) -> None:
        """Create an empty text record."""
        self.texts: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        """Record one OSC-52-compatible delivery request."""
        self.texts.append(text)


class _RecordingLocalClipboard:
    """Record local clipboard delivery and optionally emulate failure."""

    def __init__(self, *, should_raise: bool = False) -> None:
        """Configure deterministic local-copy behavior."""
        self._should_raise: bool = should_raise
        self.texts: list[str] = []

    def copy(self, *, text: str) -> None:
        """Record the local delivery or fail before OSC-52 fallback."""
        self.texts.append(text)
        if self._should_raise:
            raise RuntimeError("local clipboard unavailable")


class _RecordingVisualizerLauncher:
    """Record visualizer requests through the public launcher port."""

    def __init__(self, *, launched: bool) -> None:
        """Configure the best-effort launch result."""
        self._launched: bool = launched
        self.parent_session_ids: list[str] = []

    def launch(self, *, parent_session_id: str) -> bool:
        """Record and return the configured launch outcome."""
        self.parent_session_ids.append(parent_session_id)
        return self._launched


class _RecordingNoticeSink:
    """Collect renderer notices through its existing public notice port."""

    def __init__(self) -> None:
        """Create an empty notice record."""
        self.notices: list[tuple[str, str]] = []

    def write(self, *, content: str, classes: str = "") -> None:
        """Record one renderer-generated transcript notice."""
        self.notices.append((content, classes))


class _RecordingClipboard:
    """Capture the exact text delegated by SloTUI's existing copy policy."""

    def __init__(self) -> None:
        """Create an empty copy record."""
        self.texts: list[str] = []

    def copy(self, *, text: str) -> None:
        """Record one selected text value."""
        self.texts.append(text)


class TestDefaultSloClipboardPort:
    """Verify the extracted current local-then-OSC-52 transport funnel."""

    def test_copy_delivers_local_clipboard_then_osc52(self) -> None:
        """A successful local copy is followed by the current OSC-52 fallback."""
        local: _RecordingLocalClipboard = _RecordingLocalClipboard()
        osc52: _RecordingOsc52Clipboard = _RecordingOsc52Clipboard()
        port: DefaultSloClipboardPort = DefaultSloClipboardPort(
            local_clipboard=local,
            osc52_clipboard=osc52,
        )

        port.copy(text="selected")

        assert local.texts == ["selected"]
        assert osc52.texts == ["selected"]

    def test_copy_delivers_osc52_when_local_clipboard_fails(self) -> None:
        """A local-copy exception remains non-fatal and cannot block OSC-52."""
        local: _RecordingLocalClipboard = _RecordingLocalClipboard(should_raise=True)
        osc52: _RecordingOsc52Clipboard = _RecordingOsc52Clipboard()
        port: DefaultSloClipboardPort = DefaultSloClipboardPort(
            local_clipboard=local,
            osc52_clipboard=osc52,
        )

        port.copy(text="selected")

        assert local.texts == ["selected"]
        assert osc52.texts == ["selected"]


class TestCurrentTextualCollaboratorPropagation:
    """Verify SloTUI uses explicit Slo-owned collaborators without UI patches."""

    def test_slo_tui_delegates_selected_text_to_the_injected_clipboard_port(self) -> None:
        """Copy selection policy stays in SloTUI while transport delegates once to its port."""
        clipboard: _RecordingClipboard = _RecordingClipboard()
        app: SloTUI = SloTUI(
            session=cast(SloAgentSession, object()),
            clipboard=clipboard,
            session_factory=_NoopSessionFactory(),
        )

        app.copy_to_clipboard(text="selected")

        assert clipboard.texts == ["selected"]

    def test_renderer_factory_propagates_the_injected_visualizer_launcher(self) -> None:
        """Renderer guard behavior calls the supplied launcher and leaves service state untouched."""
        notice_sink: _RecordingNoticeSink = _RecordingNoticeSink()
        launcher: _RecordingVisualizerLauncher = _RecordingVisualizerLauncher(launched=False)
        renderer_factory: DefaultSloDetachedWorkflowRendererFactory = (
            DefaultSloDetachedWorkflowRendererFactory()
        )
        renderer = renderer_factory.build_renderer(
            notice_sink=cast(DetachedWorkflowNoticeSink, notice_sink),
            visualizer_launcher=cast(SloDetachedVisualizerLauncher, launcher),
        )

        renderer.handle_launch_result(
            result_text=(
                '{"workflow_id":"wf-1","owner_session_id":"owner-1",'
                '"orchestrator_session_id":"orchestrator-1","pid":42,'
                '"brief":"brief","cwd":"/tmp"}'
            )
        )

        assert launcher.parent_session_ids == ["orchestrator-1"]
        assert notice_sink.notices == [
            (
                "⊇ Watch the workflow live: slo visualize --session orchestrator-1 --follow",
                "sub-agent-notice",
            )
        ]
