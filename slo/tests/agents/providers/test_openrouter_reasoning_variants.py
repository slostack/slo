"""Offline SDK/session regression for distinct reasoning variants sharing an index."""

import json
from pathlib import Path

import httpx
import pytest
from langchain_core.tools import tool
from pydantic import JsonValue

from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.providers.test_openrouter_fragments import _sse
from tests.agents.providers.test_openrouter_transport import _prepared_snapshot, _OPENROUTER_MODEL_NAME


async def test_shared_index_variants_survive_tool_continuation_and_history(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Merge text fragments, retain encrypted metadata, execute once and persist privately."""
    requests: list[dict] = []
    calls: list[str] = []
    details: list[dict[str, object]] = [
        {"index": 0, "type": "reasoning.text", "text": "first second", "format": "google-gemini-v1"},
        {
            "index": 0,
            "type": "reasoning.encrypted",
            "data": "OPAQUE_VARIANT",
            "id": "opaque-id",
            "format": "google-gemini-v1",
            "vendor": {"nested": [True, 1, None]},
        },
    ]

    @tool
    def variant_echo() -> str:
        """Return a local result and record execution without external effects."""
        calls.append("echo")
        return "local result"

    def respond(request: httpx.Request) -> httpx.Response:
        """Substitute only provider HTTP, refusing unexpected retries."""
        requests.append(json.loads(request.content))
        assert len(requests) <= 3
        if len(requests) >= 2:
            return _sse([{"content": "done"}])
        return _sse(
            [
                {"reasoning_details": [{**details[0], "text": "first "}]},
                {"reasoning_details": [details[1]]},
                {
                    "reasoning_details": [{**details[0], "text": "second"}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-variant",
                            "type": "function",
                            "function": {"name": "variant_echo", "arguments": "{}"},
                        }
                    ],
                },
            ]
        )

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="SYNTHETIC_VARIANT_KEY",
            http_async_client=client,
            max_retries=0,
            slo_capabilities=_prepared_snapshot().entries[_OPENROUTER_MODEL_NAME].capabilities,
        )
        session = SloAgentSession(
            agent=SloAgent(llm=model, tools=[variant_echo], cwd=str(tmp_path), system_prompt="Echo."),
            workdir=tmp_path,
            session_id="variant-session",
            history_store=store,
            enable_history=True,
        )
        events = [event async for event in session.invoke(text="echo")]
        resumed = SloAgentSession(
            agent=SloAgent(llm=model, tools=[variant_echo], cwd=str(tmp_path), system_prompt="Echo."),
            workdir=tmp_path,
            session_id=session.session_id,
            history_store=store,
            enable_history=True,
        )
        resumed_events = [event async for event in resumed.invoke(text="continue")]
    assert resumed_events[-1].kind == "run_completed"
    resumed_anchor = next(message for message in requests[2]["messages"] if message["role"] == "assistant")
    assert resumed_anchor["reasoning_details"] == details
    assert events[-1].kind == "run_completed"
    assert calls == ["echo"]
    assert len(requests) == 3
    assistant = next(message for message in requests[1]["messages"] if message["role"] == "assistant")
    assert assistant["reasoning_details"] == details
    assert any(message.get("tool_call_id") == "call-variant" for message in requests[1]["messages"])
    persisted = await store.load_events(session_id=session.session_id)
    extensions = [
        event.payload.provider_message_extension
        for event in persisted
        if event.payload.provider_message_extension is not None
    ]
    assert len(extensions) == 1
    assert extensions[0].reasoning_details == details
    assert "OPAQUE_VARIANT" not in caplog.text
    assert "SYNTHETIC_VARIANT_KEY" not in caplog.text
    assert "OPAQUE_VARIANT" not in "".join(event.model_dump_json() for event in events)


@pytest.mark.parametrize("reverse", [False, True])
async def test_ambiguous_untyped_fragment_fails_without_publishing_extension(reverse: bool) -> None:
    """Reject ambiguous ownership through the SDK regardless of first-seen order."""
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    details: list[dict[str, object]] = [
        {"index": 0, "type": "reasoning.text", "text": "private-text"},
        {"index": 0, "type": "reasoning.encrypted", "data": "private-data"},
    ]
    if reverse:
        details.reverse()
    chunks: list[object] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Deliver two variants followed by an ownerless opaque fragment."""
        return _sse(
            [
                {"reasoning_details": details},
                {"reasoning_details": [{"index": 0, "data": "unassigned"}]},
            ]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="synthetic",
            http_async_client=client,
            max_retries=0,
        )
        with pytest.raises(OpenRouterAPIError) as caught:
            async for chunk in model.astream(input="hello"):
                chunks.append(chunk)
    assert caught.value.diagnostic_reason == "reasoning_field_conflict"
    assert all("provider_message_extension" not in str(chunk) for chunk in chunks)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_shared_index_variants_replay_through_each_sdk_path(
    asynchronous: bool, streaming: bool
) -> None:
    """Retain distinct variants on sync/async streaming and completed responses."""
    from langchain_core.messages import HumanMessage

    requests: list[dict] = []
    details = [
        {"index": 0, "type": "reasoning.text", "text": "thought"},
        {"index": 0, "type": "reasoning.encrypted", "data": "opaque"},
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        """Return equivalent synthetic SSE/JSON and capture the replay request."""
        requests.append(json.loads(request.content))
        message: dict[str, object] = {"role": "assistant", "content": "done"}
        if len(requests) == 1:
            message["reasoning_details"] = details
        if streaming:
            return _sse([message])
        return httpx.Response(
            status_code=200, json={"choices": [{"message": message, "finish_reason": "stop"}]}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            model = OpenRouterChatOpenAI(
                slo_model_name="openrouter:vendor/model",
                model="vendor/model",
                api_key="synthetic",
                http_client=client,
                http_async_client=async_client,
                streaming=streaming,
                max_retries=0,
            )
            first = await model.ainvoke(input="hello") if asynchronous else model.invoke(input="hello")
            replay = [HumanMessage(content="hello"), first, HumanMessage(content="continue")]
            if asynchronous:
                await model.ainvoke(input=replay)
            else:
                model.invoke(input=replay)
    assert len(requests) == 2
    assert requests[1]["messages"][1]["reasoning_details"] == details


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_public_sdk_conflict_diagnostic_is_single_and_private(
    asynchronous: bool, streaming: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Exercise real HTTP parsing and error normalization on all four SDK paths."""
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    details: list[dict[str, object]] = [
        {"index": 0, "type": "reasoning.text", "id": "PRIVATE_OLD"},
        {"index": 0, "type": "reasoning.encrypted", "data": "PRIVATE_DATA"},
        {"index": 0, "type": "reasoning.text", "id": "PRIVATE_NEW"},
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a true stable-ID conflict after allocating both known variants."""
        if streaming:
            return _sse([{"reasoning_details": [detail]} for detail in details])
        return httpx.Response(
            status_code=400, json={"error": {"message": "PRIVATE_BODY", "type": "invalid_request"}}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            model = OpenRouterChatOpenAI(
                slo_model_name="openrouter:vendor/model",
                model="vendor/model",
                api_key="PRIVATE_KEY",
                http_client=client,
                http_async_client=async_client,
                streaming=streaming,
                max_retries=0,
            )
            with pytest.raises(OpenRouterAPIError) as caught:
                if asynchronous:
                    await model.ainvoke(input="hello")
                else:
                    model.invoke(input="hello")
    records = [record for record in caplog.records if record.getMessage().startswith("OpenRouter failure ")]
    assert len(records) == 1
    diagnostic = json.loads(records[0].getMessage().removeprefix("OpenRouter failure "))
    assert diagnostic["diagnostic_id"] == caught.value.diagnostic_id
    assert diagnostic["diagnostic_reason"] == ("reasoning_field_conflict" if streaming else None)
    assert diagnostic["error_type"] == "invalid_request"
    assert "PRIVATE_" not in caplog.text + str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_collision_failure_never_executes_or_replays_tool(tmp_path: Path, ambiguous: bool) -> None:
    """A failed colliding stream never becomes a completed private tool anchor."""
    calls: list[str] = []
    requests: list[str] = []

    @tool
    def collision_echo() -> str:
        """Record forbidden execution in this test's memory only."""
        calls.append("executed")
        return "result"

    def respond(request: httpx.Request) -> httpx.Response:
        """Supply a tool fragment before either ambiguity or a true ID conflict."""
        requests.append(str(request.url))
        assert len(requests) == 1
        conflict: dict[str, object] = (
            {"index": 0, "data": "unassigned"}
            if ambiguous
            else {
                "index": 0,
                "type": "reasoning.text",
                "id": "different",
            }
        )
        return _sse(
            [
                {"reasoning_details": [{"index": 0, "type": "reasoning.text", "id": "original"}]},
                {
                    "reasoning_details": [{"index": 0, "type": "reasoning.encrypted", "data": "opaque"}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-collision",
                            "type": "function",
                            "function": {"name": "collision_echo", "arguments": "{}"},
                        }
                    ],
                },
                {"reasoning_details": [conflict]},
            ]
        )

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="synthetic",
            http_async_client=client,
            max_retries=0,
            slo_capabilities=_prepared_snapshot().entries[_OPENROUTER_MODEL_NAME].capabilities,
        )
        session = SloAgentSession(
            agent=SloAgent(llm=model, tools=[collision_echo], cwd=str(tmp_path), system_prompt="Echo."),
            workdir=tmp_path,
            session_id="collision-negative",
            history_store=store,
            enable_history=True,
        )
        from src.integrations.openrouter.exceptions import OpenRouterAPIError

        events = []
        with pytest.raises(OpenRouterAPIError):
            async for event in session.invoke(text="echo"):
                events.append(event)
    assert calls == []
    assert len(requests) == 1
    assert events[-1].kind == "run_failed"
    assert not {"run_completed", "run_retrying", "recovery_started", "stream_reconnecting"}.intersection(
        event.kind for event in events
    )
    persisted = await store.load_events(session_id=session.session_id)
    assert all(event.payload.provider_message_extension is None for event in persisted)


@pytest.mark.parametrize("reverse", [False, True])
def test_known_variants_keep_first_seen_order_and_independent_indexes(reverse: bool) -> None:
    """Assemble all known forms without interleaved indexes moving their slots."""
    from src.agents.providers.openrouter import OpenRouterMessageCodec
    from src.agents.slo_agent.history.dao import ProviderMessageExtensionDAO
    from src.auth.credential_dao import ProviderName

    details: list[dict[str, JsonValue]] = [
        {"index": 0, "type": "reasoning.encrypted", "data": "a"},
        {"index": 0, "type": "reasoning.summary", "summary": "b"},
        {"index": 1, "type": "reasoning.text", "text": "c"},
        {"index": 0, "type": "reasoning.text", "text": "d"},
    ]
    if reverse:
        details.reverse()
    codec = OpenRouterMessageCodec(model_name="openrouter:vendor/model")
    for detail in details + details:
        codec.append(
            extension=ProviderMessageExtensionDAO(
                provider=ProviderName.OPENROUTER,
                source_model_name="openrouter:vendor/model",
                reasoning_details=[detail],
            )
        )
    expected = [
        {
            key: value * 2 if key in {"text", "summary", "data"} and isinstance(value, str) else value
            for key, value in detail.items()
        }
        for detail in details
    ]
    assert codec.build().reasoning_details == expected


def test_single_variant_untyped_fragment_remains_compatible() -> None:
    """Preserve legacy missing-type continuation only while there is one owner."""
    from src.agents.providers.openrouter import OpenRouterMessageCodec
    from src.agents.slo_agent.history.dao import ProviderMessageExtensionDAO
    from src.auth.credential_dao import ProviderName

    codec = OpenRouterMessageCodec(model_name="openrouter:vendor/model")
    details: list[dict[str, JsonValue]] = [
        {"index": 0, "type": "reasoning.encrypted", "data": "a"},
        {"index": 0, "data": "b"},
    ]
    for detail in details:
        codec.append(
            extension=ProviderMessageExtensionDAO(
                provider=ProviderName.OPENROUTER,
                source_model_name="openrouter:vendor/model",
                reasoning_details=[detail],
            )
        )
    assert codec.build().reasoning_details == [{"index": 0, "type": "reasoning.encrypted", "data": "ab"}]


async def test_unknown_type_collision_remains_fail_closed() -> None:
    """Unknown variants cannot bypass stable-type rejection after a known pair."""
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    def respond(request: httpx.Request) -> httpx.Response:
        """Return an unsupported type after two documented forms."""
        return _sse(
            [
                {"reasoning_details": [{"index": 0, "type": "reasoning.text", "text": "a"}]},
                {"reasoning_details": [{"index": 0, "type": "reasoning.encrypted", "data": "b"}]},
                {"reasoning_details": [{"index": 0, "type": "future.variant", "data": "c"}]},
            ]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="synthetic",
            http_async_client=client,
            max_retries=0,
        )
        with pytest.raises(OpenRouterAPIError) as caught:
            async for _ in model.astream(input="hello"):
                pass
    assert caught.value.diagnostic_reason == "reasoning_field_conflict"
