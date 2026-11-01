"""Strict viewer wire decoding and one-shot lifetime tests."""

import json
from pathlib import Path
from src.agents.slo_agent.herdr.dao import HerdrVisualizerAttemptDAO, HerdrViewerOperation, HerdrCommandStatus
from tests.agents.slo_agent.herdr.test_viewer_authority_closure import active_reporter

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCommandOutcomeDAO, HerdrCommandResultDAO
from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher, HerdrViewerAdmission


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
def test_builder_rejects_invalid_identity(tmp_path: Path, operation: HerdrViewerOperation) -> None:
    """Reject ordinary slugs before constructing any viewer command."""
    viewer = active_reporter(root=tmp_path).build_visualizer()
    with pytest.raises(ValueError, match="Invalid workflow identity"):
        viewer._viewer_command(
            parent_session_id="ordinary-slug",
            operation=operation,
            attempt=HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2"),
        )


@pytest.mark.parametrize(argnames="operation", argvalues=["rename", "run"])
def test_builder_rejects_missing_pane(tmp_path: Path, operation: HerdrViewerOperation) -> None:
    """Never construct input or label commands without a validated destination."""
    viewer = active_reporter(root=tmp_path).build_visualizer()
    with pytest.raises(ValueError, match="Missing viewer pane"):
        viewer._viewer_command(
            parent_session_id="a81d92fa-7a2e-4ccd-9975-445832a91d5e",
            operation=operation,
            attempt=HerdrVisualizerAttemptDAO(state="split_attempted"),
        )


@pytest.mark.parametrize(argnames="admit", argvalues=[False, True])
def test_completion_guards_preserve_reservation(tmp_path: Path, admit: bool) -> None:
    """Never-admitted and repeated completions cannot replace or renew the ledger."""
    viewer = active_reporter(root=tmp_path).build_visualizer()
    parent = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"
    attempt = HerdrVisualizerAttemptDAO(state="split_attempted")
    viewer._attempt_by_parent[parent] = attempt
    admission = HerdrViewerAdmission(
        launcher=viewer,
        parent_session_id=parent,
        attempt=attempt,
        operation="split",
    )
    if admit:
        assert admission.try_admit()
    retained = viewer._attempt_by_parent[parent]
    result = HerdrCommandResultDAO(outcome=HerdrCommandOutcomeDAO(status="timeout"))
    admission.complete(result=result)
    assert admission._completed is admit
    admission.complete(result=result)
    assert viewer._attempt_by_parent[parent] is retained
    assert retained.admitted_operations == (frozenset({"split"}) if admit else frozenset())
    if admit:
        assert not admission.try_admit()


def test_viewer_commands(tmp_path: Path) -> None:
    """Commands use captured owner and a single fixed plain-slo run string."""
    owner = active_reporter(root=tmp_path)
    viewer = owner.build_visualizer()
    parent = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"
    attempt = HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2")
    expected: dict[HerdrViewerOperation, tuple[str, ...]] = {
        "split": ("pane", "split", "--pane", owner._config.pane_id, "--direction", "right", "--no-focus"),
        "rename": ("pane", "rename", "pane-2", "Slo workflow a81d92fa"),
        "run": ("pane", "run", "pane-2", f"slo visualize --session {parent} --follow"),
    }
    for operation, argv in expected.items():
        command = viewer._viewer_command(parent_session_id=parent, operation=operation, attempt=attempt)
        assert command.argv == argv
        assert command.capture_json is (operation == "split")


@pytest.mark.parametrize(
    argnames="payload,expected",
    argvalues=[
        ({"result": {"pane": {"pane_id": "pane-2"}}}, "pane-2"),
        ({"result": {"pane": {"pane_id": "é" * 64}}, "extra": True}, "é" * 64),
        ({"result": {"pane": {"pane_id": "é" * 65}}}, None),
        ({"result": {"pane": {"pane_id": ""}}}, None),
        ({"result": {"pane": {"pane_id": "bad\n"}}}, None),
        ({"result": {"pane": {"pane_id": "bad\u200b"}}}, None),
        ({"result": {"pane": {"pane_id": "\ud800"}}}, None),
        ({"result": {"pane": {"pane_id": 42}}}, None),
        ({"result": {"pane": {"pane_id": True}}}, None),
        ({"error": "bad", "result": {"pane": {"pane_id": "pane-2"}}}, None),
        ({"pane_id": "pane-2"}, None),
        ({"result": {"pane": []}}, None),
        ({"result": []}, None),
        ([], None),
        (None, None),
    ],
)
def test_split_parser(payload: object, expected: str | None) -> None:
    """Only the documented envelope and byte-bounded control-free ID are accepted."""
    result = HerdrCommandResultDAO(
        outcome=HerdrCommandOutcomeDAO(status="ok"),
        json_bytes=json.dumps(payload).encode(),
        admitted=True,
    )
    assert HerdrVisualizerLauncher._parse_split_pane_id(result=result) == expected


@pytest.mark.parametrize(argnames="raw", argvalues=[None, b"{", b"\xff", b""])
def test_split_parser_invalid_json(raw: bytes | None) -> None:
    """Absent, malformed and non-UTF8 stdout cannot become a run target."""
    result = HerdrCommandResultDAO(outcome=HerdrCommandOutcomeDAO(status="ok"), json_bytes=raw)
    assert HerdrVisualizerLauncher._parse_split_pane_id(result=result) is None


@pytest.mark.parametrize(argnames="status", argvalues=["suppressed", "timeout", "unavailable", "rejected"])
def test_split_parser_failed_result(status: HerdrCommandStatus) -> None:
    """Failed transport results never carry a usable pane."""
    result = HerdrCommandResultDAO(outcome=HerdrCommandOutcomeDAO(status=status))
    assert HerdrVisualizerLauncher._parse_split_pane_id(result=result) is None
