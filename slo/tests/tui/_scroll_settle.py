"""Deterministic scroll-settle helper for the transcript follow-mode tests.

Textual 8.x reconciles ``max_scroll_y`` with the deferred scroll restoration a
refresh cycle *after* the ~30 fps coalescing flush timer fires, so a single fixed
``pilot.pause(delay=...)`` sleep is a flaky settle — it passes only when the sleep
happens to be long enough. The transcript follow-mode tests
(``test_scroll_follow``, ``test_pane_scroll_follow``, ``test_app``) call
``pump_until`` to wait deterministically for the awaited scroll state before they
assert, instead of betting on a wall-clock delay.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from textual.pilot import Pilot


async def pump_until(
    *,
    pilot: Pilot,
    predicate: Callable[[], bool],
    max_cycles: int = 40,
    cycle_delay_seconds: float = 0.05,
) -> None:
    """Pump refresh cycles until a predicate holds, then stop.

    Called by the transcript follow-mode tests after they render a stream event, to
    wait for the deferred bottom-pin reconciliation before asserting scroll offsets.
    Returns as soon as ``predicate`` is satisfied; falls through after ``max_cycles``
    cycles so a genuinely broken pin still fails the caller's assertion rather than
    hanging the test.

    Each cycle advances real time by ``cycle_delay_seconds``. A bare ``pilot.pause()``
    only drains the pending message queue, which can complete in near-zero wall-clock
    time — so on a fast, unloaded machine all ``max_cycles`` cycles could elapse before
    the ~30 fps coalescing flush timer ever fired, and the pin was observed only by
    luck. That is what made ``test_stream_event_keeps_follow_mode_when_at_bottom``
    pass locally and fail intermittently on a loaded CI runner. Sleeping between
    cycles guarantees the timer gets the wall clock it needs while preserving the
    early exit, so a settled pin still returns on the first cycle.

    Args:
        pilot (Pilot): The active test pilot driving refresh cycles.
        predicate (Callable[[], bool]): Returns True once the awaited state is reached.
        max_cycles (int): Upper bound on refresh cycles before giving up.
        cycle_delay_seconds (float): Wall-clock delay per cycle, so the coalescing
            flush timer can fire. Defaults to 0.05.
    """
    for _ in range(max_cycles):
        await pilot.pause()
        if predicate():
            return
        await asyncio.sleep(cycle_delay_seconds)
