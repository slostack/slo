"""Documentary contracts for the authorized Feature 95 headless follow-up."""

import re
from pathlib import Path

import json

import pytest

from unittest.mock import AsyncMock

from src.agents.model_catalog.dao import CANONICAL_REASONING_LEVEL_ORDER
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.orchestrator.spawn_tool import resolve_sub_agent_tasks

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills/orchestration/headless-orchestration/SKILL.md"
MODELS = {"gpt-6-astra", "gpt-6.1-sol"}


def test_monitoring_routes_use_managed_identity_or_explicit_shell_scope() -> None:
    """Scan every guide subsection so later polling advice cannot bypass managed launch."""
    text = SKILL.read_text()
    sections = re.split(pattern=r"(?m)^(?=#{2,3} )", string=text)
    polling_sections = [
        section
        for section in sections
        if re.search(pattern=r"```bash\n(?:(?!```).)*\n(?:while|for) ", string=section, flags=re.S)
    ]
    assert polling_sections, "Retain the explicitly requested shell/CI monitoring example"
    for section in polling_sections:
        heading = section.splitlines()[0].lower()
        assert "shell/ci" in heading, heading
        assert "agent session" not in heading and "agent turn" not in section.lower()
    managed = [section for section in sections if "monitoring from inside" in section.lower()]
    assert len(managed) == 1
    for token in ("launch_workflow", "workflow_status", "workflow_id", "orchestrator_session_id"):
        assert token in managed[0]
    assert "```bash" not in managed[0]
    assert "schema" in managed[0] and "stop" in managed[0]
    assert "verdicts" in managed[0] and "artifacts" in managed[0]


def test_serial_examples_are_separate_native_json_calls() -> None:
    """Parse gated calls independently rather than forgiving escaped fragments."""
    text = SKILL.read_text().split("### Serial phases", 1)[1].split("**Chain shorthand:**", 1)[0]
    blocks = re.findall(pattern=r"```json\n(.*?)\n```", string=text, flags=re.S)
    assert len(blocks) == 3
    for block, expected in zip(blocks, ("medium", "high", "high"), strict=True):
        call = json.loads(block)
        assert set(call) == {"mode", "tasks"}
        assert call["mode"] == "single"
        assert len(call["tasks"]) == 1
        task = call["tasks"][0]
        assert task["model"] in MODELS
        assert task["reasoning_level"] == expected


def test_all_model_literals_are_authorized_gpt_examples() -> None:
    """Scan the entire guide, including escaped task JSON and pool entries."""
    text = SKILL.read_text().replace('\\"', '"')
    models = re.findall(pattern=r'(?:model|model_name)"\s*:\s*"([^"]+)"', string=text)
    models += re.findall(pattern=r"\b(?:claude|kimi|moonshot|gpt)-[\w.-]+", string=text)
    assert set(models) == MODELS
    assert '"provider":"openai"' in text
    assert '"provider":"anthropic"' not in text


def _example_tasks() -> list[dict[str, str]]:
    """Parse every JSON fence and collect native envelope or standalone tasks."""
    blocks = re.findall(pattern=r"```json\n(.*?)\n```", string=SKILL.read_text(), flags=re.S)
    tasks: list[dict[str, str]] = []
    for block in blocks:
        value = json.loads(block)
        if isinstance(value, list):
            tasks.extend(value)
        elif "mode" in value:
            assert set(value) == {"mode", "tasks"}
            tasks.extend(value["tasks"])
    return tasks


def test_every_child_example_has_explicit_reasoning() -> None:
    """Every parsed task, including standalone examples, carries actual fields."""
    tasks = _example_tasks()
    assert len(tasks) == 11
    for task in tasks:
        assert task["model"] in MODELS
        assert task["reasoning_level"] in {"medium", "high"}
        assert "reasoning" not in task


def test_chain_is_concrete_ungated_transformation() -> None:
    """Chain examples cannot masquerade as acceptance-gated workflow phases."""
    text = SKILL.read_text().split("**Chain shorthand:**", 1)[1].split("### Parallel phases", 1)[0]
    block = re.search(pattern=r"```json\n(.*?)\n```", string=text, flags=re.S)
    assert block is not None
    tasks = json.loads(block.group(1))["tasks"]
    assert [task["task_id"] for task in tasks] == ["summarize", "shorten"]
    assert "{previous}" in tasks[1]["prompt"]
    assert "execution status, not verdict acceptance" in text


def test_child_contract_explains_payload_and_inheritance_boundaries() -> None:
    """Documentation distinguishes child resolution from managed bootstrap state."""
    text = SKILL.read_text()
    for phrase in (
        "non-empty native `tasks` wins even when invalid",
        "`None` or `[]` falls through",
        "mode/tasks at the envelope",
        "model/reasoning_level per task",
        "not the parent's explicit reasoning",
        "Invalid task definition:",
        "No tasks provided: supply 'tasks'",
        "execution status, not verdict acceptance",
    ):
        assert phrase in text


@pytest.mark.parametrize("native", [None, []])
def test_empty_native_uses_legacy_shared_validation(native: list[dict[str, object]] | None) -> None:
    """Both absent native shapes recover legacy objects and validate the same DAO."""
    legacy = json.dumps(
        [
            {
                "task_id": "legacy",
                "task_summary": "Check child reasoning compatibility",
                "prompt": "text",
                "reasoning_level": "high",
            }
        ]
    )
    resolved = resolve_sub_agent_tasks(tasks=native, tasks_json=legacy)
    assert resolved.error is None
    assert resolved.tasks[0].reasoning_level == "high"
    assert resolved.tasks[0].task_id == "legacy"


@pytest.mark.parametrize("invalid", [{"reasoning": "high"}, {"reasoning_level": "HIGH"}])
def test_invalid_native_never_rescues_with_legacy(invalid: dict[str, str]) -> None:
    """Unknown keys and noncanonical literals fail on both input paths."""
    task = {
        "task_id": "native",
        "task_summary": "Check child reasoning compatibility",
        "prompt": "text",
        **invalid,
    }
    native = resolve_sub_agent_tasks(
        tasks=[task],
        tasks_json='[{"task_id":"valid","task_summary":"Check child reasoning compatibility","prompt":"x"}]',
    )
    legacy = resolve_sub_agent_tasks(tasks=None, tasks_json=json.dumps([task]))
    assert native.error is not None
    assert native.error.startswith("Invalid task definition:")
    assert legacy.error == native.error
    assert native.tasks == []


@pytest.mark.parametrize("native", [None, []])
@pytest.mark.parametrize("legacy", [None, "", "  "])
def test_missing_payload_returns_exact_error(
    native: list[dict[str, object]] | None, legacy: str | None
) -> None:
    """Absence is reported consistently for empty native and legacy forms."""
    resolved = resolve_sub_agent_tasks(tasks=native, tasks_json=legacy)
    assert resolved.tasks == []
    assert resolved.error == (
        "No tasks provided: supply 'tasks' (a JSON array of task objects, "
        "preferred) or the legacy 'tasks_json' string."
    )


@pytest.mark.parametrize("level", ["omitted", None, *CANONICAL_REASONING_LEVEL_ORDER])
def test_resolved_task_reasoning_reaches_child_argv(level: str | None) -> None:
    """Exercise resolver, DAO and real argv builder without spawning a process."""
    raw: dict[str, object] = {
        "task_id": "child",
        "task_summary": "Check child reasoning compatibility",
        "prompt": "text",
        "model": "gpt-6-astra",
    }
    if level != "omitted":
        raw["reasoning_level"] = level
    resolved = resolve_sub_agent_tasks(tasks=[raw], tasks_json=None)
    assert resolved.error is None
    task = resolved.tasks[0]
    registry = ProcessRegistry()
    dispatch_id = "44444444-4444-4444-8444-444444444444"
    registry.begin_dispatch(dispatch_id=dispatch_id)
    execution_id = registry.register(
        dispatch_id=dispatch_id, task_id=task.task_id, session_id="child-test", task=task
    )
    argv = SubAgentProcess(
        task=task,
        session_id="child-test",
        model=task.model,
        relay=AsyncMock(),
        registry=registry,
        execution_id=execution_id,
    )._build_argv()
    assert argv[argv.index("--model") + 1] == "gpt-6-astra"
    if level in {"omitted", None}:
        assert task.reasoning_level is None
        assert "--reasoning" not in argv
        return
    assert task.reasoning_level == level
    assert argv[argv.index("--reasoning") + 1] == level


def test_native_document_examples_pass_real_resolver() -> None:
    """Historic reasoning examples require explicit summary adaptation for the new schema."""
    for raw in _example_tasks():
        adapted = {**raw, "task_summary": "Check documented child reasoning compatibility"}
        resolved = resolve_sub_agent_tasks(tasks=[adapted], tasks_json="not JSON")
        assert resolved.error is None
        assert resolved.recovery_notes == []
        assert resolved.tasks[0].model == raw["model"]
        assert resolved.tasks[0].reasoning_level == raw["reasoning_level"]


def test_every_shell_run_has_explicit_reasoning() -> None:
    """Full runnable blocks cannot silently inherit the parent setting."""
    commands = re.findall(
        pattern=r"python -m src.cli run \\\n.*?(?=\n\n)", string=SKILL.read_text(), flags=re.S
    )
    assert len(commands) == 3
    for command in commands:
        assert '--reasoning "$ORCHESTRATOR_REASONING"' in command
    assert 'ORCHESTRATOR_REASONING="${ORCHESTRATOR_REASONING:-high}"' in SKILL.read_text()


def test_managed_launch_contract_and_evidence_limitations() -> None:
    """The managed path carries real fields and refuses schema workarounds."""
    text = SKILL.read_text()
    examples = re.findall(pattern=r'```json\n(\{\n  "brief".*?\})\n```', string=text, flags=re.S)
    assert len(examples) == 1
    launch = json.loads(examples[0])
    assert launch["model"] == "gpt-6-astra"
    assert launch["reasoning_level"] == "high"
    for required in (
        "exposed-schema mismatch",
        "do not silently inherit",
        "do not bypass",
        "bootstrap-time snapshot",
        "requested",
        "effective",
        "--resume",
        "off / minimal / low / medium / high / xhigh / max",
        "CLI forwards the raw string",
        "slash parser trims and lowercases",
        "does not prove account entitlement",
        "same-provider",
        "Code+Test: medium",
        "Review: high",
        "Completion: high",
    ):
        assert required in text
    assert "--model --reasoning" in text


def test_phase_defaults_and_managed_routing_are_consistent() -> None:
    """All executable examples carry phase defaults, not inheritance advice."""
    text = SKILL.read_text()
    assert "SLO_OPENAI_API_KEY" in text
    assert "Sub-agents inherit the pool default" not in text
    assert "prefer the background form" not in text
    assert "Chain is not a review gate" in text
    assert "ORCHESTRATOR_REASONING=high" in text
    for task in _example_tasks():
        expected = "medium" if task["task_id"] == "phase-1-code" else "high"
        assert task["reasoning_level"] == expected
