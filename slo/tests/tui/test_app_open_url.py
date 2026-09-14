"""Tests for ``SloTUI.open_url``: skip on headless hosts, never block the event loop.

Link clicks (``AuthorizationLink`` and any Textual link) reach ``App.open_url``. Textual's
driver then calls ``webbrowser.open`` synchronously, which on a headless Linux host runs a
console browser and waits for it on the TUI terminal. These tests inject the host and
record the real open through the app's own seam, so no browser starts and nothing is patched.
"""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.worker import Worker, WorkerFailed, WorkerState

import src.tui.app as app_module
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.browser_host import BrowserHost
from src.tui.app import SloTUI

_URL: str = "https://example.invalid/authorize?scope=dummy"
_GRAPHICAL_HOST: BrowserHost = BrowserHost(environment={"DISPLAY": ":0"}, platform="linux")
_HEADLESS_HOST: BrowserHost = BrowserHost(environment={"TERM": "xterm-256color"}, platform="linux")


def _build_session(*, workdir: Path) -> SloAgentSession:
    """Build a faux-driven session whose history lives under the test directory.

    Args:
        workdir (Path): Temporary workdir and history root parent.

    Returns:
        SloAgentSession: A session that never calls a real model.
    """
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(workdir), tools=[]
        ),
        workdir=workdir,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=workdir / "history"),
        enable_history=True,
    )


class _RecordingSloTUI(SloTUI):
    """Production app whose driver-level open records the URL and thread instead of launching."""

    # Textual resolves a relative CSS_PATH next to the subclass module; keep the production sheet.
    CSS_PATH = str(Path(app_module.__file__).parent / "app.tcss")

    def __init__(
        self,
        *,
        session: SloAgentSession,
        browser_host: BrowserHost,
        open_error: Exception | None = None,
    ) -> None:
        """Keep the injected host and an optional failure for the driver-level open.

        Args:
            session (SloAgentSession): Faux-driven session.
            browser_host (BrowserHost): Injected host deciding whether opening may run.
            open_error (Exception | None, optional): Raised by the driver-level open when set.
                Defaults to None.
        """
        super().__init__(session=session, browser_host=browser_host)
        self._open_error: Exception | None = open_error
        self.opened_urls: list[str] = []
        self.opener_threads: list[threading.Thread] = []

    def _open_url_with_driver(self, *, url: str, new_tab: bool) -> None:
        """Record the open request, or raise the injected failure.

        Args:
            url (str): URL the app was asked to open.
            new_tab (bool): Textual's new-tab flag, passed through unchanged.
        """
        self.opener_threads.append(threading.current_thread())
        if self._open_error is not None:
            raise self._open_error
        self.opened_urls.append(url)


def _open_url_workers(*, app: SloTUI) -> list[Worker[None]]:
    """Return the browser-open workers the app has started and not yet finished.

    Args:
        app (SloTUI): Running app under test.

    Returns:
        list[Worker[None]]: Workers in the ``open-url`` group.
    """
    return [worker for worker in app.workers if worker.group == "open-url"]


class TestSloTUIOpenUrl:
    """Link opens skip headless hosts and run off the event loop elsewhere."""

    @pytest.mark.asyncio
    async def test_open_url_when_host_is_headless_opens_nothing(self, tmp_path: Path) -> None:
        """No graphical session on Linux: no worker starts and the driver is never asked to open."""
        app: _RecordingSloTUI = _RecordingSloTUI(
            session=_build_session(workdir=tmp_path), browser_host=_HEADLESS_HOST
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.open_url(_URL)
            started: list[Worker[None]] = _open_url_workers(app=app)
            await pilot.pause()

        assert started == []
        assert app.opened_urls == []

    @pytest.mark.asyncio
    async def test_open_url_when_host_is_graphical_opens_in_worker_thread(self, tmp_path: Path) -> None:
        """A graphical host opens the exact URL from a worker thread, never the loop thread."""
        app: _RecordingSloTUI = _RecordingSloTUI(
            session=_build_session(workdir=tmp_path), browser_host=_GRAPHICAL_HOST
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            loop_thread: threading.Thread = threading.current_thread()
            app.open_url(_URL)
            for worker in _open_url_workers(app=app):
                await worker.wait()

        assert app.opened_urls == [_URL]
        assert len(app.opener_threads) == 1
        assert app.opener_threads[0] is not loop_thread

    @pytest.mark.asyncio
    async def test_open_url_when_driver_open_raises_keeps_app_running(self, tmp_path: Path) -> None:
        """A failing browser launch in the worker never exits the app."""
        app: _RecordingSloTUI = _RecordingSloTUI(
            session=_build_session(workdir=tmp_path),
            browser_host=_GRAPHICAL_HOST,
            open_error=RuntimeError("no browser"),
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.open_url(_URL)
            started: list[Worker[None]] = _open_url_workers(app=app)
            for worker in started:
                with pytest.raises(WorkerFailed):
                    await worker.wait()
            await pilot.pause()

            assert [worker.state for worker in started] == [WorkerState.ERROR]
            assert app.return_code is None
            assert app.is_running
            assert len(app.opener_threads) == 1
