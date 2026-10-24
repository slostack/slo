"""Composed startup races at the catalog boundary and real reporter projection."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
from src.agents.slo_agent.sessions.dao import OperatorAttentionReason, SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
@pytest.mark.parametrize("newer_reason", ["Authentication required", "Model preparation required"])
async def test_startup_completion_preserves_newer_attention(
    tmp_path: Path, outcome: str, newer_reason: OperatorAttentionReason
) -> None:
    """A delayed catalog completion cannot replace a newer human requirement."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._preparation_status = "pending"
    session.set_operator_attention(reason="Model preparation required")
    session._herdr_reporting_started = True
    entered, release = asyncio.Event(), asyncio.Event()
    publications: list[HerdrPublicationDAO] = []

    async def prepare(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Hold only the external preparation boundary, not session orchestration."""
        entered.set()
        await release.wait()
        if outcome == "failure":
            raise RuntimeError("catalog unavailable")
        return ModelCatalogService.load()

    def publish(*, publication: HerdrPublicationDAO) -> None:
        """Record actual immutable reporter handoffs without starting a transport."""
        publications.append(publication)

    with (
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare),
        patch.object(session._herdr_reporter, "publish", side_effect=publish),
    ):
        task = asyncio.create_task(session.prepare_startup())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            newest = session.set_operator_attention(reason=newer_reason)
            assert publications[-1].snapshot.state == "working"
            if outcome == "cancel":
                task.cancel()
            release.set()
            if outcome == "success":
                await asyncio.wait_for(task, timeout=5)
            else:
                expected = asyncio.CancelledError if outcome == "cancel" else ModelPreparationRequiredError
                with pytest.raises(expected):
                    await asyncio.wait_for(task, timeout=5)
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert session._operator_attention is not None
    assert session._operator_attention.token == newest
    assert publications[-1].snapshot.block_reason == newer_reason
    assert all(item.snapshot.state == "working" for item in publications[:-1])
    assert session._operation_serial == 1 and not session._reporting_operations
    assert not session.is_running
