"""Opt-in bounded asyncio diagnostic for the shutdown hang investigation."""

import asyncio
import sys
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def shutdown_task_probe():
    """Print await chains before pytest's process-level fault-handler deadline."""

    def dump():
        print("\nHANG71 ASYNC TASK CHAINS", file=sys.stderr, flush=True)
        for task in asyncio.all_tasks():
            print(repr(task), file=sys.stderr)
            current = task.get_coro()
            while current is not None:
                frame = getattr(current, "cr_frame", None)
                if frame is not None:
                    print(
                        f"  {frame.f_code.co_filename}:{frame.f_lineno} {frame.f_code.co_name}",
                        file=sys.stderr,
                    )
                    if frame.f_code.co_name == "_finish_shutdown_owner":
                        owner = frame.f_locals["session"]
                        print(
                            f"  selected={owner is frame.f_locals['self']._session} outcome={frame.f_locals.get('outcome')!r}",
                            file=sys.stderr,
                        )
                current = getattr(current, "cr_await", None)
        sys.stderr.flush()

    handle = asyncio.get_running_loop().call_later(3, dump)
    yield
    handle.cancel()
