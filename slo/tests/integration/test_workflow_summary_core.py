"""Actual dispatch to mounted literal row and original detail, without inference."""

import asyncio
import hashlib
import json
import importlib.util
import subprocess
import sys
from types import ModuleType
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from textual.widgets import Static

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber, SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI, PromptInput
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.session_progress_screen import SessionProgressScreen
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
from tests.tui.workflows.test_session_snapshot import _handle
from tests.tui.authentication._painted_output import (
    painted_text,
    painted_widget_strips,
    wait_for_condition,
)

SUMMARY_PAIRS = [
    (
        "You own Step 1. Read AGENTS.md. Resolve family 98 visibility and summary contract gaps. "
        "Do not spawn or commit; preserve the branch.",
        "Resolve family 98 visibility and summary contract gaps",
    ),
    ("Summarize the supplied text; no approval gate is involved.", "Summarize the supplied text"),
    (
        "Shorten this summary without changing its meaning: {previous}",
        "Shorten the supplied summary without changing meaning",
    ),
    (
        "Please compare the branch naming rules with repository policy.",
        "Compare branch naming rules with repository policy",
    ),
    (
        "Read AGENTS.md. Contrast [branch] commit and spawn policies; do not execute them.",
        "Contrast [branch] commit and spawn policies",
    ),
]


class FiniteProcess(SubAgentProcess):
    """Real wrapper with finite public execution and fixture-owned bindings."""

    bound_task: SubAgentTaskDAO
    bound_registry: ProcessRegistry
    entered: asyncio.Event
    release: asyncio.Event

    async def run(self) -> SubAgentResultDAO:
        """Expose pending publication, then finish through registry arbitration."""
        self.entered.set()
        await self.release.wait()
        return await self.finish_without_spawn(
            result=SubAgentResultDAO(
                task_id=self.bound_task.task_id,
                session_id=self.session_id,
                execution_id=self.execution_id,
                status="completed",
                exit_code=0,
                answer="Compared policy",
            ),
            terminal_reason="completed",
            terminated_by="natural",
        )


class FiniteFactory:
    """Capture public construction inputs; write only matching temp-owned detail."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.process: Optional[FiniteProcess] = None

    def __call__(
        self,
        *,
        task: SubAgentTaskDAO,
        session_id: str,
        model: Optional[str],
        relay: AgentEventSubscriber,
        registry: ProcessRegistry,
        execution_id: str,
        system_prompt: str,
        parent_session_id: str,
        history_root: Path,
    ) -> SubAgentProcess:
        """Bind a finite wrapper without launching transport."""
        process = FiniteProcess(
            task=task,
            session_id=session_id,
            model=model,
            relay=relay,
            registry=registry,
            execution_id=execution_id,
            system_prompt=system_prompt,
            parent_session_id=parent_session_id,
            history_root=history_root,
        )
        process.bound_task = task
        process.bound_registry = registry
        process.entered = self.entered
        process.release = self.release
        self.process = process
        return process


@pytest.fixture(scope="module")
def released_readers(tmp_path_factory: pytest.TempPathFactory) -> tuple[ModuleType, ModuleType]:
    """Execute exact BASE model sources from read-only Git extraction in a temp directory."""
    directory = tmp_path_factory.mktemp("summary-released-readers")
    modules: list[ModuleType] = []
    for filename in ("dao", "context_dao"):
        source = subprocess.run(
            [
                "git",
                "show",
                f"4c0133c448a6ee7b79f5266ae80d94ab2c4659a9:slo/src/agents/slo_agent/orchestrator/{filename}.py",
            ],
            check=True,
            capture_output=True,
        ).stdout
        path = directory / f"{filename}.py"
        assert path.resolve().is_relative_to(directory.resolve())
        path.write_bytes(source)
        name = f"summary_base_{filename}"
        spec = importlib.util.spec_from_file_location(name=name, location=path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules[0], modules[1]


def assert_released_files(
    *, root: Path, prompt: str, child_id: str, readers: tuple[ModuleType, ModuleType]
) -> None:
    """Decode actual newly published bytes with BASE closed models and exact key oracles."""
    dao, context = readers
    directory = root / "summary-owner" / "children" / child_id
    fleet_bytes = (root / "summary-owner" / "fleet.json").read_bytes()
    status_bytes = (directory / "status.json").read_bytes()
    context_bytes = (directory / "spawn_context.json").read_bytes()
    fleet = dao.FleetSnapshotDAO.model_validate_json(fleet_bytes)
    status = dao.SubAgentResultDAO.model_validate_json(status_bytes)
    spawn = context.SpawnContextDAO.model_validate_json(context_bytes)
    assert fleet.entries[0].session_id == status.session_id == child_id
    assert status.status == "completed"
    assert spawn.prompt == prompt
    assert set(json.loads(fleet_bytes)) == {"orchestrator_session_id", "workflow_id", "entries", "updated_at"}
    assert set(json.loads(fleet_bytes)["entries"][0]) == {
        "task_id",
        "session_id",
        "status",
        "last_text",
        "prompt_preview",
        "last_heartbeat_at",
        "last_stdout_at",
        "pid",
        "started_at",
        "heartbeat_phase",
        "exit_code",
        "terminal_reason",
        "terminated_by",
    }
    assert set(json.loads(status_bytes)) == {
        "task_id",
        "session_id",
        "status",
        "answer",
        "exit_code",
        "usage",
        "failure_code",
        "partial_output_committed",
        "attempts",
        "safe_message",
    }
    assert set(json.loads(context_bytes)) == {
        "task_id",
        "prompt",
        "inactivity_timeout_seconds",
        "system_prompt",
        "recorded_at",
    }
    for model in (
        dao.FleetSnapshotDAO,
        dao.SubAgentStatusDAO,
        dao.SubAgentResultDAO,
        context.SpawnContextDAO,
    ):
        assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize("theme", ["slo-dark", "slo-default"])
@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize(
    "prompt,label,child_id",
    [(p, l, "summary-child") for p, l in SUMMARY_PAIRS]
    + [(SUMMARY_PAIRS[-1][0], SUMMARY_PAIRS[-1][1], "summary-child-" + "long-identity-" * 5)],
)
async def test_task_summary_survives_registration_to_detail(
    tmp_path: Path,
    theme: str,
    size: tuple[int, int],
    detached: bool,
    prompt: str,
    label: str,
    released_readers: tuple[ModuleType, ModuleType],
    child_id: str,
) -> None:
    """Pending and terminal rows retain literal label; hide/show and Enter retain detail."""
    root = tmp_path / "history"
    factory = FiniteFactory()
    events: list[AgentStreamEventDAO] = []

    async def relay(event: AgentStreamEventDAO) -> None:
        """Capture lifecycle output without invoking a provider or terminal."""
        events.append(event)

    pool = SubAgentPool(
        orchestrator_session_id="summary-owner",
        default_model=None,
        relay=relay,
        owner_session_id="summary-owner",
        run_id=str(uuid4()),
        history_root=root,
        process_factory=factory,
    )
    tool = SpawnSubAgentsTool.build(pool=pool)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="summary-owner",
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="claude-sonnet-4-6", history_root=root, enable_history=True
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    if detached:
        await WorkflowHandleStore(history_root=root).write(
            handle=_handle(
                workflow_id="wf-summary",
                owner_session_id="summary-owner",
                orchestrator_session_id="summary-owner",
                state="stalled",
            )
        )
    else:
        session.attach_sub_agent_pool(pool=pool, spawn_tools=[tool])
    app = SloTUI(session=session)
    async with app.run_test(size=size) as pilot:
        app.theme = theme
        task = asyncio.create_task(
            tool.ainvoke(
                {
                    "mode": "single",
                    "tasks": [
                        {
                            "task_id": "compare",
                            "session_id": child_id,
                            "prompt": prompt,
                            "task_summary": label,
                        }
                    ],
                }
            )
        )
        try:
            await asyncio.wait_for(factory.entered.wait(), timeout=5)
            # A real command requests coalesced observation without private timer access.
            editor = app.query_one(PromptInput)
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            panel = app.query_one(SubAgentFleetPanel)
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: any(row.row.role == "child" for row in panel.query(SubAgentFleetRow)),
                description="pending child fleet row is mounted",
            )
            child = next(row for row in panel.query(SubAgentFleetRow) if row.row.role == "child")
            assert str(child.query_one(Static).render()) == f"[pending] {child_id}: {label}"
            assert child.row.task_summary == label
            panel.focus_sessions()
            await pilot.press("down")
            await pilot.pause()
            painted = painted_text(strips=painted_widget_strips(app=app, widget=child))
            expected = f"[pending] {child_id}: {label}"
            # Rows intentionally clip horizontally; compare actual visible literal cells.
            assert painted and "".join(expected.split()).startswith(painted.removesuffix("…"))
            assert "[pending]summary-child" in painted
            editor.focus()
            process = factory.process
            assert process is not None
            assert process.bound_task.prompt == prompt
            assert process.bound_task.task_summary == label
            fleet = json.loads((root / "summary-owner" / "fleet.json").read_text())
            assert fleet["entries"][0]["prompt_preview"] == "Task summary v1: " + label
            directory = root / "summary-owner" / "children" / child_id
            assert directory.resolve().is_relative_to(tmp_path.resolve())
            data = dump_json_bytes(
                SpawnContextDAO.build(
                    task_id="compare",
                    prompt=prompt,
                    system_prompt="",
                    inactivity_timeout_seconds=1.0,
                    model=None,
                    reasoning_level=None,
                    cwd=None,
                    execution_id=process.execution_id,
                )
            )
            (directory / "spawn_context.json").write_bytes(data)
            process.bound_registry.mark_running(
                session_id=process.session_id,
                execution_id=process.execution_id,
                spawn_context_sha256=hashlib.sha256(data).hexdigest(),
            )
            factory.release.set()
            await task
            assert_released_files(root=root, prompt=prompt, child_id=child_id, readers=released_readers)
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: any(row.row.role == "child" for row in panel.query(SubAgentFleetRow)),
                description="completed child fleet row is mounted",
            )
            child = next(row for row in panel.query(SubAgentFleetRow) if row.row.role == "child")
            original_key = child.row.key
            assert child.row.task_summary == label
            assert child.row.task_text == prompt
            editor.text = "/workflows tui dismiss"
            await pilot.press("enter")
            assert list(panel.query(SubAgentFleetRow)) == []
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: any(row.row.role == "child" for row in panel.query(SubAgentFleetRow)),
                description="re-shown child fleet row is mounted",
            )
            child = next(row for row in panel.query(SubAgentFleetRow) if row.row.role == "child")
            assert child.row.task_summary == label
            assert child.row.task_text == prompt
            assert child.row.task_text_complete
            assert child.row.key == original_key
            assert str(child.query_one(Static).render()) == f"[completed] {child_id}: {label}"
            panel.focus_sessions()
            await pilot.press("down", "enter")
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: isinstance(app.screen, SessionProgressScreen),
                description="session progress screen is mounted",
            )
            assert isinstance(app.screen, SessionProgressScreen)
            assert str(app.screen.query_one("#task-description", Static).render()) == prompt
            assert [event.content for event in events if event.kind == "sub_agent_spawned"] == [
                "Task summary v1: " + label
            ]
        finally:
            factory.release.set()
            await task
