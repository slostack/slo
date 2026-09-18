"""Characterize current Textual interactive and overlay behavior through terminal PTYs."""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path
from typing import TypedDict

from tests.characterization.baseline_contract import BaselineComparator
from tests.characterization.capture import baseline_case, canonical_json_bytes, loaded_baseline_ledger
from tests.characterization.normalizers import normalize_baseline_capture
from tests.characterization.textual_pty import PtyInputStepDAO, PtyTerminalCaptureDAO, TextualPtyCapture
from tests.characterization.tui_v2_79_b2_child_bootstrap import (
    PtyChildCommandDAO,
    REPLAY_ANSWER_MARKER,
    REPLAY_REASONING_MARKER,
    build_child_command,
    load_child_external_effects,
)

_LIVE_FIXTURE_PATH: Path = Path("tests/fixtures/79_tui_v2/baseline/tui/live_replay_queue_copy.json")
_OVERLAY_FIXTURE_PATH: Path = Path("tests/fixtures/79_tui_v2/baseline/tui/auth_diff_tree_fleet_workflow.json")
_LIVE_CASE_ID: str = "tui-live-replay-queue-copy"
_OVERLAY_CASE_ID: str = "tui-auth-diff-tree-fleet-workflow"
_OVERLAY_REQUIRED_MARKERS: tuple[str, ...] = (
    "AuthenticationScreen",
    "GitDiffScreen",
    "tree format: markdown; root kind: session; root children: 1",
    "⊇ task-1: spawned",
    "⊇ Opened workflow visualizer in a new window (session orch-1).",
    "workflow wf-1: launching",
)
_OVERLAY_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "credential_lookup_attempt",
    "provider_attempt",
    "network_attempt",
)


class _LivePtyRawCapture(TypedDict):
    """Represent the raw terminal metadata retained by the baseline fixture."""

    osc52_base64: str
    osc52_sha256: str


class _LivePtyCapture(TypedDict):
    """Represent the stable parsed PTY capture shape before normalization."""

    cursor: dict[str, int]
    frame: list[str]
    markers: list[str]
    raw: _LivePtyRawCapture
    written_inputs_base64: list[str]


class _LiveTerminalCapture(TypedDict):
    """Represent the complete real-child live terminal evidence."""

    child: dict[str, object]
    effects: list[dict[str, str | None]]
    pty: _LivePtyCapture


class _OverlayPtyCapture(TypedDict):
    """Represent complete parsed PTY evidence for the overlay child."""

    forbidden_markers: list[str]
    required_markers: list[str]
    written_inputs_base64: list[str]


class _OverlayTerminalCapture(TypedDict):
    """Represent genuine child effects and terminal evidence for the overlay case."""

    child: dict[str, object]
    effects: list[dict[str, str | None]]
    pty: _OverlayPtyCapture


async def test_live_replay_queue_and_copy_match_baseline(tmp_path: Path) -> None:
    """Freeze bootstrap-injected live/replay, queue, copy, and terminal lifecycle.

    WHAT: Drives a real CLI/Textual process after an explicit test-only bootstrap
        injects its session, replay, and copy collaborators. It proves mount,
        terminal input, and lifecycle routing, not unpatched production events.
    WHO: Presentation replacement work compares this isolated interaction fixture.
    WHEN: Before any candidate terminal presentation is introduced.
    """
    child_command = build_child_command(
        scenario="live_replay_queue_copy",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )
    effects_root: Path = child_command.effects_path.parent
    terminal = await TextualPtyCapture.invoke(
        command=child_command.argv,
        cwd=Path.cwd(),
        environment=child_command.environment,
        isolated_environment=True,
        input_steps=(
            PtyInputStepDAO(value=b"first\r", input_after_path=effects_root / "child-ready"),
            PtyInputStepDAO(value=b"queued stale\r", input_after_path=effects_root / "first-started"),
            PtyInputStepDAO(
                value=b"queued latest\r",
                input_after_path=effects_root / "queued-stale-accepted",
            ),
            PtyInputStepDAO(value=b"\x03", input_after_path=effects_root / "queued-latest-accepted"),
            PtyInputStepDAO(
                value=b"\x1b[99;6u",
                input_after_path=effects_root / "queued-latest-completed",
            ),
            PtyInputStepDAO(value=b"\x03", input_after_path=effects_root / "copy-completed"),
        ),
        terminal_height=30,
        terminal_width=100,
        timeout_seconds=10.0,
    )
    terminal_capture: _LiveTerminalCapture = _capture_live_terminal_boundary(
        child_command=child_command,
        terminal=terminal,
    )
    observed: bytes = normalize_baseline_capture(
        capture=canonical_json_bytes(value=terminal_capture),
        case_id=_LIVE_CASE_ID,
    )
    expected: bytes = _LIVE_FIXTURE_PATH.read_bytes()
    BaselineComparator.compare(
        case=baseline_case(case_id=_LIVE_CASE_ID, artifact_relative_path="tui/live_replay_queue_copy.json"),
        observed=observed,
        expected=expected,
        ledger=loaded_baseline_ledger(),
    )


async def test_auth_diff_tree_fleet_and_workflow_match_baseline(tmp_path: Path) -> None:
    """Freeze bootstrap-injected overlay routing through the real CLI/Textual lifecycle.

    WHAT: Drives a closed test-only overlay scenario through ``python -m src.cli``
        after explicitly injecting its session and external collaborators. It
        proves terminal lifecycle routing, not unpatched public child effects.
    WHO: The b.2 migration gate for the isolated overlay characterization.
    WHEN: Before replacing the legacy Textual presentation implementation.

    Args:
        tmp_path (Path): Isolated child root for effects and readiness evidence.
    """
    child_command = build_child_command(
        scenario="auth_diff_tree_fleet_workflow",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )
    effects_root: Path = child_command.effects_path.parent
    terminal = await TextualPtyCapture.invoke(
        command=child_command.argv,
        cwd=Path.cwd(),
        environment=child_command.environment,
        isolated_environment=True,
        input_steps=(
            PtyInputStepDAO(value=b"overlay\r", input_after_path=effects_root / "child-ready"),
            PtyInputStepDAO(value=b"\x03", input_after_path=effects_root / "overlay-completed"),
        ),
        terminal_height=30,
        terminal_width=100,
        timeout_seconds=10.0,
    )
    terminal_capture: _OverlayTerminalCapture = _capture_overlay_terminal_boundary(
        child_command=child_command,
        terminal=terminal,
    )
    observed: bytes = normalize_baseline_capture(
        capture=canonical_json_bytes(value=terminal_capture),
        case_id=_OVERLAY_CASE_ID,
    )
    expected: bytes = _OVERLAY_FIXTURE_PATH.read_bytes()
    BaselineComparator.compare(
        case=baseline_case(
            case_id=_OVERLAY_CASE_ID, artifact_relative_path="tui/auth_diff_tree_fleet_workflow.json"
        ),
        observed=observed,
        expected=expected,
        ledger=loaded_baseline_ledger(),
    )


def _capture_overlay_terminal_boundary(
    *,
    child_command: PtyChildCommandDAO,
    terminal: PtyTerminalCaptureDAO,
) -> _OverlayTerminalCapture:
    """Capture bootstrap-injected overlay markers and effects from a CLI child.

    Args:
        child_command (PtyChildCommandDAO): Exact CLI child command and test-effect path.
        terminal (PtyTerminalCaptureDAO): Unfiltered PTY output and pyte terminal state.

    Returns:
        _OverlayTerminalCapture: JSON-safe full terminal proof before the one normalizer call.
    """
    effects = load_child_external_effects(path=child_command.effects_path)
    raw_text: str = terminal.raw_bytes.decode("utf-8", errors="replace")
    rendered_text: str = "\n".join([*terminal.frame, *terminal.scrollback])
    assert terminal.raw_bytes, "overlay child must emit raw terminal bytes"
    assert raw_text or rendered_text, "overlay child must expose terminal evidence"
    for marker in _OVERLAY_REQUIRED_MARKERS:
        assert (
            marker in raw_text or marker in rendered_text
        ), f"PTY terminal omitted required marker: {marker}"
    for marker in _OVERLAY_FORBIDDEN_MARKERS:
        assert (
            marker not in raw_text and marker not in rendered_text
        ), f"PTY terminal emitted forbidden marker: {marker}"
    assert terminal.child.command == child_command.argv
    assert terminal.child.reaped is True
    assert terminal.child.return_code == 0
    assert terminal.child.cleanup_signals == ()
    assert terminal.written_inputs == (b"overlay\r", b"\x03")
    assert terminal.written_input == b"".join(terminal.written_inputs)
    assert terminal.raw.base64 == base64.b64encode(terminal.raw_bytes).decode("ascii")
    assert terminal.raw.length == len(terminal.raw_bytes)
    assert terminal.raw.sha256 == hashlib.sha256(terminal.raw_bytes).hexdigest()
    assert terminal.scrollback, "overlay child must retain nonempty complete scrollback evidence"
    assert 0 <= terminal.cursor_column < 100
    assert 0 <= terminal.cursor_row < 30
    assert (child_command.effects_path.parent / "overlay-completed").is_file()
    effect_kinds: list[str] = [effect.kind for effect in effects]
    assert effect_kinds[:3] == ["session_injected", "provider_injected", "auth_screen_shown"]
    assert [effect.text for effect in effects if effect.kind == "auth_screen_shown"] == [
        "AuthenticationScreen"
    ]
    assert not [
        effect
        for effect in effects
        if effect.kind in {"credential_lookup_attempt", "provider_attempt", "network_attempt"}
    ]
    return {
        "child": {
            "command": ["<PYTHON>", "-m", "src.cli"],
            "environment": {
                key: child_command.environment[key]
                for key in sorted(child_command.environment)
                if key
                in {
                    "LC_ALL",
                    "LANG",
                    "SLO_79_TUI_V2_B2_SCENARIO",
                    "SLO_AUTO_VISUALIZE",
                    "SLO_ENV",
                    "SLO_LOG_LEVEL",
                    "SLO_PLUGINS_DISABLED",
                    "TERM",
                }
            },
            "reaped": terminal.child.reaped,
            "return_code": terminal.child.return_code,
        },
        "effects": [{"kind": effect.kind, "text": effect.text} for effect in effects],
        "pty": {
            "forbidden_markers": list(_OVERLAY_FORBIDDEN_MARKERS),
            "required_markers": list(_OVERLAY_REQUIRED_MARKERS),
            "written_inputs_base64": [
                base64.b64encode(value).decode("ascii") for value in terminal.written_inputs
            ],
        },
    }


def _capture_live_terminal_boundary(
    *,
    child_command: PtyChildCommandDAO,
    terminal: PtyTerminalCaptureDAO,
) -> _LiveTerminalCapture:
    """Capture stable bootstrap-injected terminal and interaction evidence.

    Args:
        child_command (PtyChildCommandDAO): Deterministic CLI command built by the b.2 bootstrap.
        terminal (PtyTerminalCaptureDAO): Genuine PTY output and pyte state.

    Returns:
        _LiveTerminalCapture: JSON-safe terminal and public interaction records.
    """
    effects_path: Path = child_command.effects_path
    command: tuple[str, ...] = child_command.argv
    environment: dict[str, str] = child_command.environment
    effects = load_child_external_effects(path=effects_path)
    raw_text: str = terminal.raw_bytes.decode("utf-8", errors="replace")
    rendered_text: str = "\n".join([*terminal.frame, *terminal.scrollback])
    assert terminal.raw_bytes, "live child must emit raw terminal bytes"
    assert raw_text or rendered_text, "live child must expose terminal evidence"
    required_markers: tuple[str, ...] = (
        REPLAY_REASONING_MARKER,
        REPLAY_ANSWER_MARKER,
        "Queued: queued latest",
    )
    for marker in required_markers:
        assert (
            marker in raw_text or marker in rendered_text
        ), f"PTY terminal omitted required marker: {marker}"
    assert terminal.child.command == command
    assert terminal.child.reaped is True
    assert terminal.child.return_code == 0
    assert terminal.child.cleanup_signals == ()
    assert terminal.written_inputs == (
        b"first\r",
        b"queued stale\r",
        b"queued latest\r",
        b"\x03",
        b"\x1b[99;6u",
        b"\x03",
    )
    assert terminal.written_input == b"".join(terminal.written_inputs)
    assert terminal.raw.base64 == base64.b64encode(terminal.raw_bytes).decode("ascii")
    assert terminal.raw.length == len(terminal.raw_bytes)
    assert len(terminal.raw.sha256) == 64
    assert b"\x1b]52;" in terminal.raw_bytes, "public copy chord did not emit OSC 52"
    assert (
        effects_path.parent / "copy-completed"
    ).is_file(), "public copy chord did not reach the copy action"
    effect_kinds: list[str] = [effect.kind for effect in effects]
    assert effect_kinds[:5] == [
        "session_injected",
        "provider_injected",
        "replay_injected",
        "replay_hydration_awaited",
        "replay_hydration_awaited",
    ]
    assert [effect.text for effect in effects if effect.kind == "replay_hydration_awaited"] == [
        "entries=1",
        "startup_notice_requested",
        "entries=1",
        "startup_notice_requested",
    ]
    assert [effect.text for effect in effects if effect.kind == "prompt_queued"] == [
        "queued stale",
        "queued latest",
        "interrupt_requested",
    ]
    assert [effect.text for effect in effects if effect.kind == "clipboard_copy"] == ["characters=1202"]
    return {
        "child": {
            "environment": {
                key: environment[key]
                for key in sorted(environment)
                if key
                in {
                    "LC_ALL",
                    "LANG",
                    "SLO_79_TUI_V2_B2_SCENARIO",
                    "SLO_AUTO_VISUALIZE",
                    "SLO_ENV",
                    "SLO_PLUGINS_DISABLED",
                    "TERM",
                }
            },
            "reaped": terminal.child.reaped,
            "return_code": terminal.child.return_code,
        },
        "effects": [{"kind": effect.kind, "text": effect.text} for effect in effects],
        "pty": {
            "cursor": {"column": terminal.cursor_column, "row": terminal.cursor_row},
            "frame": _stable_terminal_lines(lines=terminal.frame),
            "markers": list(required_markers),
            "raw": _stable_raw_terminal_capture(value=terminal.raw_bytes),
            "written_inputs_base64": [
                base64.b64encode(value).decode("ascii") for value in terminal.written_inputs
            ],
        },
    }


def _stable_raw_terminal_capture(*, value: bytes) -> _LivePtyRawCapture:
    """Retain the bootstrap-injected OSC-52 terminal effect from child bytes.

    The full raw capture remains in the harness return value and is checked at
    the boundary. It is intentionally not a fixture field because terminal
    redraw traffic is not one of the normalizer's allowed substitutions; this
    characterization makes no raw-frame or PTY-parity claim.

    Args:
        value (bytes): Unfiltered bytes emitted by the actual child PTY.

    Returns:
        _LivePtyRawCapture: Actual OSC-52 bytes and digest.
    """
    osc52_match = re.search(rb"\x1b]52;c;([A-Za-z0-9+/=]+)\x07", value)
    assert osc52_match is not None, "public copy chord did not emit a typed OSC 52 sequence"
    osc52 = osc52_match.group(0)
    return {
        "osc52_base64": base64.b64encode(osc52).decode("ascii"),
        "osc52_sha256": hashlib.sha256(osc52).hexdigest(),
    }


def _stable_overlay_scrollback(*, lines: list[str]) -> list[str]:
    """Retain complete nonempty child scrollback while excluding process warning wrapping.

    Args:
        lines (list[str]): Full pyte history rows from the actual child PTY.

    Returns:
        list[str]: Every nonempty terminal-content row not belonging to startup warnings.
    """
    warning_markers: tuple[str, ...] = (
        "LangChainPendingDeprecationWarning",
        "allowed_objects",
        "from langgraph.checkpoint",
    )
    return [line for line in lines if line.strip() and not any(marker in line for marker in warning_markers)]


def _stable_terminal_lines(*, lines: list[str]) -> list[str]:
    """Project parsed PTY lines to the stable content-bearing baseline shape.

    WHAT: Retains only nonvolatile visible text after pyte has already applied
        terminal control bytes; decorative cursor and animation glyphs are not
        user-content behavior and change between otherwise identical renders.
    WHO: The two PTY baseline tests call it while assembling their fixture value.
    WHEN: After raw terminal bytes have been parsed and before direct normalization.

    Args:
        lines (list[str]): Parsed frame or scrollback lines from pyte.

    Returns:
        list[str]: Stable visible text rows in their original terminal order.
    """
    return [
        line.rstrip()
        for line in lines
        if line.strip()
        and not any(marker in line for marker in ("⭘", "▄▄", "▅▅", "▏^p palette", "──u", " │ u", " │   "))
    ]
