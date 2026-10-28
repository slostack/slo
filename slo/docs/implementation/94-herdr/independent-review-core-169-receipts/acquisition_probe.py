"""Independent temp-only acquisition rollback ownership counterexample."""

import asyncio
import errno
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.state_isolation import isolate_suite_slo_home

SUITE_ROOT = isolate_suite_slo_home()

from tests.agents.slo_agent.herdr.test_reporter import reporter


async def probe() -> None:
    """Fail loading after acquisition, then refuse close before actual release."""
    with tempfile.TemporaryDirectory(prefix="core169-acquire-") as directory:
        root = Path(directory).resolve(strict=True)
        owner = reporter(root=root)
        lease = owner._sequence_store._lease
        real_close = os.close
        close_calls: list[int] = []

        def fail_owned_close(fd: int) -> None:
            """Leave only the independently known fixture descriptor open."""
            if fd == lease._fd:
                close_calls.append(fd)
                raise OSError(errno.EIO, "synthetic private rollback fault")
            real_close(fd)

        try:
            with (
                patch.object(owner, "_validate_executable", return_value=None),
                patch.object(
                    owner._sequence_store, "_load", side_effect=ValueError("synthetic invalid counter")
                ),
                patch.object(os, "close", side_effect=fail_owned_close),
                patch.object(
                    owner._transport, "_spawn", side_effect=AssertionError("no spawn permitted")
                ) as spawn,
            ):
                await owner.start()
                intermediate = await owner.close()
                final = await owner.close_transport()
                retired = await owner.drain_retained_external_resources()
                spawn.assert_not_called()
                print("original_lease_retained", lease.retains_external_resources)
                print("original_fd_still_open", lease._fd is not None and bool(os.fstat(lease._fd)))
                print("reporter_lease_held", owner._lease_held)
                print("reporter_retains", owner.retains_external_resources)
                print("intermediate", intermediate.model_dump())
                print("final", final.model_dump())
                print("retired", retired.model_dump())
                print("raw_close_attempts", len(close_calls))
                assert lease.retains_external_resources
                assert not owner.retains_external_resources
                assert final.resources == retired.resources == "drained"
                assert len(close_calls) == 1
                print("REPRODUCED: failed acquisition hides retained pane lease from final disposal evidence")
        finally:
            # The fixture knows its injected close never released this generation.
            if lease._fd is not None:
                real_close(lease._fd)
                lease.close()


if __name__ == "__main__":
    try:
        asyncio.run(probe())
    finally:
        import shutil

        assert SUITE_ROOT.resolve() == SUITE_ROOT
        shutil.rmtree(path=SUITE_ROOT)
