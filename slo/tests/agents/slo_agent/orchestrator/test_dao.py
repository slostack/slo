"""Tests for orchestrator domain DAOs (sub-spec 01-sub-agents 01.b)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.orchestrator.dao import (
    FleetSnapshotDAO,
    build_cleanup_summary,
    project_fleet_entries,
    OrchestratorResultDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
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
