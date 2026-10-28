"""Actual native and legacy tool admission, without process execution."""

import json
from pathlib import Path

import pytest

from src.agents.slo_agent.orchestrator.dao import OrchestratorResultDAO, SubAgentMode, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool

from src.agents.slo_agent.orchestrator.task_preview import TaskPreview, TASK_SUMMARY_FALLBACK

ERROR = "Invalid task definition: every task requires task_summary describing its assigned work in 1–96 characters."

# Original b.1 §2 complete assignments, not the later producer examples.
ORIGINAL_AUTHORED_PAIRS = [
    (
        "You own Step 1. Read AGENTS.md.\n"
        "Do not commit or spawn agents.\n"
        "Task: Fix workflow dismissal refresh races.\n"
        "Return READY with evidence.",
        "Fix workflow dismissal refresh races",
        (2,),
    ),
    (
        "Repository: /root/Code/slo\n"
        "Follow all conventions.\n"
        "Please review the child abort identity checks and their tests.\n"
        "Output: report only.",
        "Review child abort identity checks",
        (2,),
    ),
    (
        "Read RESEARCH.md first.\n"
        "Implement reversible workflow visibility.\n"
        "Verify missing-file restoration.\n"
        "Do not modify the scrollbar.",
        "Implement reversible workflow visibility; Verify missing-file restoration",
        (1, 2),
    ),
]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(("prompt", "summary", "assignment_lines"), ORIGINAL_AUTHORED_PAIRS)
async def test_original_authored_examples_survive_admission_and_boilerplate_moves(
    legacy: bool, prompt: str, summary: str, assignment_lines: tuple[int, ...]
) -> None:
    """Admit original and reordered assignments without deriving labels or changing prompts."""
    lines = prompt.splitlines()
    assignment = [line for index, line in enumerate(lines) if index in assignment_lines]
    boilerplate = [line for index, line in enumerate(lines) if index not in assignment_lines]
    variants = [prompt, "\n".join(assignment + boilerplate), "\n".join(boilerplate + assignment)]
    dispatcher = RecordingDispatcher()
    tool = SpawnSubAgentsTool.build(pool=dispatcher)
    for variant in variants:
        tasks = [{"task_id": "original", "prompt": variant, "task_summary": summary}]
        arguments = (
            {"mode": "single", "tasks_json": json.dumps(tasks)}
            if legacy
            else {"mode": "single", "tasks": tasks}
        )
        result = json.loads(await tool.ainvoke(arguments))
        assert "error" not in result
    assert len(dispatcher.calls) == len(variants)
    for batch, original in zip(dispatcher.calls, variants, strict=True):
        assert len(batch) == 1
        task = batch[0]
        assert task.prompt == original
        assert task.task_summary == summary
        carrier = TaskPreview.encode_summary(task_summary=task.task_summary)
        assert carrier == "Task summary v1: " + summary
        assert TaskPreview.project_summary(prompt_preview=carrier, task_text=task.prompt) == summary
        assert task.prompt == original


def test_original_no_assignment_example_keeps_honest_legacy_fallback() -> None:
    """No work is invented; obtaining an assignment remains the producer's obligation."""
    prompt = "You are an expert. Use high reasoning.\nReturn READY. Follow conventions."
    assert TaskPreview.project_summary(prompt_preview=prompt, task_text=prompt) == TASK_SUMMARY_FALLBACK
    # Mechanical validation is not a semantic detector and cannot certify an assignment.
    assert TaskPreview.validate_summary(task_summary="Use high reasoning") == "Use high reasoning"


class RecordingDispatcher:
    """Record only fully admitted batches."""

    def __init__(self) -> None:
        self.calls: list[list[SubAgentTaskDAO]] = []

    async def dispatch(self, *, mode: SubAgentMode, tasks: list[SubAgentTaskDAO]) -> OrchestratorResultDAO:
        """Record validated tasks without launching children."""
        self.calls.append(tasks)
        return OrchestratorResultDAO(mode=mode, results=[])


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"task_summary": None},
        {"task_summary": 7},
        {"task_summary": True},
        {"task_summary": " "},
        {"task_summary": "\x00"},
        *[
            {"task_summary": value}
            for value in [
                "work on task",
                "complete task",
                "follow instructions",
                "return ready",
                "phase task",
                "do the work",
                "Task summary unavailable — open details",
                "a " + "b" * 95,
                " " * 500 + "Compare rules",
                "Task summary v1: Compare rules",
            ]
        ],
        {"task_summary": "complete task", "extra": "secret-sentinel"},
    ],
)
@pytest.mark.parametrize("invalid_first", [False, True])
async def test_required_summary_rejects_batch_before_dispatch(
    tmp_path: Path,
    legacy: bool,
    invalid: dict[str, object],
    invalid_first: bool,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A single bad summary rejects the complete batch with fixed safe JSON."""
    dispatcher = RecordingDispatcher()
    tool = SpawnSubAgentsTool.build(pool=dispatcher)
    valid = {"task_id": "valid", "prompt": "Compare branch rules", "task_summary": "Compare branch rules"}
    bad = {"task_id": "bad", "prompt": "secret-sentinel", **invalid}
    tasks = [bad, valid] if invalid_first else [valid, bad]
    paths = set(tmp_path.rglob("*"))
    arguments = (
        {"mode": "parallel", "tasks_json": json.dumps(tasks)}
        if legacy
        else {"mode": "parallel", "tasks": tasks}
    )
    result = await tool.ainvoke(arguments)
    assert json.loads(result) == {"error": ERROR}
    assert dispatcher.calls == []
    assert set(tmp_path.rglob("*")) == paths
    captured = capsys.readouterr()
    assert "secret-sentinel" not in result + caplog.text + captured.out + captured.err


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("summary_first", [False, True])
async def test_first_invalid_task_controls_error_precedence(legacy: bool, summary_first: bool) -> None:
    """A later summary error never overrides an earlier unrelated task error."""
    dispatcher = RecordingDispatcher()
    tool = SpawnSubAgentsTool.build(pool=dispatcher)
    unrelated = {"task_id": "missing-prompt", "task_summary": "Compare repository rules"}
    summary = {"task_id": "missing-summary", "prompt": "Review child identity"}
    tasks = [summary, unrelated] if summary_first else [unrelated, summary]
    arguments = (
        {"mode": "parallel", "tasks_json": json.dumps(tasks)}
        if legacy
        else {"mode": "parallel", "tasks": tasks}
    )
    result = json.loads(await tool.ainvoke(arguments))
    if summary_first:
        assert result == {"error": ERROR}
    else:
        assert result["error"] != ERROR
        assert "prompt" in result["error"]
        assert "Field required" in result["error"]
    assert dispatcher.calls == []


@pytest.mark.parametrize("legacy", [False, True])
async def test_valid_summary_keeps_original_prompt(legacy: bool) -> None:
    """Normalization changes the label only, never the execution prompt."""
    dispatcher = RecordingDispatcher()
    tool = SpawnSubAgentsTool.build(pool=dispatcher)
    prompt = "Read AGENTS.md.\nPlease compare the branch naming rules with repository policy.\nDo not commit."
    tasks = [
        {
            "task_id": "compare",
            "prompt": prompt,
            "task_summary": "  Compare branch naming rules with repository policy\n",
        }
    ]
    arguments = (
        {"mode": "single", "tasks_json": json.dumps(tasks)} if legacy else {"mode": "single", "tasks": tasks}
    )
    await tool.ainvoke(arguments)
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0][0].prompt == prompt
    assert dispatcher.calls[0][0].task_summary == "Compare branch naming rules with repository policy"


@pytest.mark.parametrize(
    ("fields", "kind"),
    [
        ({}, "missing"),
        ({"task_summary": None}, "value_error"),
        ({"task_summary": True}, "value_error"),
        ({"task_summary": "a " + "b" * 95}, "value_error"),
    ],
)
def test_task_summary_validation_locations(fields: dict[str, object], kind: str) -> None:
    """Direct DAO callers see the exact summary location, not a nested task path."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        SubAgentTaskDAO(task_id="check", prompt="Compare rules", **fields)
    errors = error.value.errors(include_url=False, include_context=False, include_input=False)
    assert [(item["loc"], item["type"]) for item in errors] == [(("task_summary",), kind)]


def test_schema_and_prompt_require_authored_summary() -> None:
    """Dictionary-shaped live schemas advertise the required nested input explicitly."""
    from src.agents.slo_agent.orchestrator.spawn_tool import (
        SpawnSubAgentsSchemaDAO,
        DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
        ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
    )

    for field in ("tasks", "tasks_json"):
        assert "task_summary" in SpawnSubAgentsSchemaDAO.model_fields[field].description
    for prompt in (DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT, ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM):
        assert "For every task, author task_summary from its actual assigned work" in prompt
