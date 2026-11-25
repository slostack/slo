"""Multi-process channel journeys O1, O3 (108.3) and C1 (108.4) — end-to-end.

Two real processes share one SQLite queue under ``tmp_path``: this pytest
process runs the real ``SloTUI`` (Textual Pilot), and a real Python subprocess
runs the production ``HeadlessRunner`` as the workflow orchestrator W
(``--notify-session`` mode) or as a pool child C (``SLO_CHANNEL_PARENT_ID``).
The only substitute is the LLM provider: inside the subprocess a
``FauxChatModel`` whose first call waits for a release file and which records
every call's context to a JSON file. Nothing reaches a real provider, and
everything is written under ``tmp_path`` (including ``SLO_HOME``).

What this cannot prove: real provider streaming, and the ``slo run`` argv /
``SubAgentProcess`` spawn path (covered by the orchestrator integration tests).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.widgets import Input

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ParticipantDAO, SentMessageRowDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.app import SloTUI
from src.tui.components.agent_composer.component import AgentComposerComponent
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.workflows.dao import WorkflowSessionKeyDAO
from tests.tui._scroll_settle import pump_until
from tests.conftest import GatedFauxChatModel
from tests.tui.test_channel_adapter import _transcript_lines

pytestmark = pytest.mark.e2e

_HEADLESS_AGENT_SCRIPT: str = r"""
import asyncio, json, os, sys
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, Optional
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import Field
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.cli.headless import HeadlessRunner


class FileGatedFauxChatModel(FauxChatModel):
    release_path: str = Field(description="First call waits until this file exists.")
    record_path: str = Field(description="JSON file receiving every call's message texts.")

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "FileGatedFauxChatModel":
        clone: FileGatedFauxChatModel = FileGatedFauxChatModel(
            responses=list(self.queue), release_path=self.release_path, record_path=self.record_path
        )
        clone.bound_tools = list(tools)
        return clone

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        record: Path = Path(self.record_path)
        contexts: list[list[str]] = json.loads(record.read_text()) if record.exists() else []
        contexts.append([str(message.content) for message in messages])
        record.write_text(json.dumps(contexts))
        if len(contexts) == 1:
            while not Path(self.release_path).exists():
                await asyncio.sleep(0.02)
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


async def main() -> int:
    env: dict[str, str] = dict(os.environ)
    repository = ChannelRepository(db_path=Path(env["E2E_DB"]))
    await repository.open()
    gateway = ChannelGateway(repository=repository)
    session_id = env["E2E_SESSION_ID"]
    workdir = Path(env["E2E_WORKDIR"])
    model = FileGatedFauxChatModel(
        responses=[AIMessage(content=env["E2E_FIRST_ANSWER"]), AIMessage(content=env["E2E_SECOND_ANSWER"])],
        release_path=env["E2E_RELEASE"],
        record_path=env["E2E_RECORD"],
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        return SloAgentSession(
            agent=SloAgent(llm=model, cwd=str(workdir), tools=list(config.extra_tools or [])),
            workdir=workdir,
            session_id=session_id,
            history_store=FilesystemSessionHistoryStore(root=Path(env["E2E_HISTORY"])),
            enable_history=True,
        )

    runner = HeadlessRunner(
        config=SessionConfigDAO(workdir=workdir, model_name="faux", enable_history=False, session_id=session_id),
        notify_session_id=env.get("E2E_NOTIFY_SESSION") or None,
        session_preparer=prepare,
        channel_gateway=gateway,
        history_root=Path(env["E2E_HISTORY"]),
    )
    try:
        return await runner.invoke(prompt="e2e task")
    finally:
        await gateway.close()


sys.exit(asyncio.run(main()))
"""


class HeadlessAgentProcess:
    """A real headless agent subprocess owned by one test (always reaped)."""

    def __init__(self, *, tmp_path: Path, session_id: str, extra_env: dict[str, str]) -> None:
        """Lay out the subprocess's private files and environment."""
        self.session_id: str = session_id
        self.release_path: Path = tmp_path / f"{session_id}.release"
        self.record_path: Path = tmp_path / f"{session_id}.contexts.json"
        self.output_path: Path = tmp_path / f"{session_id}.stdout.jsonl"
        self._env: dict[str, str] = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path.cwd()),
            "SLO_ENV": "test",
            "SLO_HERDR_DISABLED": "1",
            "SLO_AUTO_VISUALIZE": "0",
            "SLO_HOME": str(tmp_path / "slo-home"),
            "SLO_CHANNEL_POLL_MS": "50",
            "SLO_HEADLESS_HEARTBEAT_SECONDS": "0.2",
            "E2E_DB": str(tmp_path / "channels.db"),
            "E2E_SESSION_ID": session_id,
            "E2E_WORKDIR": str(tmp_path),
            "E2E_HISTORY": str(tmp_path / f"{session_id}-history"),
            "E2E_RELEASE": str(self.release_path),
            "E2E_RECORD": str(self.record_path),
            **extra_env,
        }
        self._process: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> None:
        """Start the subprocess with stdout captured to a file."""
        with self.output_path.open("wb") as output:
            self._process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", _HEADLESS_AGENT_SCRIPT, env=self._env, stdout=output, stderr=output
            )

    def release_first_call(self) -> None:
        """Let the subprocess's held first provider call finish."""
        self.release_path.write_text("go", encoding="utf-8")

    async def wait(self, *, timeout_seconds: float) -> int:
        """Wait for exit and return the exit code."""
        assert self._process is not None
        return await asyncio.wait_for(self._process.wait(), timeout=timeout_seconds)

    def recorded_contexts(self) -> list[list[str]]:
        """Return the texts of every provider call the subprocess made."""
        if not self.record_path.exists():
            return []
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    async def kill_if_running(self) -> None:
        """Kill and reap the subprocess when a test failed before it exited."""
        if self._process is not None and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open the shared queue this process uses."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


def _tui_session(*, tmp_path: Path, model: GatedFauxChatModel) -> SloAgentSession:
    """Build the TUI's own session with the gated provider double."""
    return SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "tui-history"),
        enable_history=True,
    )


async def _wait_for_db(*, predicate: Callable[[], object], timeout_seconds: float = 30.0) -> None:
    """Poll an async queue predicate until it holds."""
    async with asyncio.timeout(timeout_seconds):
        while not await predicate():  # type: ignore[misc]
            await asyncio.sleep(0.05)


async def _mount_composer(*, app: SloTUI, key: WorkflowSessionKeyDAO) -> AgentComposerComponent:
    """Mount the workflow modal's composer for one row onto the current screen."""
    composer: Optional[AgentComposerComponent] = app.progress_composer_for(key=key)
    assert composer is not None
    await app.screen.mount(composer)
    return composer


async def _rows(*, composer: AgentComposerComponent, app: SloTUI) -> list[SentMessageRowDAO]:
    """Return the composer's rows straight from the queue."""
    assert app._channel_adapter is not None
    return await app._channel_adapter.sent_to_agent(session_id=str(composer.target_agent_id))


async def test_o1_o3_workflow_notes_reach_a_busy_tui_and_a_forced_modal_message_reaches_w(
    tmp_path: Path,
) -> None:
    """O1: W's notes show as ⊛ lines while the TUI runs. O3: a forced modal send enters W's next call, row ✓."""
    release_tui_run: asyncio.Event = asyncio.Event()
    tui_model: GatedFauxChatModel = GatedFauxChatModel(
        responses=[AIMessage(content="busy answer"), AIMessage(content="workflow acknowledged")],
        first_call_release=release_tui_run,
    )
    session: SloAgentSession = _tui_session(tmp_path=tmp_path, model=tui_model)
    gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
    workflow_session_id: str = str(uuid4())
    workflow: HeadlessAgentProcess = HeadlessAgentProcess(
        tmp_path=tmp_path,
        session_id=workflow_session_id,
        extra_env={
            "E2E_NOTIFY_SESSION": session.session_id,
            "SLO_WORKFLOW_ID": "wf-e2e1",
            "E2E_FIRST_ANSWER": "phase answer",
            "E2E_SECOND_ANSWER": "skipped phase 3 as asked",
        },
    )
    app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            poller = session.channel_poller
            assert poller is not None
            prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
            prompt_input.text = "long question"
            await pilot.press("enter")
            await pump_until(pilot=pilot, predicate=lambda: poller.busy, max_cycles=200)
            assert poller.busy is True, (
                poller.paused,
                session.preparation_status,
                _transcript_lines(app=app),
            )

            await workflow.start()
            # O1: the workflow's started note shows while the TUI run is in flight.
            await pump_until(
                pilot=pilot,
                predicate=lambda: any(
                    "⊛" in content and "wf-e2e1" in content
                    for content, _classes in _transcript_lines(app=app)
                ),
                max_cycles=600,
            )
            star_lines: list[str] = [
                content for content, _classes in _transcript_lines(app=app) if "⊛" in content
            ]
            assert star_lines, _transcript_lines(app=app)
            assert poller.busy is True and not release_tui_run.is_set(), star_lines

            # O3: a forced message from W's modal composer (Ctrl+Enter).
            composer: AgentComposerComponent = await _mount_composer(
                app=app,
                key=WorkflowSessionKeyDAO(
                    orchestrator_session_id=workflow_session_id, session_id=workflow_session_id
                ),
            )
            composer.query_one("#agent-composer-input", Input).focus()
            composer.query_one("#agent-composer-input", Input).value = "skip phase 3 review"
            await pilot.press("ctrl+enter")
            await pump_until(
                pilot=pilot, predicate=lambda: bool(workflow.recorded_contexts()), max_cycles=400
            )

            async def _sent() -> bool:
                return len(await _rows(composer=composer, app=app)) == 1

            await _wait_for_db(predicate=_sent)
            await asyncio.sleep(1.0)  # W's 50 ms poller refreshes its forced snapshot
            workflow.release_first_call()
            assert await workflow.wait(timeout_seconds=60.0) == 0

            contexts: list[list[str]] = workflow.recorded_contexts()
            assert len(contexts) == 2
            assert "skip phase 3 review" not in contexts[0]
            assert contexts[1].count("skip phase 3 review") == 1
            await composer.refresh_delivery_state()
            rows: list[SentMessageRowDAO] = await _rows(composer=composer, app=app)
            assert [(row.state, row.forced) for row in rows] == [("accepted", True)]
            assert "✓ (forced) skip phase 3 review" in str(
                composer.query_one(".agent-composer-rows").render()
            )
            release_tui_run.set()
    finally:
        release_tui_run.set()
        await workflow.kill_if_running()
        await gateway.close()


async def test_c1_forced_modal_message_reaches_a_running_child_at_its_next_boundary(tmp_path: Path) -> None:
    """C1: Enter in a child row's composer sends forced; the child's next call carries it."""
    gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
    parent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
    child_session_id: str = str(uuid4())
    child: HeadlessAgentProcess = HeadlessAgentProcess(
        tmp_path=tmp_path,
        session_id=child_session_id,
        extra_env={
            "SLO_CHANNEL_PARENT_ID": str(parent.id),
            "SLO_CHANNEL_PARTICIPANT_NAME": f"review-1 (child of {str(parent.id)[:8]})",
            "SLO_HEADLESS_FOLLOWUP_TURNS": "0",
            "E2E_FIRST_ANSWER": "reviewed everything",
            "E2E_SECOND_ANSWER": "reviewed only src/tui",
        },
    )
    tui_model: GatedFauxChatModel = GatedFauxChatModel(
        responses=[AIMessage(content="unused")], first_call_release=asyncio.Event()
    )
    app: SloTUI = SloTUI(session=_tui_session(tmp_path=tmp_path, model=tui_model), channel_gateway=gateway)
    try:
        await child.start()

        async def _child_open() -> bool:
            participant: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=UUID(child_session_id)
            )
            return (
                participant is not None and participant.status == "open" and bool(child.recorded_contexts())
            )

        await _wait_for_db(predicate=_child_open)
        async with app.run_test() as pilot:
            await pilot.pause()
            composer: AgentComposerComponent = await _mount_composer(
                app=app,
                key=WorkflowSessionKeyDAO(
                    orchestrator_session_id=str(parent.id), session_id=child_session_id
                ),
            )
            assert composer.default_force is True
            composer.query_one("#agent-composer-input", Input).focus()
            composer.query_one("#agent-composer-input", Input).value = "only review src/tui"
            await pilot.press("enter")

            async def _sent() -> bool:
                return len(await _rows(composer=composer, app=app)) == 1

            await _wait_for_db(predicate=_sent)
            await asyncio.sleep(1.0)  # the child's 50 ms poller refreshes its forced snapshot
            child.release_first_call()
            assert await child.wait(timeout_seconds=60.0) == 0

            contexts: list[list[str]] = child.recorded_contexts()
            assert len(contexts) == 2
            assert contexts[1].count("only review src/tui") == 1
            rows: list[SentMessageRowDAO] = await _rows(composer=composer, app=app)
            assert [(row.state, row.forced) for row in rows] == [("accepted", True)]
            closed: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=UUID(child_session_id)
            )
            assert closed is not None and closed.status == "closed"
    finally:
        await child.kill_if_running()
        await gateway.close()
