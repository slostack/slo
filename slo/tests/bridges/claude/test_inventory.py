"""Read-only binding and schema admission without native accounts."""

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import JsonValue
from mcp.shared.memory import create_connected_server_and_client_session

from src.agents.tools.bundles import create_read_only_tools
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolDefinitionDAO,
)
from src.bridges.dao import SloBridgeSessionOptionsDAO
from tests.bridges.claude.test_lifecycle import ready_status
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport, scripted_adapter_class


def session_options(*, tmp_path: Path, tools: tuple[ClaudeToolDefinitionDAO, ...]) -> ClaudeSessionOptionsDAO:
    """Build portable options with only disposable project state."""
    return ClaudeSessionOptionsDAO(
        session_id="inventory",
        model_id="claude-bridge:claude-haiku-5-5",
        working_directory=tmp_path,
        instructions="host",
        tools=tools,
    )


def definition(*, schema: dict[str, JsonValue], name: str = "read") -> ClaudeToolDefinitionDAO:
    """Build a raw portable definition, independently of Slo tool registration."""
    return ClaudeToolDefinitionDAO(name=name, description="Read", input_schema=schema)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_canonical_subset_is_rejected_before_configuration(count: int) -> None:
    """A6: canonical names alone do not authorize a partial host bundle."""
    model = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=SloClaudeBridgeAdapter(configuration=ClaudeBridgeConfigurationDAO()),
    )
    with pytest.raises(ValueError, match="bundle|inventory"):
        model.bind_tools(tools=create_read_only_tools()[:count])


@pytest.mark.parametrize("binding", ["duplicate", "foreign", "choice"])
def test_noncanonical_binding_is_rejected(binding: str) -> None:
    """A6: duplicates, copied tools and tool-choice options never change binding."""
    tools = create_read_only_tools()
    model = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=SloClaudeBridgeAdapter(configuration=ClaudeBridgeConfigurationDAO()),
    )
    if binding == "duplicate":
        tools.append(tools[0])
    if binding == "foreign":
        tools[0] = tools[0].model_copy()
    with pytest.raises(ValueError):
        model.bind_tools(tools=tools, **({"tool_choice": "auto"} if binding == "choice" else {}))


async def test_identical_rebinding_and_explicit_empty_graph_preserve_inventory(tmp_path: Path) -> None:
    """A6: direct graph explicit empty stays empty; configured binding cannot change."""
    from src.agents.slo_agent.agent import SloAgent

    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    model = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=adapter)
    tools = create_read_only_tools()
    assert model.bind_tools(tools=tools) is model
    model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="bundle",
            working_directory=tmp_path,
            instructions="host",
        )
    )
    assert model.bind_tools(tools=list(reversed(tools))) is model
    with pytest.raises(ValueError):
        model.bind_tools(tools=[])
    await model.close()

    empty_adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    empty_model = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=empty_adapter)
    agent = SloAgent(llm=empty_model, tools=[], cwd=str(tmp_path))
    empty_model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="empty",
            working_directory=tmp_path,
            instructions=agent._system_prompt,
        )
    )
    try:
        events = [event async for event in agent.invoke(query="hello")]
        assert events[-1].kind == "run_completed"
        assert empty_adapter._session_options is not None
        assert empty_adapter._session_options.tools == ()
        assert not any(event.kind.startswith("tool_call") for event in events)
        assert transport.prompts == ["hello"]
    finally:
        await agent.close()


@pytest.mark.parametrize(
    "fault", ["duplicate", "foreign", "root", "required", "external", "missing-ref", "cycle"]
)
async def test_invalid_portable_inventory_is_rejected_before_authentication(
    fault: str, tmp_path: Path
) -> None:
    """A14: invalid names/schemas cannot acquire native resources or authenticate."""
    schemas: dict[str, dict[str, JsonValue]] = {
        "root": {"type": "array", "items": {"type": "string"}},
        "required": {"type": "object", "required": "path"},
        "external": {"type": "object", "properties": {"path": {"$ref": "https://invalid.test/schema"}}},
        "missing-ref": {"type": "object", "properties": {"path": {"$ref": "#/$defs/absent"}}},
        "cycle": {"type": "object", "properties": {"path": {"$ref": "#"}}},
    }
    tools: tuple[ClaudeToolDefinitionDAO, ...] = (
        definition(
            schema=schemas.get(fault, {"type": "object"}), name="bash" if fault == "foreign" else "read"
        ),
    )
    if fault == "duplicate":
        tools = (*tools, tools[0])
    checks: list[str] = []

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Record whether validation incorrectly reached the external boundary."""
        checks.append("auth")
        return await ready_status()

    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=status,
    )
    try:
        with pytest.raises(ValueError):
            await adapter.start_session(session_options=session_options(tmp_path=tmp_path, tools=tools))
        assert checks == []
        assert not transport.connected and transport.prompts == []
    finally:
        await adapter.close()


async def test_schema_snapshot_resolves_references_without_weakening_constraints(tmp_path: Path) -> None:
    """A14: borrowed nested schemas cannot mutate admitted or MCP-advertised values."""
    schema: dict[str, JsonValue] = {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"Path": {"type": "string", "minLength": 2, "pattern": "^[a-z]+$"}},
        "properties": {
            "path": {"$ref": "#/$defs/Path", "minLength": 1, "maxLength": 12, "description": "Project path"},
            "offset": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}], "default": None},
        },
        "required": ["path"],
    }
    original = deepcopy(schema)
    tools = (definition(schema=schema),)
    options = session_options(tmp_path=tmp_path, tools=tools)
    transport = ScriptedClaudeTransport(block_response=True)
    transport.initialized_tools = ["mcp__slo__read"]
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    try:
        await adapter.start_session(session_options=options)
        required = tools[0].input_schema["required"]
        properties = tools[0].input_schema["properties"]
        assert isinstance(required, list) and isinstance(properties, dict)
        required.clear()
        properties["path"] = {"type": "number"}
        await adapter.invoke_agent(
            invocation_options=ClaudeInvocationOptionsDAO(invocation_id="one", text="hello")
        )
        async with asyncio.timeout(3):
            await transport.submitted.wait()
        bridge = adapter._runtime._tool_bridge
        assert bridge is not None
        async with create_connected_server_and_client_session(
            server=bridge.build_mcp_server()["instance"]
        ) as client:
            inventory = await client.list_tools()
            advertised = inventory.tools[0].inputSchema
            assert "$ref" not in str(advertised)
            from jsonschema import Draft202012Validator

            validator = Draft202012Validator(advertised)
            assert validator.is_valid({"path": "file", "offset": None})
            assert validator.is_valid({"path": "file", "offset": 1})
            for invalid in (
                {},
                {"path": "x"},
                {"path": "BAD"},
                {"path": "abcdefghijklmnop"},
                {"path": "file", "offset": 0},
                {"path": "file", "extra": True},
            ):
                assert not validator.is_valid(invalid)
            original_properties = original["properties"]
            assert isinstance(original_properties, dict)
            assert advertised["properties"]["offset"] == original_properties["offset"]
            advertised["required"].clear()
            assert (await client.list_tools()).tools[0].inputSchema["required"] == ["path"]
    finally:
        await adapter.close()


class InventoryTransport(ToolRoundTransport):
    """Change only native system/init metadata before a valid scripted tool round."""

    def __init__(self, *, path: Path, fault: str) -> None:
        """Keep the existing SDK/MCP fixture and select one inventory violation."""
        super().__init__(path=path)
        self.fault = fault

    def initialization_message(self) -> dict[str, object] | None:
        """Represent malformed relevant fields without fabricating connect metadata."""
        initialized = super().initialization_message()
        assert initialized is not None
        if self.fault == "absent":
            return None
        if self.fault == "tools-absent":
            initialized.pop("tools")
        elif self.fault == "tools-null":
            initialized["tools"] = None
        elif self.fault == "tools-type":
            initialized["tools"] = [17]
        elif self.fault == "tools-duplicate":
            initialized["tools"].append(initialized["tools"][0])
        elif self.fault == "tools-missing":
            initialized["tools"].pop()
        elif self.fault == "builtin":
            initialized["tools"].append("Bash")
        elif self.fault == "server-absent":
            initialized.pop("mcp_servers")
        elif self.fault == "server-null":
            initialized["mcp_servers"] = None
        elif self.fault == "server-row":
            initialized["mcp_servers"] = ["slo"]
        elif self.fault == "server-name":
            initialized["mcp_servers"][0]["name"] = 17
        elif self.fault == "server-status":
            initialized["mcp_servers"][0]["status"] = "pending"
        elif self.fault == "server-missing":
            initialized["mcp_servers"] = []
        elif self.fault == "server-duplicate":
            initialized["mcp_servers"] *= 2
        elif self.fault == "external-server":
            initialized["mcp_servers"].append({"name": "foreign", "status": "disabled"})
        elif self.fault == "source":
            initialized["mcp_servers"][0]["source"] = "project"
        elif self.fault == "valid-skills-absent":
            initialized.pop("skills")
        elif self.fault == "valid-extensions-absent":
            initialized.pop("skills")
            initialized.pop("plugins")
        elif self.fault == "plugins-null":
            initialized["plugins"] = None
        elif self.fault == "status-absent":
            initialized["mcp_servers"][0].pop("status")
        elif self.fault == "session-type":
            initialized["session_id"] = 17
        elif self.fault == "valid-bundled-extensions":
            initialized["skills"] = ["deep-research", "verify", "plugin-authoring"]
            initialized["plugins"] = [
                {"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"},
                {
                    "name": "cc-plugin-plugin-authoring",
                    "path": "builtin",
                    "source": "cc-plugin-plugin-authoring@builtin",
                },
            ]
        elif self.fault == "plugins":
            initialized["plugins"] = [
                {"name": "external", "path": "private-not-for-diagnostics", "source": "external@marketplace"}
            ]
        elif self.fault == "valid-optional-absent":
            initialized["mcp_servers"][0].pop("source")
            initialized["capabilities"] = ["future_capability"]
        elif self.fault != "valid":
            raise AssertionError(self.fault)
        return initialized


@pytest.mark.parametrize(
    "fault",
    [
        "absent",
        "tools-absent",
        "tools-null",
        "tools-type",
        "tools-duplicate",
        "tools-missing",
        "builtin",
        "server-absent",
        "server-null",
        "server-row",
        "server-name",
        "server-status",
        "server-missing",
        "server-duplicate",
        "external-server",
        "source",
        "plugins",
        "valid-bundled-extensions",
        "valid-skills-absent",
        "valid-extensions-absent",
        "plugins-null",
        "status-absent",
        "session-type",
        "valid-optional-absent",
        "valid",
    ],
)
async def test_initialized_inventory_admits_only_expected_tools_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    """A6/A14: real graph/history cannot execute output without valid initialization."""
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "project.txt"
    assert project.resolve().is_relative_to(tmp_path.resolve())
    project.write_text("synthetic inventory marker")
    transport = InventoryTransport(path=project, fault=fault)
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="inventory",
        history_store=store,
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5", enable_history=True
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed = []
    try:
        async with asyncio.timeout(5):
            if fault.startswith("valid"):
                observed = [event async for event in session.invoke(text="Read project")]
                assert observed[-1].kind == "run_completed"
                assert len(transport.tool_results) == 1
            else:
                with pytest.raises(RuntimeError, match="inventory|initializ") as failure:
                    async for event in session.invoke(text="Read project"):
                        observed.append(event)
                assert "private-not-for-diagnostics" not in str(failure.value)
                assert transport.tool_results == []
                assert not any(event.kind.startswith("tool_call") for event in observed)
        events = await store.load_events(session_id="inventory")
        kinds = [event.kind for event in events]
        assert kinds.count("user_message") == 1
        if not fault.startswith("valid"):
            assert kinds.count("run_failed") == 1
            assert not set(kinds) & {"tool_call", "tool_result", "run_completed"}
        assert transport.prompts == ["Read project"]
        assert transport.closed and transport.close_calls == 1
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
        {"type": "object", "properties": {"value": {"default": float("nan")}}},
    ],
)
async def test_unrepresentable_schema_is_rejected_before_native_submission(
    tmp_path: Path,
    schema: dict[str, JsonValue],
) -> None:
    """Do not reinterpret reference siblings under another dialect or emit non-JSON."""
    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    try:
        with pytest.raises(ValueError):
            await adapter.start_session(
                session_options=session_options(tmp_path=tmp_path, tools=(definition(schema=schema),))
            )
        assert not transport.connected and transport.prompts == []
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        ({}, "invalid session_id"),
        ([], "invalid metadata"),
        (
            {"session_id": "n", "tools": [], "mcp_servers": [], "plugins": [{"name": "unexpected"}]},
            "invalid plugins",
        ),
        (
            {
                "session_id": "n",
                "tools": [],
                "mcp_servers": [],
                "plugins": [{"name": "x", "source": "x@builtin", "path": "/unexpected/path"}],
            },
            "external plugin inventory",
        ),
        (
            {
                "session_id": "n",
                "tools": [],
                "mcp_servers": [],
                "plugins": [{"name": "x", "source": "@builtin", "path": "builtin"}],
            },
            "external plugin inventory",
        ),
        ({"session_id": "native", "tools": ["unexpected"], "mcp_servers": []}, "tool inventory mismatch"),
        (
            {
                "session_id": "native",
                "tools": [],
                "mcp_servers": [],
                "plugins": [{"name": "unexpected", "path": "unexpected", "source": "unexpected@market"}],
            },
            "external plugin inventory",
        ),
    ],
)
def test_initialization_failure_identifies_safe_rejection_reason(
    metadata: dict[str, object], reason: str
) -> None:
    """Identify the rejected contract without disclosing native payload values."""
    from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
    from src.bridges.claude.sdk.inventory import ClaudeToolInventory

    with pytest.raises(ClaudeBridgeError, match=reason) as failure:
        ClaudeToolInventory.validate_initialization(metadata=metadata, tools=())
    assert failure.value.code == "stream_protocol_failed"
    assert "unexpected" not in str(failure.value)
