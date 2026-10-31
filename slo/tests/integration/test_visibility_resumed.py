"""Real persisted old-session replay, display commands and mounted lifetime reset."""

from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator
from dataclasses import dataclass

import pytest

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowHandleDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
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


async def test_resumed_legacy_visibility_durable_dismiss_and_lifetime_reset(tmp_path: Path) -> None:
    """Replay old history, dismiss durably, restore locally, restart and /new without leaked flags."""
    seed = resumed_session(root=tmp_path)
    async for _ in seed.invoke(text="persisted legacy prompt"):
        pass
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-legacy",
            owner_session_id="legacy-owner",
            orchestrator_session_id="legacy-parent",
            state="stalled",
        )
    )
    files.fleet(
        parent="legacy-parent", entries=[_entry(session_id="legacy-child", execution_id="")], run_id=None
    )
    store = WorkflowHandleStore(history_root=root)
    app = SloTUI(session=resumed_session(root=tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(app.query(SubAgentFleetRow)) == 2,
            description="resumed owner fleet rows are mounted",
        )
        assert app.query_one(UserMessageBlock).text == "persisted legacy prompt"
        assert len(app.query(SubAgentFleetRow)) == 2
        editor = app.query_one(PromptInput)
        editor.text = "/workflows dismiss wf-legacy"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: app._adapter is not None
            and any(
                text == "workflow wf-legacy dismissed (stalled → failed)" for text, _ in app._adapter.lines
            ),
            description="durable dismissal success is acknowledged",
        )
        handle = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert handle is not None and handle.state == "failed"
        # The durable command requests a background refresh; persistence is not its paint barrier.
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(app.query(SubAgentFleetRow)),
            description="durably dismissed workflow rows are unmounted",
        )
        assert list(app.query(SubAgentFleetRow)) == []
        editor.text = "/workflows tui show"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(app.query(SubAgentFleetRow)) == 2,
            description="both resumed fleet rows are mounted",
        )
        assert len(app.query(SubAgentFleetRow)) == 2
        assert (await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")).state == "failed"
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(app.query(SubAgentFleetRow)),
            description="locally dismissed workflow rows are unmounted",
        )
        assert list(app.query(SubAgentFleetRow)) == []
    restarted = SloTUI(session=resumed_session(root=tmp_path))
    async with restarted.run_test(size=(120, 40)) as pilot:
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(restarted.query(SubAgentFleetRow)) == 2,
            description="restarted owner does not inherit hidden workflow groups",
        )
        assert len(restarted.query(SubAgentFleetRow)) == 2
        editor = restarted.query_one(PromptInput)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(restarted.query(SubAgentFleetRow)),
            description="restarted owner workflow rows are hidden before replacement",
        )
        editor.text = "/new"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: restarted._session.session_id != "legacy-owner"
            and restarted._workflow_observation_session_id == restarted._session.session_id
            and restarted._workflow_progress_coordinator is not None
            and restarted._workflow_progress_coordinator._task is not None
            and restarted._workflow_progress_coordinator._task.done(),
            description="successor observation is bound and its first refresh is complete",
        )
        assert list(restarted.query(SubAgentFleetRow)) == []
        editor.text = "/workflows tui show"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: restarted._adapter is not None
            and any(text == "No hidden workflow groups to show." for text, _ in restarted._adapter.lines),
            description="empty-show notice is published",
        )
        assert restarted._adapter is not None
        assert any(text == "No hidden workflow groups to show." for text, _ in restarted._adapter.lines)
        # The notice precedes request_refresh; join that read/paint before checking owner isolation.
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: restarted._workflow_progress_coordinator is not None
            and restarted._workflow_progress_coordinator._task is not None
            and restarted._workflow_progress_coordinator._task.done(),
            description="successor show refresh is complete without legacy rows",
        )
        assert list(restarted.query(SubAgentFleetRow)) == []
        assert (await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")).state == "failed"


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


@pytest.mark.parametrize("fail", [False, True])
async def test_durable_resume_reveals_same_mounted_visibility_group(tmp_path: Path, fail: bool) -> None:
    """Successful adoption reveals hidden rows; launch failure rolls back and stays hidden."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-legacy",
            owner_session_id="legacy-owner",
            orchestrator_session_id="legacy-parent",
            state="failed",
        )
    )
    files.fleet(
        parent="legacy-parent", entries=[_entry(session_id="legacy-child", execution_id="")], run_id=None
    )
    store = WorkflowHandleStore(history_root=root, pid_alive=lambda pid: False)
    launcher = FiniteLauncher(store=store, fail=fail)
    app = SloTUI(session=resumed_session(root=tmp_path), workflow_resume_launcher=launcher)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(app.query(SubAgentFleetRow)) == 2,
            description="resumable workflow fleet rows are mounted",
        )
        keys = tuple(row.row.key for row in app.query(SubAgentFleetRow))
        assert len(keys) == 2
        editor = app.query_one(PromptInput)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(app.query(SubAgentFleetRow)),
            description="workflow rows are locally hidden before resume",
        )
        assert not list(app.query(SubAgentFleetRow))
        editor.text = "/workflows resume wf-legacy"
        await pilot.press("enter")
        acknowledgment = (
            "workflow wf-legacy resume failed"
            if fail
            else f"workflow wf-legacy resumed (pid {launcher.adoption.process.pid}); "
            "history replaying — state advances to running on the first heartbeat"
        )
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: app._adapter is not None
            and any(text == acknowledgment for text, _ in app._adapter.lines),
            description="durable resume outcome is acknowledged",
        )
        persisted = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert persisted is not None
        assert launcher.calls == 1 and launcher.closed
        assert launcher.adoption.activated is (not fail)
        assert persisted.state == ("failed" if fail else "launching")
        if fail:
            assert not list(app.query(SubAgentFleetRow))
        else:
            assert persisted.pid == launcher.adoption.process.pid
            # Durable adoption requests observation; it does not join the background row application.
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: tuple(row.row.key for row in app.query(SubAgentFleetRow)) == keys,
                description="successful resume restores the same mounted workflow keys",
            )
            assert tuple(row.row.key for row in app.query(SubAgentFleetRow)) == keys
            editor.text = "/workflows tui dismiss"
            await pilot.press("enter")
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: not list(app.query(SubAgentFleetRow)),
                description="resumed workflow rows are locally hidden",
            )
            assert not list(app.query(SubAgentFleetRow))
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            await wait_for_condition(
                pilot=pilot,
                predicate=lambda: len(app.query(SubAgentFleetRow)) == 2,
                description="re-shown resumed fleet rows are mounted",
            )
            assert tuple(row.row.key for row in app.query(SubAgentFleetRow)) == keys
            assert launcher.calls == 1
            assert await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy") == persisted


async def test_current_format_resume_restores_same_mounted_group_without_relaunch_on_show(
    tmp_path: Path,
) -> None:
    """Resume a run-bound fleet through Enter; local re-show retains its keys and durable adoption."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-legacy",
            owner_session_id="legacy-owner",
            orchestrator_session_id="legacy-parent",
            state="failed",
        )
    )
    files.fleet(parent="legacy-parent", entries=[_entry(session_id="current-child", execution_id=_EXEC_A)])
    store = WorkflowHandleStore(history_root=root, pid_alive=lambda pid: False)
    launcher = FiniteLauncher(store=store, fail=False)
    app = SloTUI(session=resumed_session(root=tmp_path), workflow_resume_launcher=launcher)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(app.query(SubAgentFleetRow)) == 2,
            description="current-format fleet rows are mounted",
        )
        workflow_rows = tuple(fleet_row.row for fleet_row in app.query(SubAgentFleetRow))
        keys = tuple(workflow_row.key for workflow_row in workflow_rows)
        assert len(keys) == 2
        assert workflow_rows[1].execution_id == _EXEC_A
        editor = app.query_one(PromptInput)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(app.query(SubAgentFleetRow)),
            description="current-format fleet is hidden before resume",
        )
        editor.text = "/workflows resume wf-legacy"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: app._adapter is not None
            and any(
                text == f"workflow wf-legacy resumed (pid {launcher.adoption.process.pid}); "
                "history replaying — state advances to running on the first heartbeat"
                for text, _ in app._adapter.lines
            ),
            description="current-format durable resume is acknowledged",
        )
        persisted: WorkflowHandleDAO | None = await store.read(
            owner_session_id="legacy-owner", workflow_id="wf-legacy"
        )
        assert persisted is not None and persisted.state == "launching"
        assert persisted.pid == launcher.adoption.process.pid
        assert launcher.calls == 1 and launcher.closed and launcher.adoption.activated
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: tuple(fleet_row.row.key for fleet_row in app.query(SubAgentFleetRow)) == keys,
            description="current-format resume restores original ordered keys",
        )
        assert tuple(fleet_row.row.key for fleet_row in app.query(SubAgentFleetRow)) == keys
        durable_files = tree_state(root)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: not list(app.query(SubAgentFleetRow)),
            description="resumed current-format fleet is locally hidden",
        )
        editor.text = "/workflows tui show"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: tuple(fleet_row.row.key for fleet_row in app.query(SubAgentFleetRow)) == keys,
            description="current-format local show restores original ordered keys",
        )
        assert tuple(fleet_row.row.key for fleet_row in app.query(SubAgentFleetRow)) == keys
        assert tuple(fleet_row.row.execution_id for fleet_row in app.query(SubAgentFleetRow))[1] == _EXEC_A
        assert launcher.calls == 1
        assert await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy") == persisted
        assert tree_state(root) == durable_files


async def test_resume_refuses_foreign_owner_without_launch_or_foreign_mutation(tmp_path: Path) -> None:
    """Enter cannot resume another owner's workflow, even when its ID is known."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-foreign",
            owner_session_id="foreign-owner",
            orchestrator_session_id="foreign-parent",
            state="failed",
        )
    )
    files.fleet(
        parent="foreign-parent", entries=[_entry(session_id="foreign-child", execution_id="")], run_id=None
    )
    store = WorkflowHandleStore(history_root=root, pid_alive=lambda pid: False)
    foreign_handle: WorkflowHandleDAO | None = await store.read(
        owner_session_id="foreign-owner", workflow_id="wf-foreign"
    )
    assert foreign_handle is not None
    foreign_files = (tree_state(root / "foreign-owner"), tree_state(root / "foreign-parent"))
    launcher = FiniteLauncher(store=store, fail=False)
    app = SloTUI(session=resumed_session(root=tmp_path), workflow_resume_launcher=launcher)
    async with app.run_test(size=(120, 40)) as pilot:
        editor = app.query_one(PromptInput)
        editor.text = "/workflows resume wf-foreign"
        await pilot.press("enter")
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: app._adapter is not None
            and any(text == "no workflow wf-foreign" for text, _ in app._adapter.lines),
            description="foreign-owner resume refusal is acknowledged",
        )
        assert launcher.calls == 0 and not launcher.adoption.activated
        assert await store.read(owner_session_id="foreign-owner", workflow_id="wf-foreign") == foreign_handle
        assert (tree_state(root / "foreign-owner"), tree_state(root / "foreign-parent")) == foreign_files
        assert not list(app.query(SubAgentFleetRow))
