"""Tests for the detached-workflow receive-path domain objects (spec 57.a.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    DetachedWorkflowUiEffectDAO,
    ParsedFleetUpdateDAO,
    ParsedLaunchResultDAO,
    ParsedWorkflowLifecycleMessageDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
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


_EXECUTION_ID: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"
_DISPATCH_ID: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


def _key(*, session_id: str = "child-1") -> WorkflowSessionKeyDAO:
    """Build a composite key under parent ``orch-1``."""
    return WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id=session_id)


def _child_row(**overrides: object) -> WorkflowSessionRowDAO:
    """Build a valid child row, applying field overrides."""
    fields: dict[str, object] = {
        "key": _key(),
        "workflow_id": None,
        "task_id": "t1",
        "execution_id": _EXECUTION_ID,
        "dispatch_id": _DISPATCH_ID,
        "role": "child",
        "status": "running",
        "task_text": "Fix the bug",
        "task_text_complete": False,
        "availability": "available",
    }
    fields.update(overrides)
    return WorkflowSessionRowDAO.model_validate(fields)


class TestWorkflowSessionKeyDAO:
    """The frozen ``(orchestrator_session_id, session_id)`` row identity (feature 94 a.2)."""

    def test_equal_keys_hash_equal_and_index_dicts(self) -> None:
        """Keys are value objects usable as dict keys and set members."""
        lookup: dict[WorkflowSessionKeyDAO, str] = {_key(): "row"}

        assert lookup[_key()] == "row"
        assert _key() != _key(session_id="child-2")

    @pytest.mark.parametrize(
        "fields",
        [
            {"orchestrator_session_id": "", "session_id": "child-1"},
            {"orchestrator_session_id": "orch-1", "session_id": ""},
            {"orchestrator_session_id": "orch-1", "session_id": "child-1", "extra": "x"},
        ],
        ids=["empty-parent", "empty-session", "extra-field"],
    )
    def test_key_rejects_empty_ids_and_extra_fields(self, fields: dict[str, str]) -> None:
        """Keys reject empty strings; closed schema rejects unknown fields."""
        with pytest.raises(ValidationError):
            WorkflowSessionKeyDAO.model_validate(fields)

    def test_key_is_frozen(self) -> None:
        """A captured key cannot change identity."""
        key = _key()

        with pytest.raises(ValidationError):
            key.session_id = "other"  # type: ignore[misc]


class TestWorkflowSessionRowDAO:
    """Presentation row validation; not persisted and not a status authority."""

    def test_valid_child_row_keeps_literal_fields(self) -> None:
        """Every field is stored exactly, task markup included."""
        row = _child_row(task_text="[bold]x[/bold]")

        assert (row.key, row.role, row.status, row.task_text) == (
            _key(),
            "child",
            "running",
            "[bold]x[/bold]",
        )
        assert (row.execution_id, row.dispatch_id, row.availability) == (
            _EXECUTION_ID,
            _DISPATCH_ID,
            "available",
        )

    def test_parent_row_uses_orchestrator_id_and_empty_execution(self) -> None:
        """The parent's session id equals its orchestrator id and it carries no incarnation."""
        row = _child_row(
            key=_key(session_id="orch-1"),
            role="orchestrator",
            execution_id="",
            task_id=None,
            workflow_id="wf-1",
            task_text="Orchestrator",
            task_text_complete=True,
        )

        assert (row.role, row.key.session_id, row.workflow_id) == ("orchestrator", "orch-1", "wf-1")

    def test_legacy_child_row_allows_empty_identities(self) -> None:
        """Legacy detached entries have no execution or dispatch identity."""
        row = _child_row(execution_id="", dispatch_id="", availability="stale")

        assert (row.execution_id, row.dispatch_id, row.availability) == ("", "", "stale")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"role": "orchestrator"},
            {"key": WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id="orch-1")},
            {
                "key": WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id="orch-1"),
                "role": "orchestrator",
            },
            {"role": "worker"},
            {"availability": "deleted"},
            {"execution_id": "not-a-uuid"},
            {"dispatch_id": _DISPATCH_ID.upper()},
            {"status": ""},
            {"unexpected": 1},
        ],
        ids=[
            "orchestrator-role-on-child-key",
            "child-role-on-parent-key",
            "parent-with-execution",
            "unknown-role",
            "unknown-availability",
            "non-uuid-execution",
            "non-canonical-dispatch",
            "empty-status",
            "extra-field",
        ],
    )
    def test_row_rejects_inconsistent_identity_and_closed_values(self, overrides: dict[str, object]) -> None:
        """Role must match the key shape; identities are canonical; literals are closed."""
        with pytest.raises(ValidationError):
            _child_row(**overrides)

    @pytest.mark.parametrize(
        "fields",
        [
            {
                "key": _key(session_id="orch-1"),
                "role": "orchestrator",
                "status": "running",
                "dispatch_id": _DISPATCH_ID,
                "task_text": "Orchestrator",
                "task_text_complete": True,
            },
            {
                "key": _key(),
                "role": "child",
                "task_id": "t1",
                "execution_id": _EXECUTION_ID,
                "dispatch_id": _DISPATCH_ID,
                "status": "running",
                "task_text": "Fix the bug",
                "task_text_complete": False,
            },
            {
                "key": _key(session_id="orch-1"),
                "workflow_id": "wf-1",
                "role": "orchestrator",
                "status": "running",
                "task_text": "Brief",
                "task_text_complete": True,
                "dispatch_id": _DISPATCH_ID,
            },
            {
                "key": _key(),
                "workflow_id": "wf-1",
                "task_id": "t1",
                "role": "child",
                "execution_id": _EXECUTION_ID,
                "dispatch_id": _DISPATCH_ID,
                "status": "completed",
                "task_text": "Fix the bug",
                "task_text_complete": True,
            },
        ],
        ids=["attached-parent", "attached-child", "detached-parent", "detached-child"],
    )
    def test_fresh_row_built_with_a2_construction_kwargs_is_available(
        self, fields: dict[str, object]
    ) -> None:
        """The a.2 projection sites omit availability; a fresh row defaults to ``available``."""
        row = WorkflowSessionRowDAO.model_validate(fields)

        assert row.availability == "available"

    def test_row_is_frozen(self) -> None:
        """An applied row cannot be mutated by a consumer."""
        row = _child_row()

        with pytest.raises(ValidationError):
            row.status = "completed"  # type: ignore[misc]


class TestWorkflowSessionSnapshotDAO:
    """One immutable ordered result per refresh."""

    def test_default_snapshot_is_empty_without_notice(self) -> None:
        """No rows and no notice means "hide the panel"."""
        snapshot = WorkflowSessionSnapshotDAO()

        assert (snapshot.rows, snapshot.notice) == ((), None)

    def test_snapshot_preserves_row_order_and_notice(self) -> None:
        """Rows keep service order; duplicate defense is the panel's, not the DAO's."""
        first = _child_row(key=_key(session_id="b"))
        second = _child_row(key=_key(session_id="a"))

        snapshot = WorkflowSessionSnapshotDAO(rows=(first, second), notice="Workflow list unavailable.")

        assert snapshot.rows == (first, second)
        assert snapshot.notice == "Workflow list unavailable."
        with pytest.raises(ValidationError):
            snapshot.notice = None  # type: ignore[misc]


_RUN_ID: str = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"


def _target(**overrides: object) -> ChildAbortTargetDAO:
    """Build a confirmation target for the default child key, applying overrides."""
    fields: dict[str, object] = {"key": _key(), "run_id": _RUN_ID, "execution_id": _EXECUTION_ID}
    fields.update(overrides)
    return ChildAbortTargetDAO.model_validate(fields)


def _progress(**overrides: object) -> SessionProgressSnapshotDAO:
    """Build a readable child progress snapshot, applying field overrides."""
    fields: dict[str, object] = {
        "key": _key(),
        "execution_id": _EXECUTION_ID,
        "dispatch_id": _DISPATCH_ID,
        "entries": (TranscriptEntryDAO(kind="assistant", answer="hello"),),
        "revision": "capture:1",
        "source_generation": "capture:g1",
        "availability": "available",
        "observed_at": "2026-10-18T00:00:00+00:00",
        "task_text": "Fix the bug",
        "task_text_complete": True,
        "status": "running",
    }
    fields.update(overrides)
    return SessionProgressSnapshotDAO.model_validate(fields)


class TestChildAbortTargetDAO:
    """Immutable identity captured when abort confirmation opens."""

    def test_target_is_frozen_hashable_and_canonical(self) -> None:
        """Equal targets index one dict slot and cannot be reassigned."""
        target = _target()

        assert {target: 1}[_target()] == 1
        with pytest.raises(ValidationError):
            target.run_id = _RUN_ID  # type: ignore[misc]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"run_id": "not-a-uuid"},
            {"run_id": _RUN_ID.upper()},
            {"execution_id": ""},
            {"key": WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id="orch-1")},
            {"extra": "field"},
        ],
    )
    def test_target_rejects_parent_key_bad_identity_and_extras(self, overrides: dict[str, object]) -> None:
        """Only an exact child incarnation of one run can be a confirmation target."""
        with pytest.raises(ValidationError):
            _target(**overrides)


class TestSessionProgressSnapshotDAO:
    """Bounded public progress for one selected session (feature 94 a.3)."""

    def test_defaults_carry_no_authority_or_final_read(self) -> None:
        """Read-only consumers get no abort target, no removal and no final read by default."""
        snapshot = _progress()

        assert snapshot.abort_target is None
        assert snapshot.membership_removed is False
        assert snapshot.final_read_complete is False
        assert snapshot.notice is None
        with pytest.raises(ValidationError):
            snapshot.revision = "other"  # type: ignore[misc]

    def test_matching_abort_target_is_accepted(self) -> None:
        """A target naming the snapshot's own key and execution is accepted."""
        snapshot = _progress(abort_target=_target())

        assert snapshot.abort_target == _target()

    @pytest.mark.parametrize(
        "overrides",
        [
            {"availability": "loading"},
            {"execution_id": "nope"},
            {
                "abort_target": _target(
                    key=WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id="x")
                )
            },
            {"abort_target": _target(execution_id=_DISPATCH_ID)},
            {"membership_removed": True},
            {"membership_removed": True, "entries": (), "final_read_complete": True},
            {"final_read_complete": True, "availability": "stale"},
            {
                "key": WorkflowSessionKeyDAO(orchestrator_session_id="orch-1", session_id="orch-1"),
                "execution_id": _EXECUTION_ID,
            },
            {"private": "metadata"},
        ],
    )
    def test_snapshot_rejects_inconsistent_state(self, overrides: dict[str, object]) -> None:
        """Mismatched authority, removal with content and stale final reads are refused."""
        with pytest.raises(ValidationError):
            _progress(**overrides)

    def test_removed_snapshot_is_content_free(self) -> None:
        """Authoritative removal carries no entries and keeps the fixed notice."""
        snapshot = _progress(
            entries=(),
            availability="stale",
            membership_removed=True,
            notice="Session removed from current workflow.",
        )

        assert snapshot.entries == ()
        assert snapshot.membership_removed is True
