"""Real local HTTP client lifetime contracts for the catalog owner."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog import store as store_module
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter, AtomicWriteOutcomeDAO
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.client import OpenRouterAPIClient
from tests.agents.model_catalog.test_atomic_publication import captured_key


@pytest.fixture(autouse=True)
def isolated_owner(tmp_path: Path) -> Iterator[Path]:
    """Keep credentials synthetic and all persistence below verified pytest ancestry."""
    root = tmp_path.resolve(strict=True)
    original = AtomicFileWriter.write_text_with_outcome
    original_text = Path.write_text

    def checked_text(
        self: Path, data: str, encoding: str = "utf-8", errors: str = "strict", newline: str | None = None
    ) -> int:
        """Guard direct fixture writes, including symlinked destination ancestry."""
        assert self.resolve().is_relative_to(root)
        assert self.parent.resolve().is_relative_to(root)
        return original_text(self, data=data, encoding=encoding, errors=errors, newline=newline)

    def checked_write(*, path: Path, text: str, private: bool = True) -> AtomicWriteOutcomeDAO:
        """Validate the resolved destination and parent before real atomic I/O."""
        assert path.resolve().is_relative_to(root)
        assert path.parent.resolve().is_relative_to(root)
        return original(path=path, text=text, private=private)

    with (
        patch.object(store_module, "_global_dir", return_value=root),
        patch.object(Path, "write_text", new=checked_text),
        patch.object(CredentialResolver, "resolve_with_source", return_value=captured_key()),
        patch.object(AtomicFileWriter, "write_text_with_outcome", side_effect=checked_write),
        patch.object(httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("network")),
        patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("network")),
    ):
        ModelCatalogService.reset()
        yield root
        ModelCatalogService.reset()


@pytest.mark.parametrize("owned", [True, False])
@pytest.mark.parametrize("outcome", ["success", "error", "listing_error", "cancel"])
async def test_real_client_exact_close_and_cancellation_drain(
    isolated_owner: Path, owned: bool, outcome: str
) -> None:
    """Exercise actual GET/context teardown, including delayed asynchronous close."""
    requested = asyncio.Event()
    closing = asyncio.Event()
    release_close = asyncio.Event()
    closes: list[bool] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        """Return synthetic wire data or hold a cancellable local request."""
        requested.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        if outcome == "error" or (outcome == "listing_error" and request.url.path.endswith("/models/user")):
            return httpx.Response(status_code=401, json={"error": {}})
        return httpx.Response(status_code=200, json={"data": {} if request.url.path.endswith("/key") else []})

    class ClosingClient(httpx.AsyncClient):
        """Count real transport closure and expose its pending-cleanup boundary."""

        async def aclose(self) -> None:
            """Delay cancellation cleanup until the caller proves it is awaited."""
            closes.append(True)
            closing.set()
            if outcome == "cancel":
                await release_close.wait()
            await super().aclose()

    http = ClosingClient(transport=httpx.MockTransport(respond))
    injected = OpenRouterAPIClient(credential=captured_key().credential, http_client=http)
    with patch("src.integrations.openrouter.client.httpx.AsyncClient", return_value=http):
        task = asyncio.create_task(
            ModelCatalogService.refresh(
                provider=captured_key().credential.provider,
                force=True,
                client_factory=None if owned else lambda credential: injected,
                cache_path=isolated_owner / "cache.json",
            )
        )
        try:
            await asyncio.wait_for(requested.wait(), timeout=5)
            if outcome == "cancel":
                task.cancel()
                if owned:
                    await asyncio.wait_for(closing.wait(), timeout=5)
                    assert not task.done()
                    release_close.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await ModelCatalogService.shutdown()
            else:
                result = await task
                assert result.status == ("refreshed" if outcome == "success" else "failed")
            assert len(closes) == (1 if owned else 0)
            assert http.is_closed is owned
        finally:
            release_close.set()
            await ModelCatalogService.shutdown()
            await asyncio.gather(task, return_exceptions=True)
            if not owned:
                await http.aclose()


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_cancelling_joined_default_waiter_preserves_other_waiter(
    isolated_owner: Path, cancel_first: bool
) -> None:
    """One cancelled default-client subscriber must not tear down another's GET."""
    requested = asyncio.Event()
    release = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        """Hold key verification until cancellation isolation has been observed."""
        requested.set()
        await release.wait()
        return httpx.Response(status_code=200, json={"data": {} if request.url.path.endswith("/key") else []})

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("src.integrations.openrouter.client.httpx.AsyncClient", return_value=http):
        first = asyncio.create_task(
            ModelCatalogService.refresh(
                provider=captured_key().credential.provider,
                force=True,
                cache_path=isolated_owner / "cache.json",
            )
        )
        await asyncio.wait_for(requested.wait(), timeout=5)
        second = asyncio.create_task(
            ModelCatalogService.refresh(
                provider=captured_key().credential.provider,
                force=True,
                cache_path=isolated_owner / "cache.json",
            )
        )
        checkpoint = asyncio.Event()
        asyncio.get_running_loop().call_soon(checkpoint.set)
        await checkpoint.wait()
        try:
            cancelled, retained = (first, second) if cancel_first else (second, first)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert not http.is_closed, "Cancelling a joined waiter closed the shared client"
            release.set()
            assert (await retained).status == "refreshed"
            assert http.is_closed
        finally:
            release.set()
            await ModelCatalogService.shutdown()
            await asyncio.gather(first, second, return_exceptions=True)
