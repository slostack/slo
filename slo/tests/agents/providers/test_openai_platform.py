"""Protected Platform options: pure policy followed by real SDK acceptance."""

from copy import deepcopy

import pytest
from pydantic import SecretStr
from langchain_core.runnables import RunnableBinding
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_openai import ChatOpenAI
from src.agents.model_catalog.dao import ReasoningLevel


@pytest.fixture(autouse=True)
def block_default_transports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep all provider tests on explicitly injected offline transports."""
    import httpx

    def reject(*args: object, **kwargs: object) -> None:
        """Reject an accidental default transport before network I/O."""
        raise AssertionError("default network transport is forbidden")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject)


@pytest.mark.parametrize("key", ["max_tokens", "max_completion_tokens", "max_output_tokens"])
@pytest.mark.parametrize("value", [None, 1234])
def test_call_caps_normalize_before_default_merge(key: str, value: object) -> None:
    """One cap uses the SDK default spelling and null aliases leave defaults intact."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    options = {"max_tokens": None, "max_completion_tokens": None, "max_output_tokens": None, key: value}
    before = dict(options)
    assert OpenAIRequestPolicy.normalize_output_override(options=options) == (
        {} if value is None else {"max_completion_tokens": 1234}
    )
    assert options == before
    assert OpenAIRequestPolicy.normalize_output_override(options={"unrelated": 1}) == {"unrelated": 1}


@pytest.mark.parametrize("value", [True, False, 0, -1, "1234", 1.5])
def test_invalid_caps_reject_without_values(value: object) -> None:
    """Output caps require positive strict integers before conversion."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    with pytest.raises(ValueError, match=r"^Invalid OpenAI output limit\.$"):
        OpenAIRequestPolicy.normalize_output_override(options={"max_tokens": value})


@pytest.mark.parametrize("other", [1234, 5678])
def test_multiple_nonnull_caps_reject_even_equal(other: int) -> None:
    """Ambiguous cap aliases cannot depend on SDK merge order."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    with pytest.raises(ValueError, match=r"^Conflicting OpenAI output limits\.$"):
        OpenAIRequestPolicy.normalize_output_override(
            options={"max_tokens": 1234, "max_output_tokens": other}
        )


def test_factory_rejects_oauth_before_either_constructor() -> None:
    """Static denial checks the captured credential before any backend construction."""
    from unittest.mock import patch
    from src.agents.base import LLMFactory
    from src.agents.model_catalog.dao import ModelBackendEligibilityError
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

    from src.agents.model_catalog.seed import SeedModelCatalog

    model_name = "gpt-fixture-ineligible-89"
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(
        update={"model_name": model_name, "supports_chatgpt_codex": False}
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, model_name: entry}})
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.OAUTH, access_token="fixture-oauth-89"
    )
    with (
        patch("src.agents.base.CredentialResolver.require", return_value=credential) as require,
        patch("src.agents.base.ChatOpenAI", side_effect=AssertionError("Platform construction")) as platform,
        patch(
            "src.agents.base.build_chatgpt_backed_chat_openai",
            side_effect=AssertionError("Codex construction"),
        ) as codex,
    ):
        with pytest.raises(ModelBackendEligibilityError, match="requires an OpenAI Platform API key"):
            LLMFactory.create(model_name=model_name, snapshot=snapshot)
    require.assert_called_once_with(provider=ProviderName.OPENAI)
    platform.assert_not_called()
    codex.assert_not_called()


@pytest.mark.parametrize("strict", [False, True])
async def test_custom_endpoint_and_enabled_temperature_remain_record_scoped(
    monkeypatch: pytest.MonkeyPatch, strict: bool
) -> None:
    """Legacy enabled sampling stays omitted; strict optional off preserves late merge options."""
    import json
    import httpx
    from src.agents.base import LLMFactory
    from src.agents.model_catalog.service import ModelCatalogService
    from tests.auth.test_credential_resolver import _reload_cfg
    from tests.agents.providers.feature89_responses import response_envelope

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-positive-89")
    monkeypatch.setenv("OPENAI_API_BASE", "https://custom.invalid/v1")
    _reload_cfg()
    name = "gpt-6-luna" if strict else "gpt-5.6-sol"
    snapshot = ModelCatalogService.load()
    entry = snapshot.entries[name]
    snapshot = snapshot.model_copy(
        update={
            "entries": {
                **snapshot.entries,
                name: entry.model_copy(
                    update={
                        "reasoning_profile": entry.reasoning_profile.model_copy(
                            update={"forbid_sampling_parameters_when_enabled": False}
                        )
                    }
                ),
            }
        }
    )
    requests: list[dict[str, object]] = []
    extras = {"include": ["reasoning.encrypted_content"], "extra_body": {"metadata": {"fixture": "89"}}}
    before = deepcopy(extras)

    def respond(request: httpx.Request) -> httpx.Response:
        """Observe actual SDK late merge at the permitted endpoint and return valid JSON."""
        assert str(request.url) == (
            "https://api.openai.com/v1/responses" if strict else "https://custom.invalid/v1/responses"
        )
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            json=response_envelope(
                model_name=name,
                completed=True,
                output=[
                    {
                        "id": "msg_89",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "complete-89", "annotations": []}],
                    }
                ],
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = LLMFactory.create(
            model_name=name,
            snapshot=snapshot,
            reasoning_level="off" if strict else "medium",
            temperature=0.3,
            model_kwargs=extras,
            streaming=False,
            http_async_client=client,
        )
        answer = await result.llm.ainvoke(input="answer")
    assert "complete-89" in str(answer.content)
    assert len(requests) == 1 and requests[0]["stream"] is False
    assert requests[0].get("temperature") == (0.3 if strict else None)
    assert requests[0]["metadata"] == {"fixture": "89"}
    assert requests[0]["include"] == ["reasoning.encrypted_content"]
    assert extras == before


async def test_factory_clients_keep_their_pinned_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live client retains A after B publishes; the next factory consumes B."""
    import json
    import httpx
    from unittest.mock import patch
    from src.agents.base import LLMFactory
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.model_catalog.service import ModelCatalogService
    from tests.auth.test_credential_resolver import _reload_cfg
    from tests.agents.providers.feature89_responses import answer_frames
    from src.agents.reasoning_capabilities import default_reasoning_level_for_model

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-pinned-89")
    _reload_cfg()
    first = SeedModelCatalog.load()
    entry = first.entries["gpt-6-luna"]
    changed = entry.model_copy(
        update={
            "runtime_profile": entry.runtime_profile.model_copy(update={"max_tokens": 2048}),
            "reasoning_profile": entry.reasoning_profile.model_copy(update={"default_level": "high"}),
        }
    )
    second = first.model_copy(
        update={"entries": {**first.entries, entry.model_name: changed}, "generation": 2}
    )
    bodies: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Parse actual SDK requests and return a complete synthetic answer."""
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer fixture-pinned-89"
        bodies.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=answer_frames(model_name="gpt-6-luna"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch.object(ModelCatalogService, "load", return_value=first):
            old = LLMFactory.create(
                model_name="gpt-6-luna",
                snapshot=first,
                http_async_client=client,
                reasoning_level=default_reasoning_level_for_model(model_name="gpt-6-luna", snapshot=first),
            )
        with patch.object(ModelCatalogService, "load", return_value=second):
            new = LLMFactory.create(
                model_name="gpt-6-luna",
                snapshot=second,
                http_async_client=client,
                reasoning_level=default_reasoning_level_for_model(model_name="gpt-6-luna", snapshot=second),
            )
        with patch.object(ModelCatalogService, "load", side_effect=AssertionError("adapter reload")):
            for result in (old, new, old):
                answer = await result.llm.ainvoke(input="test")
                assert "complete-89" in str(answer.content)
    assert [body["max_output_tokens"] for body in bodies] == [128000, 2048, 128000]
    assert [body["reasoning"] for body in bodies] == [
        {"effort": "medium", "summary": "auto"},
        {"effort": "high", "summary": "auto"},
        {"effort": "medium", "summary": "auto"},
    ]


def test_adapter_policy_lifetime_and_payload() -> None:
    """The thin adapter requires one pinned policy and retains converted tools/caps."""
    from src.agents.providers.openai_platform import OpenAIPlatformChatOpenAI
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.reasoning_capabilities import resolve_reasoning_config
    from src.agents.tools.echo import echo_tool

    model = OpenAIPlatformChatOpenAI(
        model="gpt-6-luna",
        api_key=SecretStr("fixture-openai-89"),
        use_responses_api=True,
        output_version="responses/v1",
        max_completion_tokens=128000,
    )
    with pytest.raises(ValueError, match="^OpenAI request policy is not configured"):
        model._get_request_payload(input_="hello")
    reasoning = resolve_reasoning_config(
        model_name="gpt-6-luna", requested_level="off", snapshot=SeedModelCatalog.load()
    )
    model.configure_request_policy(model_name="gpt-6-luna", reasoning=reasoning, forbid_sampling=False)
    with pytest.raises(ValueError, match="^OpenAI request policy is already configured"):
        model.configure_request_policy(model_name="other", reasoning=reasoning, forbid_sampling=True)
    reasoning.provider_effort = "changed"
    bound = model.bind_tools(tools=[echo_tool])
    assert isinstance(bound, RunnableBinding)
    payload = model._get_request_payload(input_="hello", max_tokens=1234, **bound.kwargs)
    assert payload["model"] == "gpt-6-luna"
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["max_output_tokens"] == 1234
    tools = payload["tools"]
    assert isinstance(tools, list)
    assert tools[0]["name"] == "echo"
    assert "function" not in tools[0]


async def test_adapter_nonstreaming_sdk_parses_complete_response() -> None:
    """The retained adapter completes real SDK JSON parsing after late-body sanitation."""
    import json
    import httpx
    from unittest.mock import patch
    from src.agents.providers.openai_platform import OpenAIPlatformChatOpenAI
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.reasoning_capabilities import resolve_reasoning_config

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve one complete synthetic Responses result on the sole permitted URL."""
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.method == "POST"
        requests.append(request)
        return httpx.Response(
            status_code=200,
            json={
                "id": "resp_89_answer",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-6-luna",
                "error": None,
                "incomplete_details": None,
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_89",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "complete-89", "annotations": []}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        model = OpenAIPlatformChatOpenAI(
            model="gpt-6-luna",
            api_key=SecretStr("fixture-openai-89"),
            base_url="https://api.openai.com/v1",
            use_responses_api=True,
            output_version="responses/v1",
            max_completion_tokens=128000,
            streaming=False,
            http_async_client=client,
        )
        model.configure_request_policy(
            model_name="gpt-6-luna",
            reasoning=resolve_reasoning_config(
                model_name="gpt-6-luna", requested_level="medium", snapshot=SeedModelCatalog.load()
            ),
            forbid_sampling=True,
        )
        with patch.object(
            httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("network")
        ):
            answer = await model.bind(extra_body={"temperature": 0.9}, temperature=0.4).ainvoke(
                input="hello", max_tokens=1234
            )
    assert isinstance(answer.content, list)
    part = answer.content[0]
    assert isinstance(part, dict)
    assert part["text"] == "complete-89"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is False
    assert body["max_output_tokens"] == 1234
    assert body["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert "temperature" not in body
    assert requests[0].headers["authorization"] == "Bearer fixture-openai-89"


@pytest.mark.parametrize(
    "model_name,level,effort",
    [
        ("gpt-6-luna", "off", "none"),
        ("gpt-6-sol", "off", "none"),
        ("gpt-6.1-sol", "off", "low"),
        ("gpt-6-luna", "medium", "medium"),
    ],
)
@pytest.mark.parametrize(
    "temperature,extras,expected",
    [
        (None, {}, 0.1),
        (None, {"temperature": 0.3}, 0.3),
        (0.4, {}, 0.4),
        (0.3, {"temperature": 0.3}, 0.3),
        (0.4, {"temperature": 0.3}, 0.3),
        (None, {"temperature": None}, None),
        (0.4, {"temperature": None}, None),
        (0.4, {"temperature": 0.3, "extra_body": {"temperature": 0.6}}, 0.6),
    ],
)
@pytest.mark.parametrize(
    "cap",
    [
        {},
        {"max_tokens": None},
        {"max_tokens": 1234},
        {"max_completion_tokens": 1234},
        {"max_output_tokens": 1234},
    ],
)
async def test_factory_luna_off_completes_locked_sdk_response(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    level: ReasoningLevel,
    effort: str,
    temperature: float | None,
    extras: dict[str, object],
    expected: float | None,
    cap: dict[str, object],
) -> None:
    """Public construction pins Platform policy and preserves off sampling and call caps."""
    import json
    import httpx
    from src.agents.base import LLMFactory
    from src.agents.providers.openai_platform import OpenAIPlatformChatOpenAI

    from tests.auth.test_credential_resolver import _reload_cfg

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-openai-89")
    _reload_cfg()
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hostile.invalid/v1")
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a complete JSON envelope only on the authorized synthetic route."""
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.method == "POST"
        requests.append(request)
        return httpx.Response(
            status_code=200,
            json={
                "id": "resp_89_answer",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": model_name,
                "error": None,
                "incomplete_details": None,
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_89",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "complete-89", "annotations": []}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        before = deepcopy(extras)
        result = LLMFactory.create(
            model_name=model_name,
            reasoning_level=level,
            temperature=temperature,
            model_kwargs=extras,
            streaming=False,
            http_async_client=client,
        )
        assert isinstance(result.llm, OpenAIPlatformChatOpenAI)
        answer = await result.llm.ainvoke(input="hello", config=None, stop=None, **cap)
    assert answer.content == [{"type": "text", "text": "complete-89", "annotations": [], "id": "msg_89"}]
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is False
    assert extras == before
    assert body["reasoning"] == (
        {"effort": "none"} if effort == "none" else {"effort": effort, "summary": "auto"}
    )
    if effort != "none" or expected is None:
        assert "temperature" not in body
    else:
        assert body["temperature"] == expected
    assert body["max_output_tokens"] == (1234 if 1234 in cap.values() else 128000)
    assert not {"max_tokens", "max_completion_tokens"}.intersection(body)
    assert requests[0].headers["authorization"] == "Bearer fixture-openai-89"


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
@pytest.mark.parametrize(
    "level,effort",
    [
        ("off", "none"),
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "max"),
    ],
)
@pytest.mark.parametrize("oauth", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_factory_stream_parses_complete_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    oauth: bool,
    streaming: bool,
    model_name: str,
    level: ReasoningLevel,
    effort: str,
) -> None:
    """Real factory and locked SDK assemble the complete fragmented function call."""
    import httpx
    from src.agents.base import LLMFactory
    from src.agents.tools.echo import echo_tool, EchoTool
    from unittest.mock import patch
    from tests.auth.test_credential_resolver import _reload_cfg
    from tests.agents.providers.feature89_responses import tool_frames, answer_frames
    from langchain_core.messages import HumanMessage
    import json

    requests: list[httpx.Request] = []

    from src.auth.credential_store import CredentialStore
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
    from src.agents.slo_agent.graph.service import adapt_chatgpt_backend_request
    from langchain_core.messages import SystemMessage

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-account-89"}})
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "" if oauth else "fixture-openai-89")
    _reload_cfg()
    if oauth:
        CredentialStore().persist(cred=_oauth_cred(access_token=token))

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve only the effective lane's complete tool stream."""
        assert str(request.url) == (
            "https://chatgpt.com/backend-api/codex/responses"
            if oauth
            else "https://api.openai.com/v1/responses"
        )
        requests.append(request)
        frames = (
            tool_frames(model_name=model_name) if len(requests) == 1 else answer_frames(model_name=model_name)
        )
        if not streaming:
            completed = json.loads(frames.decode().split("data: ")[-1])["response"]
            return httpx.Response(status_code=200, json=completed)
        return httpx.Response(status_code=200, headers={"Content-Type": "text/event-stream"}, content=frames)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        result = LLMFactory.create(
            model_name=model_name, reasoning_level=level, streaming=streaming, http_async_client=client
        )
        bound = result.llm.bind_tools(tools=[echo_tool])
        if not oauth and (level != "off" or model_name == "gpt-6.1-sol"):
            bound = bound.bind(
                temperature=0.6,
                top_p=0.7,
                top_logprobs=2,
                logprobs=True,
                include=["message.output_text.logprobs"],
                extra_body={
                    "temperature": 0.9,
                    "top_p": 0.8,
                    "top_logprobs": 3,
                    "logprobs": True,
                    "include": ["reasoning.encrypted_content", "message.output_text.logprobs"],
                },
            )
        prompt = HumanMessage(content="hello")
        messages, options = adapt_chatgpt_backend_request(
            llm=result.llm,
            messages=[SystemMessage(content="fixture instructions"), prompt],
            kwargs={"max_tokens": 128000},
        )
        answer = await bound.ainvoke(input=messages, **options)
        assert isinstance(answer, AIMessage)
        assert answer.tool_calls == [
            {"name": "echo", "args": {"text": "echo-89"}, "id": "call_89", "type": "tool_call"}
        ]
        with patch.object(EchoTool, "invoke", wraps=EchoTool.invoke) as echo:
            tool_result = await echo_tool.ainvoke(input=answer.tool_calls[0])
        assert echo.call_count == 1
        assert tool_result.content == "echo-89"
        if streaming:
            chunks = [
                chunk async for chunk in bound.astream(input=[*messages, answer, tool_result], **options)
            ]
            final = chunks[0]
            assert isinstance(final, AIMessageChunk)
            for chunk in chunks[1:]:
                assert isinstance(chunk, AIMessageChunk)
                final += chunk
        else:
            final = await bound.ainvoke(input=[*messages, answer, tool_result], **options)
    assert "complete-89" in str(final.content)
    assert len(requests) == 2
    expected_effort = "low" if model_name == "gpt-6.1-sol" and level == "off" else effort
    for request in requests:
        body = json.loads(request.content)
        assert body["stream"] is streaming
        assert body["model"] == model_name
        assert body["reasoning"] == (
            {"effort": "none"}
            if expected_effort == "none"
            else {"effort": expected_effort, "summary": "auto"}
        )
        assert body.get("max_output_tokens") == (None if oauth else 128000)
        if oauth:
            assert body["instructions"] == "fixture instructions"
            assert body["store"] is False
            assert body["prompt_cache_key"] == model_name
            assert body["include"] == ["reasoning.encrypted_content"]
            assert not any(item.get("role") == "system" for item in body["input"])
            assert request.headers["chatgpt-account-id"] == "fixture-account-89"
            assert request.headers["originator"] == "slo"
            assert request.headers["openai-beta"] == "responses=experimental"
            assert request.headers["session-id"] == request.headers["x-client-request-id"] == model_name
            assert isinstance(result.llm, ChatOpenAI)
            assert result.llm.max_retries == 0
        assert not {
            "max_tokens",
            "max_completion_tokens",
            "provider",
            "reasoning_effort",
            "thinking",
        }.intersection(body)
        if expected_effort != "none":
            assert not {"temperature", "top_p", "top_logprobs", "logprobs"}.intersection(body)
            assert body["include"] == ["reasoning.encrypted_content"]
        if not oauth:
            assert "chatgpt-account-id" not in request.headers
            assert "OpenAI-Beta" not in request.headers
        assert body["tools"][0]["name"] == "echo" and "function" not in body["tools"][0]
        assert request.headers["authorization"] == f"Bearer {token if oauth else 'fixture-openai-89'}"
    items = json.loads(requests[1].content)["input"]
    assert {"type": "function_call_output", "call_id": "call_89", "output": "echo-89"} in items
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call_89" for item in items)


@pytest.mark.parametrize(
    "temperature,extras,expected,collision",
    [
        (None, {"temperature": 0.3}, 0.3, False),
        (1.0, {"temperature": 0.3}, None, True),
        (0.4, {}, None, False),
        (1.0, {}, 1.0, False),
    ],
)
async def test_legacy_temperature_wire_contract(
    monkeypatch: pytest.MonkeyPatch,
    temperature: float | None,
    extras: dict[str, object],
    expected: float | None,
    collision: bool,
) -> None:
    """The legacy SDK validator ordering and Chat Completions wire remain unchanged."""
    import json
    import httpx
    from src.agents.base import LLMFactory
    from src.agents.providers.openai_platform import OpenAIPlatformChatOpenAI
    from tests.auth.test_credential_resolver import _reload_cfg

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-openai-89")
    _reload_cfg()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Complete the legacy route without substituting Responses data."""
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        requests.append(request)
        return httpx.Response(
            status_code=200,
            json={
                "id": "chat_89_legacy",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-5.4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "complete-89"},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        if collision:
            with pytest.raises(ValueError, match="Found temperature supplied twice"):
                LLMFactory.create(
                    model_name="gpt-5.4",
                    reasoning_level="off",
                    streaming=False,
                    temperature=temperature,
                    model_kwargs=dict(extras),
                    http_async_client=client,
                )
            assert not requests
            return
        result = LLMFactory.create(
            model_name="gpt-5.4",
            reasoning_level="off",
            streaming=False,
            temperature=temperature,
            model_kwargs=dict(extras),
            http_async_client=client,
        )
        assert isinstance(result.llm, ChatOpenAI)
        assert not isinstance(result.llm, OpenAIPlatformChatOpenAI)
        assert result.llm.temperature == expected
        assert (await result.llm.ainvoke(input="hello")).content == "complete-89"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is False and "reasoning" not in body
    assert body.get("temperature") == expected
    assert expected is not None or "temperature" not in body


@pytest.mark.parametrize(
    "options,error",
    [
        ({"max_tokens": True}, "Invalid OpenAI output limit"),
        ({"max_tokens": 0}, "Invalid OpenAI output limit"),
        ({"max_output_tokens": -1}, "Invalid OpenAI output limit"),
        ({"max_completion_tokens": "1234"}, "Invalid OpenAI output limit"),
        ({"max_tokens": 1.5}, "Invalid OpenAI output limit"),
        ({"max_tokens": 1234, "max_output_tokens": 1234}, "Conflicting OpenAI output limits"),
        ({"extra_body": {"max_tokens": 1234}}, "OpenAI request options conflict with catalog policy"),
        ({"logprobs": None}, "Use Responses include for logprobs"),
        ({"include": "bad"}, "Invalid OpenAI include options"),
        ({"include": ["ok", 1]}, "Invalid OpenAI include options"),
        ({"include": {}}, "Invalid OpenAI include options"),
        ({"extra_body": {"include": "bad"}}, "Invalid OpenAI include options"),
        ({"extra_body": {"include": ["ok", 1]}}, "Invalid OpenAI include options"),
        ({"extra_body": {"include": {}}}, "Invalid OpenAI include options"),
        ({"extra_body": "bad"}, "Invalid OpenAI extra_body options"),
        ({"extra_body": []}, "Invalid OpenAI extra_body options"),
        ({"extra_body": {1: "bad"}}, "Invalid OpenAI extra_body options"),
        ({"extra_body": {"logprobs": None}}, "Use Responses include for logprobs"),
        ({"extra_body": {"logprobs": False}}, "Use Responses include for logprobs"),
        ({"extra_body": {"logprobs": True}}, "Use Responses include for logprobs"),
    ],
)
@pytest.mark.parametrize("surface", ["call", "bind", "constructor"])
async def test_public_call_invalid_options_make_zero_requests(
    surface: str,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, object],
    error: str,
) -> None:
    """Negative call options fail before the injected SDK transport can be reached."""
    import httpx
    from src.agents.base import LLMFactory
    from tests.auth.test_credential_resolver import _reload_cfg

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-openai-89")
    _reload_cfg()
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        """Count any erroneous transport attempt without permitting network access."""
        requests.append(request)
        raise AssertionError("unexpected transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=reject)) as client:
        before = deepcopy(options)
        expected = error
        if surface == "constructor" and any(key.startswith("max_") for key in options):
            expected = "OpenAI request options conflict with catalog policy"
        with pytest.raises(ValueError, match=expected):
            result = LLMFactory.create(
                model_name="gpt-6-luna",
                reasoning_level="off",
                streaming=False,
                http_async_client=client,
                model_kwargs=options if surface == "constructor" else None,
            )
            if surface == "bind":
                await result.llm.bind(**options).ainvoke(input="hello")
            else:
                await result.llm.ainvoke(
                    input="hello", config=None, stop=None, **(options if surface == "call" else {})
                )
        assert options == before
    assert not requests


PROTECTED = (
    "model",
    "model_name",
    "reasoning",
    "reasoning_effort",
    "use_responses_api",
    "output_version",
    "api_key",
    "openai_api_key",
    "base_url",
    "openai_api_base",
    "client",
    "async_client",
    "root_client",
    "root_async_client",
    "http_client",
    "http_async_client",
    "default_headers",
    "extra_headers",
)


@pytest.mark.parametrize("key", PROTECTED)
@pytest.mark.parametrize("surface", ["constructor", "call", "extra"])
async def test_public_factory_rejects_protected_merge_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    surface: str,
) -> None:
    """Actual factory/binding rejects each protected key with zero transport requests."""
    import httpx
    from src.agents.base import LLMFactory
    from tests.auth.test_credential_resolver import _reload_cfg

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-openai-89")
    _reload_cfg()
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        """Record any attempted HTTP as a test failure, never contact a provider."""
        requests.append(request)
        raise AssertionError("unexpected transport")

    options: dict[str, object] = {key: None}
    if surface == "extra":
        options = {"extra_body": options}
    before = deepcopy(options)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=reject)) as client:
        with pytest.raises(ValueError, match=r"^OpenAI request options conflict with catalog policy\.$"):
            result = LLMFactory.create(
                model_name="gpt-6-luna",
                reasoning_level="off",
                streaming=False,
                model_kwargs=options if surface == "constructor" else {},
                http_async_client=client,
            )
            await result.llm.bind(**options).ainvoke(input="hello")
    assert not requests
    assert options == before


@pytest.mark.parametrize("key", PROTECTED)
@pytest.mark.parametrize("surface", ["constructor", "call", "extra"])
def test_protected_options_reject_by_presence(key: str, surface: str) -> None:
    """Identity and transport belong to the factory, including equal or null overrides."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    options: dict[str, object] = {key: None}
    if surface == "extra":
        options = {"extra_body": options}
    with pytest.raises(ValueError, match=r"^OpenAI request options conflict with catalog policy\.$"):
        OpenAIRequestPolicy.validate_caller_options(options=options, constructor=surface == "constructor")


@pytest.mark.parametrize(
    "key",
    [
        "tools",
        "input",
        "messages",
        "stream",
        "extra_body",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
    ],
)
def test_extra_conversion_fields_are_protected(key: str) -> None:
    """SDK late body cannot replace already converted tools, input or output caps."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    with pytest.raises(ValueError, match="^OpenAI request options conflict with catalog policy"):
        OpenAIRequestPolicy.validate_caller_options(options={"extra_body": {key: "secret"}})


@pytest.mark.parametrize("key", ["max_tokens", "max_completion_tokens", "max_output_tokens"])
def test_constructor_caps_rejected_call_caps_allowed(key: str) -> None:
    """Constructor aliases use the explicit factory argument; call caps are permitted."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    with pytest.raises(ValueError, match="^OpenAI request options conflict with catalog policy"):
        OpenAIRequestPolicy.validate_caller_options(options={key: None}, constructor=True)
    OpenAIRequestPolicy.validate_caller_options(options={key: 1234})
    OpenAIRequestPolicy.validate_caller_options(options={"extra_body": {"unrelated": True}})


@pytest.mark.parametrize("forbid", [False, True])
def test_sampling_leaf_preserves_legacy_shapes(forbid: bool) -> None:
    """Legacy construction copies only its surface and never validates nested values."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    extra = object()
    options = {
        "temperature": 0.3,
        "top_p": 0.4,
        "top_logprobs": 2,
        "logprobs": True,
        "include": "legacy-shape",
        "extra_body": extra,
    }
    result = OpenAIRequestPolicy.sanitize_sampling_fields(options=options, forbid_sampling=forbid)
    expected = {"include": "legacy-shape", "extra_body": extra} if forbid else options
    assert result == expected
    assert result is not options
    assert result["extra_body"] is extra
    assert options["temperature"] == 0.3


@pytest.mark.parametrize("forbid", [False, True])
def test_sanitize_copies_both_surfaces_and_include(forbid: bool) -> None:
    """Nested late-merge sampling follows the same rule without mutating callers."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    include = ["reasoning.encrypted_content", "message.output_text.logprobs", "reasoning.encrypted_content"]
    options = {"temperature": 0.3, "include": include, "extra_body": {"top_p": 0.7, "include": include}}
    before = deepcopy(options)
    result = OpenAIRequestPolicy.sanitize(options=options, forbid_sampling=forbid)
    expected_include = ["reasoning.encrypted_content", "reasoning.encrypted_content"] if forbid else include
    assert result["include"] == expected_include
    extra_result = result["extra_body"]
    assert isinstance(extra_result, dict)
    assert extra_result["include"] == expected_include
    assert ("temperature" in result) is not forbid
    assert ("top_p" in extra_result) is not forbid
    assert result["include"] is not include
    assert result["extra_body"] is not options["extra_body"]
    assert options == before


@pytest.mark.parametrize("surface", ["top", "extra"])
@pytest.mark.parametrize("value", ["secret-shape", ["valid", 3], {"secret": True}])
def test_invalid_include_is_safe(surface: str, value: object) -> None:
    """Strict include rejects malformed shapes on both SDK merge surfaces."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    options = {"include": value}
    if surface == "extra":
        options = {"extra_body": options}
    with pytest.raises(ValueError, match=r"^Invalid OpenAI include options\.$"):
        OpenAIRequestPolicy.sanitize(options=options, forbid_sampling=True)


@pytest.mark.parametrize("value", ["secret", [], {1: "secret"}])
def test_invalid_extra_body_is_safe(value: object) -> None:
    """Malformed late-body values fail without appearing in the error."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    with pytest.raises(ValueError, match=r"^Invalid OpenAI extra_body options\.$"):
        OpenAIRequestPolicy.sanitize(options={"extra_body": value}, forbid_sampling=True)


@pytest.mark.parametrize("surface", ["top", "extra"])
@pytest.mark.parametrize("value", [None, False, True])
def test_logprobs_presence_rejected_off_removed_enabled(surface: str, value: object) -> None:
    """Even null logprobs is a forbidden Chat-Completions field when reasoning is off."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    options = {"logprobs": value}
    if surface == "extra":
        options = {"extra_body": options}
    with pytest.raises(ValueError, match=r"^Use Responses include for logprobs\.$"):
        OpenAIRequestPolicy.sanitize(options=options, forbid_sampling=False)
    result = OpenAIRequestPolicy.sanitize(options=options, forbid_sampling=True)
    assert result == ({"extra_body": {}} if surface == "extra" else {})


@pytest.mark.parametrize("value", [None, [], ["reasoning.encrypted_content"]])
def test_valid_include_and_empty_extra(value: object) -> None:
    """Null and empty inputs remain legitimate strict option shapes."""
    from src.agents.providers.openai_platform import OpenAIRequestPolicy

    assert OpenAIRequestPolicy.sanitize(
        options={"include": value, "extra_body": None}, forbid_sampling=False
    ) == {"include": value, "extra_body": None}
    assert OpenAIRequestPolicy.sanitize(options={"extra_body": {}}, forbid_sampling=False) == {
        "extra_body": {}
    }


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6-sol"])
async def test_optional_off_sampling_survives_actual_late_merge(
    monkeypatch: pytest.MonkeyPatch, model_name: str
) -> None:
    """Off retains Responses sampling and duplicate includes after SDK late merge."""
    import json
    import httpx
    from src.agents.base import LLMFactory
    from tests.auth.test_credential_resolver import _reload_cfg
    from tests.agents.providers.feature89_responses import answer_frames

    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-openai-89")
    _reload_cfg()
    bodies: list[dict[str, object]] = []
    options = {
        "top_p": 0.7,
        "top_logprobs": 2,
        "include": ["reasoning.encrypted_content"],
        "extra_body": {
            "temperature": 0.6,
            "include": [
                "message.output_text.logprobs",
                "reasoning.encrypted_content",
                "reasoning.encrypted_content",
            ],
        },
    }
    before = deepcopy(options)

    def respond(request: httpx.Request) -> httpx.Response:
        """Parse the SDK's final JSON and return a complete locked-SDK stream."""
        assert str(request.url) == "https://api.openai.com/v1/responses"
        bodies.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=answer_frames(model_name=model_name),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = LLMFactory.create(model_name=model_name, reasoning_level="off", http_async_client=client)
        answer = await result.llm.bind(**options).ainvoke(input="hello")
    assert "complete-89" in str(answer.content)
    assert len(bodies) == 1
    assert bodies[0]["reasoning"] == {"effort": "none"}
    assert bodies[0]["top_p"] == 0.7
    assert bodies[0]["top_logprobs"] == 2
    assert bodies[0]["temperature"] == 0.6
    assert bodies[0]["include"] == [
        "message.output_text.logprobs",
        "reasoning.encrypted_content",
        "reasoning.encrypted_content",
    ]
    assert options == before
