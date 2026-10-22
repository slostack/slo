"""Pure boundary regressions required by store identity and evidence contracts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageEnvelopeDAO,
    MessageIdentityDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    canonical_submission_bytes,
)


def _submission() -> MessageSubmissionDAO:
    """Build valid immutable local intent with non-ASCII content."""
    return MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4())),
        kind="agent_input",
        text="café ☕",
    )


class TestCanonicalIdentityBytes:
    def test_canonical_utf8_sorts_complete_submission_without_ascii_escaping(self) -> None:
        """Digest and byte capacity use the exact sorted compact UTF-8 representation."""
        submission = _submission()
        expected = json.dumps(
            submission.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        assert canonical_submission_bytes(submission=submission) == expected
        assert b"\\u" not in expected

    @pytest.mark.parametrize("field", ["session_id", "generation", "channel_id"])
    def test_uuid_with_final_newline_is_invalid(self, field: str) -> None:
        """A regex end-of-line match must not accept a noncanonical pathname identity."""
        values = dict(
            kind="ui_channel", session_id=str(uuid4()), generation=str(uuid4()), channel_id=str(uuid4())
        )
        values[field] += "\n"
        with pytest.raises(ValidationError):
            MessageAddressDAO.model_validate(values)

    def test_hash_with_final_newline_is_invalid(self) -> None:
        """A tombstone digest must be exactly 64 lowercase hexadecimal characters."""
        submission = _submission()
        receipt = MessageReceiptDAO(
            message_id=submission.message_id,
            target=submission.target,
            state="accepted",
            sequence=1,
            durable=True,
            admitted_at=datetime.now(timezone.utc),
        )
        with pytest.raises(ValidationError):
            MessageIdentityDAO(
                receipt=receipt,
                sender=MessagePrincipalDAO(principal_id="owner", kind="human"),
                digest="a" * 64 + "\n",
                kind="agent_input",
                execution_generation=submission.target.generation,
            )

    def test_aware_timestamp_is_normalized_to_utc_without_changing_instant(self) -> None:
        """The on-disk timestamp is canonical UTC, not an arbitrary offset spelling."""
        submission = _submission()
        offset_time = datetime(2026, 10, 21, 10, 0, tzinfo=timezone(timedelta(hours=5)))
        envelope = MessageEnvelopeDAO(
            submission=submission,
            sender=MessagePrincipalDAO(principal_id="owner", kind="human"),
            sequence=1,
            admitted_at=offset_time,
        )
        assert envelope.admitted_at.utcoffset() == timedelta(0)
        assert envelope.admitted_at == offset_time
        assert envelope.admitted_at.isoformat() == "2026-10-21T05:00:00+00:00"

    def test_source_identifier_with_final_newline_is_invalid(self) -> None:
        """Printable source identity cannot include trailing control characters."""
        values = _submission().model_dump()
        values["workflow_id"] = "workflow\n"
        with pytest.raises(ValidationError):
            MessageSubmissionDAO.model_validate(values)
