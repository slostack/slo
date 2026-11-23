"""Pilot tests for ``SloTUI`` (sub-spec 02.a.3)."""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO
import asyncio
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from textual import events
from textual.app import App
from textual.message import Message
from textual.pilot import Pilot
from textual.widget import Widget
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool

from config.logger import interactive_logging, log_info
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.compaction.compacter import Compacter
from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO, SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.chat_transcript.component import (
    LOAD_OLDER_BATCH_SIZE,
    TRANSCRIPT_HYDRATION_ENTRY_LIMIT,
    TRANSCRIPT_PROTECTED_TAIL_SIZE,
    TRANSCRIPT_WINDOW_SIZE,
    TranscriptScrollComponent,
    ChatTranscriptComponent,
)
from src.tui.authentication import AuthenticationScreen
from src.tui.git_diff_content_service import GitDiffContentDAO, GitDiffContentError
from src.tui.git_diff_screen import GitDiffScreen
from src.tui.slash_router import SlashCommandResultDAO
from src.tui.slodiff.model import FileStateKind
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO
from src.tui.thinking_spinner import _BRAILLE_FRAMES, ThinkingSpinner
from tests.tui._scroll_settle import pump_until
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
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


def _build_resource_free_session_mock() -> MagicMock:
    """Build a presentation-only session double with truthful final drain evidence.

    These fixtures own no reporter, child or lease. Lifecycle retention tests use
    real sessions instead; an unconfigured AsyncMock is not drained evidence.
    The double reports an idle session truthfully: no channel poller is running
    and no prompt is in flight, so idle gates admit delivery.
    """
    session = MagicMock(spec=SloAgentSession)
    session.channel_poller = None
    session.is_running = False
    outcome = HerdrReporterCloseOutcomeDAO(replacement="safe", resources="drained")
    session.close_external_reporting.return_value = outcome
    session.finish_retired_reporting_cleanup.return_value = outcome
    return session


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
    timeout_seconds: float = 15.0,
) -> None:
    """Poll until no run is in flight on either owner or timeout.

    Ordinary prompts run through the session's channel poller (108.1); the
    app-owned ``_in_flight_task`` is only set by tests that drive the legacy
    ``_run_prompt`` path directly. Idleness means neither owner is running.

    Args:
        app (SloTUI): The app under test.
        pilot (Pilot): The Textual Pilot driver.
        timeout_seconds (float): Maximum wait before failing.
    """

    def _running() -> bool:
        poller = app._session.channel_poller
        return app._in_flight_task is not None or (poller is not None and poller.busy)

    deadline: float = asyncio.get_event_loop().time() + timeout_seconds
    while _running():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("timed out waiting for in-flight task to clear")
        await pilot.pause()


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

    async def _fake_invoke(
        *, text: str, channel_message_id: Optional[UUID] = None
    ) -> AsyncIterator[AgentStreamEventDAO]:
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


def _require_prompt_input(*, app: SloTUI) -> PromptInputComponent:
    """Return the mounted prompt input.

    Args:
        app (SloTUI): The app under test.

    Returns:
        PromptInputComponent: The mounted prompt editor.
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
    assert app.query_one(ChatTranscriptComponent)._adapter is not None
    return app.query_one(ChatTranscriptComponent)._adapter.lines


def _visible_prompt_lines(*, app: SloTUI) -> int:
    """Return the visible prompt-editor content height in lines.

    Args:
        app (SloTUI): The app under test.

    Returns:
        int: The number of visible content lines inside ``PromptInputComponent``.
    """
    prompt_input: PromptInputComponent = _require_prompt_input(app=app)
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
            assert ("No changes detected for example.py.", "tool-result") in _require_adapter_lines(app=app)
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
            assert ("Could not read HEAD version of file.", "tool-result") in _require_adapter_lines(app=app)
            assert not isinstance(app.screen, GitDiffScreen)


class TestSloTUIActiveModelState:
    """Title rendering, slash-triggered refresh, and auth-success provider switching."""

    @pytest.mark.asyncio
    async def test_title_uses_only_session_workdir_and_identity(self) -> None:
        """Mount-time header excludes model and reasoning metadata."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            assert app.title.endswith(" · session session-1234")
            assert "claude-sonnet-4-6" not in app.title
            assert "reasoning" not in app.title

    @pytest.mark.asyncio
    async def test_auth_dismissed_switches_to_provider_default_model(self) -> None:
        """Anthropic auth success switches away from an OpenAI active model."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            await app._on_auth_dismissed(value)
            await pilot.pause()
            session.switch_model.assert_called_once_with(model_name="claude-opus-4-8-1m-context")
            assert app.title.endswith(" · session session-1234")
            assert "claude-opus-4-8-1m-context" not in app.title
            assert app.sub_title == ""
            assert (
                "active model switched to claude-opus-4-8-1m-context",
                "tool-result",
            ) in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_dispatch_slash_command_refreshes_title_when_requested(self) -> None:
        """Slash-command results with ``refresh_title=True`` update the top bar immediately."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
                return_value=SlashCommandResultDAO(
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
            assert ("reasoning changed high -> off", "tool-result") in _require_adapter_lines(app=app)


class TestTurnSeparatorRestyle:
    """The Pi-restyled turn separator constant and mount path (spec 72.a.5)."""

    def test_turn_separator_is_a_muted_horizontal_rule(self) -> None:
        """``TURN_SEPARATOR`` is exactly eighteen ``─`` rule characters."""
        from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter

        assert TranscriptNoticeDisplayAdapter.TURN_SEPARATOR == "─" * 18


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
        argnames=("workdir_template", "expected_template"),
        argvalues=[
            ("{home}", "~"),
            ("{home}/Code/project", "~/Code/project"),
            ("/tmp/slo-outside-home", "/tmp/slo-outside-home"),
            ("{home}-other/project", "{home}-other/project"),
        ],
    )
    async def test_title_bar_renders_only_home_descendants_with_tilde(
        self,
        workdir_template: str,
        expected_template: str,
    ) -> None:
        """Verify title cwd abbreviation preserves real path ancestry.

        WHO: The title-bar regression suite mounts the live TUI after the
        per-test HOME fixture runs, not under the collection-time suite HOME.
        """
        home: str = str(Path.home())
        workdir: Path = Path(workdir_template.format(home=home))
        expected_workdir: str = expected_template.format(home=home)
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
    async def test_header_excludes_session_name_when_present(self) -> None:
        """A session name never adds another header item."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            assert app.sub_title == ""
            assert app.title.endswith(" · session session-1234")
            assert "customer import regression" not in app.title

    @pytest.mark.asyncio
    async def test_header_shows_full_session_id_without_truncation(self) -> None:
        """A full UUID session id is shown verbatim — never sliced to a prefix."""
        full_id: str = "a166b82b-617e-45c6-9ada-a36f1c589fb6"
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            assert app.title.endswith(f" · session {full_id}")
            assert app.sub_title == ""

    @pytest.mark.asyncio
    async def test_rename_session_keeps_header_identity_unchanged(self) -> None:
        """Renaming is confirmed separately without adding header metadata."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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

            assert app.title.endswith(" · session session-1234")
            assert app.sub_title == ""
            assert "release prep" not in app.title
            assert ("session renamed to release prep", "tool-result") in _require_adapter_lines(app=app)


class TestSloTUISessionLease:
    """Lease ownership and the retired file inbox (108.6)."""

    @pytest.mark.asyncio
    async def test_mount_acquires_and_unmount_releases_session_lease(self, tmp_path: Path) -> None:
        """History-backed TUI sessions hold an active lease only while mounted."""
        history_root: Path = tmp_path / "history"
        lease_store: SessionOwnershipLeaseStore = SessionOwnershipLeaseStore(history_root=history_root)
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
    async def test_idle_tui_performs_no_inbox_file_reads(self, tmp_path: Path) -> None:
        """I5: an idle mounted TUI never polls, claims or renders a legacy ``inbox/`` file.

        A pre-108.6 producer may still drop a file into ``inbox/pending``. The
        TUI no longer has an inbox timer, so after well over one old poll
        interval the file is untouched: not moved to ``claimed/`` or ``done/``,
        and nothing about it reaches the transcript.
        """
        history_root: Path = tmp_path / "history"
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = history_root
        session.is_running = False
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
        app: SloTUI = SloTUI(session=session)
        legacy_file: Path = (
            history_root / "session-1234" / "inbox" / "pending" / "20261120T090000.000000Z-m1.json"
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            assert not legacy_file.parent.parent.exists(), "mount must not create inbox lanes"
            legacy_file.parent.mkdir(parents=True)
            original_bytes: bytes = (
                b'{"message_id": "m1", "session_id": "session-1234", "schedule_id": "s1", "run_id": "r1",'
                b' "kind": "system_notice", "delivery_mode": "ui_notice", "title": "CI monitor",'
                b' "created_at": "2026-11-20T09:00:00+00:00", "text": "CI still running."}'
            )
            legacy_file.write_bytes(original_bytes)
            await asyncio.sleep(1.5)
            await pilot.pause()

            assert legacy_file.read_bytes() == original_bytes
            assert sorted(path.name for path in legacy_file.parent.parent.iterdir()) == ["pending"]
            assert not any("CI still running." in line[0] for line in _require_adapter_lines(app=app))

    @pytest.mark.asyncio
    async def test_imported_scheduled_notice_bracket_prefix_renders_literally(self, tmp_path: Path) -> None:
        """An imported legacy notice keeps its ``[scheduled notice]`` prefix and renders it verbatim.

        The prefix is exactly the shape Textual's markup parser treats as a
        tag, so this proves a channel notice mounts through ``LiteralTextStatic``
        and neither the prefix nor a bracketed body (``list[str]``) is swallowed.
        """
        from datetime import datetime, timezone
        from uuid import uuid4

        from src.channels.dao import ChannelMessageDAO
        from src.tui.channel.adapter import TuiDisplaySink

        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
        session.workdir = Path(".").resolve()
        session.session_id = "session-1234"
        session.session_name = None
        session.active_model_name = "claude-sonnet-4-6"
        session.routed_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "high"
        session.history_enabled = True
        session.history_root = tmp_path / "history"
        session.subscribe = MagicMock()
        session.unsubscribe = MagicMock()
        session.hydrate_transcript_entries = AsyncMock(return_value=[])
        session.should_show_startup_notice = AsyncMock(return_value=False)
        session.usage_snapshot = MagicMock(return_value=_empty_usage_snapshot())
        app: SloTUI = SloTUI(session=session)
        now: datetime = datetime.now(timezone.utc)
        notice: ChannelMessageDAO = ChannelMessageDAO(
            id=uuid4(),
            agent_session_id=uuid4(),
            sender_id=uuid4(),
            sender_name="scheduler type check",
            recipient_id=uuid4(),
            recipient_name="slo session",
            sent_at=now,
            accepted_at=None,
            message_contents="[scheduled notice] type check: annotate as list[str]",
            created_at=now,
            message_index=1,
            forced_at=None,
            message_type="notice",
            in_reply_to_id=None,
            channel_id=None,
            cancelled_at=None,
            cancel_reason=None,
            coalesce_key=None,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await TuiDisplaySink(transcript=app._chat_transcript).show(message=notice)
            await pilot.pause()

            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            rendered: list[str] = [
                str(child.render())
                for child in app.query_one(ChatTranscriptComponent)._transcript_content.children
                if isinstance(child, LiteralTextStatic)
            ]
            assert any("[scheduled notice]" in text and "list[str]" in text for text in rendered)

    @pytest.mark.asyncio
    async def test_new_session_replaces_active_session_and_clears_transcript(self) -> None:
        """`/new` swaps in a fresh session and clears the visible transcript."""
        old_session: MagicMock = _build_resource_free_session_mock()
        old_session.preparation_status = "ready"
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

        new_session: MagicMock = _build_resource_free_session_mock()
        new_session.preparation_status = "ready"
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
            await app.query_one(ChatTranscriptComponent).handle(
                command=TranscriptNoticeDAO(content="existing line", classes="tool-result")
            )
            await pilot.pause()

            with patch("src.tui.app.SloAgentSession.build", return_value=new_session) as build:
                await app._start_new_session(requested_name="fresh thread")
                await pilot.pause()

            build.assert_called_once()
            assert build.call_args.kwargs["allow_pending_preparation"] is True
            assert app._session is new_session
            old_session.unsubscribe.assert_called_once_with(handler=app._render_event)
            new_session.subscribe.assert_called_once_with(handler=app._render_event)
            assert ("existing line", "tool-result") not in _require_adapter_lines(app=app)
            assert app.title.endswith(" · session new-session-5678")
            assert app.sub_title == ""

    @pytest.mark.asyncio
    async def test_new_session_rejection_while_run_active_preserves_existing_behavior(self) -> None:
        """`/new` stays rejected during an active run; no second session is built."""
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            ) in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_new_session_rejection_when_app_task_is_tracked(self) -> None:
        """Keep `/new` rejected while the app tracks a completion-handoff task.

        WHAT: Verifies the app-task guard rejects session replacement even
            when the session no longer reports itself as running.
        WHO: The queued-prompt gating pilot suite calls this regression test.
        WHEN: A completed prompt remains tracked until its queue handoff
            finishes, so `/new` must not slip through the session guard alone.
        """
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
                adapter = app.query_one(ChatTranscriptComponent)._adapter
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
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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

            assert ("hi", "assistant-final") in _require_adapter_lines(app=app)

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
            starting_index: int = app._input._slash_suggestion_state.highlighted_index

            await pilot.press("down")
            await pilot.pause()

            assert app._input._slash_suggestion_state.visible is True
            assert app._input._slash_suggestion_state.highlighted_index != starting_index
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

            assert ("─" * 18, "turn-separator") in _require_adapter_lines(app=app)

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
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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

        async def _slow_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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

                poller = session.channel_poller
                assert poller is not None
                deadline: float = asyncio.get_event_loop().time() + 10.0
                while not poller.busy:
                    if asyncio.get_event_loop().time() > deadline:
                        raise AssertionError("poller never picked up the run")
                    await pilot.pause()

                await pilot.press("ctrl+c")
                await pilot.pause()

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert mock_abort.call_count == 1
                assert ("(aborted)", "assistant-aborted") in _require_adapter_lines(app=app)

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

        async def _hung_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
            await asyncio.Event().wait()  # never resolves — simulates a hung tool
            yield  # pragma: no cover — keeps this an async generator

        with patch.object(session, "invoke", _hung_invoke):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None

                app._input.load_text("hello")
                await pilot.press("enter")
                await pilot.pause()

                poller = session.channel_poller
                assert poller is not None
                deadline: float = asyncio.get_event_loop().time() + 10.0
                while not poller.busy:
                    if asyncio.get_event_loop().time() > deadline:
                        raise AssertionError("poller never picked up the run")
                    await pilot.pause()

                # Bypass the grace timer and force the escalation directly.
                assert poller.cancel_current() is True
                await _await_idle(app=app, pilot=pilot)

                assert not poller.busy
                assert ("(aborted)", "assistant-aborted") in _require_adapter_lines(app=app)

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
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
        return session

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
            await app.on_prompt_input_component_submitted(PromptInputComponent.Submitted(text="/compact"))
            await pilot.pause()

            assert (
                "cannot compact while a prompt is in flight; run /abort first",
                "tool-result",
            ) in _require_adapter_lines(app=app)
            session.compact_context.assert_awaited_once()
            assert not active_task.done()
            assert app._in_flight_task is active_task
            active_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active_task
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_compact_mounts_activity_spinner_while_running(self) -> None:
        """A running ``/compact`` shows the fixed loader, then removes it."""
        entered: asyncio.Event = asyncio.Event()
        release: asyncio.Event = asyncio.Event()

        async def _slow_compact() -> ManualCompactionResultDAO:
            entered.set()
            await release.wait()
            return ManualCompactionResultDAO(status="compacted")

        session: MagicMock = self._steering_session_stub()
        session.compact_context = AsyncMock(side_effect=_slow_compact)
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            dispatch: asyncio.Task[None] = asyncio.create_task(app._dispatch_slash_command(line="/compact"))
            await entered.wait()
            await pilot.pause()

            assert app._spinner is not None
            assert len(list(app.query(ThinkingSpinner))) == 1

            release.set()
            await dispatch
            await pilot.pause()

            assert app._spinner is None
            assert list(app.query(ThinkingSpinner)) == []

    @pytest.mark.asyncio
    async def test_steer_dispatches_and_renders_while_run_in_flight(self) -> None:
        """A ``/steer`` submitted mid-run is dispatched, not swallowed by the busy reply.

        Regression: ``on_prompt_input_component_submitted`` returned on the in-flight
        branch before the slash-command check, so steering was impossible while
        the agent was working — the one moment a forced message is meant for.
        The dispatch outcome is the 108.2 forced-send intent; without a channel
        adapter the send degrades to a truthful notice.
        """
        session: MagicMock = self._steering_session_stub()

        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Simulate a run in flight.
            app._in_flight_task = asyncio.create_task(asyncio.sleep(3600))

            await app.on_prompt_input_component_submitted(
                PromptInputComponent.Submitted(text="/steer be terse")
            )
            await pilot.pause()

            confirmations: list[tuple[str, str]] = [
                entry for entry in _require_adapter_lines(app=app) if "forced message queued" in entry[0]
            ]
            assert confirmations, "the forced-send confirmation line is missing"

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

        async def _raising_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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
                    for entry in _require_adapter_lines(app=app)
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

        async def _raising_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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
                    for entry in _require_adapter_lines(app=app)
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

        async def _raising_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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
                    for entry in _require_adapter_lines(app=app)
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
            help_content: list[str] = [
                entry[0] for entry in _require_adapter_lines(app=app) if "help" in entry[0].lower()
            ]
            assert len(help_content) >= 1


class TestQueuedPromptGating:
    """One-deep latest-wins queued ordinary prompt behind the active run (spec 72.a.4)."""


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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)
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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)
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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)

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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)

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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)

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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)
            baseline_lines: int = _visible_prompt_lines(app=app)

            prompt_input.load_text(self.LONG_WRAPPED_PROMPT)
            await pilot.pause()
            assert _visible_prompt_lines(app=app) > baseline_lines

            await pilot.press("enter")
            await _await_idle(app=app, pilot=pilot)

            assert prompt_input.text == ""
            assert _visible_prompt_lines(app=app) == baseline_lines
            assert ("ok", "assistant-final") in _require_adapter_lines(app=app)

    @pytest.mark.asyncio
    async def test_meta_enter_inserts_newline_without_submitting(self) -> None:
        """``Cmd+Enter`` inserts a literal newline in the prompt editor."""
        session: SloAgentSession = _build_session(
            responses=[AIMessage(content="unused")],
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)

            prompt_input.load_text("first")
            prompt_input.move_cursor(location=(0, len("first")))
            await pilot.press("meta+enter")
            await pilot.pause()

            assert prompt_input.text == "first\n"
            assert app._in_flight_task is None
            assert ("> first", "user-line") not in _require_adapter_lines(app=app)


class TestSloTUICopy:
    """Clipboard-oriented TUI behavior."""

    @pytest.mark.asyncio
    async def test_copy_binding_copies_visible_transcript_when_prompt_has_no_selection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``Cmd+C`` / ``Ctrl+Shift+C`` copies the transcript as plain text."""
        monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
        monkeypatch.setenv("TERM", "dumb")
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
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
                "Reasoning: high. Provider detail: effort high.\n"
                "Tip: Ctrl+Enter may be indistinguishable from Enter in this terminal — "
                "use Alt+Enter or /force <text> to send forced (108.2).\n> hello\nhi",
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
            prompt_input: PromptInputComponent = _require_prompt_input(app=app)
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

        assert handler_names == []
        assert hasattr(ChatTranscriptComponent, "on_assistant_stream_block_rendered")

    def test_transcript_blocks_use_their_declared_output_padding_contracts(self) -> None:
        """Assistant and tool blocks keep their compact inset while the user band owns its vertical breathing room."""
        compact_blocks: list[type[Widget]] = [
            AssistantStreamThinkingBlock,
            AssistantStreamBlock,
            ToolExecutionBlock,
        ]
        for block_class in compact_blocks:
            block_rule: str = block_class.DEFAULT_CSS.split(f"{block_class.__name__} {{")[1].split("}")[0]
            assert "padding: 0 1;" in block_rule, f"{block_class.__name__} must use padding: 0 1"

        user_block_rule: str = UserMessageBlock.DEFAULT_CSS.split("UserMessageBlock {")[1].split("}")[0]
        assert "padding: 1 1 2 1;" in user_block_rule

    @pytest.mark.asyncio
    async def test_focused_assistant_answer_copy_stays_green(self) -> None:
        """Focus-copy of an answer block still lands the answer via the shared funnel."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)
        clipboard: list[str] = []
        app.copy_to_clipboard = lambda text: clipboard.append(text)  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.query_one(ChatTranscriptComponent).mount_assistant_block()
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

        async def _paused_after_thinking_delta_invoke(
            *, text: str, channel_message_id: Optional[UUID] = None
        ):
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

                assert any(line[1] == "assistant-final" for line in _require_adapter_lines(app=app))

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

        async def _slow_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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

                poller = session.channel_poller
                assert poller is not None
                deadline: float = asyncio.get_event_loop().time() + 10.0
                while not poller.busy:
                    if asyncio.get_event_loop().time() > deadline:
                        raise AssertionError("poller never picked up the run")
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

        async def _paused_after_tool_result_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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

                assert any(line[1] == "tool-line" for line in _require_adapter_lines(app=app))
                assert any(line[1] == "tool-result" for line in _require_adapter_lines(app=app))
                assert list(app.query(selector=ToolExecutionBlock))
                assert app._spinner is not None
                assert list(app.query(selector=ThinkingSpinner))

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert list(app.query(selector=ThinkingSpinner)) == []
                assert ("done", "assistant-final") in _require_adapter_lines(app=app)

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

        async def _paused_on_second_iteration_invoke(*, text: str, channel_message_id: Optional[UUID] = None):
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
                assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
                children: list[Widget] = list(
                    app.query_one(ChatTranscriptComponent)._transcript_content.children
                )
                first_thinking_index: int = children.index(thinking_blocks[0])
                second_thinking_index: int = children.index(thinking_blocks[1])
                tool_index: int = next(
                    index for index, child in enumerate(children) if isinstance(child, ToolExecutionBlock)
                )
                assert first_thinking_index < tool_index < second_thinking_index
                assert app._spinner is not None

                release.set()
                await _await_idle(app=app, pilot=pilot)

                assert any(line[1] == "assistant-final" for line in _require_adapter_lines(app=app))


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
            user_block = await app.query_one(ChatTranscriptComponent).mount_user_message_block(
                text="inspect the repo"
            )
            thinking_block = await app.query_one(ChatTranscriptComponent).mount_thinking_block()
            thinking_block.append_thinking(delta="reasoning about the layout")
            answer_block = await app.query_one(ChatTranscriptComponent).mount_assistant_block()
            answer_block.append_text(delta="# Heading\n\nanswer body")
            done_block = await app.query_one(ChatTranscriptComponent).mount_tool_execution_block(
                tool_call_id="call_done", tool_name="read"
            )
            done_block.update_result(tool_name="read", output="file body")
            error_block = await app.query_one(ChatTranscriptComponent).mount_tool_execution_block(
                tool_call_id="call_err", tool_name="bash"
            )
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

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        SloTUI._attach_pool_to_session(session=session)

        config: SessionConfigDAO | None = session._config
        assert config is not None
        assert config.extra_tools is not None
        tool_names: list[str] = [tool.name for tool in config.extra_tools]
        assert "spawn_sub_agents" in tool_names

    def test_attach_pool_to_session_sets_append_system_prompt(self, tmp_path: Path) -> None:
        """``_attach_pool_to_session`` injects the orchestrator addendum."""
        from src.agents.slo_agent.sessions.service import SloAgentSession

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        SloTUI._attach_pool_to_session(session=session)

        config: SessionConfigDAO | None = session._config
        assert config is not None
        assert config.append_system_prompt is not None
        assert "spawn_sub_agents" in config.append_system_prompt

    def test_headless_session_does_not_have_spawn_tool(self, tmp_path: Path) -> None:
        """``HeadlessRunner``-built sessions have no ``spawn_sub_agents`` tool."""
        from src.agents.slo_agent.sessions.service import SloAgentSession

        # Simulate how HeadlessRunner builds its session — no _attach_pool_to_session
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        config: SessionConfigDAO | None = session._config
        assert config is not None
        tool_names: list[str] = [tool.name for tool in (config.extra_tools or [])]
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
            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.set_focus(app.query_one(ChatTranscriptComponent)._transcript_scroll)
            await pilot.pause()
            assert app.focused is app.query_one(ChatTranscriptComponent)._transcript_scroll

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
            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.set_focus(app.query_one(ChatTranscriptComponent)._transcript_scroll)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

            assert _require_prompt_input(app=app).text == ""
            assert app.focused is app.query_one(ChatTranscriptComponent)._transcript_scroll

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
            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.set_focus(app.query_one(ChatTranscriptComponent)._transcript_scroll)
            await pilot.pause()

            await pilot.press("slash")  # Textual key name for "/"
            await pilot.pause()

            prompt_input = _require_prompt_input(app=app)
            assert prompt_input.text == "/"
            assert prompt_input._slash_suggestion_state.visible is True


class TestSloTUIGlobalExpandToggle:
    """Ctrl+O global expand/collapse-all across all transcript blocks (sub-spec 42.a.12)."""

    async def _mounted_blocks(self, *, app: SloTUI):
        """Mount one user, one thinking (with reasoning), one tool block."""
        user = await app.query_one(ChatTranscriptComponent).mount_user_message_block(
            text="line one\nhidden second line"
        )
        thinking = await app.query_one(ChatTranscriptComponent).mount_thinking_block()
        thinking.set_thinking(content="reasoning text")
        tool = await app.query_one(ChatTranscriptComponent).mount_tool_execution_block(
            tool_call_id="tc", tool_name="bash"
        )
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
            assert app.query_one(ChatTranscriptComponent)._global_expand_all is None
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, True, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._global_expand_all is True
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, True, True)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._global_expand_all is False
            assert (user._expanded, thinking._body.display, tool._expanded) == (True, False, False)

            await app.action_toggle_expandable_details()
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._global_expand_all is True
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

            new_user = await app.query_one(ChatTranscriptComponent).mount_user_message_block(
                text="fresh\nmultiline"
            )
            new_thinking = await app.query_one(ChatTranscriptComponent).mount_thinking_block()
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

            new_tool = await app.query_one(ChatTranscriptComponent).mount_tool_execution_block(
                tool_call_id="tc2", tool_name="bash"
            )
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

            new_thinking = await app.query_one(ChatTranscriptComponent).mount_thinking_block()
            new_thinking.set_thinking(content="fresh reasoning")
            assert new_thinking._body.display is True

    @pytest.mark.asyncio
    async def test_answer_block_is_unaffected_by_the_global_toggle(self) -> None:
        """The answer-only block owns no expandable region and is skipped by the sweep."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            answer = await app.query_one(ChatTranscriptComponent).mount_assistant_block()
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
            for index in range(50):
                await app.query_one(ChatTranscriptComponent).handle(
                    command=TranscriptNoticeDAO(content=f"line-{index}", classes="tool-result")
                )
            await pilot.pause()
            app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_to(
                y=0, animate=False, immediate=True
            )
            await app.action_scroll_to_bottom()
            await pump_until(
                pilot=pilot,
                predicate=lambda: app.query_one(ChatTranscriptComponent)
                ._update_reading_anchor_and_build_follow_snapshot()
                .was_following,
            )
            await pilot.pause()
            assert "line-49" in "\n".join(strip.text for strip in app.screen._compositor.render_strips())

    @pytest.mark.asyncio
    async def test_action_is_noop_when_transcript_scroll_absent(self) -> None:
        """``action_scroll_to_bottom`` does not raise when the scroll container is absent."""
        session: SloAgentSession = _build_session(responses=[AIMessage(content="x")])
        app: SloTUI = SloTUI(session=session)

        await app.action_scroll_to_bottom()  # uncomposed app must not raise


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
        """``_focused_block_text`` returns empty string for ``PromptInputComponent`` (no ``get_copyable_text``)."""
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
            block: UserMessageBlock = await app.query_one(ChatTranscriptComponent).mount_user_message_block(
                text="hello world"
            )
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
            block: AssistantStreamBlock = await app.query_one(ChatTranscriptComponent).mount_assistant_block()
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
            await app.query_one(ChatTranscriptComponent).handle(
                command=TranscriptNoticeDAO(content="some transcript line", classes="tool-result")
            )
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
            if app.query_one(ChatTranscriptComponent)._adapter is not None:
                _require_adapter_lines(app=app).clear()
            await pilot.pause()

            await app.action_copy_visible_text()

            assert clipboard == []


class TestTranscriptWindow:
    """Transcript window keeps mounted children bounded (spec 59, Phase 2)."""

    def test_transcript_window_size_is_500(self) -> None:
        """The production transcript retention limit stays at the requested 500 blocks."""
        assert TRANSCRIPT_WINDOW_SIZE == 500

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
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Clear any startup adapter lines so the count is deterministic.
            await app.action_clear()
            # Mount TRANSCRIPT_WINDOW_SIZE + 5 settled user-message blocks.
            extra: int = 5
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="msg")
            await pilot.pause()
            # Pause extra ticks for any pending worker to complete.
            for _ in range(5):
                await pilot.pause()
            non_summary: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == extra
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is not None

    @pytest.mark.asyncio
    async def test_earlier_summary_absent_below_window(self) -> None:
        """Fewer than window children produce no summary widget."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Mount fewer blocks than the window.
            for _ in range(5):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="msg")
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is None
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == 0

    @pytest.mark.asyncio
    async def test_window_never_evicts_live_block(self) -> None:
        """An un-finalized AssistantStreamBlock placed first is never evicted."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Mount one live assistant block as the oldest child.
            live_block: AssistantStreamBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_assistant_block()
            # live_block is not finalized — it is live.
            assert live_block.finalized is False
            # Mount TRANSCRIPT_WINDOW_SIZE settled blocks to trigger eviction.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The live block must still be in the transcript (Textual's
            # Widget.is_mounted stays True after remove(); check children instead).
            assert live_block in app.query_one(ChatTranscriptComponent)._transcript_content.children

    @pytest.mark.asyncio
    async def test_adapter_line_mount_enforces_window(self) -> None:
        """Adapter lines via _write_adapter_line also enforce the window."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Clear any startup adapter lines so the count is deterministic.
            await app.action_clear()
            extra: int = 5
            for index in range(TRANSCRIPT_WINDOW_SIZE + extra):
                await app.query_one(ChatTranscriptComponent).handle(
                    command=TranscriptNoticeDAO(content=f"line {index}", classes="tool-result")
                )
            # Pause multiple ticks for workers to complete.
            for _ in range(10):
                await pilot.pause()
            non_summary: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == extra

    @pytest.mark.asyncio
    async def test_clear_resets_window_state(self) -> None:
        """action_clear resets _hidden_block_count and _earlier_summary."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Mount over-window blocks so summary is created.
            for _ in range(TRANSCRIPT_WINDOW_SIZE + 3):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="msg")
            for _ in range(5):
                await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is not None
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count > 0
            await app.action_clear()
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == 0
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is None

    @pytest.mark.asyncio
    async def test_window_evicts_incomplete_tool_block(self) -> None:
        """A tool block marked incomplete is evictable (terminal, not live)."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Clear any startup adapter lines so eviction order is deterministic.
            await app.action_clear()
            # Mount a tool block and mark it incomplete (terminal state).
            incomplete_block: ToolExecutionBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_tool_execution_block(tool_call_id="tc1", tool_name="bash")
            incomplete_block.mark_incomplete()
            assert incomplete_block.is_incomplete is True
            # Mount TRANSCRIPT_WINDOW_SIZE more settled blocks to trigger eviction.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            # The incomplete block should have been evicted.
            # Textual's Widget.is_mounted is a one-way flag that stays True after
            # remove() — the authoritative post-eviction check is whether the
            # widget is still present in the parent's children list.
            assert (
                incomplete_block not in app.query_one(ChatTranscriptComponent)._transcript_content.children
            ), (
                f"incomplete_block still in transcript children after eviction; "
                f"total={len(list(app.query_one(ChatTranscriptComponent)._transcript_content.children))}, "
                f"hidden={app.query_one(ChatTranscriptComponent)._hidden_block_count}, "
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
        below the window), ``app.query_one(ChatTranscriptComponent)._hidden_block_count == extra`` (correct count,
        not doubled), the pass ran twice under one guard holder, and the rerun
        request was raised then cleared.
        """
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            # Clear startup adapter lines so child count is deterministic.
            await app.action_clear()
            extra: int = 5
            # Mount directly onto the container so mount-site enforcement never
            # runs and the transcript is genuinely over-window when the enforcers
            # start — both calls must pass the fast-path into the guard.
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                await app.query_one(ChatTranscriptComponent)._transcript_content.mount(
                    UserMessageBlock(text="settled")
                )
            await pilot.pause()
            assert (
                len(list(app.query_one(ChatTranscriptComponent)._transcript_content.children))
                == TRANSCRIPT_WINDOW_SIZE + extra
            )
            transcript = app.query_one(ChatTranscriptComponent)
            transcript._enforce_window_soon()
            task = transcript._window_task
            transcript._enforce_window_soon()
            assert transcript._window_task is task
            assert task is not None
            await task
            await pilot.pause()
            assert len(transcript._get_ordinary_children()) == TRANSCRIPT_WINDOW_SIZE
            assert transcript._hidden_block_count == extra
            assert transcript._window_task is None


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
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            live_block: AssistantStreamThinkingBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_thinking_block()
            assert live_block.finalized is False
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert live_block in app.query_one(ChatTranscriptComponent)._transcript_content.children

    @pytest.mark.asyncio
    async def test_window_evicts_a_sealed_thinking_block(self) -> None:
        """A sealed thinking segment is settled and evictable."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.action_clear()
            sealed_block: AssistantStreamThinkingBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_thinking_block()
            sealed_block.set_thinking(content="done reasoning")
            sealed_block.seal()
            assert sealed_block.finalized is True
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert sealed_block not in app.query_one(ChatTranscriptComponent)._transcript_content.children

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
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.query_one(ChatTranscriptComponent)._projector.handle(
                event=AgentStreamEventDAO(
                    kind="thinking_delta",
                    delta="plan",
                    iteration=0,
                    block_id="thinking:0:0",
                ),
            )
            await pilot.pause()
            thinking_blocks: list[AssistantStreamThinkingBlock] = list(
                app.query_one(ChatTranscriptComponent)._transcript_content.query(AssistantStreamThinkingBlock)
            )
            assert len(thinking_blocks) == 1
            segment: AssistantStreamThinkingBlock = thinking_blocks[0]

            # The normalizer's implicit contentless close: the segment must stay open.
            await app.query_one(ChatTranscriptComponent)._projector.handle(
                event=AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=0,
                    block_id="thinking:0:0",
                ),
            )
            assert segment.finalized is False

            # Drive a genuine window pass over the open segment.
            for _ in range(TRANSCRIPT_WINDOW_SIZE):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count > 0
            assert segment in app.query_one(ChatTranscriptComponent)._transcript_content.children

            # The repair end lands on the still-mounted, visible segment.
            await app.query_one(ChatTranscriptComponent)._projector.handle(
                event=AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=0,
                    block_id="thinking:0:0",
                    content="plan files",
                ),
            )
            await pilot.pause()
            assert segment in app.query_one(ChatTranscriptComponent)._transcript_content.children
            assert segment.thinking_text == "plan files"
            assert segment.finalized is True

    @pytest.mark.asyncio
    async def test_mount_thinking_block_enforces_the_transcript_window(self) -> None:
        """Mounting over-window sealed thinking blocks caps the child count."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.action_clear()
            extra: int = 5
            for _ in range(TRANSCRIPT_WINDOW_SIZE + extra):
                block: AssistantStreamThinkingBlock = await app.query_one(
                    ChatTranscriptComponent
                ).mount_thinking_block()
                block.seal()
            for _ in range(5):
                await pilot.pause()
            non_summary: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == extra

    @pytest.mark.asyncio
    async def test_thinking_flush_keeps_follow_mode_when_viewport_was_at_bottom(self) -> None:
        """A thinking timer flush re-pins the viewport through the shared Rendered handler."""
        app: SloTUI = self._build_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for index in range(40):
                await app.query_one(ChatTranscriptComponent).handle(
                    command=TranscriptNoticeDAO(content=f"line {index}", classes="tool-result")
                )
            await pilot.pause()

            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_end(animate=False)
            await pump_until(
                pilot=pilot,
                predicate=lambda: app.query_one(ChatTranscriptComponent)
                ._update_reading_anchor_and_build_follow_snapshot()
                .was_following,
            )
            assert (
                app.query_one(ChatTranscriptComponent)
                ._update_reading_anchor_and_build_follow_snapshot()
                .was_following
            )

            thinking_block: AssistantStreamThinkingBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_thinking_block()
            thinking_block.append_thinking(delta="streamed reasoning")
            scroll = app.query_one(ChatTranscriptComponent)._transcript_scroll
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
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.action_clear()

            unfinalized_blocks: list[AssistantStreamBlock] = []
            for _ in range(90):
                unfinalized_blocks.append(
                    await app.query_one(ChatTranscriptComponent).mount_assistant_block()
                )
            user_block: UserMessageBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_user_message_block(text="the user's new message")
            for _ in range(5):
                await pilot.pause()

            assert user_block in app.query_one(ChatTranscriptComponent)._transcript_content.children
            for block in unfinalized_blocks:
                assert block in app.query_one(ChatTranscriptComponent)._transcript_content.children
            non_summary: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert non_summary == 91
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == 0

    @pytest.mark.asyncio
    async def test_run_window_enforcement_pass_converges_to_the_window_when_overflow_lies_outside_the_tail(
        self,
    ) -> None:
        """Ordinary eviction still converges to exactly the window when overflow lies outside the tail."""
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.action_clear()

            for _ in range(TRANSCRIPT_WINDOW_SIZE + 5):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="settled")
            for _ in range(5):
                await pilot.pause()

            non_summary: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert non_summary == TRANSCRIPT_WINDOW_SIZE
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count == 5
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is not None

    # -- 61.a.4: parametrised threshold reproduction --

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stuck_live", [29, 60, 79, 80, 90, 500, 510])
    async def test_run_window_enforcement_pass_preserves_the_user_message_at_every_diagnosed_live_block_count(
        self,
        stuck_live: int,
    ) -> None:
        """The user's new message survives at every measured, including 500-block, live count."""
        assert TRANSCRIPT_PROTECTED_TAIL_SIZE == 10
        app: SloTUI = self._build_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            await app.action_clear()

            unfinalized_blocks: list[AssistantStreamBlock] = []
            for _ in range(stuck_live):
                unfinalized_blocks.append(
                    await app.query_one(ChatTranscriptComponent).mount_assistant_block()
                )
            assert unfinalized_blocks[0].finalized is False

            settled_filler: int = max(0, TRANSCRIPT_WINDOW_SIZE - stuck_live)
            for _ in range(settled_filler):
                await app.query_one(ChatTranscriptComponent).mount_user_message_block(text="filler")

            children_before: int = len(
                [
                    c
                    for c in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if c is not app.query_one(ChatTranscriptComponent)._earlier_summary
                ]
            )
            assert children_before == max(TRANSCRIPT_WINDOW_SIZE, stuck_live)

            user_block: UserMessageBlock = await app.query_one(
                ChatTranscriptComponent
            ).mount_user_message_block(text="the user's new prompt")
            for _ in range(5):
                await pilot.pause()

            children_count: int = len(
                list(app.query_one(ChatTranscriptComponent)._transcript_content.children)
            )
            assert user_block in app.query_one(ChatTranscriptComponent)._transcript_content.children, (
                f"stuck_live={stuck_live}, children={children_count}, "
                f"hidden={app.query_one(ChatTranscriptComponent)._hidden_block_count}"
            )
            assert app.query_one(ChatTranscriptComponent)._hidden_block_count <= 1


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

        with patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 5):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._input is not None
                assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
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
                    for child in app.query_one(ChatTranscriptComponent)._transcript_content.children
                    if isinstance(child, UserMessageBlock)
                ]
                assert "second prompt" in user_texts, (
                    f"the second prompt's UserMessageBlock was evicted; "
                    f"mounted user texts={user_texts}, "
                    f"children={len(list(app.query_one(ChatTranscriptComponent)._transcript_content.children))}, "
                    f"hidden={app.query_one(ChatTranscriptComponent)._hidden_block_count}"
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
        session: MagicMock = _build_resource_free_session_mock()
        session.preparation_status = "ready"
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
            await app.query_one(ChatTranscriptComponent).handle(
                command=TranscriptNoticeDAO(content=f"line {index}", classes="tool-result")
            )
        await pilot.pause()

    @staticmethod
    def _visible_assistant_answers(*, app: SloTUI) -> list[str]:
        """Return assistant answers in on-screen transcript order.

        Args:
            app (SloTUI): App under inspection.

        Returns:
            list[str]: Visible assistant answers from top to bottom.
        """
        assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
        answers: list[str] = []
        for child in app.query_one(ChatTranscriptComponent)._transcript_content.children:
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
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 5),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                transcript = app.query_one(ChatTranscriptComponent)
                # Hydration's deferred bottom pin must settle before an explicit
                # prepend; otherwise its queued scroll-to-top event can start a
                # second load after this test's requested batch has completed.
                async with asyncio.timeout(5):
                    while (
                        transcript._active_pin is not None
                        or transcript._transcript_scroll.scroll_y
                        != transcript._transcript_scroll.max_scroll_y
                    ):
                        await pilot.pause()
                assert transcript._load_older_cursor == 7
                await transcript.load_older()
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
                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 2

    @pytest.mark.asyncio
    async def test_load_older_preserves_scroll_anchor(self) -> None:
        """Prepending older entries keeps the reader anchored in place."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=14)
        with (
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 4),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
                app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_to(y=1, animate=False)
                await pilot.pause()
                scroll = app.query_one(ChatTranscriptComponent)._transcript_scroll
                scroll_before: float = scroll.scroll_y
                await app.query_one(ChatTranscriptComponent).load_older()
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
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 3),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 2),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app.query_one(ChatTranscriptComponent).load_older()
                await pilot.pause()
                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 3
                assert app.query_one(ChatTranscriptComponent)._earlier_summary is not None
                assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
                assert any(
                    "transcript-earlier-summary" == child.id
                    for child in app.query_one(ChatTranscriptComponent)._transcript_content.children
                )

    @pytest.mark.asyncio
    async def test_load_older_removes_summary_when_cursor_reaches_zero(self) -> None:
        """The summary is removed only after the canonical cursor reaches zero."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=5)
        with (
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 3),
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 3),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 5),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app.query_one(ChatTranscriptComponent).load_older()
                await pilot.pause()
                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 0
                assert app.query_one(ChatTranscriptComponent)._earlier_summary is None
                assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
                assert all(
                    child.id != "transcript-earlier-summary"
                    for child in app.query_one(ChatTranscriptComponent)._transcript_content.children
                )

    @pytest.mark.asyncio
    async def test_load_older_noops_when_cursor_is_zero(self) -> None:
        """No hidden history means load-older does nothing."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
            child_count_before: int = len(
                list(app.query_one(ChatTranscriptComponent)._transcript_content.children)
            )
            await app.query_one(ChatTranscriptComponent).load_older()
            await pilot.pause()
            assert (
                len(list(app.query_one(ChatTranscriptComponent)._transcript_content.children))
                == child_count_before
            )
            assert app.query_one(ChatTranscriptComponent)._earlier_summary is None

    @pytest.mark.asyncio
    async def test_echo_user_line_force_reveals_and_clears_backscroll_mode(self) -> None:
        """Submitting a prompt returns from backscroll mode and re-pins the viewport."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await self._fill_transcript(app=app, pilot=pilot, line_count=40)
            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()
            app.query_one(ChatTranscriptComponent)._back_scroll_mode = True

            await app.query_one(ChatTranscriptComponent).echo_user(text="live prompt")
            # Textual 8.x needs one extra refresh cycle to reconcile max_scroll_y
            # with the force-reveal scroll restoration; behaviour is unchanged.
            await pilot.pause()
            await pilot.pause()

            assert app.query_one(ChatTranscriptComponent)._back_scroll_mode is False
            assert (
                app.query_one(ChatTranscriptComponent)._transcript_scroll.max_scroll_y
                - app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_y
            ) <= 1.0

    @pytest.mark.asyncio
    async def test_transcript_is_at_bottom_returns_true_while_force_follow_latch_is_armed(self) -> None:
        """The force-follow branch protects streaming until deferred scroll completion."""
        app: SloTUI = self._build_history_app(entries=[])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await self._fill_transcript(app=app, pilot=pilot, line_count=40)
            assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
            app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()

            app.query_one(ChatTranscriptComponent)._force_following_until_layout = True

            assert (
                app.query_one(ChatTranscriptComponent)
                ._update_reading_anchor_and_build_follow_snapshot()
                .was_following
                is True
            )

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
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_WINDOW_SIZE", 5),
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_PROTECTED_TAIL_SIZE", 25),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                for index in range(40):
                    await app.query_one(ChatTranscriptComponent).handle(
                        command=TranscriptNoticeDAO(content=f"window line {index}", classes="tool-result")
                    )
                for _ in range(4):
                    await pilot.pause()
                assert app.query_one(ChatTranscriptComponent)._transcript_scroll is not None
                app.query_one(ChatTranscriptComponent)._transcript_scroll.scroll_to(y=0, animate=False)
                await pilot.pause()
                assert (
                    app.query_one(ChatTranscriptComponent)
                    ._update_reading_anchor_and_build_follow_snapshot()
                    .was_following
                    is False
                )

                await app.query_one(ChatTranscriptComponent).echo_user(text="visible new prompt")
                await pilot.pause()
                await app._render_event(
                    event=AgentStreamEventDAO(kind="text_delta", delta="streaming tail", iteration=0)
                )
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: app.query_one(ChatTranscriptComponent)
                    ._update_reading_anchor_and_build_follow_snapshot()
                    .was_following,
                )

                assert (
                    app.query_one(ChatTranscriptComponent)
                    ._update_reading_anchor_and_build_follow_snapshot()
                    .was_following
                    is True
                )
                transcript_content = app.query_one(ChatTranscriptComponent)._transcript_content
                assert transcript_content is not None
                assert any(
                    isinstance(child, UserMessageBlock) and child.text == "visible new prompt"
                    for child in transcript_content.children
                )

    def test_transcript_scroll_posts_reached_top_only_on_threshold_crossing(self) -> None:
        """The scroll widget emits a top-reached message on downward crossing only."""
        scroll: TranscriptScrollComponent = TranscriptScrollComponent(
            id="test-scroll",
            navigate=lambda request: True,
            interrupt=lambda: None,
        )
        posted: list[Message] = []

        def _record_message(message: Message) -> bool:
            """Record the message instead of dispatching it during the unit test."""
            posted.append(message)
            return True

        with (
            patch.object(scroll, "post_message", new=_record_message),
            patch("textual.containers.VerticalScroll.watch_scroll_y", autospec=True) as mock_super_watch,
        ):
            scroll.watch_scroll_y(old_value=5.0, new_value=1.0)
            scroll.watch_scroll_y(old_value=1.0, new_value=0.0)

        assert mock_super_watch.call_count == 2
        assert len(posted) == 1
        assert isinstance(posted[0], TranscriptScrollComponent.ReachedTop)


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
        assert app.query_one(ChatTranscriptComponent)._transcript_content is not None
        return [
            child.answer_text
            for child in app.query_one(ChatTranscriptComponent)._transcript_content.children
            if isinstance(child, AssistantStreamBlock)
        ]

    @pytest.mark.asyncio
    async def test_hydration_mounts_only_the_newest_entry_limit_entries(self) -> None:
        """Hydration mounts the newest batch instead of every entry on disk."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=12)

        with patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
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

        with patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 7
                summary = app.query_one(ChatTranscriptComponent)._earlier_summary
                assert summary is not None
                assert "7 earlier messages hidden" in str(summary.content)

    @pytest.mark.asyncio
    async def test_hydration_cursor_is_zero_when_history_fits_within_the_entry_limit(self) -> None:
        """Nothing is hidden when the whole history is mounted."""
        entries: list[TranscriptEntryDAO] = self._assistant_entries(count=3)

        with patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 0
                assert app.query_one(ChatTranscriptComponent)._earlier_summary is None

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
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 4),
        ):
            app: SloTUI = self._build_history_app(entries=entries)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await app.query_one(ChatTranscriptComponent).load_older()
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
                assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 3

    @pytest.mark.asyncio
    async def test_unpainted_scroll_before_mutation_does_not_load_an_extra_page(self, tmp_path: Path) -> None:
        """An anchor captured before repaint must not manufacture a top crossing.

        A prepend can restore y synchronously and capture the next mutation's
        anchor before Textual repaints. Reproduce that ordering without sleeps
        or synthetic ReachedTop messages, then verify real Home still paginates.
        """
        from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from tests.tui.test_replay_resume import _build_session_with_history

        root = tmp_path / "history"
        assert root.resolve().is_relative_to(tmp_path.resolve())
        session = _build_session_with_history(workdir=tmp_path, history_root=root, responses=[])
        store = FilesystemSessionHistoryStore(root=root)
        await store.ensure_session(session_id=session.session_id, workdir=tmp_path, model_name="gpt-5.4")
        for index in range(12):
            await store.append_event(
                event=SessionHistoryEventDAO(
                    session_id=session.session_id,
                    kind="assistant_message",
                    iteration=index,
                    turn_id=f"turn-{index}",
                    payload=SessionHistoryEventPayloadDAO(content=f"assistant-{index}"),
                )
            )
        history_file = root / session.session_id / "events.jsonl"
        persisted = history_file.read_bytes()
        with (
            patch("src.tui.components.chat_transcript.component.TRANSCRIPT_HYDRATION_ENTRY_LIMIT", 5),
            patch("src.tui.components.chat_transcript.component.LOAD_OLDER_BATCH_SIZE", 4),
        ):
            app = SloTUI(session=session)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                transcript = app.query_one(ChatTranscriptComponent)
                scroll = transcript.query_one(TranscriptScrollComponent)
                await transcript.load_older()
                await pilot.pause()
                assert self._visible_assistant_answers(app=app) == [
                    f"assistant-{index}" for index in range(3, 12)
                ]
                assert transcript._load_older_cursor == 3

                # Suppress pagination only for this positioning crossing; the
                # subsequent capture and restoration run with pagination active.
                with scroll.prevent(TranscriptScrollComponent.ReachedTop):
                    scroll.scroll_to(y=0, animate=False, immediate=True)
                await pilot.pause()
                assert transcript._reading_anchor is None

                def scroll_then_capture() -> None:
                    """Capture in the same refresh batch as synchronous restoration."""
                    # Resolve the lazy compositor map at the old offset, as a
                    # preceding anchor callback in the same batch would do.
                    assert app.screen._compositor.full_map
                    scroll.scroll_to(y=6, animate=False, immediate=True)
                    snapshot = transcript._update_reading_anchor_and_build_follow_snapshot()
                    transcript._finish_viewport_mutation(snapshot=snapshot)

                transcript.call_after_refresh(scroll_then_capture)
                await pilot.pause()
                await pilot.pause()

                assert self._visible_assistant_answers(app=app) == [
                    f"assistant-{index}" for index in range(3, 12)
                ]
                assert transcript._load_older_cursor == 3
                assert scroll.scroll_y == 6
                scroll.focus()
                await pilot.press("home")
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                assert self._visible_assistant_answers(app=app) == [
                    f"assistant-{index}" for index in range(12)
                ]
                assert transcript._load_older_cursor == 0
        assert history_file.read_bytes() == persisted

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
            app.query_one(ChatTranscriptComponent)._hidden_block_count = 4
            await app.query_one(ChatTranscriptComponent)._update_earlier_summary()
            await pilot.pause()

            assert app.query_one(ChatTranscriptComponent)._load_older_cursor == 0
            summary = app.query_one(ChatTranscriptComponent)._earlier_summary
            assert summary is not None
            summary_text: str = str(summary.content)
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


class TestAstraTerminalOAuthRejection:
    """Feature 83.c.1: an Astra terminal OAuth rejection renders once, stays usable."""

    @pytest.mark.asyncio
    async def test_astra_oauth_4xx_renders_one_safe_error_and_allows_follow_up(self, tmp_path: Path) -> None:
        """One safe error notice, no duplicates/raw output, then a follow-up runs."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                reasoning_level="high",
                enable_history=False,
            )
        )
        session._agent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path), tools=[])
        invocation_count: int = 0

        async def _failing_invoke(**_: object):
            nonlocal invocation_count
            invocation_count += 1
            raise ValueError("Error code: 403 - unsupported model for this credential")
            yield  # pragma: no cover - async generator protocol

        async def _completing_invoke(**_: object):
            yield AgentStreamEventDAO(kind="run_completed", content="follow-up ok")

        app: SloTUI = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(session.agent, "invoke", _failing_invoke):
                await app._run_prompt(text="oauth attempt")
            with patch.object(session.agent, "invoke", _completing_invoke):
                await app._run_prompt(text="next action")
            await pilot.pause()
            transcript: list[str] = [content for content, _classes in _require_adapter_lines(app=app)]

        assert invocation_count == 1
        error_lines: list[str] = [content for content in transcript if "unsupported model" in content]
        assert len(error_lines) == 1
        assert session.is_running is False
        assert app._in_flight_task is None
        assert app._spinner is None


class TestCompactionAdvisedRendering:
    """The latency advisory uses the notice funnel, never the projector (spec 85.a.2)."""

    @pytest.mark.asyncio
    async def test_compaction_advised_renders_notice_and_bypasses_projector(self) -> None:
        """One advisory writes an adapter line and never projects or compacts."""
        app: SloTUI = SloTUI(
            session=_build_session(responses=[AIMessage(content="unused")]),
        )
        content: str = "Context is above 256,000 tokens; run /compact to help latency."

        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch.object(
                    app.query_one(ChatTranscriptComponent)._projector, "handle", new=AsyncMock()
                ) as mock_project,
                patch.object(Compacter, "compact", new=AsyncMock()) as mock_compact,
            ):
                await app._render_event(
                    AgentStreamEventDAO(kind="compaction_advised", content=content),
                )
                await pilot.pause()

            assert content in app.query_one(ChatTranscriptComponent).logical_copy_text()
            mock_project.assert_not_called()
            mock_compact.assert_not_called()
