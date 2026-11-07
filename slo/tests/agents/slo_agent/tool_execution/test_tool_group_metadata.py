"""Schema tests for the A.2 tool-group history metadata carrier."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO


def _attempt_turn_id() -> str:
    """Return a fresh canonical session attempt UUID."""
    return str(uuid4())


def _group_id(*, attempt_turn_id: str, iteration: object) -> str:
    """Return the spec's canonical group UUID5 for one attempt iteration."""
    return str(uuid5(namespace=UUID(attempt_turn_id), name="tool-group:" + str(iteration)))


def _build_metadata(
    *,
    attempt_turn_id: str | None = None,
    iteration: object = 2,
    tool_call_ids: tuple[str, ...] = ("call-a", "call-b"),
    opened_at: datetime | None = None,
    **overrides: object,
) -> ToolGroupMetadataDAO:
    """Build a valid opening metadata record, applying explicit overrides."""
    attempt: str = attempt_turn_id or _attempt_turn_id()
    values: dict[str, object] = {
        "group_id": _group_id(attempt_turn_id=attempt, iteration=iteration),
        "attempt_turn_id": attempt,
        "iteration": iteration,
        "tool_call_ids": tool_call_ids,
        "opened_at": opened_at or datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ToolGroupMetadataDAO(**values)  # type: ignore[arg-type]


def test_group_identity_is_canonical_uuid5_of_attempt_and_iteration() -> None:
    """The declared group ID must equal the deterministic UUID5 derivation."""
    attempt: str = _attempt_turn_id()
    metadata: ToolGroupMetadataDAO = _build_metadata(attempt_turn_id=attempt, iteration=7)

    assert metadata.group_id == str(uuid5(namespace=UUID(attempt), name="tool-group:7"))
    assert metadata.iteration == 7


def test_rejects_group_identity_that_does_not_match_attempt_and_iteration() -> None:
    """A caller-supplied group ID cannot drift from its attempt/iteration source."""
    attempt: str = _attempt_turn_id()

    with pytest.raises(ValidationError):
        _build_metadata(
            attempt_turn_id=attempt,
            group_id=_group_id(attempt_turn_id=attempt, iteration=3),
        )


def test_rejects_noncanonical_attempt_uuid() -> None:
    """Attempt identity is the canonical lowercase UUID string, not a loose parse."""
    attempt: str = _attempt_turn_id()

    with pytest.raises(ValidationError):
        _build_metadata(
            attempt_turn_id=attempt.upper(),
            group_id=_group_id(attempt_turn_id=attempt, iteration=2),
        )


def test_defaults_are_explicit_and_versioned() -> None:
    """Opening metadata defaults to schema version 1 and no result status."""
    metadata: ToolGroupMetadataDAO = _build_metadata()

    assert metadata.schema_version == 1
    assert metadata.tool_result_status is None
    assert metadata.disposition == "opening"


def test_rejects_unknown_schema_version() -> None:
    """Unknown metadata versions fail closed."""
    with pytest.raises(ValidationError):
        _build_metadata(schema_version=2)


def test_rejects_empty_or_duplicate_call_ids() -> None:
    """A group carries a nonempty, distinct ordered call list."""
    with pytest.raises(ValidationError):
        _build_metadata(tool_call_ids=())
    with pytest.raises(ValidationError):
        _build_metadata(tool_call_ids=("call-a", "call-a"))


@pytest.mark.parametrize(
    "call_id",
    ["", "   ", "call\nnext", "call\x00", "x" * 513],
)
def test_rejects_blank_nonprintable_or_oversized_call_ids(call_id: str) -> None:
    """Call identity is bounded printable text."""
    with pytest.raises(ValidationError):
        _build_metadata(tool_call_ids=(call_id,))


def test_preserves_source_order() -> None:
    """The ordered tuple is retained exactly as supplied."""
    metadata: ToolGroupMetadataDAO = _build_metadata(tool_call_ids=("z-call", "a-call", "m-call"))

    assert metadata.tool_call_ids == ("z-call", "a-call", "m-call")


def test_rejects_naive_or_non_utc_opened_at() -> None:
    """Opening time is aware UTC, established once by the producer."""
    with pytest.raises(ValidationError):
        _build_metadata(opened_at=datetime(2026, 11, 4, 12, 0))
    with pytest.raises(ValidationError):
        _build_metadata(
            opened_at=datetime(
                2026,
                11,
                4,
                12,
                0,
                tzinfo=timezone(timedelta(hours=1)),
            )
        )


def test_result_status_is_allowed_only_on_opening_disposition() -> None:
    """A no-start disposition never invents a tool result status."""
    opening: ToolGroupMetadataDAO = _build_metadata(tool_result_status="error")
    assert opening.tool_result_status == "error"

    with pytest.raises(ValidationError):
        _build_metadata(disposition="not_started", tool_result_status="success")
    with pytest.raises(ValidationError):
        _build_metadata(tool_result_status="unknown")


def test_no_start_disposition_omits_status() -> None:
    """Affirmative no-start metadata carries no invented result."""
    metadata: ToolGroupMetadataDAO = _build_metadata(disposition="not_started")

    assert metadata.disposition == "not_started"
    assert metadata.tool_result_status is None


def test_carrier_is_strict_frozen_and_forbids_extra_fields() -> None:
    """The carrier rejects coercion, unknown keys and post-construction mutation."""
    with pytest.raises(ValidationError):
        _build_metadata(iteration="2")
    with pytest.raises(ValidationError):
        _build_metadata(unexpected_field=True)

    metadata: ToolGroupMetadataDAO = _build_metadata()
    with pytest.raises(ValidationError):
        metadata.iteration = 3  # type: ignore[misc]
