"""Tests for ``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT`` and its injection into sessions.

Unit 1 of spec 55 — Default Orchestrator Prompt.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.agents.slo_agent.orchestrator.spawn_tool as spawn_tool_module
from src.agents.slo_agent.orchestrator.spawn_tool import (
    DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
    SpawnSubAgentsTool,
)
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


class TestDefaultOrchestratorPromptContent:
    """Content-level assertions on ``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT``."""

    def test_constant_exists_in_spawn_tool_module(self) -> None:
        """``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT`` is a non-empty string."""
        assert isinstance(DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT, str)
        assert len(DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT) > 0

    def test_prompt_identifies_orchestrator_role(self) -> None:
        """The prompt identifies the agent as an orchestrator."""
        assert "orchestrator" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_prompt_covers_parallel_mode(self) -> None:
        """The prompt describes the parallel dispatch mode."""
        assert "parallel" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_covers_chain_mode(self) -> None:
        """The prompt describes the chain dispatch mode."""
        assert "chain" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_covers_retry_policy(self) -> None:
        """The prompt includes retry policy guidance."""
        assert "retry" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_covers_result_synthesis(self) -> None:
        """The prompt covers result synthesis (matches synthesize/synthesizing/synthesis)."""
        assert "synthesiz" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_covers_headless_autonomous_policy(self) -> None:
        """The prompt explains the headless autonomous-spawn policy."""
        assert "headless" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "autonomously" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_covers_tui_explicit_request_policy(self) -> None:
        """The prompt explains the TUI explicit-request-only spawn policy."""
        assert "TUI" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "explicitly" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_treats_dynamic_workflows_alias_as_orchestrator_request(self) -> None:
        """Common dynamic-workflow phrasing is treated as an explicit orchestrator request."""
        assert "dynamic workflows" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "dyanmic workflows" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "multiple slo agents" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_addendum_treats_dynamic_workflows_as_explicit_request(self) -> None:
        """The TUI addendum recognizes the dynamic-workflows alias as explicit consent."""
        assert "dynamic workflows" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
        assert "dyanmic workflows" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM

    def test_prompt_routes_tui_dynamic_workflows_to_launch_workflow(self) -> None:
        """TUI-mode dynamic-workflow requests route to ``launch_workflow`` (spec 57.a.2)."""
        assert "launch_workflow" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "detach" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_prompt_forbids_launch_workflow_in_headless_mode(self) -> None:
        """Headless orchestrators must never recurse via ``launch_workflow``."""
        assert "NEVER call `launch_workflow` from a headless run" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_addendum_routes_dynamic_workflows_to_launch_workflow(self) -> None:
        """The TUI addendum routes dynamic workflows to ``launch_workflow`` when available."""
        assert "launch_workflow" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
        assert "spawn_sub_agents" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM

    def test_sync_phrase_routes_to_spawn_sub_agents(self) -> None:
        """Unqualified 'dynamic workflows' runs in-session via spawn_sub_agents (spec 56.a.2).

        The TUI paragraph must state that the phrase runs the workflow IN THIS SESSION
        via spawn_sub_agents; the old spec-57 routing sentence that sent unqualified
        requests to launch_workflow must be absent.
        """
        assert "run the named workflow IN THIS SESSION" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert (
            "satisfy dynamic-workflow and named-workflow requests by calling"
            not in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        )

    def test_detach_qualifiers_documented(self) -> None:
        """All three detach qualifiers and the qualifier-only rule are documented (spec 56.a.2).

        The prompt must name all three qualifiers — "headless", "detached", "independent" —
        and must state that without a detach qualifier, launch_workflow must not be called.
        """
        assert '"headless"' in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert '"detached"' in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert '"independent"' in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert "without a detach qualifier, never call it" in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_addendum_routes_unqualified_to_spawn(self) -> None:
        """Addendum states unqualified request runs in-session and qualifier-only launch rule (spec 56.a.2).

        The TUI addendum must contain "runs in-session" to document the sync default
        and must contain the qualifier-only rule for launch_workflow.
        """
        assert "runs in-session" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
        assert "launch_workflow" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
        assert "detach qualifier" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM

    def test_prose_recursion_guard_retained(self) -> None:
        """The line-97 prose recursion guard sentence is present verbatim (spec 56.a.2).

        The sentence at the old line 97 of spawn_tool.py must remain character-for-character
        so the human-readable headless-mode warning is not silently lost.
        """
        expected: str = (
            "Headless mode is already inside a detached orchestrator: "
            "keep using spawn_sub_agents there and NEVER call `launch_workflow` "
            "from a headless run — that would recurse into a second detached orchestrator."
        )
        assert expected in DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_constant_exported_in_all(self) -> None:
        """``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT`` is declared in ``__all__``."""
        assert "DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT" in spawn_tool_module.__all__


class TestAttachSubAgentPoolInjectsOrchestratorPrompt:
    """``SloAgentSession.attach_sub_agent_pool`` injects the orchestrator prompt."""

    def test_sets_system_prompt_when_config_has_none(self) -> None:
        """When ``system_prompt`` is ``None``, ``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT`` is set."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=Path("/tmp"),
            model_name="gpt-4o",
        )
        session: SloAgentSession = SloAgentSession.build(config=config)
        mock_pool = MagicMock()
        spawn_tool = SpawnSubAgentsTool.build(pool=mock_pool)
        session.attach_sub_agent_pool(pool=mock_pool, spawn_tool=spawn_tool)

        assert session._config.system_prompt == DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    def test_does_not_overwrite_existing_system_prompt(self) -> None:
        """An existing ``system_prompt`` is preserved untouched after attach."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=Path("/tmp"),
            model_name="gpt-4o",
            system_prompt="custom body",
        )
        session: SloAgentSession = SloAgentSession.build(config=config)
        mock_pool = MagicMock()
        spawn_tool = SpawnSubAgentsTool.build(pool=mock_pool)
        session.attach_sub_agent_pool(pool=mock_pool, spawn_tool=spawn_tool)

        assert session._config.system_prompt == "custom body"

    def test_addendum_appended_in_both_cases(self) -> None:
        """``ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM`` appears in ``append_system_prompt`` regardless of initial ``system_prompt``."""
        for initial_prompt in (None, "custom body"):
            config: SessionConfigDAO = SessionConfigDAO(
                workdir=Path("/tmp"),
                model_name="gpt-4o",
                system_prompt=initial_prompt,
            )
            session: SloAgentSession = SloAgentSession.build(config=config)
            mock_pool = MagicMock()
            spawn_tool = SpawnSubAgentsTool.build(pool=mock_pool)
            session.attach_sub_agent_pool(pool=mock_pool, spawn_tool=spawn_tool)

            assert ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM in (
                session._config.append_system_prompt or ""
            ), f"Addendum missing for initial_prompt={initial_prompt!r}"
