"""Real headless quota output and persistence with scripted native I/O."""

import asyncio
import json
import io
import sys
from functools import partial
from typing import Optional
from uuid import uuid4
from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.cli.headless import HeadlessRunner
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.bridges.claude.sdk.exceptions import ClaudeQuotaExceededError
from tests.bridges.claude.test_quota_recovery import QuotaThenSuccessTransport, quota_frame
from tests.cli.test_claude_bridge import scripted_adapter_class


async def test_headless_quota_is_one_actionable_durable_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Headless publishes failure exit and one terminal, never provider prose or retry."""
    transport = QuotaThenSuccessTransport(frame=quota_frame())
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="headless-quota",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare_session(config: SessionConfigDAO) -> SloAgentSession:
        """Keep real preparation, SDK parsing, graph and history behind headless."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(15):
        code = await HeadlessRunner(config=config, session_preparer=prepare_session).invoke(prompt="inspect")
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 1
    terminal = [event for event in output if event["kind"] in {"run_failed", "run_completed", "run_aborted"}]
    assert len(terminal) == 1 and terminal[0]["kind"] == "run_failed"
    assert "Claude usage limit reached" in terminal[0]["content"]
    assert "private native diagnostic" not in json.dumps(output)
    assert not any(event["kind"] == "run_retrying" for event in output)
    assert transport.prompts == ["inspect"] and transport.closed
    history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="headless-quota"
    )
    assert sum(event.kind == "run_failed" for event in history) == 1
    assert not any(event.kind in {"run_completed", "run_retrying", "assistant_message"} for event in history)
    failure = next(event for event in history if event.kind == "run_failed")
    assert failure.payload.error_message == terminal[0]["content"]


async def test_child_and_parent_quota_failures_remain_actionable(tmp_path: Path) -> None:
    """Real child headless output crosses process/pool/reporting before parent rejection."""
    history_root = tmp_path / "history"
    child_output = io.StringIO()
    child_transport = QuotaThenSuccessTransport(frame=quota_frame())
    child_config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="quota-child",
        enable_history=True,
        history_root=history_root,
    )

    async def prepare_child(config: SessionConfigDAO) -> SloAgentSession:
        """Keep SDK, headless and durable child session real."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=child_transport)
        )

    code = await HeadlessRunner(
        config=child_config, session_preparer=prepare_child, output_stream=child_output
    ).invoke(prompt="inspect child")
    assert code == 1
    capture = tmp_path / "child-wire.jsonl"
    assert capture.resolve().is_relative_to(tmp_path.resolve())
    capture.write_text(child_output.getvalue(), encoding="utf-8")
    launches: list[tuple[str, ...]] = []

    async def child_wire_spawn(
        *argv: str, stdout: int, stderr: int, limit: int, cwd: Optional[str], env: dict[str, str]
    ) -> asyncio.subprocess.Process:
        """Replace external process I/O with a bounded real pipe carrying headless output."""
        launches.append(argv)
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text(),end='');sys.exit(1)",
            str(capture),
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            cwd=cwd,
            env=env,
        )

    relayed: list[AgentStreamEventDAO] = []

    async def relay(event: AgentStreamEventDAO) -> None:
        """Observe real pool lifecycle and child terminal forwarding."""
        relayed.append(event)

    pool = SubAgentPool(
        orchestrator_session_id="quota-parent",
        default_model="claude-bridge:claude-haiku-5-5",
        relay=relay,
        owner_session_id="quota-parent",
        run_id=str(uuid4()),
        history_root=history_root,
        process_factory=partial(SubAgentProcess, spawn=child_wire_spawn),
    )
    async with asyncio.timeout(20):
        result = await pool.dispatch(
            mode="single",
            tasks=[
                SubAgentTaskDAO(
                    task_id="quota-task",
                    task_summary="Inspect child quota reporting",
                    prompt="inspect child",
                    session_id="quota-child",
                    cwd=str(tmp_path),
                    reasoning_level="off",
                )
            ],
        )
    assert not result.all_completed and result.failed_task_ids == ["quota-task"]
    assert len(launches) == 1 and launches[0][1:4] == ("-I", "-m", "src.cli")
    assert result.results[0].status == "failed"
    assert "Claude usage limit reached" in result.results[0].answer
    assert sum(event.kind == "sub_agent_failed" for event in relayed) == 1
    inbox = SessionInboxStore(history_root=history_root)
    notifier = WorkflowNotifier(
        target_session_id="quota-parent",
        orchestrator_session_id="quota-child",
        workflow_id="wf-synthetic-quota",
        inbox_store=inbox,
    )
    await notifier.failed(error=result.results[0].answer)
    note = await inbox.claim_next(session_id="quota-parent")
    assert note is not None and note.kind == "workflow_failed" and note.delivery_mode == "chat_turn"
    assert "Claude usage limit reached" in note.text
    parent_transport = QuotaThenSuccessTransport(frame=quota_frame())
    parent = await SloAgentSession.prepare(
        config=child_config.model_copy(update={"session_id": "quota-parent"}),
        bridge_adapter_class=scripted_adapter_class(transport=parent_transport),
    )
    try:
        async with asyncio.timeout(15):
            with pytest.raises(ClaudeQuotaExceededError):
                async for _event in parent.invoke(text=note.text):
                    pass
        for session_id in ("quota-child", "quota-parent"):
            events = await FilesystemSessionHistoryStore(root=history_root).load_events(session_id=session_id)
            failures = [event for event in events if event.kind == "run_failed"]
            assert len(failures) == 1 and "Claude usage limit reached" in (
                failures[0].payload.error_message or ""
            )
            assert not any(
                event.kind in {"run_completed", "run_retrying", "route_switched"} for event in events
            )
            assert sum(event.kind == "user_message" for event in events) == 1
        assert child_transport.prompts == ["inspect child"]
        assert parent_transport.prompts == [note.text]
        status = json.loads((history_root / "quota-parent/children/quota-child/status.json").read_text())
        assert status["status"] == "failed" and "Claude usage limit reached" in status["answer"]
        assert len(pool.registry.snapshot()) == 1 and len(launches) == 1
    finally:
        await parent.close_agent_resources()
