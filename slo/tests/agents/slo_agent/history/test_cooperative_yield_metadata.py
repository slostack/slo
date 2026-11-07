"""Schema tests for the A.2 cooperative-yield diagnostic metadata carrier."""

from __future__ import annotations

from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO


def _uuid() -> str:
    """Return a fresh canonical UUID."""
    return str(uuid4())


def _group_id(*, attempt_turn_id: str, iteration: int) -> str:
    """Return the tool-group UUID5 for the same attempt and iteration."""
    return str(uuid5(namespace=UUID(attempt_turn_id), name="tool-group:" + str(iteration)))


def _build_metadata(
    *,
    attempt_turn_id: str | None = None,
    iteration: int = 4,
    **overrides: object,
) -> CooperativeYieldMetadataDAO:
    """Build valid provider-interruption metadata, applying explicit overrides."""
    attempt: str = attempt_turn_id or _uuid()
    values: dict[str, object] = {
        "run_id": _uuid(),
        "boundary_index": 0,
        "attempt_turn_id": attempt,
        "iteration": iteration,
        "urgent_high_water": 3,
        "reason": "provider",
        "disposition": "interrupted",
    }
    values.update(overrides)
    return CooperativeYieldMetadataDAO(**values)  # type: ignore[arg-type]


def test_provider_interruption_may_omit_group_identity() -> None:
    """Provider interruption is diagnostic correlation, not a tool-group claim."""
    metadata: CooperativeYieldMetadataDAO = _build_metadata()

    assert metadata.schema_version == 1
    assert metadata.group_id is None
    assert metadata.reason == "provider"
    assert metadata.disposition == "interrupted"


def test_deferred_tool_group_requires_the_canonical_group_identity() -> None:
    """A deferred tool-group notice names the exact attempt/iteration group."""
    attempt: str = _uuid()
    group: str = _group_id(attempt_turn_id=attempt, iteration=4)
    metadata: CooperativeYieldMetadataDAO = _build_metadata(
        attempt_turn_id=attempt,
        reason="noninterruptible_tool",
        disposition="deferred",
        group_id=group,
    )

    assert metadata.group_id == group

    with pytest.raises(ValidationError):
        _build_metadata(
            attempt_turn_id=attempt,
            reason="noninterruptible_tool",
            disposition="deferred",
        )


def test_optional_group_identity_must_still_match_attempt_and_iteration() -> None:
    """Supplying a group ID cannot point at another attempt or iteration."""
    attempt: str = _uuid()
    with pytest.raises(ValidationError):
        _build_metadata(
            attempt_turn_id=attempt,
            iteration=4,
            group_id=_group_id(attempt_turn_id=attempt, iteration=5),
        )
    with pytest.raises(ValidationError):
        _build_metadata(group_id="not-a-uuid")


def test_rejects_noncanonical_run_and_attempt_identities() -> None:
    """Logical run and attempt UUIDs use their canonical string form."""
    with pytest.raises(ValidationError):
        _build_metadata(run_id=_uuid().upper())
    with pytest.raises(ValidationError):
        _build_metadata(attempt_turn_id=_uuid().upper())


def test_rejects_negative_counters() -> None:
    """Boundary, iteration and high-water counters are nonnegative."""
    with pytest.raises(ValidationError):
        _build_metadata(boundary_index=-1)
    with pytest.raises(ValidationError):
        _build_metadata(iteration=-1)
    with pytest.raises(ValidationError):
        _build_metadata(urgent_high_water=-1)


def test_rejects_unknown_version_reason_or_disposition() -> None:
    """Closed vocabularies and versions fail closed."""
    with pytest.raises(ValidationError):
        _build_metadata(schema_version=2)
    with pytest.raises(ValidationError):
        _build_metadata(reason="rate_limit")
    with pytest.raises(ValidationError):
        _build_metadata(disposition="applied")


def test_rejects_diagnostic_body_and_private_anchor_fields() -> None:
    """Diagnostics carry identifiers only, never bodies or provider anchors."""
    with pytest.raises(ValidationError):
        _build_metadata(body="secret")
    with pytest.raises(ValidationError):
        _build_metadata(provider_private_anchor={"token": "secret"})


def test_carrier_is_strict_frozen_and_forbids_extra_fields() -> None:
    """The carrier rejects coercion, unknown keys and post-construction mutation."""
    with pytest.raises(ValidationError):
        _build_metadata(boundary_index="0")
    with pytest.raises(ValidationError):
        _build_metadata(unexpected_field=True)

    metadata: CooperativeYieldMetadataDAO = _build_metadata()
    with pytest.raises(ValidationError):
        metadata.iteration = 5  # type: ignore[misc]


@pytest.mark.parametrize(argnames="mismatch", argvalues=["disposition", "reason", "attempt"])
def test_stream_rejects_mismatched_cooperative_metadata(mismatch: str) -> None:
    """A stream diagnostic cannot contradict its captured typed correlation."""
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    metadata = _build_metadata(disposition="requested")
    payload = metadata.model_dump(mode="json")
    if mismatch == "disposition":
        payload["disposition"] = "interrupted"
    elif mismatch == "reason":
        payload["reason"] = "dispatch"
    attempt = _uuid() if mismatch == "attempt" else metadata.attempt_turn_id
    with pytest.raises(ValueError):
        AgentStreamEventDAO(
            kind="yield_requested",
            iteration=metadata.iteration,
            attempt_turn_id=attempt,
            metadata={"cooperative_yield_v1": payload},
        )
