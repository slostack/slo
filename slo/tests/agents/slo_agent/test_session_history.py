"""Tests for ``SloAgentSession`` history orchestration (sub-spec 05.c §8, 05.d §8)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessageChunk

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import StreamEventKind
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
)
from src.agents.slo_agent.history.transcript import ReplayEntryProjector
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers import FauxChatModel


def _build_session_with_history(
    *,
    workdir: Path,
    history_root: Path,
    responses: list,
    session_id: str | None = None,
) -> SloAgentSession:
    """Build a session whose agent is faux-scripted but persistence is real.

    Args:
        workdir (Path): Workdir for the agent.
        history_root (Path): Root for the history store.
        responses (list): Scripted ``AIMessage`` responses.
        session_id (str | None): Optional explicit session id.

    Returns:
        SloAgentSession: Session with the on-disk store enabled.
    """
    agent = SloAgent(llm=FauxChatModel(responses=responses), cwd=str(workdir), tools=[])
    store = FilesystemSessionHistoryStore(root=history_root)
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=session_id or str(uuid4()),
        history_store=store,
        enable_history=True,
    )


async def _drain_session(*, session: SloAgentSession, text: str) -> str:
    """Drain ``session.invoke`` and return the final assistant text.

    Args:
        session (SloAgentSession): Session under test.
        text (str): Prompt text.

    Returns:
        str: Final response text.
    """
    final_response: str = ""
    async for event in session.invoke(text=text):
        if event.kind == "run_completed":
            final_response = event.content or ""
    return final_response


class TestPromptPersistsLifecycleEvents:
    """``invoke`` writes the full canonical event log."""

    async def test_prompt_persists_user_message_and_run_lifecycle(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        await _drain_session(session=session, text="hello")

        store = FilesystemSessionHistoryStore(root=history_root)
        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session.session_id,
        )
        kinds: list[str] = [e.kind for e in events]
        assert "run_started" in kinds
        assert "user_message" in kinds
        assert "run_completed" in kinds
        # user_message must precede run_completed
        assert kinds.index("user_message") < kinds.index("run_completed")

    async def test_next_turn_loads_projected_history_from_disk(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[
                FauxChatModel.assistant_message(content="first"),
                FauxChatModel.assistant_message(content="second"),
            ],
        )

        await _drain_session(session=session, text="hello")
        # Second turn: the projector should rebuild a HumanMessage from
        # the persisted first turn. We do not assert what the agent
        # received directly; we assert it ran cleanly without rejecting
        # the projector-built history.
        result: str = await _drain_session(session=session, text="follow up")

        assert result == "second"

    async def test_prompt_persists_replay_safe_assistant_deltas(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        agent = SloAgent(
            llm=FauxChatModel(
                responses=[FauxChatModel.assistant_message(content="final answer")],
                chunk_scripts=[
                    [
                        AIMessageChunk(
                            content=[
                                {"type": "thinking", "thinking": "reasoning"},
                                {"type": "text", "text": "partial answer"},
                            ]
                        )
                    ]
                ],
            ),
            cwd=str(tmp_path),
            tools=[],
        )
        store = FilesystemSessionHistoryStore(root=history_root)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=store,
            enable_history=True,
        )

        await _drain_session(session=session, text="hello")

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session.session_id,
        )
        delta_events: list[SessionHistoryEventDAO] = [
            event for event in events if event.kind == "assistant_delta"
        ]

        assert [event.payload.delta_kind for event in delta_events] == [
            "thinking_start",
            "thinking_delta",
            "thinking_end",  # implicit close (no content) when text block opens
            "text_start",
            "text_delta",
            "thinking_end",  # repair event from finalize_open_blocks (with completed content)
            "text_end",
        ]
        assert delta_events[1].payload.delta == "reasoning"
        assert delta_events[4].payload.delta == "partial answer"

    async def test_redacted_reasoning_persists_without_visible_replay_text(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        agent = SloAgent(
            llm=FauxChatModel(
                responses=[FauxChatModel.assistant_message(content="final answer")],
                chunk_scripts=[
                    [
                        AIMessageChunk(
                            content=[
                                {"type": "reasoning", "encrypted_content": "opaque"},
                                {"type": "text", "text": "final answer"},
                            ]
                        )
                    ]
                ],
            ),
            cwd=str(tmp_path),
            tools=[],
        )
        store = FilesystemSessionHistoryStore(root=history_root)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=store,
            enable_history=True,
        )

        await _drain_session(session=session, text="hello")

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session.session_id,
        )
        delta_events: list[SessionHistoryEventDAO] = [
            event for event in events if event.kind == "assistant_delta"
        ]

        assert [event.payload.delta_kind for event in delta_events] == [
            "thinking_start",
            "thinking_end",
            "text_start",
            "text_delta",
            "text_end",
        ]
        assert all(event.payload.redacted is True for event in delta_events[:2])
        assert all(event.payload.delta is None for event in delta_events[:2])
        assert delta_events[3].payload.delta == "final answer"

        entries = ReplayEntryProjector.build_entries(events=events)

        assistant_entries = [entry for entry in entries if entry.kind == "assistant"]
        assert [entry.answer for entry in assistant_entries] == ["final answer"]
        # Redacted reasoning must not replay as visible reasoning text.
        assert all(entry.reasoning is None for entry in assistant_entries)
        assert not any("opaque" in (entry.answer or "") for entry in entries)


class TestPersistenceFailures:
    """Persistence failures propagate; render-subscriber failures do not."""

    async def test_initial_persist_failure_aborts_run(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        session = _build_session_with_history(
            workdir=tmp_path,
            history_root=history_root,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        class _BoomStore:
            async def ensure_session(self, **_: object) -> None:
                raise RuntimeError("disk full")

            async def load_events(self, **_: object) -> list:
                return []

            async def append_event(self, **_: object) -> None:
                raise RuntimeError("disk full")

            async def session_exists(self, **_: object) -> bool:
                return False

        session._history_store = _BoomStore()  # type: ignore[assignment]
        session._history_session_ensured = False

        with pytest.raises(RuntimeError, match="disk full"):
            await _drain_session(session=session, text="hello")
        # The faux model was not consumed because the persist failed
        # before the agent loop started.
        assert session.is_running is False


class TestHistoryDisabledPath:
    """``enable_history=False`` preserves the pre-05.c session behaviour."""

    async def test_disabled_history_does_not_create_session_directory(self, tmp_path: Path) -> None:
        history_root: Path = tmp_path / "history"
        agent = SloAgent(
            llm=FauxChatModel(
                responses=[FauxChatModel.assistant_message(content="hi")],
            ),
            cwd=str(tmp_path),
            tools=[],
        )
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=FilesystemSessionHistoryStore(root=history_root),
            enable_history=False,
        )

        await _drain_session(session=session, text="hello")

        assert not (history_root / session.session_id).exists()


def _build_agent_for_history_tests(*, workdir: Path) -> "SloAgent":
    """Return a real ``SloAgent`` backed by ``FauxChatModel`` for history tests.

    Uses an empty tools list and a single no-op response so the session
    can be constructed without network credentials.

    Args:
        workdir (Path): Working directory for the agent.

    Returns:
        SloAgent: Lightweight agent suitable for unit-level history tests.
    """
    return SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        cwd=str(workdir),
        tools=[],
    )


class TestSubAgentHistoryPersistence:
    """Session persists sub-agent lifecycle events via internal subscriber (01.f)."""

    async def test_sub_agent_spawned_event_writes_history(self, tmp_path: Path) -> None:
        """A ``sub_agent_spawned`` stream event writes a ``sub_agent_spawned`` history record."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"

        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        spawned_event = AgentStreamEventDAO(
            kind="sub_agent_spawned",
            sub_agent_id="child-abc",
            task_id="t1",
        )
        await session._on_stream_event_for_history(event=spawned_event)

        store.append_event.assert_called_once()
        persisted = store.append_event.call_args.kwargs["event"]
        assert persisted.kind == "sub_agent_spawned"
        assert persisted.payload.metadata["sub_agent_id"] == "child-abc"
        assert persisted.payload.metadata["task_id"] == "t1"

    async def test_sub_agent_completed_event_writes_history(self, tmp_path: Path) -> None:
        """A ``sub_agent_completed`` stream event writes a ``sub_agent_completed`` history record."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"

        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        completed_event = AgentStreamEventDAO(
            kind="sub_agent_completed",
            sub_agent_id="child-abc",
            task_id="t1",
        )
        await session._on_stream_event_for_history(event=completed_event)

        store.append_event.assert_called_once()
        persisted = store.append_event.call_args.kwargs["event"]
        assert persisted.kind == "sub_agent_completed"
        assert persisted.payload.metadata["terminal_kind"] == "sub_agent_completed"

    async def test_sub_agent_failed_event_writes_sub_agent_completed_history(self, tmp_path: Path) -> None:
        """A ``sub_agent_failed`` stream event writes a ``sub_agent_completed`` record."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"

        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        failed_event = AgentStreamEventDAO(
            kind="sub_agent_failed",
            sub_agent_id="child-xyz",
            task_id="t2",
        )
        await session._on_stream_event_for_history(event=failed_event)

        store.append_event.assert_called_once()
        persisted = store.append_event.call_args.kwargs["event"]
        assert persisted.kind == "sub_agent_completed"
        assert persisted.payload.metadata["terminal_kind"] == "sub_agent_failed"

    async def test_orchestrator_events_do_not_write_history(self, tmp_path: Path) -> None:
        """Normal orchestrator events (``sub_agent_id=None``) produce no history write."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"

        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        normal_event = AgentStreamEventDAO(kind="text_delta", delta="x")
        await session._on_stream_event_for_history(event=normal_event)

        store.append_event.assert_not_called()

    @pytest.mark.parametrize(
        ("stream_kind", "history_kind", "extra"),
        [
            ("sub_agent_spawned", "sub_agent_spawned", {}),
            ("sub_agent_aborted", "sub_agent_completed", {"terminal_kind": "sub_agent_aborted"}),
        ],
        ids=["spawned", "terminal"],
    )
    async def test_lifecycle_audit_carries_dispatch_identity_and_stays_out_of_inference(
        self, tmp_path: Path, stream_kind: StreamEventKind, history_kind: str, extra: dict[str, str]
    ) -> None:
        """Existing audit kinds gain dispatch_id/sequence and execution_id; inference still ignores them."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.history.projector import SessionHistoryProjector

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )
        identity = {
            "dispatch_id": "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
            "dispatch_sequence": 4,
            "execution_id": "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9",
        }

        await session._on_stream_event_for_history(
            event=AgentStreamEventDAO(
                kind=stream_kind, sub_agent_id="child-abc", task_id="t1", metadata=identity
            )
        )

        persisted = store.append_event.call_args.kwargs["event"]
        assert persisted.kind == history_kind
        assert persisted.payload.metadata == {
            "sub_agent_id": "child-abc",
            "task_id": "t1",
            **extra,
            **identity,
        }
        assert SessionHistoryProjector._event_to_message(event=persisted) is None

    async def test_legacy_lifecycle_event_without_identity_keeps_old_metadata(self, tmp_path: Path) -> None:
        """An event without dispatch metadata persists exactly the released keys."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        await session._on_stream_event_for_history(
            event=AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child-abc", task_id="t1")
        )

        persisted = store.append_event.call_args.kwargs["event"]
        assert persisted.payload.metadata == {"sub_agent_id": "child-abc", "task_id": "t1"}

    async def test_dispatch_started_is_stream_only(self, tmp_path: Path) -> None:
        """The batch start event never writes history; no new history kind exists for it."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        await session._on_stream_event_for_history(
            event=AgentStreamEventDAO(
                kind="sub_agent_dispatch_started",
                metadata={
                    "orchestrator_session_id": "sess-1",
                    "dispatch_id": "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
                    "dispatch_sequence": 1,
                },
            )
        )

        store.append_event.assert_not_called()

    async def test_pool_dispatch_persists_identified_audit_and_no_start_record(self, tmp_path: Path) -> None:
        """Composed: real pool → session relay → real filesystem history (temp root).

        The admitted batch's start event is delivered to subscribers but never
        persisted; spawned/completed audits carry the same dispatch identity and
        the incarnation, and inference projection still ignores them.
        """
        from unittest.mock import patch

        from src.agents.slo_agent.history.projector import SessionHistoryProjector
        from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
        from src.agents.slo_agent.orchestrator.pool import SubAgentPool
        from src.agents.slo_agent.orchestrator.process import SubAgentProcess

        store = FilesystemSessionHistoryStore(root=tmp_path / "hist")
        await store.ensure_session(session_id="orch-1", workdir=tmp_path, model_name=None)
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="orch-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )
        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=session.event_relay,
            owner_session_id="orch-1",
            run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
            history_root=tmp_path / "hist",
        )

        async def finish(process: SubAgentProcess) -> SubAgentResultDAO:
            return process._publish_terminal(
                candidate=SubAgentResultDAO(
                    task_id=process.task.task_id,
                    session_id=process.session_id,
                    status="completed",
                    exit_code=0,
                    execution_id=process.execution_id,
                ),
                terminal_reason="completed",
                terminated_by="natural",
            )

        with patch.object(SubAgentProcess, "run", new=finish):
            await pool.dispatch(
                mode="single", tasks=[SubAgentTaskDAO(task_id="t1", prompt="x", session_id="child-1")]
            )

        snapshot = pool.attached_dispatch_snapshot()
        identity = {
            "dispatch_id": snapshot.dispatch_id,
            "dispatch_sequence": 1,
            "execution_id": snapshot.entries[0].execution_id,
        }
        events = await store.load_events(session_id="orch-1")
        audits = [event for event in events if event.kind in {"sub_agent_spawned", "sub_agent_completed"}]
        assert [event.kind for event in audits] == ["sub_agent_spawned", "sub_agent_completed"]
        assert all({key: event.payload.metadata[key] for key in identity} == identity for event in audits)
        assert not any("orchestrator_session_id" in event.payload.metadata for event in events)
        assert all(SessionHistoryProjector._event_to_message(event=event) is None for event in audits)

    async def test_internal_subscriber_is_registered_when_history_enabled(self, tmp_path: Path) -> None:
        """The internal history subscriber is registered at construction when history=True."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

        store: AsyncMock = AsyncMock(spec=FilesystemSessionHistoryStore)
        store.root = tmp_path / "hist"

        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            history_store=store,
            enable_history=True,
        )

        assert session._on_stream_event_for_history in session._subscribers

    async def test_internal_subscriber_is_not_registered_when_history_disabled(self, tmp_path: Path) -> None:
        """The internal history subscriber is NOT registered when history=False."""
        session = SloAgentSession(
            workdir=tmp_path,
            session_id="sess-1",
            agent=_build_agent_for_history_tests(workdir=tmp_path),
            enable_history=False,
        )

        assert session._on_stream_event_for_history not in session._subscribers
