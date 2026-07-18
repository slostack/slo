"""Tests for the one-time startup notice."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI


def _build_session_with_history(
    *,
    workdir: Path,
    history_root: Path,
    session_id: str,
) -> SloAgentSession:
    """Build a faux-driven session with filesystem history enabled.

    Args:
        workdir (Path): Workdir for the session.
        history_root (Path): Test-local history root.
        session_id (str): Stable session id.

    Returns:
        SloAgentSession: Session with persistent history enabled.
    """
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(workdir), tools=[]
        ),
        workdir=workdir,
        session_id=session_id,
        history_store=FilesystemSessionHistoryStore(root=history_root),
        enable_history=True,
    )


def _build_session_with_fallback_notice(
    *,
    workdir: Path,
    history_root: Path,
    session_id: str,
    fallback_notice: str,
) -> SloAgentSession:
    """Build a faux-driven session with a startup fallback notice."""
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(workdir), tools=[]
        ),
        config=SessionConfigDAO(workdir=workdir, fallback_notice=fallback_notice),
        workdir=workdir,
        session_id=session_id,
        history_store=FilesystemSessionHistoryStore(root=history_root),
        enable_history=True,
    )


class TestStartupNotice:
    """Brand-new vs resumed startup-notice behavior."""

    @pytest.mark.asyncio
    async def test_brand_new_session_renders_startup_notice_once(self, tmp_path: Path) -> None:
        """A new session shows the startup notice and records the metadata marker."""
        history_root: Path = tmp_path / "history"
        session_id: str = str(uuid4())
        session: SloAgentSession = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            session_id=session_id,
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            assert any("/help" in content for content, _classes in app._adapter.lines)

        metadata = await session.history_store.read_metadata(session_id=session_id)
        assert metadata.startup_notice_shown_at is not None

    @pytest.mark.asyncio
    async def test_resumed_session_skips_duplicate_startup_notice(self, tmp_path: Path) -> None:
        """A resumed session does not render the startup notice a second time."""
        history_root: Path = tmp_path / "history"
        session_id: str = str(uuid4())

        first_session: SloAgentSession = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            session_id=session_id,
        )
        first_app: SloTUI = SloTUI(session=first_session)
        async with first_app.run_test() as pilot:
            await pilot.pause()

        resumed_session: SloAgentSession = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            session_id=session_id,
        )
        resumed_app: SloTUI = SloTUI(session=resumed_session)
        async with resumed_app.run_test() as pilot:
            await pilot.pause()
            assert resumed_app._adapter is not None
            assert all("/help" not in content for content, _classes in resumed_app._adapter.lines)

    @pytest.mark.asyncio
    async def test_startup_notice_renders_fallback_notice(self, tmp_path: Path) -> None:
        """A session with a fallback notice surfaces it in the startup line."""
        history_root: Path = tmp_path / "history"
        session_id: str = str(uuid4())
        notice: str = "Model 'mistral-large' is not supported; falling back to gpt-5.4."
        session: SloAgentSession = _build_session_with_fallback_notice(
            workdir=tmp_path,
            history_root=history_root,
            session_id=session_id,
            fallback_notice=notice,
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            assert any("mistral-large" in content for content, _classes in app._adapter.lines)
            assert any("falling back" in content for content, _classes in app._adapter.lines)
