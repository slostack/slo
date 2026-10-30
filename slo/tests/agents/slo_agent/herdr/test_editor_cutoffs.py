"""Deterministic editor authority/lifetime cutoffs at the serialized command boundary."""

import asyncio

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrCommandAdmission, HerdrCommandResultDAO
from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher
from tests.agents.slo_agent.herdr.test_editor import RecordingPaneTransport


class HoldRunTransport(RecordingPaneTransport):
    """Pause the run request before its locked authority check."""

    async def invoke(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Split first, then hold run behind a synthetic shared-lock contender."""
        if command.argv[1] == "run":
            self.release.clear()
            self.waiting.set()
        return await super().invoke(command=command, admission=admission)


async def test_editor_run_rechecks_revoked_authority_after_successful_split() -> None:
    """Revocation after pane creation prevents input, retaining a user-owned empty pane."""
    permitted = True
    transport = HoldRunTransport()
    launcher = HerdrEditorLauncher(transport=transport, owner_pane_id="captured", authority=lambda: permitted)
    task = asyncio.create_task(coro=launcher.invoke(argv=("/nvim", "--", "/file")))
    try:
        async with asyncio.timeout(2):
            while transport.release.is_set():
                await asyncio.sleep(0)
        permitted = False
        transport.release.set()
        result = await task
        assert result.status == "failed" and result.pane_id == "editor-pane"
        assert [command.argv[1] for command in transport.commands] == ["split"]
    finally:
        transport.release.set()
        await launcher.close()
        await asyncio.gather(task, return_exceptions=True)


async def test_editor_close_cancels_pending_split_and_never_closes_visible_pane() -> None:
    """Session cleanup drains mechanics without destroying a possibly-created pane."""
    transport = RecordingPaneTransport(hold=True)
    launcher = HerdrEditorLauncher(transport=transport, owner_pane_id="captured", authority=lambda: True)
    task = asyncio.create_task(coro=launcher.invoke(argv=("/nvim", "--", "/file")))
    await asyncio.wait_for(fut=transport.waiting.wait(), timeout=2)
    await launcher.close()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert transport.commands == []
    assert not launcher._pending
    assert not transport.closed
