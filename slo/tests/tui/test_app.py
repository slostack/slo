"""Pilot tests for ``SloTUI`` (sub-spec 02.a.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from textual import events
from textual.app import App
from textual.message import Message
from textual.pilot import Pilot
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
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
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
from src.tui.git_diff_content_service import GitDiffContentDAO, GitDiffContentError
from src.tui.git_diff_screen import GitDiffScreen
from src.tui.slodiff.model import FileStateKind
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO
from src.tui.thinking_spinner import _BRAILLE_FRAMES, ThinkingSpinner
from tests.tui._scroll_settle import pump_until
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.queued_prompt_block import QueuedPromptBlock
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


def _empty_usage_snapshot() -> SessionUsageSnapshotDAO:
    """Build a minimal real usage snapshot for ``MagicMock`` session fixtures.

    The usage status bar formats token quantities arithmetically (spec 72.a.5),
    so fixtures must hand it a real ``SessionUsageSnapshotDAO`` rather than a
    bare ``MagicMock`` whose numeric fields would be mocks.

    Returns:
        SessionUsageSnapshotDAO: A snapshot with unknown usage and no limits.
    """
    return SessionUsageSnapshotDAO(
        active_model_name="gpt-5.4",
        active_reasoning_level="high",
    )


async def _await_idle(
    *,
    app: SloTUI,
    pilot: Pilot,
    timeout_seconds: float = 5.0,
) -> None:
    """Poll until ``app._in_flight_task is None`` or timeout.

    Args:
        app (SloTUI): The app under test.
        pilot (Pilot): The Textual Pilot driver.
        timeout_seconds (float): Maximum wait before failing.
    """
    deadline: float = asyncio.get_event_loop().time() + timeout_seconds
    while app._in_flight_task is not None:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("timed out waiting for in-flight task to clear")
        await pilot.pause()


async def _pump_until_drained(
    *,
    app: SloTUI,
    pilot: Pilot,
    invoke_log: list[str],
    expected_invokes: list[str],
) -> None:
    """Pump until the queued prompt drained and every expected invoke finished.

    The completion handoff keeps the finished task tracked until it has either
    marked the app idle or assigned the drained successor task, so the
    predicate requires the held slot to be empty, the invoke log to match the
    full expected sequence, and the final run to have fully released the app
    task slot. Called by the queued-prompt drain tests; the caller's own
    assertions fail when the predicate never settles.

    Args:
        app (SloTUI): The app under test.
        pilot (Pilot): The Textual Pilot driver.
        invoke_log (list[str]): Recorded ``session.invoke`` texts.
        expected_invokes (list[str]): Expected full invoke sequence.
    """
    await pump_until(
        pilot=pilot,
        predicate=lambda: invoke_log == expected_invokes
        and app._in_flight_task is None
        and app._queued_prompt_text is None,
    )


async def _wait_for_predicate(
    *,
    predicate: Callable[[], bool],
    timeout_seconds: float = 5.0,
    interval_seconds: float = 0.01,
) -> bool:
    """Poll a predicate with plain event-loop sleeps until it holds or times out.

    Unlike ``pump_until`` this never calls ``pilot.pause()``, so it is safe to
    use while a queued-block removal is deliberately stalled: the drain runs
    directly from ``SloTUI._finish_prompt_run`` under the submission gate and
    a pilot pause would deadlock the test behind the stalled removal.

    WHO: The queued-prompt race pilots call it around the gated drain.
    WHEN: The test cannot safely use ``pilot.pause()`` until the held removal
    is released.

    Args:
        predicate (Callable[[], bool]): Condition to await.
        timeout_seconds (float): Maximum wait before giving up.
        interval_seconds (float): Sleep between checks.

    Returns:
        bool: True when the predicate held before the timeout.
    """
    deadline: float = asyncio.get_event_loop().time() + timeout_seconds
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            return False
        await asyncio.sleep(interval_seconds)
    return True


def _make_gated_invoke(
    *,
    invoke_log: list[str],
    gates: Optional[dict[str, asyncio.Event]] = None,
    failures: Optional[dict[str, BaseException]] = None,
) -> Callable[..., AsyncIterator[AgentStreamEventDAO]]:
    """Build a fake ``session.invoke`` async generator gated per prompt text.

    Called by the queued-prompt gating tests to replace ``session.invoke`` with
    a deterministic async generator whose completion the test controls.

    Args:
        invoke_log (list[str]): Log appended with each invoked text, in order.
        gates (Optional[dict[str, asyncio.Event]]): Per-text events that must
            be set before that invoke completes. An event the test never sets
            simulates a hung run.
        failures (Optional[dict[str, BaseException]]): Per-text exceptions
            raised after that invoke's gate opens.

    Returns:
        Callable[..., AsyncIterator[AgentStreamEventDAO]]: Async generator
            function compatible with ``session.invoke``.
    """

    async def _fake_invoke(*, text: str) -> AsyncIterator[AgentStreamEventDAO]:
        invoke_log.append(text)
        gate: Optional[asyncio.Event] = (gates or {}).get(text)
        if gate is not None:
            await gate.wait()
        failure: Optional[BaseException] = (failures or {}).get(text)
        if failure is not None:
            raise failure
        if text == "__never_yielded__":
            yield AgentStreamEventDAO(kind="text_delta", delta="")

    return _fake_invoke


def _require_prompt_input(*, app: SloTUI) -> PromptInput:
    """Return the mounted prompt input.

    Args:
        app (SloTUI): The app under test.

    Returns:
        PromptInput: The mounted prompt editor.
    """
    assert app._input is not None
    return app._input


def _require_adapter_lines(*, app: SloTUI) -> list[tuple[str, str]]:
    """Return the recorded transcript lines.

    Args:
        app (SloTUI): The app under test.

    Returns:
        list[tuple[str, str]]: Recorded ``(content, classes)`` transcript lines.
    """
    assert app._adapter is not None
    return app._adapter.lines


def _visible_prompt_lines(*, app: SloTUI) -> int:
    """Return the visible prompt-editor content height in lines.

    Args:
        app (SloTUI): The app under test.

    Returns:
        int: The number of visible content lines inside ``PromptInput``.
    """
    prompt_input: PromptInput = _require_prompt_input(app=app)
    return prompt_input.size.height


class TestDiffSlashCommand:
    """Pilot coverage for the operator-facing /diff screen flow."""

    async def test_diff_command_when_content_loads_pushes_screen_and_escape_returns(
        self, tmp_path: Path
    ) -> None:
        """The real slash route opens GitDiffScreen and Escape restores the transcript."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
        )
        content = GitDiffContentDAO(
            repository_relative_path="example.py",
            base_content="before\\n",
            changed_content="after\\n",
            file_state=FileStateKind.MODIFIED,
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            with patch(
                "src.tui.git_diff_content_service.GitDiffContentService.invoke",
                new=AsyncMock(return_value=content),
            ):
                await app._dispatch_slash_command(line="/diff example.py")
                await pilot.pause()
            assert isinstance(app.screen, GitDiffScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, GitDiffScreen)

    async def test_diff_command_when_content_load_fails_writes_safe_message_without_screen(
        self, tmp_path: Path
    ) -> None:
        """The TUI keeps the transcript active when the service rejects a requested path."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)
        error = GitDiffContentError(operator_message="No changes detected for example.py.")

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.git_diff_content_service.GitDiffContentService.invoke",
                new=AsyncMock(side_effect=error),
            ):
                await app._dispatch_slash_command(line="/diff example.py")
                await pilot.pause()
            assert ("No changes detected for example.py.", "tool-result") in app._adapter.lines
            assert not isinstance(app.screen, GitDiffScreen)

    async def test_diff_command_when_service_io_fails_writes_safe_message_without_screen(
        self, tmp_path: Path
    ) -> None:
        """A service-wrapped I/O failure stays in the transcript and never opens a screen."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)
        error = GitDiffContentError(operator_message="Could not read HEAD version of file.")

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.git_diff_content_service.GitDiffContentService.invoke",
                new=AsyncMock(side_effect=error),
            ):
                await app._dispatch_slash_command(line="/diff example.py")
                await pilot.pause()
            assert ("Could not read HEAD version of file.", "tool-result") in app._adapter.lines
            assert not isinstance(app.screen, GitDiffScreen)


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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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


class TestTurnSeparatorRestyle:
    """The Pi-restyled turn separator constant and mount path (spec 72.a.5)."""

    def test_turn_separator_is_a_muted_horizontal_rule(self) -> None:
        """``TURN_SEPARATOR`` is exactly eighteen ``─`` rule characters."""
        from src.tui.app import _TranscriptAdapter

        assert _TranscriptAdapter.TURN_SEPARATOR == "─" * 18


class TestCollapseHomeInPath:
    """Title-only home abbreviation for the working directory (spec 72.a.5)."""

    def test_home_directory_collapses_to_tilde(self) -> None:
        """The home directory itself renders as plain ``~``."""
        assert SloTUI._collapse_home_in_path(path=Path.home()) == "~"

    def test_descendant_of_home_collapses_to_tilde_path(self) -> None:
        """A child below home renders as ``~/child``."""
        descendant: Path = Path.home() / "Code" / "project"

        assert SloTUI._collapse_home_in_path(path=descendant) == "~/Code/project"

    def test_path_outside_home_stays_absolute(self) -> None:
        """An unrelated absolute path is returned unchanged."""
        outside: Path = Path("/tmp/slo-outside-home")

        assert SloTUI._collapse_home_in_path(path=outside) == "/tmp/slo-outside-home"

    def test_home_prefix_lookalike_stays_absolute(self) -> None:
        """A sibling sharing the home string prefix is not falsely collapsed.

        ``/Users/<name>-other/project`` starts with the same characters as
        ``/Users/<name>`` but is not a descendant; only ``Path.relative_to``
        ancestry (not string replacement) keeps it absolute.
        """
        lookalike: Path = Path(str(Path.home()) + "-other") / "project"

        assert SloTUI._collapse_home_in_path(path=lookalike) == str(lookalike)

    @pytest.mark.parametrize(
        ("workdir", "expected_workdir"),
        [
            (Path.home(), "~"),
            (Path.home() / "Code" / "project", "~/Code/project"),
            (Path("/tmp/slo-outside-home"), "/tmp/slo-outside-home"),
            (
                Path(f"{Path.home()}-other") / "project",
                str(Path(f"{Path.home()}-other") / "project"),
            ),
        ],
    )
    async def test_title_bar_renders_only_home_descendants_with_tilde(
        self,
        workdir: Path,
        expected_workdir: str,
    ) -> None:
        """Verify title cwd abbreviation preserves real path ancestry.

        WHO: The spec-72.a.5 title-bar regression suite mounts the live TUI.
        """
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=workdir,
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert app.title.startswith(f"slo · {expected_workdir} · ")


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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
    async def test_inbox_chat_turn_starts_directly_when_idle(self, tmp_path: Path) -> None:
        """`chat_turn` inbox items start a direct machine turn when the app is idle.

        The machine turn never enters the user queue: no ``QueuedPromptBlock``
        mounts, the slot stays empty, and no human-path ``user-line`` echo is
        recorded for the inbox text.
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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
            # The machine turn never touches the user queue or human echo path.
            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            assert list(app.query(QueuedPromptBlock)) == []
            assert (
                "> Check the repo and summarize new failures.",
                "user-line",
            ) not in _require_adapter_lines(app=app)

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
        old_session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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
        new_session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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
    async def test_new_session_rejection_while_run_active_preserves_existing_behavior(self) -> None:
        """`/new` stays rejected during an active run; no second session is built."""
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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch("src.tui.app.SloAgentSession.build") as mock_build:
                await app._start_new_session(requested_name="fresh thread")
                await pilot.pause()
                mock_build.assert_not_called()

            assert app._session is session
            assert (
                "cannot start a new session while a prompt is in flight; run /abort first",
                "tool-result",
            ) in app._adapter.lines

    @pytest.mark.asyncio
    async def test_new_session_rejection_when_app_task_is_tracked(self) -> None:
        """Keep `/new` rejected while the app tracks a completion-handoff task.

        WHAT: Verifies the app-task guard rejects session replacement even
            when the session no longer reports itself as running.
        WHO: The queued-prompt gating pilot suite calls this regression test.
        WHEN: A completed prompt remains tracked until its queue handoff
            finishes, so `/new` must not slip through the session guard alone.
        """
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_root = Path("/tmp/history")
        session.history_enabled = True
        session.is_running = False
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task
            try:
                with patch("src.tui.app.SloAgentSession.build") as mock_build:
                    await app._start_new_session(requested_name="fresh thread")
                    await pilot.pause()
                    mock_build.assert_not_called()

                assert app._session is session
                adapter = app._adapter
                assert adapter is not None
                assert (
                    "cannot start a new session while a prompt is in flight; run /abort first",
                    "tool-result",
                ) in adapter.lines
            finally:
                busy_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await busy_task
                app._in_flight_task = None

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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

            assert ("─" * 18, "turn-separator") in app._adapter.lines

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())

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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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


class TestQueuedPromptGating:
    """One-deep latest-wins queued ordinary prompt behind the active run (spec 72.a.4)."""

    _SURVIVAL_NOTICE: str = (
        "(queued prompt held — it will run next; resubmit to replace it, /clear to drop it)"
    )

    @staticmethod
    def _mock_session_stub() -> MagicMock:
        """Build a session stub with the prompt- and lifecycle-facing surface.

        Returns:
            MagicMock: ``SloAgentSession``-specced stub for queue/abort tests.
        """
        session: MagicMock = MagicMock(spec=SloAgentSession)
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.model_pool_dao = None
        session.history_root = Path("/tmp/history")
        session.history_enabled = True
        session.is_running = False
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
        session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
        session.abort = MagicMock()
        session.steer = MagicMock()
        return session

    @staticmethod
    async def _submit_prompt(*, app: SloTUI, pilot: Pilot, text: str) -> None:
        """Submit one prompt through the mounted Textual input.

        WHAT: Enters text through the real input path and waits for rendering.
        WHO: Queued-prompt pilot tests call it for each operator submission.
        WHEN: Before asserting queue state or releasing a gated run.

        Args:
            app (SloTUI): Mounted application under test.
            pilot (Pilot): Textual pilot driving the application.
            text (str): Prompt text to submit.
        """
        assert app._input is not None
        app._input.load_text(text)
        await pilot.press("enter")
        await pilot.pause()

    @pytest.mark.asyncio
    async def test_submit_while_in_flight_mounts_queued_block_instead_of_discarding(self) -> None:
        """A busy ordinary submit fills the visible slot; no echo, no invoke, no busy line."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first reply"), AIMessage(content="second reply")],
        )
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": release}),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                assert app._in_flight_task is not None

                await self._submit_prompt(app=app, pilot=pilot, text="queued request")

                # The held text occupies the one-deep slot with exactly one block.
                assert app._queued_prompt_text == "queued request"
                queued_blocks: list[QueuedPromptBlock] = list(app.query(QueuedPromptBlock))
                assert len(queued_blocks) == 1
                assert queued_blocks[0] is app._queued_prompt_block
                assert "⏳ Queued: queued request" in str(queued_blocks[0].render())

                # It is not a user turn yet: no echo and no second invoke.
                assert ("> queued request", "user-line") not in _require_adapter_lines(app=app)
                assert len(list(app.query(UserMessageBlock))) == 1
                assert invoke_log == ["first"]

                release.set()
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "queued request"],
                )

    @pytest.mark.asyncio
    async def test_held_prompt_stays_anchored_above_input_until_consumed(self) -> None:
        """Acceptance (72 review §8): the held block anchors directly above ``PromptInput``.

        During a long streaming run the queued block mounts as a direct child of
        ``#chat-shell`` immediately before ``PromptInput`` — never inside
        ``#transcript-content`` — and stays anchored there while real streamed
        ``text_delta`` output scrolls the transcript and keeps it bottom-following.
        A busy resubmit replaces the SAME anchored instance in place. When the
        active run completes, the anchored block is removed BEFORE the accepted
        user turn echoes into the transcript.
        """
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first reply"), AIMessage(content="second reply")],
        )
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []
        order: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": release}),
        ):
            async with app.run_test(size=(80, 8)) as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                assert app._in_flight_task is not None

                await self._submit_prompt(app=app, pilot=pilot, text="held")

                chat_shell: Widget = app.query_one("#chat-shell")
                block: Optional[QueuedPromptBlock] = app._queued_prompt_block
                assert block is not None
                assert app._transcript_content is not None
                # Anchored: a direct ``#chat-shell`` child immediately above the input.
                assert block.parent is chat_shell
                assert block not in app._transcript_content.children
                shell_children: list[Widget] = list(chat_shell.children)
                assert shell_children.index(block) == shell_children.index(prompt_input) - 1

                # Real streamed output during the gated run overflows the tiny
                # viewport, so the transcript genuinely scrolls...
                for index in range(40):
                    await app._render_event(
                        AgentStreamEventDAO(
                            kind="text_delta",
                            iteration=0,
                            delta=f"stream line {index}\n",
                        ),
                    )

                assert app._transcript_scroll is not None
                scroll: TranscriptScroll = app._transcript_scroll
                await pump_until(pilot=pilot, predicate=lambda: scroll.max_scroll_y > 0)
                assert scroll.max_scroll_y > 0
                # ...and stays bottom-following through the stream...
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: (scroll.max_scroll_y - scroll.scroll_y) <= 1.0,
                )
                assert (scroll.max_scroll_y - scroll.scroll_y) <= 1.0
                assert app._transcript_is_at_bottom()
                # ...while the anchor holds directly above the input.
                assert block.parent is chat_shell
                assert block not in app._transcript_content.children
                shell_children = list(chat_shell.children)
                assert shell_children.index(block) == shell_children.index(prompt_input) - 1

                # Latest-wins resubmit updates the SAME anchored instance in place.
                await self._submit_prompt(app=app, pilot=pilot, text="held newer")
                assert app._queued_prompt_block is block
                assert block.queued_text == "held newer"
                assert len(list(app.query(QueuedPromptBlock))) == 1
                assert block.parent is chat_shell

                # Completion removes the anchored block BEFORE the held turn echoes.
                original_remove_block = app._remove_queued_prompt_block

                async def _tracked_remove_block() -> None:
                    order.append("remove_queued_block")
                    await original_remove_block()

                original_echo = app._echo_user_line

                async def _tracked_echo(*, text: str) -> None:
                    order.append(f"echo:{text}")
                    await original_echo(text=text)

                with (
                    patch.object(
                        target=app, attribute="_remove_queued_prompt_block", new=_tracked_remove_block
                    ),
                    patch.object(target=app, attribute="_echo_user_line", new=_tracked_echo),
                ):
                    release.set()
                    await _pump_until_drained(
                        app=app,
                        pilot=pilot,
                        invoke_log=invoke_log,
                        expected_invokes=["first", "held newer"],
                    )

                assert order.index("remove_queued_block") < order.index("echo:held newer")
                assert list(app.query(QueuedPromptBlock)) == []
                assert ("> held newer", "user-line") in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_second_busy_submit_replaces_the_single_queued_prompt(self) -> None:
        """Latest-wins: one block carrying the newest text; the replaced text never runs."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first reply"), AIMessage(content="second reply")],
        )
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": release}),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                await self._submit_prompt(app=app, pilot=pilot, text="queued one")
                await self._submit_prompt(app=app, pilot=pilot, text="queued two")

                # One block, newest text, same mounted instance.
                assert app._queued_prompt_text == "queued two"
                queued_blocks: list[QueuedPromptBlock] = list(app.query(QueuedPromptBlock))
                assert len(queued_blocks) == 1
                assert queued_blocks[0].queued_text == "queued two"
                assert "⏳ Queued: queued two" in str(queued_blocks[0].render())

                release.set()
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "queued two"],
                )

                # The replaced text is neither invoked nor echoed as a user turn.
                assert invoke_log == ["first", "queued two"]
                assert ("> queued one", "user-line") not in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_queued_prompt_drains_after_completed_run_in_remove_echo_start_order(self) -> None:
        """Drain order: the block is removed before the held turn echoes and starts."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="first reply"), AIMessage(content="second reply")],
        )
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []
        order: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": release}),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                original_remove_block = app._remove_queued_prompt_block

                async def _tracked_remove_block() -> None:
                    order.append("remove_queued_block")
                    await original_remove_block()

                original_echo = app._echo_user_line

                async def _tracked_echo(*, text: str) -> None:
                    order.append(f"echo:{text}")
                    await original_echo(text=text)

                with (
                    patch.object(
                        target=app, attribute="_remove_queued_prompt_block", new=_tracked_remove_block
                    ),
                    patch.object(target=app, attribute="_echo_user_line", new=_tracked_echo),
                ):
                    await self._submit_prompt(app=app, pilot=pilot, text="first")
                    await self._submit_prompt(app=app, pilot=pilot, text="queued")
                    held_block: Optional[QueuedPromptBlock] = app._queued_prompt_block
                    assert held_block is not None

                    release.set()
                    await _pump_until_drained(
                        app=app,
                        pilot=pilot,
                        invoke_log=invoke_log,
                        expected_invokes=["first", "queued"],
                    )

                # Removal strictly precedes the echo of the held turn.
                assert order.index("remove_queued_block") < order.index("echo:queued")
                assert invoke_log == ["first", "queued"]
                assert app._queued_prompt_text is None
                assert app._queued_prompt_block is None
                assert list(app.query(QueuedPromptBlock)) == []
                assert ("> queued", "user-line") in _require_adapter_lines(app=app)
                # The detached block no longer counts as live for window eviction.
                assert app._is_block_live(child=held_block) is False

    @pytest.mark.asyncio
    async def test_queued_prompt_drains_after_failed_run(self) -> None:
        """A provider failure still drains the held prompt because the handoff is in `finally`."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(
                invoke_log=invoke_log,
                gates={"first": release},
                failures={"first": RuntimeError("provider boom")},
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                await self._submit_prompt(app=app, pilot=pilot, text="queued")

                release.set()
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "queued"],
                )

                assert any(entry[0].startswith("(error:") for entry in _require_adapter_lines(app=app))
                assert ("> queued", "user-line") in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_queued_prompt_drains_after_hard_cancel(self) -> None:
        """A hard-cancelled run still hands off to the held prompt after `(aborted)`."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        never: asyncio.Event = asyncio.Event()  # never set — the hung run
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": never}),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                await self._submit_prompt(app=app, pilot=pilot, text="queued")
                assert app._in_flight_task is not None

                # Bypass the grace timer and force the escalation directly.
                app._hard_cancel_task(task=app._in_flight_task)
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "queued"],
                )

                assert ("(aborted)", "assistant-aborted") in _require_adapter_lines(app=app)
                assert ("> queued", "user-line") in _require_adapter_lines(app=app)
                assert app._in_flight_task is None

    @pytest.mark.asyncio
    async def test_third_submit_waiting_during_drain_queues_behind_drained_prompt(self) -> None:
        """A submit landing mid-drain waits on the gate, then queues behind the drained run.

        Stalls ``QueuedPromptBlock.remove`` so the completion handoff holds the
        prompt-submission gate; the third submission must not observe an idle
        gap, start a second task, or overtake the drained prompt in invoke
        order. The completed run task must remain tracked as the app run guard
        for the whole stall — this falsifies the old clear-before-await
        ordering, under which the third submit would have observed the app as
        idle and started a second concurrent run ahead of the held prompt.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        release_first: asyncio.Event = asyncio.Event()
        release_second: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(
                invoke_log=invoke_log,
                gates={"first": release_first, "second": release_second},
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                first_task: Optional[asyncio.Task[None]] = app._in_flight_task
                assert first_task is not None
                await self._submit_prompt(app=app, pilot=pilot, text="second")
                assert app._queued_prompt_text == "second"
                held_block: Optional[QueuedPromptBlock] = app._queued_prompt_block
                assert held_block is not None

                # Track later queue insertions; "second" was queued before this patch.
                queue_calls: list[str] = []
                original_queue_prompt = app._queue_prompt

                async def _tracked_queue_prompt(*, text: str) -> None:
                    queue_calls.append(text)
                    await original_queue_prompt(text=text)

                # Signal when the third submission handler reaches the gate.
                submit_entered: asyncio.Event = asyncio.Event()
                original_submit = app._submit_or_queue_prompt

                async def _tracked_submit(*, text: str) -> None:
                    submit_entered.set()
                    await original_submit(text=text)

                # Stall the queued block's removal so the drain holds the gate.
                remove_started: asyncio.Event = asyncio.Event()
                remove_release: asyncio.Event = asyncio.Event()
                original_remove = held_block.remove

                async def _wait_then_remove() -> None:
                    await remove_release.wait()
                    await original_remove()

                def _stalling_remove() -> Awaitable[None]:
                    remove_started.set()
                    return _wait_then_remove()

                with (
                    patch.object(target=app, attribute="_queue_prompt", new=_tracked_queue_prompt),
                    patch.object(target=app, attribute="_submit_or_queue_prompt", new=_tracked_submit),
                    patch.object(target=held_block, attribute="remove", new=_stalling_remove),
                ):
                    release_first.set()
                    started: bool = await _wait_for_predicate(predicate=lambda: remove_started.is_set())
                    assert started, "drain never reached the stalled block removal"

                    third_task: asyncio.Task[None] = asyncio.create_task(
                        app.on_prompt_input_submitted(PromptInput.Submitted(text="third"))
                    )
                    try:
                        entered: bool = await _wait_for_predicate(predicate=submit_entered.is_set)
                        assert entered, "third submission never reached the submission gate"
                        # The third handler is parked on the gate: no queue mutation,
                        # no detachment of the block mid-removal, and the completed
                        # first run remains tracked as the app run guard.
                        assert not third_task.done()
                        assert queue_calls == []
                        assert app._in_flight_task is first_task
                        assert app._queued_prompt_block is held_block
                    finally:
                        # Always release the stalled drain so a failed assertion
                        # cannot wedge app shutdown behind the held gate.
                        remove_release.set()

                    third_done: bool = await _wait_for_predicate(predicate=lambda: third_task.done())
                    assert third_done, "third submission never completed after the drain"

                    # The drain resumes concurrently with the parked third
                    # handler; on a loaded loop the third handler can finish
                    # first, so wait for the drained invoke to actually start
                    # instead of assuming the scheduling order.
                    drained: bool = await _wait_for_predicate(
                        predicate=lambda: invoke_log == ["first", "second"]
                    )
                    assert drained, "drained prompt never invoked after the block removal"

                # The drained prompt won: exactly two invokes, in order.
                assert invoke_log == ["first", "second"]
                # The third submission became the sole queue behind the drained run.
                assert queue_calls == ["third"]
                assert app._in_flight_task is not None
                assert app._queued_prompt_text == "third"
                queued_blocks: list[QueuedPromptBlock] = list(app.query(QueuedPromptBlock))
                assert len(queued_blocks) == 1
                assert queued_blocks[0].queued_text == "third"

                release_second.set()
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "second", "third"],
                )

    @pytest.mark.asyncio
    async def test_ctrl_c_with_queued_prompt_preserves_slot_and_writes_survival_notice(self) -> None:
        """``^C`` aborts the run cooperatively, keeps the held prompt, and explains it once.

        The fake ``session.invoke`` for the active run terminates only when the
        app's abort action fires — not when the test manually releases a gate —
        so the drain that follows is the real cooperative-abort terminal path.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        abort_requested: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        async def _cooperative_invoke(*, text: str) -> AsyncIterator[AgentStreamEventDAO]:
            invoke_log.append(text)
            if text == "first":
                await abort_requested.wait()
                return
            yield AgentStreamEventDAO(kind="run_completed")

        with (
            patch.object(target=session, attribute="invoke", new=_cooperative_invoke),
            patch.object(target=session, attribute="abort", side_effect=abort_requested.set) as mock_abort,
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                await self._submit_prompt(app=app, pilot=pilot, text="held")
                assert app._queued_prompt_text == "held"

                await pilot.press("ctrl+c")
                # The cooperative abort itself ends the first run — no manual
                # release — and the held prompt drains next.
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first", "held"],
                )

                assert mock_abort.call_count == 1
                # The abort retained the held prompt: it ran as the next turn.
                assert invoke_log == ["first", "held"]
                assert ("> held", "user-line") in _require_adapter_lines(app=app)
                # The survival notice was written exactly once, ahead of the
                # ``(aborting…)`` marker.
                notice_entries: list[tuple[str, str]] = [
                    entry for entry in _require_adapter_lines(app=app) if entry[0] == self._SURVIVAL_NOTICE
                ]
                assert len(notice_entries) == 1
                contents: list[str] = [entry[0] for entry in _require_adapter_lines(app=app)]
                assert contents.index(self._SURVIVAL_NOTICE) < contents.index("(aborting…)")

    @pytest.mark.asyncio
    async def test_slash_abort_with_queued_prompt_preserves_slot_and_writes_survival_notice(self) -> None:
        """``/abort`` keeps the router contract and writes the same survival notice once."""
        session: MagicMock = self._mock_session_stub()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="held prompt"))
            await pilot.pause()
            assert app._queued_prompt_text == "held prompt"

            await app._dispatch_slash_command(line="/abort")
            await pilot.pause()

            # The router still owns the cooperative abort request.
            session.abort.assert_called_once_with()
            assert app._queued_prompt_text == "held prompt"
            notice_entries: list[tuple[str, str]] = [
                entry for entry in _require_adapter_lines(app=app) if entry[0] == self._SURVIVAL_NOTICE
            ]
            assert len(notice_entries) == 1

            busy_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await busy_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_abort_without_queued_prompt_writes_no_survival_notice(self) -> None:
        """Guard path: no held prompt means no survival notice is written."""
        session: MagicMock = self._mock_session_stub()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task

            await app._dispatch_slash_command(line="/abort")
            await pilot.pause()

            session.abort.assert_called_once_with()
            assert all(entry[0] != self._SURVIVAL_NOTICE for entry in _require_adapter_lines(app=app))

            busy_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await busy_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_clear_drops_queued_prompt_and_detaches_its_block(self) -> None:
        """`/clear` drops the slot and detaches the block; the held text never runs."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        app: SloTUI = SloTUI(session=session)
        release: asyncio.Event = asyncio.Event()
        invoke_log: list[str] = []

        with patch.object(
            target=session,
            attribute="invoke",
            new=_make_gated_invoke(invoke_log=invoke_log, gates={"first": release}),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await self._submit_prompt(app=app, pilot=pilot, text="first")
                await self._submit_prompt(app=app, pilot=pilot, text="held")
                held_block: Optional[QueuedPromptBlock] = app._queued_prompt_block
                assert held_block is not None

                await app.action_clear()
                await pilot.pause()

                assert app._queued_prompt_text is None
                assert app._queued_prompt_block is None
                assert list(app.query(QueuedPromptBlock)) == []
                assert app._is_block_live(child=held_block) is False

                # The active run completes, but the discarded text never invokes.
                release.set()
                await _pump_until_drained(
                    app=app,
                    pilot=pilot,
                    invoke_log=invoke_log,
                    expected_invokes=["first"],
                )
                assert invoke_log == ["first"]

    @pytest.mark.asyncio
    async def test_allowed_new_session_clear_path_discards_queue_state(self) -> None:
        """An allowed `/new` replacement discards the slot; nothing crosses sessions."""
        old_session: MagicMock = self._mock_session_stub()
        new_session: MagicMock = self._mock_session_stub()
        new_session.session_id = "new-session-5678"

        app: SloTUI = SloTUI(session=old_session)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Controlled busy state so an ordinary submission fills the slot.
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="held prompt"))
            await pilot.pause()
            assert app._queued_prompt_text == "held prompt"
            assert app._queued_prompt_block is not None
            # Return the app to idle so the replacement is allowed.
            busy_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await busy_task
            app._in_flight_task = None

            with patch("src.tui.app.SloAgentSession.build", return_value=new_session):
                await app._start_new_session(requested_name=None)
                await pilot.pause()

            assert app._session is new_session
            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            assert list(app.query(QueuedPromptBlock)) == []

    @pytest.mark.asyncio
    async def test_slash_command_while_in_flight_does_not_queue(self) -> None:
        """Slash text dispatches immediately mid-run and never enters the slot."""
        session: MagicMock = self._mock_session_stub()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task

            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/steer be terse"))
            await pilot.pause()
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/help"))
            await pilot.pause()

            session.steer.assert_called_once_with(message="be terse")
            assert any("help" in entry[0].lower() for entry in _require_adapter_lines(app=app))
            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            assert list(app.query(QueuedPromptBlock)) == []

            busy_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await busy_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_inbox_poll_does_not_claim_chat_turn_while_local_task_is_active(
        self, tmp_path: Path
    ) -> None:
        """The idle guard keeps a pending `chat_turn` unclaimed while a run is active."""
        history_root: Path = tmp_path / "history"
        inbox_store: SessionInboxStore = SessionInboxStore(history_root=history_root)
        session: MagicMock = self._mock_session_stub()
        session.history_root = history_root

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
            busy_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
            app._in_flight_task = busy_task

            await app._poll_session_inbox()
            await pilot.pause()

            # The local task is untouched and the inbox item was not claimed/acked.
            assert app._in_flight_task is busy_task
            assert await inbox_store.list_pending(session_id="session-1234") == [message]
            assert await inbox_store.list_done(session_id="session-1234") == []

            busy_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await busy_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_inbox_claim_and_local_submit_are_serialized(self, tmp_path: Path) -> None:
        """An inbox claim and a local submit never produce two invokes.

        Gates ``claim_next`` so the inbox poll holds the prompt-submission
        gate; the local submission must wait, then observe the inbox chat
        turn's task and queue behind it — exactly one run starts.
        """
        history_root: Path = tmp_path / "history"
        inbox_store: SessionInboxStore = SessionInboxStore(history_root=history_root)
        session: MagicMock = self._mock_session_stub()
        session.history_root = history_root

        app: SloTUI = SloTUI(session=session, inbox_store=inbox_store)
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            message_id="message-1",
            session_id="session-1234",
            schedule_id="schedule-1",
            run_id="run-1",
            kind="scheduled_prompt",
            delivery_mode="chat_turn",
            title="Morning research",
            text="inbox turn text",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await inbox_store.enqueue(message=message)

            claim_entered: asyncio.Event = asyncio.Event()
            claim_release: asyncio.Event = asyncio.Event()
            original_claim_next = inbox_store.claim_next

            async def _gated_claim_next(*, session_id: str) -> Optional[SessionInboxMessageDAO]:
                claim_entered.set()
                await claim_release.wait()
                return await original_claim_next(session_id=session_id)

            # Tracks queue insertions; only reachable under the gate when busy.
            queue_calls: list[str] = []
            original_queue_prompt = app._queue_prompt

            async def _tracked_queue_prompt(*, text: str) -> None:
                queue_calls.append(text)
                await original_queue_prompt(text=text)

            with (
                patch.object(target=inbox_store, attribute="claim_next", new=_gated_claim_next),
                patch.object(target=app, attribute="_queue_prompt", new=_tracked_queue_prompt),
                patch.object(target=app, attribute="_run_prompt", new=AsyncMock()) as mock_run_prompt,
            ):
                poll_task: asyncio.Task[None] = asyncio.create_task(app._poll_session_inbox())
                await pump_until(pilot=pilot, predicate=lambda: claim_entered.is_set())

                submit_task: asyncio.Task[None] = asyncio.create_task(
                    app.on_prompt_input_submitted(PromptInput.Submitted(text="local prompt"))
                )
                for _ in range(3):
                    await pilot.pause()
                # The local submit handler is parked on the gate while the
                # inbox claim holds it: no queue mutation yet.
                assert queue_calls == []

                claim_release.set()
                await pump_until(pilot=pilot, predicate=lambda: submit_task.done())
                await pump_until(pilot=pilot, predicate=lambda: poll_task.done())

                # The inbox chat turn won the gate: exactly one run started.
                mock_run_prompt.assert_awaited_once_with(text="inbox turn text")
                # The local prompt queued behind it — never a second invoke.
                assert queue_calls == ["local prompt"]
                assert app._queued_prompt_text == "local prompt"
                queued_blocks: list[QueuedPromptBlock] = list(app.query(QueuedPromptBlock))
                assert len(queued_blocks) == 1
                assert queued_blocks[0].queued_text == "local prompt"
                assert await inbox_store.list_done(session_id="session-1234") == [message]


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


class TestFlattenedTranscriptCopy:
    """Copy-control deletion and uniform output padding (spec 72.a.3)."""

    def test_app_keeps_only_the_rendered_assistant_block_handler(self) -> None:
        """Verify Textual dispatch has only the retained assistant-block handler.

        A retired card copy-request handler would reappear as a second
        ``on_assistant_stream_block_*`` method, so the handler-name list is
        the behavioral guard that only the shared ``Rendered`` handler remains
        (spec 72.a.3).

        WHO: The spec-72.a.3 regression suite calls this against ``SloTUI``.
        """
        handler_names: list[str] = [
            name for name in dir(SloTUI) if name.startswith("on_assistant_stream_block_")
        ]

        assert handler_names == ["on_assistant_stream_block_rendered"]

    def test_four_transcript_blocks_share_transcript_output_pad(self) -> None:
        """All four message widgets use the uniform ``padding: 0 1`` convention."""
        message_blocks: list[type[Widget]] = [
            UserMessageBlock,
            AssistantStreamThinkingBlock,
            AssistantStreamBlock,
            ToolExecutionBlock,
        ]
        for block_class in message_blocks:
            block_rule: str = block_class.DEFAULT_CSS.split(f"{block_class.__name__} {{")[1].split("}")[0]
            assert "padding: 0 1;" in block_rule, f"{block_class.__name__} must use padding: 0 1"

    @pytest.mark.asyncio
    async def test_focused_assistant_answer_copy_stays_green(self) -> None:
        """Focus-copy of an answer block still lands the answer via the shared funnel."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)
        clipboard: list[str] = []
        app.copy_to_clipboard = lambda text: clipboard.append(text)  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()
            block.append_text(delta="assistant answer")
            app.set_focus(block)
            await pilot.pause()

            await app.action_copy_visible_text()

            assert clipboard == ["assistant answer"]


class TestSloTUISpinner:
    """``ThinkingSpinner`` lifecycle inside ``_run_prompt``."""

    @pytest.mark.asyncio
    async def test_visible_thinking_delta_keeps_spinner_and_mounts_a_thinking_block(self) -> None:
        """Visible thinking deltas keep the fixed spinner and mount a thinking segment block."""
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
                thinking_blocks: list[AssistantStreamThinkingBlock] = list(
                    app.query(selector=AssistantStreamThinkingBlock)
                )
                assert len(thinking_blocks) == 1
                assert thinking_blocks[0].thinking_text == "plan"
                # The answer has not streamed yet, so no answer block is mounted.
                assert list(app.query(selector=AssistantStreamBlock)) == []

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
        """Later assistant iterations render below tool output instead of rewriting the first block.

        Each thinking segment mounts as its own chronological child: the first
        iteration's thinking block, then the tool block, then the second
        iteration's thinking block.
        """

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

                thinking_blocks: list[AssistantStreamThinkingBlock] = list(
                    app.query(selector=AssistantStreamThinkingBlock)
                )
                assert len(thinking_blocks) == 2
                assert thinking_blocks[0].thinking_text == "first pass"
                assert thinking_blocks[1].thinking_text == "second pass"
                # Chronological children: thinking(t0) < tool < thinking(t1).
                assert app._transcript_content is not None
                children: list[Widget] = list(app._transcript_content.children)
                first_thinking_index: int = children.index(thinking_blocks[0])
                second_thinking_index: int = children.index(thinking_blocks[1])
                tool_index: int = next(
                    index for index, child in enumerate(children) if isinstance(child, ToolExecutionBlock)
                )
                assert first_thinking_index < tool_index < second_thinking_index
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


class TestPiRestylePilot:
    """Compositor-level proof for the Pi restyle CSS hooks (spec 72.a.5).

    Mounts the four finalized transcript surfaces, drives the tool block to
    both terminal states, and toggles the registered themes so a misspelled
    ``$``-variable or broken selector surfaces as a compositor exception
    rather than a silent visual defect.
    """

    @pytest.mark.asyncio
    async def test_tool_terminal_states_and_theme_toggle_render_without_compositor_error(self) -> None:
        """User/thinking/answer/tool surfaces paint under both registered themes."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            user_block = await app.mount_user_message_block(text="inspect the repo")
            thinking_block = await app.mount_thinking_block()
            thinking_block.append_thinking(delta="reasoning about the layout")
            answer_block = await app.mount_assistant_block()
            answer_block.append_text(delta="# Heading\n\nanswer body")
            done_block = await app.mount_tool_execution_block(tool_call_id="call_done", tool_name="read")
            done_block.update_result(tool_name="read", output="file body")
            error_block = await app.mount_tool_execution_block(tool_call_id="call_err", tool_name="bash")
            error_block.mark_incomplete()
            await pilot.pause()

            assert done_block.has_class("-done")
            assert not done_block.has_class("-error")
            assert error_block.has_class("-error")
            assert not error_block.has_class("-done")
            assert "assistant-thinking-body" in thinking_block._body.classes
            assert "user-message-body" in user_block._body.classes
            assert "assistant-answer-body" in answer_block._answer_body.classes

            app.theme = "slo-default"
            await pilot.pause()
            assert app._exception is None

            app.theme = "slo-dark"
            await pilot.pause()
            assert app._exception is None

    @pytest.mark.asyncio
    async def test_spinner_renders_glyph_and_text_children_under_both_themes(self) -> None:
        """The two-surface spinner composites without error on either theme."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await pilot.pause()

            assert app._spinner is not None
            assert str(app._spinner._glyph.content) in _BRAILLE_FRAMES
            assert str(app._spinner._text.content).endswith("…")

            app.theme = "slo-default"
            await pilot.pause()
            assert app._exception is None
            await app._unmount_spinner()


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
        """Mount one user, one thinking (with reasoning), one tool block."""
        user = await app.mount_user_message_block(text="line one\nhidden second line")
        thinking = await app.mount_thinking_block()
        thinking.set_thinking(content="reasoning text")
        tool = await app.mount_tool_execution_block(tool_call_id="tc", tool_name="bash")
        tool.update_tool_call(tool_input={"command": "ls"})
        tool.update_result(tool_name="bash", output="out")
        return user, thinking, tool

    @pytest.mark.asyncio
    async def test_ctrl_o_cycles_natural_expand_collapse(self) -> None:
        """First Ctrl+O expands all; second collapses all; third expands again."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            user, thinking, tool = await self._mounted_blocks(app=app)
            await pilot.pause()

            # Natural default: user full, reasoning visible, tool collapsed.
            assert app._global_expand_all is None
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, True, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is True
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, True, True)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is False
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, False, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app._global_expand_all is True
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, True, True)

    @pytest.mark.asyncio
    async def test_new_block_keeps_user_expanded_but_collapses_assistant_state(self) -> None:
        """Collapse-all does not affect user blocks but still applies to thinking blocks."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await self._mounted_blocks(app=app)
            await app.action_toggle_expandable_details()  # expand all
            await app.action_toggle_expandable_details()  # collapse all
            await pilot.pause()

            new_user = await app.mount_user_message_block(text="fresh\nmultiline")
            new_thinking = await app.mount_thinking_block()
            new_thinking.set_thinking(content="fresh reasoning")
            await pilot.pause()

            assert new_user._expanded is True
            assert new_thinking._body.display is False

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

    @pytest.mark.asyncio
    async def test_new_thinking_block_respects_expand_all_state(self) -> None:
        """A thinking block mounted after expand-all inherits the expanded state."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await self._mounted_blocks(app=app)
            await app.action_toggle_expandable_details()  # expand all
            await pilot.pause()

            new_thinking = await app.mount_thinking_block()
            new_thinking.set_thinking(content="fresh reasoning")
            assert new_thinking._body.display is True

    @pytest.mark.asyncio
    async def test_answer_block_is_unaffected_by_the_global_toggle(self) -> None:
        """The answer-only block owns no expandable region and is skipped by the sweep."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            answer = await app.mount_assistant_block()
            answer.set_answer(content="the answer")
            await app.action_toggle_expandable_details()  # expand all
            await app.action_toggle_expandable_details()  # collapse all
            await pilot.pause()

            assert answer._answer_body.display is True


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


class TestQueuedPromptAnchoring:
    """Input-adjacent anchoring for ``QueuedPromptBlock`` (spec 72 review §8).

    The block mounts into ``#chat-shell`` directly above ``PromptInput`` — it is
    never a transcript child, so transcript window eviction can never reach it
    and it carries no liveness classification in ``_is_block_live``.
    """

    def _build_app(self) -> SloTUI:
        """Build a ``SloTUI`` for queued-prompt anchoring tests.

        Returns:
            SloTUI: App ready for ``run_test``.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        return SloTUI(session=session)

    @pytest.mark.asyncio
    async def test_queued_prompt_block_mounts_above_input_outside_the_transcript(self) -> None:
        """The held block is a ``#chat-shell`` child immediately before ``PromptInput``."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            await app._queue_prompt(text="held prompt")
            block: Optional[QueuedPromptBlock] = app._queued_prompt_block
            assert block is not None
            assert app._transcript_content is not None
            chat_shell: Widget = app.query_one("#chat-shell")
            assert block.parent is chat_shell
            assert block not in app._transcript_content.children
            shell_children: list[Widget] = list(chat_shell.children)
            assert shell_children.index(block) == shell_children.index(prompt_input) - 1

    @pytest.mark.asyncio
    async def test_anchored_block_cannot_be_evicted_by_the_transcript_window(self) -> None:
        """An over-window eviction pass leaves the anchored block mounted above the input.

        The block is not a transcript child, so the transcript window's
        eviction candidates never include it — the old ``_is_block_live``
        guard that protected it from eviction is gone precisely because
        eviction can no longer reach it. The window is overflowed by one
        because eviction starts only ABOVE ``TRANSCRIPT_WINDOW_SIZE``; the
        hidden-count assertion proves the pass genuinely ran and still could
        not reach the anchored block.
        """
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            # Clear any startup adapter lines so the count is deterministic.
            await app.action_clear()
            await app._queue_prompt(text="held prompt")
            block: Optional[QueuedPromptBlock] = app._queued_prompt_block
            assert block is not None
            # Overflow the window by one: eviction starts only above the threshold.
            for _ in range(TRANSCRIPT_WINDOW_SIZE + 1):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The pass provably ran: exactly one settled block was evicted...
            assert app._hidden_block_count == 1
            chat_shell: Widget = app.query_one("#chat-shell")
            # ...and the anchored block was never an eviction candidate.
            assert block in chat_shell.children
            assert block not in app._transcript_content.children

    @pytest.mark.asyncio
    async def test_clear_detaches_the_anchored_block(self) -> None:
        """``/clear`` removes the anchored block itself, not just its slot reference."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._queue_prompt(text="held prompt")
            block: Optional[QueuedPromptBlock] = app._queued_prompt_block
            assert block is not None
            chat_shell: Widget = app.query_one("#chat-shell")
            assert block in chat_shell.children

            await app.action_clear()
            await pilot.pause()

            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            assert block not in chat_shell.children
            assert list(app.query(QueuedPromptBlock)) == []


class TestThinkingBlockLiveness:
    """Window liveness classification for ``AssistantStreamThinkingBlock`` (spec 72.a.2)."""

    def _build_app(self) -> SloTUI:
        """Build a ``SloTUI`` for thinking-liveness tests.

        Returns:
            SloTUI: App ready for ``run_test``.
        """
        session: SloAgentSession = _build_session(responses=[AIMessage(content="unused")])
        return SloTUI(session=session)

    @pytest.mark.asyncio
    async def test_window_never_evicts_an_unsealed_thinking_block(self) -> None:
        """An unsealed thinking segment placed first is never evicted."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            live_block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
            assert live_block.finalized is False
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert live_block in app._transcript_content.children

    @pytest.mark.asyncio
    async def test_window_evicts_a_sealed_thinking_block(self) -> None:
        """A sealed thinking segment is settled and evictable."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app.action_clear()
            sealed_block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
            sealed_block.set_thinking(content="done reasoning")
            sealed_block.seal()
            assert sealed_block.finalized is True
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert sealed_block not in app._transcript_content.children

    @pytest.mark.asyncio
    async def test_contentless_thinking_end_keeps_segment_mounted_through_window_until_repair(
        self,
    ) -> None:
        """A contentless end leaves its segment live: a window pass must not evict it before the repair.

        Regression: a contentless ``thinking_end`` that sealed its segment made
        the block evictable, so a window pass removed it before the normalizer's
        content-bearing repair arrived and the repair updated only the orphaned
        widget (``evicted=True``, ``visible_repair=False``).
        """
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app._projector.project(
                event=AgentStreamEventDAO(
                    kind="thinking_delta",
                    delta="plan",
                    iteration=0,
                    block_id="thinking:0:0",
                ),
            )
            await pilot.pause()
            thinking_blocks: list[AssistantStreamThinkingBlock] = list(
                app._transcript_content.query(AssistantStreamThinkingBlock)
            )
            assert len(thinking_blocks) == 1
            segment: AssistantStreamThinkingBlock = thinking_blocks[0]

            # The normalizer's implicit contentless close: the segment must stay open.
            await app._projector.project(
                event=AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=0,
                    block_id="thinking:0:0",
                ),
            )
            assert segment.finalized is False

            # Drive a genuine window pass over the open segment.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert app._hidden_block_count > 0
            assert segment in app._transcript_content.children

            # The repair end lands on the still-mounted, visible segment.
            await app._projector.project(
                event=AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=0,
                    block_id="thinking:0:0",
                    content="plan files",
                ),
            )
            await pilot.pause()
            assert segment in app._transcript_content.children
            assert segment.thinking_text == "plan files"
            assert segment.finalized is True

    @pytest.mark.asyncio
    async def test_mount_thinking_block_enforces_the_transcript_window(self) -> None:
        """Mounting over-window sealed thinking blocks caps the child count."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            await app.action_clear()
            extra: int = 5
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
                block.seal()
            for _ in range(5):
                await pilot.pause()
            non_summary: int = len(
                [c for c in app._transcript_content.children if c is not app._earlier_summary]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app._hidden_block_count == extra

    @pytest.mark.asyncio
    async def test_thinking_flush_keeps_follow_mode_when_viewport_was_at_bottom(self) -> None:
        """A thinking timer flush re-pins the viewport through the shared Rendered handler."""
        app: SloTUI = self._build_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for index in range(40):
                app._write_adapter_line(content=f"line {index}", classes="tool-result")
            await pilot.pause()

            assert app._transcript_scroll is not None
            app._transcript_scroll.scroll_end(animate=False)
            await pump_until(pilot=pilot, predicate=app._transcript_is_at_bottom)
            assert app._transcript_is_at_bottom()

            thinking_block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
            thinking_block.append_thinking(delta="streamed reasoning")
            scroll = app._transcript_scroll
            await pump_until(
                pilot=pilot,
                predicate=lambda: (scroll.max_scroll_y - scroll.scroll_y) <= 1.0,
            )

            assert (scroll.max_scroll_y - scroll.scroll_y) <= 1.0


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

                thinking_blocks: list[AssistantStreamThinkingBlock] = list(
                    app.query(selector=AssistantStreamThinkingBlock)
                )
                assert len(thinking_blocks) >= 2, (
                    "scripted turn did not drive multiple outer-loop iterations; "
                    f"mounted {len(thinking_blocks)} thinking blocks"
                )

                # LOAD-BEARING: D1/D2 proof — the terminal sweep sealed every
                # thinking segment this run mounted, so none report live.
                for index, block in enumerate(thinking_blocks):
                    assert block.finalized is True, (
                        f"thinking block {index} of {len(thinking_blocks)} still "
                        "reports itself live after the run terminated"
                    )
                answer_blocks: list[AssistantStreamBlock] = list(app.query(selector=AssistantStreamBlock))
                assert len(answer_blocks) >= 1
                for index, answer_block in enumerate(answer_blocks):
                    assert answer_block.finalized is True, (
                        f"assistant block {index} of {len(answer_blocks)} still "
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
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
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
        """A stranded live viewport shows the submitted user turn and remains bottom-pinned while streaming.

        The tail patch is mandatory beside the window patch (KB
        ``transcript-window-liveness``): with the production tail of 10 above
        the patched window of 5, enforcement would converge at ~10 children
        and the transcript could never overflow the restored full-height
        viewport. Tail 25 lets real evictions run while 40 written lines keep
        enough mounted rows to scroll away from the bottom.
        """
        app: SloTUI = self._build_history_app(entries=[])
        with (
            patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.app.TRANSCRIPT_PROTECTED_TAIL_SIZE", 25),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                for index in range(40):
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
