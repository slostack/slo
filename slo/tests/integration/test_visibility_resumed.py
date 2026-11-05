"""Real persisted old-session replay, display commands and mounted lifetime reset."""

from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal
from textual.pilot import Pilot
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from dataclasses import dataclass

import pytest

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowHandleDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.tui.authentication._painted_output import wait_for_condition
from tests.tui.workflows.test_session_snapshot import _Files, _entry, _handle, _EXEC_A
from tests.tui.workflows.test_visibility_loader_slice import tree_state


def resumed_session(*, root: Path) -> SloAgentSession:
    """Reconstruct the same owner with real legacy flat history, never migrate it."""
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="saved answer")]), cwd=str(root), tools=[]
        ),
        workdir=root,
        session_id="legacy-owner",
        history_store=FilesystemSessionHistoryStore(root=root / "history"),
        enable_history=True,
        config=SessionConfigDAO(
            workdir=root, model_name="claude-sonnet-4-6", enable_history=True, history_root=root / "history"
        ),
    )


@dataclass
class FiniteProcess:
    """Synthetic identity only; never an OS process."""

    pid: int = 987654


class FiniteAdoption:
    """Check durable adoption before accepting activation."""

    def __init__(self, *, store: WorkflowHandleStore) -> None:
        self.process = FiniteProcess()
        self.store = store
        self.activated = False

    async def activate(self, *, expected_pid: int) -> None:
        """Verify the command committed its PID before activation."""
        handle = await self.store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert handle is not None and handle.state == "launching"
        assert handle.pid == expected_pid == self.process.pid
        self.activated = True


class FiniteLauncher:
    """Replace only process/capture launch, retaining real command/store policy."""

    def __init__(self, *, store: WorkflowHandleStore, fail: bool) -> None:
        self.store = store
        self.fail = fail
        self.calls = 0
        self.closed = False
        self.adoption = FiniteAdoption(store=store)

    @asynccontextmanager
    async def __call__(
        self, *, handle: WorkflowHandleDAO, history_root: Path
    ) -> AsyncIterator[FiniteAdoption]:
        """Assert reservation on disk and return one finite launch lifetime."""
        self.calls += 1
        persisted = await self.store.read(
            owner_session_id=handle.owner_session_id, workflow_id=handle.workflow_id
        )
        assert persisted == handle and handle.state == "launching" and handle.pid == 0
        assert history_root.is_dir()
        try:
            if self.fail:
                raise OSError("synthetic launch refusal")
            yield self.adoption
        finally:
            self.closed = True


@pytest.fixture(autouse=True)
def workflow_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide authentication prerequisites without changing workflow behavior."""

    def resolve(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(provider=provider, auth_type=AuthType.API_KEY, access_token="workflow-test")

    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", resolve)


@dataclass
class VisibilityUI:
    """One mounted lifetime with real command handling and bounded readiness."""

    app: SloTUI
    pilot: Pilot

    @property
    def keys(self) -> tuple:
        return tuple(row.row.key for row in self.app.query(SubAgentFleetRow))

    async def command(self, text: str) -> None:
        editor = self.app.query_one(PromptInputComponent)
        editor.focus()
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: self.app.focused is editor,
            description="workflow editor owns keyboard focus",
        )
        editor.text = text
        await self.pilot.press("enter")

    async def rows(self, count: int) -> None:
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: len(self.app.query(SubAgentFleetRow)) == count,
            description=f"fleet has {count} rows",
        )

    def notice(self, text: str) -> bool:
        adapter = self.app._chat_transcript._adapter
        return adapter is not None and any(line == text for line, _ in adapter.lines)

    async def acknowledged(self, text: str) -> None:
        await wait_for_condition(
            pilot=self.pilot, predicate=lambda: self.notice(text), description=f"command acknowledged: {text}"
        )

    async def hide(self) -> None:
        await self.command("/workflows tui dismiss")
        await self.rows(0)


async def seed_workflow(
    root: Path,
    *,
    current: bool = False,
    owner: str = "legacy-owner",
    workflow: str = "wf-legacy",
    parent: str = "legacy-parent",
    state: Literal["launching", "running", "completed", "failed", "aborted", "stalled"] = "failed",
) -> None:
    """Write a real durable workflow and its fleet into this test's private tree."""
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id=workflow, owner_session_id=owner, orchestrator_session_id=parent, state=state
        )
    )
    if current:
        files.fleet(parent=parent, entries=[_entry(session_id="current-child", execution_id=_EXEC_A)])
    else:
        files.fleet(parent=parent, entries=[_entry(session_id="legacy-child", execution_id="")], run_id=None)


@asynccontextmanager
async def mounted(root: Path, launcher: FiniteLauncher | None = None) -> AsyncIterator[VisibilityUI]:
    app = SloTUI(session=resumed_session(root=root), workflow_resume_launcher=launcher)
    async with app.run_test(size=(120, 40)) as pilot:
        yield VisibilityUI(app, pilot)


@pytest.fixture
async def legacy_history(tmp_path: Path) -> Path:
    """Persist the old-session prompt and stalled workflow, without mounting a UI."""
    seed = resumed_session(root=tmp_path)
    async for _ in seed.invoke(text="persisted legacy prompt"):
        pass
    await seed_workflow(tmp_path / "history", state="stalled")
    return tmp_path


async def dismiss_durably(ui: VisibilityUI) -> None:
    await ui.command("/workflows dismiss wf-legacy")
    await ui.acknowledged("workflow wf-legacy dismissed (stalled → failed)")
    await ui.rows(0)


async def test_legacy_replay_restores_prompt_and_fleet(legacy_history: Path) -> None:
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        assert ui.app.query_one(UserMessageBlock).text == "persisted legacy prompt"
        assert len(ui.keys) == 2


async def test_durable_dismiss_marks_handle_failed(legacy_history: Path) -> None:
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        await ui.command("/workflows dismiss wf-legacy")
        await ui.acknowledged("workflow wf-legacy dismissed (stalled → failed)")
        handle = await WorkflowHandleStore(history_root=legacy_history / "history").read(
            owner_session_id="legacy-owner", workflow_id="wf-legacy"
        )
        assert handle is not None and handle.state == "failed"


async def test_durable_dismiss_unmounts_fleet(legacy_history: Path) -> None:
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        await dismiss_durably(ui)
        assert ui.keys == ()


async def test_local_show_does_not_reverse_durable_dismiss(legacy_history: Path) -> None:
    store = WorkflowHandleStore(history_root=legacy_history / "history")
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        keys = ui.keys
        await dismiss_durably(ui)
        persisted = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        await ui.command("/workflows tui show")
        await ui.rows(2)
        assert ui.keys == keys
        assert await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy") == persisted


async def test_restart_does_not_inherit_hidden_groups(legacy_history: Path) -> None:
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        await dismiss_durably(ui)
        await ui.command("/workflows tui show")
        await ui.rows(2)
        keys = ui.keys
        await ui.hide()
    async with mounted(legacy_history) as restarted:
        await restarted.rows(2)
        assert restarted.keys == keys


async def test_new_session_does_not_inherit_hidden_legacy_groups(legacy_history: Path) -> None:
    store = WorkflowHandleStore(history_root=legacy_history / "history")
    async with mounted(legacy_history) as ui:
        await ui.rows(2)
        await dismiss_durably(ui)
        await ui.command("/workflows tui show")
        await ui.rows(2)
        await ui.hide()
        persisted = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        await ui.command("/new")
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: ui.app._session.session_id != "legacy-owner"
            and ui.app._workflow_observation_session_id == ui.app._session.session_id
            and ui.app._workflow_progress_coordinator is not None
            and ui.app._workflow_progress_coordinator._task is not None
            and ui.app._workflow_progress_coordinator._task.done(),
            description="replacement owner observation is complete",
        )
        await ui.command("/workflows tui show")
        await ui.acknowledged("No hidden workflow groups to show.")
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: ui.app._workflow_progress_coordinator is not None
            and ui.app._workflow_progress_coordinator._task is not None
            and ui.app._workflow_progress_coordinator._task.done(),
            description="replacement show observation is complete",
        )
        assert ui.keys == ()
        assert await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy") == persisted


@dataclass
class ResumeUI:
    ui: VisibilityUI
    store: WorkflowHandleStore
    launcher: FiniteLauncher
    keys: tuple

    async def resume(self) -> None:
        await self.ui.command("/workflows resume wf-legacy")
        text = (
            "workflow wf-legacy resume failed"
            if self.launcher.fail
            else f"workflow wf-legacy resumed (pid {self.launcher.adoption.process.pid}); "
            "history replaying — state advances to running on the first heartbeat"
        )
        await self.ui.acknowledged(text)


@asynccontextmanager
async def hidden_resume(root: Path, *, current: bool, fail: bool = False) -> AsyncIterator[ResumeUI]:
    await seed_workflow(root / "history", current=current)
    store = WorkflowHandleStore(history_root=root / "history", pid_alive=lambda pid: False)
    launcher = FiniteLauncher(store=store, fail=fail)
    async with mounted(root, launcher) as ui:
        await ui.rows(2)
        keys = ui.keys
        await ui.hide()
        yield ResumeUI(ui, store, launcher, keys)


formats = pytest.mark.parametrize("current", [False, True], ids=["legacy", "current"])


@formats
async def test_resume_adopts_pid_before_activation(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current) as case:
        await case.resume()
        handle = await case.store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert handle is not None and (handle.state, handle.pid) == (
            "launching",
            case.launcher.adoption.process.pid,
        )
        assert case.launcher.calls == 1 and case.launcher.closed and case.launcher.adoption.activated


@formats
async def test_resume_restores_original_row_identity(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current) as case:
        await case.resume()
        await case.ui.rows(2)
        assert case.ui.keys == case.keys
        assert list(case.ui.app.query(SubAgentFleetRow))[1].row.execution_id == (_EXEC_A if current else "")


@formats
async def test_failed_resume_rolls_back_without_activation(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current, fail=True) as case:
        await case.resume()
        handle = await case.store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert handle is not None and handle.state == "failed"
        assert case.launcher.calls == 1 and case.launcher.closed and not case.launcher.adoption.activated


@formats
async def test_failed_resume_keeps_fleet_hidden(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current, fail=True) as case:
        await case.resume()
        assert case.ui.keys == ()


@formats
async def test_show_after_resume_restores_same_rows(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current) as case:
        await case.resume()
        await case.ui.rows(2)
        await case.ui.hide()
        await case.ui.command("/workflows tui show")
        await case.ui.rows(2)
        assert case.ui.keys == case.keys
        assert list(case.ui.app.query(SubAgentFleetRow))[1].row.execution_id == (_EXEC_A if current else "")


@formats
async def test_show_after_resume_neither_relaunches_nor_writes(tmp_path: Path, current: bool) -> None:
    async with hidden_resume(tmp_path, current=current) as case:
        await case.resume()
        await case.ui.rows(2)
        persisted = tree_state(tmp_path / "history")
        await case.ui.hide()
        await case.ui.command("/workflows tui show")
        await case.ui.rows(2)
        assert case.launcher.calls == 1
        assert tree_state(tmp_path / "history") == persisted


@asynccontextmanager
async def refused_foreign_resume(root: Path) -> AsyncIterator[tuple[VisibilityUI, FiniteLauncher, tuple]]:
    await seed_workflow(
        root / "history", owner="foreign-owner", workflow="wf-foreign", parent="foreign-parent"
    )
    store = WorkflowHandleStore(history_root=root / "history", pid_alive=lambda pid: False)
    launcher = FiniteLauncher(store=store, fail=False)
    original = (tree_state(root / "history/foreign-owner"), tree_state(root / "history/foreign-parent"))
    async with mounted(root, launcher) as ui:
        await ui.command("/workflows resume wf-foreign")
        await ui.acknowledged("no workflow wf-foreign")
        yield ui, launcher, original


async def test_foreign_resume_is_refused_without_launch(tmp_path: Path) -> None:
    async with refused_foreign_resume(tmp_path) as (ui, launcher, _):
        assert ui.notice("no workflow wf-foreign")
        assert launcher.calls == 0 and not launcher.adoption.activated


async def test_foreign_resume_preserves_foreign_files(tmp_path: Path) -> None:
    async with refused_foreign_resume(tmp_path) as (_, _, original):
        assert (
            tree_state(tmp_path / "history/foreign-owner"),
            tree_state(tmp_path / "history/foreign-parent"),
        ) == original


async def test_foreign_resume_does_not_mount_foreign_rows(tmp_path: Path) -> None:
    async with refused_foreign_resume(tmp_path) as (ui, _, _):
        assert ui.keys == ()
