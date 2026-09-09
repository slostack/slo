"""Unit tests for orchestrator context persistence (sub-spec 54.a.3).

Covers ``SloAgentSession._write_orchestrator_context`` and the call from
``_persist_attempt_opening_events`` on the first user message.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.service import SloAgentSession

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_session(
    *,
    tmp_path: Path,
    session_id: Optional[str] = None,
    attach_pool: bool = True,
) -> SloAgentSession:
    """Build a ``SloAgentSession`` wired to a temporary history root.

    Uses a pre-built ``FauxChatModel`` agent so no config/lazy build is needed.
    History is enabled and the store is pointed at ``tmp_path`` so tests can
    inspect the files written without touching ``~/.slo``.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.
        session_id (Optional[str]): Override session id; a fresh UUID4 is used
            when ``None``.

    Returns:
        SloAgentSession: Ready-to-test session.
    """
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    sid: str = session_id or str(uuid4())
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="done")]))
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=sid,
        agent=agent,
        history_store=store,
        enable_history=True,
    )
    if attach_pool:
        session._sub_agent_pool = MagicMock()
    return session


# ── tests ─────────────────────────────────────────────────────────────────────


class TestAssembledSystemPrompt:
    """``_assembled_system_prompt`` combines base and append fragments."""

    def test_returns_empty_string_when_no_config(self, tmp_path: Path) -> None:
        """Returns empty string when no config is available (pre-built agent path)."""
        session = _make_session(tmp_path=tmp_path)
        assert session._assembled_system_prompt() == ""

    def test_combines_base_and_append_from_config(self, tmp_path: Path) -> None:
        """Returns base + append when config provides both fragments."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        session = _make_session(tmp_path=tmp_path)
        config = MagicMock()
        config.system_prompt = "BASE"
        config.append_system_prompt = "_APPEND"
        session._config = config
        assert session._assembled_system_prompt() == "BASE_APPEND"

    def test_handles_none_fragments(self, tmp_path: Path) -> None:
        """Returns empty string when config fragments are both None."""
        session = _make_session(tmp_path=tmp_path)
        config = MagicMock()
        config.system_prompt = None
        config.append_system_prompt = None
        session._config = config
        assert session._assembled_system_prompt() == ""


class TestWriteOrchestratorContext:
    """``_write_orchestrator_context`` writes orchestrator_context.json atomically."""

    @pytest.mark.asyncio
    async def test_skips_when_pool_missing(self, tmp_path: Path) -> None:
        """Guard clause returns early when no sub-agent pool is attached."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid, attach_pool=False)
        session_dir = tmp_path / sid
        session_dir.mkdir(parents=True)

        await session._write_orchestrator_context(user_prompt="prompt")

        context_path = session_dir / "orchestrator_context.json"
        assert not context_path.exists()
        assert session._orchestrator_context_written is False

    @pytest.mark.asyncio
    async def test_context_written_on_first_run(self, tmp_path: Path) -> None:
        """First call writes a valid ``orchestrator_context.json`` to the session dir."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        session_dir = tmp_path / sid
        session_dir.mkdir(parents=True)

        await session._write_orchestrator_context(user_prompt="implement feature X")

        context_path = session_dir / "orchestrator_context.json"
        assert context_path.exists(), "orchestrator_context.json should be written"
        raw = context_path.read_bytes()
        dao = OrchestratorContextDAO.model_validate_json(raw)
        assert dao.user_prompt == "implement feature X"
        assert dao.recorded_at.endswith("+00:00")

    @pytest.mark.asyncio
    async def test_context_not_rewritten_when_flag_set(self, tmp_path: Path) -> None:
        """Subsequent calls are skipped once ``_orchestrator_context_written`` is True."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        session_dir = tmp_path / sid
        session_dir.mkdir(parents=True)
        session._orchestrator_context_written = True

        await session._write_orchestrator_context(user_prompt="second prompt")

        context_path = session_dir / "orchestrator_context.json"
        assert not context_path.exists(), "Should not write when flag is already set"

    @pytest.mark.asyncio
    async def test_context_not_rewritten_when_file_exists(self, tmp_path: Path) -> None:
        """File is preserved when it already exists on disk (resume case)."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        session_dir = tmp_path / sid
        session_dir.mkdir(parents=True)
        sentinel = b'{"sentinel": true}'
        (session_dir / "orchestrator_context.json").write_bytes(sentinel)

        await session._write_orchestrator_context(user_prompt="any prompt")

        context_path = session_dir / "orchestrator_context.json"
        assert context_path.read_bytes() == sentinel, "Existing file must not be overwritten"

    @pytest.mark.asyncio
    async def test_context_skipped_when_history_disabled(self, tmp_path: Path) -> None:
        """No file is written when history is disabled."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        session._enable_history = False

        await session._write_orchestrator_context(user_prompt="prompt")

        context_path = tmp_path / sid / "orchestrator_context.json"
        assert not context_path.exists()

    @pytest.mark.asyncio
    async def test_write_failure_is_logged_not_raised(self, tmp_path: Path) -> None:
        """An ``OSError`` during write is swallowed and logged; workflow continues."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        session_dir = tmp_path / sid
        session_dir.mkdir(parents=True)

        with patch("os.replace", side_effect=OSError("disk full")):
            await session._write_orchestrator_context(user_prompt="prompt")

        context_path = session_dir / "orchestrator_context.json"
        assert not context_path.exists(), "File must not exist after failed write"

    @pytest.mark.asyncio
    async def test_sets_written_flag_on_success(self, tmp_path: Path) -> None:
        """``_orchestrator_context_written`` is True after a successful write."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        (tmp_path / sid).mkdir(parents=True)

        assert not session._orchestrator_context_written
        await session._write_orchestrator_context(user_prompt="p")
        assert session._orchestrator_context_written

    @pytest.mark.asyncio
    async def test_sets_written_flag_even_on_ioerror(self, tmp_path: Path) -> None:
        """Flag is set to True even when the write fails, preventing retry storms."""
        sid = str(uuid4())
        session = _make_session(tmp_path=tmp_path, session_id=sid)
        (tmp_path / sid).mkdir(parents=True)

        with patch("os.replace", side_effect=OSError("disk full")):
            await session._write_orchestrator_context(user_prompt="p")

        assert session._orchestrator_context_written
