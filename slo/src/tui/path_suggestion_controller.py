"""One owner for prompt-path discovery, stale rejection, replacement and reader lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict
from textual.worker import Worker, WorkerCancelled

from src.agents.slo_agent.herdr.service import HerdrTaskJoin
from src.tui.path_suggestion_engine import PathSuggestionEngine, PathSuggestionQueryDAO, PathSuggestionReader
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO


class PathPromptSnapshotDAO(BaseModel):
    """Immutable prompt/cwd authority; selection and cwd changes invalidate old output."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    cursor: tuple[int, int]
    workdir: Path
    selection_empty: bool = True

    def query(self, *, explicit: bool) -> Optional[PathSuggestionQueryDAO]:
        """Parse a collapsed cursor only, without filesystem work.

        Args:
            explicit: Whether basename discovery is active.

        Returns:
            Cursor-local query, or None for selection/non-path context.
        """
        if not self.selection_empty:
            return None
        offset = sum(len(line) + 1 for line in self.text.split("\n")[: self.cursor[0]]) + self.cursor[1]
        return PathSuggestionEngine.query(
            text=self.text, cursor=offset, workdir=self.workdir, explicit=explicit
        )


class PathSuggestionView(Protocol):
    """TextArea/presentation port; policy and task ownership stay in the controller."""

    def capture_path_prompt(self) -> Optional[PathPromptSnapshotDAO]:
        """Capture the live collapsed-selection/cursor/cwd authority, or no mounted input."""
        ...

    def publish_path_suggestions(self, *, state: SlashSuggestionStateDAO) -> None:
        """Paint a controller-owned menu state through the shared suggestion menu."""
        ...

    def replace_path_span(
        self, *, insert_text: str, start: tuple[int, int], end: tuple[int, int], cursor_inside_quote: bool
    ) -> None:
        """Apply one undo-aware range edit; optionally keep the cursor before its closing quote."""
        ...


class PathWorkerScheduler(Protocol):
    """Admit completion work to the app's supervised worker manager."""

    def __call__(
        self, *, work: Callable[[], Coroutine[None, None, None]], group: str, exit_on_error: bool
    ) -> Worker[None]:
        """Schedule lazy work so cancellation before entry cannot leak a coroutine."""
        ...


class PathSuggestionController:
    """Own completion policy and one retained off-thread reader for a mounted prompt.

    Prompt events call request/accept/dismiss; app shutdown closes admission before
    unrelated cleanup, then joins. OS filesystem calls cannot be cancelled, so a
    stuck filesystem can delay join. No bounded shutdown latency is promised.
    """

    def __init__(
        self,
        *,
        view: PathSuggestionView,
        run_worker: PathWorkerScheduler,
        reader: Optional[PathSuggestionReader] = None,
    ) -> None:
        """Bind the UI port and inert reader without starting work.

        Args:
            view: Live snapshot, range-edit and presentation adapter.
            reader: Injected off-thread reader; defaults to immediate real enumeration.
            run_worker: App-owned Textual worker admission, not a raw task scheduler.
        """
        self._run_worker = run_worker
        self._worker: Optional[Worker[None]] = None
        self._worker_wait: Optional[asyncio.Task[None]] = None
        self._view = view
        self._reader = reader or PathSuggestionEngine()
        self._explicit = False
        self._closed = False
        self._generation = 0
        self._query: Optional[PathSuggestionQueryDAO] = None
        self._snapshot: Optional[PathPromptSnapshotDAO] = None
        self._dismissed: Optional[PathPromptSnapshotDAO] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._state = SlashSuggestionStateDAO(visible=False)

    def invalidate(self) -> None:
        """Revoke captured/painted authority without abandoning an active filesystem call."""
        self._generation += 1
        self._query = None
        self._snapshot = None

    def dismiss(self) -> None:
        """Remember the current prompt so unchanged events cannot reopen the menu."""
        self._explicit = False
        self.invalidate()
        self._dismissed = self._view.capture_path_prompt()
        self._publish(state=SlashSuggestionStateDAO(visible=False))

    def close(self) -> None:
        """Seal admission and revoke output synchronously before app teardown yields."""
        self._closed = True
        self._explicit = False
        self.invalidate()

    def request(self, *, explicit: bool = False) -> bool:
        """Coalesce latest prompt context; return whether paths own this menu.

        Args:
            explicit: Tab discovery clears dismissal and admits plain basenames.

        Returns:
            True for eligible path context, including unchanged/dismissed snapshots.
        """
        snapshot = self._view.capture_path_prompt()
        if snapshot is None or self._closed:
            return False
        query = self._discover_query(snapshot=snapshot, explicit=explicit)
        if query is None:
            self._explicit = False
            self.invalidate()
            return False
        self._admit_query(snapshot=snapshot, query=query)
        return True

    def _discover_query(
        self, *, snapshot: PathPromptSnapshotDAO, explicit: bool
    ) -> Optional[PathSuggestionQueryDAO]:
        """Persist Tab discovery only while editing its original token."""
        if explicit:
            self._dismissed = None
            self._explicit = True
        query = snapshot.query(explicit=self._explicit)
        if (
            not explicit
            and self._explicit
            and (query is None or self._query is None or query.start != self._query.start)
        ):
            self._explicit = False
            return snapshot.query(explicit=False)
        return query

    def _admit_query(self, *, snapshot: PathPromptSnapshotDAO, query: PathSuggestionQueryDAO) -> None:
        """Skip dismissed/identical work and start at most one reader task."""
        self._retire_completed_worker()
        if snapshot == self._dismissed or (snapshot == self._snapshot and query == self._query):
            return
        self.invalidate()
        self._snapshot, self._query = snapshot, query
        self._publish(state=SlashSuggestionStateDAO(visible=False))
        if self._worker_wait is None:
            self._worker = self._run_worker(
                work=self._run_queries, group="path-suggestions", exit_on_error=False
            )
            # Textual may leave state RUNNING after pre-entry cancellation. The
            # wait owns actual completion, including joined uncancellable reads.
            self._worker_wait = asyncio.create_task(coro=self._wait_for_worker(worker=self._worker))

    def _retire_completed_worker(self) -> None:
        """Revoke cancelled snapshots only after the retained wait has joined all work."""
        if self._worker_wait is None or not self._worker_wait.done():
            return
        self._worker_wait.result()
        if self._worker is not None and self._worker.is_cancelled:
            self.invalidate()
        self._worker = None
        self._worker_wait = None

    async def _run_queries(self) -> None:
        """Supervise a retained reader; worker cancellation revokes then joins OS work.

        The app worker starts this controller-owned inner task. Repeated cancellation
        never releases the single-flight slot or permits late publication while a
        filesystem call still runs. Close/join also waits for this worker boundary.
        """
        task = asyncio.create_task(coro=self._consume_queries())
        self._task = task
        try:
            await asyncio.shield(arg=task)
        except asyncio.CancelledError:
            self.invalidate()
            task.cancel()
            await HerdrTaskJoin.wait(task=task)
            self.invalidate()
            raise
        finally:
            self._task = None

    async def _consume_queries(self) -> None:
        """Drain latest queries serially; revoked generations never paint.

        Started by request, retained until the current read/latest query ends, and
        joined by app shutdown. Exceptions from the injected reader become hidden
        menus, never private filesystem diagnostics.
        """
        while self._query is not None and not self._closed:
            query, generation = self._query, self._generation
            state = await self._read(query=query)
            if generation != self._generation:
                continue
            if self._snapshot_is_current():
                self._publish(state=state)
            return

    async def _read(self, *, query: PathSuggestionQueryDAO) -> SlashSuggestionStateDAO:
        """Contain collaborator failures in the completion boundary."""
        read = asyncio.create_task(coro=asyncio.to_thread(self._reader.evaluate, query=query))
        cancelled = await HerdrTaskJoin.wait(task=read)
        if cancelled:
            raise asyncio.CancelledError
        try:
            return read.result()
        except Exception:
            return SlashSuggestionStateDAO(visible=False)

    def _snapshot_is_current(self) -> bool:
        """Validate synchronous edits, cursor, selection and cwd before paint or acceptance."""
        return (
            not self._closed
            and self._snapshot is not None
            and self._snapshot == self._view.capture_path_prompt()
        )

    def _publish(self, *, state: SlashSuggestionStateDAO) -> None:
        """Retain the replacement span that corresponds to the painted rows."""
        self._state = state
        if not self._closed:
            self._view.publish_path_suggestions(state=state)

    async def join(self) -> None:
        """Join retained filesystem work; cancellation never abandons its thread."""
        wait = self._worker_wait
        if wait is not None:
            await HerdrTaskJoin.wait(task=wait)
            wait.result()

    @staticmethod
    async def _wait_for_worker(*, worker: Worker[None]) -> None:
        """Treat supervised cancellation as cleanup, while retaining failure evidence."""
        try:
            await worker.wait()
        except WorkerCancelled:
            pass

    def accept(self, *, insert_text: str) -> None:
        """Apply the selected token only under its still-current snapshot authority.

        Args:
            insert_text: Encoded literal selected path, trailing slash for directory.
        """
        if not self._snapshot_is_current() or self._snapshot is None:
            return
        text = self._snapshot.text
        start = self._location(text=text, offset=self._state.replacement_start)
        end = self._location(text=text, offset=self._state.replacement_end)
        self.invalidate()
        self._replace_token(insert_text=insert_text, start=start, end=end)
        if insert_text.endswith("/"):
            self.request()
            return
        self.dismiss()

    def _replace_token(self, *, insert_text: str, start: tuple[int, int], end: tuple[int, int]) -> None:
        """Keep a directory's closing quote while continuing navigation inside it."""
        quoted_directory = insert_text.endswith("/") and insert_text[0] in "\"'"
        replacement = insert_text + insert_text[0] if quoted_directory else insert_text
        self._view.replace_path_span(
            insert_text=replacement, start=start, end=end, cursor_inside_quote=quoted_directory
        )

    @staticmethod
    def _location(*, text: str, offset: int) -> tuple[int, int]:
        """Translate a captured character offset to a TextArea row/column."""
        before = text[:offset]
        return before.count("\n"), len(before.rsplit(sep="\n", maxsplit=1)[-1])
