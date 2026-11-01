"""Exact offline Codex constructor wire and SDK retry contract."""

import json

import httpx
import pytest
from openai import RateLimitError

from src.agents.providers.openai_codex import build_chatgpt_backed_chat_openai
from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
from tests.agents.retry_options import SDKRetryOptions


@pytest.mark.parametrize("retry_options", [{}, {"max_retries": 0}])
async def test_codex_exact_wire_and_configured_retries(retry_options: SDKRetryOptions) -> None:
    """Rejected Responses requests honor SDK retries and retain wire semantics."""
    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "offline-account"}})
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        """Capture locally and reject without any network connection."""
        requests.append(request)
        return httpx.Response(
            status_code=429, json={"error": {"message": "offline limit", "type": "rate_limit_error"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=_oauth_cred(access_token=token),
            session_id="offline-session",
            streaming=False,
            http_async_client=client,
            **retry_options,
        )
        with pytest.raises(RateLimitError):
            await chat.ainvoke("hello")
    assert len(requests) == retry_options.get("max_retries", 3) + 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
    assert request.headers["authorization"] == f"Bearer {token}"
    for key, value in {
        "chatgpt-account-id": "offline-account",
        "originator": "slo",
        "openai-beta": "responses=experimental",
        "session-id": "offline-session",
        "x-client-request-id": "offline-session",
    }.items():
        assert request.headers[key] == value
    assert json.loads(request.content) == {
        "model": "gpt-5",
        "input": [{"role": "user", "content": "hello"}],
        "stream": False,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": "offline-session",
    }
