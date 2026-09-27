"""OpenAI ChatGPT-subscription Responses lane (feature 07).

Wires ``langchain_openai.ChatOpenAI`` against the ChatGPT backend by
overriding ``openai_api_base`` and supplying the identity headers
ChatGPT requires (``chatgpt-account-id``, ``originator``,
``OpenAI-Beta``, ``session-id``, ``x-client-request-id``) plus the
Responses-API body shape switches (``use_responses_api=True``,
``output_version="responses/v1"``, ``store=False``, ``include=[...]``).

The pair of public surfaces is intentionally tiny:

- ``extract_chatgpt_account_id`` — decode the OAuth JWT and pull the
  ``chatgpt_account_id`` claim out of it. Required for the
  ``chatgpt-account-id`` header that routes the request to the ChatGPT
  subscription quota lane.
- ``build_chatgpt_backed_chat_openai`` — assemble a ready-to-bind
  ``ChatOpenAI`` configured for that lane. The LangChain agent loop
  does not need to know which lane it is on.

Background: ChatGPT-subscription OAuth tokens carry zero quota on
``api.openai.com``; they bill against the user's ChatGPT plan via the
``chatgpt.com/backend-api`` lane. See ``docs/RESEARCH.md`` "Two OpenAI lanes"
and the parent spec at
``specifications/07-slo-openai-codex-responses-provider/``.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import CredentialDAO

__all__ = [
    "build_chatgpt_backed_chat_openai",
    "extract_chatgpt_account_id",
    "openai_reasoning_payload",
]


_CHATGPT_BACKEND_BASE_URL: str = "https://chatgpt.com/backend-api/codex"
"""Base URL for the ChatGPT backend Responses API.

``openai-python`` POSTs to ``{base_url}/responses`` for Responses-mode
calls, so this resolves to
``https://chatgpt.com/backend-api/codex/responses`` — byte-for-byte the
URL pi-ai's ``openai-codex-responses`` provider uses.
"""

_JWT_AUTH_CLAIM_PATH: str = "https://api.openai.com/auth"
"""Top-level claim key inside the OAuth JWT payload.

OpenAI namespaces the ChatGPT-account claims under a URL-shaped key so
they cannot collide with first-class OIDC claims. The value at this
key is a nested object that includes ``chatgpt_account_id`` and
``chatgpt_plan_type``.
"""

_ORIGINATOR: str = "slo"
"""Client identifier sent in the ``originator`` header.

OpenAI uses this for support-side request attribution. pi-ai sends
``pi``; we send ``slo``. The value is opaque to quota routing.
"""


def extract_chatgpt_account_id(*, access_token: str) -> str:
    """Decode the OAuth JWT payload and return the ``chatgpt_account_id`` claim.

    Args:
        access_token (str): The Codex OAuth JWT.

    Returns:
        str: The ChatGPT account id claim required for the
            ``chatgpt-account-id`` header.

    Raises:
        ValueError: When the token is not a JWT, the payload does not
            decode, or the expected claim is missing.
    """
    parts: list[str] = access_token.split(".")
    if len(parts) != 3:
        raise ValueError("OpenAI OAuth access token is not a JWT.")
    padded: str = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        # ``Any`` is required because JWT payloads are untyped JSON.
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("OpenAI OAuth JWT payload did not decode.") from exc
    claim: Optional[dict[str, Any]] = payload.get(_JWT_AUTH_CLAIM_PATH)
    account_id: Optional[str] = (claim or {}).get("chatgpt_account_id")
    if not account_id:
        raise ValueError("OpenAI OAuth JWT does not carry the chatgpt_account_id claim.")
    return account_id


def openai_reasoning_payload(
    *,
    reasoning: Optional[ResolvedReasoningConfigDAO],
) -> Optional[dict[str, str]]:
    """Build the OpenAI Responses ``reasoning`` payload from resolved config.

    Args:
        reasoning (Optional[ResolvedReasoningConfigDAO]): Resolved
            reasoning config for the active model.

    Returns:
        Optional[dict[str, str]]: OpenAI ``reasoning`` payload, or
            ``None`` when reasoning is disabled.

    Raises:
        ValueError: If reasoning is enabled but no provider effort is
            available.
    """
    if reasoning is None or not reasoning.enabled:
        return None
    if reasoning.provider_effort is None:
        raise ValueError("Resolved OpenAI reasoning config is missing provider_effort.")
    payload: dict[str, str] = {"effort": reasoning.provider_effort}
    if reasoning.provider_summary_mode is not None:
        payload["summary"] = reasoning.provider_summary_mode
    return payload


def build_chatgpt_backed_chat_openai(
    *,
    model_name: str,
    cred: CredentialDAO,
    session_id: str,
    temperature: Optional[float] = None,
    reasoning: Optional[ResolvedReasoningConfigDAO] = None,
    model_kwargs: Optional[dict[str, Any]] = None,
    streaming: bool = True,
    http_async_client: Optional[Any] = None,
) -> ChatOpenAI:
    """Build a ``ChatOpenAI`` that targets ``chatgpt.com/backend-api/codex/responses``.

    The returned chat model is byte-compatible with pi-ai's
    ``openai-codex-responses`` request shape (Responses API body,
    ``store: false``, ``include: ["reasoning.encrypted_content"]``, flat
    ``function`` tool encoding, ``function_call`` / ``function_call_output``
    input items) so the same JWT bills against the user's ChatGPT
    subscription quota.

    Args:
        model_name (str): The OpenAI model identifier (e.g. ``gpt-5``).
        cred (CredentialDAO): The persisted OAuth credential. Its
            ``access_token`` is decoded once to extract the
            ``chatgpt-account-id`` header.
        session_id (str): Active ``SloAgentSession.session_id``,
            threaded into the ``session-id`` and ``x-client-request-id``
            headers so backend prompt caching is attributable.
        temperature (Optional[float]): Forwarded to ``ChatOpenAI``.
        reasoning (Optional[ResolvedReasoningConfigDAO]): Resolved
            provider-ready reasoning config.
        model_kwargs (Optional[dict[str, Any]]): Optional caller-supplied
            extra request kwargs. Copied before forwarding; the builder never
            mutates the caller's mapping and never decides which values are
            forbidden (that policy lives in the factory).
        streaming (bool): Streaming flag. Defaults to ``True`` so the
            ReAct loop sees deltas as they arrive.
        http_async_client (Optional[Any]): Optional pre-built
            ``httpx.AsyncClient``. Wired through to the underlying
            ``openai-python`` client so tests can inject a
            ``MockTransport`` and capture the outbound request. ``None``
            lets ``ChatOpenAI`` build its own client in production.

    Returns:
        ChatOpenAI: A ready-to-bind chat model configured for the
            ChatGPT-backend Responses lane.
    """
    account_id: str = extract_chatgpt_account_id(access_token=cred.access_token)
    return ChatOpenAI(
        model=model_name,
        api_key=cred.access_token,
        openai_api_base=_CHATGPT_BACKEND_BASE_URL,
        default_headers={
            "chatgpt-account-id": account_id,
            "originator": _ORIGINATOR,
            "OpenAI-Beta": "responses=experimental",
            "session-id": session_id,
            "x-client-request-id": session_id,
        },
        use_responses_api=True,
        output_version="responses/v1",
        store=False,
        include=["reasoning.encrypted_content"],
        reasoning=openai_reasoning_payload(reasoning=reasoning),
        temperature=temperature,
        model_kwargs=dict(model_kwargs or {}),
        streaming=streaming,
        # ``ChatOpenAI`` would otherwise transparently retry 429s a few
        # times before surfacing them. For the ChatGPT lane we want
        # quota errors to reach the TUI immediately so the user sees a
        # plan-limit message instead of a stuck spinner.
        max_retries=0,
        extra_body={"prompt_cache_key": session_id},
        http_async_client=http_async_client,
    )
