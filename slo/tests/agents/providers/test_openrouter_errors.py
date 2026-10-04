"""OpenRouter error classification and no-raw-error regression tests."""

from __future__ import annotations

from src.agents.providers.credit_exhaustion_policy import ProviderErrorClassifier, ProviderErrorKind
from src.auth.credential_dao import ProviderName
import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO

from src.agents.base import LLMFactory
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import AuthType, CredentialDAO
from src.integrations.openrouter.exceptions import OpenRouterAuthenticationError, OpenRouterAPIError

_OPENROUTER_MODEL_NAME = "openrouter:vendor/exact-model"


def _prepared_snapshot():
    """Build one local prepared exact-route snapshot for transport-only tests."""
    seed = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO

    entry = template.model_copy(
        update={
            "model_name": _OPENROUTER_MODEL_NAME,
            "api_model_name": "vendor/exact-model",
            "provider": ProviderName.OPENROUTER,
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
            ),
        }
    )
    return seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})


def test_classify_when_openrouter_authentication_error_is_terminal() -> None:
    """Classify a safe OpenRouter auth exception without inspecting its string body."""
    error: OpenRouterAuthenticationError = OpenRouterAuthenticationError(status_code=401)

    result: ProviderErrorKind = ProviderErrorClassifier.classify(
        error=error,
        provider=ProviderName.OPENROUTER,
    )

    assert result is ProviderErrorKind.AUTHENTICATION_FAILED


def test_classify_when_openrouter_temporary_budget_has_retry_after_is_rate_limited() -> None:
    """Classify only the documented temporary in-flight budget signal as a rate limit."""
    error: OpenRouterAPIError = OpenRouterAPIError(
        status_code=402,
        limit_source="openrouter_in_flight_budget",
        retry_after_seconds=5,
    )

    result: ProviderErrorKind = ProviderErrorClassifier.classify(
        error=error,
        provider=ProviderName.OPENROUTER,
    )

    assert result is ProviderErrorKind.RATE_LIMITED


def test_openrouter_error_repr_excludes_sentinel_secret() -> None:
    """Ensure the shared error object cannot reveal an upstream key or body marker."""
    error: OpenRouterAuthenticationError = OpenRouterAuthenticationError(status_code=401)

    assert "test-openrouter-secret" not in repr(error)
    assert "test-openrouter-secret" not in str(error)


@pytest.mark.parametrize(
    ("status_code", "body", "expected_error_type"),
    [
        (401, {"error": {"type": "authentication", "message": "test-openrouter-secret"}}, "authentication"),
        (
            503,
            {"error": {"type": "provider_unavailable", "message": "test-openrouter-secret"}},
            "provider_unavailable",
        ),
    ],
)
async def test_local_http_failure_normalizes_sdk_error_without_raw_body(
    status_code: int,
    body: dict[str, object],
    expected_error_type: str,
) -> None:
    """Normalize non-2xx SDK failures before they escape the adapter."""
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )

    def respond(request: httpx.Request) -> httpx.Response:
        """Return one synthetic non-2xx Chat Completions response."""
        return httpx.Response(status_code=status_code, json=body, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, http_async_client=client, snapshot=_prepared_snapshot()
            ).llm
        with pytest.raises(OpenRouterAPIError) as caught:
            _ = [chunk async for chunk in model.astream(input=[HumanMessage(content="hello")])]

    assert caught.value.status_code == status_code
    assert caught.value.error_type == expected_error_type
    assert "test-openrouter-secret" not in str(caught.value)
    assert "test-openrouter-secret" not in repr(caught.value)


@pytest.mark.parametrize(
    "failure_frame",
    [
        {"error": {"type": "invalid_request", "message": "test-openrouter-secret"}},
        {
            "id": "fixture",
            "choices": [
                {"index": 0, "error": {"type": "permission_denied", "message": "test-openrouter-secret"}}
            ],
        },
        {
            "id": "fixture",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": ""},
                    "finish_reason": "error",
                    "error": {"type": "provider_unavailable"},
                }
            ],
        },
    ],
)
async def test_local_sse_error_shapes_normalize_before_first_chunk(
    failure_frame: dict[str, object],
) -> None:
    """Reject HTTP-200 gateway error frames before a normal chunk is returned."""
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )

    def respond(request: httpx.Request) -> httpx.Response:
        """Return one synthetic in-memory SSE failure frame."""
        content: str = f"data: {json.dumps(failure_frame)}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=content,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, http_async_client=client, snapshot=_prepared_snapshot()
            ).llm
        with pytest.raises(OpenRouterAPIError) as caught:
            _ = [chunk async for chunk in model.astream(input=[HumanMessage(content="hello")])]

    assert "test-openrouter-secret" not in str(caught.value)
    assert "test-openrouter-secret" not in repr(caught.value)


@pytest.mark.parametrize(
    "first_frame",
    [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
        {"choices": [{"index": 0, "delta": {"content": "committed"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning": "visible reasoning"}}]},
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_fixture",
                                "type": "function",
                                "function": {"name": "echo", "arguments": "{"},
                            }
                        ]
                    },
                }
            ]
        },
    ],
    ids=["role", "usage", "text", "reasoning", "tool-fragment"],
)
async def test_local_sse_failure_after_committed_chunk_propagates_safe_error(
    first_frame: dict[str, object],
) -> None:
    """Keep each SDK-committed fragment on its lane without replay or direct fallback.

    Args:
        first_frame (dict[str, object]): Local SSE fragment preceding a switchable error.
    """
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )
    text_frame: dict[str, object] = {"id": "fixture", **first_frame}
    requests: list[str] = []
    error_frame: dict[str, object] = {
        "id": "fixture",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "error",
                "error": {"type": "provider_unavailable", "message": "test-openrouter-secret"},
            }
        ],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a text chunk then an in-memory terminal SSE failure."""
        requests.append(str(request.url))
        if request.url.host == "direct.invalid":
            payload = json.loads(request.content)
            assert payload["model"] == "gpt-direct-fixture"
            assert "reasoning" not in payload
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content='data: {"id":"direct","choices":[{"index":0,"delta":{"content":"direct ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
                request=request,
            )
        content: str = (
            f"data: {json.dumps(text_frame)}\n\ndata: {json.dumps(error_frame)}\n\ndata: [DONE]\n\n"
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=content,
            request=request,
        )

    received: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, http_async_client=client, snapshot=_prepared_snapshot()
            ).llm
        direct = ChatOpenAI(
            model="gpt-direct-fixture",
            api_key=SecretStr("synthetic-direct-key"),
            max_retries=0,
            base_url="https://direct.invalid/v1",
            http_async_client=client,
        )
        pool = ModelPool(
            pool_dao=ModelPoolDAO(
                entries=[
                    ModelPoolEntryDAO(
                        model_name=_OPENROUTER_MODEL_NAME, provider=ProviderName.OPENROUTER, priority=0
                    ),
                    ModelPoolEntryDAO(
                        model_name="gpt-direct-fixture", provider=ProviderName.OPENAI, priority=1
                    ),
                ]
            ),
            models={_OPENROUTER_MODEL_NAME: model, "gpt-direct-fixture": direct},
        )
        with pytest.raises(OpenRouterAPIError) as caught:
            async for chunk in pool.astream(input=[HumanMessage(content="hello")]):
                received.append(str(chunk.content))
        assert pool.drain_route_switch_log() == []
        assert pool.active_model_name == _OPENROUTER_MODEL_NAME
        assert requests == ["https://openrouter.ai/api/v1/chat/completions"]
        direct_response = await direct.ainvoke(
            input=[HumanMessage(content="direct compatibility")], stream=True
        )
        assert direct_response.content == "direct ok"

    assert len(received) == 1
    if "committed" in json.dumps(first_frame):
        assert received == ["committed"]
    assert requests == [
        "https://openrouter.ai/api/v1/chat/completions",
        "https://direct.invalid/v1/chat/completions",
    ]
    assert caught.value.status_code is None
    assert caught.value.error_type == "provider_unavailable"
    assert "test-openrouter-secret" not in str(caught.value)
    assert "test-openrouter-secret" not in repr(caught.value)
