"""Independent review probes; no product or existing-test mutation."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.app import SloTUI
from tests.tui.test_startup_notice_cutoff import _build_session, _seed_complete_turn
from tests.implementation_checks import test_conventions_audit_paths as audit_tests


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_replay_continuation_after_first_admitted_mount(tmp_path: Path, cutoff: str) -> None:
    """Finish the first real replay mount, cut off, and forbid the next mount."""
    session = _build_session(tmp_path=tmp_path, session_id="11111111-1111-4111-8111-111111111111")
    await _seed_complete_turn(session=session, prompt="review replay")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = app._projector.project_replay_entry
    late_entries: list[str] = []
    calls = 0

    async def project(*, entry: TranscriptEntryDAO) -> None:
        """Retain real mounting and hold its first completion at the await boundary."""
        nonlocal calls
        calls += 1
        if app._app_closing or app._session is not session:
            late_entries.append(entry.kind)
        await original(entry=entry)
        if calls == 1:
            entered.set()
            await release.wait()

    async def cut_off() -> None:
        """Use public shutdown or displace the captured owner before continuation."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            if cutoff == "closing":
                await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
            else:
                app._session = _build_session(
                    tmp_path=tmp_path, session_id="22222222-2222-4222-8222-222222222222"
                )
        finally:
            release.set()

    with patch.object(app._projector, "project_replay_entry", side_effect=project):
        driver = asyncio.create_task(coro=cut_off())
        try:
            async with app.run_test():
                await driver
                print("late_replay_entries", cutoff, late_entries)
                assert late_entries == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


async def test_failed_notice_predicate_after_shutdown_does_not_render(tmp_path: Path) -> None:
    """An ordinary predicate failure after public shutdown must not repaint."""
    session = _build_session(tmp_path=tmp_path, session_id="33333333-3333-4333-8333-333333333333")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.should_show_startup_notice
    original_write = app._write_adapter_line
    late_lines: list[str] = []

    async def predicate() -> bool:
        """Complete real history lookup, then fail after cutoff."""
        await original()
        entered.set()
        await release.wait()
        raise OSError("synthetic predicate failure")

    def write(*, content: str, classes: str) -> None:
        """Observe late fixed diagnostics without changing rendering."""
        if app._app_closing:
            late_lines.append(content)
        original_write(content=content, classes=classes)

    async def cut_off() -> None:
        """Close publicly while startup is waiting."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
        finally:
            release.set()

    with (
        patch.object(session, "should_show_startup_notice", side_effect=predicate),
        patch.object(app, "_write_adapter_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=cut_off())
        try:
            async with app.run_test():
                await driver
                print("late_failure_lines", late_lines)
                assert late_lines == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


@pytest.mark.parametrize("case", ["untyped", "typed", "missing"])
def test_existing_audit_regressions_with_tracked_enumeration_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Measure whether current tests reject loss of the tracked-discovery channel."""
    source = audit_tests.AUDIT.read_text()
    old = '''changed = subprocess.check_output(
        ["git", "diff", "--relative", "--name-only", BASE, "--", "src", "tests"], text=True
    ).splitlines()'''
    assert source.count(old) == 1
    mutant = tmp_path / "audit-mutant.py"
    assert mutant.resolve().is_relative_to(tmp_path.resolve())
    mutant.write_text(source.replace(old, "changed = []"))
    monkeypatch.setattr(target=audit_tests, name="AUDIT", value=mutant)
    cases = {
        "untyped": audit_tests.test_audit_flags_new_tracked_definition_from_nested_product_cwd,
        "typed": audit_tests.test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd,
        "missing": audit_tests.test_audit_fails_on_missing_candidate_path,
    }
    cases[case](tmp_path=tmp_path)
    print("existing audit regression passed with tracked discovery removed:", case)
