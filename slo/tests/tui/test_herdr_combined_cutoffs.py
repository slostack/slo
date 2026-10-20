"""Combined occupied-owner probes reusing the real inbox disposition assertions."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.tui import test_herdr_inbox_disposition as inbox_cases


@asynccontextmanager
async def occupied_viewer(*, root: Path, session_id: str | None = None) -> AsyncIterator[SloTUI]:
    """Add an actual registered viewer whose cancellation finalizer needs the gate."""
    async with original_mount(root=root, session_id=session_id) as app:
        entered = asyncio.Event()
        finalized = asyncio.Event()

        async def worker(*, parent_session_id: str, session: SloAgentSession) -> None:
            """Keep registry ownership until gate-dependent cancellation completes."""
            assert session is app._session and parent_session_id == "combined-parent"
            entered.set()
            try:
                await asyncio.Future()
            finally:
                async with app._prompt_submission_lock:
                    finalized.set()

        with patch.object(app, "_run_visualizer_launch", side_effect=worker):
            app._schedule_visualizer_launch(parent_session_id="combined-parent")
            task = app._visualizer_launch_tasks["combined-parent"]
            await asyncio.wait_for(entered.wait(), timeout=5)
            try:
                yield app
            finally:
                await asyncio.wait_for(app.on_unmount(), timeout=5)
                assert finalized.is_set() and task.done()
                assert not app._visualizer_launch_tasks
                app._schedule_visualizer_launch(parent_session_id="late-parent")
                assert not app._visualizer_launch_tasks


original_mount = inbox_cases.mounted_inbox


@pytest.mark.parametrize("operator_abort", [False, True])
@pytest.mark.parametrize("displace_store", [False, True])
async def test_combined_registered_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operator_abort: bool, displace_store: bool
) -> None:
    """Preserve admitted task identity, original ack and explicit active-stream abort."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    with patch.object(inbox_cases, "mounted_inbox", new=occupied_viewer):
        await inbox_cases.test_already_registered_ack_pending_at_close(
            tmp_path=tmp_path, operator_abort=operator_abort, displace_store=displace_store
        )


@pytest.mark.parametrize("cutoff", ["claim_pending", "workflow_advance_pending", "before_chat_registration"])
@pytest.mark.parametrize("throwing_notice", [False, True])
async def test_combined_refusal_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cutoff: str, throwing_notice: bool
) -> None:
    """Run real claim/advance/refusal/restart assertions with an occupied registry."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    with patch.object(inbox_cases, "mounted_inbox", new=occupied_viewer):
        await inbox_cases.test_durable_advance_then_shutdown(
            tmp_path=tmp_path, throwing_notice=throwing_notice, cutoff=cutoff
        )
