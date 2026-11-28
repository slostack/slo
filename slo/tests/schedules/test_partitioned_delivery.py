"""One delivery per schedule on the real engine lock (111.a.4 A8, A9; FIR111-01).

The engine holds the per-schedule honker lock for the whole delivery and
renews it, so a delivery that outlasts the TTL still excludes a second
delivery of the same schedule while a different schedule makes progress.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

import honker
import pytest

from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.workflows import ScheduleEngine


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


class GatedFreshRunner:
    """FreshRunStarter that records each start and blocks until released.

    It is passed through the engine's ``fresh_runs`` seam, so the engine's own
    deliver-service assembly, real database and channel store stay under test;
    this double only owns the process boundary.
    """

    def __init__(self, *, gate: asyncio.Event, blocked_starts: int = 1) -> None:
        """Bind the gate the first ``blocked_starts`` start calls wait on.

        Args:
            gate (asyncio.Event): Set by the test to let a blocked run finish.
            blocked_starts (int): How many initial start calls block on the
                gate; later calls finish immediately (the parallel-schedule
                case needs one blocked and one free start).
        """
        self._gate: asyncio.Event = gate
        self._blocked_starts: int = blocked_starts
        self.calls: list[str] = []
        self.entered = asyncio.Event()

    async def start(
        self,
        *,
        prompt: str,
        cwd: str | None,
        model: str | None,
        session_id: str,
    ) -> FreshRunResultDAO:
        """Record one start call, signal entry and wait for the gate.

        Args:
            prompt (str): The schedule prompt.
            cwd (str | None): The schedule's working directory override.
            model (str | None): The schedule's model override.
            session_id (str): The minted session id for this run.

        Returns:
            FreshRunResultDAO: A completed run with exit code 0.
        """
        self.calls.append(session_id)
        self.entered.set()
        if len(self.calls) <= self._blocked_starts:
            await self._gate.wait()
        return FreshRunResultDAO(session_id=session_id, exit_code=0, status="completed")


class LeakingLease:
    """A honker lock double that reports the lease lost on first renewal.

    honker is the third-party boundary here; the double exercises the engine's
    renewal loop without waiting for a real TTL race.
    """

    def __init__(self) -> None:
        """Acquire trivially; every renewal fails."""
        self.renew_calls: int = 0

    def __enter__(self) -> "LeakingLease":
        """Acquire the lease."""
        return self

    def renew(self, ttl: int | None = None) -> bool:
        """Report the lease lost after the first renewal attempt.

        Args:
            ttl (int | None): Unused; matches the honker signature.

        Returns:
            bool: False — another owner took the expired lease.
        """
        self.renew_calls += 1
        return False

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        """Release the lease."""
        return False


class FailingRenewalLease:
    """A honker lock double whose renew raises — honker renew does real I/O.

    honker is the third-party boundary here; the double exercises the engine's
    supervision of a renewal that raises (e.g. a storage failure) without
    waiting for a real transaction error.
    """

    def __init__(self) -> None:
        """Acquire trivially; every renewal raises."""
        self.renew_calls: int = 0
        self.release_calls: int = 0

    def __enter__(self) -> "FailingRenewalLease":
        """Acquire the lease."""
        return self

    def renew(self, ttl: int | None = None) -> bool:
        """Raise on the first renewal attempt.

        Args:
            ttl (int | None): Unused; matches the honker signature.

        Returns:
            bool: Never returns; the renewal storage fails.

        Raises:
            OSError: The renewal transaction cannot be committed.
        """
        self.renew_calls += 1
        raise OSError("renewal storage failed")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        """Release the lease; the engine must still attempt it."""
        self.release_calls += 1
        return False


def _no_reference_input(name: str) -> NewScheduleDAO:
    """Build one continuous schedule with no session reference (runs fresh)."""
    return NewScheduleDAO(
        name=name,
        prompt=f"{name} prompt",
        trigger=IntervalTriggerDAO(every_seconds=3600),
        session_mode="continuous",
    )


async def _create_schedule_with_two_invocations(*, tmp_path: Path, now: datetime) -> tuple[UUID, list[UUID]]:
    """Create one no-reference schedule and two pending invocations for it."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        created = await service.create(new_schedule=_no_reference_input("Partitioned target"), now=now)
        first = await service.trigger_now(reference=str(created.id), now=now)
        second = await service.trigger_now(reference=str(created.id), now=now + timedelta(milliseconds=1))
    finally:
        await service.close()
        await database.close()
    return created.id, [first.id, second.id]


async def _wait_for(*, event: asyncio.Event, timeout_seconds: float = 5.0) -> None:
    """Await one event with a bound."""
    await asyncio.wait_for(event.wait(), timeout=timeout_seconds)


async def test_one_schedule_never_delivers_two_invocations_at_once(tmp_path: Path) -> None:
    """A8: while one delivery runs, a second invocation of the same schedule
    is refused by the lock and never starts until the first completes."""
    now = _utc_now()
    schedule_id, invocation_ids = await _create_schedule_with_two_invocations(tmp_path=tmp_path, now=now)
    gate = asyncio.Event()
    runner = GatedFreshRunner(gate=gate)
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        delivery_lock_ttl_seconds=60,
        fresh_runs=runner,
    )
    engine.open()
    try:
        first = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[0]), schedule_id=str(schedule_id))
        )
        await _wait_for(event=runner.entered)
        assert len(runner.calls) == 1, "the first delivery is the only one running"

        second = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[1]), schedule_id=str(schedule_id))
        )
        with pytest.raises(honker.Retryable):
            await asyncio.wait_for(second, timeout=10)
        assert len(runner.calls) == 1, "no second child start while the first delivery runs"

        gate.set()
        await asyncio.wait_for(first, timeout=10)
        assert len(runner.calls) == 1

        await engine.deliver_one(invocation_id=str(invocation_ids[1]), schedule_id=str(schedule_id))
        assert len(runner.calls) == 2, "the second invocation delivers after the first ends"
    finally:
        gate.set()
        engine.close()


async def test_renewal_keeps_exclusion_past_the_lock_ttl(tmp_path: Path) -> None:
    """A8 (renewal): a delivery longer than the lock TTL keeps the schedule
    locked; the second attempt is refused after the original TTL expired.

    The TTL is 3 s because honker stores lock expiry at whole-second
    granularity: with ttl=1 the margin after a renewal can drop below the
    renewal interval and the lease lapses spuriously."""
    now = _utc_now()
    schedule_id, invocation_ids = await _create_schedule_with_two_invocations(tmp_path=tmp_path, now=now)
    gate = asyncio.Event()
    runner = GatedFreshRunner(gate=gate)
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        delivery_lock_ttl_seconds=3,
        fresh_runs=runner,
    )
    engine.open()
    try:
        first = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[0]), schedule_id=str(schedule_id))
        )
        await _wait_for(event=runner.entered)
        await asyncio.sleep(3.5)  # longer than the TTL; the renewal keeps ownership

        second = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[1]), schedule_id=str(schedule_id))
        )
        with pytest.raises(honker.Retryable):
            await asyncio.wait_for(second, timeout=10)
        assert len(runner.calls) == 1
    finally:
        gate.set()
        await asyncio.wait_for(first, timeout=10)
        engine.close()


async def test_lost_lease_cancels_the_delivery(tmp_path: Path) -> None:
    """A8 (lease loss): a renewal that reports a lost lease cancels the
    delivery and asks the worker to retry; the row never completes twice."""
    now = _utc_now()
    schedule_id, invocation_ids = await _create_schedule_with_two_invocations(tmp_path=tmp_path, now=now)
    gate = asyncio.Event()
    runner = GatedFreshRunner(gate=gate)
    lease = LeakingLease()
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        delivery_lock_ttl_seconds=1,
        fresh_runs=runner,
        delivery_locks=lambda schedule_id: lease,
    )
    engine.open()
    try:
        first = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[0]), schedule_id=str(schedule_id))
        )
        await _wait_for(event=runner.entered)
        with pytest.raises(honker.Retryable):
            await asyncio.wait_for(first, timeout=10)
        assert len(runner.calls) == 1, "the cancelled run started exactly once"
    finally:
        gate.set()
        engine.close()


async def test_failed_renewal_supervises_the_delivery(tmp_path: Path) -> None:
    """FRR111-03: a renewal that raises stops the delivery, asks the worker to
    retry, and still releases the lease — the delivery never outlives the
    failed lease maintenance."""
    now = _utc_now()
    schedule_id, invocation_ids = await _create_schedule_with_two_invocations(tmp_path=tmp_path, now=now)
    gate = asyncio.Event()
    runner = GatedFreshRunner(gate=gate)
    lease = FailingRenewalLease()
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        delivery_lock_ttl_seconds=1,
        fresh_runs=runner,
        delivery_locks=lambda schedule_id: lease,
    )
    engine.open()
    try:
        first = asyncio.create_task(
            engine.deliver_one(invocation_id=str(invocation_ids[0]), schedule_id=str(schedule_id))
        )
        await _wait_for(event=runner.entered)
        with pytest.raises(honker.Retryable):
            await asyncio.wait_for(first, timeout=10)
        assert len(runner.calls) == 1, "the cancelled run started exactly once"
        assert lease.renew_calls == 1, "renewal ran once and failed"
        assert lease.release_calls == 1, "the engine still released the lease"
    finally:
        gate.set()
        engine.close()


async def test_different_schedules_deliver_in_parallel(tmp_path: Path) -> None:
    """A9: a slow delivery of one schedule does not block another schedule."""
    now = _utc_now()
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        slow = await service.create(new_schedule=_no_reference_input("Slow target"), now=now)
        fast = await service.create(new_schedule=_no_reference_input("Fast target"), now=now)
        slow_invocation = await service.trigger_now(reference=str(slow.id), now=now)
        fast_invocation = await service.trigger_now(reference=str(fast.id), now=now)
    finally:
        await service.close()
        await schedules_db.close()

    gate = asyncio.Event()
    runner = GatedFreshRunner(gate=gate, blocked_starts=1)
    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        fresh_runs=runner,
    )
    engine.open()
    try:
        slow_task = asyncio.create_task(
            engine.deliver_one(invocation_id=str(slow_invocation.id), schedule_id=str(slow.id))
        )
        await _wait_for(event=runner.entered)
        await asyncio.wait_for(
            engine.deliver_one(invocation_id=str(fast_invocation.id), schedule_id=str(fast.id)),
            timeout=10,
        )
        assert len(runner.calls) == 2, "the fast schedule delivered while the slow one ran"
    finally:
        gate.set()
        await asyncio.wait_for(slow_task, timeout=10)
        engine.close()
