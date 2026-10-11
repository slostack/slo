"""Direct unit tests for scheduling runtime helper modules."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.scheduling.dao import OneShotTriggerDAO, ScheduleDefinitionDAO, ScheduleStateDAO
from src.scheduling.dao import ScheduleSessionPolicyDAO
from src.scheduling.runtime.dao import (
    ResolvedSessionTargetDAO,
    ScheduleExecutionOutcomeDAO,
    ScheduleSubprocessResultDAO,
)
from src.scheduling.runtime.fire_lock import ScheduleFireLock
from src.scheduling.runtime.reporting import ScheduleReportWriter
from src.scheduling.runtime.session_target_resolver import SessionTargetResolver
from src.scheduling.runtime.subprocess_runner import ScheduleSubprocessRunner
from src.scheduling.store import ScheduleStore


def _utc_datetime(*, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a deterministic aware UTC datetime."""
    return datetime(year=year, month=month, day=day, hour=hour, minute=minute, tzinfo=timezone.utc)


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect schedule persistence into a test-local root."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))


def _build_definition(*, schedule_id: str, session_mode: str = "continuous") -> ScheduleDefinitionDAO:
    """Build a scheduling definition for runtime helper tests."""
    return ScheduleDefinitionDAO(
        schedule_id=schedule_id,
        name=f"Schedule {schedule_id}",
        name_key=f"schedule-{schedule_id}",
        trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=12, hour=10)),
        prompt="Check the repo and summarize new failures.",
        cwd="/tmp/project",
        model="gpt-5.4",
        session_mode=session_mode,  # type: ignore[arg-type]
        session_policy=(
            ScheduleSessionPolicyDAO(session_reference=None) if session_mode == "continuous" else None
        ),
    )


class _FakeHistoryStore:
    """Test double for history-based session reference resolution."""

    def __init__(self, *, resolved_session_id: str | None = None) -> None:
        self._resolved_session_id: str | None = resolved_session_id

    async def resolve_session_reference(self, *, reference: str) -> str:
        """Resolve or reject one explicit reference."""
        if self._resolved_session_id is None:
            raise ValueError(f"unknown session: {reference}")
        return self._resolved_session_id


class _FakeProcess:
    """Minimal fake subprocess handle for runner tests."""

    def __init__(self, *, returncode: int | None, stdout: bytes, stderr: bytes) -> None:
        self.returncode: int | None = returncode
        self._stdout: bytes = stdout
        self._stderr: bytes = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return pre-seeded stdout and stderr bytes."""
        return self._stdout, self._stderr


class TestScheduleFireLock:
    """Per-schedule overlap lock behavior."""

    @pytest.mark.asyncio
    async def test_acquire_and_release_roundtrip(self, tmp_path: Path) -> None:
        """A released lock can be reacquired by the next fire."""
        lock: ScheduleFireLock = ScheduleFireLock(lock_path=tmp_path / ".fire.lock")

        first_acquire: bool = await lock.acquire()
        second_acquire: bool = await lock.acquire()
        await lock.release()
        third_acquire: bool = await lock.acquire()

        assert first_acquire is True
        assert second_acquire is False
        assert third_acquire is True


class TestSessionTargetResolver:
    """Continuous-session target resolution rules."""

    @pytest.mark.asyncio
    async def test_resolves_known_explicit_reference(self) -> None:
        """Known explicit references resolve to resume-ready targets."""
        resolver: SessionTargetResolver = SessionTargetResolver(
            history_store=_FakeHistoryStore(resolved_session_id="session-123"),  # type: ignore[arg-type]
        )
        definition: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-1").model_copy(
            update={
                "session_policy": ScheduleSessionPolicyDAO(session_reference="release-prep"),
            },
        )

        resolved: ResolvedSessionTargetDAO = await resolver.resolve(
            definition=definition,
            state=ScheduleStateDAO(),
        )

        assert resolved.resolved_reference == "release-prep"
        assert resolved.target_session_id == "session-123"
        assert resolved.explicit_session_id is None

    @pytest.mark.asyncio
    async def test_unknown_slug_reference_seeds_explicit_session(self) -> None:
        """Unknown slug-like references are treated as explicit seed ids."""
        resolver: SessionTargetResolver = SessionTargetResolver(
            history_store=_FakeHistoryStore(),  # type: ignore[arg-type]
        )
        definition: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-2").model_copy(
            update={
                "session_policy": ScheduleSessionPolicyDAO(session_reference="release-prep"),
            },
        )

        resolved: ResolvedSessionTargetDAO = await resolver.resolve(
            definition=definition,
            state=ScheduleStateDAO(),
        )

        assert resolved.resolved_reference is None
        assert resolved.target_session_id == "release-prep"
        assert resolved.explicit_session_id == "release-prep"

    @pytest.mark.asyncio
    async def test_first_continuous_fire_seeds_schedule_owned_session(self) -> None:
        """Continuous schedules without prior session state seed a stable session id."""
        resolver: SessionTargetResolver = SessionTargetResolver(
            history_store=_FakeHistoryStore(),  # type: ignore[arg-type]
        )
        definition: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-3").model_copy(
            update={"session_policy": ScheduleSessionPolicyDAO(session_reference=None)},
        )

        resolved: ResolvedSessionTargetDAO = await resolver.resolve(
            definition=definition,
            state=ScheduleStateDAO(),
        )

        assert resolved.resolved_reference is None
        assert resolved.target_session_id == "schedule-schedule-3"
        assert resolved.explicit_session_id == "schedule-schedule-3"


class TestScheduleSubprocessRunner:
    """Headless child-process runner normalization."""

    @pytest.mark.asyncio
    async def test_run_fresh_uses_slo_executable_cwd_and_narrows_returncode(self, tmp_path: Path) -> None:
        """Fresh runs invoke `slo run` and treat a missing returncode as exit code 1."""
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-4", session_mode="fresh"
        ).model_copy(
            update={"cwd": str(tmp_path)},
        )
        fake_process: _FakeProcess = _FakeProcess(
            returncode=None,
            stdout=b"line one\nfinal summary\n",
            stderr=b"stderr output\n",
        )
        create_subprocess_exec: AsyncMock = AsyncMock(return_value=fake_process)

        with (
            patch(
                "src.scheduling.runtime.subprocess_runner.ScheduleExecutableLocator.locate",
                return_value=Path("/usr/local/bin/slo"),
            ),
            patch(
                "src.scheduling.runtime.subprocess_runner.asyncio.create_subprocess_exec",
                create_subprocess_exec,
            ),
        ):
            result: ScheduleSubprocessResultDAO = await ScheduleSubprocessRunner().run_fresh(
                definition=definition
            )

        create_subprocess_exec.assert_awaited_once()
        assert create_subprocess_exec.await_args is not None
        kwargs = create_subprocess_exec.await_args.kwargs
        argv: tuple[object, ...] = create_subprocess_exec.await_args.args
        assert argv[:2] == ("/usr/local/bin/slo", "run")
        assert kwargs["cwd"] == str(tmp_path.resolve())
        assert result.exit_code == 1
        assert result.status == "failed"
        assert result.summary == "final summary"

    @pytest.mark.asyncio
    async def test_run_fresh_executes_real_wrapper_from_hostile_cwd_and_pythonpath(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scheduler executes the persisted wrapper, whose -I ignores hostile import inputs."""
        hostile_root: Path = tmp_path / "hostile"
        hostile_root.mkdir()
        (hostile_root / "src").mkdir()
        (hostile_root / "src" / "cli.py").write_text("raise RuntimeError('foreign src selected')\n")
        bin_dir: Path = tmp_path / "venv" / "bin"
        bin_dir.mkdir(parents=True)
        entry: Path = bin_dir / "slo-entry"
        entry.write_text(
            "import json\nimport sys\n"
            "print(json.dumps({'foreign_present': any('hostile' in item for item in sys.path)}))\n"
        )
        wrapper: Path = bin_dir / "slo"
        wrapper.write_text("#!/bin/sh\n" f"exec '{sys.executable}' -I '{entry}' \"$@\"\n")
        wrapper.chmod(0o755)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-wrapper", session_mode="fresh"
        ).model_copy(update={"cwd": str(hostile_root)})
        monkeypatch.setenv("PYTHONPATH", str(hostile_root))

        with patch(
            "src.scheduling.runtime.subprocess_runner.ScheduleExecutableLocator.locate",
            return_value=wrapper,
        ):
            result: ScheduleSubprocessResultDAO = await ScheduleSubprocessRunner().run_fresh(
                definition=definition
            )

        assert result.status == "completed"
        assert '"foreign_present": false' in result.stdout_summary

    @pytest.mark.asyncio
    async def test_run_resume_passes_exact_openrouter_route_to_headless_preparation(
        self, tmp_path: Path
    ) -> None:
        """Inactive schedules preserve their exact OpenRouter route in the real CLI argv."""
        definition: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-openrouter").model_copy(
            update={"model": "openrouter:vendor/scheduled", "cwd": str(tmp_path)}
        )
        process = _FakeProcess(returncode=0, stdout=b"done\n", stderr=b"")
        create_subprocess_exec: AsyncMock = AsyncMock(return_value=process)

        with (
            patch(
                "src.scheduling.runtime.subprocess_runner.ScheduleExecutableLocator.locate",
                return_value=Path("/tmp/slo"),
            ),
            patch(
                "src.scheduling.runtime.subprocess_runner.asyncio.create_subprocess_exec",
                create_subprocess_exec,
            ),
        ):
            result = await ScheduleSubprocessRunner().run_resume(
                definition=definition,
                session_reference="scheduled-session",
                target_session_id="scheduled-session",
            )

        assert result.status == "completed"
        assert create_subprocess_exec.await_args is not None
        argv = create_subprocess_exec.await_args.args
        assert argv[argv.index("--model") + 1] == "openrouter:vendor/scheduled"
        assert argv[argv.index("--resume") + 1] == "scheduled-session"


class TestScheduleReportWriter:
    """Run-record and state snapshot persistence."""

    @pytest.mark.asyncio
    async def test_write_persists_run_record_and_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Writing an outcome appends one record and advances mutable state."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-5", session_mode="fresh")
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        loaded = ScheduleStore.load(reference=definition.schedule_id)
        outcome: ScheduleExecutionOutcomeDAO = ScheduleExecutionOutcomeDAO(
            run_id="run-1",
            started_at=_utc_datetime(year=2026, month=7, day=12, hour=10),
            finished_at=_utc_datetime(year=2026, month=7, day=12, hour=10, minute=1),
            status="completed",
            delivery_path="fresh_headless",
            delivery_state="executed",
            session_id="session-123",
            target_session_id=None,
            exit_code=0,
            summary="summary",
            stdout_summary="stdout",
            stderr_summary="",
        )

        await ScheduleReportWriter().write(loaded=loaded, outcome=outcome)
        reloaded = ScheduleStore.load(reference=definition.schedule_id)

        assert reloaded.state.last_run_at == outcome.started_at
        assert reloaded.state.last_status == "completed"
        assert reloaded.state.last_session_id == "session-123"
        assert reloaded.state.last_delivery_path == "fresh_headless"
        assert reloaded.state.last_delivery_state == "executed"
        assert reloaded.state.run_count == 1
