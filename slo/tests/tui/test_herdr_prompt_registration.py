"""Mounted prompt-admission cutoff regressions with an offline real session."""

import asyncio
import ast
import inspect
import textwrap
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI


def test_prompt_registration_shutdown_atomic_commit() -> None:
    """The final check has only create/assign and return, with no suspension/hook."""
    module = ast.parse(textwrap.dedent(inspect.getsource(SloTUI._register_prompt_task)))
    method = module.body[0]
    assert isinstance(method, ast.FunctionDef)
    _, guard, assignment, result = method.body
    assert isinstance(guard, ast.If)
    assert ast.unparse(guard.test) == "self._app_closing or self._session_transitioning"
    assert ast.unparse(guard.body[0]) == "return False"
    assert isinstance(assignment, ast.Assign)
    assert ast.unparse(assignment.targets[0]) == "self._in_flight_task"
    assert ast.unparse(assignment.value) == "asyncio.create_task(coro=self._run_prompt(text=text))"
    assert ast.unparse(result) == "return True"
    assert not any(isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)) for node in ast.walk(method))


@pytest.fixture
async def mounted_app(tmp_path: Path) -> AsyncIterator[SloTUI]:
    """Mount a real session with only the model boundary replaced by Faux."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(
                responses=[AIMessage(content="completed"), AIMessage(content="successor completed")]
            ),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            yield app
            if app._in_flight_task is not None:
                await asyncio.wait_for(app._in_flight_task, timeout=5)


@pytest.mark.parametrize("entry", ["manual", "accepted"])
async def test_ordinary_entry_closed(tmp_path: Path, entry: str) -> None:
    """A closed mounted app neither echoes nor records an ordinary submission."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.on_unmount()
            with (
                patch.object(app._chat_transcript, "echo_user", wraps=app._chat_transcript.echo_user) as echo,
                patch.object(app._prompt_history, "record", wraps=app._prompt_history.record) as record,
            ):
                if entry == "manual":
                    await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
                else:
                    async with app._prompt_submission_lock:
                        await app._start_accepted_prompt(text="late")
                assert app._in_flight_task is None
                assert app._queued_prompt_text is None
                echo.assert_not_called()
                record.assert_not_called()


@pytest.mark.parametrize("cutoff", ["local_echo_pending", "queue_remove_pending", "queue_echo_pending"])
async def test_prompt_registration_shutdown(mounted_app: SloTUI, cutoff: str) -> None:
    """Real echo/removal continuations cannot admit a task after public shutdown."""
    app = mounted_app
    entered, release = asyncio.Event(), asyncio.Event()
    seam = "_remove_queued_prompt_block" if cutoff == "queue_remove_pending" else "_echo_user_line"
    original_echo = app._chat_transcript.echo_user
    original_remove = app._remove_queued_prompt_block

    async def echo(*, text: str) -> None:
        """Pause only after actual Textual echo has completed."""
        await original_echo(text=text)
        entered.set()
        await release.wait()

    async def remove() -> None:
        """Pause actual queued-block removal before acceptance resumes."""
        await original_remove()
        entered.set()
        await release.wait()

    finished, drain = asyncio.Event(), asyncio.Event()
    original_refresh = app._refresh_context_window_after_prompt

    async def refresh() -> None:
        """Hold the real first run until its successor is queued."""
        await original_refresh()
        finished.set()
        await drain.wait()

    with patch.object(app, "_refresh_context_window_after_prompt", side_effect=refresh):
        if cutoff != "local_echo_pending":
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="first"))
            await asyncio.wait_for(finished.wait(), timeout=5)
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
        # The registered run has already entered the original finalizer wrapper.
    with patch.object(
        app if cutoff == "queue_remove_pending" else app._chat_transcript,
        "_remove_queued_prompt_block" if cutoff == "queue_remove_pending" else "echo_user",
        side_effect=remove if cutoff == "queue_remove_pending" else echo,
    ):
        submission = app._in_flight_task
        if cutoff == "local_echo_pending":
            submission = asyncio.create_task(
                coro=app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
            )
        assert submission is not None
        drain.set()
        shutdown = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            shutdown = asyncio.create_task(coro=app.on_unmount())
            await asyncio.sleep(0)
            assert app._app_closing
            release.set()
            await asyncio.wait_for(submission, timeout=5)
            assert app._in_flight_task in (None, submission)
            assert app._queued_prompt_text is None
        finally:
            release.set()
            drain.set()
            await asyncio.wait_for(submission, timeout=5)
            if shutdown is not None:
                await asyncio.wait_for(shutdown, timeout=5)


@pytest.mark.parametrize("entry", ["busy_closed", "lock_wait_idle", "lock_wait_busy"])
async def test_prompt_registration_shutdown_submission_gate(mounted_app: SloTUI, entry: str) -> None:
    """Closing refuses both busy entry and callers already waiting for admission."""
    app = mounted_app
    entered, release = asyncio.Event(), asyncio.Event()
    original_refresh = app._refresh_context_window_after_prompt

    async def refresh() -> None:
        """Retain the real registered owner while testing late submissions."""
        await original_refresh()
        entered.set()
        await release.wait()

    task = None
    with patch.object(app, "_refresh_context_window_after_prompt", side_effect=refresh):
        if entry != "lock_wait_idle":
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="first"))
            task = app._in_flight_task
            await asyncio.wait_for(entered.wait(), timeout=5)
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="held"))
        held = app._queued_prompt_text
        block = app._queued_prompt_block
        await app._prompt_submission_lock.acquire()
        submission = asyncio.create_task(
            coro=app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
        )
        shutdown = None
        try:
            if entry != "busy_closed":
                await asyncio.sleep(0)
                assert not submission.done()
            shutdown = asyncio.create_task(coro=app.on_unmount())
            if entry == "busy_closed":
                # Run the public shutdown prefix before this entry is submitted.
                submission.cancel()
                await asyncio.gather(submission, return_exceptions=True)
                await asyncio.sleep(0)
                submission = asyncio.create_task(
                    coro=app.on_prompt_input_submitted(event=PromptInput.Submitted(text="late"))
                )
            await asyncio.sleep(0)
            assert app._app_closing
            app._prompt_submission_lock.release()
            await asyncio.wait_for(submission, timeout=5)
            await asyncio.wait_for(shutdown, timeout=5)
            assert app._in_flight_task is task
            assert app._queued_prompt_text == held
            assert app._queued_prompt_block is block
            assert app._prompt_history._entries == ([] if task is None else ["first"])
        finally:
            if app._prompt_submission_lock.locked():
                app._prompt_submission_lock.release()
            release.set()
            await asyncio.wait_for(submission, timeout=5)
            if task is not None:
                await asyncio.wait_for(task, timeout=5)
            if shutdown is not None:
                await asyncio.wait_for(shutdown, timeout=5)


@pytest.mark.parametrize("entry", ["manual", "inbox", "direct"])
@pytest.mark.parametrize("closing", [False, True])
async def test_prompt_registration_shutdown_entry_matrix(
    mounted_app: SloTUI, entry: str, closing: bool
) -> None:
    """All registration callers share refusal without constructing a run coroutine."""
    app = mounted_app
    if closing:
        await app.on_unmount()
    with patch.object(app, "_run_prompt", wraps=app._run_prompt) as run:
        async with app._prompt_submission_lock:
            if entry == "direct":
                assert app._register_prompt_task(text="selected") is (not closing)
            elif entry == "inbox":
                message = SessionInboxMessageDAO(
                    session_id=app._session.session_id,
                    schedule_id="schedule",
                    run_id="run",
                    kind="system_notice",
                    delivery_mode="chat_turn",
                    text="selected",
                )
                assert await app._start_inbox_chat_turn(message=message) is (not closing)
            else:
                await app._start_accepted_prompt(text="selected")
            task = app._in_flight_task
            assert run.call_count == int(not closing)
        if task is not None:
            await asyncio.wait_for(task, timeout=5)
        assert app._queued_prompt_text is None
        assert app._prompt_history._entries == (["selected"] if entry == "manual" and not closing else [])


@pytest.mark.parametrize("entry", ["submitted_slash", "direct_slash"])
async def test_prompt_registration_shutdown_slash(mounted_app: SloTUI, entry: str) -> None:
    """Slash routing remains available and does not register an ordinary run."""
    app = mounted_app
    await app.on_unmount()
    with patch.object(app, "_run_prompt", wraps=app._run_prompt) as run:
        if entry == "direct_slash":
            await app._dispatch_slash_command(line="/help")
        else:
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="/help"))
        run.assert_not_called()
    assert app._prompt_history._entries == []
    assert app._in_flight_task is None
    assert app._queued_prompt_text is None


@pytest.mark.parametrize("entry", ["manual", "inbox"])
@pytest.mark.parametrize("policy", ["complete", "interrupt", "slash_abort"])
async def test_prompt_registration_shutdown_preexecution(
    mounted_app: SloTUI, policy: str, entry: str
) -> None:
    """Pre-cutoff registration keeps identity and execution/abort policy after close."""
    app = mounted_app
    entered, release = asyncio.Event(), asyncio.Event()
    original_spinner = app._mount_spinner

    async def spinner() -> None:
        """Stop the real run immediately before session invocation."""
        await original_spinner()
        entered.set()
        await release.wait()

    with (
        patch.object(app, "_mount_spinner", side_effect=spinner),
        patch.object(app._session, "invoke", wraps=app._session.invoke) as invoke,
        patch.object(app._session, "abort", wraps=app._session.abort) as abort,
    ):
        if entry == "manual":
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="first"))
        else:
            assert app._inbox_timer is not None
            app._inbox_timer.stop()
            store = app._inbox_store
            assert store is not None
            message = SessionInboxMessageDAO(
                session_id=app._session.session_id,
                schedule_id="schedule",
                run_id="run",
                kind="system_notice",
                delivery_mode="chat_turn",
                text="first",
            )
            await store.enqueue(message=message)
            await app._poll_session_inbox()
            assert await store.claim_next(session_id=app._session.session_id) is None
            assert app._prompt_history._entries == []
        task = app._in_flight_task
        assert task is not None
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            invoke.assert_not_called()
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="held"))
            await app.on_unmount()
            assert app._in_flight_task is task
            assert task.cancelling() == 0
            abort.assert_not_called()
            if policy == "interrupt":
                await app.action_interrupt()
            elif policy == "slash_abort":
                await app._dispatch_slash_command(line="/abort")
            assert abort.call_count == int(policy != "complete")
            release.set()
            await asyncio.wait_for(task, timeout=5)
            invoke.assert_called_once_with(text="first")
            assert app._in_flight_task is None
            assert app._queued_prompt_text == "held"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=5)


async def test_prompt_registration_open_queue_and_new(mounted_app: SloTUI) -> None:
    """Open admission preserves input, history, latest-wins and busy/new policy."""
    app = mounted_app
    entered, release = asyncio.Event(), asyncio.Event()
    original_refresh = app._refresh_context_window_after_prompt

    async def refresh() -> None:
        """Hold a completed first run before the real queued handoff."""
        await original_refresh()
        entered.set()
        await release.wait()

    with patch.object(app, "_refresh_context_window_after_prompt", side_effect=refresh):
        await app.on_prompt_input_submitted(event=PromptInput.Submitted(text=" first "))
        first = app._in_flight_task
        assert first is not None
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="older"))
            block = app._queued_prompt_block
            assert app._input is not None
            app._input.load_text("latest")
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="latest"))
            assert app._input.text == ""
            assert app._queued_prompt_block is block
            assert app._queued_prompt_text == "latest"
            assert app._prompt_history._entries == ["first"]
            session = app._session
            await app._dispatch_slash_command(line="/new")
            assert app._session is session
            assert app._queued_prompt_text == "latest"
            release.set()
            await asyncio.wait_for(first, timeout=5)
            successor = app._in_flight_task
            assert successor is not None and successor is not first
            await asyncio.wait_for(successor, timeout=5)
            assert app._prompt_history._entries == ["first", "latest"]
            assert app._queued_prompt_text is None
            assert app._queued_prompt_block is None
            await app._dispatch_slash_command(line="/new")
            assert app._session is not session
            assert app._in_flight_task is None
        finally:
            release.set()
            await asyncio.wait_for(first, timeout=5)


async def test_prompt_registration_shutdown_registered_completion(mounted_app: SloTUI) -> None:
    """An admitted real run settles without consuming its held successor at close."""
    app = mounted_app
    entered, release = asyncio.Event(), asyncio.Event()
    original_refresh = app._refresh_context_window_after_prompt

    async def refresh() -> None:
        """Hold the actual run's finalizer after its Faux execution."""
        await original_refresh()
        entered.set()
        await release.wait()

    with patch.object(app, "_refresh_context_window_after_prompt", side_effect=refresh):
        await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="first"))
        task = app._in_flight_task
        assert task is not None
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await app.on_prompt_input_submitted(event=PromptInput.Submitted(text="held"))
            assert app._queued_prompt_text == "held"
            await app.on_unmount()
            assert app._in_flight_task is task
            assert not task.cancelled()
            with patch.object(
                app._chat_transcript, "echo_user", wraps=app._chat_transcript.echo_user
            ) as echo:
                release.set()
                await asyncio.wait_for(task, timeout=5)
                echo.assert_not_called()
            assert app._in_flight_task is None
            assert app._queued_prompt_text == "held"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=5)
