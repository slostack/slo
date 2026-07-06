"""Tests for the A2A peer tool (sub-spec 01.i §5.1)."""
from __future__ import annotations

import json
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from a2a.client import A2AClient
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    DataPart,
    JSONRPCError,
    JSONRPCErrorResponse,
    Part,
    SendMessageResponse,
    SendMessageSuccessResponse,
    Task,
    TaskState,
    TaskStatus,
)

from src.agents.tools.a2a_peer import (
    A2APeerSchemaDAO,
    A2APeerTool,
    a2a_peer_tool,
    fetch_agent_card,
)


# --------------------------------------------------------------------------
# Test scaffolding: build a real AgentCard, serialise it, hand it to httpserver
# --------------------------------------------------------------------------


def _agent_card_dict(*, base_url: str, with_skills: bool = True) -> dict[str, Any]:
    """Build a valid AgentCard JSON body for the stub peer.

    Args:
        base_url: The URL the stub peer is reachable at.
        with_skills: When False, returns a card with an empty ``skills`` list
            (used by the no-skills validation test).
    """
    skills = (
        [
            AgentSkill(
                id="stub.echo",
                name="StubEcho",
                description="Returns whatever you send.",
                tags=["test"],
                examples=[],
            )
        ]
        if with_skills
        else []
    )
    card = AgentCard(
        name="StubPeer",
        description="A stub A2A peer for tests.",
        url=base_url,
        version="0.0.1",
        preferred_transport="jsonrpc",
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            state_transition_history=False,
        ),
        skills=skills,
        defaultInputModes=["application/json"],
        defaultOutputModes=["text/plain"],
        supports_authenticated_extended_card=False,
    )
    return json.loads(card.model_dump_json())


def _make_task_response(*, data: dict[str, Any]) -> SendMessageResponse:
    """Wrap a single ``DataPart`` data dict in a full SendMessageResponse envelope."""
    return SendMessageResponse(
        root=SendMessageSuccessResponse(
            id="rpc-id-1",
            result=Task(
                id="t-1",
                context_id="c-1",
                status=TaskStatus(state=TaskState.completed),
                artifacts=[
                    Artifact(artifact_id="a-1", parts=[Part(root=DataPart(data=data))])
                ],
            ),
        )
    )


def _make_jsonrpc_error_response(*, code: int, message: str) -> SendMessageResponse:
    """Wrap a JSON-RPC error envelope as a SendMessageResponse."""
    return SendMessageResponse(
        root=JSONRPCErrorResponse(
            id="rpc-id-1",
            error=JSONRPCError(code=code, message=message),
        )
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


class TestA2APeerTool:
    """Behavioural tests for the ``A2APeerTool`` class + bridges."""

    class TestSanitiseToolName:
        def test_simple_dot(self) -> None:
            assert A2APeerTool._sanitise_tool_name(raw="stub.echo") == "stub_echo"

        def test_leading_digit_gets_prefix(self) -> None:
            assert A2APeerTool._sanitise_tool_name(raw="123abc") == "peer_123abc"

        def test_mixed_punctuation(self) -> None:
            assert A2APeerTool._sanitise_tool_name(raw="foo-bar:baz") == "foo_bar_baz"

    class TestFetchAgentCard:
        @pytest.mark.asyncio
        async def test_round_trip_via_module_bridge(self, httpserver: HTTPServer) -> None:
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )
            card = await fetch_agent_card(peer_url=httpserver.url_for(""))
            assert card.name == "StubPeer"
            assert card.skills[0].id == "stub.echo"

    class TestInvoke:
        @pytest.mark.asyncio
        async def test_construction_sets_name_and_description(
            self, httpserver: HTTPServer
        ) -> None:
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )
            tool = await a2a_peer_tool(peer_url=httpserver.url_for(""))
            assert tool.name == "stub_echo"
            assert "[A2A peer at" in tool.description
            assert "Returns whatever you send" in tool.description
            assert tool.args_schema is A2APeerSchemaDAO

        @pytest.mark.asyncio
        async def test_raises_for_no_skills(self, httpserver: HTTPServer) -> None:
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for(""), with_skills=False),
            )
            with pytest.raises(ValueError, match="no skills"):
                await a2a_peer_tool(peer_url=httpserver.url_for(""))

        @pytest.mark.asyncio
        async def test_invoke_returns_peer_response(
            self,
            httpserver: HTTPServer,
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
            """Happy path: peer returns ``{"response": "..."}`` and the tool surfaces it."""
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )

            async def fake_send_message(self: A2AClient, **kwargs: Any) -> SendMessageResponse:
                return _make_task_response(data={"response": "peer says hi"})

            monkeypatch.setattr(A2AClient, "send_message", fake_send_message)

            tool = await a2a_peer_tool(peer_url=httpserver.url_for(""))
            result = await tool.ainvoke({"query": "hello"})
            assert result == "peer says hi"

        @pytest.mark.asyncio
        async def test_invoke_surfaces_peer_error_code(
            self,
            httpserver: HTTPServer,
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
            """A structured-error artifact (``{error_code, message}``) becomes a clean string."""
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )

            async def fake_send_message(self: A2AClient, **kwargs: Any) -> SendMessageResponse:
                return _make_task_response(
                    data={"error_code": "execution_error", "message": "boom"},
                )

            monkeypatch.setattr(A2AClient, "send_message", fake_send_message)

            tool = await a2a_peer_tool(peer_url=httpserver.url_for(""))
            result = await tool.ainvoke({"query": "do thing"})
            assert "Error from peer" in result
            assert "execution_error" in result
            assert "boom" in result

        @pytest.mark.asyncio
        async def test_invoke_surfaces_transport_failure(
            self,
            httpserver: HTTPServer,
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
            """An exception inside ``send_message`` becomes a clean error string."""
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )

            async def fake_send_message(self: A2AClient, **kwargs: Any) -> SendMessageResponse:
                raise RuntimeError("connection refused")

            monkeypatch.setattr(A2AClient, "send_message", fake_send_message)

            tool = await a2a_peer_tool(peer_url=httpserver.url_for(""))
            result = await tool.ainvoke({"query": "x"})
            assert "Error: A2A peer call failed: connection refused" in result

        @pytest.mark.asyncio
        async def test_invoke_surfaces_jsonrpc_error_envelope(
            self,
            httpserver: HTTPServer,
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
            """A JSON-RPC error envelope (no Task) is surfaced as a string."""
            httpserver.expect_request("/.well-known/agent.json").respond_with_json(
                _agent_card_dict(base_url=httpserver.url_for("")),
            )

            async def fake_send_message(self: A2AClient, **kwargs: Any) -> SendMessageResponse:
                return _make_jsonrpc_error_response(code=-32603, message="internal error")

            monkeypatch.setattr(A2AClient, "send_message", fake_send_message)

            tool = await a2a_peer_tool(peer_url=httpserver.url_for(""))
            result = await tool.ainvoke({"query": "x"})
            assert "Error: A2A JSON-RPC error" in result
            assert "internal error" in result
