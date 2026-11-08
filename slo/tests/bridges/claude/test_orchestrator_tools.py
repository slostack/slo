"""Orchestrator replacement journeys using real session and pool ownership."""

from pathlib import Path
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from typing import Any
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
import os
from src.bridges.claude.bridge import SloClaudeBridge
from tests.cli.test_claude_bridge import ToolRoundTransport

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class


@pytest.mark.parametrize(
    "prompt_options",
    [{}, {"system_prompt": "custom orchestrator"}, {"append_system_prompt": "extra guidance"}],
)
async def test_model_switch_keeps_orchestrator_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prompt_options: dict[str, str]
) -> None:
    """A8: selecting the bridge changes the model, not the attached capabilities."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    from src.auth.credential_store import CredentialStore
    from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType

    store = CredentialStore()
    assert store.path.resolve().is_relative_to(Path(os.environ["SLO_HOME"]).resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="synthetic-not-used-for-network",
        )
    )
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            history_root=tmp_path / "history",
            system_prompt=prompt_options.get("system_prompt"),
            append_system_prompt=prompt_options.get("append_system_prompt"),
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    OrchestratorSessionBootstrap.attach(session=session)
    pool = session._sub_agent_pool
    tools = session.orchestration_tools
    assert session._config is not None
    attached_prompts = (session._config.system_prompt, session._config.append_system_prompt)
    try:
        for route in ("claude-bridge:claude-haiku-5-5", "gpt-5.4"):
            outcome = await session.prepare_model_selection(model_name=route)
            assert outcome.startswith("active model switched"), outcome
            assert session._sub_agent_pool is pool
            assert session.orchestration_tools == tools
            assert session._config is not None
            assert (session._config.system_prompt, session._config.append_system_prompt) == attached_prompts
            if route.startswith("claude-bridge:"):
                model = session.agent.llm
                assert isinstance(model, SloClaudeBridge)
                assert len(session._runtime_tool_names()) == 13
                assert {tool.name for tool in model._tools} == set(session._runtime_tool_names())
        assert not transport.connected
    finally:
        await session.close_agent_resources()


async def test_foreign_extension_rejects_before_replacing_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A8: unsupported extra names cannot retire the current agent or pool."""
    from langchain_core.tools import StructuredTool

    def foreign(*, value: str) -> str:
        """Return inert input; this foreign tool is never executed."""
        return value

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    from src.auth.credential_store import CredentialStore
    from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType

    store = CredentialStore()
    assert store.path.resolve().is_relative_to(Path(os.environ["SLO_HOME"]).resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="synthetic-not-used-for-network",
        )
    )
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            extra_tools=[StructuredTool.from_function(func=foreign)],
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    OrchestratorSessionBootstrap.attach(session=session)
    prior_pool = session.sub_agent_pool
    assert prior_pool is not None
    prior_tools = session.orchestration_tools
    prior_config = session._config
    prior_agent = session._agent
    try:
        outcome = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert "extension" in outcome
        assert session.active_model_name == "gpt-5.4"
        assert session._config is prior_config and session._agent is prior_agent
        assert session.sub_agent_pool is prior_pool
        assert session.orchestration_tools == prior_tools
        assert not transport.connected
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("binding", ["dictionary-schema", "duplicate", "unsupported-dialect"])
async def test_invalid_allowed_binding_preserves_usable_prior_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding: str
) -> None:
    """FR101A5-01: reject complete binding before retiring a working direct session."""
    from langchain_core.tools import BaseTool, StructuredTool
    from pydantic import BaseModel, ConfigDict
    from src.agents.base import LLMBuildResult, LLMFactory
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.preferences.service import UserPreferencesStore
    from src.auth.credential_store import CredentialStore
    from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType

    class InputDAO(BaseModel):
        """Typed host input whose unsupported dialect reaches portable validation."""

        model_config = ConfigDict(json_schema_extra={"$schema": "http://json-schema.org/draft-07/schema#"})
        value: str

    def answer(*, value: str) -> str:
        """Return input without dispatching children; the tool is never invoked."""
        return value

    # The heterogeneous kwargs belong to the vendor model factory boundary only.
    def direct_model(**kwargs: Any) -> LLMBuildResult:
        """Supply the third-party model, retaining real session/graph/executor owners."""
        assert kwargs["model_name"] == "gpt-5.4"
        return LLMBuildResult(
            llm=FauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(content="prior works"),
                    FauxChatModel.assistant_message(content="still works"),
                ]
            ),
            supports_explicit_caching=False,
        )

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.setattr(target=LLMFactory, name="create", value=direct_model)
    store = CredentialStore()
    assert store.path.resolve().is_relative_to(Path(os.environ["SLO_HOME"]).resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-unused"
        )
    )
    preferences_path = UserPreferencesStore._preferences_path()
    assert preferences_path.resolve().is_relative_to(Path(os.environ["SLO_HOME"]).resolve())
    UserPreferencesStore.upsert(model_name="gpt-5.4")
    preferences = preferences_path.read_bytes()
    extra_tools: list[BaseTool] = [
        StructuredTool.from_function(
            func=answer,
            name="spawn_sub_agents" if binding == "duplicate" else "launch_workflow",
            description="inert allowed-name extension",
            args_schema=InputDAO if binding != "dictionary-schema" else {"type": "object"},
        )
    ]
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            extra_tools=extra_tools,
            history_root=tmp_path / "history",
            system_prompt="retained prompt",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    OrchestratorSessionBootstrap.attach(session=session, headless=True)
    try:
        before: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="before selection")]
        assert before[-1].kind == "run_completed" and before[-1].content == "prior works"
        prior_agent: SloAgent = session.agent
        prior_config = session._config
        assert prior_config is not None
        prior_pool = session.sub_agent_pool
        assert prior_pool is not None
        prior_tools: list[BaseTool] = list(prior_agent.tools)
        prior_orchestration_tools = session.orchestration_tools
        outcome = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert "active model switched" not in outcome, outcome
        assert (
            "typed argument schema"
            if binding == "dictionary-schema"
            else "tool binding" if binding == "duplicate" else "schema dialect"
        ) in outcome
        assert session.active_model_name == "gpt-5.4"
        assert session._config is prior_config and session._agent is prior_agent
        assert session._config.extra_tools == prior_config.extra_tools
        assert session.sub_agent_pool is prior_pool
        assert session.orchestration_tools == prior_orchestration_tools
        assert prior_agent.tools == prior_tools
        assert preferences_path.read_bytes() == preferences
        assert not transport.connected and transport.prompts == []
        after: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="after rejection")]
        assert after[-1].kind == "run_completed" and after[-1].content == "still works"
        assert session.agent is prior_agent
        stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
            root=tmp_path / "history"
        ).load_events(session_id=session.session_id)
        assert sum(event.kind == "run_completed" for event in stored) == 2
        assert not any(event.kind in {"run_failed", "run_aborted"} for event in stored)
        assert not transport.connected and transport.prompts == []
    finally:
        await session.close_agent_resources()


class DelegatingTransport(ToolRoundTransport):
    """Ask the real host graph to dispatch two children through its registered tool."""

    async def _emit_tool_round(self) -> None:
        """Adapt the scripted native tool blocks and MCP call to spawn_sub_agents."""
        import json

        await super()._emit_tool_round()
        arguments: dict[str, Any] = {
            "mode": "parallel",
            "tasks": [
                {
                    "task_id": name,
                    "task_summary": f"Inspect {name} module",
                    "prompt": f"Inspect {name}",
                    "model": "claude-bridge:claude-haiku-5-5",
                }
                for name in ("alpha", "beta")
            ],
        }
        # Vendor wire frames are heterogeneous JSON; mutations preserve that raw seam.
        pending: list[dict[str, Any]] = []
        while not self.messages.empty():
            message = self.messages.get_nowait()
            if message["type"] == "stream_event":
                event = message["event"]
                if event["type"] == "content_block_start":
                    event["content_block"]["name"] = "mcp__slo__spawn_sub_agents"
                if event["type"] == "content_block_delta":
                    event["delta"]["partial_json"] = json.dumps(arguments)
            if message["type"] == "assistant":
                message["message"]["content"][0].update(name="mcp__slo__spawn_sub_agents", input=arguments)
            pending.append(message)
        for message in pending:
            await self.messages.put(message)
        self._tool_request["request"]["message"]["params"].update(
            name="spawn_sub_agents", arguments=arguments
        )


def scripted_bootstrap(*, tmp_path: Path, fail_child: bool = False) -> type[OrchestratorSessionBootstrap]:
    """Build a bootstrap using a real pool and scripted process wrappers, never OS children."""
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool
    from src.agents.slo_agent.orchestrator.process import SubAgentProcess
    from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO

    class ScriptedChild(SubAgentProcess):
        """Publish a scripted child terminal through the real registry/persistence gateway."""

        async def run(self) -> SubAgentResultDAO:
            """Return one canonical winner without launching a managed process."""
            assert self._model == "claude-bridge:claude-haiku-5-5"
            from src.agents.slo_agent.events.stream import AgentStreamEventDAO

            failed = fail_child and self.task.task_id == "beta"
            event = AgentStreamEventDAO(
                kind="run_failed" if failed else "run_completed",
                content="Claude Code /login required" if failed else f"answer-{self.task.task_id}",
                metadata={"failure_scope": "preparation"} if failed else {},
            )
            await self._handle_line(raw=(event.model_dump_json() + "\n").encode())
            return self._publish_terminal(
                candidate=self._terminal_result(exit_code=1 if failed else 0),
                terminal_reason="failed" if failed else "completed",
                terminated_by="natural",
            )

    class ScriptedBootstrap(OrchestratorSessionBootstrap):
        """Keep normal attachment and pool dispatch; replace only child execution."""

        @classmethod
        def _build_pool(cls, *, session: SloAgentSession, owner_session_id: str) -> SubAgentPool:
            """Construct the real retained pool with an injected process factory."""
            return SubAgentPool(
                orchestrator_session_id=session.session_id,
                default_model=session.active_model_name,
                relay=session.event_relay,
                owner_session_id=owner_session_id,
                run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
                history_root=tmp_path / "history",
                process_factory=ScriptedChild,
            )

    return ScriptedBootstrap


@pytest.mark.parametrize("fail_child", [False, True])
async def test_claude_orchestrator_delegates_to_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_child: bool
) -> None:
    """A9/A10: the real graph receives combined child results once, including auth failures."""
    import json
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = DelegatingTransport(path=tmp_path / "unused")
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="parent",
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    scripted_bootstrap(tmp_path=tmp_path, fail_child=fail_child).attach(session=session)
    try:
        events: list[AgentStreamEventDAO] = [
            event async for event in session.invoke(text="Delegate inspection")
        ]
        assert events[-1].kind == "run_completed"
        assert len(transport.tool_results) == 1
        receipt = json.dumps(transport.tool_results)
        assert "answer-alpha" in receipt
        assert ("Claude Code /login required" if fail_child else "answer-beta") in receipt
        pool = session._sub_agent_pool
        assert pool is not None
        statuses = pool.registry.snapshot()
        assert len(statuses) == 2
        assert sorted(entry.status for entry in statuses) == (
            ["completed", "failed"] if fail_child else ["completed", "completed"]
        )
        stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
            root=tmp_path / "history"
        ).load_events(session_id="parent")
        assert sum(event.kind == "tool_result" for event in stored) == 1
        assert sum(event.kind == "run_completed" for event in stored) == 1
    finally:
        await session.close_agent_resources()


async def test_plugin_rejection_preserves_attached_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A8: real plugin loading rejects bridge selection before replacing prior capability owners."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.delenv(name="SLO_PLUGINS_DISABLED", raising=False)
    plugin = tmp_path / "extension.py"
    assert plugin.resolve().is_relative_to(tmp_path.resolve())
    plugin.write_text(
        "from langchain_core.tools import tool\n"
        '@tool\ndef extension(value: str) -> str:\n    """Return input."""\n    return value\n'
        "def register(slo):\n    slo.register_tool(tool=extension)\n",
        encoding="utf-8",
    )
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", plugin_paths=[plugin], history_root=tmp_path / "history"
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    OrchestratorSessionBootstrap.attach(session=session)
    pool, config, agent = session._sub_agent_pool, session._config, session._agent
    tools = session.orchestration_tools
    try:
        assert session._plugin_registry is not None and session._plugin_registry.all_tools()
        outcome = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert "plugin tools" in outcome
        assert session.active_model_name == "gpt-5.4"
        assert session._config is config and session._agent is agent and session._sub_agent_pool is pool
        assert session.orchestration_tools == tools
        assert not transport.connected
    finally:
        await session.close_agent_resources()
