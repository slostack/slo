"""Tests for ``FilesystemSessionHistoryStore`` (sub-spec 05.a §8)."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    normalize_session_name_key,
)


def _build_store(*, tmp_path: Path) -> FilesystemSessionHistoryStore:
    """Build a store rooted under ``tmp_path``.

    Args:
        tmp_path (Path): The pytest tmp_path fixture value.

    Returns:
        FilesystemSessionHistoryStore: A store scoped to the test dir.
    """
    return FilesystemSessionHistoryStore(root=tmp_path / "history")


def _build_event(
    *,
    session_id: str,
    turn_id: str,
    kind: str = "user_message",
    content: str = "hello",
) -> SessionHistoryEventDAO:
    """Build one minimal canonical event.

    Args:
        session_id (str): Owning session.
        turn_id (str): Owning turn.
        kind (str): Event kind.
        content (str): Optional payload content.

    Returns:
        SessionHistoryEventDAO: A test event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        turn_id=turn_id,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(content=content),
    )


class TestEnsureSession:
    """``ensure_session`` — directory + metadata bootstrap."""

    async def test_ensure_session_creates_private_directory_structure(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())

        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name="gpt-test",
        )

        session_dir: Path = store.root / session_id
        assert session_dir.is_dir()
        assert (session_dir / "session.json").is_file()
        dir_mode: int = stat.S_IMODE(session_dir.stat().st_mode)
        meta_mode: int = stat.S_IMODE((session_dir / "session.json").stat().st_mode)
        assert dir_mode == 0o700
        assert meta_mode == 0o600

    async def test_ensure_session_is_idempotent(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())

        first: SessionHistoryMetadataDAO = await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )
        await store.append_event(
            event=_build_event(session_id=session_id, turn_id="t1"),
        )
        second: SessionHistoryMetadataDAO = await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )

        assert second.session_id == first.session_id
        assert second.latest_sequence == 1


class TestAppendEvent:
    """``append_event`` — JSONL semantics."""

    async def test_append_event_writes_one_valid_jsonl_line(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )

        await store.append_event(
            event=_build_event(session_id=session_id, turn_id="t1", content="hi"),
        )

        events_path: Path = store.root / session_id / "events.jsonl"
        raw: str = events_path.read_text(encoding="utf-8")
        lines: list[str] = [line for line in raw.splitlines() if line.strip()]
        assert len(lines) == 1
        parsed: dict = json.loads(lines[0])
        assert parsed["session_id"] == session_id
        assert parsed["payload"]["content"] == "hi"
        assert parsed["sequence"] == 1

    async def test_append_event_increments_latest_sequence(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )

        for _ in range(3):
            await store.append_event(
                event=_build_event(session_id=session_id, turn_id="t"),
            )

        meta: SessionHistoryMetadataDAO = await store.read_metadata(
            session_id=session_id,
        )
        assert meta.latest_sequence == 3

    async def test_append_event_preserves_full_tool_output(self, tmp_path: Path) -> None:
        """Full-fidelity property: nothing in the store truncates tool output."""
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )
        large_output: str = "x" * 10_000

        event = SessionHistoryEventDAO(
            session_id=session_id,
            turn_id="t1",
            kind="tool_result",
            payload=SessionHistoryEventPayloadDAO(
                tool_name="read",
                tool_call_id="call_01",
                tool_output=large_output,
            ),
        )
        await store.append_event(event=event)

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session_id,
        )
        assert events[0].payload.tool_output == large_output

    async def test_load_events_round_trips_unicode_line_separator_inside_payload(
        self, tmp_path: Path
    ) -> None:
        """Unicode separators inside a JSON string must not split a JSONL record."""
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )
        tool_output: str = "prefix\u0085suffix"

        await store.append_event(
            event=SessionHistoryEventDAO(
                session_id=session_id,
                turn_id="t1",
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_01",
                    tool_output=tool_output,
                ),
            ),
        )

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session_id,
        )
        assert events[0].payload.tool_output == tool_output


class TestReadMetadata:
    """``read_metadata`` — round-trip."""

    async def test_read_metadata_round_trips_written_values(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())

        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name="gpt-test",
        )
        meta: SessionHistoryMetadataDAO = await store.read_metadata(
            session_id=session_id,
        )

        assert meta.session_id == session_id
        assert meta.model_name == "gpt-test"
        assert meta.latest_sequence == 0


class TestLoadEvents:
    """``load_events`` — validation + ordering."""

    async def test_load_events_validates_all_lines(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )
        for content in ["a", "b", "c"]:
            await store.append_event(
                event=_build_event(
                    session_id=session_id,
                    turn_id="t",
                    content=content,
                ),
            )

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id=session_id,
        )

        assert [e.payload.content for e in events] == ["a", "b", "c"]
        assert [e.sequence for e in events] == [1, 2, 3]

    async def test_load_events_returns_empty_for_unknown_session(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)

        events: list[SessionHistoryEventDAO] = await store.load_events(
            session_id="nope",
        )

        assert events == []


class TestRebuildTranscript:
    """``rebuild_transcript`` — derived markdown is not canonical."""

    async def test_rebuild_transcript_is_derived_from_canonical_events(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )

        path: Path = await store.rebuild_transcript(
            session_id=session_id,
            markdown="# hi\n",
        )

        assert path.read_text(encoding="utf-8") == "# hi\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestSessionNaming:
    """Session-name normalization, persistence, and reference resolution."""

    def test_normalize_session_name_key_trims_collapses_and_lowercases(self) -> None:
        """Normalization trims, lowercases, and collapses whitespace runs."""
        assert normalize_session_name_key(session_name="  Bug   TRIAGE  ") == "bug triage"

    def test_normalize_session_name_key_rejects_blank_names(self) -> None:
        """Blank-or-whitespace names are rejected."""
        with pytest.raises(ValueError, match="must not be blank"):
            normalize_session_name_key(session_name="   ")

    async def test_rename_session_persists_name_and_key(self, tmp_path: Path) -> None:
        """Renaming writes both the visible name and canonical lookup key."""
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)

        metadata: SessionHistoryMetadataDAO = await store.rename_session(
            session_id=session_id,
            session_name="  Build   Failure Triage  ",
        )

        assert metadata.session_name == "Build   Failure Triage"
        assert metadata.session_name_key == "build failure triage"
        persisted: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
        assert persisted.session_name == "Build   Failure Triage"
        assert persisted.session_name_key == "build failure triage"

    async def test_rename_session_rejects_duplicate_normalized_name(self, tmp_path: Path) -> None:
        """Two sessions cannot claim the same normalized name."""
        store = _build_store(tmp_path=tmp_path)
        first_session_id: str = str(uuid4())
        second_session_id: str = str(uuid4())
        await store.ensure_session(session_id=first_session_id, workdir=tmp_path, model_name=None)
        await store.ensure_session(session_id=second_session_id, workdir=tmp_path, model_name=None)
        await store.rename_session(session_id=first_session_id, session_name="Release Prep")

        with pytest.raises(ValueError, match="already in use"):
            await store.rename_session(
                session_id=second_session_id,
                session_name="  release   prep ",
            )

    async def test_resolve_session_reference_prefers_exact_session_id(self, tmp_path: Path) -> None:
        """Exact session-id matches win before normalized-name lookup."""
        store = _build_store(tmp_path=tmp_path)
        session_id: str = "release prep"
        await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
        await store.rename_session(session_id=session_id, session_name="Different Name")

        resolved_session_id: str = await store.resolve_session_reference(reference="release prep")

        assert resolved_session_id == session_id

    async def test_resolve_session_reference_finds_named_session(self, tmp_path: Path) -> None:
        """Normalized session-name matches resolve to the canonical session id."""
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
        await store.rename_session(session_id=session_id, session_name="Customer Import Regression")

        resolved_session_id: str = await store.resolve_session_reference(
            reference="  customer   import regression ",
        )

        assert resolved_session_id == session_id

    async def test_resolve_session_reference_rejects_unknown_reference(self, tmp_path: Path) -> None:
        """Unknown references fail with actionable copy."""
        store = _build_store(tmp_path=tmp_path)

        with pytest.raises(ValueError, match="unknown session reference: missing"):
            await store.resolve_session_reference(reference="missing")


class TestMetadataAtomicity:
    """``write_metadata`` — atomic temp+rename across repeated updates."""

    async def test_metadata_write_is_atomic_on_repeated_updates(self, tmp_path: Path) -> None:
        store = _build_store(tmp_path=tmp_path)
        session_id: str = str(uuid4())
        await store.ensure_session(
            session_id=session_id,
            workdir=tmp_path,
            model_name=None,
        )

        # Hammer the file with a sequence of writes; final read should
        # parse cleanly and reflect the last value.
        for n in range(5):
            meta: SessionHistoryMetadataDAO = await store.read_metadata(
                session_id=session_id,
            )
            meta.latest_sequence = n
            await store.write_metadata(metadata=meta)

        final: SessionHistoryMetadataDAO = await store.read_metadata(
            session_id=session_id,
        )
        assert final.latest_sequence == 4
        tmp_files: list[Path] = list(
            (store.root / session_id).glob("session.json.tmp"),
        )
        assert tmp_files == []
