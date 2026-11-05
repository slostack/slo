"""Recovery-only elapsed clock; watchdog clocks are deliberately unchanged."""

from __future__ import annotations

from collections.abc import Callable
import math
import time


class RecoveryElapsedClock:
    """Use suspend-inclusive BOOTTIME, or conservative episode-relative elapsed time."""

    def __init__(
        self,
        *,
        use_boottime: bool | None = None,
        monotonic_reader: Callable[[], float] = time.monotonic,
        wall_reader: Callable[[], float] = time.time,
        boottime_reader: Callable[[], float] | None = None,
    ) -> None:
        """Select a fixed clock mode without reading clocks during healthy startup.

        Args:
            use_boottime: Explicit mode for clock-contract tests; default detects support.
            monotonic_reader: Portable monotonic source.
            wall_reader: Portable suspend-sensitive wall source.
            boottime_reader: Optional platform clock source for deterministic tests.
        """
        self._use_boottime = hasattr(time, "CLOCK_BOOTTIME") if use_boottime is None else use_boottime
        self._monotonic_reader = monotonic_reader
        self._wall_reader = wall_reader
        self._boottime_reader = boottime_reader
        self.start_episode()

    def start_episode(self) -> None:
        """Discard sampling state only when the session begins an independent episode."""
        self._started_monotonic: float | None = None
        self._started_wall: float = 0.0
        self._previous_wall: float = 0.0
        self._elapsed: float = 0.0
        self._failed = False

    def __call__(self) -> float:
        """Read time; poison this episode on invalid readings or observed wall rollback.

        Fallback cannot detect backward wall adjustments hidden during suspend.
        Forward steps may expire recovery early. Never switch epochs on failure.

        Returns:
            float: Finite BOOTTIME seconds or conservative episode-relative elapsed time.

        Raises:
            OSError: When the selected source fails.
            ValueError: On invalid time or an already failed episode.
        """
        if self._failed:
            raise ValueError("Recovery clock episode failed")
        try:
            return self._read()
        except (OSError, ValueError, OverflowError):
            self._failed = True
            raise

    def _read(self) -> float:
        """Sample the fixed source and advance the portable running maximum."""
        if self._use_boottime:
            seconds = (
                self._boottime_reader()
                if self._boottime_reader is not None
                else time.clock_gettime(time.CLOCK_BOOTTIME)
            )
            return self._finite(seconds=seconds)
        monotonic = self._finite(seconds=self._monotonic_reader())
        wall = self._finite(seconds=self._wall_reader())
        if self._started_monotonic is None:
            self._started_monotonic = monotonic
            self._started_wall = self._previous_wall = wall
        if wall < self._previous_wall:
            raise ValueError("Recovery wall clock moved backward")
        self._previous_wall = wall
        self._elapsed = max(self._elapsed, monotonic - self._started_monotonic, wall - self._started_wall)
        return self._elapsed

    @staticmethod
    def _finite(*, seconds: float) -> float:
        """Reject invalid readings before they can extend recovery."""
        if not math.isfinite(seconds):
            raise ValueError("Invalid recovery clock reading")
        return seconds
