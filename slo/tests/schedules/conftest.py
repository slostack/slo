"""Schedule test fixtures: no automatically started worker outlives its test."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.schedules.worker_processes import retire_workers_under


@pytest.fixture(autouse=True)
def retire_test_schedule_workers(tmp_path: Path, isolated_slo_home: Path) -> Iterator[None]:
    """Retire every worker a test started under its own temporary roots.

    ``slo schedule add`` and ``start`` now start a detached shared worker, so
    each test that runs them owns a real worker process; this teardown stops
    it before the test's directories are released.

    Args:
        tmp_path (Path): The test's temporary directory.
        isolated_slo_home (Path): The test's private SLO_HOME.
    """
    yield
    # Only test-owned roots are searched: an inherited SLO_SCHEDULES_DIR could
    # name a real user store, whose worker a test must never touch.
    retire_workers_under(roots=[tmp_path, isolated_slo_home])
