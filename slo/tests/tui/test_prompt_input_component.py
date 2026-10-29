"""Mounted journey tests for the extracted PromptInput component (spec 96.f.2)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.screen import ModalScreen
from textual.widgets import TextArea

from src.agents.model_catalog.dao import CatalogLifecycleStatusDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowResumeLauncher
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import HistoryReader
from src.tui.components.prompt_input.component import PromptInput
from src.tui.model_catalog import ModelSuggestionProjection, model_suggestion_entries
from src.tui.prompt_history import PromptHistoryNavigator
from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from src.tui.slash_suggestion_engine import SlashSuggestionEngine, SlashSuggestionStateDAO
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from tests.tui._scroll_settle import pump_until
from tests.tui.test_prompt_input_rules import _recording_invoke, _submit_prompt


def _build_session(
    *,
    workdir: Path,
    responses: list[AIMessage] | None = None,
    enable_history: bool = False,
) -> SloAgentSession:
    """Build a real session driven by a Faux model; no provider is contacted.

    Args:
        workdir (Path): Test-owned working directory.
        responses (list[AIMessage] | None): Scripted assistant responses.
        enable_history (bool): Persist real session history under ``workdir``.

    Returns:
        SloAgentSession: Session ready to drive a mounted ``SloTUI``.
    """
    history_store = FilesystemSessionHistoryStore(root=workdir / "history") if enable_history else None
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses or [AIMessage(content="ok")])),
        workdir=workdir,
        session_id=str(uuid4()),
        history_store=history_store,
        enable_history=enable_history,
    )


def _require_prompt_input(*, app: SloTUI) -> PromptInput:
    """Return the mounted prompt editor.

    Args:
        app (SloTUI): Mounted application.

    Returns:
        PromptInput: The mounted prompt editor.
    """
    assert app._input is not None
    return app._input


async def _wait_for_app_idle(*, app: SloTUI, pilot: Pilot) -> None:
    """Pump until the app owns no in-flight or queued prompt.

    Args:
        app (SloTUI): Mounted application.
        pilot: Textual pilot.
    """
    await pump_until(
        pilot=pilot,
        predicate=lambda: app._in_flight_task is None and app._queued_prompt_text is None,
    )


async def _history_user_texts(*, session: SloAgentSession) -> list[str]:
    """Read accepted user prompts from the real session history store.

    Args:
        session (SloAgentSession): Session whose store is read.

    Returns:
        list[str]: Persisted ``user_message`` payload contents in order.
    """
    assert session.history_store is not None
    events = await session.history_store.load_events(session_id=session.session_id)
    return [event.payload.content or "" for event in events if event.kind == "user_message"]


def _gated_real_invoke(
    *,
    invoke_log: list[str],
    gate: asyncio.Event,
    original_invoke: Callable[..., AsyncIterator[AgentStreamEventDAO]],
) -> Callable[..., AsyncIterator[AgentStreamEventDAO]]:
    """Hold each real run busy after its first event, preserving real history writes.

    Args:
        invoke_log (list[str]): Receives each admitted prompt text.
        gate (asyncio.Event): Releases the held continuation.
        original_invoke: Real ``session.invoke`` bound before patching.

    Returns:
        Callable[..., AsyncIterator[AgentStreamEventDAO]]: Gated async generator.
    """

    held_texts: set[str] = set()

    async def _invoke(*, text: str) -> AsyncIterator[AgentStreamEventDAO]:
        invoke_log.append(text)
        async for event in original_invoke(text=text):
            yield event
            if text not in held_texts and not gate.is_set():
                held_texts.add(text)
                await gate.wait()

    return _invoke


class _PromptInputHost(App):
    """Minimal mounted host for PromptInput binding boundaries."""

    def compose(self) -> ComposeResult:
        """Compose the borrowed menu and the editor under test.

        Yields:
            ComposeResult: Menu followed by the editor.
        """
        self.menu: SlashSuggestionMenu = SlashSuggestionMenu()
        self.editor: PromptInput = PromptInput()
        yield self.menu
        yield self.editor


class _ModalHost(ModalScreen[None]):
    """Modal screen with its own focusable editor."""

    def compose(self) -> ComposeResult:
        """Yield one focusable editor.

        Yields:
            ComposeResult: Modal editor.
        """
        self.editor: TextArea = TextArea()
        yield self.editor


class _ChangedStub:
    """Minimal owned Changed event for the post-unmount cutoff."""

    def __init__(self, *, text_area: PromptInput) -> None:
        """Capture the owner and seed the stopped marker.

        Args:
            text_area (PromptInput): Event owner.
        """
        self.text_area = text_area
        self.stopped: bool = False

    def stop(self) -> None:
        """Record that the closed handler stopped the owned event."""
        self.stopped = True


class _FailingSuggestionEngine(SlashSuggestionEngine):
    """Engine whose evaluation fails, injected through ``bind_suggestions``."""

    def __init__(self) -> None:
        """Build a real registry-backed engine that fails on evaluation."""
        super().__init__(registry=SlashRouter.registry())

    def evaluate(
        self,
        *,
        buffer_text: str,
        active_model_name: str,
    ) -> SlashSuggestionStateDAO:
        """Fail the binding evaluation.

        Args:
            buffer_text (str): Current prompt buffer.
            active_model_name (str): Current session model.

        Raises:
            RuntimeError: Always, to prove failed-bind cleanup.
        """
        del buffer_text, active_model_name
        raise RuntimeError("suggestion evaluation failed")


async def test_key_precedence_and_single_submit(tmp_path: Path) -> None:
    """Suggestions keep intent local; Enter submits once; modified Enter inserts newlines."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    release: asyncio.Event = asyncio.Event()
    release.set()
    dispatch_lines: list[str] = []

    async def record_dispatch(*, line: str) -> None:
        """Record one app-level slash dispatch without executing it."""
        dispatch_lines.append(line)

    with patch.object(
        target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            editor.load_text("/mo")
            await pilot.pause()
            assert editor._slash_suggestion_state.visible is True

            await pilot.press("tab")
            await pilot.pause()
            assert editor.text == "/model "
            assert invoke_log == []
            assert dispatch_lines == []

            editor.load_text("")
            await pilot.pause()
            editor.focus()
            await pilot.press("a")
            await pilot.press("shift+enter")
            await pilot.press("ctrl+enter")
            await pilot.press("meta+enter")
            await pilot.pause()
            assert editor.text == "a\n\n\n"
            assert invoke_log == []

            editor.load_text("/mo")
            await pilot.pause()
            assert editor._slash_suggestion_state.visible is True
            with patch.object(app, "_dispatch_slash_command", new=record_dispatch):
                await pilot.press("enter")
                await pilot.pause()
            assert dispatch_lines == ["/mo"]
            assert invoke_log == []
            assert editor.text == ""

            editor.load_text("plain")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert invoke_log == ["plain"]
            assert editor.text == ""

            await pilot.press("enter")
            await pilot.pause()
            assert invoke_log == ["plain"]
            assert not hasattr(SloTUI, "on_prompt_input_suggestion_accepted")


async def test_suggestion_span_and_empty_menu(tmp_path: Path) -> None:
    """Acceptance splices the engine span, keeps the suffix and no-ops on empty rows."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    release: asyncio.Event = asyncio.Event()
    release.set()

    with patch.object(
        target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            editor.load_text("/mo suffix kept")
            await pilot.pause()
            assert editor._slash_suggestion_state.visible is True
            await pilot.press("tab")
            await pilot.pause()
            assert editor.text == "/model  suffix kept"
            assert editor.cursor_location == (0, len("/model  suffix kept"))
            assert invoke_log == []

            editor.load_text("/zzzz")
            await pilot.pause()
            assert editor._slash_suggestion_state.visible is False
            before: str = editor.text
            editor.post_message(PromptInput.SuggestionAccepted())
            await pilot.pause()
            assert editor.text == before
            assert invoke_log == []


async def test_recall_restores_draft(tmp_path: Path) -> None:
    """Recall restores drafts and slash-like text without exiting navigation early."""
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        responses=[AIMessage(content="one"), AIMessage(content="two")],
    )
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    release: asyncio.Event = asyncio.Event()
    release.set()

    with patch.object(
        target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            await _submit_prompt(app=app, pilot=pilot, text="first prompt")
            await _wait_for_app_idle(app=app, pilot=pilot)
            await _submit_prompt(app=app, pilot=pilot, text="second prompt")
            await _wait_for_app_idle(app=app, pilot=pilot)

            editor.load_text("")
            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "second prompt"
            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "first prompt"
            await pilot.press("down")
            await pilot.pause()
            assert editor.text == "second prompt"
            await pilot.press("down")
            await pilot.pause()
            assert editor.text == ""
            assert editor._prompt_history.is_navigating is False

            editor.record_accepted_prompt(text="/model open")
            editor.load_text("")
            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "/model open"
            assert editor._prompt_history.is_navigating is True
            assert editor._slash_suggestion_state.visible is True
            await pilot.press("escape")
            await pilot.press("down")
            await pilot.pause()
            assert editor.text == ""
            assert editor._prompt_history.is_navigating is False

            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "/model open"
            assert editor._prompt_history.is_navigating is True
            await pilot.press("x")
            await pilot.pause()
            assert editor.text == "/model openx"
            assert editor._prompt_history.is_navigating is False


async def test_submit_queue_and_history(tmp_path: Path) -> None:
    """Idle/busy submission records only accepted turns once in real history and recall."""
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        responses=[AIMessage(content="one"), AIMessage(content="two")],
        enable_history=True,
    )
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    gate: asyncio.Event = asyncio.Event()
    original_invoke = session.invoke

    with patch.object(
        target=session,
        attribute="invoke",
        new=_gated_real_invoke(invoke_log=invoke_log, gate=gate, original_invoke=original_invoke),
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            await _submit_prompt(app=app, pilot=pilot, text="first")
            await pump_until(pilot=pilot, predicate=lambda: session.is_running)
            assert await _history_user_texts(session=session) == ["first"]

            await _submit_prompt(app=app, pilot=pilot, text="held one")
            await _submit_prompt(app=app, pilot=pilot, text="held two")
            assert app._queued_prompt_text == "held two"
            assert await _history_user_texts(session=session) == ["first"]

            gate.set()
            await _wait_for_app_idle(app=app, pilot=pilot)
            assert invoke_log == ["first", "held two"]
            assert await _history_user_texts(session=session) == ["first", "held two"]

            editor.load_text("")
            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "held two"
            await pilot.press("up")
            await pilot.pause()
            assert editor.text == "first"
            assert editor._prompt_history._entries == ["first", "held two"]


async def test_commands_keep_queue_policy(tmp_path: Path) -> None:
    """Abort/clear/new keep the existing held-prompt and recall ownership rules."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    release: asyncio.Event = asyncio.Event()

    with patch.object(
        target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            await _submit_prompt(app=app, pilot=pilot, text="first")
            await _submit_prompt(app=app, pilot=pilot, text="held")
            assert app._queued_prompt_text == "held"
            recall_before = list(editor._prompt_history._entries)

            await app._dispatch_slash_command(line="/abort")
            await pilot.pause()
            assert app._queued_prompt_text == "held"

            await app._dispatch_slash_command(line="/new")
            await pilot.pause()
            assert app._session is session
            assert app._queued_prompt_text == "held"
            assert list(editor._prompt_history._entries) == recall_before

            await app._dispatch_slash_command(line="/clear")
            await pilot.pause()
            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            assert list(editor._prompt_history._entries) == recall_before

            release.set()
            await _wait_for_app_idle(app=app, pilot=pilot)
            assert invoke_log == ["first"]


async def test_session_adoption_resets_editor_only(tmp_path: Path) -> None:
    """Adoption replaces recall/draft and publishes the new model; failed preparation keeps all."""
    old: SloAgentSession = _build_session(workdir=tmp_path)
    candidate: SloAgentSession = _build_session(workdir=tmp_path)
    candidate._active_model_name = "gpt-4o-mini"
    app: SloTUI = SloTUI(
        session=old,
        session_factory=lambda *, config, allow_pending_preparation: candidate,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        editor: PromptInput = _require_prompt_input(app=app)
        engine: SlashSuggestionEngine = editor._suggestion_engine  # type: ignore[assignment]
        assert engine is not None
        editor.record_accepted_prompt(text="remembered")
        editor.record_model_selection(model_name="gpt-4o")
        old_navigator: PromptHistoryNavigator = editor._prompt_history
        editor.load_text("draft")

        with patch.object(editor, "update_model_context", wraps=editor.update_model_context) as update:
            await app._start_new_session(requested_name=None)
        await pilot.pause()
        assert app._session is candidate
        assert editor.text == ""
        assert editor._prompt_history is not old_navigator
        assert editor._suggestion_engine is engine
        assert engine._recent_models == ["gpt-4o"]
        assert editor._active_model_name == "gpt-4o-mini"
        update.assert_called_once_with(active_model_name="gpt-4o-mini")

    failed: SloAgentSession = _build_session(workdir=tmp_path)
    failed_app: SloTUI = SloTUI(session=failed)
    async with failed_app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        failed_editor: PromptInput = _require_prompt_input(app=failed_app)
        failed_editor.record_accepted_prompt(text="kept")
        failed_navigator: PromptHistoryNavigator = failed_editor._prompt_history
        failed_editor.load_text("draft kept")
        with patch.object(SloAgentSession, "build", side_effect=ValueError("private failure")):
            await failed_app._start_new_session(requested_name=None)
        assert failed_app._session is failed
        assert failed_editor._prompt_history is failed_navigator
        assert failed_editor.text == "draft kept"


async def test_published_catalog_refresh(tmp_path: Path) -> None:
    """A published revision refreshes an open picker on idle without typing or auth I/O."""
    ModelCatalogService.reset()
    ModelCatalogService._publish_status(
        status=CatalogLifecycleStatusDAO(
            state="historical",
            key_verified_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            catalog_checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    snapshot = SeedModelCatalog.load()
    route = "openrouter:vendor/model"
    entry = snapshot.entries["kimi-k3"].model_copy(
        update={
            "model_name": route,
            "provider": ProviderName.OPENROUTER,
            "display_name": "literal",
        }
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}, "generation": 999})
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)

    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(
            CredentialResolver,
            "resolve",
            side_effect=lambda *, provider: CredentialDAO(
                provider=provider, auth_type=AuthType.API_KEY, access_token="fixture-picker"
            ),
        ),
    ):
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)
            editor.load_text("/model ")
            await pilot.pause()
            assert editor._slash_suggestion_state.visible is True
            await pilot.press("down", "down")
            await pilot.pause()
            selected = editor._slash_suggestion_state.highlighted_row
            assert selected is not None

            ModelCatalogService._publish_status(
                status=CatalogLifecycleStatusDAO(
                    state="historical",
                    key_verified_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
                    catalog_checked_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
                )
            )
            with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("typing I/O")):
                await pilot.pause()

            assert editor._slash_suggestion_state.visible is True
            highlighted = editor._slash_suggestion_state.highlighted_row
            assert highlighted is not None
            assert highlighted.insert_text == selected.insert_text
            assert editor._picker_catalog_revision == ModelSuggestionProjection.current_revision()
            assert all(
                row.catalog_generation == 999
                for row in model_suggestion_entries(active_model_name=session.active_model_name)
            )
    ModelCatalogService.reset()


async def test_focus_and_teardown_cutoffs(tmp_path: Path) -> None:
    """A modal never loses focus to the prompt, and late callbacks never repaint the menu."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        editor: PromptInput = _require_prompt_input(app=app)
        editor.load_text("draft")
        await pilot.pause()
        await app.push_screen(_ModalHost())
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, _ModalHost)
        modal.editor.focus()
        await pilot.press("z")
        await pilot.pause()
        assert modal.editor.text == "z"
        assert editor.text == "draft"
        assert app.focused is modal.editor
        app.pop_screen()
        await pilot.pause()

    menu: SlashSuggestionMenu = app._suggestion_menu  # type: ignore[assignment]
    assert menu is not None
    menu_state = menu._state
    for _ in range(3):
        app.on_idle()
        editor.update_model_context(active_model_name="late-model")
        editor.refresh_published_suggestions()
    changed = _ChangedStub(text_area=editor)
    editor.on_text_area_changed(changed)  # type: ignore[arg-type]
    assert changed.stopped is True
    assert menu._state == menu_state
    assert editor._closed is True
    assert editor._suggestion_engine is None
    assert editor._suggestion_menu is None


async def test_layout_and_packaged_styles(tmp_path: Path) -> None:
    """Computed editor styling matches the moved app rule in both themes, focused/blurred."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    release: asyncio.Event = asyncio.Event()

    with patch.object(
        target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)

            for theme in (SLO_DARK_THEME, SLO_DEFAULT_THEME):
                app.theme = theme.name
                await pilot.pause()
                for focused in (True, False):
                    if focused:
                        editor.focus()
                    else:
                        editor.blur()
                    await pilot.pause()
                    styles = editor.styles
                    theme_surface = app.current_theme.surface
                    theme_accent = app.current_theme.accent
                    assert theme_surface is not None
                    assert theme_accent is not None
                    assert styles.background is not None
                    assert styles.background.hex.lower() == theme_surface.lower()
                    assert (
                        styles.margin.top,
                        styles.margin.right,
                        styles.margin.bottom,
                        styles.margin.left,
                    ) == (
                        1,
                        0,
                        0,
                        0,
                    )
                    assert (
                        styles.padding.top,
                        styles.padding.right,
                        styles.padding.bottom,
                        styles.padding.left,
                    ) == (
                        0,
                        1,
                        0,
                        1,
                    )
                    assert styles.border_top[0] == "solid"
                    assert styles.border_bottom[0] == "solid"
                    assert styles.border_top[1] is not None
                    assert styles.border_top[1].hex.lower() == theme_accent.lower()
                    assert str(styles.height) == "auto"
                    assert str(styles.min_height) == "3"
                    assert str(styles.max_height) == "17"

            editor.focus()
            await pilot.pause()
            await _submit_prompt(app=app, pilot=pilot, text="first")
            await _submit_prompt(app=app, pilot=pilot, text="held")
            editor.load_text("/mo")
            await pilot.pause()
            queue = app._queued_prompt_block
            assert queue is not None
            assert queue.parent is app._chat_shell
            assert app._chat_transcript not in queue.ancestors
            assert queue.region.bottom <= editor.region.y
            assert editor._slash_suggestion_state.visible is True
            release.set()
            await _wait_for_app_idle(app=app, pilot=pilot)


async def test_submission_lifetime_guards(tmp_path: Path) -> None:
    """A shutdown cutoff refuses late admission and never invokes or records it."""
    session: SloAgentSession = _build_session(
        workdir=tmp_path, responses=[AIMessage(content="one")], enable_history=True
    )
    app: SloTUI = SloTUI(session=session)
    invoke_log: list[str] = []
    gate: asyncio.Event = asyncio.Event()
    original_invoke = session.invoke

    with patch.object(
        target=session,
        attribute="invoke",
        new=_gated_real_invoke(invoke_log=invoke_log, gate=gate, original_invoke=original_invoke),
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor: PromptInput = _require_prompt_input(app=app)
            await _submit_prompt(app=app, pilot=pilot, text="first")
            await pump_until(pilot=pilot, predicate=lambda: session.is_running)

            app._app_closing = True
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
            assert invoke_log == ["first"]
            assert app._queued_prompt_text is None
            assert list(editor._prompt_history._entries) == ["first"]
            assert await _history_user_texts(session=session) == ["first"]

            gate.set()
            await pump_until(pilot=pilot, predicate=lambda: app._in_flight_task is None)
            assert invoke_log == ["first"]
            assert list(editor._prompt_history._entries) == ["first"]


async def test_model_context_publication_paths(tmp_path: Path) -> None:
    """Auth, slash and busy publications push the current name without stale recency."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        editor: PromptInput = _require_prompt_input(app=app)
        engine: SlashSuggestionEngine = editor._suggestion_engine  # type: ignore[assignment]
        assert engine is not None

        editor.load_text("/model ")
        await pilot.pause()
        assert editor._slash_suggestion_state.visible is True

        # (a) auth cancel re-evaluates a visible picker with the current name.
        with (
            patch(
                "src.tui.components.prompt_input.component.ModelSuggestionProjection.current_revision",
                return_value=(901, 901),
            ),
            patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as cancel_update,
        ):
            app._on_auth_dismissed(None)
        cancel_update.assert_called_once_with(active_model_name=session.active_model_name)
        assert editor._picker_catalog_revision == (901, 901)

        # (a) a same-provider credential also publishes and re-evaluates.
        same_provider = CredentialDAO(
            provider=provider_for_model(model_name=session.active_model_name),
            auth_type=AuthType.API_KEY,
            access_token="fixture-same-provider",
        )
        with (
            patch(
                "src.tui.components.prompt_input.component.ModelSuggestionProjection.current_revision",
                return_value=(902, 902),
            ),
            patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as same_update,
        ):
            app._on_auth_dismissed(same_provider)
        same_update.assert_called_once_with(active_model_name=session.active_model_name)
        assert editor._picker_catalog_revision == (902, 902)

        # (b) the provider-default switch publishes while a run is busy, without recency.
        session._is_running = True
        recency_before = list(engine._recent_models)
        with (
            patch("src.tui.app.default_model_for_provider", return_value="openrouter:vendor/model"),
            patch.object(session, "switch_model") as switch,
            patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as busy_update,
        ):
            app._on_auth_dismissed(
                CredentialDAO(
                    provider=ProviderName.OPENROUTER,
                    auth_type=AuthType.API_KEY,
                    access_token="fixture-openrouter",
                )
            )
            switch.assert_called_once_with(model_name="openrouter:vendor/model")
        session._is_running = False
        busy_update.assert_called_with(active_model_name="openrouter:vendor/model")
        assert editor._active_model_name == "openrouter:vendor/model"
        assert list(engine._recent_models) == recency_before

        # (c) a refused or unchanged selection records no recency and publishes nothing.
        async def unchanged_dispatch(
            *,
            line: str,
            session: SloAgentSession,
            workflow_resume_launcher: Optional[WorkflowResumeLauncher] = None,
        ) -> SlashCommandResultDAO:
            """Simulate a slash selection that leaves the active name unchanged."""
            del line, session, workflow_resume_launcher
            return SlashCommandResultDAO()

        recency_before = list(engine._recent_models)
        with (
            patch("src.tui.app.SlashRouter.dispatch", new=unchanged_dispatch),
            patch.object(
                editor, "record_model_selection", wraps=editor.record_model_selection
            ) as recency_spy,
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as update_spy,
        ):
            await app._dispatch_slash_command(line="/model gpt-5.4")
        recency_spy.assert_not_called()
        update_spy.assert_not_called()
        assert list(engine._recent_models) == recency_before

        # `/model refresh` publishes the unchanged name but still records no recency.
        with (
            patch("src.tui.app.SlashRouter.dispatch", new=unchanged_dispatch),
            patch.object(
                editor, "record_model_selection", wraps=editor.record_model_selection
            ) as recency_spy,
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as refresh_update,
        ):
            await app._dispatch_slash_command(line="/model refresh")
        recency_spy.assert_not_called()
        refresh_update.assert_called_once_with(active_model_name=session.active_model_name)

        # (g) a session displaced during dispatch neither records recency nor publishes.
        other = _build_session(workdir=tmp_path)
        original_name = session.active_model_name

        async def displaced_dispatch(
            *,
            line: str,
            session: SloAgentSession,
            workflow_resume_launcher: Optional[WorkflowResumeLauncher] = None,
        ) -> SlashCommandResultDAO:
            """Displace the captured session mid-dispatch before it returns."""
            del line, workflow_resume_launcher
            session._active_model_name = "stale-selection"
            app._session = other
            return SlashCommandResultDAO()

        recency_before = list(engine._recent_models)
        active_before = editor._active_model_name
        with (
            patch("src.tui.app.SlashRouter.dispatch", new=displaced_dispatch),
            patch.object(
                editor, "record_model_selection", wraps=editor.record_model_selection
            ) as recency_spy,
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as update_spy,
        ):
            await app._dispatch_slash_command(line="/model stale-selection")
        recency_spy.assert_not_called()
        update_spy.assert_not_called()
        assert list(engine._recent_models) == recency_before
        assert editor._active_model_name == active_before
        app._session = session
        session._active_model_name = original_name

        async def changed_dispatch(
            *,
            line: str,
            session: SloAgentSession,
            workflow_resume_launcher: Optional[WorkflowResumeLauncher] = None,
        ) -> SlashCommandResultDAO:
            """Simulate one successful changed slash model selection."""
            del line, workflow_resume_launcher
            session._active_model_name = "changed-model"
            return SlashCommandResultDAO()

        with (
            patch("src.tui.app.SlashRouter.dispatch", new=changed_dispatch),
            patch.object(
                editor, "record_model_selection", wraps=editor.record_model_selection
            ) as recency_spy,
        ):
            await app._dispatch_slash_command(line="/model changed-model")
        recency_spy.assert_called_once_with(model_name="changed-model")
        assert editor._active_model_name == "changed-model"
        assert engine._recent_models[0] == "changed-model"


async def test_preparation_and_replacement_context_guards(tmp_path: Path) -> None:
    """Preparation publishes only on a live success; a displaced replacement never resets."""
    session: SloAgentSession = _build_session(workdir=tmp_path)
    app: SloTUI = SloTUI(session=session)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        editor: PromptInput = _require_prompt_input(app=app)

        async def prepare_ok() -> None:
            """Complete preparation successfully."""

        with (
            patch.object(session, "prepare_startup", new=prepare_ok),
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as success_update,
        ):
            await app._prepare_mounted_session(session=session)
        success_update.assert_called_once_with(active_model_name=session.active_model_name)

        async def prepare_fail() -> None:
            """Fail preparation before any publication."""
            raise RuntimeError("private preparation failure")

        with (
            patch.object(session, "prepare_startup", new=prepare_fail),
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as failed_update,
        ):
            await app._prepare_mounted_session(session=session)
        failed_update.assert_not_called()

        displaced = _build_session(workdir=tmp_path)

        async def prepare_displaced() -> None:
            """Displace the captured session before its success publication."""
            app._session = displaced

        with (
            patch.object(session, "prepare_startup", new=prepare_displaced),
            patch.object(
                editor, "update_model_context", wraps=editor.update_model_context
            ) as displaced_update,
        ):
            await app._prepare_mounted_session(session=session)
        displaced_update.assert_not_called()
        app._session = session

        # (f) displacement between the replacement awaits skips reset and publication.
        editor.load_text("survives")
        navigator = editor._prompt_history
        replacement = _build_session(workdir=tmp_path)

        async def displace_bind_history(*, history_reader: HistoryReader) -> None:
            """Displace the captured session across the replacement await."""
            del history_reader
            app._session = replacement

        with (
            patch.object(app._chat_transcript, "bind_history", new=displace_bind_history),
            patch.object(editor, "reset_session", wraps=editor.reset_session) as reset_spy,
            patch.object(editor, "update_model_context", wraps=editor.update_model_context) as update_spy,
        ):
            await app._refresh_replacement_ui()
        reset_spy.assert_not_called()
        update_spy.assert_not_called()
        assert app._session is replacement
        assert editor.text == "survives"
        assert editor._prompt_history is navigator
        app._session = session


async def test_binding_and_changed_ordering() -> None:
    """Unbound intents are safe, bind evaluates the latest draft, duplicate bind raises."""
    host: _PromptInputHost = _PromptInputHost()
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashRouter.registry())

    async with host.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        editor: PromptInput = host.editor
        assert editor._suggestion_engine is None
        assert editor._suggestion_menu is None

        editor.post_message(PromptInput.SuggestionMoved(delta=1))
        editor.post_message(PromptInput.SuggestionAccepted())
        editor.post_message(PromptInput.SuggestionDismissed())
        editor.post_message(PromptInput.PromptHistoryOlderRequested())
        editor.post_message(PromptInput.PromptHistoryNewerRequested())
        await pilot.pause()
        assert editor.text == ""
        assert editor._slash_suggestion_state.visible is False
        assert host.menu._state == SlashSuggestionStateDAO(visible=False)

        editor.load_text("/mo")
        await pilot.pause()
        assert editor._slash_suggestion_state.visible is False
        assert host.menu._state.visible is False

        editor.bind_suggestions(menu=host.menu, engine=engine, active_model_name="gpt-5.4")
        assert editor._slash_suggestion_state.visible is True
        assert host.menu._state.visible is True
        assert host.menu._state.rows[0].label == "/model"

        with pytest.raises(RuntimeError):
            editor.bind_suggestions(menu=host.menu, engine=engine, active_model_name="other")
        assert editor._suggestion_engine is engine
        assert editor._suggestion_menu is host.menu
        assert editor._active_model_name == "gpt-5.4"
        assert host.menu._state.rows[0].label == "/model"

    assert editor._closed is True
    assert editor._suggestion_engine is None
    assert editor._suggestion_menu is None
    with pytest.raises(RuntimeError):
        editor.bind_suggestions(menu=host.menu, engine=engine, active_model_name="gpt-5.4")
    assert editor._suggestion_engine is None


async def test_closed_bind_while_menu_mounted() -> None:
    """Closing the unbound editor alone makes bind raise and leaves no collaborators."""
    host: _PromptInputHost = _PromptInputHost()
    engine: SlashSuggestionEngine = SlashSuggestionEngine(registry=SlashRouter.registry())

    async with host.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        editor: PromptInput = host.editor
        await editor.remove()
        await pilot.pause()
        assert editor._closed is True
        assert host.menu.is_mounted is True
        with pytest.raises(RuntimeError):
            editor.bind_suggestions(menu=host.menu, engine=engine, active_model_name="gpt-5.4")
        assert editor._suggestion_engine is None
        assert editor._suggestion_menu is None
        assert host.menu._state == SlashSuggestionStateDAO(visible=False)


async def test_failed_bind_releases_collaborators() -> None:
    """Evaluation failure renders hidden state then keeps no menu or engine reference."""
    host: _PromptInputHost = _PromptInputHost()

    async with host.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        editor: PromptInput = host.editor
        editor.load_text("/mo")
        await pilot.pause()

        with pytest.raises(RuntimeError, match="suggestion evaluation failed"):
            editor.bind_suggestions(
                menu=host.menu,
                engine=_FailingSuggestionEngine(),
                active_model_name="gpt-5.4",
            )

        assert editor._suggestion_engine is None
        assert editor._suggestion_menu is None
        assert editor._active_model_name == ""
        assert editor._picker_catalog_revision == (0, 0)
        assert editor._slash_suggestion_state == SlashSuggestionStateDAO(visible=False)
        assert editor._suggestion_navigation_enabled is False
        assert host.menu._state == SlashSuggestionStateDAO(visible=False)
