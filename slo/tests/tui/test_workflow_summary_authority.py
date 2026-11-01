"""Summary authority over real legacy and incarnation-bound observation files."""

from pathlib import Path

import pytest

from src.agents.slo_agent.orchestrator.task_preview import TASK_SUMMARY_FALLBACK
from tests.tui.test_workflow_visualizer_loader import (
    _Layout,
    _PARENT,
    _EXEC_A,
    _EXEC_B,
    _observer,
    _status,
)


def file_snapshot(*, root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Capture bytes, modes and modification times to forbid observation repairs."""
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "matching",
        "missing-context",
        "corrupt-context",
        "missing-summary",
        "invalid-tag",
        "missing-fleet",
        "corrupt-fleet",
        "legacy-prefix",
        "unlabeled-missing-context",
    ],
)
async def test_summary_authority_is_local_and_read_only(tmp_path: Path, modern: bool, mutation: str) -> None:
    """Only admitted tag or complete explicit legacy text can describe a task."""
    layout = _Layout(root=tmp_path)
    prompt = "Read AGENTS.md.\nTask: Compare repository branch policy\nDo not commit."
    label = "Contrast [branch] commit and spawn policies"
    if modern:
        layout.running_child(child="child", execution_id=_EXEC_A, prompt=prompt)
    else:
        layout.context(child="child", prompt=prompt)
    preview = "Task summary v1: " + label
    if mutation == "missing-summary":
        preview = "Read AGENTS.md..."
    if mutation == "invalid-tag":
        preview = "Task summary v1: Complete task"
    if mutation == "legacy-prefix":
        preview = "Goal: Compare repository branch policy\n"
    if mutation == "unlabeled-missing-context":
        preview = "Read AGENTS.md..."
    layout.fleet(
        entries=[_status(child="child", execution_id=_EXEC_A if modern else "", preview=preview)],
        run_id=None if not modern else "11111111-1111-4111-8111-111111111111",
    )
    context = tmp_path / _PARENT / "children" / "child" / "spawn_context.json"
    fleet = tmp_path / _PARENT / "fleet.json"
    if mutation in {"missing-context", "unlabeled-missing-context"}:
        context.unlink()
    if mutation == "corrupt-context":
        context.write_text("{broken")
    if mutation == "missing-fleet":
        fleet.unlink()
    if mutation == "corrupt-fleet":
        fleet.write_text("{broken")
    before = file_snapshot(root=tmp_path)
    group = await _observer(root=tmp_path).load_observation_group()
    assert file_snapshot(root=tmp_path) == before
    if mutation == "corrupt-fleet":
        assert group.availability == "unavailable"
        assert not group.children
        return
    child = group.children[0]
    expected = (
        "Compare repository branch policy"
        if mutation in {"missing-summary", "invalid-tag", "missing-fleet", "legacy-prefix"}
        else label
    )
    if mutation == "unlabeled-missing-context":
        expected = TASK_SUMMARY_FALLBACK
    assert child.task_summary == expected
    assert child.task_text_complete == (
        mutation not in {"missing-context", "corrupt-context", "unlabeled-missing-context"}
    )
    if child.task_text_complete:
        assert child.task_text == prompt


@pytest.mark.parametrize(
    "mutation", ["wrong-execution", "missing-index", "corrupt-index", "index-ahead", "context-replaced"]
)
async def test_new_incarnation_never_inherits_old_summary(tmp_path: Path, mutation: str) -> None:
    """Missing or crossed publication evidence must not label a new execution with old work."""
    layout = _Layout(root=tmp_path)
    old_prompt = "Task: Delete obsolete branch records\n"
    old_label = "Delete obsolete branch records"
    new_label = "Audit current commit policy"
    layout.running_child(child="child", execution_id=_EXEC_A, prompt=old_prompt)
    layout.fleet(
        entries=[_status(child="child", execution_id=_EXEC_A, preview="Task summary v1: " + old_label)]
    )
    fleet_path = tmp_path / _PARENT / "fleet.json"
    old_fleet = fleet_path.read_bytes()
    layout.fleet(
        entries=[_status(child="child", execution_id=_EXEC_B, preview="Task summary v1: " + new_label)]
    )
    index = tmp_path / _PARENT / "execution-index.v1.json"
    if mutation == "index-ahead":
        # Exact writer interruption: new index is durable but old fleet is still active.
        fleet_path.write_bytes(old_fleet)
    if mutation == "missing-index":
        index.unlink()
    if mutation == "corrupt-index":
        index.write_text("{broken")
    if mutation == "context-replaced":
        layout.context(child="child", prompt="Task: Forged unrelated assignment\n", execution_id=_EXEC_B)
    before = file_snapshot(root=tmp_path)
    group = await _observer(root=tmp_path).load_observation_group()
    assert file_snapshot(root=tmp_path) == before
    if mutation == "corrupt-index":
        assert group.availability == "unavailable"
        return
    child = group.children[0]
    assert old_label not in child.task_summary
    assert old_prompt not in child.task_text
    assert "Forged" not in child.task_summary
    assert not child.task_text_complete
    assert child.task_summary == (
        TASK_SUMMARY_FALLBACK if mutation in {"index-ahead", "missing-index"} else new_label
    )
