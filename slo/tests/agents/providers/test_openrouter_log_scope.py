"""Lifetime contracts for request-local SDK log protection."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.agents.providers.openrouter import _OpenRouterPrivateRequestLogScope
from tests.agents.providers.test_openrouter_fragments import _InMemoryLogHandler


@pytest.mark.parametrize("overlapping", [False, True])
async def test_scope_keeps_other_request_protected_and_restores_filters(overlapping: bool) -> None:
    """Nested and overlapping tasks retain protection until their own final exit."""
    logger = logging.getLogger("openai._base_client")
    unrelated_filter = logging.Filter()
    logger.addFilter(unrelated_filter)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate
    handler = _InMemoryLogHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    entered = asyncio.Event()
    released = asyncio.Event()

    async def first() -> None:
        """Exit while the second scope remains active."""
        with _OpenRouterPrivateRequestLogScope():
            entered.set()
            await released.wait()

    try:
        if overlapping:
            task = asyncio.create_task(first())
            await entered.wait()
            with _OpenRouterPrivateRequestLogScope():
                released.set()
                await task
                logger.debug("Request options: %s", "OPAQUE_SCOPE_SENTINEL")
        else:
            with _OpenRouterPrivateRequestLogScope():
                with _OpenRouterPrivateRequestLogScope():
                    pass
                logger.debug("Request options: %s", "OPAQUE_SCOPE_SENTINEL")
        logger.debug("Request options: %s", "DIRECT_DIAGNOSTIC")
        assert logger.filters == original_filters
    finally:
        logger.removeHandler(handler)
        logger.removeFilter(unrelated_filter)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
    captured = "\n".join(record.getMessage() for record in handler.records)
    assert "OPAQUE_SCOPE_SENTINEL" not in captured
    assert "DIRECT_DIAGNOSTIC" in captured


def test_thread_scope_exit_does_not_remove_active_sync_scope() -> None:
    """Concurrent synchronous invocations own independent filter lifetimes."""
    logger = logging.getLogger("openai._base_client")
    original_filters = list(logger.filters)
    entered = Event()
    release = Event()

    def request() -> None:
        """Keep the first thread's request active until the second has entered."""
        with _OpenRouterPrivateRequestLogScope():
            entered.set()
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(request)
        assert entered.wait(timeout=5)
        with _OpenRouterPrivateRequestLogScope():
            release.set()
            future.result(timeout=5)
            record = logging.LogRecord(
                name="openai._base_client",
                level=logging.DEBUG,
                pathname=__file__,
                lineno=0,
                msg="Request options: %s",
                args=("private",),
                exc_info=None,
            )
            assert not logger.filter(record=record)
    assert logger.filters == original_filters
