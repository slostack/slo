"""Completion owner lifetime decisions over real directories and an injected UI port."""

import asyncio
from pathlib import Path
from typing import Optional

import pytest
from textual.app import App

from src.tui.path_suggestion_controller import PathPromptSnapshotDAO, PathSuggestionController
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO
from tests.tui.test_path_suggestions_app import ControlledPathReader
from tests.tui._scroll_settle import pump_until


class RecordingPathView:
    """Capture prompt snapshots and record rendering without replacing filesystem I/O."""

    def __init__(self, *, workdir: Path) -> None:
        """Retain the current UI snapshot and paint history."""
        self.snapshot = PathPromptSnapshotDAO(text="./", cursor=(0, 2), workdir=workdir)
        self.states: list[SlashSuggestionStateDAO] = []

    def capture_path_prompt(self) -> Optional["PathPromptSnapshotDAO"]:
        """Return the current prompt snapshot through the production UI port."""
        return self.snapshot

    async def publish_path_suggestions(
        self,
        *,
        state: SlashSuggestionStateDAO,
        controller: PathSuggestionController,
        snapshot: PathPromptSnapshotDAO,
    ) -> None:
        """Record only menu state, never file content."""
        self.states.append(state)

    async def replace_path_span(
        self,
        *,
        insert_text: str,
        start: tuple[int, int],
        end: tuple[int, int],
        cursor_inside_quote: bool,
        controller: PathSuggestionController,
        snapshot: PathPromptSnapshotDAO,
    ) -> None:
        """Reject replacement in this reader-only lifetime scenario."""
        raise AssertionError("No acceptance was requested")


async def test_changed_workdir_snapshot_revokes_held_read_and_close_joins(tmp_path: Path) -> None:
    """One owner drops a stale cwd result, consumes latest, and drains after closing."""
    for name in ("old", "new"):
        directory = tmp_path / name
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        (directory / (name + ".py")).touch()
    reader = ControlledPathReader()
    view = RecordingPathView(workdir=tmp_path / "old")
    app: App[None] = App()
    async with app.run_test():
        await exercise_workdir_change(app=app, view=view, reader=reader, tmp_path=tmp_path)


@pytest.mark.parametrize(argnames="explicit", argvalues=[False, True])
async def test_cancel_before_worker_entry_allows_identical_request_to_reopen(
    tmp_path: Path, explicit: bool
) -> None:
    """Normal/Tab requests recover without a shutdown join repairing Textual's state."""
    target = tmp_path / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    view = RecordingPathView(workdir=tmp_path)
    app: App[None] = App()
    reader = ControlledPathReader()
    reader.release.set()
    async with app.run_test() as pilot:
        controller = PathSuggestionController(view=view, reader=reader, run_worker=app.run_worker)
        try:
            assert await controller.request()
            worker = next(worker for worker in app.workers if worker.group == "path-suggestions")
            worker.cancel()  # No yield: callable entry and OS work cannot have started.
            await pilot.pause()
            assert worker not in app.workers
            assert controller._task is None
            assert reader.calls == []
            assert not any(state.visible for state in view.states)
            assert await controller.request(explicit=explicit)
            await pump_until(pilot=pilot, predicate=lambda: view.states[-1].visible)
            assert len(reader.calls) == 1
            assert [row.label for row in view.states[-1].rows] == ["one.py"]
        finally:
            controller.close()
            await controller.join()


async def test_join_propagates_cancellation_only_after_owned_read_finishes(tmp_path: Path) -> None:
    """Repeated cancellation cannot orphan the reader or claim successful completion."""
    reader = ControlledPathReader()
    view = RecordingPathView(workdir=tmp_path)
    app: App[None] = App()
    async with app.run_test() as pilot:
        controller = PathSuggestionController(view=view, reader=reader, run_worker=app.run_worker)
        try:
            assert await controller.request()
            await pump_until(pilot=pilot, predicate=reader.entered.is_set)
            controller.close()
            joining = asyncio.create_task(coro=controller.join())
            await asyncio.sleep(0)
            joining.cancel()
            await asyncio.sleep(0)
            joining.cancel()
            await asyncio.sleep(0)
            assert not joining.done()
            reader.release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(joining, timeout=3)
            await controller.join()
            assert controller._task is None
            assert not any(state.visible for state in view.states)
        finally:
            reader.release.set()
            controller.close()
            await controller.join()


async def test_failed_publication_join_releases_owned_worker_and_allows_retry(tmp_path: Path) -> None:
    """A failed awaited view delivery surfaces at join without poisoning reader reuse."""
    from textual.worker import WorkerFailed

    class FailingPathView(RecordingPathView):
        """Fail one visible delivery through the injected production view port."""

        fail: bool = True

        async def publish_path_suggestions(
            self,
            *,
            state: SlashSuggestionStateDAO,
            controller: PathSuggestionController,
            snapshot: PathPromptSnapshotDAO,
        ) -> None:
            """Reject one result, then permit ordinary recording after operator retry."""
            if state.visible and self.fail:
                raise ValueError("publication failed")
            await super().publish_path_suggestions(state=state, controller=controller, snapshot=snapshot)

    target = (tmp_path / "one.py").resolve()
    assert target.is_relative_to(tmp_path.resolve())
    target.touch()
    view = FailingPathView(workdir=tmp_path)
    app: App[None] = App()
    async with app.run_test():
        controller = PathSuggestionController(view=view, run_worker=app.run_worker)
        try:
            assert await controller.request()
            with pytest.raises(WorkerFailed, match="publication failed"):
                await controller.join()
            assert controller._worker_wait is None
            assert controller._worker is None
            await controller.join()
            view.fail = False
            assert await controller.request()
            await controller.join()
            assert view.states[-1].visible
        finally:
            controller.close()
            await controller.join()


async def test_close_during_awaited_publication_prevents_worker_admission(tmp_path: Path) -> None:
    """Async delivery is a real completion barrier, not permission to start retired work."""

    class GatedPathView(RecordingPathView):
        """Hold the initial hide delivery before a filesystem worker is admitted."""

        def __init__(self, *, workdir: Path) -> None:
            """Construct explicit bounded test barriers."""
            super().__init__(workdir=workdir)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def publish_path_suggestions(
            self,
            *,
            state: SlashSuggestionStateDAO,
            controller: PathSuggestionController,
            snapshot: PathPromptSnapshotDAO,
        ) -> None:
            """Wait for release; the caller must recheck retirement afterward."""
            self.entered.set()
            await self.release.wait()

    view = GatedPathView(workdir=tmp_path)
    app: App[None] = App()
    async with app.run_test():
        controller = PathSuggestionController(view=view, run_worker=app.run_worker)
        requesting = asyncio.create_task(coro=controller.request())
        try:
            await asyncio.wait_for(view.entered.wait(), timeout=2)
            assert not requesting.done()
            controller.close()
            view.release.set()
            await requesting
            assert controller._worker_wait is None
            assert controller._worker is None
        finally:
            view.release.set()
            await requesting
            controller.close()
            await controller.join()


async def exercise_workdir_change(
    *, app: App[None], view: RecordingPathView, reader: ControlledPathReader, tmp_path: Path
) -> None:
    """Drive the controller through actual Textual supervision and a recording view."""
    controller = PathSuggestionController(view=view, reader=reader, run_worker=app.run_worker)
    try:
        assert await controller.request()
        async with asyncio.timeout(delay=2):
            while not reader.entered.is_set():
                await asyncio.sleep(0.001)
        view.snapshot = PathPromptSnapshotDAO(text="./", cursor=(0, 2), workdir=tmp_path / "new")
        assert await controller.request()
        assert len(reader.calls) == 1
        reader.release.set()
        await controller.join()
        assert [row.label for row in view.states[-1].rows] == ["new.py"]
        assert len(reader.calls) == 2
        controller.close()
        assert not await controller.request()
        painted = len(view.states)
        await controller.dismiss()  # Late queued UI/replacement events must not paint after close.
        assert not await controller.request()
        assert len(view.states) == painted
        assert controller._task is None
    finally:
        reader.release.set()
        controller.close()
        await controller.join()
