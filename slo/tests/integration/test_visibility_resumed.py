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
from tests.tui.workflows.test_session_snapshot import _Files, _entry, _handle


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
        await pilot.pause()
        assert app.query_one(UserMessageBlock).text == "persisted legacy prompt"
        assert len(app.query(SubAgentFleetRow)) == 2
        editor = app.query_one(PromptInput)
        editor.text = "/workflows dismiss wf-legacy"
        await pilot.press("enter")
        await pilot.pause()
        handle = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert handle is not None and handle.state == "failed"
        assert list(app.query(SubAgentFleetRow)) == []
        editor.text = "/workflows tui show"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.query(SubAgentFleetRow)) == 2
        assert (await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")).state == "failed"
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await pilot.pause()
        assert list(app.query(SubAgentFleetRow)) == []
    restarted = SloTUI(session=resumed_session(root=tmp_path))
    async with restarted.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert len(restarted.query(SubAgentFleetRow)) == 2
        editor = restarted.query_one(PromptInput)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await pilot.pause()
        editor.text = "/new"
        await pilot.press("enter")
        await pilot.pause()
        assert list(restarted.query(SubAgentFleetRow)) == []
        editor.text = "/workflows tui show"
        await pilot.press("enter")
        await pilot.pause()
        assert restarted._adapter is not None
        assert any(text == "No hidden workflow groups to show." for text, _ in restarted._adapter.lines)
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
        await pilot.pause()
        keys = tuple(row.row.key for row in app.query(SubAgentFleetRow))
        assert len(keys) == 2
        editor = app.query_one(PromptInput)
        editor.text = "/workflows tui dismiss"
        await pilot.press("enter")
        await pilot.pause()
        assert not list(app.query(SubAgentFleetRow))
        editor.text = "/workflows resume wf-legacy"
        await pilot.press("enter")
        await pilot.pause()
        persisted = await store.read(owner_session_id="legacy-owner", workflow_id="wf-legacy")
        assert persisted is not None
        assert launcher.calls == 1 and launcher.closed
        assert launcher.adoption.activated is (not fail)
        assert persisted.state == ("failed" if fail else "launching")
        if fail:
            assert not list(app.query(SubAgentFleetRow))
        else:
            assert persisted.pid == launcher.adoption.process.pid
            assert tuple(row.row.key for row in app.query(SubAgentFleetRow)) == keys
            editor.text = "/workflows tui dismiss"
            await pilot.press("enter")
            await pilot.pause()
            assert not list(app.query(SubAgentFleetRow))
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            await pilot.pause()
            assert tuple(row.row.key for row in app.query(SubAgentFleetRow)) == keys
