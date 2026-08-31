"""Tests for resume + replay hydration (sub-spec 05.e §8)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
)
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.stream_recovery.dao import (
    ProviderStreamFailure,
    StreamRecoveryAction,
    StreamRecoveryDecisionDAO,
)
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.user_message_block import UserMessageBlock


def _build_session_with_history(
    *,
    workdir: Path,
    history_root: Path,
    responses: list[AIMessage],
    session_id: str | None = None,
) -> SloAgentSession:
    """Build a faux-driven session with the on-disk store enabled."""
    agent = SloAgent(llm=FauxChatModel(responses=responses), cwd=str(workdir), tools=[])
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=session_id or str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        enable_history=True,
    )


async def _drain_session(*, session: SloAgentSession, text: str) -> None:
    """Drain ``session.invoke`` to completion for history seeding.

    Args:
        session (SloAgentSession): Session under test.
        text (str): Prompt text.
    """
    async for _event in session.invoke(text=text):
        pass


class TestConfigCarriesResumeSessionId:
    """``SessionConfigDAO.session_id`` is threaded into ``SloAgentSession.build``."""

    def test_build_honours_explicit_session_id(self, tmp_path: Path) -> None:
        explicit: str = str(uuid4())
        config = SessionConfigDAO(
            workdir=tmp_path,
            session_id=explicit,
            history_root=tmp_path / "history",
        )

        session = SloAgentSession.build(config=config)

        assert session.session_id == explicit

    def test_build_allocates_uuid_when_session_id_absent(self, tmp_path: Path) -> None:
        config = SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
        )

        session = SloAgentSession.build(config=config)

        # Crude UUID4-shape check (8-4-4-4-12 hex segments).
        assert len(session.session_id) == 36
        assert session.session_id.count("-") == 4


class TestHydrateTranscriptEntries:
    """``SloAgentSession.hydrate_transcript_entries`` reads from disk."""

    async def test_returns_empty_when_no_persisted_events(self, tmp_path: Path) -> None:
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        entries = await session.hydrate_transcript_entries()

        assert entries == []

    async def test_returns_entries_when_events_exist(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        explicit: str = str(uuid4())
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="hello back")],
            session_id=explicit,
        )
        await _drain_session(session=session, text="hi there")

        # Build a fresh session that resumes the same id.
        resumed = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="ignored")],
            session_id=explicit,
        )
        entries = await resumed.hydrate_transcript_entries()

        user_entries = [entry for entry in entries if entry.kind == "user"]
        assistant_entries = [entry for entry in entries if entry.kind == "assistant"]
        assert any("hi there" in (entry.content or "") for entry in user_entries)
        assert any("hello back" in (entry.answer or "") for entry in assistant_entries)


class TestTUIStreamReconnect:
    """The real Textual TUI renders the public session reconnect boundary."""

    @pytest.mark.asyncio
    async def test_tui_renders_reconnect_then_completion_for_pre_commit_failure(self, tmp_path: Path) -> None:
        """A pre-commit retry reaches the visible TUI transcript exactly once.

        This functional Textual test drives ``_run_prompt`` through the public
        session stream. Before the reconnect-yield fix, the session subscriber
        saw the audit but the TUI loop never did, so no reconnect notice could
        render here.
        """
        session: SloAgentSession = _build_session_with_history(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            responses=[FauxChatModel.assistant_message(content="unused")],
        )
        invocation_count: int = 0

        async def _scripted_invoke(**_: object):
            nonlocal invocation_count
            invocation_count += 1
            if invocation_count == 1:
                raise ProviderStreamFailure(
                    decision=StreamRecoveryDecisionDAO(
                        action=StreamRecoveryAction.RETRY_FRESH_CONNECTION,
                        reason_code="provider_stream_disconnected",
                        retry_delay_seconds=0.0,
                        exception_family="httpx.RemoteProtocolError",
                    ),
                    partial_output_committed=False,
                    attempt_number=1,
                )
            yield AgentStreamEventDAO(kind="text_delta", delta="recovered")
            yield AgentStreamEventDAO(kind="run_completed", content="recovered")

        app: SloTUI = SloTUI(session=session)
        from unittest.mock import patch

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(session.agent, "invoke", _scripted_invoke):
                await app._run_prompt(text="functional retry")
            await pilot.pause()

        assert invocation_count == 2
        assert app._adapter is not None
        transcript: list[str] = [content for content, _classes in app._adapter.lines]
        assert any("provider_stream_disconnected" in content for content in transcript)
        assert session.is_running is False
        assert app._in_flight_task is None


class TestTUIHydration:
    """``SloTUI.on_mount`` hydrates from persisted history before live rendering."""

    async def test_on_mount_noops_when_history_is_absent(self, tmp_path: Path) -> None:
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            responses=[FauxChatModel.assistant_message(content="hi")],
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            assert any("/help" in content for content, _classes in app._adapter.lines)

    async def test_on_mount_hydrates_transcript_from_persisted_history(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        explicit: str = str(uuid4())

        # Step 1: seed persisted history by running one prompt.
        seed = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="seeded reply")],
            session_id=explicit,
        )
        await _drain_session(session=seed, text="seeded prompt")

        # Step 2: a fresh session reusing the same id boots the TUI.
        resumed = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="ignored")],
            session_id=explicit,
        )
        app = SloTUI(session=resumed)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._adapter is not None
            # Logical lines are recorded (copy/replay seam) ...
            contents: list[str] = [c for c, _ in app._adapter.lines]
            assert any("seeded prompt" in c for c in contents)
            assert any("seeded reply" in c for c in contents)
            # ... and replay mounts the same components the live path mounts.
            assert len(app.query(UserMessageBlock)) >= 1
            assert len(app.query(AssistantStreamBlock)) >= 1
