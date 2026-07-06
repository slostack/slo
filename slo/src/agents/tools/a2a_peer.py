"""A2A peer tool — exposes a remote A2A agent to the LLM as a LangChain tool (sub-spec 01.i).

`a2a_peer_tool(peer_url=...)` is an async factory that fetches the peer's
``AgentCard`` (via ``A2ACardResolver``), picks the first declared skill, and
returns a ``StructuredTool`` whose ``coroutine`` issues a JSON-RPC
``message/send`` against the peer and returns the artifact's ``response`` text.

Logic lives in ``A2APeerTool`` (the class); the module exposes thin
``a2a_peer_tool`` and ``fetch_agent_card`` bridges as the public surface so
tests and callers don't reach into private classmethods.
"""
from __future__ import annotations

A2A_PEER_PROMPT_SNIPPET: str = (
    "delegate a query to a remote A2A peer agent"
)

import re
from typing import Any, Optional
from uuid import uuid4

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    DataPart,
    JSONRPCErrorResponse,
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task,
)

from config.cfg import A2A_FETCH_TIMEOUT_SECONDS, A2A_INVOKE_TIMEOUT_SECONDS
from config.logger import log_error, log_info


__all__ = [
    "A2APeerSchemaDAO",
    "A2APeerTool",
    "a2a_peer_tool",
    "fetch_agent_card",
]


_DEFAULT_FETCH_TIMEOUT_S: float = A2A_FETCH_TIMEOUT_SECONDS
_DEFAULT_INVOKE_TIMEOUT_S: float = A2A_INVOKE_TIMEOUT_SECONDS


class A2APeerSchemaDAO(BaseModel):
    """LangChain args schema for the A2A peer tool.

    v1 contract: every A2A peer accepts a single ``query`` field. Multi-field
    peers would need v1.1's ``skill_id``-aware schema synthesis.
    """

    query: str = Field(description="The prompt to send to the peer agent.")

    model_config = ConfigDict(
        title="A2APeerSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class A2APeerTool:
    """Build a LangChain ``StructuredTool`` that delegates to an A2A peer agent.

    The factory ``invoke`` fetches the peer's AgentCard, picks the first
    declared skill, and returns a ``StructuredTool`` whose async ``coroutine``
    sends a JSON-RPC ``message/send`` request and returns the artifact's
    ``response`` field.
    """

    @classmethod
    async def invoke(
        cls,
        *,
        peer_url: str,
        fetch_timeout: float = _DEFAULT_FETCH_TIMEOUT_S,
        invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT_S,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> StructuredTool:
        """Build a LangChain tool wired to ``peer_url``.

        Args:
            peer_url: Base URL of the peer; the agent card is fetched from
                ``<peer_url>/.well-known/agent.json``.
            fetch_timeout: Seconds allowed for the initial card fetch.
            invoke_timeout: Seconds allowed for each peer invocation.
            extra_headers: Optional headers forwarded on the peer requests
                (e.g. for bearer-token auth).

        Returns:
            A ``StructuredTool`` ready to add to a ``SloAgent``'s tool list.

        Raises:
            ValueError: If the peer's AgentCard declares zero skills.
            httpx.HTTPError: If the AgentCard fetch fails.
        """
        card: AgentCard = await cls._fetch_agent_card(
            peer_url=peer_url,
            timeout=fetch_timeout,
            extra_headers=extra_headers,
        )
        if not card.skills:
            raise ValueError(f"A2A peer at {peer_url} has no skills declared.")

        skill = card.skills[0]
        tool_name = cls._sanitise_tool_name(raw=skill.id or card.name or "a2a_peer")
        description = (
            f"[A2A peer at {peer_url}] {skill.description or skill.name or ''}"
        ).strip()

        async def _peer_invoke(query: str) -> str:
            return await cls._send_peer_request(
                peer_url=peer_url,
                query=query,
                invoke_timeout=invoke_timeout,
                extra_headers=extra_headers,
            )

        return StructuredTool.from_function(
            coroutine=_peer_invoke,
            name=tool_name,
            description=description,
            args_schema=A2APeerSchemaDAO,
        )

    @classmethod
    async def _fetch_agent_card(
        cls,
        *,
        peer_url: str,
        timeout: float,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> AgentCard:
        """Fetch ``<peer_url>/.well-known/agent.json`` via ``A2ACardResolver``."""
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=dict(extra_headers or {}),
        ) as http:
            resolver = A2ACardResolver(httpx_client=http, base_url=peer_url)
            return await resolver.get_agent_card()

    @classmethod
    def _sanitise_tool_name(cls, *, raw: str) -> str:
        """Convert a skill id (e.g. ``"slo.react"``) into a valid LangChain tool name.

        LangChain tool names must match ``[A-Za-z_][A-Za-z0-9_]*``. Punctuation
        becomes underscores; a leading digit gets a ``peer_`` prefix.
        """
        sanitised = re.sub(r"[^A-Za-z0-9_]", "_", raw)
        if not sanitised or not (sanitised[0].isalpha() or sanitised[0] == "_"):
            sanitised = "peer_" + sanitised
        return sanitised

    @classmethod
    async def _send_peer_request(
        cls,
        *,
        peer_url: str,
        query: str,
        invoke_timeout: float,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> str:
        """Send a single ``message/send`` JSON-RPC request and decode the response."""
        try:
            async with httpx.AsyncClient(
                timeout=invoke_timeout,
                headers=dict(extra_headers or {}),
            ) as http:
                client = A2AClient(httpx_client=http, url=peer_url)
                request = SendMessageRequest(
                    id=str(uuid4()),
                    params=MessageSendParams(
                        message=Message(
                            role=Role.user,
                            parts=[Part(root=DataPart(data={"query": query}))],
                            message_id=str(uuid4()),
                        ),
                    ),
                )
                response: SendMessageResponse = await client.send_message(request=request)
                return cls._extract_response(result=response)
        except Exception as exc:  # noqa: BLE001 — bubble up as a tool string error
            log_error(msg=f"A2APeerTool: peer call failed: {exc}", e=exc, stack_trace=False)
            return f"Error: A2A peer call failed: {exc}"

    @classmethod
    def _extract_response(cls, *, result: SendMessageResponse) -> str:
        """Pull the peer's ``response`` text out of the JSON-RPC response.

        Handles three shapes:
            - JSON-RPC error envelope     -> ``"Error: A2A JSON-RPC error: ..."``
            - ``Task`` result with a structured-error artifact (``error_code``)
              -> ``"Error from peer: <code>: <message>"``
            - ``Task`` result with a normal response artifact
              -> the ``data["response"]`` text

        Args:
            result: The full ``SendMessageResponse`` returned by ``A2AClient``.

        Returns:
            A single string suitable for the LLM to see as the tool output.
        """
        root = result.root
        if isinstance(root, JSONRPCErrorResponse):
            return f"Error: A2A JSON-RPC error: {root.error.message}"

        success_result: Any = root.result
        if not isinstance(success_result, Task):
            return "(peer returned a Message rather than a Task — v1 expects Task artifacts)"

        artifacts = success_result.artifacts or []
        if not artifacts:
            return "(peer returned no artifacts)"

        last = artifacts[-1]
        parts = last.parts or []
        if not parts:
            return "(peer's final artifact had no parts)"

        part_root = parts[0].root
        if not isinstance(part_root, DataPart):
            return "(peer's final artifact part was not a DataPart)"

        data = part_root.data or {}
        if "error_code" in data:
            return f"Error from peer: {data.get('error_code')}: {data.get('message', '')}"
        return data.get("response") or "(peer returned an empty response)"


async def a2a_peer_tool(
    peer_url: str,
    fetch_timeout: float = _DEFAULT_FETCH_TIMEOUT_S,
    invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT_S,
    extra_headers: Optional[dict[str, str]] = None,
) -> StructuredTool:
    """Thin module-level bridge over ``A2APeerTool.invoke``.

    Build a LangChain tool that delegates work to an A2A peer agent.

    Args:
        peer_url: Base URL of the peer.
        fetch_timeout: Seconds allowed for the initial AgentCard fetch.
        invoke_timeout: Seconds allowed for each peer invocation.
        extra_headers: Optional auth / tracing headers forwarded to the peer.

    Returns:
        A ``StructuredTool`` ready to add to a ``SloAgent``'s tool list.
    """
    log_info(msg=f"Building A2A peer tool for {peer_url}")
    return await A2APeerTool.invoke(
        peer_url=peer_url,
        fetch_timeout=fetch_timeout,
        invoke_timeout=invoke_timeout,
        extra_headers=extra_headers,
    )


async def fetch_agent_card(
    peer_url: str,
    timeout: float = _DEFAULT_FETCH_TIMEOUT_S,
    extra_headers: Optional[dict[str, str]] = None,
) -> AgentCard:
    """Thin module-level bridge over ``A2APeerTool._fetch_agent_card``.

    Args:
        peer_url: Base URL of the peer.
        timeout: Seconds allowed for the fetch.
        extra_headers: Optional auth headers.

    Returns:
        The parsed ``AgentCard``.
    """
    return await A2APeerTool._fetch_agent_card(
        peer_url=peer_url,
        timeout=timeout,
        extra_headers=extra_headers,
    )


if __name__ == "__main__":
    # Smoke-test runner: exercises the pure helpers without touching the network.
    print("---[ scenario 1: sanitise 'stub.echo' ]---")
    print(A2APeerTool._sanitise_tool_name(raw="stub.echo"))

    print("\n---[ scenario 2: sanitise leading-digit '9foo' ]---")
    print(A2APeerTool._sanitise_tool_name(raw="9foo"))

    print("\n---[ scenario 3: extract_response on a stub error artifact ]---")
    from a2a.types import (
        Artifact,
        SendMessageSuccessResponse,
        TaskState,
        TaskStatus,
    )

    err_response = SendMessageResponse(
        root=SendMessageSuccessResponse(
            id="rpc-1",
            result=Task(
                id="t-1",
                context_id="c-1",
                status=TaskStatus(state=TaskState.completed),
                artifacts=[
                    Artifact(
                        artifact_id="a-1",
                        parts=[Part(root=DataPart(data={"error_code": "execution_error", "message": "boom"}))],
                    )
                ],
            ),
        )
    )
    print(A2APeerTool._extract_response(result=err_response))
