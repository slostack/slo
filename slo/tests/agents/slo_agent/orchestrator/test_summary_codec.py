"""Authored summary policy and bounded legacy extraction."""

import pytest

from src.agents.slo_agent.orchestrator.task_preview import TaskPreview

FALLBACK = "Task summary unavailable — open details"
PREFIX = "Task summary v1: "
ERROR = "task_summary must describe the assigned work in 1–96 characters; include an operation and concrete subject."


@pytest.mark.parametrize(
    "label",
    [
        "Compare branch naming rules with repository policy",
        "Résumer le rapport de déploiement",
        "Audit [commit] and spawn boundaries",
        "Resolve family 98 visibility and summary contract gaps",
        "Summarize the supplied text",
        "Shorten the supplied summary without changing meaning",
        "a " + "b" * 93,
        "a " + "b" * 94,
    ],
)
def test_authored_labels_are_complete(label: str) -> None:
    """Meaningful fixture labels survive the carrier without clipping."""
    assert TaskPreview.validate_summary(task_summary=label) == label
    assert TaskPreview.encode_summary(task_summary=label) == PREFIX + label
    assert (
        TaskPreview.project_summary(prompt_preview=PREFIX + label, task_text="Task: Different assigned work")
        == label
    )


@pytest.mark.parametrize(
    "label",
    [
        "",
        "\x00\x1b",
        "word",
        "a " + "b" * 95,
        " " * 500 + "Compare rules",
        "work on task",
        "Complete Task",
        "follow instructions",
        "return ready",
        "phase task",
        "do the work",
        FALLBACK,
        PREFIX + "Compare rules",
    ],
)
def test_invalid_labels_are_rejected_without_echo(label: str) -> None:
    """Policy failure is fixed and never includes rejected input."""
    with pytest.raises(ValueError) as error:
        TaskPreview.validate_summary(task_summary=label)
    assert str(error.value) == ERROR


def test_normalization_raw_limit_and_bidi() -> None:
    """Raw bounds precede normalization and directional controls disappear."""
    assert TaskPreview.validate_summary(task_summary=" " * 499 + "Compare rules") == "Compare rules"
    assert (
        TaskPreview.validate_summary(task_summary="\u061cCompare\u200e \u202erules\u2069\t[exact]\x1b")
        == "Compare rules [exact]"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Read instructions\nTask: Compare branch rules\nReturn READY", "Compare branch rules"),
        ("goal: Preserve negation and constraints", "Preserve negation and constraints"),
        (
            "```text\nTask: Wrong fenced task\n```\n> Goal: Wrong quoted task\nObjective: Audit spawn boundaries",
            "Audit spawn boundaries",
        ),
        ("~~~\nTask: Wrong fenced task\n~~~\nTask: Review commit rules", "Review commit rules"),
        ("Please review the rules", FALLBACK),
        ("Task: complete task\nTask: Review actual rules", "Review actual rules"),
    ],
)
def test_legacy_explicit_whole_lines(text: str, expected: str) -> None:
    """Only explicit labels outside fences and quotes are legacy evidence."""
    assert TaskPreview.project_summary(prompt_preview="", task_text=text) == expected


def test_scan_and_incomplete_preview_boundaries() -> None:
    """A cut-off line or preview cannot fabricate a complete assignment."""
    label = "Task: Compare branch rules"
    assert TaskPreview.project_summary(prompt_preview=label + "…") == FALLBACK
    assert TaskPreview.project_summary(prompt_preview=label + "...") == FALLBACK
    prefix = "\n" * (16384 - len(label))
    assert TaskPreview.project_summary(prompt_preview="", task_text=prefix + label) == "Compare branch rules"
    assert TaskPreview.project_summary(prompt_preview="", task_text=prefix + label + " more") == FALLBACK
    assert (
        TaskPreview.project_summary(prompt_preview=PREFIX + "complete task", task_text=label)
        == "Compare branch rules"
    )


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\x85", "\u2028", "\u2029"])
def test_complete_legacy_lines_keep_unicode_boundaries(separator: str) -> None:
    """A complete explicit line remains eligible before later instructions."""
    text = separator.join(["Read AGENTS.md", "Task: Compare branch rules", "Return evidence"])
    assert TaskPreview.project_summary(prompt_preview="", task_text=text) == "Compare branch rules"


@pytest.mark.parametrize("terminator_inside", [False, True])
def test_scan_requires_terminator_inside_window(terminator_inside: bool) -> None:
    """Only a newline inside the bounded scan admits a nonfinal explicit line."""
    label = "Task: Compare branch rules"
    padding = "\n" * (16384 - len(label) - int(terminator_inside))
    text = padding + label + "\nReturn evidence"
    expected = "Compare branch rules" if terminator_inside else FALLBACK
    assert TaskPreview.project_summary(prompt_preview="", task_text=text) == expected


@pytest.mark.parametrize(
    "wrapper",
    [
        "````text\nTask: Wrong fenced task\n```\nGoal: Wrong fenced goal\n````\n",
        "~~~text\nTask: Wrong fenced task\n```\nGoal: Wrong fenced goal\n~~~\n",
        "> Task: Wrong quoted task\n  > Goal: Wrong quoted goal\n",
    ],
)
def test_fences_and_quotes_do_not_supply_task_labels(wrapper: str) -> None:
    """Shorter or different fences cannot expose hidden candidate labels."""
    assert (
        TaskPreview.project_summary(
            prompt_preview="", task_text=wrapper + "Objective: Audit spawn boundaries"
        )
        == "Audit spawn boundaries"
    )


@pytest.mark.parametrize("boilerplate_first", [False, True])
def test_boilerplate_position_does_not_change_explicit_work(boilerplate_first: bool) -> None:
    """Legacy extraction uses explicit work rather than orchestration prose."""
    boilerplate = "You own Step 1. Read AGENTS.md.\nDo not commit or spawn agents.\nReturn READY."
    work = "Task: Fix workflow dismissal refresh races"
    text = boilerplate + "\n" + work if boilerplate_first else work + "\n" + boilerplate
    assert TaskPreview.project_summary(prompt_preview="", task_text=text) == (
        "Fix workflow dismissal refresh races"
    )
    assert TaskPreview.project_summary(prompt_preview="", task_text=boilerplate) == FALLBACK


@pytest.mark.parametrize(
    "control",
    ["\u061c", "\u200e", "\u200f", *map(chr, range(0x202A, 0x202F)), *map(chr, range(0x2066, 0x206A))],
)
def test_each_directional_control_is_removed(control: str) -> None:
    """Every prohibited directional control is removed without changing words."""
    assert (
        TaskPreview.validate_summary(task_summary=f"Compare{control} branch rules") == "Compare branch rules"
    )


@pytest.mark.parametrize("codepoint", [*range(0, 9), *range(14, 32), *range(127, 160)])
def test_summary_removes_each_non_whitespace_control(codepoint: int) -> None:
    """Every stripped C0/C1 code point preserves the authored words."""
    control = chr(codepoint)
    assert (
        TaskPreview.validate_summary(task_summary=f"Compare{control} branch rules") == "Compare branch rules"
    )


@pytest.mark.parametrize(
    "label",
    [
        "Resolve family 98 visibility and summary contract gaps",
        "Summarize the supplied text",
        "Shorten the supplied summary without changing meaning",
        "Compare branch naming rules with repository policy",
    ],
)
@pytest.mark.parametrize("boilerplate_first", [False, True])
def test_authored_pair_ignores_boilerplate_order(label: str, boilerplate_first: bool) -> None:
    """All required operation/subject pairs survive movement of orchestration instructions."""
    boilerplate = "Read AGENTS.md. Do not commit or spawn. Return READY."
    prompt = f"{boilerplate}\nTask: {label}" if boilerplate_first else f"Task: {label}\n{boilerplate}"
    assert (
        TaskPreview.project_summary(
            prompt_preview=TaskPreview.encode_summary(task_summary=label), task_text=prompt
        )
        == label
    )
