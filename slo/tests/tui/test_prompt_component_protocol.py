"""Real application journeys for the prompt command and lifecycle boundary."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.commands import (
    ClearSubmissionDAO,
    PromptCommand,
    ReplacePromptDAO,
    RecordAcceptedPromptDAO,
    SetModelContextDAO,
    RefreshPublishedSuggestionsDAO,
)
from src.tui.components.protocols import ComponentProtocol
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from src.tui.slash_suggestion_engine import SlashSuggestionEngine
from src.tui.slash_router import SlashRouter
from tests.tui._scroll_settle import pump_until
from tests.tui.test_path_suggestions_app import ControlledPathReader


def build_session(*, tmp_path: Path) -> SloAgentSession:
    """Build a real persisted session with only the provider replaced.

    Args:
        tmp_path: Test-owned filesystem root.

    Returns:
        Session using contained real history and a finite model script.
    """
    history_root = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="literal answer")]),
            cwd=str(tmp_path),
            tools=[],
        ),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        enable_history=True,
    )


async def test_commands_replace_recall_and_model_before_return(tmp_path: Path) -> None:
    """Public commands update the mounted editor before the next caller action."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        component: ComponentProtocol[PromptCommand] = prompt
        await component.handle(command=ReplacePromptDAO(text="draft\nnext"))
        assert prompt.text == "draft\nnext"
        assert prompt.cursor_location == (1, 4)
        await component.handle(command=SetModelContextDAO(active_model_name="gpt-5.4"))
        assert prompt._active_model_name == "gpt-5.4"
        await component.handle(command=RefreshPublishedSuggestionsDAO())
        await component.handle(command=RecordAcceptedPromptDAO(text="remembered"))
        await component.handle(command=ClearSubmissionDAO())
        await pilot.pause()
        await pilot.press("up")
        assert prompt.text == "remembered"


async def test_closed_native_keys_do_not_submit_or_edit(tmp_path: Path) -> None:
    """Explicit delivery close leaves Textual alive without leaking late submission."""
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        prompt.load_text("closed draft")
        await prompt.close()
        await pilot.press("enter", "tab", "up", "down", "escape", "escape", "x", "shift+enter")
        assert prompt.text == "closed draft"
        assert session.history_store is not None
        assert await session.history_store.load_events(session_id=session.session_id) == []


@pytest.mark.parametrize(argnames="cutoff", argvalues=["reset", "rebind"])
async def test_queued_native_intents_cannot_change_successor(tmp_path: Path, cutoff: str) -> None:
    """Messages already queued before retirement cannot submit or alter successor recall."""
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        await pilot.pause()
        prompt.post_message(prompt.Submitted(text="obsolete"))
        prompt.post_message(prompt.PromptHistoryOlderRequested())
        prompt.post_message(prompt.SuggestionAccepted())
        prompt.post_message(prompt.SuggestionMoved(delta=1))
        prompt.post_message(prompt.PathSuggestionsRequested())
        prompt.post_message(prompt.PromptHistoryNewerRequested())
        prompt.post_message(prompt.SuggestionDismissed())
        if cutoff == "reset":
            await prompt.reset()
        else:
            await prompt.replace_suggestion_binding(
                menu=menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name="gpt-5.4",
            )
        await prompt.handle(command=RecordAcceptedPromptDAO(text="successor recall"))
        await prompt.handle(command=ReplacePromptDAO(text="/he"))
        await pilot.pause()
        assert prompt.text == "/he"
        assert not menu.has_class("-hidden")
        assert session.history_store is not None
        assert await session.history_store.load_events(session_id=session.session_id) == []


@pytest.mark.parametrize(argnames="cutoff", argvalues=["reset", "rebind", "close"])
async def test_retired_controller_cannot_publish_to_rebound_prompt(tmp_path: Path, cutoff: str) -> None:
    """An old view callback cannot overwrite the successor, even with identical draft."""
    from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        await prompt.handle(command=ReplacePromptDAO(text="/he"))
        await pilot.pause()
        snapshot = app.capture_path_prompt()
        assert snapshot is not None
        if cutoff == "reset":
            await prompt.reset()
            await prompt.handle(command=ReplacePromptDAO(text="/he"))
            await pilot.pause()
        elif cutoff == "close":
            await prompt.close()
        else:
            await prompt.replace_suggestion_binding(
                menu=menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name="gpt-5.4",
            )
        await app.publish_path_suggestions(
            state=SlashSuggestionStateDAO(visible=False),
            controller=app._path_suggestions,
            snapshot=snapshot,
        )
        assert menu.has_class("-hidden") == (cutoff == "close")
        await app.replace_path_span(
            insert_text="obsolete",
            start=(0, 0),
            end=(0, 3),
            cursor_inside_quote=False,
            controller=app._path_suggestions,
            snapshot=snapshot,
        )
        assert prompt.text == "/he"


@pytest.mark.parametrize(argnames="cancelled", argvalues=[False, True])
async def test_rebind_failure_releases_old_and_failed_successor(tmp_path: Path, cancelled: bool) -> None:
    """Failed evaluation cannot retain old authority or publish a partial successor."""
    from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO

    class FailingEngine(SlashSuggestionEngine):
        """Fail evaluation after retirement, without replacing persistence."""

        def evaluate(self, *, buffer_text: str, active_model_name: str) -> SlashSuggestionStateDAO:
            """Expose the original translation error to the caller."""
            if cancelled:
                raise asyncio.CancelledError("evaluation failed")
            raise ValueError("evaluation failed")

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        await pilot.pause()
        with pytest.raises(asyncio.CancelledError if cancelled else ValueError, match="evaluation failed"):
            await prompt.replace_suggestion_binding(
                menu=menu,
                engine=FailingEngine(registry=SlashRouter.registry()),
                active_model_name="failed",
            )
        assert prompt._suggestion_menu is None
        assert prompt._suggestion_engine is None
        assert prompt._path_controller is None
        assert menu.has_class("-hidden")
        assert not app._path_suggestions._closed
        await prompt.replace_suggestion_binding(
            menu=menu,
            engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
            active_model_name="gpt-5.4",
            path_controller=app._path_suggestions,
        )
        await prompt.handle(command=ReplacePromptDAO(text="/he"))
        await pilot.pause()
        assert not menu.has_class("-hidden")


async def test_failed_retirement_never_adopts_successor_and_can_retry(tmp_path: Path) -> None:
    """Controller invalidation failure releases references without transferring ownership."""
    from src.tui.path_suggestion_controller import PathSuggestionController

    class FailingInvalidationController(PathSuggestionController):
        """Fail invalidation after the binding has been successfully admitted."""

        fail: bool = False

        def invalidate(self) -> None:
            """Expose the cleanup error at the borrowed collaborator boundary."""
            if self.fail:
                raise ValueError("invalidation failed")
            super().invalidate()

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        controller = FailingInvalidationController(view=app, run_worker=app.run_worker)
        engine = SlashSuggestionEngine(registry=SlashRouter.registry())
        await prompt.replace_suggestion_binding(
            menu=menu,
            engine=engine,
            active_model_name="old",
            path_controller=controller,
        )
        controller.fail = True
        with pytest.raises(ValueError, match="invalidation failed"):
            await prompt.replace_suggestion_binding(menu=menu, engine=engine, active_model_name="new")
        assert prompt._suggestion_engine is None
        assert prompt._path_controller is None
        assert prompt._suggestion_menu is None
        assert prompt._active_model_name == ""
        assert not controller._closed
        assert menu.is_mounted
        await prompt.replace_suggestion_binding(menu=menu, engine=engine, active_model_name="new")
        assert prompt._active_model_name == "new"
        controller.fail = False
        controller.close()
        await controller.join()
        await pilot.pause()


async def test_close_releases_every_reference_when_menu_cleanup_fails(tmp_path: Path) -> None:
    """Cleanup reports the failure once but cannot retain or close borrowed collaborators."""
    from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO

    class FailingMenu(SlashSuggestionMenu):
        """Native menu with a controllable rendering failure."""

        def __init__(self) -> None:
            """Keep startup rendering real; fail only the requested cleanup."""
            super().__init__()
            self.fail = False

        def update_state(self, *, state: SlashSuggestionStateDAO) -> None:
            """Propagate failure without changing native ownership."""
            if self.fail:
                raise ValueError("menu cleanup failed")
            super().update_state(state=state)

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = FailingMenu()
        await app.mount(menu)
        await prompt.replace_suggestion_binding(
            menu=menu,
            engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
            active_model_name="gpt-5.4",
            path_controller=app._path_suggestions,
        )
        menu.fail = True
        with pytest.raises(ValueError, match="menu cleanup failed"):
            await prompt.close()
        assert prompt._suggestion_menu is None
        assert prompt._suggestion_engine is None
        assert prompt._path_controller is None
        assert menu.is_mounted
        assert not app._path_suggestions._closed
        await prompt.close()
        menu.fail = False
        menu.update_state(state=SlashSuggestionStateDAO(visible=False))
        await pilot.press("enter")


@pytest.mark.parametrize(argnames="cutoff", argvalues=["reset", "rebind", "close"])
async def test_awaited_clear_cannot_erase_successor_draft(tmp_path: Path, cutoff: str) -> None:
    """A suspended borrowed dismissal loses authority when the editor retires it."""
    from src.tui.path_suggestion_controller import PathSuggestionController

    class GatedDismissalController(PathSuggestionController):
        """Hold one dismissal through the actual typed binding seam."""

        def __init__(self, *, app: SloTUI) -> None:
            """Construct explicit admission and release barriers."""
            super().__init__(view=app, run_worker=app.run_worker)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.hold = True

        async def dismiss(self) -> None:
            """Hold only the first call so reset can finish independently."""
            if self.hold:
                self.hold = False
                self.entered.set()
                await self.release.wait()
            else:
                await super().dismiss()

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test():
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        controller = GatedDismissalController(app=app)
        await prompt.replace_suggestion_binding(
            menu=menu,
            engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
            active_model_name="old",
            path_controller=controller,
        )
        clearing = asyncio.create_task(coro=prompt.handle(command=ClearSubmissionDAO()))
        try:
            await asyncio.wait_for(controller.entered.wait(), timeout=2)
            if cutoff == "reset":
                await prompt.reset()
            elif cutoff == "rebind":
                await prompt.replace_suggestion_binding(
                    menu=menu,
                    engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                    active_model_name="new",
                )
            await prompt.handle(command=ReplacePromptDAO(text="successor"))
            if cutoff == "close":
                await prompt.close()
            controller.release.set()
            await asyncio.wait_for(clearing, timeout=2)
            assert prompt.text == "successor"
        finally:
            controller.release.set()
            await clearing
            controller.close()
            await controller.join()


async def test_submission_suspended_in_clear_cannot_enter_successor_session(tmp_path: Path) -> None:
    """The real app rechecks queued intent authority after awaited draft clearing."""
    from src.tui.path_suggestion_controller import PathSuggestionController

    class GatedDismissalController(PathSuggestionController):
        """Hold dismissal while a posted submission is inside the real app handler."""

        def __init__(self, *, app: SloTUI) -> None:
            """Construct a one-call barrier without changing the session."""
            super().__init__(view=app, run_worker=app.run_worker)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.hold = True

        async def dismiss(self) -> None:
            """Let reset proceed while the old submission awaits completion."""
            if self.hold:
                self.hold = False
                self.entered.set()
                await self.release.wait()
            else:
                await super().dismiss()

    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        controller = GatedDismissalController(app=app)
        await prompt.replace_suggestion_binding(
            menu=app.query_one(SlashSuggestionMenu),
            engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
            active_model_name="old",
            path_controller=controller,
        )
        try:
            prompt.post_message(prompt.Submitted(text="obsolete submission"))
            await asyncio.wait_for(controller.entered.wait(), timeout=2)
            await prompt.reset()
            controller.release.set()
            await pilot.pause()
            async with asyncio.timeout(delay=5):
                while app._in_flight_task is not None:
                    await pilot.pause()
            assert session.history_store is not None
            assert await session.history_store.load_events(session_id=session.session_id) == []
        finally:
            controller.release.set()
            controller.close()
            await controller.join()


@pytest.mark.parametrize(argnames="fail", argvalues=[False, True])
async def test_suspended_binding_cannot_render_or_release_successor(tmp_path: Path, fail: bool) -> None:
    """An obsolete bind continuation cannot evaluate or clean up the replacement."""
    from src.tui.path_suggestion_controller import PathSuggestionController

    class GatedRequestController(PathSuggestionController):
        """Suspend initial evaluation through the borrowed controller interface."""

        def __init__(self, *, app: SloTUI) -> None:
            """Create bounded synchronization for one old binding."""
            super().__init__(view=app, run_worker=app.run_worker)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def request(self, *, explicit: bool = False) -> bool:
            """Finish old evaluation after the replacement has been adopted."""
            self.entered.set()
            await self.release.wait()
            if fail:
                raise ValueError("old evaluation failed")
            return False

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test():
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        controller = GatedRequestController(app=app)
        binding = asyncio.create_task(
            coro=prompt.replace_suggestion_binding(
                menu=menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name="old",
                path_controller=controller,
            )
        )
        try:
            await asyncio.wait_for(controller.entered.wait(), timeout=2)
            await prompt.replace_suggestion_binding(
                menu=menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name="new",
            )
            controller.release.set()
            if fail:
                with pytest.raises(ValueError, match="old evaluation failed"):
                    await asyncio.wait_for(binding, timeout=2)
            else:
                await asyncio.wait_for(binding, timeout=2)
            assert prompt._suggestion_menu is menu
            assert prompt._active_model_name == "new"
            await prompt.handle(command=ReplacePromptDAO(text="/he"))
        finally:
            controller.release.set()
            await asyncio.gather(binding, return_exceptions=True)
            controller.close()
            await controller.join()


async def test_public_prompt_boundaries_reject_foreign_loop(tmp_path: Path) -> None:
    """No public delivery, reset, binding or close may mutate from a worker loop."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test():
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)

        async def foreign_calls() -> None:
            """Exercise production admission on a second asyncio loop."""
            with pytest.raises(RuntimeError, match="UI loop"):
                await prompt.handle(command=ReplacePromptDAO(text="wrong loop"))
            with pytest.raises(RuntimeError, match="UI loop"):
                await prompt.reset()
            with pytest.raises(RuntimeError, match="UI loop"):
                await prompt.replace_suggestion_binding(
                    menu=menu,
                    engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                    active_model_name="wrong loop",
                )
            with pytest.raises(RuntimeError, match="UI loop"):
                await prompt.close()

        await asyncio.to_thread(asyncio.run, foreign_calls())
        assert prompt.text == ""
        assert prompt.is_prompt_input_open


def test_static_prompt_contract_accepts_union_and_rejects_invalid_consumers(tmp_path: Path) -> None:
    """Existing mypy checks real structural assignments and meaningful invalid deliveries."""
    import subprocess
    import sys

    contract = (tmp_path / "prompt_contract.py").resolve()
    assert contract.is_relative_to(tmp_path.resolve())
    contract.write_text(
        """from src.tui.components.protocols import ComponentProtocol
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.commands import PromptCommand, ClearSubmissionDAO, ReplacePromptDAO

async def consumers(prompt: PromptInputComponent, narrow: ComponentProtocol[ClearSubmissionDAO]) -> None:
    good: ComponentProtocol[PromptCommand] = prompt
    clear_only: ComponentProtocol[ClearSubmissionDAO] = good
    await good.handle(command=ReplacePromptDAO(text="draft"))
    await good.reset()
    await good.close()
    await good.handle(command=object())
    broad: ComponentProtocol[PromptCommand] = narrow
    await prompt.handle(ClearSubmissionDAO())

class SynchronousPrompt:
    def handle(self, *, command: PromptCommand) -> None: pass
    async def reset(self) -> None: pass
    async def close(self) -> None: pass

wrong: ComponentProtocol[PromptCommand] = SynchronousPrompt()
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-m",
            "mypy",
            "--cache-dir=/dev/null",
            "--follow-imports=silent",
            str(contract),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    diagnostics = [line for line in result.stdout.splitlines() if ": error:" in line]
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(diagnostics) == 4, result.stdout
    assert all(str(contract) in line for line in diagnostics)
    assert sum("[arg-type]" in line for line in diagnostics) == 1
    assert sum("[assignment]" in line for line in diagnostics) == 2
    assert sum("[misc]" in line for line in diagnostics) == 1


async def test_enter_clears_prompt_and_persists_real_turn(tmp_path: Path) -> None:
    """Renamed message routing clears before invocation and keeps native editing usable."""
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(PromptInputComponent)
        component: ComponentProtocol[PromptCommand] = prompt
        prompt.load_text("discard")
        await component.handle(command=ClearSubmissionDAO())
        assert prompt.text == ""  # Applied without a paint barrier.
        await pilot.press("h", "i", "enter")
        async with asyncio.timeout(5):
            while app._in_flight_task is not None:
                await pilot.pause()
        await pilot.pause()
        assert prompt.text == ""
        assert app.focused is prompt
        await pilot.press("x", "shift+enter", "y")
        assert prompt.text == "x\ny"
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        assert [event.payload.content for event in events if event.kind == "user_message"] == ["hi"]
        assert [event.payload.content for event in events if event.kind == "assistant_message"] == [
            "literal answer"
        ]
        assert [event.kind for event in events].index("user_message") < [
            event.kind for event in events
        ].index("run_completed")
        assert (tmp_path / "history" / session.session_id / "events.jsonl").is_file()


async def test_reset_reuses_binding_and_close_preserves_borrowed_menu(tmp_path: Path) -> None:
    """Lifecycle clears recall, rejects terminal delivery, and never closes shared targets."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        component: ComponentProtocol[PromptCommand] = prompt
        await prompt.handle(command=RecordAcceptedPromptDAO(text="old recall"))
        prompt.load_text("draft")
        await component.reset()
        await component.reset()
        assert prompt.text == ""
        await pilot.press("up")
        assert prompt.text == ""
        prompt.load_text("/he")
        await pilot.pause()
        assert not menu.has_class("-hidden")
        await component.handle(command=ClearSubmissionDAO())
        assert menu.has_class("-hidden")
        with pytest.raises(TypeError, match="Unsupported"):
            await component.handle(command=object())  # type: ignore[arg-type]
        prompt.load_text("/he")
        await pilot.pause()
        assert not menu.has_class("-hidden")
        await component.close()
        assert menu.has_class("-hidden")
        await pilot.pause()  # Native message pump remains live after delivery closes.
        await component.close()
        with pytest.raises(RuntimeError, match="closed"):
            await component.reset()
        with pytest.raises(RuntimeError, match="closed"):
            await component.handle(command=ClearSubmissionDAO())
        assert menu.is_mounted
        assert not app._session.is_running
        with pytest.raises(RuntimeError, match="closed"):
            await prompt.bind_suggestions(
                menu=menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name="gpt-5.4",
            )


@pytest.mark.parametrize(argnames="cutoff", argvalues=["reset", "close", "unmount"])
async def test_pending_path_read_cannot_publish_after_prompt_retirement(tmp_path: Path, cutoff: str) -> None:
    """Retirement revokes old output; reset reuses the borrowed reader and real session."""
    target = tmp_path / "old.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    reader = ControlledPathReader()
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session, path_reader=reader)
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(PromptInputComponent)
        menu = app.query_one(SlashSuggestionMenu)
        try:
            await pilot.press(".", "/")
            await pump_until(pilot=pilot, predicate=reader.entered.is_set)
            assert reader.entered.is_set()
            if cutoff == "reset":
                await prompt.reset()
            elif cutoff == "close":
                await prompt.close()
                await prompt.close()
            else:
                await prompt.remove()
            reader.release.set()
            await pump_until(pilot=pilot, predicate=lambda: app._path_suggestions._task is None)
            assert app._path_suggestions._task is None
            assert menu.has_class("-hidden")
            assert not app._path_suggestions._closed
            assert menu.is_mounted
            if cutoff == "reset":
                await pilot.press(".", "/")
                await pump_until(pilot=pilot, predicate=lambda: not menu.has_class("-hidden"))
                assert not menu.has_class("-hidden")
                assert len(reader.calls) == 2
                await prompt.handle(command=ClearSubmissionDAO())
            else:
                with pytest.raises(RuntimeError, match="closed"):
                    await prompt.handle(command=ClearSubmissionDAO())
            assert session.history_store is not None
            assert await session.history_store.load_events(session_id=session.session_id) == []
        finally:
            reader.release.set()
    assert app._path_suggestions._task is None


async def test_draft_revision_advances_at_every_edit_boundary(tmp_path: Path) -> None:
    """A8 (01.2): typing, undo, redo, paste, recall, replace and clear each advance the revision."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(PromptInputComponent)
        component: ComponentProtocol[PromptCommand] = prompt
        revision: int = prompt._draft_revision

        async def advanced(*, action: Callable[[], object]) -> int:
            """Apply one edit boundary and require the revision to advance exactly once."""
            before: int = revision_holder[0]
            result = action()
            if asyncio.iscoroutine(result):
                await result
            await pilot.pause()
            assert prompt._draft_revision == before + 1
            revision_holder[0] = prompt._draft_revision
            return prompt._draft_revision

        revision_holder: list[int] = [revision]
        await advanced(action=lambda: pilot.press("a"))
        assert prompt.text == "a"
        await advanced(action=lambda: prompt.undo())
        assert prompt.text == ""
        await advanced(action=lambda: prompt.redo())
        assert prompt.text == "a"
        await advanced(action=lambda: prompt.replace(insert="bc", start=(0, 1), end=(0, 1)))
        assert prompt.text == "abc"
        await component.handle(command=RecordAcceptedPromptDAO(text="remembered revision"))
        await pilot.pause()
        await advanced(action=lambda: component.handle(command=ClearSubmissionDAO()))
        assert prompt.text == ""
        await advanced(action=lambda: pilot.press("up"))
        assert prompt.text == "remembered revision"
        await advanced(action=lambda: component.handle(command=ReplacePromptDAO(text="replaced")))
        assert prompt.text == "replaced"
        await advanced(action=lambda: component.handle(command=ClearSubmissionDAO()))
        assert prompt.text == ""
        # Editing back to the same text still advances; restoration stays refused.
        await advanced(action=lambda: pilot.press("a"))
        assert prompt.text == "a"
