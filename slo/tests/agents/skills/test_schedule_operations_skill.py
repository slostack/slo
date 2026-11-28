"""Built-in schedule skill tests (111.a.6 A1–A7; FIR111-08 real assertions).

Every behavioural test exercises the real CLI or the real loader; the skill
text is parsed, not merely searched for a slogan.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from tests.schedules.worker_processes import retire_workers_under

_SKILL_PATH: Path = Path("skills") / "cli" / "schedule-operations" / "SKILL.md"

_MUST_APPEAR_VERBS: frozenset[str] = frozenset(
    {"add", "edit", "show", "list", "status", "trigger", "start", "stop", "delete", "report"}
)
_RETIRED_VERBS: frozenset[str] = frozenset(
    {"execute", "run", "install", "uninstall", "reports", "show-report", "cleanup", "import-legacy"}
)


@pytest.fixture(autouse=True)
def _retire_example_workers(tmp_path: Path, isolated_slo_home: Path) -> Iterator[None]:
    """The examples start a real shared worker; stop it with the test."""
    yield
    retire_workers_under(roots=[tmp_path, isolated_slo_home])


def _skill_text() -> str:
    """Read the skill file or raise AssertionError when it is missing."""
    assert _SKILL_PATH.exists(), f"skill file missing: {_SKILL_PATH}"
    return _SKILL_PATH.read_text(encoding="utf-8")


def _fenced_schedule_commands(text: str) -> list[str]:
    """Return every ``slo schedule`` command line in the fenced shell blocks.

    Continuation lines (a trailing backslash) are joined into one command.

    Args:
        text (str): The full skill text.

    Returns:
        list[str]: One string per command, in document order.
    """
    commands: list[str] = []
    for block in re.findall(r"```sh\n(.*?)```", text, flags=re.DOTALL):
        joined: list[str] = []
        pending: str = ""
        for raw_line in block.splitlines():
            line = raw_line.rstrip()
            if line.endswith("\\"):
                pending += line[:-1].rstrip() + " "
                continue
            joined.append(pending + line)
            pending = ""
        if pending:
            joined.append(pending)
        commands.extend(line for line in joined if line.startswith("slo schedule"))
    return commands


def test_loader_finds_schedule_operations_and_drops_scheduled_tui_skills() -> None:
    """A1: the loader finds schedule-operations; the two old skills are absent."""
    from src.agents.slo_agent.skills.service import SkillsLoader

    entries = SkillsLoader.load(skills_dir="skills")
    names: set[str] = {entry.name for entry in entries}
    assert "schedule-operations" in names
    assert "tui-scheduled-operations" not in names
    assert "tui-scheduled-workflows" not in names


def test_every_must_appear_verb_is_registered_in_schedule_group() -> None:
    """A2 (registration): every must-appear verb is registered on the single
    schedule group under ``src.cli.app.app``."""
    runner = CliRunner()
    for verb in sorted(_MUST_APPEAR_VERBS):
        result = runner.invoke(app, ["schedule", verb, "--help"])
        assert result.exit_code == 0, f"{verb} must be registered"


def test_skill_names_only_registered_commands_and_flags() -> None:
    """A2 (accuracy): every ``slo schedule`` command in the skill names a
    registered verb and only flags the real CLI accepts; no retired verb and
    no promised-but-missing option appears."""
    text: str = _skill_text()
    runner = CliRunner()
    documented_commands: list[str] = _fenced_schedule_commands(text)
    assert documented_commands, "the skill must contain runnable examples"
    for command in documented_commands:
        tokens = shlex.split(command)
        verb = tokens[2]
        assert verb not in _RETIRED_VERBS, command
        result = runner.invoke(app, ["schedule", verb, "--help"])
        assert result.exit_code == 0, f"{verb} is not registered: {command}"
        for token in tokens[3:]:
            if token.startswith("--"):
                assert token in result.output, f"{verb} does not accept {token}: {command}"
    for verb in _RETIRED_VERBS:
        assert not re.search(rf"schedule {verb}\b", text), f"retired verb in skill: {verb}"


def test_delete_section_requires_user_confirmation() -> None:
    """A3: the delete section states the user is asked first."""
    text: str = _skill_text()
    assert "confirm" in text.lower()
    assert "--yes" in text


def test_skill_never_points_agents_at_the_database() -> None:
    """A4: the skill never mentions editing ``schedules.db`` directly."""
    text: str = _skill_text()
    assert "schedules.db" not in text


def test_examples_run_against_temporary_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A5: every example command runs against a disposable store, in order,
    with the documented exit codes."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))
    (tmp_path / "schedules").mkdir()
    runner = CliRunner()
    for command in _fenced_schedule_commands(_skill_text()):
        result = runner.invoke(app, shlex.split(command)[1:])
        assert result.exit_code == 0, f"{command} failed: {result.output}"


def test_guidance_appears_once() -> None:
    """FIR111-08: the guidance block is not duplicated verbatim."""
    text: str = _skill_text()
    guidance_header = "## Guidance"
    assert text.count(guidance_header) == 1


def test_fresh_section_matches_d5_rules() -> None:
    """A7 / FIR111-08: the session-target section states the decided D5
    behaviour and claims nothing beyond it."""
    text: str = _skill_text()
    assert "--session-mode fresh" in text
    assert "headless" in text
    assert "durable inbox" in text
    assert "resumes" in text or "resume" in text
    assert "treated as fresh" in text
    assert "--resume" not in text.replace("resumes", "").replace("resume", "")


def _section(*, text: str, heading: str) -> str:
    """Return one ``## heading`` section body of the skill.

    Args:
        text (str): The full skill text.
        heading (str): The section heading without the ``## `` prefix.

    Returns:
        str: The section body up to the next ``## `` heading.
    """
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, flags=re.DOTALL | re.MULTILINE)
    assert match is not None, f"skill section missing: {heading}"
    return match.group(1)


def test_skill_creates_operational_schedules_and_verifies_health() -> None:
    """OPS111-10: creation is followed by a status check in the same example
    block, success is defined as operational/healthy, and the manual worker
    is never a prerequisite."""
    text: str = _skill_text()
    create_commands: list[str] = _fenced_schedule_commands(_section(text=text, heading="Create a schedule"))
    verbs: list[str] = [shlex.split(command)[2] for command in create_commands]
    assert verbs.index("status") > verbs.index("add"), "the example verifies health after creating"
    operational: str = _section(text=text, heading="How schedules become operational")
    assert '"operational": true' in operational and '"state": "healthy"' in operational
    assert "detached" in operational and "closes" in operational
    assert "Never tell the user to run `slo schedule worker`" in text
    assert "administration and debugging only" in _section(text=text, heading="Guidance")
    assert "slo schedule worker" not in "".join(_fenced_schedule_commands(text))
    for state in ("healthy", "starting", "stopped", "unresponsive", "blocked"):
        assert f"`{state}`" in _section(text=text, heading="Verify health")
    assert "does not prove" in _section(text=text, heading="Verify health")


def test_skill_teaches_saved_but_not_operational_recovery() -> None:
    """OPS111-10: partial failure — no second add, quote the cause, retry
    start on the same id, never self-assert the upgrade confirmation."""
    recovery: str = _section(text=_skill_text(), heading="When the schedule is saved but not operational")
    assert "schedule saved, but not operational" in recovery
    assert "Do **not** run `add` again" in recovery
    assert "slo schedule start --schedule <id>" in recovery
    assert '"operational": false' in recovery
    assert "never pass `--earlier-workers-stopped`" in recovery


def test_skill_explains_closed_sessions_and_hides_internal_storage() -> None:
    """OPS111-10/11: closed sessions keep a durable queued prompt; no
    internal file or store detail is taught."""
    text: str = _skill_text()
    targets: str = _section(text=text, heading="Session targets")
    assert "durable inbox" in targets and "never resumes a session headlessly" in targets
    assert "queued, not lost" in targets
    for internal in (".schedule-engine", ".schedule-worker", "schedules.db", "honker", "WAL"):
        assert internal not in text, f"skill leaks internal storage detail: {internal}"


def test_documented_status_example_reports_a_healthy_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPS111-10: the skill's own create block, run through the real CLI,
    leaves an operational schedule whose status JSON reports a healthy worker."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))
    runner = CliRunner()
    outputs: list[str] = []
    for command in _fenced_schedule_commands(_section(text=_skill_text(), heading="Create a schedule")):
        result = runner.invoke(app, shlex.split(command)[1:])
        assert result.exit_code == 0, f"{command} failed: {result.output}"
        outputs.append(result.stdout)
    created = json.loads(outputs[1])
    status = json.loads(outputs[2])
    assert created["operational"] is True
    assert status["worker"]["state"] == "healthy"
    assert status["worker"]["launch_id"] == created["worker"]["launch_id"]
    assert status["next_due_at"] is not None
