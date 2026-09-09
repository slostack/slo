"""Tests for core partial tool-output snapshots."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.tools.tool_output import ToolOutputUpdateDAO


def test_tool_output_update_round_trips() -> None:
    """A display-only snapshot preserves its routing and truncation metadata."""
    snapshot: ToolOutputUpdateDAO = ToolOutputUpdateDAO(
        tool_call_id="call-1",
        tool_name="bash",
        content_snapshot="working",
        truncated=True,
        full_output_path="/tmp/output.txt",
    )

    restored: ToolOutputUpdateDAO = ToolOutputUpdateDAO.model_validate_json(snapshot.model_dump_json())

    assert restored == snapshot


def test_tool_output_update_rejects_extra_fields() -> None:
    """The cross-layer snapshot contract forbids unknown data."""
    with pytest.raises(ValidationError):
        ToolOutputUpdateDAO.model_validate(
            {
                "tool_call_id": "call-1",
                "tool_name": "bash",
                "content_snapshot": "working",
                "unexpected": True,
            }
        )
