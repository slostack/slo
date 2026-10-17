"""Tests for Kimi prompt-clause wiring in the sub-agent orchestrator."""

from __future__ import annotations

from pathlib import Path

from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO


def _make_process(
    *,
    task_id: str = "t1",
    prompt: str = "Do the thing.",
    model: str | None = None,
) -> SubAgentProcess:
    """Build a minimal SubAgentProcess for argv inspection."""
    return SubAgentProcess(
        task=SubAgentTaskDAO(task_id=task_id, prompt=prompt),
        session_id="s1",
        model=model,
        relay=None,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        execution_id="0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40",
        system_prompt="",
        parent_session_id=None,
        slo_home=None,
    )


class TestKimiClauseInSubAgentArgv:
    """The sub-agent process appends the Kimi clause only for the exact model."""

    def test_argv_appends_kimi_clause_for_exact_model(self) -> None:
        """``kimi-for-coding`` triggers the clause in the argv prompt."""
        process: SubAgentProcess = _make_process(
            prompt="Implement the feature.",
            model="kimi-for-coding",
        )

        argv: list[str] = process._build_argv()

        prompt_index: int = argv.index("-p")
        rendered_prompt: str = argv[prompt_index + 1]
        assert "Be succinct and terse" in rendered_prompt

    def test_argv_no_clause_for_kimi_k3(self) -> None:
        """``kimi-k3`` does not trigger the clause."""
        process: SubAgentProcess = _make_process(
            prompt="Implement the feature.",
            model="kimi-k3",
        )

        argv: list[str] = process._build_argv()

        prompt_index: int = argv.index("-p")
        rendered_prompt: str = argv[prompt_index + 1]
        assert "Be succinct and terse" not in rendered_prompt

    def test_argv_no_clause_for_highspeed(self) -> None:
        """``kimi-for-coding-highspeed`` does not trigger the clause."""
        process: SubAgentProcess = _make_process(
            prompt="Implement the feature.",
            model="kimi-for-coding-highspeed",
        )

        argv: list[str] = process._build_argv()

        prompt_index: int = argv.index("-p")
        rendered_prompt: str = argv[prompt_index + 1]
        assert "Be succinct and terse" not in rendered_prompt

    def test_argv_no_clause_for_non_kimi_model(self) -> None:
        """Non-Kimi models do not trigger the clause."""
        process: SubAgentProcess = _make_process(
            prompt="Implement the feature.",
            model="gpt-5.5",
        )

        argv: list[str] = process._build_argv()

        prompt_index: int = argv.index("-p")
        rendered_prompt: str = argv[prompt_index + 1]
        assert "Be succinct and terse" not in rendered_prompt
