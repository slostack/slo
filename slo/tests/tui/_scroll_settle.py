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

from typing import Callable

from textual.pilot import Pilot


async def pump_until(*, pilot: Pilot, predicate: Callable[[], bool], max_cycles: int = 40) -> None:
    """Pump refresh cycles until a predicate holds, then stop.

    Called by the transcript follow-mode tests after they render a stream event, to
    wait for the deferred bottom-pin reconciliation before asserting scroll offsets.
    Returns as soon as ``predicate`` is satisfied; falls through after ``max_cycles``
    cycles so a genuinely broken pin still fails the caller's assertion rather than
    hanging the test.

    Args:
        pilot (Pilot): The active test pilot driving refresh cycles.
        predicate (Callable[[], bool]): Returns True once the awaited state is reached.
        max_cycles (int): Upper bound on refresh cycles before giving up.
    """
    for _ in range(max_cycles):
        await pilot.pause()
        if predicate():
            return
