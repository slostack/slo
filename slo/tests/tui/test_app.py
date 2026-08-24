"""Pilot tests for ``SloTUI`` (sub-spec 02.a.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from textual import events
from textual.app import App
from textual.message import Message
from textual.widget import Widget
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool

from config.logger import interactive_logging, log_info
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import (
    LOAD_OLDER_BATCH_SIZE,
    TRANSCRIPT_HYDRATION_ENTRY_LIMIT,
    TRANSCRIPT_PROTECTED_TAIL_SIZE,
    TRANSCRIPT_WINDOW_SIZE,
    PromptInput,
    SloTUI,
    TranscriptScroll,
)
from src.tui.authentication import AuthenticationScreen
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO
from src.tui.thinking_spinner import ThinkingSpinner
from tests.tui._scroll_settle import pump_until
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.steering_pending_block import SteeringPendingBlock
from src.tui.widgets.user_message_block import UserMessageBlock


def _build_session(*, responses: list[AIMessage]) -> SloAgentSession:
    """Build a ``SloAgentSession`` driven by a Faux LLM.

    Args:
        responses (list[AIMessage]): Scripted Faux responses.

    Returns:
        SloAgentSession: A session ready to drive a ``SloTUI``.
    """
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=responses))
    return SloAgentSession(
        agent=agent,
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


async def _await_idle(
    *,
    app: SloTUI,
    pilot,
    timeout_seconds: float = 5.0,
) -> None:
    """Poll until ``app._in_flight_task is None`` or timeout.

    Args:
        app (SloTUI): The app under test.
        pilot: The Textual Pilot driver.
        timeout_seconds (float): Maximum wait before failing.
    """
    deadline: float = asyncio.get_event_loop().time() + timeout_seconds
    while app._in_flight_task is not None:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("timed out waiting for in-flight task to clear")
        await pilot.pause()


def _require_prompt_input(*, app: SloTUI) -> PromptInput:
    """Return the mounted prompt input.

    Args:
        app (SloTUI): The app under test.

    Returns:
        PromptInput: The mounted prompt editor.
    """
    assert app._input is not None
    return app._input


def _visible_prompt_lines(*, app: SloTUI) -> int:
    """Return the visible prompt-editor content height in lines.

    Args:
        app (SloTUI): The app under test.

    Returns:
        int: The number of visible content lines inside ``PromptInput``.
    """
    prompt_input: PromptInput = _require_prompt_input(app=app)
    return prompt_input.size.height


class TestSloTUIActiveModelState:
    """Title rendering, slash-triggered refresh, and auth-success provider switching."""

    @pytest.mark.asyncio
    async def test_title_uses_session_active_model_and_reasoning_state(self) -> None:
        """Mount-time title reflects the session active model and reasoning level."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert "claude-sonnet-4-6" in app.title
            assert "reasoning high" in app.title

    @pytest.mark.asyncio
    async def test_auth_dismissed_switches_to_provider_default_model(self) -> None:
        """Anthropic auth success switches away from an OpenAI active model."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "gpt-5.4"
        session.routed_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        def _switch(*, model_name: str) -> None:
            session.active_model_name = model_name
            session.routed_model_name = model_name

        session.switch_model = MagicMock(side_effect=_switch)

        app: SloTUI = SloTUI(session=session)
        value: CredentialDAO = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token="oauth-token",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            app._on_auth_dismissed(value)
            await pilot.pause()
            session.switch_model.assert_called_once_with(model_name="claude-opus-4-8-1m-context")
            assert "claude-opus-4-8-1m-context" in app.title
            assert "reasoning high" in app.title
            assert (
                "active model switched to claude-opus-4-8-1m-context",
                "tool-result",
            ) in app._adapter.lines

    @pytest.mark.asyncio
    async def test_dispatch_slash_command_refreshes_title_when_requested(self) -> None:
        """Slash-command results with ``refresh_title=True`` update the top bar immediately."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.app.SlashRouter.dispatch",
                return_value=MagicMock(
                    rendered="reasoning changed high -> off",
                    should_clear=False,
                    open_auth_modal=False,
                    should_exit=False,
                    refresh_title=True,
                    replace_session=False,
                    requested_session_name=None,
                    rename_current_session_to=None,
                    toggle_theme=False,
                ),
            ):
                with patch.object(app, "_refresh_title_bar") as mock_refresh_title_bar:
                    await app._dispatch_slash_command(line="/reasoning off")
                    await pilot.pause()

            mock_refresh_title_bar.assert_called_once_with()
            assert ("reasoning changed high -> off", "tool-result") in app._adapter.lines


class TestSloTUI:
    """Pilot-driven tests for the ``slo`` Textual app."""

    @pytest.mark.asyncio
    async def test_subtitle_uses_session_name_when_present(self) -> None:
        """The subtitle shows the session name and full (untruncated) id."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = "customer import regression"
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.sub_title == "session customer import regression · session-1234"

    @pytest.mark.asyncio
    async def test_subtitle_shows_full_session_id_without_truncation(self) -> None:
        """A full UUID session id is shown verbatim — never sliced to a prefix."""
        full_id: str = "a166b82b-617e-45c6-9ada-a36f1c589fb6"
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = full_id
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.sub_title == f"session {full_id}"

    @pytest.mark.asyncio
    async def test_rename_session_updates_subtitle_immediately(self) -> None:
        """Renaming the active session refreshes the subtitle right away."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        async def _rename_session(*, session_name: str) -> None:
            session.session_name = session_name

        session.rename_session = AsyncMock(side_effect=_rename_session)

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._rename_current_session(session_name="release prep")
            await pilot.pause()

            assert app.sub_title.startswith("session release prep · session-")
            assert ("session renamed to release prep", "tool-result") in app._adapter.lines


class TestSloTUISessionInbox:
    """Lease and SessionInbox delivery behavior."""

    @pytest.mark.asyncio
    async def test_mount_acquires_and_unmount_releases_session_lease(self, tmp_path: Path) -> None:
        """History-backed TUI sessions hold an active lease only while mounted."""
        history_root: Path = tmp_path / "history"
        lease_store: SessionOwnershipLeaseStore = SessionOwnershipLeaseStore(history_root=history_root)
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = history_root
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session, lease_store=lease_store)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert await lease_store.is_active(session_id="session-1234") is True

        assert await lease_store.is_active(session_id="session-1234") is False

    @pytest.mark.asyncio
    async def test_poll_session_inbox_renders_ui_notice(self, tmp_path: Path) -> None:
        """`ui_notice` inbox items render a low-noise notice and are acked."""
        history_root: Path = tmp_path / "history"
        inbox_store: SessionInboxStore = SessionInboxStore(history_root=history_root)
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = history_root
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session, inbox_store=inbox_store)
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            message_id="message-1",
            session_id="session-1234",
            schedule_id="schedule-1",
            run_id="run-1",
            kind="monitor_update",
            delivery_mode="ui_notice",
            title="CI monitor",
            text="CI still running.",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await inbox_store.enqueue(message=message)
            await app._poll_session_inbox()
            await pilot.pause()

            assert any(
                "[scheduled notice] CI monitor: CI still running." in line[0] for line in app._adapter.lines
            )
            assert await inbox_store.list_pending(session_id="session-1234") == []
            assert await inbox_store.list_done(session_id="session-1234") == [message]

    @pytest.mark.asyncio
    async def test_inbox_notice_bracket_prefix_renders_literally(self, tmp_path: Path) -> None:
        """The ``[scheduled notice]`` prefix and bracketed body render verbatim.

        The prefix is exactly the shape Textual's markup parser treats as a tag, so
        this proves the notice mounts through ``LiteralTextStatic`` and neither the
        prefix nor a bracketed body (``list[str]``) is swallowed after the 8.x bump.
        """
        history_root: Path = tmp_path / "history"
        inbox_store: SessionInboxStore = SessionInboxStore(history_root=history_root)
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = history_root
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session, inbox_store=inbox_store)
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            message_id="message-1",
            session_id="session-1234",
            schedule_id="schedule-1",
            run_id="run-1",
            kind="monitor_update",
            delivery_mode="ui_notice",
            title="type check",
            text="annotate as list[str]",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await inbox_store.enqueue(message=message)
            await app._poll_session_inbox()
            await pilot.pause()

            assert app._transcript_content is not None
            rendered: list[str] = [
                str(child.render())
                for child in app._transcript_content.children
                if isinstance(child, LiteralTextStatic)
            ]
            assert any("[scheduled notice]" in text and "list[str]" in text for text in rendered)

    @pytest.mark.asyncio
    async def test_poll_session_inbox_starts_chat_turn(self, tmp_path: Path) -> None:
        """`chat_turn` inbox items submit a real queued prompt when the session is idle."""
        history_root: Path = tmp_path / "history"
        inbox_store: SessionInboxStore = SessionInboxStore(history_root=history_root)
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = history_root
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session, inbox_store=inbox_store)
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            message_id="message-1",
            session_id="session-1234",
            schedule_id="schedule-1",
            run_id="run-1",
            kind="scheduled_prompt",
            delivery_mode="chat_turn",
            title="Morning research",
            text="Check the repo and summarize new failures.",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await inbox_store.enqueue(message=message)
            with patch.object(app, "_run_prompt", new=AsyncMock()) as mock_run_prompt:
                await app._poll_session_inbox()
                assert app._in_flight_task is not None
                await app._in_flight_task
                app._in_flight_task = None

            mock_run_prompt.assert_awaited_once_with(text="Check the repo and summarize new failures.")
            assert await inbox_store.list_done(session_id="session-1234") == [message]

    @pytest.mark.asyncio
    async def test_new_session_replaces_active_session_and_clears_transcript(self) -> None:
        """`/new` swaps in a fresh session and clears the visible transcript."""
        old_session: MagicMock = MagicMock(spec=SloAgentSession)
        old_session.workdir = Path(".").resolve()
        old_session.session_id = "old-session-1234"
        old_session.session_name = None
        old_session.active_model_name = "claude-sonnet-4-6"
        old_session.model_pool_dao = None
        old_session.active_reasoning_level = "high"
        old_session.history_root = Path("/tmp/history")
        old_session.history_enabled = True
        old_session.is_running = False
        old_session.subscribe = MagicMock()
        old_session.unsubscribe = MagicMock()
        old_session.hydrate_transcript_entries = AsyncMock(return_value=[])
        old_session.should_show_startup_notice = AsyncMock(return_value=False)
        old_session.usage_snapshot = MagicMock(return_value=MagicMock())
        old_session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())

        new_session: MagicMock = MagicMock(spec=SloAgentSession)
        new_session.workdir = Path(".").resolve()
        new_session.session_id = "new-session-5678"
        new_session.session_name = "fresh thread"
        new_session.active_model_name = "claude-sonnet-4-6"
        new_session.active_reasoning_level = "high"
        new_session.history_root = Path("/tmp/history")
        new_session.history_enabled = True
        new_session.is_running = False
        new_session.subscribe = MagicMock()
        new_session.unsubscribe = MagicMock()
        new_session.hydrate_transcript_entries = AsyncMock(return_value=[])
        new_session.should_show_startup_notice = AsyncMock(return_value=False)
        new_session.usage_snapshot = MagicMock(return_value=MagicMock())
        new_session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
        new_session.rename_session = AsyncMock(
            side_effect=lambda *, session_name: setattr(new_session, "session_name", session_name)
        )

        app: SloTUI = SloTUI(session=old_session)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._write_adapter_line(content="existing line", classes="tool-result")
            await pilot.pause()

            with patch("src.tui.app.SloAgentSession.build", return_value=new_session):
                await app._start_new_session(requested_name="fresh thread")
                await pilot.pause()

            assert app._session is new_session
            old_session.unsubscribe.assert_called_once_with(handler=app._render_event)
            new_session.subscribe.assert_called_once_with(handler=app._render_event)
            assert ("existing line", "tool-result") not in app._adapter.lines
            assert app.sub_title.startswith("session fresh thread · new-sess")

    @pytest.mark.asyncio
    async def test_new_session_rejects_when_prompt_is_in_flight(self) -> None:
        """`/new` is rejected while the current session is still running."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_root = Path("/tmp/history")
        session.history_enabled = True
        session.is_running = True
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._start_new_session(requested_name="fresh thread")
            await pilot.pause()

            assert app._session is session
            assert (
                "cannot start a new session while a prompt is in flight; run /abort first",
                "tool-result",
            ) in app._adapter.lines

    @pytest.mark.asyncio
    async def test_dispatch_slash_command_handles_new_and_rename_intents(self) -> None:
        """Slash dispatch routes naming lifecycle intents through app-owned helpers."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch(
                    "src.tui.app.SlashRouter.dispatch",
                    return_value=MagicMock(
                        should_clear=False,
                        rendered=None,
                        refresh_title=False,
                        open_auth_modal=False,
                        should_exit=False,
                        replace_session=True,
                        requested_session_name="fresh thread",
                        rename_current_session_to=None,
                    ),
                ),
                patch.object(app, "_start_new_session", new=AsyncMock()) as mock_new,
            ):
                await app._dispatch_slash_command(line="/new fresh thread")
                mock_new.assert_awaited_once_with(requested_name="fresh thread")

            with (
                patch(
                    "src.tui.app.SlashRouter.dispatch",
                    return_value=MagicMock(
                        should_clear=False,
                        rendered=None,
                        refresh_title=False,
                        open_auth_modal=False,
                        should_exit=False,
                        replace_session=False,
                        requested_session_name=None,
                        rename_current_session_to="release prep",
                    ),
                ),
                patch.object(app, "_rename_current_session", new=AsyncMock()) as mock_rename,
            ):
                await app._dispatch_slash_command(line="/rename release prep")
                mock_rename.assert_awaited_once_with(session_name="release prep")

    @pytest.mark.asyncio
    async def test_default_theme_is_slo_dark(self) -> None:
        """``SloTUI`` boots with ``slo-dark`` as its active Textual theme."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "slo-dark"

    @pytest.mark.asyncio
    async def test_submitting_a_prompt_renders_final_response(self) -> None:
        """A submitted prompt produces an ``assistant-final`` transcript line."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="hi")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("hello")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            assert ("hi", "assistant-final") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_double_submit_while_in_flight_is_refused(self) -> None:
        """A second submit while busy renders the busy line; only one echo."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="ok")],
        )
        app: SloTUI = SloTUI(session=session)

        # Hold invoke open until we release it.
        release: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _slow_invoke(*, text: str):
            await release.wait()
            async for event in original_invoke(text=text):
                yield event

        with patch.object(session, "invoke", _slow_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()

                # Second submit arrives mid-run.
                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()

                busy_line: str = "(prompt in flight — wait, or steer with `/steer <msg>`)"
                busy_entries: list[tuple[str, str]] = [
                    entry for entry in app._adapter.lines if entry[0] == busy_line
                ]
                echo_entries: list[tuple[str, str]] = [
                    entry for entry in app._adapter.lines if entry == ("> hello", "user-line")
                ]
                assert len(busy_entries) == 1
                assert len(echo_entries) == 1

                release.set()
                await _await_idle(app=app, pilot=pilot)

    @pytest.mark.asyncio
    async def test_up_recalls_latest_submitted_prompt_and_down_restores_blank_draft(self) -> None:
        """Prompt history recalls prior non-slash prompts and restores the blank draft."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first"), AIMessage(content="second")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None

            app._input.load_text("first prompt")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            app._input.load_text("second prompt")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            await pilot.press("up")
            await pilot.pause()
            assert app._input.text == "second prompt"

            await pilot.press("up")
            await pilot.pause()
            assert app._input.text == "first prompt"

            await pilot.press("down")
            await pilot.pause()
            assert app._input.text == "second prompt"

            await pilot.press("down")
            await pilot.pause()
            assert app._input.text == ""

    @pytest.mark.asyncio
    async def test_slash_commands_are_not_recorded_in_prompt_history(self) -> None:
        """Slash commands never enter prompt-history recall."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None

            app._input.load_text("/help")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("up")
            await pilot.pause()
            assert app._input.text == ""

    @pytest.mark.asyncio
    async def test_slash_suggestion_navigation_takes_precedence_over_prompt_history(self) -> None:
        """Visible slash suggestions keep using Up/Down for suggestion movement."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None

            app._input.load_text("previous prompt")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            app._input.load_text("/")
            await pilot.pause()
            starting_index: int = app._slash_suggestion_state.highlighted_index

            await pilot.press("down")
            await pilot.pause()

            assert app._slash_suggestion_state.visible is True
            assert app._slash_suggestion_state.highlighted_index != starting_index
            assert app._input.text == "/"

    @pytest.mark.asyncio
    async def test_second_turn_gets_a_separator_line_for_readability(self) -> None:
        """A later user turn is preceded by a subtle transcript separator."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first"), AIMessage(content="second")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None

            app._input.load_text("one")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            app._input.load_text("two")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            assert ("┈" * 18, "turn-separator") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_ctrl_c_while_idle_quits(self) -> None:
        """``^C`` with no in-flight task triggers ``App.exit``."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="hi")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._in_flight_task is None

            with patch.object(app, "exit", wraps=app.exit) as mock_exit:
                await pilot.press("ctrl+c")
                await pilot.pause()
                mock_exit.assert_called()

    @pytest.mark.asyncio
    async def test_exit_prints_resume_command_for_active_session(self) -> None:
        """Quitting prints a ``slo --resume <id>`` line so the session can be reopened."""
        full_id: str = "a166b82b-617e-45c6-9ada-a36f1c589fb6"
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = full_id
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._resume_command_hint() == f"Resume this session: slo --resume {full_id}"
            with patch.object(App, "exit") as mock_super_exit:
                app.exit()
                _args, kwargs = mock_super_exit.call_args
                assert kwargs["message"] == f"Resume this session: slo --resume {full_id}"

    @pytest.mark.asyncio
    async def test_ctrl_c_while_in_flight_aborts(self) -> None:
        """``^C`` while running calls ``session.abort()`` and ends with ``(aborted)``."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="ok")],
        )
        app: SloTUI = SloTUI(session=session)

        release: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _slow_invoke(*, text: str):
            await release.wait()
            async for event in original_invoke(text=text):
                yield event

        with (
            patch.object(session, "invoke", _slow_invoke),
            patch.object(session, "abort", wraps=session.abort) as mock_abort,
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("ctrl+c")
                await pilot.pause()

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert mock_abort.call_count == 1
                assert app._adapter.lines[-1] == (
                    "(aborted)",
                    "assistant-aborted",
                )

    @pytest.mark.asyncio
    async def test_hard_cancel_aborts_a_hung_run(self) -> None:
        """A run wedged inside a hung tool call is torn down by the hard cancel.

        The cooperative abort flag is only observed between graph stream
        items, so a stream that never yields must be cancelled outright. The
        TUI surfaces this as an ``(aborted)`` line and clears the in-flight
        task rather than hanging forever.
        """
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async def _hung_invoke(*, text: str):
            await asyncio.Event().wait()  # never resolves — simulates a hung tool
            yield  # pragma: no cover — keeps this an async generator

        with patch.object(session, "invoke", _hung_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()
                assert app._in_flight_task is not None

                # Bypass the grace timer and force the escalation directly.
                app._hard_cancel_task(task=app._in_flight_task)
                await _await_idle(app=app, pilot=pilot)

                assert app._in_flight_task is None
                assert ("(aborted)", "assistant-aborted") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_hard_cancel_only_cancels_the_task_it_was_armed_for(self) -> None:
        """A stale abort escalation must never cancel a later, unrelated run."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="ok")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            async def _finished() -> None:
                return None

            aborted_task: asyncio.Task[None] = asyncio.create_task(_finished())
            await aborted_task  # the run it was armed for has already ended

            async def _running() -> None:
                await asyncio.Event().wait()

            fresh_task: asyncio.Task[None] = asyncio.create_task(_running())
            app._in_flight_task = fresh_task

            # The escalation was armed for the *old* task; firing it must not
            # touch the fresh in-flight task.
            app._hard_cancel_task(task=aborted_task)
            await pilot.pause()

            assert not fresh_task.cancelled()
            fresh_task.cancel()

    @pytest.mark.asyncio
    async def test_slash_abort_escalates_to_hard_cancel(self) -> None:
        """``/abort`` arms the hard-cancel escalation, not just the cooperative flag."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())
        session.abort = MagicMock()

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "_escalate_abort") as mock_escalate:
                await app._dispatch_slash_command(line="/abort")
                await pilot.pause()

            session.abort.assert_called_once_with()
            mock_escalate.assert_called_once_with()

    def _steering_session_stub(self) -> MagicMock:
        """Build a session stub with the steering-facing runtime surface."""
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
        session.steer = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_steer_renders_pending_block_then_user_message_on_apply(self) -> None:
        """``/steer`` mounts a SteeringPendingBlock; ``steering_applied`` swaps it for a user message."""
        session: MagicMock = self._steering_session_stub()

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            await app._dispatch_slash_command(line="/steer be terse")
            await pilot.pause()

            session.steer.assert_called_once_with(message="be terse")
            blocks = list(app.query(SteeringPendingBlock))
            assert len(blocks) == 1
            assert "be terse" in str(blocks[0].render())

            await app._render_event(
                AgentStreamEventDAO(kind="steering_applied", content="be terse"),
            )
            await pilot.pause()

            # Pending block is consumed and replaced by a normal user message.
            assert list(app.query(SteeringPendingBlock)) == []
            assert ("> be terse", "user-line") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_compact_while_a_prompt_is_in_flight_renders_the_session_guard(self) -> None:
        """Textual dispatch keeps the prompt alive and delegates the compact guard once."""
        session: MagicMock = self._steering_session_stub()
        session.compact_context = AsyncMock(
            return_value=ManualCompactionResultDAO(
                status="unavailable",
                detail="cannot compact while a prompt is in flight; run /abort first",
            )
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            active_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = active_task
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/compact"))
            await pilot.pause()

            assert (
                "cannot compact while a prompt is in flight; run /abort first",
                "tool-result",
            ) in app._adapter.lines
            session.compact_context.assert_awaited_once()
            assert not active_task.done()
            assert app._in_flight_task is active_task
            active_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_steer_dispatches_and_renders_while_run_in_flight(self) -> None:
        """A ``/steer`` submitted mid-run is dispatched, not swallowed by the busy reply.

        Regression: ``on_prompt_input_submitted`` returned on the in-flight
        branch before the slash-command check, so steering was impossible while
        the agent was working — the one moment steering is meant for.
        """
        session: MagicMock = self._steering_session_stub()

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Simulate a run in flight.
            app._in_flight_task = asyncio.create_task(asyncio.sleep(3600))

            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/steer be terse"))
            await pilot.pause()

            session.steer.assert_called_once_with(message="be terse")
            assert len(list(app.query(SteeringPendingBlock))) == 1

            app._in_flight_task.cancel()

    @pytest.mark.asyncio
    async def test_value_error_from_session_renders_inline_and_keeps_tui_alive(
        self,
    ) -> None:
        """A ``ValueError`` from the lazy build surfaces as a ``tool-result`` line."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async def _raising_invoke(*, text: str):
            raise ValueError("SLO_OPENAI_API_KEY is not set.")
            yield  # pragma: no cover — required to make this an async generator

        with patch.object(session, "invoke", _raising_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await _await_idle(app=app, pilot=pilot)

                error_entries: list[tuple[str, str]] = [
                    entry
                    for entry in app._adapter.lines
                    if entry[0].startswith("(configuration error:") and entry[1] == "tool-result"
                ]
                assert len(error_entries) == 1
                assert "SLO_OPENAI_API_KEY" in error_entries[0][0]
                # The TUI did not exit; the in-flight task was cleared.
                assert app._in_flight_task is None

    @pytest.mark.asyncio
    async def test_unexpected_exception_renders_error_line_and_keeps_tui_alive(
        self,
    ) -> None:
        """Any non-``ValueError`` raised mid-run (e.g. provider 429) surfaces in the transcript.

        Before this fix, exceptions like ``openai.RateLimitError`` were
        swallowed by Python's "Task exception was never retrieved"
        path, leaving the user with a blank stop and no signal at all.
        """
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        class _FakeRateLimitError(RuntimeError):
            """Stand-in for ``openai.RateLimitError`` without the import dep."""

        async def _raising_invoke(*, text: str):
            raise _FakeRateLimitError("Error code: 429 - You exceeded your current quota.")
            yield  # pragma: no cover — keeps this an async generator

        with patch.object(session, "invoke", _raising_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await _await_idle(app=app, pilot=pilot)

                error_entries: list[tuple[str, str]] = [
                    entry
                    for entry in app._adapter.lines
                    if entry[0].startswith("(error:") and entry[1] == "assistant-aborted"
                ]
                assert len(error_entries) == 1
                rendered: str = error_entries[0][0]
                assert "_FakeRateLimitError" in rendered
                assert "429" in rendered
                # The TUI did not exit; the in-flight task was cleared.
                assert app._in_flight_task is None

    @pytest.mark.asyncio
    async def test_openai_rate_limit_error_renders_without_type_prefix(
        self,
    ) -> None:
        """``openai.RateLimitError`` lines drop the ``<ExcType>:`` prefix.

        Feature 07 §4.4: the OpenAI message body is already plan-aware
        and user-readable; the type prefix only adds visual noise on
        the only failure mode users hit regularly.
        """
        import httpx
        from openai import RateLimitError

        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        message: str = "You have hit your ChatGPT usage limit (business plan). " "Try again in ~37 min."

        async def _raising_invoke(*, text: str):
            """Raise an ``openai.RateLimitError`` mid-stream."""
            raise RateLimitError(
                message=message,
                response=httpx.Response(
                    status_code=429,
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            )
            yield  # pragma: no cover — keeps this an async generator

        with patch.object(session, "invoke", _raising_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await _await_idle(app=app, pilot=pilot)

                error_entries: list[tuple[str, str]] = [
                    entry
                    for entry in app._adapter.lines
                    if entry[0].startswith("(error:") and entry[1] == "assistant-aborted"
                ]
                assert len(error_entries) == 1
                rendered: str = error_entries[0][0]
                # The friendly OpenAI message is rendered verbatim;
                # the ``RateLimitError:`` prefix MUST NOT appear.
                assert "RateLimitError" not in rendered
                assert "business plan" in rendered
                assert app._in_flight_task is None

    @pytest.mark.asyncio
    async def test_slash_command_does_not_create_in_flight_task(self) -> None:
        """``/help`` renders inline; no prompt task is spawned."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None

            app._input.load_text("/help")
            await pilot.press("enter")
            await pilot.pause()

            assert app._in_flight_task is None
            help_content: list[str] = [entry[0] for entry in app._adapter.lines if "help" in entry[0].lower()]
            assert len(help_content) >= 1


class TestPromptInputAutoResize:
    """Auto-resizing prompt-input behavior inside ``SloTUI``."""

    LONG_WRAPPED_PROMPT: str = "wrap this prompt so the editor grows " * 20
    TALL_PROMPT: str = "\n".join(f"line {index}" for index in range(30))

    @pytest.mark.asyncio
    async def test_prompt_input_grows_for_wrapped_content(self) -> None:
        """Wrapped content increases the visible prompt height."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            baseline_lines: int = _visible_prompt_lines(app=app)

            prompt_input.load_text(self.LONG_WRAPPED_PROMPT)
            await pilot.pause()

            grown_lines: int = _visible_prompt_lines(app=app)
            assert grown_lines > baseline_lines

    @pytest.mark.asyncio
    async def test_prompt_input_returns_to_baseline_height_after_clearing(self) -> None:
        """Clearing the buffer collapses the prompt editor back to baseline."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            baseline_lines: int = _visible_prompt_lines(app=app)

            prompt_input.load_text(self.LONG_WRAPPED_PROMPT)
            await pilot.pause()
            assert _visible_prompt_lines(app=app) > baseline_lines

            prompt_input.load_text("")
            await pilot.pause()

            assert _visible_prompt_lines(app=app) == baseline_lines

    @pytest.mark.asyncio
    async def test_prompt_input_caps_visible_height_at_fifteen_lines(self) -> None:
        """Very tall content stops growing after fifteen visible lines."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text(self.TALL_PROMPT)
            await pilot.pause()

            assert _visible_prompt_lines(app=app) == 15

    @pytest.mark.asyncio
    async def test_prompt_input_scrolls_internally_after_visible_height_cap(self) -> None:
        """Over-cap content keeps vertical scroll headroom inside the editor."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text(self.TALL_PROMPT)
            await pilot.pause()

            assert prompt_input.max_scroll_y > 0

            prompt_input.move_cursor(location=(29, 0))
            await pilot.pause()

            assert prompt_input.scroll_y > 0

    @pytest.mark.asyncio
    async def test_prompt_input_recomputes_height_when_terminal_width_changes(
        self,
    ) -> None:
        """Terminal width changes rewrap the prompt and adjust visible height."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text(self.LONG_WRAPPED_PROMPT)
            await pilot.pause()
            starting_lines: int = _visible_prompt_lines(app=app)

            await pilot.resize_terminal(width=40, height=24)
            await pilot.pause()
            narrow_lines: int = _visible_prompt_lines(app=app)

            await pilot.resize_terminal(width=100, height=24)
            await pilot.pause()
            wide_lines: int = _visible_prompt_lines(app=app)

            assert narrow_lines > starting_lines
            assert wide_lines < narrow_lines

    @pytest.mark.asyncio
    async def test_submitting_long_prompt_restores_baseline_height(self) -> None:
        """Submitting a long prompt clears the buffer and collapses the editor."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="ok")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            baseline_lines: int = _visible_prompt_lines(app=app)

            prompt_input.load_text(self.LONG_WRAPPED_PROMPT)
            await pilot.pause()
            assert _visible_prompt_lines(app=app) > baseline_lines

            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            assert prompt_input.text == ""
            assert _visible_prompt_lines(app=app) == baseline_lines
            assert ("ok", "assistant-final") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_meta_enter_inserts_newline_without_submitting(self) -> None:
        """``Cmd+Enter`` inserts a literal newline in the prompt editor."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text("first")
            prompt_input.move_cursor(location=(0, len("first")))
            await pilot.press("meta+enter")
            await pilot.pause()

            assert prompt_input.text == "first\n"
            assert app._in_flight_task is None
            assert ("> first", "user-line") not in app._adapter.lines


class TestSloTUICopy:
    """Clipboard-oriented TUI behavior."""

    @pytest.mark.asyncio
    async def test_copy_binding_copies_visible_transcript_when_prompt_has_no_selection(self) -> None:
        """``Cmd+C`` / ``Ctrl+Shift+C`` copies the transcript as plain text."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="hi")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("hello")
            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            with patch.object(app, "copy_to_clipboard") as mock_copy:
                await pilot.press("meta+c")
                await pilot.pause()

            mock_copy.assert_called_once_with(
                "slo, Copyright (C) 2026 Siddharth Ravichandran. "
                "This program comes with ABSOLUTELY NO WARRANTY; see LICENSE. "
                "This is free software, and you are welcome to redistribute it under GPLv2.\n"
                "Tip: use /help to see available commands. "
                f"Session: {session.session_id}. Initialized model: gpt-5.4. "
                "Reasoning: high. Provider detail: effort high.\n> hello\nhi",
            )

    @pytest.mark.asyncio
    async def test_copy_binding_prefers_selected_prompt_text(self) -> None:
        """Selected prompt text wins over transcript copy."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            prompt_input.load_text("copy me")
            prompt_input.select_all()
            await pilot.pause()

            with patch.object(app, "copy_to_clipboard") as mock_copy:
                await pilot.press("meta+c")
                await pilot.pause()

            mock_copy.assert_called_once_with("copy me")


class TestSloTUISpinner:
    """``ThinkingSpinner`` lifecycle inside ``_run_prompt``."""

    @pytest.mark.asyncio
    async def test_visible_thinking_delta_keeps_spinner_and_mounts_assistant_stream_block(self) -> None:
        """Visible thinking deltas keep the fixed spinner and mount a transcript block."""
        session = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(
                    responses=[FauxChatModel.assistant_message(content="completed answer")],
                    chunk_scripts=[
                        [
                            AIMessageChunk(
                                content=[
                                    {"type": "thinking", "thinking": "plan"},
                                    {"type": "text", "text": "partial answer"},
                                ]
                            )
                        ]
                    ],
                ),
                tools=[],
            ),
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        release: asyncio.Event = asyncio.Event()
        saw_thinking_delta: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _paused_after_thinking_delta_invoke(*, text: str):
            async for event in original_invoke(text=text):
                yield event
                if event.kind == "thinking_delta":
                    saw_thinking_delta.set()
                    await release.wait()

        with patch.object(session, "invoke", _paused_after_thinking_delta_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")

                await asyncio.wait_for(saw_thinking_delta.wait(), timeout=5)
                await pilot.pause()

                assert app._spinner is not None
                assert list(app.query(selector=ThinkingSpinner))
                blocks: list[AssistantStreamBlock] = list(app.query(selector=AssistantStreamBlock))
                assert len(blocks) == 1
                assert blocks[0].thinking_text == "plan"

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert any(line[1] == "assistant-final" for line in app._adapter.lines)

    @pytest.mark.asyncio
    async def test_thinking_spinner_mounts_during_prompt_and_unmounts_after(
        self,
    ) -> None:
        """A spinner is in the DOM while in flight and gone after the run finishes."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="hi")],
        )
        app: SloTUI = SloTUI(session=session)

        release: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _slow_invoke(*, text: str):
            await release.wait()
            async for event in original_invoke(text=text):
                yield event

        with patch.object(session, "invoke", _slow_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()

                spinners_in_flight: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
                assert len(spinners_in_flight) == 1

                release.set()
                await _await_idle(app=app, pilot=pilot)

                spinners_after: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
                assert spinners_after == []
                assert app._spinner is None

    @pytest.mark.asyncio
    async def test_tool_block_keeps_spinner_during_intermediate_tool_updates(self) -> None:
        """Visible tool execution blocks do not replace the fixed status spinner."""

        @tool
        def stub_echo(text: str) -> str:
            """Echo the provided text."""
            return text

        agent: SloAgent = SloAgent(
            llm=FauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(
                        tool_calls=[FauxChatModel.tool_call_dict(name="stub_echo", args={"text": "x"})],
                    ),
                    FauxChatModel.assistant_message(content="done"),
                ]
            ),
            tools=[stub_echo],
        )
        session = SloAgentSession(
            agent=agent,
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        release: asyncio.Event = asyncio.Event()
        saw_tool_result: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _paused_after_tool_result_invoke(*, text: str):
            async for event in original_invoke(text=text):
                yield event
                if event.kind == "tool_result":
                    saw_tool_result.set()
                    await release.wait()

        with patch.object(session, "invoke", _paused_after_tool_result_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")

                await asyncio.wait_for(saw_tool_result.wait(), timeout=5)
                await pilot.pause()

                assert any(line[1] == "tool-line" for line in app._adapter.lines)
                assert any(line[1] == "tool-result" for line in app._adapter.lines)
                assert list(app.query(selector=ToolExecutionBlock))
                assert app._spinner is not None
                assert list(app.query(selector=ThinkingSpinner))

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert list(app.query(selector=ThinkingSpinner)) == []
                assert ("done", "assistant-final") in app._adapter.lines

    @pytest.mark.asyncio
    async def test_second_assistant_iteration_mounts_a_new_transcript_block(self) -> None:
        """Later assistant iterations render below tool output instead of rewriting the first block."""

        @tool
        def stub_echo(text: str) -> str:
            """Echo the provided text."""
            return text

        agent: SloAgent = SloAgent(
            llm=FauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(
                        tool_calls=[FauxChatModel.tool_call_dict(name="stub_echo", args={"text": "x"})],
                    ),
                    FauxChatModel.assistant_message(content="done"),
                ],
                chunk_scripts=[
                    [
                        AIMessageChunk(
                            content=[{"type": "thinking", "thinking": "first pass"}],
                            tool_calls=[{"id": "call_1", "name": "stub_echo", "args": {"text": "x"}}],
                        )
                    ],
                    [
                        AIMessageChunk(
                            content=[
                                {"type": "thinking", "thinking": "second pass"},
                                {"type": "text", "text": "partial"},
                            ]
                        )
                    ],
                ],
            ),
            tools=[stub_echo],
        )
        session = SloAgentSession(
            agent=agent,
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        release: asyncio.Event = asyncio.Event()
        saw_second_iteration: asyncio.Event = asyncio.Event()
        original_invoke = session.invoke

        async def _paused_on_second_iteration_invoke(*, text: str):
            async for event in original_invoke(text=text):
                yield event
                if event.kind == "thinking_delta" and event.iteration == 1:
                    saw_second_iteration.set()
                    await release.wait()

        with patch.object(session, "invoke", _paused_on_second_iteration_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")

                await asyncio.wait_for(saw_second_iteration.wait(), timeout=5)
                await pilot.pause()

                blocks: list[AssistantStreamBlock] = list(app.query(selector=AssistantStreamBlock))
                assert len(blocks) == 2
                assert blocks[0].thinking_text == "first pass"
                assert blocks[1].thinking_text == "second pass"
                assert app._spinner is not None

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert any(line[1] == "assistant-final" for line in app._adapter.lines)


class TestSloTUILogIsolation:
    """Interactive logging should not leak to terminal streams."""

    @pytest.mark.asyncio
    async def test_logging_while_app_is_mounted_does_not_touch_terminal_streams(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mounted-app log records stay off stdout/stderr in interactive mode."""
        capsys.readouterr()
        with interactive_logging(slo_home=tmp_path) as log_path:
            session: SloAgentSession = _build_session(
                responses=[AIMessage(content="unused")],
            )
            app: SloTUI = SloTUI(session=session)

            async with app.run_test() as pilot:
                await pilot.pause()
                log_info(msg="mounted app log isolation")
                await pilot.pause()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert log_path is not None
        assert "mounted app log isolation" in log_path.read_text()


class TestSloTUIAuthMount:
    """``on_mount`` auto-opens the modal when no credential resolves (02.b.6)."""

    @pytest.mark.asyncio
    async def test_mount_pushes_modal_when_no_credential(self, monkeypatch) -> None:
        """Resolver returns ``None`` → ``AuthenticationScreen`` is in the stack."""
        monkeypatch.setattr(
            "src.tui.app.CredentialResolver.resolve",
            lambda *, provider: None,
        )
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert any(screen.__class__.__name__ == "AuthenticationScreen" for screen in app.screen_stack)

    @pytest.mark.asyncio
    async def test_mount_does_not_push_modal_when_credential_present(
        self,
    ) -> None:
        """Default (autouse) fixture returns a fake credential → no modal."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert all(screen.__class__.__name__ != "AuthenticationScreen" for screen in app.screen_stack)

    @pytest.mark.asyncio
    async def test_mount_pushes_modal_when_active_provider_has_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolver returns ``None`` for the active model's provider → modal is pushed."""
        monkeypatch.setattr(
            "src.tui.app.CredentialResolver.resolve",
            lambda *, provider: None,
        )
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            modal_pushed: bool = any(
                screen.__class__.__name__ == "AuthenticationScreen" for screen in app.screen_stack
            )
            assert modal_pushed is True

    @pytest.mark.asyncio
    async def test_mount_does_not_push_modal_when_model_name_unsupported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``provider_for_model`` raises ValueError → modal NOT pushed.

        Pins the ValueError-swallow branch in
        ``SloTUI._has_credential_for_active_model`` which treats
        unsupported model names as "has credential" and skips the modal.
        """
        monkeypatch.setattr(
            "src.tui.app.cfg",
            lambda key: "mistral-large" if key == "DEFAULT_MODEL_NAME" else "",
        )
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert all(screen.__class__.__name__ != "AuthenticationScreen" for screen in app.screen_stack)

    @pytest.mark.asyncio
    async def test_slash_auth_pushes_modal(self) -> None:
        """``/auth`` pushes the modal mid-session even when configured."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("/auth")
            await pilot.press("enter")
            await pilot.pause()

            assert any(screen.__class__.__name__ == "AuthenticationScreen" for screen in app.screen_stack)


class TestSloTUIThemeToggle:
    """Tests for the ``/theme`` slash-command integration."""

    @pytest.mark.asyncio
    async def test_slash_theme_toggles_from_slo_dark_to_slo_default(self) -> None:
        """``/theme`` while on the boot slo-dark theme switches to slo-default."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "slo-dark"
            assert app._input is not None
            app._input.load_text("/theme")
            await pilot.press("enter")
            await pilot.pause()

            assert app.theme == "slo-default"

    @pytest.mark.asyncio
    async def test_slash_theme_toggles_back_to_slo_dark(self) -> None:
        """Two ``/theme`` invocations return to the slo-dark starting theme."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("/theme")
            await pilot.press("enter")
            await pilot.pause()
            assert app.theme == "slo-default"

            app._input.load_text("/theme")
            await pilot.press("enter")
            await pilot.pause()
            assert app.theme == "slo-dark"


class TestSloTUIPoolAttachment:
    """``SloTUI._attach_pool_to_session`` wiring (sub-spec 03.b)."""

    def test_attach_pool_to_session_sets_spawn_tool_on_session(self, tmp_path: Path) -> None:
        """``_attach_pool_to_session`` injects the spawn tool into the session config."""
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        SloTUI._attach_pool_to_session(session=session)

        assert session._config.extra_tools is not None
        tool_names: list[str] = [t.name for t in session._config.extra_tools]
        assert "spawn_sub_agents" in tool_names

    def test_attach_pool_to_session_sets_append_system_prompt(self, tmp_path: Path) -> None:
        """``_attach_pool_to_session`` injects the orchestrator addendum."""
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        SloTUI._attach_pool_to_session(session=session)

        assert session._config.append_system_prompt is not None
        assert "spawn_sub_agents" in session._config.append_system_prompt

    def test_headless_session_does_not_have_spawn_tool(self, tmp_path: Path) -> None:
        """``HeadlessRunner``-built sessions have no ``spawn_sub_agents`` tool."""
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        # Simulate how HeadlessRunner builds its session — no _attach_pool_to_session
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        tool_names: list[str] = [t.name for t in (session._config.extra_tools or [])]
        assert "spawn_sub_agents" not in tool_names

    def test_pre_built_agent_session_is_skipped_gracefully(self, tmp_path: Path) -> None:
        """``_attach_pool_to_session`` is a no-op for pre-built agent sessions."""
        from src.agents.slo_agent.agent import SloAgent
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.providers.faux import FauxChatModel

        agent: SloAgent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
            cwd=str(tmp_path),
            tools=[],
        )
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=agent,
            enable_history=False,
        )

        # Must not raise — pre-built agent sessions are silently skipped.
        SloTUI._attach_pool_to_session(session=session)

        assert session._sub_agent_pool is None


class TestSloTUITypingRedirect:
    """Typing while the prompt is unfocused redirects focus and replays the char."""

    @pytest.mark.asyncio
    async def test_printable_key_redirects_focus_and_replays_char(self) -> None:
        """A printable key while the transcript is focused jumps to the prompt."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_scroll is not None
            app.set_focus(app._transcript_scroll)
            await pilot.pause()
            assert app.focused is app._transcript_scroll

            await pilot.press("h")
            await pilot.pause()

            assert app.focused is app._input
            assert _require_prompt_input(app=app).text == "h"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key",
        ["up", "down", "pageup", "pagedown", "home", "end", "ctrl+o", "escape"],
    )
    async def test_navigation_key_does_not_redirect(self, key: str) -> None:
        """Navigation and chord keys are not printable and never type into the prompt."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_scroll is not None
            app.set_focus(app._transcript_scroll)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

            assert _require_prompt_input(app=app).text == ""
            assert app.focused is app._transcript_scroll

    @pytest.mark.asyncio
    async def test_no_redirect_before_prompt_is_mounted(self) -> None:
        """Guard 1: with no prompt input mounted, a printable key is never redirected."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            app._input = None  # simulate the pre-mount window
            should_redirect: bool = app._should_redirect_typing_to_prompt(
                event=events.Key(key="a", character="a"),
            )
            assert should_redirect is False

    @pytest.mark.asyncio
    async def test_no_redirect_when_prompt_already_focused(self) -> None:
        """When the prompt owns focus, typing is handled by TextArea, not redirected."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.focused is app._input  # focused on mount

            await pilot.press("a")
            await pilot.pause()

            assert _require_prompt_input(app=app).text == "a"  # exactly one 'a'

    @pytest.mark.asyncio
    async def test_no_redirect_while_modal_screen_is_active(self) -> None:
        """A printable key never lands in the background prompt while a modal is up."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(AuthenticationScreen())
            await pilot.pause()
            assert app._input is not None
            assert app.screen is not app._input.screen  # modal is on top

            await pilot.press("h")
            await pilot.pause()

            assert _require_prompt_input(app=app).text == ""  # background untouched

    @pytest.mark.asyncio
    async def test_replayed_slash_opens_suggestion_menu(self) -> None:
        """A replayed '/' drives the normal slash-suggestion refresh path."""
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_scroll is not None
            app.set_focus(app._transcript_scroll)
            await pilot.pause()

            await pilot.press("slash")  # Textual key name for "/"
            await pilot.pause()

            assert _require_prompt_input(app=app).text == "/"
            assert app._slash_suggestion_state.visible is True


class TestSloTUIGlobalExpandToggle:
    """Ctrl+O global expand/collapse-all across all transcript blocks (sub-spec 42.a.12)."""

    async def _mounted_blocks(self, *, app: SloTUI):
        """Mount one user, one assistant (with reasoning), one tool block."""
        user = await app.mount_user_message_block(text="line one\nhidden second line")
        assistant = await app.mount_assistant_block()
        assistant.set_thinking(content="reasoning text")
        tool = await app.mount_tool_execution_block(tool_call_id="tc", tool_name="bash")
        tool.update_tool_call(tool_input={"command": "ls"})
        tool.update_result(tool_name="bash", output="out")
        return user, assistant, tool

    @pytest.mark.asyncio
    async def test_ctrl_o_cycles_natural_expand_collapse(self) -> None:
        """First Ctrl+O expands all; second collapses all; third expands again."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            user, assistant, tool = await self._mounted_blocks(app=app)
            await pilot.pause()

            # Natural default: user full, reasoning visible, tool collapsed.
            assert app._global_expand_all is None
            assert (user._expanded, assistant._thinking_body.display, tool._expanded) == (True, True, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is True
            assert (user._expanded, assistant._thinking_body.display, tool._expanded) == (True, True, True)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is False
            assert (user._expanded, assistant._thinking_body.display, tool._expanded) == (True, False, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is True
            assert (user._expanded, assistant._thinking_body.display, tool._expanded) == (True, True, True)

    @pytest.mark.asyncio
    async def test_new_block_keeps_user_expanded_but_collapses_assistant_state(self) -> None:
        """Collapse-all does not affect user blocks but still applies to assistant blocks."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await self._mounted_blocks(app=app)
            await app.action_toggle_expandable_details()  # expand all
            await app.action_toggle_expandable_details()  # collapse all
            await pilot.pause()

            new_user = await app.mount_user_message_block(text="fresh\nmultiline")
            new_assistant = await app.mount_assistant_block()
            new_assistant.set_thinking(content="fresh reasoning")
            await pilot.pause()

            assert new_user._expanded is True
            assert new_assistant._thinking_body.display is False

    @pytest.mark.asyncio
    async def test_new_block_respects_expand_all_state(self) -> None:
        """A tool block mounted after expand-all inherits the expanded state."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await self._mounted_blocks(app=app)
            await app.action_toggle_expandable_details()  # expand all
            await pilot.pause()

            new_tool = await app.mount_tool_execution_block(tool_call_id="tc2", tool_name="bash")
            assert new_tool._expanded is True


class TestScrollToBottom:
    """``action_scroll_to_bottom`` and ``meta+down`` gesture (spec 56)."""

    @pytest.mark.asyncio
    async def test_action_delegates_to_scroll_transcript_to_end(self) -> None:
        """``action_scroll_to_bottom`` delegates to ``_scroll_transcript_to_end``."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            called: list[bool] = []
            app._scroll_transcript_to_end = lambda: called.append(True)  # type: ignore[method-assign]

            await app.action_scroll_to_bottom()

            assert called == [True]

    @pytest.mark.asyncio
    async def test_action_is_noop_when_transcript_scroll_absent(self) -> None:
        """``action_scroll_to_bottom`` does not raise when the scroll container is absent."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._transcript_scroll = None

            await app.action_scroll_to_bottom()  # must not raise


class TestFocusedBlockText:
    """``_focused_block_text`` helper (spec 56)."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_focused(self) -> None:
        """``_focused_block_text`` returns empty string when ``self.focused`` is None."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_focus(None)
            await pilot.pause()

            assert app._focused_block_text() == ""

    @pytest.mark.asyncio
    async def test_returns_empty_for_widget_without_protocol(self) -> None:
        """``_focused_block_text`` returns empty string for ``PromptInput`` (no ``get_copyable_text``)."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app.set_focus(app._input)
            await pilot.pause()

            assert app._focused_block_text() == ""

    @pytest.mark.asyncio
    async def test_returns_block_text_when_transcript_block_focused(self) -> None:
        """``_focused_block_text`` returns ``get_copyable_text()`` when a block holds focus."""
        from src.tui.widgets.user_message_block import UserMessageBlock

        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            block: UserMessageBlock = await app.mount_user_message_block(text="hello world")
            app.set_focus(block)
            await pilot.pause()

            assert app._focused_block_text() == "hello world"


class TestCopyVisibleTextResolutionChain:
    """``action_copy_visible_text`` three-tier resolution (spec 56)."""

    @pytest.mark.asyncio
    async def test_copies_focused_block_text_first(self) -> None:
        """Focused transcript block text wins over prompt selection and full transcript."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)
        clipboard: list[str] = []
        app.copy_to_clipboard = lambda text: clipboard.append(text)  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()
            block._answer_text = "assistant answer"
            app.set_focus(block)
            await pilot.pause()

            await app.action_copy_visible_text()

            assert clipboard and clipboard[-1] == "assistant answer"

    @pytest.mark.asyncio
    async def test_falls_back_to_transcript_when_no_block_focused(self) -> None:
        """Full transcript plain text is used when no transcript block holds focus."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)
        clipboard: list[str] = []
        app.copy_to_clipboard = lambda text: clipboard.append(text)  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app.set_focus(app._input)
            app._write_adapter_line(content="some transcript line", classes="tool-result")
            await pilot.pause()

            await app.action_copy_visible_text()

            assert clipboard and "some transcript line" in clipboard[-1]

    @pytest.mark.asyncio
    async def test_is_noop_when_all_tiers_empty(self) -> None:
        """``action_copy_visible_text`` does not call ``copy_to_clipboard`` when everything is empty."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)
        clipboard: list[str] = []
        app.copy_to_clipboard = lambda text: clipboard.append(text)  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_focus(None)
            # Clear adapter lines so the transcript fallback has nothing to offer.
            if app._adapter is not None:
                app._adapter.lines.clear()
            await pilot.pause()

            await app.action_copy_visible_text()

            assert clipboard == []


class TestTranscriptWindow:
    """Transcript window keeps mounted children bounded (spec 59, Phase 2)."""

    def _build_app(self) -> SloTUI:
        """Build a ``SloTUI`` for transcript-window tests.

        Returns:
            SloTUI: App ready for ``run_test``.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        return SloTUI(session=session)

    @pytest.mark.asyncio
    async def test_transcript_window_caps_mounted_children(self) -> None:
        """Mounting more than TRANSCRIPT_WINDOW_SIZE settled blocks caps the count."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Clear any startup adapter lines so the count is deterministic.
            await app.action_clear()
            # Mount TRANSCRIPT_WINDOW_SIZE + 5 settled user-message blocks.
            extra: int = 5
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                await app.mount_user_message_block(text="msg")
            await pilot.pause()
            # Pause extra ticks for any pending worker to complete.
            for _ in range(5):
                await pilot.pause()
            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app._hidden_block_count == extra
            assert app._earlier_summary is not None

    @pytest.mark.asyncio
    async def test_earlier_summary_absent_below_window(self) -> None:
        """Fewer than window children produce no summary widget."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Mount fewer blocks than the window.
            for _ in range(5):
                await app.mount_user_message_block(text="msg")
            await pilot.pause()
            assert app._earlier_summary is None
            assert app._hidden_block_count == 0

    @pytest.mark.asyncio
    async def test_window_never_evicts_live_block(self) -> None:
        """An un-finalized AssistantStreamBlock placed first is never evicted."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Mount one live assistant block as the oldest child.
            live_block: AssistantStreamBlock = await app.mount_assistant_block()
            # live_block is not finalized — it is live.
            assert live_block.finalized is False
            # Mount TRANSCRIPT_WINDOW_SIZE settled blocks to trigger eviction.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The live block must still be in the transcript (Textual's
            # Widget.is_mounted stays True after remove(); check children instead).
            assert live_block in app._transcript_content.children

    @pytest.mark.asyncio
    async def test_window_never_evicts_pending_steer_block(self) -> None:
        """A SteeringPendingBlock tracked in _pending_steer_blocks is never evicted."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Mount a pending steer block as the oldest child.
            steer_block: SteeringPendingBlock = SteeringPendingBlock(message="steer msg")
            await app._transcript_content.mount(steer_block)
            app._pending_steer_blocks.append(steer_block)
            # Mount TRANSCRIPT_WINDOW_SIZE settled blocks.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The steer block must still be in the transcript (Textual's
            # Widget.is_mounted stays True after remove(); check children instead).
            assert steer_block in app._transcript_content.children

    @pytest.mark.asyncio
    async def test_adapter_line_mount_enforces_window(self) -> None:
        """Adapter lines via _write_adapter_line also enforce the window."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Clear any startup adapter lines so the count is deterministic.
            await app.action_clear()
            extra: int = 5
            for index in range(TRANSCRIPT_WINDOW_SIZE + extra):
                app._write_adapter_line(content=f"line {index}", classes="tool-result")
            # Pause multiple ticks for workers to complete.
            for _ in range(10):
                await pilot.pause()
            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app._hidden_block_count == extra

    @pytest.mark.asyncio
    async def test_clear_resets_window_state(self) -> None:
        """action_clear resets _hidden_block_count and _earlier_summary."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Mount over-window blocks so summary is created.
            for _ in range(TRANSCRIPT_WINDOW_SIZE + 3):
                await app.mount_user_message_block(text="msg")
            for _ in range(5):
                await pilot.pause()
            assert app._earlier_summary is not None
            assert app._hidden_block_count > 0
            await app.action_clear()
            await pilot.pause()
            assert app._hidden_block_count == 0
            assert app._earlier_summary is None

    @pytest.mark.asyncio
    async def test_window_evicts_incomplete_tool_block(self) -> None:
        """A tool block marked incomplete is evictable (terminal, not live)."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Clear any startup adapter lines so eviction order is deterministic.
            await app.action_clear()
            # Mount a tool block and mark it incomplete (terminal state).
            incomplete_block: ToolExecutionBlock = await app.mount_tool_execution_block(
                tool_call_id="tc1", tool_name="bash"
            )
            incomplete_block.mark_incomplete()
            assert incomplete_block.is_incomplete is True
            # Mount TRANSCRIPT_WINDOW_SIZE more settled blocks to trigger eviction.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The incomplete block should have been evicted.
            # Textual's Widget.is_mounted is a one-way flag that stays True after
            # remove() — the authoritative post-eviction check is whether the
            # widget is still present in the parent's children list.
            assert incomplete_block not in app._transcript_content.children, (
                f"incomplete_block still in transcript children after eviction; "
                f"total={len(list(app._transcript_content.children))}, "
                f"hidden={app._hidden_block_count}, "
                f"is_incomplete={incomplete_block.is_incomplete}"
            )

    @pytest.mark.asyncio
    async def test_concurrent_window_enforcement_is_single_flight(self) -> None:
        """Overlapping enforcer invocations never double-remove a child.

        The transcript is driven genuinely over-window by mounting directly onto
        the container, so mount-site enforcement never fires and both enforcer
        coroutines observe ``children_count > TRANSCRIPT_WINDOW_SIZE`` — past the
        fast-path early return. ``asyncio.gather`` schedules both concurrently:
        the first invocation claims the single-flight guard
        (``_window_enforcement_running = True``) and yields at its first
        ``await child.remove()``; the second then finds the guard held, sets
        ``_window_enforcement_rerun = True`` and returns without claiming the
        guard. The first invocation's ``while`` loop then consumes the rerun
        request with one extra pass that removes nothing because overflow is
        already 0. Only the first pass removes children, so no child is
        double-removed even though the enforcer was invoked twice.

        A patched ``_run_window_enforcement_pass`` wrapper forces every pass to
        yield at entry (``await asyncio.sleep(0)``) so the first invocation
        suspends before the second call runs, making the interleave
        deterministic. Counting the wrapped calls proves both the initial pass
        and the rerun pass executed under a single guard holder (two passes,
        one holder) rather than two concurrent removal loops, and confirms the
        rerun flag was raised then consumed.

        Assertions: non-summary children count == TRANSCRIPT_WINDOW_SIZE
        (exactly-once removal; a genuine second removal loop would drive it
        below the window), ``app._hidden_block_count == extra`` (correct count,
        not doubled), the pass ran twice under one guard holder, and the rerun
        request was raised then cleared.
        """
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Clear startup adapter lines so child count is deterministic.
            await app.action_clear()
            extra: int = 5
            # Mount directly onto the container so mount-site enforcement never
            # runs and the transcript is genuinely over-window when the enforcers
            # start — both calls must pass the fast-path into the guard.
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                await app._transcript_content.mount(UserMessageBlock(text="settled"))
            await pilot.pause()
            assert len(list(app._transcript_content.children)) == TRANSCRIPT_WINDOW_SIZE + extra
            # Wrap the removal pass so the first invocation yields at entry,
            # guaranteeing the second call observes the guard held and takes the
            # rerun branch. Count passes to prove both ran under one guard holder.
            pass_count: int = 0
            original_pass = app._run_window_enforcement_pass

            async def _counting_pass() -> None:
                nonlocal pass_count
                pass_count += 1
                await asyncio.sleep(0)
                await original_pass()

            with patch.object(app, "_run_window_enforcement_pass", _counting_pass):
                # Both calls see count > window and race into the single-flight
                # guard: the first claims it and yields; the second sets the
                # rerun flag and returns.
                await asyncio.gather(
                    app._enforce_transcript_window(),
                    app._enforce_transcript_window(),
                )
            await pilot.pause()
            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            # Exactly-once removal: a second removal loop would drop the count
            # below the window or double the hidden count.
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app._hidden_block_count == extra
            # The pass ran twice under a single guard holder: the initial removal
            # pass plus the rerun pass consumed by the while loop (the rerun pass
            # removes nothing because overflow is already 0). Two concurrent
            # removal loops would instead have double-removed above.
            assert pass_count == 2
            # The rerun request was raised by the guarded second call, then
            # consumed by the first invocation's while loop.
            assert app._window_enforcement_rerun is False
            assert app._window_enforcement_running is False


class TestProtectedTail:
    """Structural starvation guard: the newest tail is never an eviction candidate (spec 61, D3/D4)."""

    def _build_app(self) -> SloTUI:
        """Build a ``SloTUI`` for protected-tail tests.

        Returns:
            SloTUI: App ready for ``run_test``.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        return SloTUI(session=session)

    # -- Unit tests for _eviction_candidates --

    def test_eviction_candidates_excludes_the_newest_tail_when_children_exceed_the_tail_size(
        self,
    ) -> None:
        """The candidate prefix excludes exactly the newest tail-sized suffix."""
        app: SloTUI = self._build_app()
        widgets: list[Widget] = [UserMessageBlock(text=f"msg{i}") for i in range(5)]

        with patch("src.tui.app.TRANSCRIPT_PROTECTED_TAIL_SIZE", 3):
            candidates: list[Widget] = app._eviction_candidates(children=widgets)

        assert candidates == [widgets[0], widgets[1]]

    def test_eviction_candidates_returns_empty_when_children_equal_the_tail_size(self) -> None:
        """The boundary case of the guard clause: children exactly equal to the tail size."""
        app: SloTUI = self._build_app()
        widgets: list[Widget] = [UserMessageBlock(text=f"msg{i}") for i in range(5)]

        with patch("src.tui.app.TRANSCRIPT_PROTECTED_TAIL_SIZE", 5):
            candidates: list[Widget] = app._eviction_candidates(children=widgets)

        assert candidates == []

    def test_eviction_candidates_returns_empty_when_children_are_fewer_than_the_tail_size(
        self,
    ) -> None:
        """The strictly-below branch of the same guard clause."""
        app: SloTUI = self._build_app()
        widgets: list[Widget] = [UserMessageBlock(text=f"msg{i}") for i in range(3)]

        with patch("src.tui.app.TRANSCRIPT_PROTECTED_TAIL_SIZE", 5):
            candidates: list[Widget] = app._eviction_candidates(children=widgets)

        assert candidates == []

    def test_protected_tail_is_strictly_smaller_than_the_transcript_window(self) -> None:
        """Pins the convergence invariant documented on the constant."""
        assert TRANSCRIPT_PROTECTED_TAIL_SIZE < TRANSCRIPT_WINDOW_SIZE

    # -- Pilot tests for the enforcement pass --

    @pytest.mark.asyncio
    async def test_run_window_enforcement_pass_preserves_the_newest_child_when_every_candidate_is_live(
        self,
    ) -> None:
        """The newest child is never touched even when every candidate reports live."""
        assert TRANSCRIPT_PROTECTED_TAIL_SIZE == 10
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app.action_clear()

            unfinalized_blocks: list[AssistantStreamBlock] = []
            for _ in range(90):
                unfinalized_blocks.append(await app.mount_assistant_block())
            user_block: UserMessageBlock = await app.mount_user_message_block(text="the user's new message")
            for _ in range(5):
                await pilot.pause()

            assert user_block in app._transcript_content.children
            for block in unfinalized_blocks:
                assert block in app._transcript_content.children
            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert non_summary == 91
            assert app._hidden_block_count == 0

    @pytest.mark.asyncio
    async def test_run_window_enforcement_pass_converges_to_the_window_when_overflow_lies_outside_the_tail(
        self,
    ) -> None:
        """Ordinary eviction still converges to exactly the window when overflow lies outside the tail."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app.action_clear()

            for _ in range(TRANSCRIPT_WINDOW_SIZE + 5):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()

            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app._hidden_block_count == 5
            assert app._earlier_summary is not None

    # -- 61.a.4: parametrised threshold reproduction --

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stuck_live", [29, 60, 79, 80, 90])
    async def test_run_window_enforcement_pass_preserves_the_user_message_at_every_diagnosed_live_block_count(
        self,
        stuck_live: int,
    ) -> None:
        """The user's new message survives at every stuck-live count the investigation measured."""
        assert TRANSCRIPT_PROTECTED_TAIL_SIZE == 10
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app.action_clear()

            unfinalized_blocks: list[AssistantStreamBlock] = []
            for _ in range(stuck_live):
                unfinalized_blocks.append(await app.mount_assistant_block())
            assert unfinalized_blocks[0].finalized is False

            settled_filler: int = max(0, TRANSCRIPT_WINDOW_SIZE - stuck_live)
            for _ in range(settled_filler):
                await app.mount_user_message_block(text="filler")

            children_before: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert children_before == max(TRANSCRIPT_WINDOW_SIZE, stuck_live)

            user_block: UserMessageBlock = await app.mount_user_message_block(text="the user's new prompt")
            for _ in range(5):
                await pilot.pause()

            children_count: int = len(list(app._transcript_content.children))
            assert user_block in app._transcript_content.children, (
                f"stuck_live={stuck_live}, children={children_count}, " f"hidden={app._hidden_block_count}"
            )
            assert app._hidden_block_count <= 1


class TestLivenessLeakReproduction:
    """End-to-end proof that a multi-iteration turn never hides the next prompt (spec 61)."""

    @pytest.mark.asyncio
    async def test_multi_iteration_turn_does_not_hide_the_next_prompt(self) -> None:
        """Spec 61: a multi-iteration turn never hides the user's next prompt.

        Deliberately runs in the non-converging window regime —
        TRANSCRIPT_WINDOW_SIZE is patched to 5 while TRANSCRIPT_PROTECTED_TAIL_SIZE
        keeps its production value of 10, so the eviction candidate set is always
        empty and the enforcer removes nothing. Nothing asserted here depends on
        eviction making progress: the `finalized` assertions prove the liveness
        fix (D1/D2) at source, and the visible-prompt assertion proves the
        user-facing symptom is gone.
        """

        @tool
        def stub_echo(text: str) -> str:
            """Echo the provided text."""
            return text

        agent: SloAgent = SloAgent(
            llm=FauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(
                        tool_calls=[FauxChatModel.tool_call_dict(name="stub_echo", args={"text": f"x{i}"})],
                    )
                    for i in range(5)
                ]
                + [
                    FauxChatModel.assistant_message(content="all done"),
                ],
                chunk_scripts=[
                    [
                        AIMessageChunk(
                            content=[{"type": "thinking", "thinking": f"pass {i}"}],
                            tool_calls=[{"id": f"call_{i}", "name": "stub_echo", "args": {"text": f"x{i}"}}],
                        )
                    ]
                    for i in range(5)
                ]
                + [
                    [AIMessageChunk(content=[{"type": "text", "text": "all done"}])],
                ],
            ),
            tools=[stub_echo],
        )
        session = SloAgentSession(
            agent=agent,
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        with patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None
                assert app._transcript_content is not None
                await app.action_clear()

                # --- first prompt: six iterations ---
                app._input.load_text("first prompt")
                await pilot.press("enter")
                await _await_idle(app=app, pilot=pilot, timeout_seconds=10.0)
                await pilot.pause()

                assistant_blocks: list[AssistantStreamBlock] = list(app.query(selector=AssistantStreamBlock))
                assert len(assistant_blocks) >= 2, (
                    "scripted turn did not drive multiple outer-loop iterations; "
                    f"mounted {len(assistant_blocks)} assistant blocks"
                )

                # LOAD-BEARING: D1/D2 proof — every block except the last is sealed.
                non_terminal_blocks: list[AssistantStreamBlock] = assistant_blocks[:-1]
                for index, block in enumerate(non_terminal_blocks):
                    assert block.finalized is True, (
                        f"assistant block {index} of {len(assistant_blocks)} still "
                        "reports itself live after the run terminated"
                    )

                # --- second prompt ---
                app._input.load_text("second prompt")
                await pilot.press("enter")
                await _await_idle(app=app, pilot=pilot, timeout_seconds=10.0)
                for _ in range(5):
                    await pilot.pause()

                # SYMPTOM-LEVEL: the user's message is on screen.
                user_texts: list[str] = [
                    child.text
                    for child in app._transcript_content.children
                    if isinstance(child, UserMessageBlock)
                ]
                assert "second prompt" in user_texts, (
                    f"the second prompt's UserMessageBlock was evicted; "
                    f"mounted user texts={user_texts}, "
                    f"children={len(list(app._transcript_content.children))}, "
                    f"hidden={app._hidden_block_count}"
                )


class TestLoadOlderEntries:
    """Load-older scrollback behavior for spec 60."""

    @staticmethod
    def _assistant_entries(*, count: int) -> list[TranscriptEntryDAO]:
        """Build ordered replay entries with distinctive assistant answers.

        Args:
            count (int): Number of entries to build.

        Returns:
            list[TranscriptEntryDAO]: Chronological assistant entries.
        """
        return [TranscriptEntryDAO(kind="assistant", answer=f"assistant-{index}") for index in range(count)]

    @staticmethod
    def _build_history_app(*, entries: list[TranscriptEntryDAO]) -> SloTUI:
        """Build a TUI whose replay path returns ``entries``.

        Args:
            entries (list[TranscriptEntryDAO]): Ordered replay entries.

        Returns:
            SloTUI: App under test.
        """
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-history-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = False
        session.history_root = None
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=entries)
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=MagicMock())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
        return SloTUI(session=session)

    @staticmethod
    async def _fill_transcript(*, app: SloTUI, pilot, line_count: int = 40) -> None:
        """Write enough transcript lines to create scroll headroom.

        Args:
            app (SloTUI): App under test.
            pilot: Textual pilot.
            line_count (int, optional): Number of lines to append. Defaults to 40.
        """
        for index in range(line_count):
            app._write_adapter_line(content=f"line {index}", classes="tool-result")
        await pilot.pause()

    @staticmethod
    def _visible_assistant_answers(*, app: SloTUI) -> list[str]:
        """Return assistant answers in on-screen transcript order.

        Args:
            app (SloTUI): App under inspection.

        Returns:
            list[str]: Visible assistant answers from top to bottom.
        """
        assert app._transcript_content is not None
        answers: list[str] = []
        for child in app._transcript_content.children:
            if isinstance(child, AssistantStreamBlock):
                answers.append(child.answer_text)
        return answers

    @pytest.mark.asyncio
    async def test_load_older_prepends_entries_below_summary_in_chronological_order(self) -> None:
        """One load-older pass prepends the batch immediately before the cursor.

        Asserts the whole visible list rather than a prefix: an earlier version
        of this test sliced ``[:5]``, which let hydration's over-reported cursor
        prepend a duplicate copy of the mounted batch without failing anything.
        """
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 5),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app._load_older_entries()
                await pilot.pause()
                visible_answers: list[str] = self._visible_assistant_answers(app=app)
                assert visible_answers == [
                    "assistant-2",
                    "assistant-3",
                    "assistant-4",
                    "assistant-5",
                    "assistant-6",
                    "assistant-7",
                    "assistant-8",
                    "assistant-9",
                    "assistant-10",
                    "assistant-11",
                ]
                assert app._load_older_cursor == 2

    @pytest.mark.asyncio
    async def test_load_older_preserves_scroll_anchor(self) -> None:
        """Prepending older entries keeps the reader anchored in place."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=14)
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 4),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert app._transcript_scroll is not None
                app._transcript_scroll.scroll_to(y=1, animate=False)
                await pilot.pause()
                scroll = app._transcript_scroll
                scroll_before: float = scroll.scroll_y
                await app._load_older_entries()
                await pump_until(pilot=pilot, predicate=lambda: scroll.scroll_y > scroll_before)
                assert scroll.scroll_y > scroll_before
                assert scroll.scroll_y <= scroll.max_scroll_y

    @pytest.mark.asyncio
    async def test_load_older_keeps_summary_when_cursor_is_still_positive(self) -> None:
        """The summary survives a pass that leaves older entries unreached.

        Renamed from a second ``test_load_older_removes_summary_when_cursor_reaches_zero``
        definition, which shadowed the one below it so this case never ran.
        """
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=8)
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 3),
            patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 2),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app._load_older_entries()
                await pilot.pause()
                assert app._load_older_cursor == 3
                assert app._earlier_summary is not None
                assert app._transcript_content is not None
                assert any(
                    "transcript-earlier-summary" == child.id for child in app._transcript_content.children
                )

    @pytest.mark.asyncio
    async def test_load_older_removes_summary_when_cursor_reaches_zero(self) -> None:
        """The summary is removed only after the canonical cursor reaches zero."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=5)
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 3),
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 3),
            patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 5),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app._load_older_entries()
                await pilot.pause()
                assert app._load_older_cursor == 0
                assert app._earlier_summary is None
                assert app._transcript_content is not None
                assert all(
                    child.id != "transcript-earlier-summary" for child in app._transcript_content.children
                )

    @pytest.mark.asyncio
    async def test_fetch_older_batch_returns_empty_without_cursor_or_history_read(self) -> None:
        """A zero cursor avoids a history read and returns no batch."""
        app: SloTUI = self._build_history_app(entries=self._assistant_entries(count=3))
        app._load_older_cursor = 0

        batch: list[TranscriptEntryDAO] = await app._fetch_older_batch()

        assert batch == []
        app._session.hydrate_transcript_entries.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_older_batch_returns_chronological_slice(self) -> None:
        """Fetching slices immediately before the canonical cursor in chronological order."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=8)
        with patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 3):
            app: SloTUI = self._build_history_app(entries=entries)
            app._load_older_cursor = 7

            batch: list[TranscriptEntryDAO] = await app._fetch_older_batch()

        assert [entry.answer for entry in batch] == ["assistant-4", "assistant-5", "assistant-6"]

    @pytest.mark.asyncio
    async def test_load_older_keeps_cursor_when_history_read_fails(self) -> None:
        """An error-safe history read does not advance the cursor or arm back-scroll mode."""
        app: SloTUI = self._build_history_app(entries=self._assistant_entries(count=4))
        app._load_older_cursor = 4
        app._session.hydrate_transcript_entries = AsyncMock(side_effect=OSError("history unavailable"))

        await app._load_older_entries()

        assert app._load_older_cursor == 4
        assert app._back_scroll_mode is False

    @pytest.mark.asyncio
    async def test_load_older_is_single_flight(self) -> None:
        """Concurrent load-older requests do not double-run the pass."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                async def _slow_pass() -> None:
                    await asyncio.sleep(0)

                with patch.object(
                    app, "_run_load_older_pass", new=AsyncMock(side_effect=_slow_pass)
                ) as mock_pass:
                    await asyncio.gather(app._load_older_entries(), app._load_older_entries())

                mock_pass.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_load_older_noops_when_cursor_is_zero(self) -> None:
        """No hidden history means load-older does nothing."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            child_count_before: int = len(list(app._transcript_content.children))
            await app._load_older_entries()
            await pilot.pause()
            assert len(list(app._transcript_content.children)) == child_count_before
            assert app._earlier_summary is None

    @pytest.mark.asyncio
    async def test_echo_user_line_force_reveals_and_clears_backscroll_mode(self) -> None:
        """Submitting a prompt returns from backscroll mode and re-pins the viewport."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await self._fill_transcript(app=app, pilot=pilot, line_count=40)
            assert app._transcript_scroll is not None
            app._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()
            app._back_scroll_mode = True

            await app._echo_user_line(text="live prompt")
            # Textual 8.x needs one extra refresh cycle to reconcile max_scroll_y
            # with the force-reveal scroll restoration; behaviour is unchanged.
            await pilot.pause()
            await pilot.pause()

            assert app._back_scroll_mode is False
            assert (app._transcript_scroll.max_scroll_y - app._transcript_scroll.scroll_y) <= 1.0

    @pytest.mark.asyncio
    async def test_transcript_is_at_bottom_returns_true_while_force_follow_latch_is_armed(self) -> None:
        """The force-follow branch protects streaming until deferred scroll completion."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await self._fill_transcript(app=app, pilot=pilot, line_count=40)
            assert app._transcript_scroll is not None
            app._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()

            app._force_following_until_layout = True

            assert app._transcript_is_at_bottom() is True

    @pytest.mark.asyncio
    async def test_echo_user_line_rearms_follow_for_subsequent_streaming_after_window_activation(
        self,
    ) -> None:
        """A stranded live viewport shows the submitted user turn and remains bottom-pinned while streaming."""
        app: SloTUI = self._build_history_app(entries=[])
        with patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                for index in range(12):
                    app._write_adapter_line(content=f"window line {index}", classes="tool-result")
                for _ in range(4):
                    await pilot.pause()
                assert app._transcript_scroll is not None
                app._transcript_scroll.scroll_to(y=0, animate=False)
                await pilot.pause()
                assert app._transcript_is_at_bottom() is False

                await app._echo_user_line(text="visible new prompt")
                await pilot.pause()
                await app._render_event(
                    event=AgentStreamEventDAO(kind="text_delta", delta="streaming tail", iteration=0)
                )
                await pump_until(pilot=pilot, predicate=lambda: app._transcript_is_at_bottom())

                assert app._transcript_is_at_bottom() is True
                assert any(
                    isinstance(child, UserMessageBlock) and child.text == "visible new prompt"
                    for child in app._transcript_content.children
                )

    def test_transcript_scroll_posts_reached_top_only_on_threshold_crossing(self) -> None:
        """The scroll widget emits a top-reached message on downward crossing only."""
        scroll: TranscriptScroll = TranscriptScroll()
        posted: list[Message] = []
        scroll.post_message = lambda message: posted.append(message)  # type: ignore[method-assign]

        with patch("textual.containers.VerticalScroll.watch_scroll_y", autospec=True) as mock_super_watch:
            scroll.watch_scroll_y(old_value=5.0, new_value=1.0)
            scroll.watch_scroll_y(old_value=1.0, new_value=0.0)

        assert mock_super_watch.call_count == 2
        assert len(posted) == 1
        assert isinstance(posted[0], TranscriptScroll.ReachedTop)

    def test_reached_top_handler_starts_worker_for_load_older(self) -> None:
        """The app-level top-reached handler delegates through ``run_worker``."""
        app: SloTUI = self._build_history_app(entries=[])
        with patch.object(app, "run_worker") as mock_run_worker:
            app.on_transcript_scroll_reached_top(TranscriptScroll.ReachedTop())

        mock_run_worker.assert_called_once()
        args, kwargs = mock_run_worker.call_args
        args[0].close()
        assert kwargs["group"] == "load-older"
        assert kwargs["exit_on_error"] is False


class TestHydrationEntryCursor:
    """Hydration bounds what it mounts and reports the cursor honestly (spec 62)."""

    @staticmethod
    def _assistant_entries(*, count: int) -> list[TranscriptEntryDAO]:
        """Build ordered replay entries with distinctive assistant answers.

        Args:
            count (int): Number of entries to build.

        Returns:
            list[TranscriptEntryDAO]: Chronological assistant entries.
        """
        return [TranscriptEntryDAO(kind="assistant", answer=f"assistant-{index}") for index in range(count)]

    def _build_history_app(self, *, entries: list[TranscriptEntryDAO]) -> SloTUI:
        """Build a TUI whose replay path returns ``entries``.

        Args:
            entries (list[TranscriptEntryDAO]): Ordered replay entries.

        Returns:
            SloTUI: App under test.
        """
        return TestLoadOlderEntries._build_history_app(entries=entries)

    @staticmethod
    def _visible_assistant_answers(*, app: SloTUI) -> list[str]:
        """Return assistant answers in on-screen transcript order.

        Args:
            app (SloTUI): App under inspection.

        Returns:
            list[str]: Visible assistant answers from top to bottom.
        """
        assert app._transcript_content is not None
        return [
            child.answer_text
            for child in app._transcript_content.children
            if isinstance(child, AssistantStreamBlock)
        ]

    @pytest.mark.asyncio
    async def test_hydration_mounts_only_the_newest_entry_limit_entries(self) -> None:
        """Hydration mounts the newest batch instead of every entry on disk."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)

        with patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                assert self._visible_assistant_answers(app=app) == [
                    "assistant-7",
                    "assistant-8",
                    "assistant-9",
                    "assistant-10",
                    "assistant-11",
                ]

    @pytest.mark.asyncio
    async def test_hydration_cursor_counts_only_entries_it_did_not_mount(self) -> None:
        """The cursor is the count of entries left above the mounted batch."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)

        with patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                assert app._load_older_cursor == 7
                assert app._earlier_summary is not None
                assert "7 earlier messages hidden" in str(app._earlier_summary.content)

    @pytest.mark.asyncio
    async def test_hydration_cursor_is_zero_when_history_fits_within_the_entry_limit(self) -> None:
        """Nothing is hidden when the whole history is mounted."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=3)

        with patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                assert app._load_older_cursor == 0
                assert app._earlier_summary is None

    @pytest.mark.asyncio
    async def test_load_older_after_hydration_prepends_no_duplicate_entries(self) -> None:
        """The batch prepended by a load-older pass never repeats a mounted entry.

        This is the regression guard for the defect diagnosed alongside spec 61:
        hydration used to set the cursor to the *total* entry count, so the first
        load-older pass re-fetched the newest batch — the entries already on
        screen — and prepended them above themselves, duplicated and out of
        chronological order.
        """
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)

        with (
            patch("src.tui.app.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.app.LOAD_OLDER_BATCH_SIZE", 4),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app._load_older_entries()
                await pilot.pause()

                visible_answers: list[str] = self._visible_assistant_answers(app=app)
                assert visible_answers == [
                    "assistant-3",
                    "assistant-4",
                    "assistant-5",
                    "assistant-6",
                    "assistant-7",
                    "assistant-8",
                    "assistant-9",
                    "assistant-10",
                    "assistant-11",
                ]
                assert len(visible_answers) == len(set(visible_answers))
                assert app._load_older_cursor == 3

    @pytest.mark.asyncio
    async def test_earlier_summary_omits_the_load_hint_when_no_entries_can_be_loaded(self) -> None:
        """A live session with evictions never advertises an unreachable load path.

        With no resumable history the cursor stays at zero, so the summary must
        not claim "0 earlier messages hidden" nor promise a scroll-to-top
        recovery that ``_has_older_entries_to_load`` would refuse.
        """
        app: SloTUI = self._build_history_app(entries=[])

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._hidden_block_count = 4
            await app._update_earlier_summary()
            await pilot.pause()

            assert app._load_older_cursor == 0
            assert app._earlier_summary is not None
            summary_text: str = str(app._earlier_summary.content)
            assert "0 earlier messages hidden" not in summary_text
            assert "scroll to the top" not in summary_text

    def test_hydration_entry_limit_is_positive(self) -> None:
        """Pins the constant's only load-bearing invariant."""
        assert TRANSCRIPT_HYDRATION_ENTRY_LIMIT > 0


class TestTypingNoReflow:
    """Typing plain prose must not reflow the transcript (spec 59, Bug #1, AC #1)."""

    @pytest.mark.asyncio
    async def test_typing_plain_prose_does_not_reflow_transcript(self) -> None:
        """Plain-prose keystrokes trigger no ``update_state`` when menu state is stable.

        The slash-suggestion menu returns ``visible=False`` for every plain-prose
        keystroke. With the Phase 1a equality guard in place, ``update_state``
        returns early on the second and subsequent identical states, so no
        ``Static.update`` is issued and Textual never schedules a reflow.

        Asserted via a spy installed on ``app._suggestion_menu.update_state``
        so the test is implementation-agnostic (does not scrape reflow internals).
        Every call recorded by the spy must have ``visible is False``, and the
        final stored state must be ``visible is False``.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._suggestion_menu is not None
            assert app._input is not None
            # Install a spy that records every state passed to update_state.
            recorded_states: list[SlashSuggestionStateDAO] = []
            original_update_state = app._suggestion_menu.update_state

            def _spy_update_state(*, state: SlashSuggestionStateDAO) -> None:
                recorded_states.append(state)
                original_update_state(state=state)

            app._suggestion_menu.update_state = _spy_update_state  # type: ignore[method-assign]
            # Focus the prompt and type plain prose (no leading slash).
            app.set_focus(app._input)
            await pilot.pause()
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()
            # Every state the spy recorded must be non-visible.
            for recorded_state in recorded_states:
                assert (
                    recorded_state.visible is False
                ), f"Expected visible=False for plain prose but got {recorded_state}"
            # The final stored state on the menu must be non-visible.
            assert app._suggestion_menu._state.visible is False
