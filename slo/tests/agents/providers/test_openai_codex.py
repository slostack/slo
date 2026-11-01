"""Tests for the ChatGPT-backend Responses lane (feature 07 §4.1).

Three layers:

- ``TestExtractChatgptAccountId`` — JWT decoder unit tests.
- ``TestBuildChatgptBackedChatOpenAI`` — constructor-level config assertions
  (no HTTP).
- ``TestWireFormat`` — end-to-end capture via ``httpx.MockTransport``:
  POSTs are intercepted, the outbound URL/headers/body are dumped and
  compared against pi-ai's ``openai-codex-responses`` reference shape.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from unittest.mock import patch

from src.agents.base import LLMFactory
from src.agents.providers.openai_codex import (
    build_chatgpt_backed_chat_openai,
    extract_chatgpt_account_id,
)
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from tests.agents.retry_options import SDKRetryOptions


def _build_jwt(*, claims: dict[str, Any]) -> str:
    """Build a fake JWT carrying ``claims`` in the payload segment.

    The signature is irrelevant for our decoder; we only parse the
    payload. Headers and signature are dummy bytes so the structure is
    still ``header.payload.signature``.

    Args:
        claims (dict[str, Any]): The payload to embed.

    Returns:
        str: A three-segment JWT-shaped string with the given payload.
    """
    header_b64: str = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode("ascii")
    payload_b64: str = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode("ascii")
    )
    return f"{header_b64}.{payload_b64}.signature"


def _oauth_cred(*, access_token: str) -> CredentialDAO:
    """Build an OAuth credential carrying ``access_token``."""
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token=access_token,
        refresh_token="rt-test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="openid profile email offline_access",
    )


def _enabled_reasoning(
    *,
    requested_level: str = "high",
    active_level: str = "high",
    effort: str = "high",
) -> ResolvedReasoningConfigDAO:
    """Build an enabled resolved OpenAI reasoning config.

    Args:
        requested_level (str, optional): Canonical requested reasoning level.
            Defaults to ``"high"``.
        active_level (str, optional): Canonical active reasoning level after clamping.
            Defaults to ``"high"``.
        effort (str, optional): Provider-native effort string. Defaults to ``"high"``.

    Returns:
        ResolvedReasoningConfigDAO: Enabled resolved config for builder tests.
    """
    return ResolvedReasoningConfigDAO(
        enabled=True,
        requested_level=requested_level,  # type: ignore[arg-type]
        active_level=active_level,  # type: ignore[arg-type]
        provider_effort=effort,
        provider_summary_mode="auto",
    )


class TestExtractChatgptAccountId:
    """``extract_chatgpt_account_id`` — JWT decode + claim extraction."""

    def test_decodes_jwt_and_returns_chatgpt_account_id(self) -> None:
        """Well-formed JWT with the claim → the account id is returned."""
        token: str = _build_jwt(
            claims={
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "d1e42ebe-1818-450e-aa84-7b72835887a1",
                    "chatgpt_plan_type": "business",
                },
            },
        )

        result: str = extract_chatgpt_account_id(access_token=token)

        assert result == "d1e42ebe-1818-450e-aa84-7b72835887a1"

    def test_rejects_non_jwt_token_with_wrong_segment_count(self) -> None:
        """A non-three-segment string raises ``ValueError`` with a useful message."""
        with pytest.raises(ValueError, match="not a JWT"):
            extract_chatgpt_account_id(access_token="sk-not-a-jwt")

    def test_rejects_three_segment_string_that_is_not_valid_base64_json(
        self,
    ) -> None:
        """Three segments but the payload is not valid JSON → ``ValueError``."""
        with pytest.raises(ValueError, match="did not decode"):
            extract_chatgpt_account_id(
                access_token="aaaa.not_valid_b64_json.bbbb",
            )

    def test_rejects_token_without_required_claim(self) -> None:
        """JWT without ``chatgpt_account_id`` → ``ValueError``."""
        token: str = _build_jwt(
            claims={"https://api.openai.com/auth": {"chatgpt_plan_type": "business"}},
        )

        with pytest.raises(ValueError, match="chatgpt_account_id"):
            extract_chatgpt_account_id(access_token=token)

    def test_rejects_token_without_auth_claim_namespace(self) -> None:
        """JWT without the ``https://api.openai.com/auth`` envelope → ``ValueError``."""
        token: str = _build_jwt(claims={"sub": "user-123"})

        with pytest.raises(ValueError, match="chatgpt_account_id"):
            extract_chatgpt_account_id(access_token=token)

    def test_handles_payload_segment_with_stripped_base64_padding(self) -> None:
        """JWTs strip base64 padding; the decoder re-pads before decoding."""
        # _build_jwt already strips padding so this is implicitly
        # exercised, but assert the round-trip on a payload whose base64
        # length forces 2 chars of padding to make the property explicit.
        token: str = _build_jwt(
            claims={
                "https://api.openai.com/auth": {"chatgpt_account_id": "ab"},
            },
        )
        payload_segment: str = token.split(".")[1]
        # Force the property under test: the payload must require
        # padding to decode cleanly.
        assert len(payload_segment) % 4 != 0

        result: str = extract_chatgpt_account_id(access_token=token)

        assert result == "ab"


class TestBuildChatgptBackedChatOpenAI:
    """``build_chatgpt_backed_chat_openai`` — constructor-level config."""

    def test_sets_chatgpt_backend_base_url(self) -> None:
        """The constructed model is pointed at ``chatgpt.com/backend-api/codex``."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="sess-1",
        )

        assert chat.openai_api_base == "https://chatgpt.com/backend-api/codex"

    def test_sets_required_default_headers(self) -> None:
        """Every identity header pi-ai sends is present with the right value."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-9"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="sess-9",
        )

        assert chat.default_headers == {
            "chatgpt-account-id": "acct-9",
            "originator": "slo",
            "OpenAI-Beta": "responses=experimental",
            "session-id": "sess-9",
            "x-client-request-id": "sess-9",
        }

    @pytest.mark.parametrize("retry_options", [{}, {"max_retries": 0}, {"max_retries": 5}])
    def test_enables_responses_api_and_disables_store(self, retry_options: SDKRetryOptions) -> None:
        """``use_responses_api=True``, ``store=False``, reasoning include set."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="s",
            **retry_options,
        )

        assert chat.use_responses_api is True
        assert chat.output_version == "responses/v1"
        assert chat.store is False
        assert chat.include == ["reasoning.encrypted_content"]
        assert chat.max_retries == retry_options.get("max_retries", 3)
        assert chat.root_async_client.max_retries == retry_options.get("max_retries", 3)

    def test_threads_prompt_cache_key_through_extra_body(self) -> None:
        """``extra_body["prompt_cache_key"]`` is the session id."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="cache-key-1",
        )

        assert chat.extra_body == {"prompt_cache_key": "cache-key-1"}

    def test_sets_reasoning_payload_when_enabled(self) -> None:
        """Enabled resolved reasoning config becomes a Responses ``reasoning`` payload."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="reasoning-enabled",
            reasoning=_enabled_reasoning(
                requested_level="xhigh",
                active_level="xhigh",
                effort="xhigh",
            ),
        )

        assert chat.reasoning == {"effort": "xhigh", "summary": "auto"}

    def test_omits_reasoning_payload_when_disabled(self) -> None:
        """Disabled reasoning config leaves the Responses ``reasoning`` payload unset."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )
        disabled_reasoning: ResolvedReasoningConfigDAO = ResolvedReasoningConfigDAO(
            enabled=False,
            requested_level="off",
            active_level="off",
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=cred,
            session_id="reasoning-disabled",
            reasoning=disabled_reasoning,
        )

        assert chat.reasoning is None

    def test_forwards_copied_sanitized_model_kwargs(self) -> None:
        """Supplied sanitized extras reach ``ChatOpenAI`` as a fresh copy."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )
        caller_kwargs: dict[str, Any] = {"parallel_tool_calls": True}

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-6-astra",
            cred=cred,
            session_id="s-extras",
            model_kwargs=caller_kwargs,
        )

        assert chat.model_kwargs == {"parallel_tool_calls": True}
        caller_kwargs["parallel_tool_calls"] = False
        assert chat.model_kwargs == {"parallel_tool_calls": True}

    def test_omitted_model_kwargs_defaults_to_empty_mapping(self) -> None:
        """No extras → an empty model-kwargs mapping on the chat model."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "x"},
                },
            ),
        )

        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-6-astra",
            cred=cred,
            session_id="s-default",
        )

        assert chat.model_kwargs == {}


@tool
def _probe_read(path: str) -> str:
    """Stub tool used by the wire-format capture."""
    return ""


def _captured_via_mock_transport(
    *,
    cred: CredentialDAO,
    session_id: str,
    messages: list,
    reasoning: ResolvedReasoningConfigDAO | None = None,
    model_kwargs: dict[str, Any] | None = None,
    model_name: str = "gpt-5",
) -> dict[str, Any]:
    """Run one ``ainvoke`` against a ``MockTransport`` and return the captured request.

    Args:
        cred (CredentialDAO): OAuth credential to wire through the
            builder.
        session_id (str): Session id to thread into the headers.
        messages (list): LangChain message history to send.
        reasoning (ResolvedReasoningConfigDAO | None): Optional resolved
            reasoning config forwarded to the builder.
        model_kwargs (dict[str, Any] | None): Optional sanitized extras
            forwarded to the builder.
        model_name (str): Provider-facing model ID used in the captured request.

    Returns:
        dict[str, Any]: ``{"method", "url", "headers", "body"}``.
    """
    captured: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        """Capture the outbound request and return a minimal SSE 200."""
        body_bytes: bytes = request.content if request.content else b""
        try:
            body_json: Any = json.loads(body_bytes.decode())
        except Exception:  # noqa: BLE001
            body_json = body_bytes.decode(errors="replace")
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = body_json
        sse: bytes = (
            b"event: response.created\n"
            b'data: {"type": "response.created", "response": {"id": "resp_test", "status": "in_progress"}}\n\n'
            b"event: response.completed\n"
            b'data: {"type": "response.completed", "response": {"id": "resp_test", "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}]}}\n\n'
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=sse,
        )

    mock_client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
    )
    chat = build_chatgpt_backed_chat_openai(
        model_name=model_name,
        cred=cred,
        session_id=session_id,
        reasoning=reasoning,
        model_kwargs=model_kwargs,
        http_async_client=mock_client,
    )
    chat_with_tools = chat.bind_tools(tools=[_probe_read])

    import asyncio

    async def _run() -> None:
        """Drain ``ainvoke`` for its capture side-effects."""
        try:
            await chat_with_tools.ainvoke(messages)
        except Exception:  # noqa: BLE001
            # The minimal SSE may not produce a valid LangChain response;
            # we only care about the request capture.
            pass

    asyncio.run(_run())
    return captured


class TestWireFormat:
    """End-to-end byte-level wire capture against ``httpx.MockTransport``."""

    def test_request_targets_codex_responses_url(self) -> None:
        """URL is ``https://chatgpt.com/backend-api/codex/responses``."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-w",
            messages=[HumanMessage(content="hi")],
        )

        assert captured["method"] == "POST"
        assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"

    def test_request_carries_required_identity_headers(self) -> None:
        """All six identity headers are present with the right values."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="sess-headers",
            messages=[HumanMessage(content="hi")],
        )

        headers: dict[str, str] = captured["headers"]
        assert headers["authorization"].startswith("Bearer ")
        assert headers["chatgpt-account-id"] == "acct-w"
        assert headers["originator"] == "slo"
        assert headers["openai-beta"] == "responses=experimental"
        assert headers["session-id"] == "sess-headers"
        assert headers["x-client-request-id"] == "sess-headers"

    def test_body_uses_responses_api_input_shape(self) -> None:
        """Body has ``input[]`` (not ``messages[]``); ``store=false``; ``stream=true``."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-body",
            messages=[
                SystemMessage(content="You are helpful."),
                HumanMessage(content="hi"),
            ],
        )

        body: dict[str, Any] = captured["body"]
        assert "input" in body
        assert "messages" not in body
        assert body["store"] is False
        assert body["stream"] is True
        assert body["include"] == ["reasoning.encrypted_content"]

    def test_body_round_trips_tool_call_and_tool_result(self) -> None:
        """Tool-call history renders as ``function_call`` + ``function_call_output``."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-tool",
            messages=[
                SystemMessage(content="You are helpful."),
                HumanMessage(content="read foo.py"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "_probe_read",
                            "args": {"path": "foo.py"},
                            "id": "call_abc",
                            "type": "tool_call",
                        }
                    ],
                ),
                ToolMessage(
                    content="line1\nline2",
                    tool_call_id="call_abc",
                    name="_probe_read",
                ),
                HumanMessage(content="what's in it?"),
            ],
        )

        input_items: list[dict[str, Any]] = captured["body"]["input"]
        types_in_order: list[str] = [item.get("type", item.get("role", "?")) for item in input_items]
        assert "function_call" in types_in_order
        assert "function_call_output" in types_in_order
        # The call_id round-trips through both sides of the pair.
        call_items = [i for i in input_items if i.get("type") == "function_call"]
        output_items = [i for i in input_items if i.get("type") == "function_call_output"]
        assert call_items[0]["call_id"] == "call_abc"
        assert output_items[0]["call_id"] == "call_abc"

    def test_body_includes_reasoning_payload_when_enabled(self) -> None:
        """Enabled reasoning config reaches the outbound Responses request body."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-reasoning",
            messages=[HumanMessage(content="hi")],
            reasoning=_enabled_reasoning(effort="high"),
        )

        body: dict[str, Any] = captured["body"]
        assert body["reasoning"] == {"effort": "high", "summary": "auto"}

    def test_body_renders_tools_in_flat_function_shape(self) -> None:
        """Bound tools become ``{type, name, parameters, description}`` items."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-tools",
            messages=[HumanMessage(content="hi")],
        )

        tools_payload: list[dict[str, Any]] = captured["body"]["tools"]
        assert tools_payload[0]["type"] == "function"
        assert tools_payload[0]["name"] == "_probe_read"
        assert "parameters" in tools_payload[0]
        # Chat-Completions nesting MUST NOT be present.
        assert "function" not in tools_payload[0]


class TestSanitizedExtrasWireFormat:
    """Feature 83.b.1: sanitized extras reach the Responses wire unchanged."""

    def test_oauth_codex_astra_bound_tool_request_uses_responses_without_sampling_fields(self) -> None:
        """OAuth/Codex builder capture proves its own Responses wire contract."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-astra-oauth-codex-contract",
            messages=[HumanMessage(content="list files")],
            reasoning=_enabled_reasoning(requested_level="off", active_level="off", effort="low"),
            model_kwargs={"parallel_tool_calls": True},
            model_name="gpt-6-astra",
        )

        body: dict[str, Any] = captured["body"]
        assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
        assert body["model"] == "gpt-6-astra"
        assert body["stream"] is True
        assert body["reasoning"] == {"effort": "low", "summary": "auto"}
        assert body["parallel_tool_calls"] is True
        assert "input" in body
        assert body["tools"][0]["type"] == "function"
        assert body["tools"][0]["name"] == "_probe_read"
        assert "parameters" in body["tools"][0]
        assert "function" not in body["tools"][0]
        for forbidden_key in ("temperature", "top_p", "top_logprobs", "logprobs"):
            assert forbidden_key not in body

    def test_api_key_astra_factory_bound_tool_streams_platform_responses_without_sampling_fields(self) -> None:
        """Factory API-key Astra streams a local Platform Responses request, never Codex."""
        captured: dict[str, Any] = {}

        async def _handler(request: httpx.Request) -> httpx.Response:
            """Capture the Platform request and return a minimal Responses SSE stream."""
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=(
                    b"event: response.created\n"
                    b'data: {"type": "response.created", "response": {"id": "resp_test", "status": "in_progress"}}\n\n'
                    b"event: response.completed\n"
                    b'data: {"type": "response.completed", "response": {"id": "resp_test", "status": "completed", "output": []}}\n\n'
                ),
            )

        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="sk-platform-test",
        )
        mock_client: httpx.AsyncClient = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            product = LLMFactory.create(
                model_name="gpt-6-astra",
                reasoning_level="off",
                model_kwargs={
                    "parallel_tool_calls": True,
                    "top_p": 0.5,
                    "top_logprobs": 3,
                    "logprobs": True,
                },
                http_async_client=mock_client,
            )

        assert isinstance(product.llm, ChatOpenAI)
        chat_with_tools = product.llm.bind_tools(tools=[_probe_read])

        import asyncio

        async def _stream_request() -> None:
            """Drain the bound factory model stream to force its HTTP request."""
            try:
                async for _ in chat_with_tools.astream(input=[HumanMessage(content="list files")]):
                    pass
            except Exception:  # noqa: BLE001
                # A minimal synthetic SSE response need only reach the wire-capture seam.
                pass

        asyncio.run(_stream_request())

        body: dict[str, Any] = captured["body"]
        assert captured["method"] == "POST"
        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert "/backend-api/codex/" not in captured["url"]
        assert body["model"] == "gpt-6-astra"
        assert body["stream"] is True
        assert body["reasoning"] == {"effort": "low", "summary": "auto"}
        assert body["parallel_tool_calls"] is True
        assert "input" in body
        assert body["tools"][0]["type"] == "function"
        assert body["tools"][0]["name"] == "_probe_read"
        assert "parameters" in body["tools"][0]
        assert "function" not in body["tools"][0]
        for forbidden_key in ("temperature", "top_p", "top_logprobs", "logprobs"):
            assert forbidden_key not in body

    def test_sanitized_extras_present_and_no_forbidden_sampling_fields(self) -> None:
        """A sanitized caller mapping appears on the body; forbidden keys never do."""
        cred: CredentialDAO = _oauth_cred(
            access_token=_build_jwt(
                claims={
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-w"},
                },
            ),
        )

        captured = _captured_via_mock_transport(
            cred=cred,
            session_id="s-sanitized",
            messages=[HumanMessage(content="hi")],
            reasoning=_enabled_reasoning(effort="low"),
            model_kwargs={"parallel_tool_calls": True},
        )

        body: dict[str, Any] = captured["body"]
        assert body["parallel_tool_calls"] is True
        for forbidden_key in ("temperature", "top_p", "top_logprobs", "logprobs"):
            assert forbidden_key not in body
        assert body["reasoning"] == {"effort": "low", "summary": "auto"}
        assert body["store"] is False
        assert body["stream"] is True
