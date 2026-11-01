"""Rendered main-header contract for the v0.3.1 release."""

from pathlib import Path

from langchain_core.messages import AIMessage
from textual.content import Content
from textual.widgets import Header

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_rendered_header_tracks_selected_session_without_runtime_metadata(tmp_path: Path) -> None:
    """Mount and replace real sessions; only cwd and full ID accompany the app name.

    Args:
        tmp_path: Disposable working directories; the provider is a scripted model.
    """
    first_workdir: Path = tmp_path / "first"
    next_workdir: Path = tmp_path / "second"
    first_workdir.mkdir()
    next_workdir.mkdir()
    first: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=first_workdir,
        session_id="a166b82b-617e-45c6-9ada-a36f1c589fb6",
    )
    successor: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=next_workdir,
        session_id="b166b82b-617e-45c6-9ada-a36f1c589fb7",
    )
    app: SloTUI = SloTUI(session=first)
    home: Path = Path.home()
    first_display: str = (
        f"~/{first_workdir.relative_to(home)}" if first_workdir.is_relative_to(home) else str(first_workdir)
    )
    next_display: str = (
        f"~/{next_workdir.relative_to(home)}" if next_workdir.is_relative_to(home) else str(next_workdir)
    )

    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        header: Header = app.query_one(Header)
        assert header.format_title().plain == f"slo · {first_display} · session {first.session_id}"
        assert app.sub_title == ""
        assert header.icon == "⭘"
        rendered_title = header.query_one("HeaderTitle").render()
        assert isinstance(rendered_title, Content)
        assert rendered_title.plain == header.format_title().plain

        await app._commit_replacement_session(old_session=first, candidate=successor)
        await pilot.pause()
        assert app._session is successor
        assert header.format_title().plain == f"slo · {next_display} · session {successor.session_id}"
        rendered_title = header.query_one("HeaderTitle").render()
        assert isinstance(rendered_title, Content)
        assert rendered_title.plain == header.format_title().plain
        assert app.sub_title == ""
        assert header.icon == "⭘"
