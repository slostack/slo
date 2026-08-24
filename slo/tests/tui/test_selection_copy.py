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

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


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
