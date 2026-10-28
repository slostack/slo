"""Independent mounted probe of the inner startup-notice await boundary."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_startup_notice_does_not_publish_after_public_shutdown(tmp_path: Path) -> None:
    """Pause the real history predicate, close publicly, then resume its caller."""
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")]), tools=[], cwd=str(tmp_path)),
        workdir=tmp_path,
        session_id="11111111-1111-4111-8111-111111111111",
        history_store=store,
        enable_history=True,
    )
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.should_show_startup_notice
    late_lines: list[str] = []
    original_write = app._write_adapter_line

    async def predicate() -> bool:
        """Retain the actual history result before the notice continuation resumes."""
        result = await original()
        entered.set()
        await release.wait()
        return result

    def write(*, content: str, classes: str) -> None:
        """Observe actual notice output after the monotonic cutoff."""
        if app._app_closing:
            late_lines.append(content)
        original_write(content=content, classes=classes)

    async def close_during_predicate() -> None:
        """Use public shutdown while on_mount is suspended inside its notice helper."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
            assert app._app_closing
            assert not await store.session_exists(session_id=session.session_id)
        finally:
            release.set()

    with (
        patch.object(session, "should_show_startup_notice", side_effect=predicate),
        patch.object(app, "_write_adapter_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=close_during_predicate())
        try:
            async with app.run_test():
                await driver
                assert app._mount_runtime_task is None
                metadata = await store.read_metadata(session_id=session.session_id)
                print("late_notice_count", len(late_lines))
                print("startup_marker_written_after_shutdown", metadata.startup_notice_shown_at is not None)
                assert late_lines == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)
