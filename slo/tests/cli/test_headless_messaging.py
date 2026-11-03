"""Opt-in real HeadlessRunner messaging journeys with only a vendor model substitute."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.cli.headless import HeadlessRunner
from src.agents.base import LLMBuildResult
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.agents.slo_agent.messaging.test_queue_closure import submission, wait_until


@pytest.mark.parametrize(argnames="abort_second", argvalues=[False, True])
async def test_second_run_settles_without_second_publish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], abort_second: bool
) -> None:
    """The host publishes once; a second externally admitted run determines finite exit."""
    # A held render subscriber uses the existing public subscription seam to admit
    # input after the first provider has decided to end its run, before settlement.
    model = RecordingModel(responses=[AIMessage(content="first"), AIMessage(content="second")])
    config = SessionConfigDAO(
        workdir=tmp_path,
        history_root=tmp_path / "history",
        enable_history=True,
        model_name="claude-sonnet-4-6",
    )
    runner = HeadlessRunner(config=config, messaging_enabled=True)
    task = None
    client = None
    try:
        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
        ):
            task = asyncio.create_task(runner.invoke(prompt="initial"))
            await asyncio.wait_for(model.entered.wait(), timeout=5)
            session = runner._session
            assert session is not None
            client = LocalSessionMessagingClient(
                session=session, target=session.messaging_target, principal=session.messaging_owner_principal
            )
            published = False

            async def admit_after_terminal(event: AgentStreamEventDAO) -> None:
                """Admit only after the agent ended, requiring the scheduler's next run."""
                nonlocal published
                if abort_second and published and event.kind == "text_start":
                    session.abort()
                if event.kind == "run_completed" and not published:
                    published = True
                    await client.submit(
                        submission=submission(target=session.messaging_target, text="external second")
                    )

            session.subscribe(handler=admit_after_terminal)
            model.release.set()
            assert await asyncio.wait_for(task, timeout=5) == (2 if abort_second else 0)
            assert session._messaging_scheduler is not None and session._messaging_note_task is not None
            assert session._messaging_scheduler.done() and session._messaging_note_task.done()
            assert len(model.requests) == 2
            import sqlite3

            assert config.history_root is not None
            path = config.history_root / session.session_id / "messaging.v1.sqlite3"
            assert path.resolve().is_relative_to(tmp_path.resolve())
            with sqlite3.connect(path) as connection:
                rows = connection.execute(
                    "SELECT state, submission_json FROM messages ORDER BY sequence"
                ).fetchall()
            assert [state for state, _ in rows] == ["applied", "applied"]
            assert [json.loads(body)["text"] for _, body in rows] == ["initial", "external second"]
            terminals = [
                json.loads(line)
                for line in capsys.readouterr().out.splitlines()
                if line.startswith('{"kind"')
            ]
            settled = [event for event in terminals if event["kind"] in ("run_completed", "run_aborted")]
            assert settled[0]["content"] == "first"
            assert len(settled) == 2
            assert settled[-1]["kind"] == ("run_aborted" if abort_second else "run_completed")
            if not abort_second:
                assert settled[-1]["content"] == "second"
    finally:
        model.release.set()
        if client is not None:
            await client.close()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


async def test_hard_abort_stops_actual_scheduler(tmp_path: Path) -> None:
    """Host grace escalation stops a never-released provider and preserves pending input."""
    model = RecordingModel(responses=[AIMessage(content="unreachable")])
    runner = HeadlessRunner(
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            enable_history=True,
            model_name="claude-sonnet-4-6",
        ),
        messaging_enabled=True,
    )
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
    ):
        task = asyncio.create_task(runner.invoke(prompt="held"))
        try:
            await asyncio.wait_for(model.entered.wait(), timeout=5)
            assert runner._session is not None
            session = runner._session
            await session.admit_message(
                submission=submission(target=session.messaging_target, text="pending"),
                principal=session.messaging_owner_principal,
            )
            runner._request_cooperative_abort("operator_abort")
            assert await asyncio.wait_for(task, timeout=10) == 2
            assert session._messaging_scheduler is not None and session._messaging_note_task is not None
            assert session._messaging_scheduler.done()
            assert not model.release.is_set()
            import sqlite3

            path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
            assert path.resolve().is_relative_to(tmp_path.resolve())
            with sqlite3.connect(path) as connection:
                assert connection.execute(
                    "SELECT state, retained FROM messages ORDER BY sequence"
                ).fetchall() == [("applied", 0), ("accepted", 1)]
        finally:
            model.release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_runner_joins_actual_execution(tmp_path: Path) -> None:
    """Cancelling the host cannot strand its scheduler or skip messaging resource close."""
    model = RecordingModel(responses=[AIMessage(content="unreachable")])
    runner = HeadlessRunner(
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            enable_history=True,
            model_name="claude-sonnet-4-6",
        ),
        messaging_enabled=True,
    )
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
    ):
        task = asyncio.create_task(runner.invoke(prompt="held"))
        try:
            await asyncio.wait_for(model.entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            session = runner._session
            assert session is not None and session._messaging_scheduler is not None
            assert session._messaging_scheduler.done()
            assert not session.is_messaging_ready
            assert not model.release.is_set()
        finally:
            model.release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_legacy_runner_refuses_store_presence_without_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DC09 rollback: even an empty messaging file blocks the real legacy runner."""
    from uuid import uuid4

    session_id = str(uuid4())
    path = tmp_path / "history" / session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    model = RecordingModel(responses=[])
    runner = HeadlessRunner(
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            session_id=session_id,
            enable_history=True,
            model_name="claude-sonnet-4-6",
        ),
        messaging_enabled=False,
    )
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
    ):
        assert await runner.invoke(prompt="forbidden") == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"kind"')]
    assert any(
        event["kind"] == "run_failed"
        and event["content"] == "This session has durable messages; use a messaging-enabled Slo."
        for event in events
    )
    assert model.requests == []
