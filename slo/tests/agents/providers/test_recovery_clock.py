"""Recovery clock contracts using injected readings, not live suspend experiments."""

from collections.abc import Iterator

import pytest

from src.agents.providers.stream_recovery.clock import RecoveryElapsedClock


def test_fallback_new_episode_discards_forward_step_maximum() -> None:
    """A wall correction in one episode cannot freeze elapsed in the next."""
    mono: Iterator[float] = iter([0, 1, 2, 3, 4])
    wall: Iterator[float] = iter([100, 1000, 100, 101, 110])
    clock = RecoveryElapsedClock(
        use_boottime=False, monotonic_reader=mono.__next__, wall_reader=wall.__next__
    )
    assert clock() == 0
    assert clock() == 900
    clock.start_episode()
    assert clock() == 0
    assert clock() == 1
    assert clock() == 10


def test_fallback_rollback_fails_closed_until_new_episode() -> None:
    """Rollback poisons the current episode, not subsequent independent recovery."""
    mono: Iterator[float] = iter([0, 1, 2, 3])
    wall: Iterator[float] = iter([100, 99, 101, 102])
    clock = RecoveryElapsedClock(
        use_boottime=False, monotonic_reader=mono.__next__, wall_reader=wall.__next__
    )
    assert clock() == 0
    with pytest.raises(ValueError):
        clock()
    with pytest.raises(ValueError):
        clock()
    clock.start_episode()
    assert clock() == 0
    assert clock() == 1


def test_boottime_is_selected_without_consulting_wall_or_monotonic() -> None:
    """The Linux path reads only the suspend-inclusive source."""

    def forbidden() -> float:
        """Reject accidental fallback clock reads."""
        raise AssertionError("unexpected fallback")

    readings = iter([100.0, 500.0])
    clock = RecoveryElapsedClock(
        use_boottime=True,
        boottime_reader=readings.__next__,
        monotonic_reader=forbidden,
        wall_reader=forbidden,
    )
    assert clock() == 100
    assert clock() == 500


@pytest.mark.parametrize("invalid", [float("inf"), float("nan"), float("-inf")])
def test_invalid_clock_reading_poisons_episode(invalid: float) -> None:
    """Invalid samples cannot reset an episode and permit late reconnects."""
    readings = iter([invalid, 0.0])
    clock = RecoveryElapsedClock(use_boottime=True, boottime_reader=readings.__next__)
    with pytest.raises(ValueError):
        clock()
    with pytest.raises(ValueError):
        clock()
    clock.start_episode()
    assert clock() == 0


def test_clock_read_failure_is_not_silently_replaced_with_another_epoch() -> None:
    """Source failure ends this episode even if subsequent reads could succeed."""

    def unavailable() -> float:
        """Simulate a platform clock failure."""
        raise OSError("clock unavailable")

    clock = RecoveryElapsedClock(use_boottime=True, boottime_reader=unavailable)
    with pytest.raises(OSError):
        clock()
    with pytest.raises(ValueError):
        clock()


def test_wall_advances_elapsed_while_monotonic_is_frozen() -> None:
    """Portable fallback counts an ordinary suspend represented by advancing wall time."""
    readings = iter([100.0, 401.0])
    clock = RecoveryElapsedClock(
        use_boottime=False, wall_reader=readings.__next__, monotonic_reader=lambda: 1.0
    )
    assert clock() == 0
    assert clock() == 301
