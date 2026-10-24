"""Deterministic one-slot worker wake and latest-publication ownership."""

import asyncio
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO, HerdrPublicationDAO
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


@pytest.mark.parametrize("case", ["empty", "new", "busy_replaced", "adoption_wake", "close"])
async def test_worker_wake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    """A wake consumes the latest slot once; revocation wakes an empty worker."""
    owner = reporter(root=tmp_path)
    entered, release, second = asyncio.Event(), asyncio.Event(), asyncio.Event()
    consumed: list[HerdrPublicationDAO] = []

    async def consume(*, publication: HerdrPublicationDAO) -> None:
        """Observe real worker scheduling while holding its first publication."""
        consumed.append(publication)
        if len(consumed) == 1:
            entered.set()
            await release.wait()
        else:
            second.set()

    monkeypatch.setattr(target=owner, name="_consume_publication", value=consume)
    worker = asyncio.create_task(coro=owner._consume_pending())
    owner._worker = worker
    initial = publication(eligible=True)
    try:
        await asyncio.sleep(delay=0)
        assert not consumed and not worker.done()
        if case in ("empty", "close"):
            owner.revoke_viewer_admission()
            await asyncio.wait_for(fut=worker, timeout=2)
            assert not consumed
            return
        owner.publish(publication=initial)
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        assert owner._pending is None
        if case == "busy_replaced":
            for value in ("1", "2", "3"):
                latest = initial.model_copy(
                    update={
                        "snapshot": initial.snapshot.model_copy(
                            update={"tokens": (HerdrDisplayTokenDAO(key="turn", value=value),)}
                        )
                    }
                )
                owner.publish(publication=latest)
            assert owner._pending is latest
        elif case == "adoption_wake":
            saved = await owner._save_capture(publication=initial)
            owner._adopt_save(saved=saved)
            assert owner._pending is initial and owner._wake.is_set()
        release.set()
        if case != "new":
            await asyncio.wait_for(fut=second.wait(), timeout=2)
            assert consumed[-1] is owner._latest
        await asyncio.sleep(delay=0)
        assert len(consumed) == (1 if case == "new" else 2)
        assert owner._pending is None and not owner._wake.is_set()
        owner.revoke_viewer_admission()
        await asyncio.wait_for(fut=worker, timeout=2)
    finally:
        release.set()
        await owner.close()
        await owner.close_transport()
    assert worker.done() and not owner.retains_external_resources
