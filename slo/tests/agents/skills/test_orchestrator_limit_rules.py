"""Keep documented orchestration limits consistent with runtime defaults."""

import ast
from pathlib import Path

import pytest

from src.agents.slo_agent.orchestrator.spawn_tool import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[3]


def test_concurrency_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluate the actual config expression without reloading global config."""
    import os

    tree = ast.parse((ROOT / "config/cfg.py").read_text())
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SUBAGENT_MAX_CONCURRENCY"
    )
    expression = compile(ast.Expression(body=assignment.value), "config/cfg.py", "eval")
    monkeypatch.delenv("SLO_SUBAGENT_MAX_CONCURRENCY", raising=False)
    assert eval(expression, {"os": os}) == 6
    monkeypatch.setenv("SLO_SUBAGENT_MAX_CONCURRENCY", "2")
    assert eval(expression, {"os": os}) == 2


def test_prompt_retry_and_dispatch_policy() -> None:
    text = DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
    assert "initial attempt plus up to 3 retries" in text
    assert "After the third retry fails" in text
    assert "Default maximum dispatch calls per workflow turn: 20" in text
    assert "Default maximum workflow turns started per task: 60" in text
    assert "including partial turns" in text
    assert "1,200 dispatch calls" in text
    assert "Never retry an aborted task" in text
    for stale in ("retry once", "maximum of 1 additional", "aborts or crashes", "Maximum total spawn calls"):
        assert stale not in text


@pytest.mark.parametrize(
    "workflow", ["code-test-review", "specification-development", "gitlab-code-test-review"]
)
def test_workflow_failure_policy(workflow: str) -> None:
    text = (ROOT / f"skills/design-and-analysis/workflows/{workflow}.md").read_text()
    assert "up to three times" in text
    assert "Never retry an aborted task" in text
    assert "retried once" not in text


def test_headless_skill_defaults_and_abort_policy() -> None:
    text = (ROOT / "skills/design-and-analysis/headless-orchestration/SKILL.md").read_text()
    assert "| `SLO_SUBAGENT_MAX_CONCURRENCY` | `6` | `6` |" in text
    assert "| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1800` | `1800` |" in text
    assert "Never retry an aborted task" in text
    assert "Resume if partial work exists, or relaunch" not in text


def test_claude_timeout_defaults() -> None:
    text = (ROOT / "CLAUDE.md").read_text()
    assert "(default `10800`)" in text
    assert "(default `7200`)" in text
    assert "(default `4800`)" not in text
    assert "(default `3600`)" not in text


def test_verdict_gates_and_chain_restriction() -> None:
    text = DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
    assert "Execution success is not workflow acceptance" in text
    assert "Use chain only for sequences with no intermediate approval or revision gate" in text
    assert "Advance only on verified READY/COMPLETE" in text
    assert "return to the start of the revision loop" in text
    assert "Keep implementation and its tests together" in text
    assert "explicitly authorized to take over" in text
    assert "A Bash tool export cannot change the running orchestrator" in text


def test_headless_completion_requires_verdict_and_artifacts() -> None:
    text = (ROOT / "skills/design-and-analysis/headless-orchestration/SKILL.md").read_text()
    assert "workflow done" not in text
    assert "execution success, not workflow acceptance" in text
    assert "phase verdicts and required artifacts" in text


@pytest.mark.parametrize(
    "source",
    (
        "src/agents/slo_agent/orchestrator/spawn_tool.py",
        "skills/design-and-analysis/workflows/SKILL.md",
    ),
)
def test_workflow_budget_defaults_and_user_override_contract(source: str) -> None:
    """Published defaults are overridable without resetting counts or runtime caps."""
    text = " ".join((ROOT / source).read_text().split())
    for phrase in (
        "60 workflow turns",
        "20 dispatch calls",
        "1,200 dispatch calls",
        "Explicit user instructions override these two prompt-level budgets",
        "raise, lower or remove",
        "unlimited",
        "workflow-specific numeric defaults",
        "Changing a budget does not reset consumed counts",
        "runtime batch, concurrency or detached-workflow caps",
        "six dispatch calls",
        "stop before turn 61 or dispatch 21 within a turn",
        "no numeric cutoff for an explicitly unlimited budget",
        "retain the default for any unspecified budget",
        "carry them into phase prompts and authorized continuations",
    ):
        assert phrase in text
    for stale in (
        "48 dispatch calls",
        "Eight started turns",
        "Eight turns started",
        "Stop before turn 9",
        "Start no ninth turn",
        "seventh dispatch",
        "A stricter user or workflow limit still applies",
    ):
        assert stale not in text


@pytest.mark.parametrize("source", ("AGENTS.md", "CLAUDE.md"))
def test_project_guidance_budget_defaults_and_overrides(source: str) -> None:
    """Automatically loaded project context must not restore superseded limits."""
    text = " ".join((ROOT / source).read_text().split())
    assert "60 workflow turns" in text
    assert "20 dispatch calls" in text
    assert "Explicit user instructions override" in text
    assert "unlimited" in text
    assert "eight workflow turns" not in text
    assert "six dispatch calls per workflow turn" not in text
