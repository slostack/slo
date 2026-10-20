"""Unit tests for OrchestratorContextDAO, SpawnContextDAO, and dump_json_bytes (sub-spec 54.a.1)."""

from __future__ import annotations

import json

import pytest

from src.agents.slo_agent.orchestrator.context_dao import (
    OrchestratorContextDAO,
    SpawnContextDAO,
    dump_json_bytes,
)
from tests.agents.slo_agent.orchestrator.released_schemas import ReleasedSpawnContextDAO

# ---------------------------------------------------------------------------
# OrchestratorContextDAO
# ---------------------------------------------------------------------------


class TestOrchestratorContextDAO:
    def test_build_populates_all_fields(self) -> None:
        """build() produces a DAO with the supplied values and a UTC timestamp."""
        dao = OrchestratorContextDAO.build(
            system_prompt="system",
            user_prompt="user",
            model="claude-sonnet-4-6",
        )
        assert dao.system_prompt == "system"
        assert dao.user_prompt == "user"
        assert dao.model == "claude-sonnet-4-6"
        assert dao.recorded_at.endswith("+00:00")

    def test_build_with_none_model(self) -> None:
        """build() works when model is None."""
        dao = OrchestratorContextDAO.build(
            system_prompt="s",
            user_prompt="u",
            model=None,
        )
        assert dao.model is None

    def test_round_trip_json(self) -> None:
        """model_dump_json / model_validate_json round-trip is lossless."""
        dao = OrchestratorContextDAO.build(
            system_prompt="long system prompt here",
            user_prompt="implement feature X",
            model="claude-opus-4-8",
        )
        serialized = dao.model_dump_json()
        restored = OrchestratorContextDAO.model_validate_json(serialized)
        assert restored == dao

    def test_extra_fields_forbidden(self) -> None:
        """extra='forbid' rejects unknown fields during validation."""
        with pytest.raises(Exception):
            OrchestratorContextDAO.model_validate(
                {
                    "system_prompt": "s",
                    "user_prompt": "u",
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "unknown_field": "boom",
                }
            )


# ---------------------------------------------------------------------------
# SpawnContextDAO
# ---------------------------------------------------------------------------


class TestSpawnContextDAO:
    def test_build_populates_all_fields(self) -> None:
        """build() produces a DAO with all supplied values."""
        dao = SpawnContextDAO.build(
            task_id="task-1",
            prompt="Write tests",
            system_prompt="child system prompt",
            inactivity_timeout_seconds=120.0,
            model="claude-sonnet-4-6",
            reasoning_level="high",
            cwd="/tmp/work",
        )
        assert dao.task_id == "task-1"
        assert dao.prompt == "Write tests"
        assert dao.system_prompt == "child system prompt"
        assert dao.inactivity_timeout_seconds == 120.0
        assert dao.model == "claude-sonnet-4-6"
        assert dao.reasoning_level == "high"
        assert dao.cwd == "/tmp/work"
        assert dao.recorded_at.endswith("+00:00")

    def test_build_with_all_optional_none(self) -> None:
        """build() works when all optional fields are None."""
        dao = SpawnContextDAO.build(
            task_id="t",
            prompt="p",
            system_prompt="s",
            inactivity_timeout_seconds=60.0,
            model=None,
            reasoning_level=None,
            cwd=None,
        )
        assert dao.model is None
        assert dao.reasoning_level is None
        assert dao.cwd is None

    def test_round_trip_json(self) -> None:
        """model_dump_json / model_validate_json round-trip is lossless."""
        dao = SpawnContextDAO.build(
            task_id="abc",
            prompt="do something",
            system_prompt="big system prompt",
            inactivity_timeout_seconds=1200.0,
            model="claude-haiku-4-5",
            reasoning_level=None,
            cwd=None,
        )
        serialized = dao.model_dump_json()
        restored = SpawnContextDAO.model_validate_json(serialized)
        assert restored == dao

    def test_extra_fields_forbidden(self) -> None:
        """extra='forbid' rejects unknown fields during validation."""
        with pytest.raises(Exception):
            SpawnContextDAO.model_validate(
                {
                    "task_id": "t",
                    "prompt": "p",
                    "system_prompt": "s",
                    "inactivity_timeout_seconds": 60.0,
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "rogue": "field",
                }
            )


# ---------------------------------------------------------------------------
# dump_json_bytes
# ---------------------------------------------------------------------------


class TestDumpJsonBytes:
    def test_returns_bytes(self) -> None:
        """dump_json_bytes returns a bytes object."""
        dao = OrchestratorContextDAO.build(system_prompt="s", user_prompt="u", model=None)
        result = dump_json_bytes(model=dao)
        assert isinstance(result, bytes)

    def test_parseable_json(self) -> None:
        """Output parses as valid JSON."""
        dao = OrchestratorContextDAO.build(system_prompt="s", user_prompt="u", model="m")
        parsed = json.loads(dump_json_bytes(model=dao))
        assert parsed["system_prompt"] == "s"
        assert parsed["user_prompt"] == "u"
        assert parsed["model"] == "m"

    def test_excludes_none_fields(self) -> None:
        """dump_json_bytes omits None-valued optional fields."""
        dao = OrchestratorContextDAO.build(system_prompt="s", user_prompt="u", model=None)
        parsed = json.loads(dump_json_bytes(model=dao))
        assert "model" not in parsed

    def test_spawn_context_round_trip(self) -> None:
        """dump_json_bytes + model_validate_json round-trips a SpawnContextDAO."""
        dao = SpawnContextDAO.build(
            task_id="t",
            prompt="p",
            system_prompt="s",
            inactivity_timeout_seconds=30.0,
            model=None,
            reasoning_level=None,
            cwd=None,
        )
        raw = dump_json_bytes(model=dao)
        restored = SpawnContextDAO.model_validate_json(raw)
        assert restored.task_id == dao.task_id
        assert restored.inactivity_timeout_seconds == dao.inactivity_timeout_seconds


class TestSpawnContextExecutionIdentity:
    """Spawn context keeps its released wire schema while carrying runtime identity."""

    _EXECUTION_ID: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"

    def _build(self) -> SpawnContextDAO:
        return SpawnContextDAO.build(
            task_id="t",
            prompt="p",
            system_prompt="s",
            inactivity_timeout_seconds=60.0,
            model=None,
            reasoning_level=None,
            cwd=None,
            execution_id=self._EXECUTION_ID,
        )

    def test_build_retains_runtime_execution_id(self) -> None:
        """build() binds the registry-captured incarnation identity in memory."""
        assert self._build().execution_id == self._EXECUTION_ID

    def test_serialization_excludes_execution_id_for_released_readers(self) -> None:
        """Written context bytes decode with the released closed spawn-context DAO."""
        dao: SpawnContextDAO = self._build()

        for raw in (dao.model_dump_json(indent=2), dump_json_bytes(dao).decode("utf-8")):
            assert "execution_id" not in raw
            assert ReleasedSpawnContextDAO.model_validate_json(raw).task_id == "t"

    def test_rejects_non_uuid_execution_id(self) -> None:
        """A malformed runtime identity is refused before any write."""
        with pytest.raises(ValueError):
            SpawnContextDAO.build(
                task_id="t",
                prompt="p",
                system_prompt="s",
                inactivity_timeout_seconds=60.0,
                model=None,
                reasoning_level=None,
                cwd=None,
                execution_id="bad",
            )
