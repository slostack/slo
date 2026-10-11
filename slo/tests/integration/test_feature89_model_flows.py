"""Offline Feature89 acceptance through the mounted app, real SDK, tools and history."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, cast
from unittest.mock import patch

import httpx
import pytest

from src.agents.providers.stream_recovery.dao import ProviderStreamFailure, StreamRecoveryAction
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from src.agents.base import LLMFactory, LLMBuildResult
from src.agents.model_catalog.dao import ReasoningLevel
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.echo import EchoTool, echo_tool
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.tui.app import SloTUI
from src.cli.headless import HeadlessRunner
from src.cli.typer_dispatch import TyperDispatch
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.agents.providers.feature89_responses import answer_frames, tool_frames
from tests.integration.test_openrouter_full_flow import isolated_catalog
from tests.agents.model_catalog.test_feature89_jev_lifecycle import ROUTE, jev_transport


def jev_frames(*, tool: bool, answer: str = "complete-89") -> bytes:
    """Supply full Chat Completions chunks to the real SDK during composed tests."""
    deltas: list[dict[str, object]] = [{"role": "assistant", "content": answer}]
    if tool:
        deltas = [
            {
                "role": "assistant",
                "reasoning_details": [{"type": "encrypted", "data": "private-jev89"}],
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_jev89",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"text":'},
                    }
                ],
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": '"echo-89"}'}}]},
        ]
    chunks: list[dict[str, object]] = [
        {
            "id": "chat_89_tool" if tool else "chat_89_answer",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "typesafe/jev-router",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        for delta in deltas
    ]
    chunks.append(
        {
            **chunks[-1],
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool else "stop"}],
        }
    )
    chunks.append(
        {
            **chunks[-1],
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
    )
    return ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol", ROUTE])
@pytest.mark.parametrize("oauth", [False, True])
@pytest.mark.parametrize("entry", ["default", "explicit", "preference", "child"])
async def test_feature89_headless_routes_use_shared_admission(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    model_name: str,
    oauth: bool,
    entry: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose CLI selection with real headless tools and scan public channels."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    assert (root / "history").resolve().is_relative_to(root)
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-account-89"}})
    isolated_catalog.persist(
        cred=(
            _oauth_cred(access_token=token)
            if oauth
            else CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-openai-89"
            )
        )
    )
    direct = model_name != ROUTE
    frames = (
        [tool_frames(model_name=model_name), answer_frames(model_name=model_name)]
        if direct
        else [jev_frames(tool=True), jev_frames(tool=False)]
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Consume a finite two-response script without callback assertions."""
        requests.append(request)
        if not frames:
            return httpx.Response(status_code=400, json={"error": {"message": "finite script exhausted"}})
        return httpx.Response(
            status_code=200, headers={"content-type": "text/event-stream"}, content=frames.pop(0)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)
        with (
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(**{**kwargs, "http_async_client": client}),
            ),
            patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo,
        ):
            from src.agents.slo_agent.preferences.service import UserPreferencesStore
            from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
            import importlib

            configuration = importlib.import_module("config.cfg")
            model: Optional[str] = model_name
            level = None
            if entry == "default":
                monkeypatch.setitem(configuration.__cfg__, "DEFAULT_MODEL_NAME", model_name)
                model = None
            elif entry == "preference":
                assert UserPreferencesStore._preferences_path().resolve().is_relative_to(root)
                UserPreferencesStore.upsert(model_name=model_name, reasoning_level="low")
                model = None
                level = "low"
            elif entry == "child":
                task = SubAgentTaskDAO(
                    task_id="child89", prompt="offline", model=model_name, reasoning_level="off"
                )
                model, level = task.model, task.reasoning_level
            else:
                level = "max"
            config = TyperDispatch._build_session_config(workdir=root, model=model)
            config = TyperDispatch._apply_reasoning_override(config=config, reasoning=level)
            runner = HeadlessRunner(
                config=config.model_copy(
                    update={
                        "history_root": root / "history",
                        "session_id": "headless89",
                        "extra_tools": [echo_tool],
                    }
                )
            )
            assert await runner.invoke(prompt="run echo-89") == 0
            echo.assert_called_once()
    captured = capsys.readouterr()
    public = captured.out + captured.err + caplog.text
    assert all(
        value not in public
        for value in ("fixture-openai-89", "fixture-jev-A", "private-jev89", token, "fixture-account-89")
    )
    events = [json.loads(line) for line in captured.out.splitlines() if line.startswith('{"kind":')]
    assert [event["content"] for event in events if event["kind"] == "run_completed"] == ["complete-89"]
    assert len(requests) == 2 and not frames
    assert [request.url.path for request in jev_transport] == (
        [] if direct else ["/api/v1/key", "/api/v1/models/user"]
    )
    expected_url = (
        "https://api.openai.com/v1/responses" if direct else "https://openrouter.ai/api/v1/chat/completions"
    )
    if direct and oauth:
        expected_url = "https://chatgpt.com/backend-api/codex/responses"
    direct_token = token if oauth else "fixture-openai-89"
    for request in requests:
        assert request.method == "POST" and str(request.url) == expected_url
        assert request.headers["authorization"] == f"Bearer {direct_token if direct else 'fixture-jev-A'}"
        assert json.loads(request.content)["model"] == (model_name if direct else "typesafe/jev-router")
        if direct:
            effort = {"default": "medium", "explicit": "max", "preference": "low", "child": "none"}[entry]
            if entry == "child" and model_name == "gpt-6.1-sol":
                effort = "low"
            expected = {"effort": effort}
            if effort != "none":
                expected["summary"] = "auto"
            assert json.loads(request.content)["reasoning"] == expected
    for artifact in (root / "history").rglob("*"):
        if artifact.is_file():
            assert artifact.resolve().is_relative_to(root)
            contents = artifact.read_text(encoding="utf-8")
            assert all(
                sentinel not in contents
                for sentinel in (token, "rt-test", "fixture-account-89", "fixture-openai-89", "fixture-jev-A")
            )
    assert runner._session is not None and not runner._session.is_running
    assert runner._session.active_model_name == model_name
    assert runner._operation_credential is None


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol", ROUTE])
async def test_feature89_headless_rejection_precedes_inference(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    model_name: str,
) -> None:
    """Reject fully expired direct OAuth or missing gateway auth before refresh/build."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="fixture-denied-oauth89",
            refresh_token="fixture-refresh89",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    if model_name == ROUTE:
        isolated_catalog.remove(provider=ProviderName.OPENROUTER)
    with (
        patch.object(LLMFactory, "create", side_effect=AssertionError("must not build")) as build,
        patch.object(
            SloAgentSession,
            "_refresh_oauth_credential_if_needed",
            side_effect=AssertionError("must not refresh"),
        ) as refresh,
    ):
        runner = HeadlessRunner(
            config=SessionConfigDAO(
                workdir=root,
                model_name=model_name,
                history_root=root / "history",
                session_id="denied89",
            )
        )
        assert await runner.invoke(prompt="must not infer") == 1
        build.assert_not_called()
        refresh.assert_not_called()
    assert not jev_transport
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.startswith('{"kind":')]
    assert sum(event["kind"] == "run_failed" for event in events) == 1
    assert not any(event["kind"] in {"run_completed", "run_retrying", "run_recovering"} for event in events)
    assert "fixture-denied-oauth89" not in captured.out + captured.err
    assert "fixture-refresh89" not in captured.out + captured.err
    assert runner._session is None or not runner._session.is_running


class CommittedFailureStream(httpx.AsyncByteStream):
    """Yield a genuine SDK content delta before disconnecting the admitted lane."""

    def __init__(self, *, content: bytes) -> None:
        """Retain only the synthetic SSE prefix for this request lifetime."""
        self.content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Deliver the prefix, then report a read failure without another request."""
        yield self.content
        raise httpx.ReadError("synthetic committed disconnect")


class FiniteCommittedTransport:
    """Own one provider's finite stream script and independent request ledger."""

    def __init__(self, *, route: str, continuation: bool) -> None:
        """Build a committed prefix, optionally followed by one successful answer."""
        self.requests: list[httpx.Request] = []
        direct = route == "gpt-6-luna"
        frames = answer_frames(model_name=route) if direct else jev_frames(tool=False)
        prefix = (
            frames.split(b"event: response.output_text.done")[0]
            if direct
            else frames.split(b"\n\n")[0] + b"\n\n"
        )
        self.responses = [
            httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                stream=CommittedFailureStream(content=prefix),
            )
        ]
        if continuation:
            self.responses.append(
                httpx.Response(
                    status_code=200,
                    headers={"content-type": "text/event-stream"},
                    content=frames.replace(b"complete-89", b"continued-89"),
                )
            )

    def respond(self, request: httpx.Request) -> httpx.Response:
        """Capture without callback assertions that could manufacture recovery errors."""
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(status_code=400, json={"error": {"message": "finite script exhausted"}})


@pytest.mark.parametrize("first", ["gpt-6-luna", ROUTE])
@pytest.mark.parametrize("oauth", [False, True])
async def test_prepared_mixed_pool_tool_fallback(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    first: str,
    oauth: bool,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real 429 before output switches lanes without losing bound tool conversion."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-account-89"}})
    isolated_catalog.persist(
        cred=(
            _oauth_cred(access_token=token)
            if oauth
            else CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-openai-89"
            )
        )
    )
    other = ROUTE if first == "gpt-6-luna" else "gpt-6-luna"
    direct_requests: list[httpx.Request] = []
    gateway_requests: list[httpx.Request] = []
    order: list[str] = []

    def provider_transport(*, route: str, ledger: list[httpx.Request]) -> httpx.MockTransport:
        """Build a finite provider script; assert captured wire only after consumption."""
        frames = (
            (tool_frames(model_name=route), answer_frames(model_name=route))
            if route == "gpt-6-luna"
            else (jev_frames(tool=True), jev_frames(tool=False))
        )
        responses = [
            httpx.Response(status_code=200, headers={"content-type": "text/event-stream"}, content=frame)
            for frame in frames
        ]
        if route == first:
            responses = [
                httpx.Response(
                    status_code=429,
                    headers={"retry-after-ms": "1"},
                    json={"error": {"message": "rate limit", "type": "rate_limit"}},
                )
                for _ in range(4 if route == "gpt-6-luna" and not oauth else 1)
            ]

        def respond(request: httpx.Request) -> httpx.Response:
            """Record every attempt without injecting assertion errors into recovery."""
            ledger.append(request)
            order.append(route)
            if responses:
                return responses.pop(0)
            return httpx.Response(status_code=400, json={"error": {"message": "finite script exhausted"}})

        return httpx.MockTransport(respond)

    async with (
        httpx.AsyncClient(transport=provider_transport(route="gpt-6-luna", ledger=direct_requests)) as dc,
        httpx.AsyncClient(transport=provider_transport(route=ROUTE, ledger=gateway_requests)) as gc,
    ):
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)
        with (
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(
                    **{**kwargs, "http_async_client": gc if kwargs["model_name"] == ROUTE else dc}
                ),
            ),
            patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo,
        ):
            pool = ModelPoolDAO(
                entries=[
                    ModelPoolEntryDAO(
                        model_name=name,
                        priority=index,
                        provider=ProviderName.OPENROUTER if name == ROUTE else ProviderName.OPENAI,
                    )
                    for index, name in enumerate((first, other))
                ]
            )
            session = await SloAgentSession.prepare(
                config=SessionConfigDAO(
                    workdir=root, model_pool_dao=pool, history_root=root / "history", extra_tools=[echo_tool]
                )
            )
            events = [event async for event in session.invoke(text="run echo-89")]
            echo.assert_called_once()
    assert order == [first] * (4 if first == "gpt-6-luna" and not oauth else 1) + [other, other]
    assert session.active_model_name == first
    assert session.usage_snapshot().active_model_name == other
    totals = session.refresh_usage_snapshot().session_totals
    assert (totals.input_tokens, totals.output_tokens, totals.total_tokens) == (10, 4, 14)
    assert [event.content for event in events if event.kind == "run_completed"] == ["complete-89"]
    public = "\n".join(event.model_dump_json() for event in events)
    assert "private-jev89" not in public
    captured = capsys.readouterr()
    public += captured.out + captured.err + caplog.text
    artifacts = list((root / "history").rglob("*"))
    assert any(artifact.name == "events.jsonl" for artifact in artifacts)
    for artifact in artifacts:
        assert artifact.resolve().is_relative_to(root)
        if artifact.is_file():
            public += artifact.read_text(encoding="utf-8")
    for sentinel in (token, "rt-test", "fixture-account-89", "fixture-openai-89", "fixture-jev-A"):
        assert sentinel not in public
    for ledger, url, key, model in (
        (
            direct_requests,
            (
                "https://chatgpt.com/backend-api/codex/responses"
                if oauth
                else "https://api.openai.com/v1/responses"
            ),
            token if oauth else "fixture-openai-89",
            "gpt-6-luna",
        ),
        (
            gateway_requests,
            "https://openrouter.ai/api/v1/chat/completions",
            "fixture-jev-A",
            "typesafe/jev-router",
        ),
    ):
        for request in ledger:
            assert request.method == "POST" and str(request.url) == url
            assert request.headers["authorization"] == f"Bearer {key}"
            body = json.loads(request.content)
            assert body["model"] == model and body["stream"] is True
            direct = model == "gpt-6-luna"
            definitions = [tool if direct else tool["function"] for tool in body["tools"]]
            definition = next(tool for tool in definitions if tool.get("name") == "echo")
            assert definition["parameters"]["properties"]["text"]["type"] == "string"
            assert "function" not in definition
            if direct:
                assert definition["type"] == "function" and "messages" not in body
                assert body.get("max_output_tokens") == (None if oauth else 128000)
            else:
                assert body["provider"] == {"require_parameters": True}
                assert body["max_completion_tokens"] == 4096
                assert not {"input", "reasoning", "reasoning_effort", "max_output_tokens"}.intersection(body)
    second = json.loads((gateway_requests if other == ROUTE else direct_requests)[1].content)
    if other == ROUTE:
        assert {"role": "tool", "content": "echo-89", "tool_call_id": "call_jev89"} in second["messages"]
        assistant = next(message for message in second["messages"] if message.get("tool_calls"))
        assert assistant["tool_calls"][0]["id"] == "call_jev89"
        assert assistant["reasoning_details"] == [{"type": "encrypted", "data": "private-jev89"}]
    else:
        assert {"type": "function_call_output", "call_id": "call_89", "output": "echo-89"} in second["input"]
        assert any(
            item.get("type") == "function_call" and item["call_id"] == "call_89" for item in second["input"]
        )


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("first", ["gpt-6-luna", ROUTE])
@pytest.mark.parametrize("oauth", [False, True])
async def test_prepared_pool_cancellation_closes_stream_without_fallback(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    first: str,
    oauth: bool,
    committed: bool,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cancel before/after visible output and release the stream and lock without replay."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-openai-89"
        )
    )
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "cancel-account-89"}})
    if oauth:
        isolated_catalog.persist(cred=_oauth_cred(access_token=token))
    entered, closed = asyncio.Event(), asyncio.Event()
    direct_requests: list[httpx.Request] = []
    gateway_requests: list[httpx.Request] = []

    class WaitingStream(httpx.AsyncByteStream):
        """Hold one provider read until cancellation; record SDK teardown."""

        async def __aiter__(self) -> AsyncIterator[bytes]:
            """Hold after the optional prefix; the consumer owns the committed barrier."""
            if committed:
                frames = answer_frames(model_name=first) if first != ROUTE else jev_frames(tool=False)
                prefix = (
                    frames.split(b"event: response.output_text.done")[0]
                    if first != ROUTE
                    else frames.split(b"\n\n")[0] + b"\n\n"
                )
                yield prefix
            else:
                entered.set()
            await asyncio.Event().wait()
            yield b""

        async def aclose(self) -> None:
            """Observe cancellation-driven response closure."""
            closed.set()

    def transport(*, ledger: list[httpx.Request]) -> httpx.MockTransport:
        """Provide only one waiting response per independent provider ledger."""

        def respond(request: httpx.Request) -> httpx.Response:
            """Capture attempted inference without an assertion-triggered recovery."""
            ledger.append(request)
            if len(ledger) > 1:
                return httpx.Response(status_code=400, json={"error": {"message": "finite script exhausted"}})
            return httpx.Response(
                status_code=200, stream=WaitingStream(), headers={"content-type": "text/event-stream"}
            )

        return httpx.MockTransport(respond)

    other = ROUTE if first == "gpt-6-luna" else "gpt-6-luna"
    pool = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name=name,
                priority=index,
                provider=ProviderName.OPENROUTER if name == ROUTE else ProviderName.OPENAI,
            )
            for index, name in enumerate((first, other))
        ]
    )
    async with (
        httpx.AsyncClient(transport=transport(ledger=direct_requests)) as dc,
        httpx.AsyncClient(transport=transport(ledger=gateway_requests)) as gc,
    ):
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)
        with (
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(
                    **{**kwargs, "http_async_client": gc if kwargs["model_name"] == ROUTE else dc}
                ),
            ),
            patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo,
        ):
            session = await SloAgentSession.prepare(
                config=SessionConfigDAO(
                    workdir=root, model_pool_dao=pool, history_root=root / "history", extra_tools=[echo_tool]
                )
            )
            events = []

            async def consume() -> None:
                """Drain the public session until the test cancels its provider read."""
                async for event in session.invoke(text="cancel-89"):
                    events.append(event)
                    if committed and event.kind == "text_delta" and event.delta:
                        entered.set()

            task = asyncio.create_task(consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=10)
            finally:
                task.cancel()
                await task
            await asyncio.wait_for(closed.wait(), timeout=10)
            echo.assert_not_called()
    assert len(direct_requests) == int(first == "gpt-6-luna")
    assert len(gateway_requests) == int(first == ROUTE)
    assert not session._lock.locked()
    assert not {
        "route_switched",
        "run_retrying",
        "run_recovering",
        "stream_reconnecting",
        "tool_call",
        "run_completed",
    }.intersection(event.kind for event in events)
    assert sum(event.kind == "run_aborted" for event in events) == 1
    assert any(event.kind == "text_delta" and event.delta for event in events) == committed
    captured = capsys.readouterr()
    for sentinel in (token, "rt-test", "cancel-account-89", "fixture-openai-89", "fixture-jev-A"):
        assert sentinel not in captured.out + captured.err + caplog.text
    for request in direct_requests:
        assert str(request.url) == (
            "https://chatgpt.com/backend-api/codex/responses"
            if oauth
            else "https://api.openai.com/v1/responses"
        )
        assert request.headers["authorization"] == f"Bearer {token if oauth else 'fixture-openai-89'}"
    public = "\n".join(event.model_dump_json() for event in events)
    for artifact in (root / "history").rglob("*"):
        assert artifact.resolve().is_relative_to(root)
        if artifact.is_file():
            public += artifact.read_text()
    for sentinel in (token, "cancel-account-89", "rt-test", "fixture-openai-89", "fixture-jev-A"):
        assert sentinel not in public


@pytest.mark.parametrize("first", ["gpt-6-luna", ROUTE])
@pytest.mark.parametrize("oauth", [False, True])
@pytest.mark.parametrize("session_boundary", [False, True])
async def test_committed_pool_failure_boundaries(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    first: str,
    session_boundary: bool,
    oauth: bool,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Distinguish agent no-replay from the unchanged session semantic continuation."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-openai-89"
        )
    )
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "failure-account-89"}})
    if oauth:
        isolated_catalog.persist(cred=_oauth_cred(access_token=token))
    direct = FiniteCommittedTransport(route="gpt-6-luna", continuation=session_boundary)
    gateway = FiniteCommittedTransport(route=ROUTE, continuation=False)
    other = ROUTE if first == "gpt-6-luna" else "gpt-6-luna"
    pool = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name=name,
                priority=index,
                provider=ProviderName.OPENROUTER if name == ROUTE else ProviderName.OPENAI,
            )
            for index, name in enumerate((first, other))
        ]
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(direct.respond)) as dc,
        httpx.AsyncClient(transport=httpx.MockTransport(gateway.respond)) as gc,
    ):
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)
        with (
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(
                    **{**kwargs, "http_async_client": gc if kwargs["model_name"] == ROUTE else dc}
                ),
            ),
            patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo,
        ):
            session = await SloAgentSession.prepare(
                config=SessionConfigDAO(
                    workdir=root,
                    model_pool_dao=pool,
                    history_root=root / "history",
                    session_id="committed89",
                    extra_tools=[echo_tool],
                )
            )
            await session._ensure_agent_ready()
            assert session._agent is not None
            stream = (
                session.invoke(text="run echo-89")
                if session_boundary
                else session._agent.invoke(query="run echo-89")
            )
            events = []
            error_text = ""
            if session_boundary and first == "gpt-6-luna":
                events = [event async for event in stream]
            else:
                with pytest.raises(OpenRouterAPIError if first == ROUTE else ProviderStreamFailure) as caught:
                    async for event in stream:
                        events.append(event)
                assert isinstance(caught.value, (OpenRouterAPIError, ProviderStreamFailure))
                error_text = str(caught.value) + repr(caught.value)
                assert caught.value.partial_output_committed
                if isinstance(caught.value, ProviderStreamFailure):
                    assert caught.value.decision.action is StreamRecoveryAction.DO_NOT_REPLAY
            echo.assert_not_called()
    assert len(direct.requests) == (2 if session_boundary else 1) * (first == "gpt-6-luna")
    assert len(gateway.requests) == (first == ROUTE)
    assert "".join(event.delta or "" for event in events if event.kind == "text_delta") == (
        "complete-89continued-89" if session_boundary and first == "gpt-6-luna" else "complete-89"
    )
    assert not {"route_switched", "run_recovering", "stream_reconnecting", "tool_call"}.intersection(
        event.kind for event in events
    )
    assert sum(event.kind == "run_retrying" for event in events) == int(session_boundary and first != ROUTE)
    assert not session._lock.locked()
    for ledger, url, key in (
        (
            direct.requests,
            (
                "https://chatgpt.com/backend-api/codex/responses"
                if oauth
                else "https://api.openai.com/v1/responses"
            ),
            token if oauth else "fixture-openai-89",
        ),
        (gateway.requests, "https://openrouter.ai/api/v1/chat/completions", "fixture-jev-A"),
    ):
        assert all(request.method == "POST" and str(request.url) == url for request in ledger)
        assert all(request.headers["authorization"] == f"Bearer {key}" for request in ledger)
    public = "\n".join(event.model_dump_json() for event in events)
    captured = capsys.readouterr()
    public += captured.out + captured.err + caplog.text + error_text
    artifacts = list((root / "history").rglob("*"))
    for artifact in artifacts:
        assert artifact.resolve().is_relative_to(root)
        if artifact.is_file():
            public += artifact.read_text()
    for sentinel in (token, "failure-account-89", "rt-test", "fixture-openai-89", "fixture-jev-A"):
        assert sentinel not in public
    if not session_boundary:
        assert not any(event.kind == "run_completed" for event in events)
        return
    path = root / "history/committed89/events.jsonl"
    assert path.resolve().is_relative_to(root)
    history = [json.loads(line) for line in path.read_text().splitlines()]
    failed = [event for event in history if event["kind"] == "run_failed"]
    assert len(failed) == 1
    users = [event for event in history if event["kind"] == "user_message"]
    assert users[0]["payload"]["content"] == "run echo-89"
    if first == ROUTE:
        assert len(users) == 1
        assert not any(event["kind"] in {"run_retrying", "run_completed"} for event in history)
        return
    assert failed[0]["payload"]["metadata"]["partial_output_committed"] is True
    assert len(users) == 2 and users[0]["turn_id"] != users[1]["turn_id"]
    continuation = users[1]["payload"]["content"]
    assert continuation.startswith("Continuation attempt 2/5.")
    assert "Original task:\nrun echo-89" in continuation
    assert "inspect the current worktree, git diff, and task artifacts" in continuation
    assert "Do not repeat a completed or side-effecting operation" in continuation
    assert "synthetic committed disconnect" not in continuation
    second = json.loads(direct.requests[1].content)["input"]
    assert [item["content"] for item in second if item.get("role") == "user"] == ["run echo-89", continuation]
    assert sum(event["kind"] == "run_retrying" for event in history) == 1
    completed = [event for event in history if event["kind"] == "run_completed"]
    assert len(completed) == 1 and completed[0]["payload"]["content"] == "continued-89"
    assert completed[0]["turn_id"] == users[1]["turn_id"]


async def test_mounted_prepared_jev_tool_cycle_and_resume(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Admit the literal Jev row and run real mounted tools with private replay."""
    root = tmp_path.resolve()
    requests: list[dict[str, object]] = []
    public_events: list[AgentStreamEventDAO] = []

    async def observe(event: AgentStreamEventDAO) -> None:
        """Capture session-public DTOs before forwarding to the mounted renderer."""
        public_events.append(event)

    def respond(request: httpx.Request) -> httpx.Response:
        """Reject any cross-provider inference and provide complete SDK SSE."""
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fixture-jev-A"
        requests.append(json.loads(request.content))
        assert len(requests) <= 3
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=jev_frames(
                tool=len(requests) == 1, answer="resume-89" if len(requests) == 3 else "complete-89"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)
        with (
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(**{**kwargs, "http_async_client": client}),
            ),
            patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo,
        ):
            config = SessionConfigDAO(
                workdir=root,
                model_name=ROUTE,
                history_root=root / "history",
                session_id="jev89",
                extra_tools=[echo_tool],
            )
            session = await SloAgentSession.prepare(config=config)
            session.subscribe(handler=observe)
            assert [request.url.path for request in jev_transport] == ["/api/v1/key", "/api/v1/models/user"]
            app = SloTUI(session=session)
            async with app.run_test(size=(120, 40)) as pilot:
                await app._dispatch_slash_command(line=f"/model {ROUTE}")
                await app._dispatch_slash_command(line="/reasoning")
                assert "provider default; controls unavailable" in app._copyable_transcript_text()
                await app._submit_or_queue_prompt(text="run echo-89")
                assert app._in_flight_task is not None
                await app._in_flight_task
                await pilot.pause()
                assert "complete-89" in app._copyable_transcript_text()
            from src.agents.model_catalog.service import ModelCatalogService

            from datetime import datetime, timedelta
            from tests.agents.model_catalog.test_feature89_jev_lifecycle import NOW

            # Expire retained verification, requiring authenticated readmission on resume.
            ModelCatalogService.reset()
            later = NOW + timedelta(hours=2)
            with (
                patch("src.agents.model_catalog.service.datetime", wraps=datetime) as clock,
                patch("src.integrations.openrouter.client.verification_now", return_value=later),
            ):
                clock.now.return_value = later
                with patch(
                    "src.cli.typer_dispatch.FilesystemSessionHistoryStore",
                    return_value=FilesystemSessionHistoryStore(root=root / "history"),
                ):
                    resumed_name = await TyperDispatch._read_resumed_model(session_id="jev89")
                resumed_config = TyperDispatch._build_session_config(
                    workdir=root, resume_session_id="jev89", resumed_model_name=resumed_name
                ).model_copy(update={"history_root": root / "history", "extra_tools": [echo_tool]})
                assert resumed_config.model_name == ROUTE
                resumed = await SloAgentSession.prepare(config=resumed_config)
            assert [request.url.path for request in jev_transport] == [
                "/api/v1/key",
                "/api/v1/models/user",
                "/api/v1/key",
                "/api/v1/models/user",
            ]
            assert resumed is not session and resumed._agent is None
            resumed.subscribe(handler=observe)
            resumed_app = SloTUI(session=resumed)
            async with resumed_app.run_test(size=(120, 40)) as pilot:
                await resumed_app._submit_or_queue_prompt(text="continue-89")
                assert resumed_app._in_flight_task is not None
                await resumed_app._in_flight_task
                await pilot.pause()
                transcript = resumed_app._copyable_transcript_text()
                assert "complete-89" in transcript and "resume-89" in transcript
            echo.assert_called_once()
    captured = capsys.readouterr()
    public = (
        captured.out
        + captured.err
        + caplog.text
        + "\n".join(event.model_dump_json() for event in public_events)
    )
    assert all(value not in public for value in ("fixture-openai-89", "fixture-jev-A", "private-jev89"))
    assert [event.content for event in public_events if event.kind == "run_completed"] == [
        "complete-89",
        "resume-89",
    ]
    assert len(requests) == 3
    for request in requests:
        assert request["model"] == "typesafe/jev-router"
        assert request["stream"] is True and request["max_completion_tokens"] == 4096
        assert request["provider"] == {"require_parameters": True}
        assert not {"reasoning", "reasoning_effort", "input", "max_output_tokens"}.intersection(request)
        tools = request["tools"]
        assert isinstance(tools, list)
        assert any(tool["function"]["name"] == "echo" for tool in tools)
    for request in requests[1:]:
        messages = request["messages"]
        assert isinstance(messages, list)
        assert {"role": "tool", "content": "echo-89", "tool_call_id": "call_jev89"} in messages
        assistant = next(message for message in messages if message.get("tool_calls"))
        assert assistant["tool_calls"][0]["id"] == "call_jev89"
        assert assistant["reasoning_details"] == [{"type": "encrypted", "data": "private-jev89"}]
    events_path = root / "history/jev89/events.jsonl"
    assert events_path.resolve().is_relative_to(root)
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [event["payload"]["content"] for event in events if event["kind"] == "run_completed"] == [
        "complete-89",
        "resume-89",
    ]
    assert [event["payload"]["tool_call_id"] for event in events if event["kind"] == "tool_result"] == [
        "call_jev89"
    ]
    assert "private-jev89" in events_path.read_text()
    assert [event["payload"]["content"] for event in events if event["kind"] == "user_message"] == [
        "run echo-89",
        "continue-89",
    ]
    assert [event["payload"]["content"] for event in events if event["kind"] == "assistant_message"] == [
        "complete-89",
        "resume-89",
    ]
    assert [event["payload"]["model_name"] for event in events if event["kind"] == "run_started"] == [
        ROUTE,
        ROUTE,
    ]
    call = next(event for event in events if event["kind"] == "tool_call")
    result = next(event for event in events if event["kind"] == "tool_result")
    assert call["payload"]["tool_call_id"] == result["payload"]["tool_call_id"] == "call_jev89"
    assert call["payload"]["tool_input"] == {"text": "echo-89"}
    assert result["payload"]["tool_output"] == "echo-89"
    assert result["payload"]["metadata"]["parent_entry_id"] == call["event_id"]
    assert not {"run_failed", "run_retrying", "run_recovering"}.intersection(
        event["kind"] for event in events
    )
    replay = json.dumps(requests[2]["messages"])
    assert replay.index("run echo-89") < replay.index("complete-89") < replay.index("continue-89")
    assert all(sentinel not in transcript for sentinel in ("fixture-jev-A", "private-jev89"))
    for path in (root / "history/jev89").iterdir():
        assert path.resolve().is_relative_to(root)
        if path.is_file():
            text = path.read_text()
            assert "fixture-jev-A" not in text
            if path.name != "events.jsonl":
                assert "private-jev89" not in text


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
@pytest.mark.parametrize("level", ["off", "medium"])
@pytest.mark.parametrize("oauth", [False, True])
async def test_mounted_gpt6_tool_cycle_and_resume(
    isolated_catalog: CredentialStore, tmp_path: Path, model_name: str, level: ReasoningLevel, oauth: bool
) -> None:
    """Execute one real echo through the mounted session and retain its wire call identity."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-account-89"}})
    isolated_catalog.persist(
        cred=(
            _oauth_cred(access_token=token)
            if oauth
            else CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-openai-89"
            )
        )
    )
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve only the two complete synthetic Responses streams for this test."""
        assert request.method == "POST" and str(request.url) == (
            "https://chatgpt.com/backend-api/codex/responses"
            if oauth
            else "https://api.openai.com/v1/responses"
        )
        assert request.headers["authorization"] == f"Bearer {token if oauth else 'fixture-openai-89'}"
        requests.append(json.loads(request.content))
        body = (
            tool_frames(model_name=model_name) if len(requests) == 1 else answer_frames(model_name=model_name)
        )
        if len(requests) == 3:
            body = body.replace(b"complete-89", b"resume-89")
        assert len(requests) <= 3
        return httpx.Response(status_code=200, headers={"content-type": "text/event-stream"}, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        original = cast(Callable[..., LLMBuildResult], LLMFactory.create)

        def create(**kwargs: object) -> LLMBuildResult:
            """Inject only the trusted HTTP client into the unchanged public factory."""
            return original(**{**kwargs, "http_async_client": client})

        with patch.object(LLMFactory, "create", side_effect=create):
            session = await SloAgentSession.prepare(
                config=SessionConfigDAO(
                    workdir=root,
                    model_name="gpt-5.4",
                    reasoning_level="high",
                    history_root=root / "history",
                    session_id="feature89-mounted",
                    extra_tools=[echo_tool],
                )
            )
            app = SloTUI(session=session)
            with patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo:
                async with app.run_test(size=(120, 40)) as pilot:
                    await app._dispatch_slash_command(line=f"/model {model_name}")
                    await app._dispatch_slash_command(line=f"/reasoning {level}")
                    assert session.active_model_name == model_name
                    assert session.active_reasoning_level == level
                    assert not requests
                    await app._submit_or_queue_prompt(text="run echo-89")
                    assert app._in_flight_task is not None
                    await app._in_flight_task
                    await pilot.pause()
                    assert "complete-89" in app._copyable_transcript_text()
                with patch(
                    "src.cli.typer_dispatch.FilesystemSessionHistoryStore",
                    return_value=FilesystemSessionHistoryStore(root=root / "history"),
                ):
                    resumed_name = await TyperDispatch._read_resumed_model(session_id="feature89-mounted")
                resumed_config = TyperDispatch._build_session_config(
                    workdir=root, resume_session_id="feature89-mounted", resumed_model_name=resumed_name
                ).model_copy(update={"history_root": root / "history", "extra_tools": [echo_tool]})
                assert resumed_config.model_name == model_name
                assert resumed_config.reasoning_level == level
                resumed = await SloAgentSession.prepare(config=resumed_config)
                assert resumed is not session and resumed._agent is None
                resumed_app = SloTUI(session=resumed)
                async with resumed_app.run_test(size=(120, 40)) as pilot:
                    await resumed_app._submit_or_queue_prompt(text="continue-89")
                    assert resumed_app._in_flight_task is not None
                    await resumed_app._in_flight_task
                    await pilot.pause()
                    transcript = resumed_app._copyable_transcript_text()
                    assert "complete-89" in transcript and "resume-89" in transcript
                echo.assert_called_once()
    assert len(requests) == 3
    for request in requests:
        assert request["model"] == model_name and request["stream"] is True
        effort = "low" if level == "off" and model_name == "gpt-6.1-sol" else level
        expected = {"effort": "none"} if effort == "off" else {"effort": effort, "summary": "auto"}
        assert request["reasoning"] == expected
        assert request.get("max_output_tokens") == (None if oauth else 128000)
        if oauth:
            assert request["store"] is False
            assert request["instructions"]
            assert request["include"] == ["reasoning.encrypted_content"]
        tools = request["tools"]
        assert isinstance(tools, list)
        echo_definition = [tool for tool in tools if tool.get("name") == "echo"]
        assert len(echo_definition) == 1
        assert echo_definition[0]["type"] == "function"
        assert "function" not in echo_definition[0]
        assert echo_definition[0]["parameters"]["properties"]["text"]["type"] == "string"
    for request in requests[1:]:
        inputs = request["input"]
        assert isinstance(inputs, list)
        assert {"type": "function_call_output", "call_id": "call_89", "output": "echo-89"} in inputs
        assert any(item.get("type") == "function_call" and item["call_id"] == "call_89" for item in inputs)
    replay = json.dumps(requests[2]["input"])
    assert replay.index("run echo-89") < replay.index("complete-89") < replay.index("continue-89")
    events_path = root / "history/feature89-mounted/events.jsonl"
    assert events_path.resolve().is_relative_to(root)
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    kinds = [event["kind"] for event in events]
    assert kinds.count("run_completed") == 2
    assert kinds.count("tool_call") == kinds.count("tool_result") == 1
    assert not {"run_failed", "run_retrying", "run_recovering"}.intersection(kinds)
    assert "fixture-openai-89" not in transcript
    assert [event["payload"]["content"] for event in events if event["kind"] == "user_message"] == [
        "run echo-89",
        "continue-89",
    ]
    assert [event["payload"]["content"] for event in events if event["kind"] == "assistant_message"] == [
        "complete-89",
        "resume-89",
    ]
    call = next(event for event in events if event["kind"] == "tool_call")
    result = next(event for event in events if event["kind"] == "tool_result")
    assert call["payload"]["tool_call_id"] == result["payload"]["tool_call_id"] == "call_89"
    assert call["payload"]["tool_name"] == result["payload"]["tool_name"] == "echo"
    assert call["payload"]["tool_input"] == {"text": "echo-89"}
    assert result["payload"]["tool_output"] == "echo-89"
    assert result["payload"]["metadata"]["parent_entry_id"] == call["event_id"]
    assert [event["payload"]["model_name"] for event in events if event["kind"] == "run_started"] == [
        model_name,
        model_name,
    ]
