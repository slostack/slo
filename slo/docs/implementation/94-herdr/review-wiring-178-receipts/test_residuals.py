"""Independent residual probes; product, permanent tests and historical probes stay untouched."""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

import src.tui.app as app_module
from src.tui.app import SloTUI
from tests.implementation_checks import test_conventions_audit_paths as audit_tests
from tests.tui.test_startup_notice_cutoff import _build_session, _seed_complete_turn


@pytest.mark.parametrize("case", ["untyped", "typed", "missing"])
@pytest.mark.parametrize("redirect_alias", [False, True])
def test_regression_rejects_removed_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, redirect_alias: bool
) -> None:
    """Require rejection, contrasting the historical seam with both current source bindings."""
    source = audit_tests.AUDIT.read_text()
    enumeration = audit_tests._TRACKED_ENUMERATION
    assert source.count(enumeration) == 1
    mutant = tmp_path / "audit-mutant.py"
    assert mutant.resolve().is_relative_to(tmp_path.resolve())
    mutant.write_text(source.replace(enumeration, "changed = []"))
    monkeypatch.setattr(target=audit_tests, name="AUDIT", value=mutant)
    if redirect_alias:
        monkeypatch.setattr(target=audit_tests, name="_REAL_AUDIT", value=mutant)
    cases = {
        "untyped": audit_tests.test_audit_flags_new_tracked_definition_from_nested_product_cwd,
        "typed": audit_tests.test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd,
        "missing": audit_tests.test_audit_fails_on_missing_candidate_path,
    }
    with pytest.raises(AssertionError):
        cases[case](tmp_path=tmp_path)


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_summary_completion_cannot_initiate_late_scroll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cutoff: str
) -> None:
    """Complete a real summary mount, cut off its return, and forbid a new scroll."""
    session = _build_session(tmp_path=tmp_path, session_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    await _seed_complete_turn(session=session, prompt="summary boundary")
    # Two actual history entries, one retained: summary must really mount.
    monkeypatch.setattr(target=app_module, name="TRANSCRIPT_HYDRATION_ENTRY_LIMIT", value=1)
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original_summary = app._update_earlier_summary
    original_scroll = app._scroll_transcript_to_end
    late_scrolls: list[str] = []

    async def summary() -> None:
        """Preserve the actual summary body and its real Textual mount."""
        await original_summary()
        assert app._earlier_summary is not None
        assert app._earlier_summary.is_mounted
        entered.set()
        await release.wait()

    def scroll() -> None:
        """Observe the new effect without replacing the real scroll implementation."""
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        # Mock dispatch frames sit between this observer and the production caller.
        while caller is not None and caller.f_code.co_filename.endswith("unittest/mock.py"):
            caller = caller.f_back
        caller_name = caller.f_code.co_name if caller is not None else "unknown"
        if (app._app_closing or app._session is not session) and caller_name == "_hydrate_transcript_from_history":
            late_scrolls.append(caller_name)
        del frame, caller
        original_scroll()

    async def cut_off() -> None:
        """Close publicly or replace selected identity before the summary returns."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            if cutoff == "closing":
                await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
            else:
                app._session = _build_session(
                    tmp_path=tmp_path, session_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
                )
        finally:
            release.set()

    with (
        patch.object(app, "_update_earlier_summary", side_effect=summary),
        patch.object(app, "_scroll_transcript_to_end", side_effect=scroll),
    ):
        driver = asyncio.create_task(coro=cut_off())
        try:
            async with app.run_test():
                await driver
                print("late_scrolls_after_summary", cutoff, late_scrolls)
                assert late_scrolls == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)
