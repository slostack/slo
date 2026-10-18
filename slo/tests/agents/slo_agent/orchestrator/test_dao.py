"""Tests for orchestrator domain DAOs (sub-spec 01-sub-agents 01.b)."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    ChildExecutionEvidenceDAO,
    DispatchIdentityDAO,
    ExecutionIndexDAO,
    ResolvedDispatchTaskDAO,
    StdoutCaptureIdentityDAO,
    FleetSnapshotDAO,
    build_cleanup_summary,
    project_fleet_entries,
    OrchestratorResultDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
)
from tests.agents.slo_agent.orchestrator.released_schemas import (
    ReleasedFleetSnapshotDAO,
    ReleasedSubAgentResultDAO,
    ReleasedSubAgentStatusDAO,
)


class TestSubAgentTaskDAO:
    """``SubAgentTaskDAO`` construction and validation."""

    def test_required_fields_accepted(self) -> None:
        """Minimal construction with only required fields succeeds."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(task_id="t1", prompt="Do something.")

        assert task.task_id == "t1"
        assert task.prompt == "Do something."
        assert task.cwd is None
        assert task.model is None

    def test_optional_overrides_accepted(self) -> None:
        """``cwd`` and ``model`` fields are stored correctly when supplied."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t2",
            prompt="Do {previous}.",
            cwd="/tmp/work",
            model="claude-opus-4-5",
        )

        assert task.cwd == "/tmp/work"
        assert task.model == "claude-opus-4-5"

    def test_rejects_extra_fields(self) -> None:
        """Extra fields raise ``ValidationError`` due to ``extra='forbid'``."""
        with pytest.raises(ValidationError):
            SubAgentTaskDAO(task_id="t1", prompt="x", unexpected="y")  # type: ignore[call-arg]

    def test_reasoning_level_accepted(self) -> None:
        """``reasoning_level`` stores a valid ``ReasoningLevel`` literal."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t3",
            prompt="Think deeply.",
            reasoning_level="high",
        )

        assert task.reasoning_level == "high"

    def test_reasoning_level_defaults_to_none(self) -> None:
        """``reasoning_level`` defaults to ``None`` when not provided."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(task_id="t1", prompt="x")

        assert task.reasoning_level is None

    def test_resume_session_reference_accepted(self) -> None:
        """``resume_session_reference`` stores the session reference string."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t4",
            prompt="Continue.",
            resume_session_reference="my-session-ref",
        )

        assert task.resume_session_reference == "my-session-ref"

    def test_session_id_accepted(self) -> None:
        """``session_id`` stores the explicit id string."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t5",
            prompt="Run.",
            session_id="my-child-sess-01",
        )

        assert task.session_id == "my-child-sess-01"

    def test_enable_history_accepted(self) -> None:
        """``enable_history`` stores True, False, and None correctly."""
        for value in (True, False, None):
            task: SubAgentTaskDAO = SubAgentTaskDAO(
                task_id="t6",
                prompt="Run.",
                enable_history=value,
            )
            assert task.enable_history == value

    def test_resume_and_session_id_together_raises(self) -> None:
        """Supplying both ``resume_session_reference`` and ``session_id`` raises ``ValidationError``."""
        with pytest.raises(ValidationError, match="mutually exclusive"):
            SubAgentTaskDAO(
                task_id="t7",
                prompt="Run.",
                resume_session_reference="ref-abc",
                session_id="id-xyz",
            )


class TestSubAgentTaskDAOHistoryCoercion:
    """``resume_session_reference`` implies ``enable_history=True``."""

    def test_enable_history_coerced_to_true_when_resume_reference_set(self) -> None:
        """``enable_history`` is forced to ``True`` when ``resume_session_reference`` is set."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t8",
            prompt="Resume.",
            resume_session_reference="my-session-ref",
        )

        assert task.enable_history is True

    def test_enable_history_false_coerced_to_true_when_resume_reference_set(self) -> None:
        """``enable_history=False`` is upgraded to ``True`` when ``resume_session_reference`` is set."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t9",
            prompt="Resume.",
            resume_session_reference="my-session-ref",
            enable_history=False,
        )

        assert task.enable_history is True

    def test_existing_true_enable_history_preserved_when_resume_reference_set(self) -> None:
        """``enable_history=True`` is preserved unchanged when ``resume_session_reference`` is set."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t10",
            prompt="Resume.",
            resume_session_reference="my-session-ref",
            enable_history=True,
        )

        assert task.enable_history is True

    def test_enable_history_not_coerced_when_no_resume_reference(self) -> None:
        """``enable_history`` is left as ``None`` when ``resume_session_reference`` is not set."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t11",
            prompt="Run.",
        )

        assert task.enable_history is None

    def test_enable_history_false_preserved_when_no_resume_reference(self) -> None:
        """``enable_history=False`` is left unchanged when ``resume_session_reference`` is not set."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t12",
            prompt="Run.",
            enable_history=False,
        )

        assert task.enable_history is False


class TestSubAgentStatusDAO:
    """``SubAgentStatusDAO`` defaults and status values."""

    def test_defaults_to_pending_status(self) -> None:
        """Default status is ``pending`` when not supplied."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
        )

        assert dao.status == "pending"
        assert dao.last_text is None
        assert dao.prompt_preview == ""

    def test_all_status_literals_accepted(self) -> None:
        """All five ``SubAgentStatus`` literals are valid status values."""
        for status in ("pending", "running", "completed", "failed", "aborted"):
            dao: SubAgentStatusDAO = SubAgentStatusDAO(
                task_id="t1",
                session_id="s1",
                status=status,  # type: ignore[arg-type]
            )
            assert dao.status == status

    def test_accepts_durable_process_and_cleanup_fields(self) -> None:
        """Fleet entries retain process identity and terminal cleanup evidence."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            pid=123,
            started_at=10.0,
            heartbeat_phase="streaming",
            exit_code=0,
            terminal_reason="completed",
            terminated_by="natural",
        )

        assert dao.pid == 123
        assert dao.started_at == 10.0
        assert dao.heartbeat_phase == "streaming"
        assert dao.exit_code == 0
        assert dao.terminal_reason == "completed"
        assert dao.terminated_by == "natural"


class TestFleetSnapshotDAO:
    """``FleetSnapshotDAO`` durable envelope behavior."""

    def test_preserves_orchestrator_identity_and_ordered_entries(self) -> None:
        """Snapshots serialize the owner, optional workflow, and fleet order."""
        entry: SubAgentStatusDAO = SubAgentStatusDAO(task_id="t1", session_id="s1")
        snapshot: FleetSnapshotDAO = FleetSnapshotDAO(
            orchestrator_session_id="orchestrator-1",
            workflow_id="workflow-1",
            entries=[entry],
            updated_at="2026-09-06T00:00:00+00:00",
        )

        assert snapshot.orchestrator_session_id == "orchestrator-1"
        assert snapshot.workflow_id == "workflow-1"
        assert snapshot.entries == [entry]


class TestSubAgentStatusDAOLiveness:
    """``SubAgentStatusDAO.liveness`` read-time classifications."""

    def test_liveness_returns_healthy_for_terminal_status(self) -> None:
        """Terminal entries classify as healthy without activity timestamps."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            status="completed",
        )

        assert dao.liveness(now_seconds=100.0, heartbeat_seconds=15.0, inactivity_seconds=7200.0) == "healthy"

    def test_liveness_returns_healthy_when_heartbeat_fresh(self) -> None:
        """A running entry with a fresh heartbeat classifies as healthy."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            status="running",
            last_heartbeat_at=60.0,
        )

        assert dao.liveness(now_seconds=100.0, heartbeat_seconds=15.0, inactivity_seconds=7200.0) == "healthy"

    def test_liveness_returns_degraded_when_only_stdout_fresh(self) -> None:
        """A stale heartbeat and recent stdout classify as degraded."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            status="running",
            last_heartbeat_at=50.0,
            last_stdout_at=99.0,
        )

        assert (
            dao.liveness(now_seconds=100.0, heartbeat_seconds=15.0, inactivity_seconds=7200.0) == "degraded"
        )

    def test_liveness_returns_silent_when_nothing_fresh(self) -> None:
        """Stale heartbeat and stdout classify as silent."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            status="running",
            last_heartbeat_at=50.0,
            last_stdout_at=1.0,
        )

        assert dao.liveness(now_seconds=100.0, heartbeat_seconds=15.0, inactivity_seconds=10.0) == "silent"

    def test_liveness_returns_degraded_when_no_heartbeat_seen(self) -> None:
        """Recent stdout without a heartbeat still classifies as degraded."""
        dao: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1",
            session_id="s1",
            status="running",
            last_stdout_at=99.0,
        )

        assert (
            dao.liveness(now_seconds=100.0, heartbeat_seconds=15.0, inactivity_seconds=7200.0) == "degraded"
        )


class TestFleetReporting:
    """Compact fleet projections and terminal cleanup summaries."""

    def test_project_fleet_entries_counts_running(self) -> None:
        """The note projection keeps compact fields and counts running entries."""
        entries: list[SubAgentStatusDAO] = [
            SubAgentStatusDAO(task_id="t1", session_id="s1", status="running", heartbeat_phase="streaming"),
            SubAgentStatusDAO(task_id="t2", session_id="s2", status="completed"),
        ]

        projected, live_count = project_fleet_entries(entries=entries)

        assert projected == [
            {"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"},
            {"task_id": "t2", "status": "completed", "heartbeat_phase": ""},
        ]
        assert live_count == 1

    @pytest.mark.parametrize(
        ("reason", "label"),
        [
            ("completed", "completed"),
            ("failed", "failed"),
            ("operator_abort", "aborted (operator)"),
            ("orchestrator_died", "died with orchestrator"),
            ("reaped_orphan", "reaped orphan"),
        ],
    )
    def test_build_cleanup_summary_labels_reason(self, reason: str, label: str) -> None:
        """Each terminal reason maps to its operator-facing cleanup label."""
        entries: list[SubAgentStatusDAO] = [
            SubAgentStatusDAO(
                task_id="t1",
                session_id="s1",
                status="completed",
                terminal_reason=reason,  # type: ignore[arg-type]
            )
        ]

        summary: str = build_cleanup_summary(entries=entries, live_count=0)

        assert summary == f"fleet: 1 {label} · 0 live"

    def test_build_cleanup_summary_handles_empty_fleet(self) -> None:
        """An empty terminal snapshot still gives the operator a zero-live line."""
        assert build_cleanup_summary(entries=[], live_count=0) == "fleet: 0 live"


class TestSubAgentResultDAO:
    """``SubAgentResultDAO`` defaults and serialisation."""

    def test_defaults(self) -> None:
        """Default values are correct for optional fields."""
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t1",
            session_id="s1",
            status="completed",
        )

        assert result.answer == ""
        assert result.exit_code == -1
        assert result.usage == {}

    def test_serialisation_round_trip(self) -> None:
        """DAO survives ``model_dump_json`` / ``model_validate_json`` round-trip."""
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t1",
            session_id="s1",
            status="failed",
            answer="error msg",
            exit_code=1,
        )
        raw: str = result.model_dump_json()
        recovered: SubAgentResultDAO = SubAgentResultDAO.model_validate_json(raw)

        assert recovered == result


class TestOrchestratorResultDAO:
    """``OrchestratorResultDAO`` construction and JSON output."""

    def test_all_completed_defaults_true(self) -> None:
        """Default value for ``all_completed`` is ``True``."""
        dao: OrchestratorResultDAO = OrchestratorResultDAO(mode="parallel")

        assert dao.all_completed is True
        assert dao.failed_task_ids == []

    def test_failed_task_ids_populated(self) -> None:
        """Failed task ids are recorded and ``all_completed`` is ``False``."""
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t2",
            session_id="s2",
            status="failed",
            exit_code=1,
        )
        dao: OrchestratorResultDAO = OrchestratorResultDAO(
            mode="chain",
            results=[result],
            all_completed=False,
            failed_task_ids=["t2"],
        )

        assert "t2" in dao.failed_task_ids
        assert dao.all_completed is False

    def test_serialises_to_valid_json_for_llm(self) -> None:
        """``model_dump_json()`` produces valid JSON the LLM can parse."""
        dao: OrchestratorResultDAO = OrchestratorResultDAO(mode="single")
        raw: str = dao.model_dump_json()
        parsed: dict = json.loads(raw)

        assert parsed["mode"] == "single"
        assert isinstance(parsed["results"], list)

    def test_all_modes_accepted(self) -> None:
        """All three ``SubAgentMode`` literals are valid ``mode`` values."""
        for mode in ("parallel", "chain", "single"):
            dao: OrchestratorResultDAO = OrchestratorResultDAO(mode=mode)  # type: ignore[arg-type]
            assert dao.mode == mode


class TestSubAgentTaskDAOSystemPrompt:
    """``SubAgentTaskDAO.system_prompt`` field."""

    def test_sub_agent_task_dao_accepts_system_prompt(self) -> None:
        """``system_prompt`` field is stored when supplied."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t-sp1",
            prompt="Run.",
            system_prompt="You are a test-writing agent.",
        )
        assert task.system_prompt == "You are a test-writing agent."

    def test_sub_agent_task_dao_system_prompt_defaults_to_none(self) -> None:
        """``system_prompt`` defaults to ``None`` when not provided."""
        task: SubAgentTaskDAO = SubAgentTaskDAO(task_id="t-sp2", prompt="Run.")
        assert task.system_prompt is None

    def test_sub_agent_task_dao_extra_forbid_still_applies(self) -> None:
        """``extra='forbid'`` still rejects unknown fields after adding ``system_prompt``."""
        with pytest.raises(ValidationError):
            SubAgentTaskDAO(
                task_id="t-sp3",
                prompt="Run.",
                unknown_extra_field="oops",  # type: ignore[call-arg]
            )


# ── Feature 94 T02: runtime execution identity and versioned evidence ─────────

_EXECUTION_ID: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"
_DISPATCH_ID: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_REQUEST_ID: str = "c3b2a190-8e7d-4c6b-9a58-473625140f0e"
_STATUS_DIGEST: str = "a" * 64
_CONTEXT_DIGEST: str = "b" * 64


class TestReleasedWireSchemas:
    """Runtime execution identity never leaks into released closed wire schemas."""

    def test_status_and_fleet_dump_decode_with_released_readers(self) -> None:
        """A fleet entry carrying execution_id serializes to the released fleet shape."""
        entry: SubAgentStatusDAO = SubAgentStatusDAO(
            task_id="t1", session_id="child-1", status="running", execution_id=_EXECUTION_ID
        )
        snapshot: FleetSnapshotDAO = FleetSnapshotDAO(
            orchestrator_session_id="orch-1", entries=[entry], updated_at="2026-10-18T00:00:00+00:00"
        )

        raw: str = snapshot.model_dump_json(indent=2)

        assert "execution_id" not in raw
        decoded: ReleasedFleetSnapshotDAO = ReleasedFleetSnapshotDAO.model_validate_json(raw)
        assert decoded.entries[0].session_id == "child-1"
        assert entry.execution_id == _EXECUTION_ID

    def test_result_dump_decodes_with_released_reader(self) -> None:
        """A terminal result carrying execution_id serializes to the released status shape."""
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t1",
            session_id="child-1",
            status="completed",
            answer="ok",
            exit_code=0,
            execution_id=_EXECUTION_ID,
        )

        raw: str = result.model_dump_json(indent=2)

        assert "execution_id" not in raw
        assert ReleasedSubAgentResultDAO.model_validate_json(raw).answer == "ok"

    def test_current_wire_fields_match_released_fields(self) -> None:
        """Only excluded runtime fields may differ from the released field sets."""
        pairs: list[tuple[type[BaseModel], type[BaseModel]]] = [
            (SubAgentStatusDAO, ReleasedSubAgentStatusDAO),
            (SubAgentResultDAO, ReleasedSubAgentResultDAO),
            (FleetSnapshotDAO, ReleasedFleetSnapshotDAO),
        ]
        for current, released in pairs:
            wire: set[str] = {name for name, field in current.model_fields.items() if not field.exclude}
            assert wire == set(released.model_fields), current.__name__

    def test_runtime_execution_id_defaults_empty_for_legacy_rows(self) -> None:
        """Legacy rows without identity remain readable with an empty execution_id."""
        entry: SubAgentStatusDAO = SubAgentStatusDAO.model_validate_json(
            '{"task_id": "t1", "session_id": "child-1"}'
        )

        assert entry.execution_id == ""

    def test_runtime_execution_id_rejects_non_uuid(self) -> None:
        """A non-empty runtime identity must be a canonical UUID."""
        with pytest.raises(ValidationError):
            SubAgentResultDAO(task_id="t1", session_id="s", status="failed", execution_id="not-a-uuid")

    def test_runtime_execution_id_accepts_explicit_empty_legacy_value(self) -> None:
        """An explicitly passed empty identity runs the validator and stays the legacy value."""
        status: SubAgentStatusDAO = SubAgentStatusDAO(task_id="t1", session_id="s", execution_id="")
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t1", session_id="s", status="failed", execution_id=""
        )

        assert (status.execution_id, result.execution_id) == ("", "")


class TestChildExecutionEvidenceDAO:
    """Versioned sibling evidence owns the persisted incarnation phases."""

    def test_pending_then_running_then_terminal_transitions(self) -> None:
        """Each phase transition returns a new frozen value with phase-specific evidence."""
        pending: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.pending(
            session_id="child-1", execution_id=_EXECUTION_ID, dispatch_id=_DISPATCH_ID
        )
        running: ChildExecutionEvidenceDAO = pending.running(
            stdout_identity=StdoutCaptureIdentityDAO(device=1, inode=2),
            spawn_context_sha256=_CONTEXT_DIGEST,
        )
        terminal: ChildExecutionEvidenceDAO = running.terminal(
            status="completed", status_sha256=_STATUS_DIGEST
        )

        assert (pending.phase, pending.status, pending.stdout_identity) == ("pending", "pending", None)
        assert (running.phase, running.status) == ("running", "running")
        assert running.stdout_identity == StdoutCaptureIdentityDAO(device=1, inode=2)
        assert (terminal.phase, terminal.status, terminal.status_sha256) == (
            "terminal",
            "completed",
            _STATUS_DIGEST,
        )
        assert terminal.stdout_identity == running.stdout_identity
        assert terminal.execution_id == pending.execution_id == _EXECUTION_ID

    def test_pending_terminal_without_spawn_has_no_stdout_identity(self) -> None:
        """A pending abort publishes terminal status evidence with no capture identity."""
        terminal: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.pending(
            session_id="child-1", execution_id=_EXECUTION_ID, dispatch_id=_DISPATCH_ID
        ).terminal(status="aborted", status_sha256=_STATUS_DIGEST)

        assert terminal.stdout_identity is None
        assert terminal.spawn_context_sha256 is None

    def test_every_phase_keeps_the_admitting_dispatch(self) -> None:
        """Running and terminal evidence copy the dispatch identity from pending."""
        terminal: ChildExecutionEvidenceDAO = (
            ChildExecutionEvidenceDAO.pending(
                session_id="child-1", execution_id=_EXECUTION_ID, dispatch_id=_DISPATCH_ID
            )
            .running(stdout_identity=None, spawn_context_sha256=None)
            .terminal(status="completed", status_sha256=_STATUS_DIGEST)
        )

        assert terminal.dispatch_id == _DISPATCH_ID

    def test_pending_requires_a_dispatch_identity(self) -> None:
        """Registration evidence cannot be built without the admitting dispatch."""
        with pytest.raises(TypeError):
            ChildExecutionEvidenceDAO.pending(  # type: ignore[call-arg]
                session_id="child-1", execution_id=_EXECUTION_ID
            )

    @pytest.mark.parametrize("dispatch_id", ["batch-1", _DISPATCH_ID.upper(), ""])
    def test_non_canonical_dispatch_identity_is_rejected(self, dispatch_id: str) -> None:
        """A present dispatch identity must be a canonical UUID like every other holder."""
        with pytest.raises(ValidationError):
            ChildExecutionEvidenceDAO.pending(
                session_id="child-1", execution_id=_EXECUTION_ID, dispatch_id=dispatch_id
            )

    def test_sibling_without_dispatch_identity_still_parses(self) -> None:
        """Readers accept an earlier sibling that predates dispatch metadata."""
        evidence: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.model_validate(
            {"session_id": "child-1", "execution_id": _EXECUTION_ID, "phase": "pending", "status": "pending"}
        )

        assert evidence.dispatch_id is None

    def test_frozen(self) -> None:
        """Evidence values cannot be mutated in place."""
        evidence = ChildExecutionEvidenceDAO.pending(
            session_id="child-1", execution_id=_EXECUTION_ID, dispatch_id=_DISPATCH_ID
        )

        with pytest.raises(ValidationError):
            evidence.phase = "running"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "payload",
        [
            {"phase": "pending", "status": "running"},
            {"phase": "running", "status": "running", "status_sha256": _STATUS_DIGEST},
            {"phase": "terminal", "status": "completed"},
            {"phase": "terminal", "status": "running", "status_sha256": _STATUS_DIGEST},
            {"phase": "pending", "status": "pending", "spawn_context_sha256": _CONTEXT_DIGEST},
            {"phase": "running", "status": "running", "spawn_context_sha256": "xyz"},
            {"phase": "pending", "status": "pending", "extra": 1},
        ],
    )
    def test_rejects_inconsistent_phase_evidence(self, payload: dict[str, object]) -> None:
        """Phase, status and digests must agree before evidence can be constructed."""
        with pytest.raises(ValidationError):
            ChildExecutionEvidenceDAO.model_validate(
                {"schema_version": 1, "session_id": "child-1", "execution_id": _EXECUTION_ID, **payload}
            )

    @pytest.mark.parametrize("session_id", ["", "../x", "a/b", "a\\b", ".."])
    def test_rejects_unsafe_session_id(self, session_id: str) -> None:
        """Session identity must be a safe path slug before it addresses evidence."""
        with pytest.raises(ValidationError):
            ChildExecutionEvidenceDAO.pending(
                session_id=session_id, execution_id=_EXECUTION_ID, dispatch_id=_DISPATCH_ID
            )

    @pytest.mark.parametrize("execution_id", ["", "abc", _EXECUTION_ID.upper(), "{" + _EXECUTION_ID + "}"])
    def test_rejects_non_canonical_execution_id(self, execution_id: str) -> None:
        """Execution identity is a strictly parsed canonical UUID."""
        with pytest.raises(ValidationError):
            ChildExecutionEvidenceDAO.pending(
                session_id="child-1", execution_id=execution_id, dispatch_id=_DISPATCH_ID
            )

    def test_rejects_unknown_schema_version(self) -> None:
        """Only schema version 1 is readable by this owner."""
        with pytest.raises(ValidationError):
            ChildExecutionEvidenceDAO.model_validate(
                {
                    "schema_version": 2,
                    "session_id": "child-1",
                    "execution_id": _EXECUTION_ID,
                    "phase": "pending",
                    "status": "pending",
                }
            )


class TestExecutionIndexDAO:
    """The execution index maps current fleet sessions to their incarnations."""

    def test_valid_index_round_trips(self) -> None:
        """A run-scoped index survives JSON round trip."""
        index: ExecutionIndexDAO = ExecutionIndexDAO(
            orchestrator_session_id="orch-1",
            run_id=_RUN_ID,
            executions={"child-1": _EXECUTION_ID},
            updated_at="2026-10-18T00:00:00+00:00",
        )

        assert ExecutionIndexDAO.model_validate_json(index.model_dump_json()) == index

    @pytest.mark.parametrize(
        "update",
        [{"run_id": "nope"}, {"executions": {"../x": _EXECUTION_ID}}, {"executions": {"child-1": "nope"}}],
    )
    def test_rejects_invalid_identity(self, update: dict[str, object]) -> None:
        """Unsafe session keys and non-UUID identities are refused."""
        payload: dict[str, object] = {
            "orchestrator_session_id": "orch-1",
            "run_id": _RUN_ID,
            "executions": {"child-1": _EXECUTION_ID},
            "updated_at": "now",
            **update,
        }
        with pytest.raises(ValidationError):
            ExecutionIndexDAO.model_validate(payload)


class TestChildControlDAOs:
    """Child-control request, outcome and capability structures (no capability yet)."""

    def _request_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "request_id": _REQUEST_ID,
            "owner_session_id": "owner-1",
            "orchestrator_session_id": "orch-1",
            "session_id": "child-1",
            "run_id": _RUN_ID,
            "execution_id": _EXECUTION_ID,
        }

    def test_request_accepts_exact_identity(self) -> None:
        """A complete request carries only safe IDs and strict UUIDs."""
        request: ChildAbortRequestDAO = ChildAbortRequestDAO.model_validate(self._request_payload())

        assert request.execution_id == _EXECUTION_ID

    @pytest.mark.parametrize(
        "update",
        [
            {"request_id": "x"},
            {"run_id": "x"},
            {"execution_id": "x"},
            {"session_id": "../child"},
            {"owner_session_id": ""},
            {"orchestrator_session_id": "a/b"},
            {"pid": 123},
            {"schema_version": 2},
        ],
    )
    def test_request_rejects_unsafe_or_extra_fields(self, update: dict[str, object]) -> None:
        """No PID, prompt, path or malformed identity can enter a request."""
        with pytest.raises(ValidationError):
            ChildAbortRequestDAO.model_validate({**self._request_payload(), **update})

    def test_request_is_frozen(self) -> None:
        """Requests are immutable once validated."""
        request = ChildAbortRequestDAO.model_validate(self._request_payload())

        with pytest.raises(ValidationError):
            request.session_id = "other"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "outcome", ["requested", "aborted", "already_terminal", "not_owned", "unavailable", "unresolved"]
    )
    def test_outcome_accepts_each_literal(self, outcome: str) -> None:
        """Each closed outcome literal is accepted with a fixed safe message."""
        dao: ChildAbortOutcomeDAO = ChildAbortOutcomeDAO(
            request_id=_REQUEST_ID,
            session_id="child-1",
            execution_id=_EXECUTION_ID,
            outcome=outcome,  # type: ignore[arg-type]
            safe_message="fixed",
        )

        assert dao.outcome == outcome

    def test_outcome_rejects_unknown_literal_and_status(self) -> None:
        """Unknown outcomes and non-status terminal values are refused."""
        with pytest.raises(ValidationError):
            ChildAbortOutcomeDAO(
                request_id=_REQUEST_ID,
                session_id="child-1",
                execution_id=_EXECUTION_ID,
                outcome="done",  # type: ignore[arg-type]
                safe_message="x",
            )
        with pytest.raises(ValidationError):
            ChildAbortOutcomeDAO(
                request_id=_REQUEST_ID,
                session_id="child-1",
                execution_id=_EXECUTION_ID,
                outcome="aborted",
                terminal_status="gone",  # type: ignore[arg-type]
                safe_message="x",
            )

    def test_capability_validates_identity(self) -> None:
        """Capabilities carry strict run identity and an accepting flag."""
        capability: ChildControlCapabilityDAO = ChildControlCapabilityDAO(
            run_id=_RUN_ID, owner_session_id="owner-1", orchestrator_session_id="orch-1", accepting=True
        )

        assert capability.schema_version == 1
        with pytest.raises(ValidationError):
            ChildControlCapabilityDAO(
                run_id="x", owner_session_id="owner-1", orchestrator_session_id="orch-1", accepting=True
            )


_DISPATCH_EXECUTION_ID: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"


class TestDispatchDAOs:
    """Feature 94 a.2 dispatch identity, resolution and attached-snapshot DAOs."""

    def test_dispatch_identity_builds_exact_event_metadata(self) -> None:
        """Start metadata has exactly three keys; lifecycle metadata adds the incarnation."""
        identity = DispatchIdentityDAO(dispatch_id=_DISPATCH_ID, dispatch_sequence=3)

        assert identity.started_metadata(orchestrator_session_id="orch-1") == {
            "orchestrator_session_id": "orch-1",
            "dispatch_id": _DISPATCH_ID,
            "dispatch_sequence": 3,
        }
        assert identity.lifecycle_metadata(execution_id=_DISPATCH_EXECUTION_ID) == {
            "dispatch_id": _DISPATCH_ID,
            "dispatch_sequence": 3,
            "execution_id": _DISPATCH_EXECUTION_ID,
        }

    @pytest.mark.parametrize(
        "fields",
        [
            {"dispatch_id": "not-a-uuid", "dispatch_sequence": 1},
            {"dispatch_id": _DISPATCH_ID.upper(), "dispatch_sequence": 1},
            {"dispatch_id": _DISPATCH_ID, "dispatch_sequence": 0},
            {"dispatch_id": _DISPATCH_ID, "dispatch_sequence": 1, "extra": 1},
        ],
        ids=["non-uuid", "non-canonical", "sequence-zero", "extra-field"],
    )
    def test_dispatch_identity_rejects_invalid_fields(self, fields: dict[str, object]) -> None:
        """An admitted dispatch always has a canonical UUID and a positive sequence."""
        with pytest.raises(ValidationError):
            DispatchIdentityDAO.model_validate(fields)

    def test_dispatch_identity_is_frozen(self) -> None:
        """Captured identity cannot be mutated after admission."""
        identity = DispatchIdentityDAO(dispatch_id=_DISPATCH_ID, dispatch_sequence=1)

        with pytest.raises(ValidationError):
            identity.dispatch_sequence = 2  # type: ignore[misc]

    def test_resolved_task_keeps_task_and_safe_session(self) -> None:
        """Resolution pairs the original task with its single resolved session."""
        task = SubAgentTaskDAO(task_id="t1", prompt="x")

        resolved = ResolvedDispatchTaskDAO(task=task, session_id="child-1")

        assert (resolved.task, resolved.session_id) == (task, "child-1")

    @pytest.mark.parametrize("session_id", ["", "..", "a/b", "../x", "."])
    def test_resolved_task_rejects_unsafe_session(self, session_id: str) -> None:
        """A resolved session must be a safe path component before admission."""
        with pytest.raises(ValidationError):
            ResolvedDispatchTaskDAO(task=SubAgentTaskDAO(task_id="t1", prompt="x"), session_id=session_id)

    def test_empty_attached_snapshot_denotes_no_dispatch(self) -> None:
        """The explicit empty value has no identity, sequence zero and no entries."""
        empty = AttachedDispatchSnapshotDAO.empty()

        assert (empty.dispatch_id, empty.dispatch_sequence, empty.entries) == ("", 0, ())

    def test_attached_snapshot_carries_entries_as_tuple(self) -> None:
        """Entries are an ordered immutable tuple of status copies."""
        entry = SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_DISPATCH_EXECUTION_ID)

        snapshot = AttachedDispatchSnapshotDAO(
            dispatch_id=_DISPATCH_ID, dispatch_sequence=1, entries=(entry,)
        )

        assert snapshot.entries == (entry,)
        with pytest.raises(ValidationError):
            snapshot.dispatch_sequence = 2  # type: ignore[misc]

    @pytest.mark.parametrize(
        "fields",
        [
            {"dispatch_id": "", "dispatch_sequence": 1},
            {"dispatch_id": _DISPATCH_ID, "dispatch_sequence": 0},
            {"dispatch_id": "", "dispatch_sequence": -1},
            {"dispatch_id": "batch", "dispatch_sequence": 1},
        ],
        ids=["empty-id-with-sequence", "id-without-sequence", "negative", "non-uuid"],
    )
    def test_attached_snapshot_rejects_inconsistent_identity(self, fields: dict[str, object]) -> None:
        """Empty identity pairs only with sequence zero; any other identity is a UUID."""
        with pytest.raises(ValidationError):
            AttachedDispatchSnapshotDAO.model_validate(fields)
