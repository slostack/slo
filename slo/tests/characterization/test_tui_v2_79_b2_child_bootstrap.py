"""Focused lifecycle tests for the 79_tui_v2 b.2 real-CLI PTY bootstrap."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.characterization.textual_pty import PtyChildTimeoutError, TextualPtyCapture
from tests.characterization.tui_v2_79_b2_child_bootstrap import (
    CHILD_STARTUP_MARKER,
    ChildExternalEffectCallbacks,
    ChildExternalEffectRecorder,
    REPLAY_ANSWER_MARKER,
    REPLAY_REASONING_MARKER,
    build_child_command,
    build_deterministic_session,
    install_child_external_seams_from_environment,
    load_child_external_effects,
    validate_child_scenario,
)


def _capture_environment(*, tmp_path: Path) -> dict[str, str]:
    """Build an isolated, disposable environment for one real PTY child.

    Args:
        tmp_path (Path): Per-test filesystem root.

    Returns:
        dict[str, str]: Parent-harness overrides for the child command.
    """
    return {
        "HOME": str(tmp_path / "home"),
        "SLO_HOME": str(tmp_path / "slo-home"),
        "SLO_ANTHROPIC_API_KEY": "must-not-reach-child",
        "SLO_KIMI_FOR_CODING_API_KEY": "must-not-reach-child",
        "SLO_OPENAI_API_KEY": "must-not-reach-child",
        "SLO_AUTH_FILE": str(tmp_path / "unreadable-authentication.json"),
    }


def test_validate_child_scenario_when_unknown_rejects_closed_set() -> None:
    """Reject a scenario outside the bootstrap's closed Literal vocabulary."""
    with pytest.raises(ValueError, match="unknown 79_tui_v2 b.2 child scenario"):
        validate_child_scenario(value="unreviewed")


def test_build_child_command_when_requested_constructs_isolated_bootstrap_cli_environment(tmp_path: Path) -> None:
    """Construct an explicit test-bootstrap CLI child without inherited credentials."""
    command = build_child_command(
        scenario="idle_exit",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )

    assert command.argv == (sys.executable, "-m", "src.cli")
    assert command.environment["PYTHONPATH"] == f"{tmp_path / 'python-bootstrap'}{os.pathsep}{Path.cwd()}"
    assert command.environment["HOME"] == str(tmp_path / "home")
    assert command.environment["SLO_HOME"] == str(tmp_path / "slo-home")
    assert command.environment["TERM"] == "xterm-256color"
    assert command.environment["SLO_AUTO_VISUALIZE"] == "0"
    assert command.environment["SLO_79_TUI_V2_B2_TEST_BOOTSTRAP"] == "1"
    preloader: str = (tmp_path / "python-bootstrap" / "sitecustomize.py").read_text(encoding="utf-8")
    assert "SLO_79_TUI_V2_B2_TEST_BOOTSTRAP" in preloader
    assert "== '1'" in preloader
    assert all("API_KEY" not in key for key in command.environment)
    assert "SLO_AUTH_FILE" not in command.environment


async def test_bootstrap_cli_child_when_mounted_exits_cleanly_and_reaps(tmp_path: Path) -> None:
    """Drive an explicitly bootstrap-patched CLI/Textual child to a clean exit.

    The injected session/application collaborators make this a lifecycle test,
    not evidence for unpatched CLI events or external effects.
    """
    child_command = build_child_command(
        scenario="idle_exit",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )

    capture = await TextualPtyCapture.invoke(
        command=child_command.argv,
        cwd=Path.cwd(),
        environment=child_command.environment,
        isolated_environment=True,
        input_after_path=child_command.effects_path.parent / "child-ready",
        input_bytes=(b"\x03",),
        terminal_height=5,
        timeout_seconds=5.0,
    )

    assert capture.child.command == child_command.argv
    assert capture.child.reaped is True
    assert capture.child.return_code == 0
    assert capture.child.cleanup_signals == ()
    assert (child_command.effects_path.parent / "child-ready").read_bytes() == CHILD_STARTUP_MARKER


async def test_real_cli_child_when_credentials_are_present_does_not_lookup_or_use_them(
    tmp_path: Path,
) -> None:
    """Observe the bootstrap record proving injected collaborators avoided credentials."""
    child_command = build_child_command(
        scenario="idle_exit",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )

    await TextualPtyCapture.invoke(
        command=child_command.argv,
        cwd=Path.cwd(),
        environment={**child_command.environment, **_capture_environment(tmp_path=tmp_path)},
        isolated_environment=True,
        input_after_path=child_command.effects_path.parent / "child-ready",
        input_bytes=(b"\x03",),
        terminal_height=5,
        timeout_seconds=5.0,
    )

    effects = load_child_external_effects(path=child_command.effects_path)
    assert [effect.kind for effect in effects] == ["session_injected", "provider_injected"]
    assert not [
        effect
        for effect in effects
        if effect.kind
        in {"credential_lookup_attempt", "provider_attempt", "network_attempt", "launch_attempt"}
    ]


async def test_real_cli_child_when_timeout_occurs_sends_term_then_kill_and_reaps(tmp_path: Path) -> None:
    """Observe bounded TERM, escalation to KILL, and reaping for a bootstrap CLI child."""
    child_command = build_child_command(
        scenario="term_resistant",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )

    with pytest.raises(PtyChildTimeoutError) as error:
        await TextualPtyCapture.invoke(
            command=child_command.argv,
            cwd=Path.cwd(),
            environment=child_command.environment,
            isolated_environment=True,
            input_after_path=child_command.effects_path.parent / "child-ready",
            terminal_height=5,
            timeout_seconds=2.0,
        )

    assert error.value.child.reaped is True
    assert error.value.child.return_code == -signal.SIGKILL
    assert error.value.child.cleanup_signals == ("TERM", "KILL")
    assert [effect.kind for effect in load_child_external_effects(path=child_command.effects_path)][:2] == [
        "session_injected",
        "provider_injected",
    ]


def test_replay_hydration_when_injected_but_not_awaited_has_no_lifecycle_evidence(tmp_path: Path) -> None:
    """Show wiring the replay gateway alone cannot claim a completed mount lifecycle."""
    recorder = ChildExternalEffectRecorder(path=tmp_path / "effects.jsonl")

    session = build_deterministic_session(recorder=recorder, scenario="replay_exit")

    assert callable(session.hydrate_transcript_entries)
    assert [effect.kind for effect in load_child_external_effects(path=tmp_path / "effects.jsonl")] == [
        "session_injected",
        "provider_injected",
        "replay_injected",
    ]


async def test_real_cli_child_when_replay_requested_awaits_and_renders_deterministic_replay(
    tmp_path: Path,
) -> None:
    """Observe bootstrap-injected replay through the real Textual mount lifecycle."""
    child_command = build_child_command(
        scenario="replay_exit",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )

    capture = await TextualPtyCapture.invoke(
        command=child_command.argv,
        cwd=Path.cwd(),
        environment=child_command.environment,
        isolated_environment=True,
        input_after_path=child_command.effects_path.parent / "child-ready",
        input_bytes=(b"\x03",),
        terminal_height=30,
        timeout_seconds=5.0,
    )

    effects = load_child_external_effects(path=child_command.effects_path)
    assert [effect.kind for effect in effects[:3]] == [
        "session_injected",
        "provider_injected",
        "replay_injected",
    ]
    replay_hydration_effects = [effect for effect in effects if effect.kind == "replay_hydration_awaited"]
    assert replay_hydration_effects
    assert {effect.text for effect in replay_hydration_effects} == {"entries=1", "startup_notice_requested"}
    assert capture.child.reaped is True
    assert capture.child.return_code == 0
    rendered_terminal_text = "\n".join([*capture.frame, *capture.scrollback])
    raw_terminal_text = capture.raw_bytes.decode("utf-8", errors="replace")
    for marker in (REPLAY_REASONING_MARKER, REPLAY_ANSWER_MARKER):
        assert marker in raw_terminal_text, f"bootstrap-patched SloTUI mount omitted replay marker: {marker}"
        assert marker in rendered_terminal_text or marker in raw_terminal_text


def test_child_bootstrap_when_sentinel_is_absent_rejects_patch_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject test-bootstrap activation unless the isolated-child sentinel is explicit."""
    monkeypatch.delenv("SLO_79_TUI_V2_B2_TEST_BOOTSTRAP", raising=False)

    with pytest.raises(RuntimeError, match="explicit test sentinel"):
        install_child_external_seams_from_environment()


def test_sitecustomize_when_sentinel_is_absent_does_not_import_bootstrap(tmp_path: Path) -> None:
    """Prove the generated global hook cannot activate patches without the sentinel."""
    command = build_child_command(
        scenario="idle_exit",
        worktree=Path.cwd(),
        temporary_root=tmp_path,
        python_executable=Path(sys.executable),
    )
    environment: dict[str, str] = dict(command.environment)
    environment.pop("SLO_79_TUI_V2_B2_TEST_BOOTSTRAP")
    probe = (
        "import sys; "
        "print('tests.characterization.tui_v2_79_b2_child_bootstrap' in sys.modules)"
    )

    result = subprocess.run(
        args=[sys.executable, "-c", probe],
        capture_output=True,
        check=True,
        cwd=Path.cwd(),
        env=environment,
        text=True,
    )

    assert result.stdout == "False\n"


def test_child_external_effect_callbacks_when_invoked_record_observed_attempts(tmp_path: Path) -> None:
    """Record each observed external-effect path immediately before its local handling."""
    recorder = ChildExternalEffectRecorder(path=tmp_path / "effects.jsonl")

    with pytest.raises(AssertionError, match="credential lookup"):
        ChildExternalEffectCallbacks.block_credential_lookup(recorder=recorder)
    with pytest.raises(AssertionError, match="real provider"):
        ChildExternalEffectCallbacks.block_provider(recorder=recorder)
    with pytest.raises(AssertionError, match="network access"):
        ChildExternalEffectCallbacks.block_network(recorder=recorder)
    assert ChildExternalEffectCallbacks.record_clipboard_copy(recorder=recorder, text="copy") is True
    with pytest.raises(AssertionError, match="external launch"):
        ChildExternalEffectCallbacks.block_launch(recorder=recorder)

    assert [effect.kind for effect in load_child_external_effects(path=tmp_path / "effects.jsonl")] == [
        "credential_lookup_attempt",
        "provider_attempt",
        "network_attempt",
        "clipboard_copy",
        "launch_attempt",
    ]


def test_child_external_effect_records_when_written_are_ordered_and_fail_closed(tmp_path: Path) -> None:
    """Persist deterministic effect records and reject an unrecognized record shape."""
    effects_path = tmp_path / "effects.jsonl"
    recorder = ChildExternalEffectRecorder(path=effects_path)
    recorder.record(kind="session_injected")
    recorder.record(kind="clipboard_copy", text="copied text")

    assert load_child_external_effects(path=effects_path) == [
        recorder.effects[0],
        recorder.effects[1],
    ]

    effects_path.write_text('{"kind":"unexpected","sequence":0}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown child external-effect kind"):
        load_child_external_effects(path=effects_path)
