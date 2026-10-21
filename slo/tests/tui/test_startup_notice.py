"""Tests for the one-time startup notice."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.preferences.dao import UserPreferencesDAO
from src.cli.typer_dispatch import TyperDispatch
from src.tui.app import SloTUI
from src.tui.widgets.user_message_block import UserMessageBlock
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock


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

        assert session.history_store is not None
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
    async def test_startup_notice_reports_k3_max_provider_effort(self, tmp_path: Path) -> None:
        """A prebuilt K3 session reports its canonical default and native maximum effort."""
        history_root: Path = tmp_path / "history"
        session_id: str = str(uuid4())
        session: SloAgentSession = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            session_id=session_id,
        )
        session._active_model_name = "kimi-k3"
        session._active_reasoning_level = "xhigh"
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            assert any("Reasoning: xhigh" in content for content, _classes in app._adapter.lines)
            assert any("Provider detail: effort max" in content for content, _classes in app._adapter.lines)

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

    async def test_should_show_startup_notice_when_resumed_with_fallback_renders_existing_block(
        self, tmp_path: Path
    ) -> None:
        """Each fallback launch renders the full block despite a persisted startup marker."""
        history_root: Path = tmp_path / "history"
        assert history_root.resolve().is_relative_to(tmp_path.resolve())
        session_id: str = str(uuid4())
        first_session = _build_session_with_history(
            workdir=tmp_path, history_root=history_root, session_id=session_id
        )
        await first_session.mark_startup_notice_shown()
        notice: str = (
            "Model 'retired-model-x' from the resumed session is not available in this version; "
            "using the default model instead."
        )
        for _launch in range(2):
            session = _build_session_with_fallback_notice(
                workdir=tmp_path,
                history_root=history_root,
                session_id=session_id,
                fallback_notice=notice,
            )
            app = SloTUI(session=session)
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._adapter is not None
                lines: list[str] = [content for content, _classes in app._adapter.lines]
                assert lines[0] == notice
                assert "Copyright (C)" in lines[1]
                assert f"Initialized model: {session.active_model_name}" in lines[2]
                assert len(lines) == 3

    @pytest.mark.parametrize(argnames="fallback_notice", argvalues=[None, "Resume fallback"])
    async def test_should_show_startup_notice_when_history_disabled_honors_fallback(
        self, tmp_path: Path, fallback_notice: str | None
    ) -> None:
        """A fallback launch remains visible after the in-memory marker is set."""
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
                fallback_notice=fallback_notice,
            )
        )
        assert await session.should_show_startup_notice()
        await session.mark_startup_notice_shown()
        assert await session.should_show_startup_notice() is (fallback_notice is not None)

    async def test_startup_notice_when_fallback_uses_pool_names_primary_and_replays_history(
        self, tmp_path: Path
    ) -> None:
        """Actual CLI config and session build hydrate history and identify the effective pool primary."""
        history: Path = tmp_path / "history"
        assert history.resolve().is_relative_to(tmp_path.resolve())
        first = _build_session_with_history(workdir=tmp_path, history_root=history, session_id="resumed")
        await first.mark_startup_notice_shown()
        events = [event async for event in first.invoke(text="old question")]
        assert events[-1].kind == "run_completed"
        assert first.history_store is not None
        metadata = await first.history_store.read_metadata(session_id="resumed")
        metadata.model_name = "retired-model-x"
        await first.history_store.write_metadata(metadata=metadata)
        with patch(
            target="src.cli.typer_dispatch.UserPreferencesStore.load",
            return_value=UserPreferencesDAO(
                default_model_name="gpt-5.4", default_model_pool="claude-sonnet-4-6,gpt-5.4"
            ),
        ):
            config = TyperDispatch._build_session_config(
                workdir=tmp_path, resume_session_id="resumed", resumed_model_name=metadata.model_name
            )
        config = config.model_copy(update={"history_root": history})
        session = SloAgentSession.build(config=config, allow_pending_preparation=True)
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            lines: list[str] = [content for content, _classes in app._adapter.lines]
            assert config.fallback_notice in lines
            assert any("Copyright (C)" in line for line in lines)
            assert any("Initialized model: claude-sonnet-4-6." in line for line in lines)
            assert [block.get_copyable_text() for block in app.query(UserMessageBlock)] == ["old question"]
            assert [block.get_copyable_text() for block in app.query(AssistantStreamBlock)] == ["unused"]
