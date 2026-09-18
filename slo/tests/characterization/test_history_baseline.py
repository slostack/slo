"""Characterize flat JSONL history, metadata recovery, and resume-name resolution."""

from __future__ import annotations

from pathlib import Path

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.characterization.baseline_contract import BaselineComparator
from tests.characterization.capture import baseline_case, canonical_json_bytes, loaded_baseline_ledger
from tests.characterization.normalizers import normalize_baseline_capture

_FIXTURE_PATH: Path = Path("tests/fixtures/79_tui_v2/baseline/history/flat_events_resume.json")
_CASE_ID: str = "history-flat-events-resume"


async def test_flat_events_resume_and_metadata_recovery_match_baseline(tmp_path: Path) -> None:
    """Freeze flat event order, metadata recovery, and normalized resume naming.

    WHAT: Uses the real flat filesystem store to characterize persisted event
        bytes, append sequencing, and name-based reference recovery.
    WHO: Later history replacement work consumes this fixture as source truth.
    WHEN: Before any integration work repoints generic history mechanisms.
    """
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session_id: str = "0a0b0c0d-0000-4000-8000-000000000001"
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="faux")
    await store.rename_session(session_id=session_id, session_name="  Release   Prep  ")
    await store.append_event(
        event=_event(session_id=session_id, turn_id="turn-1", kind="user_message", content="resume me")
    )
    await store.append_event(
        event=_event(
            session_id=session_id,
            turn_id="turn-1",
            kind="assistant_message",
            content="resumed response",
        )
    )
    events: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    metadata = await store.read_metadata(session_id=session_id)
    resolved_session_id: str = await store.resolve_session_reference(reference=" release prep ")
    event_bytes: bytes = (store.root / session_id / "events.jsonl").read_bytes()
    capture: dict[str, object] = {
        "event_bytes": event_bytes.decode("utf-8").splitlines(),
        "event_kinds": [event.kind for event in events],
        "event_sequences": [event.sequence for event in events],
        "metadata": {
            "latest_sequence": metadata.latest_sequence,
            "session_id": metadata.session_id,
            "session_name": metadata.session_name,
            "session_name_key": metadata.session_name_key,
        },
        "resolved_session_id": resolved_session_id,
    }
    observed: bytes = normalize_baseline_capture(
        capture=canonical_json_bytes(value=capture),
        case_id=_CASE_ID,
    )
    BaselineComparator.compare(
        case=baseline_case(case_id=_CASE_ID, artifact_relative_path="history/flat_events_resume.json"),
        observed=observed,
        expected=_FIXTURE_PATH.read_bytes(),
        ledger=loaded_baseline_ledger(),
    )


def _event(
    *,
    session_id: str,
    turn_id: str,
    kind: str,
    content: str,
) -> SessionHistoryEventDAO:
    """Build one deterministic persisted history event.

    WHAT: Provides the two source-truth event shapes for the flat-store capture.
    WHO: The history characterization calls it before the real store appends.
    WHEN: During fixture construction only.

    Args:
        session_id (str): Owner session identity.
        turn_id (str): Stable turn association.
        kind (str): Persisted event discriminator.
        content (str): Visible message payload.

    Returns:
        SessionHistoryEventDAO: Store-ready canonical event.
    """
    return SessionHistoryEventDAO(
        event_id=(
            "1a1b1c1d-0000-4000-8000-000000000001"
            if kind == "user_message"
            else "2a2b2c2d-0000-4000-8000-000000000002"
        ),
        session_id=session_id,
        turn_id=turn_id,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(content=content),
    )
