"""Unit tests for mouse-selection auto-copy and the clipboard-delivery override.

Covers ``SloTUI.on_text_selected`` (sub-spec 68.b.3) and
``SloTUI.copy_to_clipboard`` / ``_copy_via_local_clipboard`` (sub-spec 68.b.4).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual import events
from textual.app import App
from textual.containers import Vertical
from textual.widgets import Static

from src.tui.app import PromptInput
from src.tui.widgets.tool_execution_block import ToolExecutionBlock

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.user_message_block import UserMessageBlock


def _build_session() -> SloAgentSession:
    """Build a faux-model session for selection/clipboard tests.

    Returns:
        SloAgentSession: Session driven by a faux assistant response.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestOnTextSelected:
    """``SloTUI.on_text_selected`` auto-copy behaviour (68.b.3)."""

    @pytest.mark.asyncio
    async def test_on_text_selected_copies_non_empty_selection(self) -> None:
        """A non-empty screen selection is handed to the clipboard funnel."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.get_selected_text = MagicMock(return_value="hello world")  # type: ignore[method-assign]
            copied: list[str] = []
            app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign, assignment]

            app.post_message(events.TextSelected())
            await pilot.pause()

            assert copied == ["hello world"]

    @pytest.mark.asyncio
    async def test_on_text_selected_noop_on_empty_selection(self) -> None:
        """A ``None`` selection copies nothing."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.get_selected_text = MagicMock(return_value=None)  # type: ignore[method-assign]
            copied: list[str] = []
            app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign, assignment]

            app.post_message(events.TextSelected())
            await pilot.pause()

            assert copied == []

    @pytest.mark.asyncio
    async def test_on_text_selected_noop_on_blank_selection(self) -> None:
        """An empty-string selection copies nothing."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.get_selected_text = MagicMock(return_value="")  # type: ignore[method-assign]
            copied: list[str] = []
            app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign, assignment]

            app.post_message(events.TextSelected())
            await pilot.pause()

            assert copied == []


class TestRawMarkdownCopy:
    """Explicit raw-copy action and its nearest-owner resolver."""

    def test_registers_the_required_raw_markdown_key_chords(self) -> None:
        """The paired raw-copy chords remain discoverable in the app binding registry."""
        bindings_by_key = {binding.key: binding.action for binding in SloTUI.BINDINGS}
        assert bindings_by_key["ctrl+shift+m"] == "copy_raw_markdown"
        assert bindings_by_key["meta+shift+m"] == "copy_raw_markdown"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["answer", "thinking", "user"])
    async def test_copies_raw_markdown_from_focused_inner_body(self, kind: str) -> None:
        """A body focus resolves only to its nearest transcript owner provider."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            if kind == "answer":
                block = await app.mount_assistant_block()
                block.finalize(final_text="# answer")
                body = block._answer_body
            elif kind == "thinking":
                block = await app.mount_thinking_block()
                block.set_thinking(content="# thinking")
                body = block._body
            else:
                block = await app.mount_user_message_block(text="# user")
                body = block._body
            app.screen.focused = body  # type: ignore[attr-defined]
            await app.action_copy_raw_markdown()
            assert app._clipboard == block.get_raw_markdown_for_copy()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["prompt", "tool", "notice", "generic"])
    async def test_raw_copy_noops_for_non_provider_focuses(self, kind: str) -> None:
        """Non-transcript-provider focus targets never invoke the clipboard funnel."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            if kind == "prompt":
                target = app._input
            elif kind == "tool":
                target = await app.mount_tool_execution_block(tool_call_id="call", tool_name="read")
            elif kind == "notice":
                target = Static("notice")
                await app.mount(target)
            else:
                target = Static("generic")
                await app.mount(target)
            assert target is not None
            app.screen.focused = target  # type: ignore[attr-defined]
            app.copy_to_clipboard = MagicMock()  # type: ignore[method-assign]

            await app.action_copy_raw_markdown()

            app.copy_to_clipboard.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_copy_noops_without_focus(self) -> None:
        """An absent focus chain leaves raw copy as an intentional no-op."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            app.screen.focused = None  # type: ignore[attr-defined]
            app.copy_to_clipboard = MagicMock()  # type: ignore[method-assign]

            await app.action_copy_raw_markdown()

            app.copy_to_clipboard.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_value", [None, 42, ""])
    async def test_raw_copy_noops_for_invalid_or_empty_nearest_provider(self, provider_value: object) -> None:
        """A present nearest provider terminates resolution when it declines raw text."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            ancestor = Vertical(Static("target"))
            await app.mount(ancestor)
            target = ancestor.children[0]
            ancestor.get_raw_markdown_for_copy = MagicMock(return_value="ancestor raw")  # type: ignore[attr-defined]
            target.get_raw_markdown_for_copy = provider_value  # type: ignore[attr-defined]
            app.screen.focused = target  # type: ignore[attr-defined]
            app.copy_to_clipboard = MagicMock()  # type: ignore[method-assign]

            await app.action_copy_raw_markdown()

            app.copy_to_clipboard.assert_not_called()
            ancestor.get_raw_markdown_for_copy.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_copy_terminates_at_empty_callable_nearest_provider(self) -> None:
        """An empty callable provider runs once and prevents farther ancestor fallback."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            ancestor = Vertical(Static("target"))
            await app.mount(ancestor)
            target = ancestor.children[0]
            nearest_provider = MagicMock(return_value="")
            farther_provider = MagicMock(return_value="ancestor raw")
            target.get_raw_markdown_for_copy = nearest_provider  # type: ignore[attr-defined]
            ancestor.get_raw_markdown_for_copy = farther_provider  # type: ignore[attr-defined]
            app.screen.focused = target  # type: ignore[attr-defined]
            app.copy_to_clipboard = MagicMock()  # type: ignore[method-assign]

            await app.action_copy_raw_markdown()

            nearest_provider.assert_called_once_with()
            farther_provider.assert_not_called()
            app.copy_to_clipboard.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_copy_uses_the_single_clipboard_funnel_once_on_success(self) -> None:
        """A provider success invokes only the established clipboard writer exactly once."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            block = await app.mount_user_message_block(text="# raw")
            app.screen.focused = block  # type: ignore[attr-defined]
            app.copy_to_clipboard = MagicMock()  # type: ignore[method-assign]

            await app.action_copy_raw_markdown()

            app.copy_to_clipboard.assert_called_once_with("# raw")


class TestCopyToClipboard:
    """``SloTUI.copy_to_clipboard`` local-then-OSC-52 delivery (68.b.4)."""

    @pytest.mark.asyncio
    async def test_copy_to_clipboard_tries_pyperclip_then_osc52(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The funnel copies via pyperclip first, then always via the OSC 52 base."""
        import pyperclip

        order: list[str] = []
        monkeypatch.setattr(pyperclip, "copy", lambda text: order.append(f"pyperclip:{text}"))

        app: SloTUI = SloTUI(session=_build_session())
        original_super = App.copy_to_clipboard

        def _record_super(self: App, text: str) -> None:
            order.append(f"osc52:{text}")
            original_super(self, text)

        monkeypatch.setattr(App, "copy_to_clipboard", _record_super)

        async with app.run_test() as pilot:
            await pilot.pause()
            app.copy_to_clipboard("payload")

            assert order == ["pyperclip:payload", "osc52:payload"]
            assert app._clipboard == "payload"

    @pytest.mark.asyncio
    async def test_copy_to_clipboard_survives_pyperclip_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing pyperclip never blocks the OSC 52 write."""
        monkeypatch.setitem(sys.modules, "pyperclip", None)

        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.copy_to_clipboard("payload")

            assert app._clipboard == "payload"

    @pytest.mark.asyncio
    async def test_copy_to_clipboard_survives_pyperclip_copy_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pyperclip copy error is swallowed; OSC 52 still runs."""
        import pyperclip

        def _raise(text: str) -> None:
            raise RuntimeError("no display")

        monkeypatch.setattr(pyperclip, "copy", _raise)

        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.copy_to_clipboard("payload")

            assert app._clipboard == "payload"

    @pytest.mark.asyncio
    async def test_copy_to_clipboard_emits_osc52(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The OSC 52 base path is reached and sets the app clipboard."""
        import pyperclip

        monkeypatch.setattr(pyperclip, "copy", lambda text: None)

        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            app.copy_to_clipboard("payload")

            assert app._clipboard == "payload"

    def test_copy_via_local_clipboard_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The helper reports success when pyperclip copies without raising."""
        import pyperclip

        monkeypatch.setattr(pyperclip, "copy", lambda text: None)

        assert SloTUI._copy_via_local_clipboard(text="x") is True

    def test_copy_via_local_clipboard_returns_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The helper reports failure when pyperclip raises."""
        import pyperclip

        def _raise(text: str) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(pyperclip, "copy", _raise)

        assert SloTUI._copy_via_local_clipboard(text="x") is False
