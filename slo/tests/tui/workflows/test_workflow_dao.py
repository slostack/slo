"""Tests for the detached-workflow receive-path domain objects (spec 57.a.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.tui.workflows.dao import (
    DetachedWorkflowUiEffectDAO,
    ParsedFleetUpdateDAO,
    ParsedLaunchResultDAO,
    ParsedWorkflowLifecycleMessageDAO,
    parse_fleet_update_message,
    parse_launch_workflow_result,
    parse_workflow_lifecycle_message,
    workflow_lifecycle_target_for_kind,
)


class TestWorkflowLifecycleTargetForKind:
    """The kind → lifecycle-target lookup table."""

    def test_started_kind_maps_to_started(self) -> None:
        """``workflow_started`` targets the started path."""
        assert workflow_lifecycle_target_for_kind(kind="workflow_started") == "started"

    def test_completed_kind_maps_to_terminal(self) -> None:
        """``workflow_completed`` targets the terminal path."""
        assert workflow_lifecycle_target_for_kind(kind="workflow_completed") == "terminal"

    def test_failed_kind_maps_to_terminal(self) -> None:
        """``workflow_failed`` targets the terminal path."""
        assert workflow_lifecycle_target_for_kind(kind="workflow_failed") == "terminal"

    def test_nonworkflow_kind_maps_to_none(self) -> None:
        """Non-workflow kinds (e.g. ``workflow_phase_update``) are no-ops."""
        assert workflow_lifecycle_target_for_kind(kind="workflow_phase_update") is None
        assert workflow_lifecycle_target_for_kind(kind="monitor_update") is None


class TestParseWorkflowLifecycleMessage:
    """Inbox message → typed lifecycle payload validation."""

    def test_started_message_parses_with_running_target_state(self) -> None:
        """A well-formed ``workflow_started`` payload parses fully."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_started",
            payload={"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"},
        )

        assert parsed is not None
        assert parsed.workflow_id == "wf-1"
        assert parsed.orchestrator_session_id == "orch-1"
        assert parsed.target_state == "running"
        assert parsed.target == "started"

    def test_terminal_message_parses_with_terminal_target(self) -> None:
        """A ``workflow_failed`` payload maps to the ``failed`` terminal state."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_failed",
            payload={"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"},
        )

        assert parsed is not None
        assert parsed.target_state == "failed"
        assert parsed.target == "terminal"

    def test_nonworkflow_kind_returns_none(self) -> None:
        """A non-lifecycle kind never parses, even with a workflow payload."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_phase_update",
            payload={"workflow_id": "wf-1"},
        )

        assert parsed is None

    def test_missing_workflow_id_returns_none(self) -> None:
        """A lifecycle kind without a workflow id is ignored safely."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_started",
            payload={"orchestrator_session_id": "orch-1"},
        )

        assert parsed is None

    def test_missing_payload_returns_none(self) -> None:
        """A lifecycle kind with a ``None`` payload is ignored safely."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_started",
            payload=None,
        )

        assert parsed is None

    def test_path_unsafe_workflow_id_returns_none(self) -> None:
        """Workflow ids carrying path metas never reach durable state."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_started",
            payload={"workflow_id": "../escape", "orchestrator_session_id": "orch-1"},
        )

        assert parsed is None

    def test_missing_orchestrator_session_id_defaults_to_empty(self) -> None:
        """A payload without an orchestrator id still parses the lifecycle."""
        parsed: ParsedWorkflowLifecycleMessageDAO | None = parse_workflow_lifecycle_message(
            kind="workflow_completed",
            payload={"workflow_id": "wf-1"},
        )

        assert parsed is not None
        assert parsed.orchestrator_session_id == ""


class TestParseFleetUpdateMessage:
    """Fleet-update inbox payload validation."""

    def test_parse_fleet_update_message_round_trip(self) -> None:
        """A valid compact fleet payload preserves identity, entries, and live count."""
        parsed: ParsedFleetUpdateDAO | None = parse_fleet_update_message(
            kind="workflow_fleet_update",
            payload={
                "workflow_id": "wf-1",
                "entries": [{"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"}],
                "live_count": 1,
            },
        )

        assert parsed == ParsedFleetUpdateDAO(
            workflow_id="wf-1",
            entries=[{"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"}],
            live_count=1,
        )

    def test_parse_fleet_update_message_returns_none_for_wrong_kind(self) -> None:
        """Non-fleet inbox kinds cannot update the fleet cache."""
        assert parse_fleet_update_message(kind="workflow_started", payload={"workflow_id": "wf-1"}) is None

    def test_parse_fleet_update_message_returns_none_for_invalid_payload(self) -> None:
        """Fleet notes without a workflow id are ignored safely."""
        assert parse_fleet_update_message(kind="workflow_fleet_update", payload={"live_count": 1}) is None


class TestParseLaunchWorkflowResult:
    """``launch_workflow`` tool-result text → typed launch payload validation."""

    def test_valid_handle_json_parses(self) -> None:
        """A full handle JSON parses with workflow id and state."""
        parsed: ParsedLaunchResultDAO | None = parse_launch_workflow_result(
            result_text=(
                '{"workflow_id": "wf-9a1b", "orchestrator_session_id": "orch-1", ' '"state": "launching"}'
            ),
        )

        assert parsed is not None
        assert parsed.workflow_id == "wf-9a1b"
        assert parsed.orchestrator_session_id == "orch-1"
        assert parsed.state == "launching"

    def test_missing_state_defaults_to_launching(self) -> None:
        """A handle JSON without ``state`` seeds ``launching``."""
        parsed: ParsedLaunchResultDAO | None = parse_launch_workflow_result(
            result_text='{"orchestrator_session_id": "orch-1"}',
        )

        assert parsed is not None
        assert parsed.workflow_id == ""
        assert parsed.state == "launching"

    def test_invalid_state_value_defaults_to_launching(self) -> None:
        """An untrusted ``state`` string coerces to ``launching``."""
        parsed: ParsedLaunchResultDAO | None = parse_launch_workflow_result(
            result_text='{"orchestrator_session_id": "orch-1", "state": "bogus"}',
        )

        assert parsed is not None
        assert parsed.state == "launching"

    def test_malformed_json_returns_none(self) -> None:
        """Non-JSON tool results never launch."""
        assert parse_launch_workflow_result(result_text="not json {") is None

    def test_non_dict_json_returns_none(self) -> None:
        """A JSON array is not a launch handle."""
        assert parse_launch_workflow_result(result_text='["orch-1"]') is None

    def test_error_json_returns_none(self) -> None:
        """Error JSON (no orchestrator id) is ignored safely."""
        assert parse_launch_workflow_result(result_text='{"error": "workflow cap reached"}') is None

    def test_empty_orchestrator_session_id_returns_none(self) -> None:
        """A blank orchestrator id is not launchable."""
        assert parse_launch_workflow_result(result_text='{"orchestrator_session_id": ""}') is None


class TestDetachedWorkflowUiEffectDAO:
    """The typed UI effect contract between service and renderer."""

    def test_launch_effect_carries_typed_state(self) -> None:
        """A launch effect records the typed lifecycle state it carries."""
        effect: DetachedWorkflowUiEffectDAO = DetachedWorkflowUiEffectDAO(
            effect="launch_visualizer",
            orchestrator_session_id="orch-1",
            state="running",
        )

        assert effect.effect == "launch_visualizer"
        assert effect.orchestrator_session_id == "orch-1"
        assert effect.state == "running"

    def test_reset_effect_carries_typed_terminal_state(self) -> None:
        """A reset effect records the typed terminal state that motivated it."""
        effect: DetachedWorkflowUiEffectDAO = DetachedWorkflowUiEffectDAO(
            effect="reset_launch_guard",
            orchestrator_session_id="orch-1",
            state="completed",
        )

        assert effect.effect == "reset_launch_guard"
        assert effect.state == "completed"

    def test_invalid_state_value_is_rejected(self) -> None:
        """A bogus ``state`` string never enters a typed effect."""
        with pytest.raises(ValidationError):
            DetachedWorkflowUiEffectDAO.model_validate(
                {
                    "effect": "launch_visualizer",
                    "orchestrator_session_id": "orch-1",
                    "state": "bogus",
                }
            )
