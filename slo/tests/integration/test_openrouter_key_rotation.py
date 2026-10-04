"""Real lazy session/SDK key rotation proof using private local transports only."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from typing import Any
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ResolvedCredentialDAO,
    ProviderName,
)
from src.auth.credential_resolver import CredentialResolver
from src.cli.headless import HeadlessRunner
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.dao import credential_fingerprint


@pytest.mark.parametrize("hold_before_build", [False, True])
async def test_equal_catalog_rotation_rebinds_next_lazy_session_request(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    hold_before_build: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hold the first SDK request, publish equal B metadata, then require B next run.

    Persistence is redirected beneath the resolved pytest root; credentials exist
    only in memory. No tools execute, subprocesses launch, or default HTTP escapes.
    """
    root = tmp_path.resolve()
    history = root / "history"
    cache = root / "catalog.json"
    assert history.resolve().is_relative_to(root)
    assert cache.resolve().is_relative_to(root)
    keys = ("synthetic-rotation-a", "synthetic-rotation-b")
    effective = ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=keys[0]
        ),
        source=CredentialSource.ENVIRONMENT,
    )
    entered, release = asyncio.Event(), asyncio.Event()
    wire_matches: list[bool] = []
    route = "openrouter:vendor/rotation"

    async def respond(request: httpx.Request) -> httpx.Response:
        """Reject unexpected requests and keep all authorization comparisons private."""
        assert request.url.host == "openrouter.ai"
        if request.method == "GET":
            assert request.headers["authorization"] == "Bearer " + effective.credential.access_token
            if request.url.path == "/api/v1/key":
                return httpx.Response(status_code=200, json={"data": {}})
            assert request.url.path == "/api/v1/models/user"
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/rotation",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        }
                    ]
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chat/completions"
        index = len(wire_matches)
        assert index < 3
        if index == 0:
            entered.set()
            await release.wait()
        expected = keys[0] if index == 0 else keys[1]
        wire_matches.append(request.headers["authorization"] == "Bearer " + expected)
        # Do not put raw headers into assertion diagnostics.
        assert wire_matches[-1], "SDK used a stale credential binding"
        chunk = {
            "id": "local",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/rotation",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "local answer"},
                    "finish_reason": "stop",
                }
            ],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    async def drain(session: SloAgentSession) -> list[AgentStreamEventDAO]:
        """Consume the real session generator to completion, retaining public events."""
        return [event async for event in session.invoke(text="Answer without tools.")]

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        original_builder = LLMFactory._build_openrouter

        def build_with_transport(
            *, model_name: str, resolved: dict[str, Any], entry: ModelCatalogEntryDAO
        ) -> OpenRouterChatOpenAI:
            """Inject only the transport into the unchanged normal factory path."""
            resolved["http_async_client"] = http
            return original_builder(model_name=model_name, resolved=resolved, entry=entry)

        with (
            patch.object(CredentialResolver, "resolve_with_source", side_effect=lambda **_: effective),
            patch("src.agents.model_catalog.store._CFG_SLO_HOME", root),
            patch("src.agents.model_catalog.store._cfg", return_value=None),
            patch("src.agents.slo_agent.preferences.service._CFG_SLO_HOME", root),
            patch("src.agents.slo_agent.preferences.service._cfg", return_value=None),
            patch.object(SloAgentSession, "_load_plugins"),
            patch.object(
                httpx.AsyncHTTPTransport,
                "handle_async_request",
                side_effect=AssertionError("Network forbidden"),
            ),
            patch.object(
                httpx.HTTPTransport, "handle_request", side_effect=AssertionError("Network forbidden")
            ),
            patch(
                "src.agents.model_catalog.service.OpenRouterAPIClient",
                side_effect=lambda *, credential: OpenRouterAPIClient(
                    credential=credential, http_client=http
                ),
            ),
            patch.object(LLMFactory, "_build_openrouter", side_effect=build_with_transport) as builds,
        ):
            ModelCatalogService.reset()
            try:
                first = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER)
                assert first.status == "refreshed"
                before = ModelCatalogService.load()
                config = SessionConfigDAO(
                    workdir=root, model_name=route, system_prompt="Local test only.", enable_history=True
                )
                session = SloAgentSession(
                    session_id="rotation-test",
                    workdir=root,
                    config=config,
                    catalog_snapshot=before,
                    history_store=FilesystemSessionHistoryStore(root=history),
                )
                runner = HeadlessRunner(config=config)
                session.subscribe(handler=runner._emit)
                original_refresh = session._refresh_oauth_credential_if_needed

                async def hold_construction() -> None:
                    """Hold after admission but before SDK construction on the first run."""
                    if hold_before_build and not release.is_set():
                        entered.set()
                        await release.wait()
                    await original_refresh()

                monkeypatch.setattr(session, "_refresh_oauth_credential_if_needed", hold_construction)
                task = asyncio.create_task(drain(session=session))
                try:
                    async with asyncio.timeout(15):
                        await entered.wait()
                    effective = effective.model_copy(
                        update={
                            "credential": effective.credential.model_copy(update={"access_token": keys[1]})
                        }
                    )
                    second = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
                    assert second.status == "refreshed"
                    after = ModelCatalogService.load()
                    assert before.entries[route] == after.entries[route]
                    assert session.catalog_snapshot is before
                    assert not task.done()
                finally:
                    release.set()
                    events = await task
                assert wire_matches == [True]
                events += await drain(session=session)
                assert wire_matches == [True, True]
                assert builds.call_count == 2
                events += await drain(session=session)
                assert wire_matches == [True, True, True]
                assert builds.call_count == 2  # Same key and metadata may reuse the SDK.
                assert sum(event.kind == "run_completed" for event in events) == 3
                captured = capsys.readouterr()
                public = captured.out + captured.err + caplog.text + repr(session) + repr(events)
                public += before.model_dump_json() + after.model_dump_json()
                public += "".join(event.model_dump_json() for event in events)
                for path in history.rglob("*"):
                    assert path.resolve().is_relative_to(root)
                    if path.is_file():
                        public += path.read_text()
                for key in keys:
                    assert key not in public
                    assert credential_fingerprint(access_token=key) not in public
                    # Private catalog provenance may contain a hash, never the key.
                    for path in root.rglob("*"):
                        assert path.resolve().is_relative_to(root)
                        if path.is_file():
                            assert key not in path.read_text()
            finally:
                await ModelCatalogService.shutdown()
                ModelCatalogService.reset()
