"""Actual dispatch to mounted literal row and original detail, without inference."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Any
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
from langchain_core.tools import BaseTool
from textual.widgets import Static
from textual.pilot import Pilot
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore

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
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
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


SUMMARY_CASES = [(p, label, "summary-child") for p, label in SUMMARY_PAIRS] + [
    (SUMMARY_PAIRS[-1][0], SUMMARY_PAIRS[-1][1], "summary-child-" + "long-identity-" * 5)
]
summary_cases = pytest.mark.parametrize("prompt,label,child_id", SUMMARY_CASES)
execution_modes = pytest.mark.parametrize("detached", [False, True])


@dataclass
class SummaryDispatch:
    """One independently owned dispatch; no UI assertions are hidden in setup."""

    root: Path
    factory: FiniteFactory
    pool: SubAgentPool
    tool: BaseTool
    events: list[AgentStreamEventDAO]
    task: asyncio.Task[Any]
    prompt: str
    label: str
    child_id: str

    @property
    def process(self) -> FiniteProcess:
        """Return the process whose entry barrier has already completed."""
        process = self.factory.process
        if process is None:
            raise RuntimeError("Dispatch entered without constructing its process")
        return process

    async def complete(self) -> None:
        """Supply the finite transport's context and settle through real arbitration."""
        process = self.process
        directory = self.root / "summary-owner" / "children" / self.child_id
        data = dump_json_bytes(
            SpawnContextDAO.build(
                task_id="compare",
                prompt=self.prompt,
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
        self.factory.release.set()
        await self.task


@asynccontextmanager
async def summary_dispatch(
    *, tmp_path: Path, prompt: str, label: str, child_id: str
) -> AsyncIterator[SummaryDispatch]:
    """Start a real dispatch with finite transport and always join its owned task."""
    root = tmp_path / "history"
    factory = FiniteFactory()
    events: list[AgentStreamEventDAO] = []

    async def relay(event: AgentStreamEventDAO) -> None:
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
    task = asyncio.create_task(
        tool.ainvoke(
            {
                "mode": "single",
                "tasks": [
                    {"task_id": "compare", "session_id": child_id, "prompt": prompt, "task_summary": label}
                ],
            }
        )
    )
    try:
        await asyncio.wait_for(factory.entered.wait(), timeout=5)
        yield SummaryDispatch(root, factory, pool, tool, events, task, prompt, label, child_id)
    finally:
        factory.release.set()
        await task


@pytest.fixture
def authenticated_summary_ui(isolated_slo_home: Path) -> None:
    """Persist the prerequisite in the real isolated store, not a resolver mock."""
    CredentialStore().persist(
        cred=CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.API_KEY,
            access_token="test-summary-credential",
        )
    )


@dataclass
class SummaryUI:
    """Mounted app access with observable command and row readiness barriers."""

    app: SloTUI
    pilot: Pilot
    dispatch: SummaryDispatch

    @property
    def panel(self) -> SubAgentFleetPanel:
        return self.app.query_one(SubAgentFleetPanel)

    @property
    def child(self) -> SubAgentFleetRow:
        return next(row for row in self.panel.query(SubAgentFleetRow) if row.row.role == "child")

    async def command(self, text: str) -> None:
        editor = self.app.query_one(PromptInputComponent)
        editor.focus()
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: self.app.focused is editor,
            description="workflow command editor owns focus",
        )
        editor.text = text
        await self.pilot.press("enter")

    async def wait_for_row(self, status: str) -> None:
        expected = f"[{status}] {self.dispatch.child_id}: {self.dispatch.label}"
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: any(
                row.row.role == "child" and str(row.query_one(Static).render()) == expected
                for row in self.panel.query(SubAgentFleetRow)
            ),
            description=f"{status} child row is presented",
        )

    async def dismiss(self) -> None:
        await self.command("/workflows tui dismiss")
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: not list(self.panel.query(SubAgentFleetRow)),
            description="fleet is locally hidden",
        )


@asynccontextmanager
async def summary_ui(
    *,
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
    completed: bool = False,
    theme: str = "slo-dark",
    size: tuple[int, int] = (120, 40),
) -> AsyncIterator[SummaryUI]:
    """Each caller gets a fresh dispatch and app, never another test's state."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        if completed:
            await dispatch.complete()
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="summary-owner",
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="claude-sonnet-4-6",
                history_root=dispatch.root,
                enable_history=True,
            ),
            history_store=FilesystemSessionHistoryStore(root=dispatch.root),
        )
        if detached:
            await WorkflowHandleStore(history_root=dispatch.root).write(
                handle=_handle(
                    workflow_id="wf-summary",
                    owner_session_id="summary-owner",
                    orchestrator_session_id="summary-owner",
                    state="stalled",
                )
            )
        else:
            session.attach_sub_agent_pool(pool=dispatch.pool, spawn_tools=[dispatch.tool])
        app = SloTUI(session=session)
        async with app.run_test(size=size) as pilot:
            app.theme = theme
            ui = SummaryUI(app, pilot, dispatch)
            await ui.command("/workflows tui show")
            await ui.wait_for_row("completed" if completed else "pending")
            yield ui


@summary_cases
async def test_summary_dispatch_starts_child(tmp_path: Path, prompt: str, label: str, child_id: str) -> None:
    """Dispatch reaches the finite child's public execution entry point."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        assert dispatch.factory.entered.is_set()
        assert dispatch.process.session_id == child_id


@summary_cases
async def test_summary_dispatch_preserves_inputs(
    tmp_path: Path, prompt: str, label: str, child_id: str
) -> None:
    """The child receives the original prompt separately from its summary."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        assert dispatch.process.bound_task.prompt == prompt
        assert dispatch.process.bound_task.task_summary == label


@summary_cases
async def test_summary_is_persisted_in_fleet(tmp_path: Path, prompt: str, label: str, child_id: str) -> None:
    """The wire preview carries the summary encoding, not the full prompt."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        fleet = json.loads((dispatch.root / "summary-owner" / "fleet.json").read_text())
        assert fleet["entries"][0]["prompt_preview"] == "Task summary v1: " + label


@summary_cases
async def test_summary_spawn_event(tmp_path: Path, prompt: str, label: str, child_id: str) -> None:
    """Exactly one spawn event publishes the encoded summary."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        await dispatch.complete()
        assert [event.content for event in dispatch.events if event.kind == "sub_agent_spawned"] == [
            "Task summary v1: " + label
        ]


@summary_cases
async def test_summary_files_remain_readable_by_released_models(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    released_readers: tuple[ModuleType, ModuleType],
) -> None:
    """Published files preserve the historical schema independently of UI layout."""
    async with summary_dispatch(tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id) as dispatch:
        await dispatch.complete()
        assert_released_files(root=dispatch.root, prompt=prompt, child_id=child_id, readers=released_readers)


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
@summary_cases
async def test_pending_summary_row(
    tmp_path: Path, prompt: str, label: str, child_id: str, detached: bool
) -> None:
    """Pending presentation retains the literal summary in model and renderable."""
    async with summary_ui(
        tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id, detached=detached
    ) as ui:
        assert ui.child.row.task_summary == label
        assert str(ui.child.query_one(Static).render()) == f"[pending] {child_id}: {label}"


@pytest.mark.usefixtures("authenticated_summary_ui")
@pytest.mark.parametrize("theme", ["slo-dark", "slo-default"])
@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
@execution_modes
@summary_cases
async def test_pending_summary_is_painted(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
    theme: str,
    size: tuple[int, int],
) -> None:
    """Actual visible cells are a literal prefix, allowing intentional clipping."""
    async with summary_ui(
        tmp_path=tmp_path,
        prompt=prompt,
        label=label,
        child_id=child_id,
        detached=detached,
        theme=theme,
        size=size,
    ) as ui:
        ui.panel.focus_sessions()
        await ui.pilot.press("down")
        ui.child.scroll_visible(animate=False)
        await ui.pilot.wait_for_scheduled_animations()
        expected = "".join(f"[pending] {child_id}: {label}".split())

        def painted() -> str:
            return painted_text(strips=painted_widget_strips(app=ui.app, widget=ui.child))

        def literal_prefix_visible() -> bool:
            value = painted()
            return "[pending]summary-child" in value and expected.startswith(value.removesuffix("…"))

        await wait_for_condition(
            pilot=ui.pilot,
            predicate=literal_prefix_visible,
            description="literal pending row prefix is painted",
        )
        assert literal_prefix_visible()


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
@summary_cases
async def test_completion_preserves_summary_and_prompt(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
) -> None:
    """A live pending-to-completed transition retains both task fields."""
    async with summary_ui(
        tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id, detached=detached
    ) as ui:
        await ui.dispatch.complete()
        await ui.command("/workflows tui show")
        await ui.wait_for_row("completed")
        assert ui.child.row.task_summary == label
        assert ui.child.row.task_text == prompt


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
async def test_summary_dismiss_hides_rows(tmp_path: Path, detached: bool) -> None:
    """Dismiss removes a known mounted fleet without requiring a later show."""
    prompt, label = SUMMARY_PAIRS[0]
    async with summary_ui(
        tmp_path=tmp_path,
        prompt=prompt,
        label=label,
        child_id="summary-child",
        detached=detached,
        completed=True,
    ) as ui:
        await ui.dismiss()
        assert list(ui.panel.query(SubAgentFleetRow)) == []


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
@summary_cases
async def test_summary_show_restores_identity_and_content(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
) -> None:
    """Showing a hidden fleet restores the same identity and complete task content."""
    async with summary_ui(
        tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id, detached=detached, completed=True
    ) as ui:
        original_key = ui.child.row.key
        await ui.dismiss()
        await ui.command("/workflows tui show")
        await ui.wait_for_row("completed")
        assert ui.child.row.key == original_key
        assert (ui.child.row.task_summary, ui.child.row.task_text, ui.child.row.task_text_complete) == (
            label,
            prompt,
            True,
        )


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
@summary_cases
async def test_completed_summary_row_rendering(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
) -> None:
    """A completed row renders its terminal status and literal summary."""
    async with summary_ui(
        tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id, detached=detached, completed=True
    ) as ui:
        assert str(ui.child.query_one(Static).render()) == f"[completed] {child_id}: {label}"


@pytest.mark.usefixtures("authenticated_summary_ui")
@execution_modes
@summary_cases
async def test_summary_keyboard_selection_opens_original_prompt(
    tmp_path: Path,
    prompt: str,
    label: str,
    child_id: str,
    detached: bool,
) -> None:
    """Selecting a completed child opens its detail with the original prompt."""
    async with summary_ui(
        tmp_path=tmp_path, prompt=prompt, label=label, child_id=child_id, detached=detached, completed=True
    ) as ui:
        ui.panel.focus_sessions()
        await ui.pilot.press("down", "enter")
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: isinstance(ui.app.screen, SessionProgressScreen),
            description="selected child's detail screen opens",
        )
        assert isinstance(ui.app.screen, SessionProgressScreen)
        assert str(ui.app.screen.query_one("#task-description", Static).render()) == prompt
