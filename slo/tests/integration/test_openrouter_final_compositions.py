"""Two finite offline Feature 86 acceptance compositions; no live provider calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.integrations.openrouter.client import OpenRouterAPIClient
from tests.integration.test_openrouter_full_flow import isolated_catalog
from tests.integration.test_openrouter_scheduled_preparation import contained_writes


async def test_complete_removal_during_run_rejects_prepared_resume_with_readable_history(
    isolated_catalog: CredentialStore, contained_writes: list[Path], tmp_path: Path
) -> None:
    """Publish real empty discovery while admitted SDK work waits, then reject resume."""
    route = "openrouter:vendor/removal"
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="removal-test-key"
        )
    )
    entered, release = asyncio.Event(), asyncio.Event()
    removed = False
    requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        """Serve complete discovery and hold the actual admitted inference request."""
        nonlocal requests
        if request.url.path.endswith("/key"):
            return httpx.Response(status_code=200, json={"data": {}})
        if request.url.path.endswith("/models/user"):
            rows = (
                []
                if removed
                else [
                    {
                        "id": "vendor/removal",
                        "context_length": 64000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            )
            return httpx.Response(status_code=200, json={"data": rows})
        assert request.url.path.endswith("/chat/completions")
        requests += 1
        assert json.loads(request.content)["model"] == "vendor/removal"
        entered.set()
        await release.wait()
        chunk = {
            "id": "removal",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/removal",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "admitted answer survives"},
                    "finish_reason": "stop",
                }
            ],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name=route,
        session_id="removal-session",
        history_root=tmp_path / "history",
        enable_history=True,
        system_prompt="Answer briefly.",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:

        def catalog_client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject only the HTTP boundary, retaining catalog publication."""
            return OpenRouterAPIClient(credential=credential, http_client=client)

        original = LLMFactory._build_openrouter

        def local_model(
            *, model_name: str, resolved: dict[str, object], entry: ModelCatalogEntryDAO
        ) -> OpenRouterChatOpenAI:
            """Keep factory policy and SDK, substituting its transport only."""
            return original(
                model_name=model_name, resolved={**resolved, "http_async_client": client}, entry=entry
            )

        with (
            patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=catalog_client),
            patch.object(LLMFactory, "_build_openrouter", side_effect=local_model),
        ):
            session = await SloAgentSession.prepare(config=config)
            admitted = session.catalog_snapshot

            async def drain() -> None:
                """Consume the real history-backed submission through terminal completion."""
                async for _ in session.invoke(text="ordinary removal prompt"):
                    pass

            task = asyncio.create_task(drain())
            try:
                await asyncio.wait_for(entered.wait(), timeout=10)
                removed = True
                result = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
                assert result.status == "refreshed"
                assert route not in ModelCatalogService.load().entries
                assert session.catalog_snapshot == admitted
            finally:
                release.set()
                await task
            store = FilesystemSessionHistoryStore(root=tmp_path / "history")
            assert config.session_id is not None
            metadata = await store.read_metadata(session_id=config.session_id)
            assert metadata.model_name == route
            history_path = tmp_path / "history" / "removal-session" / "events.jsonl"
            before = history_path.read_bytes()
            assert b"admitted answer survives" in before
            with pytest.raises(ModelPreparationRequiredError, match="refresh"):
                await SloAgentSession.prepare(config=config)
            assert history_path.read_bytes() == before
            from src.agents.slo_agent.history.projector import SessionHistoryProjector

            messages = await SessionHistoryProjector.build_message_history(
                events=await store.load_events(session_id=config.session_id)
            )
            assert any(message.content == "admitted answer survives" for message in messages)
            assert requests == 1
            assert contained_writes


@pytest.mark.parametrize("failure_before_session_event", [False, True])
async def test_normalized_provider_failure_populates_headless_status_and_terminal_inbox(
    isolated_catalog: CredentialStore,
    contained_writes: list[Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    failure_before_session_event: bool,
) -> None:
    """One real SDK failure reaches status and notifier with positive public controls."""
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore
    from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
    from src.cli.headless import HeadlessRunner

    secret, body_marker = "FINAL_HEADLESS_SYNTHETIC_KEY", "FINAL_RAW_PROVIDER_BODY"
    isolated_catalog.persist(
        cred=CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=secret)
    )
    history_root = tmp_path / "history"
    monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-final-body")
    monkeypatch.delenv("SLO_PARENT_PID", raising=False)
    monkeypatch.setattr("src.cli.headless.default_history_root", lambda: history_root)
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a body-bearing terminal HTTP failure only at real inference."""
        nonlocal requests
        assert request.headers["authorization"] == f"Bearer {secret}"
        if request.url.path.endswith("/key"):
            return httpx.Response(status_code=200, json={"data": {}})
        if request.url.path.endswith("/models/user"):
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/failure",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        }
                    ]
                },
            )
        assert request.url.path.endswith("/chat/completions")
        requests += 1
        return httpx.Response(
            status_code=400, json={"error": {"type": "invalid_request", "message": f"{secret} {body_marker}"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:

        def catalog_client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Retain production admission while injecting local HTTP."""
            return OpenRouterAPIClient(credential=credential, http_client=client)

        original = LLMFactory._build_openrouter

        def local_model(
            *, model_name: str, resolved: dict[str, object], entry: ModelCatalogEntryDAO
        ) -> OpenRouterChatOpenAI:
            """Retain the SDK normalizer and factory policy."""
            return original(
                model_name=model_name, resolved={**resolved, "http_async_client": client}, entry=entry
            )

        inbox = SessionInboxStore(history_root=history_root)
        notifier = WorkflowNotifier(
            target_session_id="owner",
            orchestrator_session_id="body-session",
            workflow_id="wf-final-body",
            inbox_store=inbox,
        )
        runner = HeadlessRunner(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="openrouter:vendor/failure",
                session_id="body-session",
                history_root=history_root,
                enable_history=True,
                system_prompt="Answer briefly.",
            ),
            notify_session_id="owner",
            notifier=notifier,
        )
        with (
            patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=catalog_client),
            patch.object(LLMFactory, "_build_openrouter", side_effect=local_model),
        ):
            if failure_before_session_event:
                from langchain_core.messages import HumanMessage

                async def fail_before_event(*, session: SloAgentSession, prompt: str) -> None:
                    """Exercise runner fallback when the SDK fails before session emission."""
                    model = LLMFactory.create(
                        model_name=session.active_model_name,
                        snapshot=session.catalog_snapshot,
                        http_async_client=client,
                    ).llm
                    await model.ainvoke(input=[HumanMessage(content=prompt)])

                monkeypatch.setattr(runner, "_drain_session_stream_until_abort", fail_before_event)
            assert await runner.invoke(prompt="ordinary public prompt") == 1

    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines()]
    failures = [event for event in events if event["kind"] == "run_failed"]
    assert len(failures) == 1
    assert "OpenRouter request failed" in failures[0]["content"]
    status_path = history_root / "body-session" / "orchestrator.json"
    status = json.loads(status_path.read_text())
    assert status["state"] == "failed" and status["exit_code"] == 1
    assert status["orchestrator_session_id"] == "body-session"
    pending = await inbox.list_pending(session_id="owner")
    terminals = [message for message in pending if message.kind == "workflow_failed"]
    assert len(terminals) == 1
    assert "OpenRouter request failed" in terminals[0].model_dump_json()
    assert any("ordinary public prompt" in message.model_dump_json() for message in pending)
    public = captured.out + captured.err + caplog.text
    for path in history_root.rglob("*"):
        if path.is_file():
            public += path.read_text()
    assert "ordinary public prompt" in public
    assert "headless_run_failed" in public
    assert secret not in public and body_marker not in public
    assert requests == 1 and contained_writes
