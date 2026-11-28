"""CLI journey acceptance tests for `slo schedule` (111.a.1 A1, A2, A3, A13, A14)."""

import json
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from src.cli.app import app
from src.cli.schedule_commands import schedule_app

runner: CliRunner = CliRunner()


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the schedule database into a test-local directory."""
    db_dir: Path = tmp_path / "schedules"
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(db_dir))
    return db_dir / "schedules.db"


def _invoke(*arguments: str) -> Any:
    """Run one CLI command and return the parsed result."""
    return runner.invoke(app, list(arguments))


def _add_interval(*, name: str = "Daily Summary") -> Any:
    """Add one fresh interval schedule through the mounted CLI."""
    return _invoke(
        "schedule",
        "add",
        "--name",
        name,
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "60",
    )


def _show_json(*, schedule: str) -> dict[str, Any]:
    """Show one schedule as JSON and return the parsed object."""
    result = _invoke("schedule", "show", "--schedule", schedule, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _utc_now() -> datetime:
    """Return the current UTC instant (boundary clock)."""
    return datetime.now(timezone.utc)


def test_add_interval_schedule_persists_row_and_next_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1: add persists one row; the printed id matches the row id and next due is created_at + interval."""
    db_path: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

    result = _add_interval()
    assert result.exit_code == 0, result.output
    printed_id: str = result.output.splitlines()[0].strip()
    assert "Mode: fresh" in result.output

    shown: dict[str, Any] = _show_json(schedule=printed_id)
    assert shown["id"] == printed_id
    assert shown["name"] == "Daily Summary"
    assert shown["name_key"] == "daily-summary"
    assert shown["session_mode"] == "fresh"
    assert shown["session_reference"] is None
    assert shown["enabled"] is True
    assert shown["deleted_at"] is None
    created_at: datetime = datetime.fromisoformat(shown["created_at"].replace("Z", "+00:00"))
    next_due_at: datetime = datetime.fromisoformat(shown["next_due_at"].replace("Z", "+00:00"))
    assert next_due_at - created_at == timedelta(seconds=60)

    # EF111-07: the store holds exactly one row — count it, do not just read one back.
    connection: sqlite3.Connection = sqlite3.connect(db_path)
    try:
        row_count: int = int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
    finally:
        connection.close()
    assert row_count == 1

    assert db_path.exists()
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    # OPS111-01 amends the old "add never touches channels" assertion: add now
    # starts the shared worker, whose engine opens the channel store itself.
    assert "Worker: healthy" in result.output


def test_add_continuous_schedule_persists_session_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 continuous variant: the stored session reference and coalescing key match the flags."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

    result = _invoke(
        "schedule",
        "add",
        "--name",
        "Repo Watch",
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "3600",
        "--session-mode",
        "continuous",
        "--session-reference",
        "release-prep",
        "--coalescing-mode",
        "latest_by_key",
        "--coalescing-key",
        "repo-watch",
    )
    assert result.exit_code == 0, result.output
    printed_id: str = result.output.splitlines()[0].strip()

    shown: dict[str, Any] = _show_json(schedule=printed_id)
    assert shown["session_mode"] == "continuous"
    assert shown["session_reference"] == "release-prep"
    assert shown["coalescing_mode"] == "latest_by_key"
    assert shown["coalescing_key"] == "repo-watch"


def test_add_one_shot_and_cron_persist_their_triggers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-shot and cron adds store their trigger kind and a computed next due."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    run_at: datetime = (_utc_now() + timedelta(hours=1)).replace(microsecond=0)

    one_shot = _invoke(
        "schedule",
        "add",
        "--name",
        "One Shot",
        "--prompt",
        "Run once",
        "--run-at",
        run_at.isoformat(),
    )
    assert one_shot.exit_code == 0, one_shot.output
    shown: dict[str, Any] = _show_json(schedule=one_shot.output.splitlines()[0].strip())
    assert shown["trigger"]["kind"] == "one_shot"
    assert datetime.fromisoformat(shown["next_due_at"].replace("Z", "+00:00")) == run_at

    cron = _invoke(
        "schedule",
        "add",
        "--name",
        "Cron Watch",
        "--prompt",
        "Watch",
        "--cron",
        "*/5 * * * *",
    )
    assert cron.exit_code == 0, cron.output
    shown = _show_json(schedule=cron.output.splitlines()[0].strip())
    assert shown["trigger"]["kind"] == "cron"
    assert shown["trigger"]["expression"] == "*/5 * * * *"
    assert shown["next_due_at"] is not None


def test_add_and_edit_persist_cwd_and_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """EF111-01: --cwd and --model persist through add and edit and read back from the store."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

    added = _invoke(
        "schedule",
        "add",
        "--name",
        "Pinned Fresh",
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "60",
        "--cwd",
        "/tmp/scheduler-runs",
        "--model",
        "openrouter:vendor/schedule-only",
    )
    assert added.exit_code == 0, added.output
    schedule_id: str = added.output.splitlines()[0].strip()
    shown: dict[str, Any] = _show_json(schedule=schedule_id)
    assert shown["cwd"] == "/tmp/scheduler-runs"
    assert shown["model"] == "openrouter:vendor/schedule-only"

    edited = _invoke(
        "schedule",
        "edit",
        "--schedule",
        schedule_id,
        "--name",
        "Pinned Fresh",
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "60",
        "--cwd",
        "/tmp/second-runs",
    )
    assert edited.exit_code == 0, edited.output
    shown = _show_json(schedule=schedule_id)
    assert shown["cwd"] == "/tmp/second-runs"
    # edit replaces the whole definition, so an omitted --model resets to None.
    assert shown["model"] is None


def _stored_row_count(*, db_path: Path) -> int:
    """Count schedule rows in the real store; an absent file counts as zero."""
    if not db_path.exists():
        return 0
    connection: sqlite3.Connection = sqlite3.connect(db_path)
    try:
        return int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
    finally:
        connection.close()


_INVALID_CREATE_CASES: list[tuple[tuple[str, ...], int, str]] = [
    (("--name", "Sub Floor", "--prompt", "P", "--interval-seconds", "14"), 1, "every_seconds"),
    (("--name", "Past Shot", "--prompt", "P", "--run-at", "PAST"), 1, "future"),
    (("--name", "Naive Shot", "--prompt", "P", "--run-at", "2026-01-01T12:00:00"), 1, "timezone-aware"),
    (("--name", "Long Prompt", "--prompt", "x" * 65537, "--interval-seconds", "60"), 1, "prompt"),
    (("--name", "   ", "--prompt", "P", "--interval-seconds", "60"), 1, "name"),
    (("--name", "No Trigger", "--prompt", "P"), 2, "Exactly one of"),
    (
        ("--name", "Two Triggers", "--prompt", "P", "--interval-seconds", "60", "--cron", "*/5 * * * *"),
        2,
        "Exactly one of",
    ),
    (
        (
            "--name",
            "Fresh Reference",
            "--prompt",
            "P",
            "--interval-seconds",
            "60",
            "--session-reference",
            "r",
        ),
        2,
        "--session-reference requires --session-mode continuous",
    ),
    (
        ("--name", "Fresh Coalesce", "--prompt", "P", "--interval-seconds", "60", "--coalescing-key", "k"),
        2,
        "--coalescing-key requires --session-mode continuous",
    ),
    (
        (
            "--name",
            "Fresh Coalesce Mode",
            "--prompt",
            "P",
            "--interval-seconds",
            "60",
            "--coalescing-mode",
            "latest_by_key",
        ),
        2,
        "--coalescing-mode requires --session-mode continuous",
    ),
]


@pytest.mark.parametrize(
    ("arguments", "expected_exit", "expected_fragment"),
    _INVALID_CREATE_CASES,
)
def test_invalid_create_inputs_print_diagnostics_and_write_no_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: tuple[str, ...],
    expected_exit: int,
    expected_fragment: str,
) -> None:
    """A2/EF111-03: each invalid create prints a safe diagnostic and writes no row."""
    db_path: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    resolved: list[str] = [
        (_utc_now() - timedelta(hours=1)).isoformat() if argument == "PAST" else argument
        for argument in arguments
    ]

    result = _invoke("schedule", "add", *resolved)

    assert result.exit_code == expected_exit, f"{arguments}: {result.output}"
    assert expected_fragment in result.output, f"{arguments}: {result.output}"
    assert "Traceback" not in result.output, f"{arguments}: {result.output}"
    assert _stored_row_count(db_path=db_path) == 0, f"{arguments}: a row was written"


def test_duplicate_active_name_is_rejected_with_one_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2: a duplicate active name exits 1, writes no second row and the original stays readable."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

    result = _add_interval()
    assert result.exit_code == 0, result.output
    schedule_id: str = result.output.splitlines()[0].strip()
    duplicate = _add_interval()
    assert duplicate.exit_code == 1, duplicate.output
    assert "Traceback" not in duplicate.output

    shown: dict[str, Any] = _show_json(schedule=schedule_id)
    assert shown["name"] == "Daily Summary"


def test_invalid_cron_write_no_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A3: an invalid cron expression or unknown timezone is rejected with exit 1 and no row."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

    bad_expression = _invoke("schedule", "add", "--name", "Bad Cron", "--prompt", "P", "--cron", "not a cron")
    assert bad_expression.exit_code == 1, bad_expression.output
    unknown_tz = _invoke(
        "schedule",
        "add",
        "--name",
        "Far Cron",
        "--prompt",
        "P",
        "--cron",
        "*/5 * * * *",
        "--tz",
        "Mars/Olympus",
    )
    assert unknown_tz.exit_code == 1, unknown_tz.output

    listed = _invoke("schedule", "list", "--json")
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output) == []


def test_edit_renames_schedule_selected_by_schedule_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported edit case: --schedule selects the row and --name renames it; --json reads back the change."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval()
    schedule_id: str = added.output.splitlines()[0].strip()

    edited = _invoke(
        "schedule",
        "edit",
        "--schedule",
        schedule_id,
        "--name",
        "Repo Watch",
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "3600",
        "--session-mode",
        "continuous",
        "--session-reference",
        "release-prep",
        "--coalescing-mode",
        "latest_by_key",
        "--coalescing-key",
        "repo-watch",
    )
    assert edited.exit_code == 0, edited.output

    shown: dict[str, Any] = _show_json(schedule=schedule_id)
    assert shown["name"] == "Repo Watch"
    assert shown["prompt"] == "Summarise the repo"
    assert shown["session_reference"] == "release-prep"
    assert shown["coalescing_key"] == "repo-watch"
    assert shown["trigger"]["every_seconds"] == 3600


def test_list_renders_continuous_without_reference_as_fresh_per_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5 part 3 (EF111-A03): a continuous schedule without a reference runs fresh per invocation."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _invoke(
        "schedule",
        "add",
        "--name",
        "Nightly Poll",
        "--prompt",
        "Poll the repo",
        "--interval-seconds",
        "60",
        "--session-mode",
        "continuous",
    )
    assert added.exit_code == 0, added.output

    listed = _invoke("schedule", "list")
    assert listed.exit_code == 0, listed.output
    lines: list[str] = listed.output.strip().splitlines()
    assert len(lines) == 2, listed.output
    assert "Nightly Poll" in lines[1]
    assert "fresh per invocation" in lines[1]
    assert "schedule-owned" not in listed.output


def test_list_prints_renderer_columns_without_os_or_inbox_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported list case: the five renderer columns; no installed or inbox state appears."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval()
    assert added.exit_code == 0, added.output

    listed = _invoke("schedule", "list")
    assert listed.exit_code == 0, listed.output
    lines: list[str] = listed.output.strip().splitlines()
    assert "Name" in lines[0]
    assert "Trigger" in lines[0]
    assert "Next Due" in lines[0]
    assert "Recipient Session" in lines[0]
    assert "Last Status" in lines[0]
    assert "Daily Summary" in lines[1]
    assert "interval:60s" in lines[1]
    assert "installed" not in listed.output
    assert "inbox" not in listed.output


def test_cli_stop_then_start_recomputes_next_due_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SREC-A6 CLI side: stop clears next due through the mounted app; start recomputes from now."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval()
    schedule_id: str = added.output.splitlines()[0].strip()

    stopped = _invoke("schedule", "stop", "--schedule", schedule_id, "--json")
    assert stopped.exit_code == 0, stopped.output
    stopped_row: dict[str, Any] = json.loads(stopped.output)
    assert stopped_row["enabled"] is False
    assert stopped_row["next_due_at"] is None

    started = _invoke("schedule", "start", "--schedule", schedule_id, "--json")
    assert started.exit_code == 0, started.output
    started_row: dict[str, Any] = json.loads(started.output)
    assert started_row["enabled"] is True
    restarted_due: datetime = datetime.fromisoformat(started_row["next_due_at"].replace("Z", "+00:00"))
    assert restarted_due > _utc_now()
    assert restarted_due - _utc_now() < timedelta(seconds=90)


def test_show_prints_schedule_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A13: show prints name, trigger, next due, session mode and session reference."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _invoke(
        "schedule",
        "add",
        "--name",
        "Repo Watch",
        "--prompt",
        "Summarise the repo",
        "--interval-seconds",
        "3600",
        "--session-mode",
        "continuous",
        "--session-reference",
        "release-prep",
    )
    assert added.exit_code == 0, added.output

    shown = _invoke("schedule", "show", "--schedule", "repo watch")
    assert shown.exit_code == 0, shown.output
    assert "Name: Repo Watch" in shown.output
    assert "Trigger: interval:3600s" in shown.output
    assert "Mode: continuous" in shown.output
    assert "Target Session: release-prep" in shown.output
    # EF111-07: the printed next due must agree with the stored instant, not merely exist.
    stored: dict[str, Any] = _show_json(schedule="repo watch")
    printed_due_line: str = next(line for line in shown.output.splitlines() if line.startswith("Next Due: "))
    printed_due: datetime = datetime.fromisoformat(printed_due_line.removeprefix("Next Due: "))
    assert printed_due == datetime.fromisoformat(stored["next_due_at"].replace("Z", "+00:00"))


def test_schedule_reference_resolves_by_id_or_name_among_active_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A14: id or name selects the same active row; unknown names and deleted ids never match."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval(name="Repo Watch")
    schedule_id: str = added.output.splitlines()[0].strip()

    by_id: dict[str, Any] = _show_json(schedule=schedule_id)
    by_name: dict[str, Any] = _show_json(schedule="REPO WATCH")
    assert by_id["id"] == by_name["id"] == schedule_id

    unknown = _invoke("schedule", "show", "--schedule", "unknown-name")
    assert unknown.exit_code == 1, unknown.output

    deleted = _invoke("schedule", "delete", "--schedule", schedule_id, "--yes")
    assert deleted.exit_code == 0, deleted.output
    assert _invoke("schedule", "show", "--schedule", schedule_id).exit_code == 1
    assert _invoke("schedule", "show", "--schedule", "repo watch").exit_code == 1


def test_delete_requires_yes_and_frees_the_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A7: delete without --yes exits 2 and writes nothing; with --yes the name is reusable."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval(name="Repo Watch")
    schedule_id: str = added.output.splitlines()[0].strip()

    refused = _invoke("schedule", "delete", "--schedule", schedule_id)
    assert refused.exit_code == 2, refused.output
    by_id: dict[str, Any] = _show_json(schedule=schedule_id)
    assert by_id["id"] == schedule_id

    deleted = _invoke("schedule", "delete", "--schedule", schedule_id, "--yes")
    assert deleted.exit_code == 0, deleted.output
    assert _invoke("schedule", "show", "--schedule", schedule_id).exit_code == 1

    recreated = _add_interval(name="Repo Watch")
    assert recreated.exit_code == 0, recreated.output
    assert recreated.output.splitlines()[0].strip() != schedule_id


def test_trigger_queues_one_invocation_and_prints_its_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5: trigger creates one pending invocation due now and prints its id; repeat returns the same row."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    added = _add_interval(name="Repo Watch")
    schedule_id: str = added.output.splitlines()[0].strip()

    queued = _invoke("schedule", "trigger", "--schedule", schedule_id)
    assert queued.exit_code == 0, queued.output
    invocation_id: str = queued.output.splitlines()[0].strip()
    assert invocation_id

    missing = _invoke("schedule", "trigger", "--schedule", "ghost")
    assert missing.exit_code == 1, missing.output


def test_worker_command_is_registered_on_the_schedule_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A10: `slo schedule worker` is registered on the single schedule group."""
    _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
    result = _invoke("schedule", "--help")
    assert result.exit_code == 0, result.output
    assert "worker" in result.output


def test_retired_verbs_are_not_registered() -> None:
    """A8: execute, run, install and uninstall are gone; trigger stays registered."""
    command_names: set[str] = {command.name for command in schedule_app.registered_commands if command.name}
    assert "execute" not in command_names
    assert "run" not in command_names
    assert "install" not in command_names
    assert "uninstall" not in command_names
    assert "trigger" in command_names


def _schedule_group_command_names() -> set[str]:
    """Read the single schedule group's command names through the registered app.

    The guard never imports the group's module: it reads the Typer group that
    ``src.cli.app.app`` mounts under the name ``schedule`` (111.a.7 §5.2).
    """
    schedule_infos: list[typer.models.TyperInfo] = [
        info for info in app.registered_groups if info.name == "schedule"
    ]
    assert schedule_infos, "the schedule group must stay registered on src.cli.app.app"
    schedule_group: typer.Typer | None = schedule_infos[0].typer_instance
    assert schedule_group is not None
    return {command.name or "" for command in schedule_group.registered_commands}


def test_schedule_app_registers_only_the_new_verbs() -> None:
    """A2 (B16): the single schedule group registers exactly the new verb set."""
    expected_verbs: frozenset[str] = frozenset(
        {"add", "edit", "show", "list", "trigger", "start", "stop", "delete", "report", "worker", "status"}
    )
    registered_verbs: set[str] = _schedule_group_command_names()
    assert registered_verbs == set(
        expected_verbs
    ), f"registered={sorted(registered_verbs)} expected={sorted(expected_verbs)}"
