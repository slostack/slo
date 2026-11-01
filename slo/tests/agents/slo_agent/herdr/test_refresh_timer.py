"""Exercise the reporter-owned timer rather than manually repeating a batch."""

import asyncio
from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


@pytest.mark.parametrize("cutoff", ["active", "revoked", "closing", "disabled", "empty"])
async def test_refresh_timer_preserves_revision(tmp_path: Path, cutoff: str) -> None:
    """The real two-second wake queues only live latest facts and never revises them."""
    owner = reporter(root=tmp_path)
    if cutoff != "empty":
        owner.publish(publication=publication(eligible=False))
    owner._take_pending()
    revision = owner._revision
    loop = asyncio.get_running_loop()
    started = loop.time()
    timer = asyncio.create_task(coro=owner._refresh_publication())
    owner._refresh_task = timer
    try:
        # Let the timer enter its real sleep before changing its admission facts.
        await asyncio.sleep(delay=0)
        if cutoff == "revoked":
            owner.revoke_viewer_admission()
            owner._wake.clear()
        elif cutoff == "closing":
            owner._closing = True
        elif cutoff == "disabled":
            owner._disabled = True
        if cutoff == "active":
            await asyncio.wait_for(fut=owner._wake.wait(), timeout=4)
            assert loop.time() - started >= 2.0
            assert owner._pending is owner._latest
        elif cutoff == "empty":
            # An empty timer remains alive after its first tick, without a wake.
            await asyncio.sleep(delay=2.05)
            assert not timer.done()
            assert owner._pending is None and not owner._wake.is_set()
        else:
            await asyncio.wait_for(fut=asyncio.shield(timer), timeout=4)
            assert owner._pending is None and not owner._wake.is_set()
        assert owner._revision == revision
    finally:
        await owner.close()
        await owner.close_transport()
    assert timer.done() and not owner.retains_external_resources
