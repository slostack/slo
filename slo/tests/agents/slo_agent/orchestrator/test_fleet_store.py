"""Tests for the durable orchestrator fleet projection (sub-spec 71.a.2)."""

from __future__ import annotations

import hashlib
import os
import threading
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import (
    ChildExecutionEvidenceDAO,
    ExecutionIndexDAO,
    StdoutCaptureIdentityDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import MAX_EVIDENCE_BYTES, FleetStore
from tests.agents.slo_agent.orchestrator.released_schemas import ReleasedFleetSnapshotDAO


def _entry() -> SubAgentStatusDAO:
    """Build one terminal fleet entry for FleetStore tests.

    Returns:
        SubAgentStatusDAO: Completed child entry with durable cleanup fields.
    """
    return SubAgentStatusDAO(
        task_id="task-1",
        session_id="child-1",
        status="completed",
        pid=1234,
        started_at=10.0,
        exit_code=0,
        terminal_reason="completed",
        terminated_by="natural",
    )


class TestFleetStore:
    """FleetStore durable snapshot behavior."""

    def test_persist_then_load_round_trips_snapshot(self, tmp_path: Path) -> None:
        """Persisted fleet entries can be loaded after the writer exits."""
        store: FleetStore = FleetStore(
            history_root=tmp_path,
            orchestrator_session_id="orchestrator-1",
            workflow_id="workflow-1",
        )

        store.persist(entries=[_entry()])

        snapshot = store.load()

        assert snapshot is not None
        assert snapshot.orchestrator_session_id == "orchestrator-1"
        assert snapshot.workflow_id == "workflow-1"
        assert snapshot.entries == [_entry()]
        assert snapshot.updated_at

    def test_load_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        """Loading before a registry transition returns no fleet snapshot."""
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        assert store.load() is None

    def test_load_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt fleet JSON is logged and never escapes to a reader."""
        fleet_path: Path = tmp_path / "orchestrator-1" / "fleet.json"
        fleet_path.parent.mkdir()
        fleet_path.write_text("not json", encoding="utf-8")
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        with patch(target="src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning:
            assert store.load() is None

        warning.assert_called_once()

    def test_persist_swallows_oserror(self, tmp_path: Path) -> None:
        """A failed best-effort fleet write only logs a warning."""
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        with (
            patch(
                target="src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_json",
                side_effect=OSError("disk full"),
            ),
            patch(target="src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning,
        ):
            store.persist(entries=[_entry()])

        warning.assert_called_once()


# ── Feature 94 T02: execution index and versioned sibling evidence ───────────

_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_EXEC_A: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"
_EXEC_B: str = "1e2d3c4b-5a69-4788-9a1b-2c3d4e5f6a7b"
_BOUNDED_SECONDS: float = 3.0
"""Bounded wait for reads that must not block; never a timing oracle."""


def _bound_store(tmp_path: Path) -> FleetStore:
    """Build a writer-side store bound to a synthetic run identity."""
    return FleetStore(history_root=tmp_path, orchestrator_session_id="orch-1", run_id=_RUN_ID)


def _child_dir(tmp_path: Path) -> Path:
    return tmp_path / "orch-1" / "children" / "child-1"


def _publish_running(
    tmp_path: Path, store: FleetStore, *, execution_id: str = _EXEC_A
) -> ChildExecutionEvidenceDAO:
    """Write fresh context/capture files and publish matching running evidence."""
    child_dir: Path = _child_dir(tmp_path)
    child_dir.mkdir(parents=True, exist_ok=True)
    context_bytes: bytes = b'{"task_id": "t1"}'
    (child_dir / "spawn_context.json").write_bytes(context_bytes)
    stdout_path: Path = child_dir / "stdout.jsonl"
    stdout_path.write_bytes(b"")
    stat = stdout_path.stat()
    running: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.pending(
        session_id="child-1", execution_id=execution_id
    ).running(
        stdout_identity=StdoutCaptureIdentityDAO(device=stat.st_dev, inode=stat.st_ino),
        spawn_context_sha256=hashlib.sha256(context_bytes).hexdigest(),
    )
    store.persist(
        entries=[
            SubAgentStatusDAO(task_id="t1", session_id="child-1", status="running", execution_id=execution_id)
        ]
    )
    assert store.publish_execution(evidence=running) is True
    return running


def _publish_terminal(tmp_path: Path, store: FleetStore, running: ChildExecutionEvidenceDAO) -> None:
    status_bytes: bytes = b'{"status": "completed"}'
    (_child_dir(tmp_path) / "status.json").write_bytes(status_bytes)
    store.publish_execution(
        evidence=running.terminal(status="completed", status_sha256=hashlib.sha256(status_bytes).hexdigest())
    )


def _evidence_path(tmp_path: Path, *, name: str) -> Path:
    """Resolve a verification input: the run index, or a file in the child directory."""
    if name == "index":
        return tmp_path / "orch-1" / "execution-index.v1.json"
    return _child_dir(tmp_path) / name


def _verified(tmp_path: Path) -> ChildExecutionEvidenceDAO | None:
    return FleetStore.load_verified_execution(
        history_root=tmp_path, orchestrator_session_id="orch-1", child_session_id="child-1"
    )


class TestExecutionIndex:
    """FleetStore writes execution-index.v1.json beside fleet.json."""

    def test_persist_writes_index_and_legacy_fleet(self, tmp_path: Path) -> None:
        """The index maps sessions to incarnations; fleet.json stays released-shape."""
        store: FleetStore = _bound_store(tmp_path)

        store.persist(
            entries=[
                SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A),
                SubAgentStatusDAO(task_id="t2", session_id="child-2", execution_id=_EXEC_B),
            ]
        )

        index: ExecutionIndexDAO = ExecutionIndexDAO.model_validate_json(
            (tmp_path / "orch-1" / "execution-index.v1.json").read_text(encoding="utf-8")
        )
        assert index.run_id == _RUN_ID
        assert index.executions == {"child-1": _EXEC_A, "child-2": _EXEC_B}
        fleet_raw: str = (tmp_path / "orch-1" / "fleet.json").read_text(encoding="utf-8")
        assert "execution_id" not in fleet_raw
        assert ReleasedFleetSnapshotDAO.model_validate_json(fleet_raw).entries[1].session_id == "child-2"

    def test_index_written_before_fleet(self, tmp_path: Path) -> None:
        """Identity projection precedes the old-shaped fleet projection."""
        store: FleetStore = _bound_store(tmp_path)
        written: list[str] = []

        def record(*, path: Path, text: str, private: bool = True) -> None:
            written.append(path.name)

        with patch(
            "src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_text", side_effect=record
        ):
            store.persist(
                entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)]
            )

        assert written == ["execution-index.v1.json", "fleet.json"]

    def test_unbound_reader_store_writes_no_index(self, tmp_path: Path) -> None:
        """A store without run identity keeps legacy fleet-only persistence."""
        FleetStore(history_root=tmp_path, orchestrator_session_id="orch-1").persist(entries=[_entry()])

        assert not (tmp_path / "orch-1" / "execution-index.v1.json").exists()
        assert (tmp_path / "orch-1" / "fleet.json").exists()

    def test_index_write_failure_still_persists_fleet(self, tmp_path: Path) -> None:
        """An index OSError is logged with a fixed reason and does not block fleet.json."""
        store: FleetStore = _bound_store(tmp_path)
        real_write = AtomicFileWriter.write_text

        def fail_index(*, path: Path, text: str, private: bool = True) -> None:
            if path.name == "execution-index.v1.json":
                raise OSError("disk full")
            real_write(path=path, text=text, private=private)

        with (
            patch(
                "src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_text",
                side_effect=fail_index,
            ),
            patch("src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning,
        ):
            store.persist(
                entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)]
            )

        assert (tmp_path / "orch-1" / "fleet.json").exists()
        assert warning.call_args.kwargs["msg"] == "execution_index_persist_failed"


class TestExecutionEvidence:
    """Sibling publication and new-reader verification over real temp files."""

    def test_publish_execution_writes_sibling(self, tmp_path: Path) -> None:
        """Pending evidence lands at children/<id>/execution.v1.json."""
        evidence = ChildExecutionEvidenceDAO.pending(session_id="child-1", execution_id=_EXEC_A)

        assert _bound_store(tmp_path).publish_execution(evidence=evidence) is True

        sibling: Path = _child_dir(tmp_path) / "execution.v1.json"
        assert ChildExecutionEvidenceDAO.model_validate_json(sibling.read_text(encoding="utf-8")) == evidence

    def test_publish_execution_failure_returns_false(self, tmp_path: Path) -> None:
        """A sibling write failure is reported, logged with a fixed reason, never raised."""
        evidence = ChildExecutionEvidenceDAO.pending(session_id="child-1", execution_id=_EXEC_A)

        with (
            patch(
                "src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_text",
                side_effect=OSError("secret path detail"),
            ),
            patch("src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning,
        ):
            committed: bool = _bound_store(tmp_path).publish_execution(evidence=evidence)

        assert committed is False
        assert warning.call_args.kwargs["msg"] == "execution_evidence_publish_failed"
        assert "secret path detail" not in str(warning.call_args)

    def test_pending_evidence_verifies_with_matching_index(self, tmp_path: Path) -> None:
        """Matching index and pending sibling verify; no output is trusted yet."""
        store: FleetStore = _bound_store(tmp_path)
        store.persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)])
        store.publish_execution(
            evidence=ChildExecutionEvidenceDAO.pending(session_id="child-1", execution_id=_EXEC_A)
        )

        verified = _verified(tmp_path)

        assert verified is not None and verified.phase == "pending"

    def test_running_and_terminal_evidence_verify(self, tmp_path: Path) -> None:
        """Fresh capture inode, context digest and status digest all verify."""
        store: FleetStore = _bound_store(tmp_path)
        running = _publish_running(tmp_path, store)
        assert _verified(tmp_path) == running

        _publish_terminal(tmp_path, store, running)

        verified = _verified(tmp_path)
        assert verified is not None and (verified.phase, verified.status) == ("terminal", "completed")

    def test_stale_sibling_from_previous_incarnation_is_rejected(self, tmp_path: Path) -> None:
        """An old terminal sibling cannot authorize a newly pending fleet row."""
        store: FleetStore = _bound_store(tmp_path)
        running = _publish_running(tmp_path, store, execution_id=_EXEC_A)
        _publish_terminal(tmp_path, store, running)

        store.persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_B)])

        assert _verified(tmp_path) is None

    def test_missing_index_or_sibling_is_rejected(self, tmp_path: Path) -> None:
        """Absent identity evidence never verifies."""
        store: FleetStore = _bound_store(tmp_path)
        assert _verified(tmp_path) is None
        store.persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)])
        assert _verified(tmp_path) is None

    def test_changed_capture_inode_is_rejected(self, tmp_path: Path) -> None:
        """A replaced stdout capture (new inode) invalidates running evidence."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        stdout_path: Path = _child_dir(tmp_path) / "stdout.jsonl"
        replacement: Path = _child_dir(tmp_path) / "replacement"
        replacement.write_bytes(b"old output\n")
        os.replace(replacement, stdout_path)

        assert _verified(tmp_path) is None

    def test_missing_capture_is_rejected(self, tmp_path: Path) -> None:
        """Running evidence that names a capture fails closed once that capture is gone."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        assert _verified(tmp_path) is not None

        (_child_dir(tmp_path) / "stdout.jsonl").unlink()

        assert _verified(tmp_path) is None

    def test_changed_context_digest_is_rejected(self, tmp_path: Path) -> None:
        """A spawn context that is not this incarnation's exact bytes is untrusted."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        (_child_dir(tmp_path) / "spawn_context.json").write_bytes(b'{"task_id": "old"}')

        assert _verified(tmp_path) is None

    def test_changed_status_digest_is_rejected(self, tmp_path: Path) -> None:
        """Status bytes that differ from the terminal digest are untrusted."""
        store: FleetStore = _bound_store(tmp_path)
        running = _publish_running(tmp_path, store)
        _publish_terminal(tmp_path, store, running)
        (_child_dir(tmp_path) / "status.json").write_bytes(b'{"status": "failed"}')

        assert _verified(tmp_path) is None

    def test_sibling_changed_during_read_is_rejected(self, tmp_path: Path) -> None:
        """The sibling must be byte-identical before and after verification reads."""
        store: FleetStore = _bound_store(tmp_path)
        running = _publish_running(tmp_path, store)
        sibling: Path = _child_dir(tmp_path) / "execution.v1.json"
        real_files_match = FleetStore._files_match

        def replace_sibling_then_check(*, child_dir: Path, evidence: ChildExecutionEvidenceDAO) -> bool:
            AtomicFileWriter.write_text(
                path=sibling,
                text=running.terminal(status="failed", status_sha256="c" * 64).model_dump_json(),
            )
            return real_files_match(child_dir=child_dir, evidence=evidence)

        with patch.object(FleetStore, "_files_match", side_effect=replace_sibling_then_check):
            assert _verified(tmp_path) is None

    @pytest.mark.parametrize("change", ["vanished", "oversized"])
    def test_sibling_unreadable_on_reread_is_rejected(self, tmp_path: Path, change: str) -> None:
        """A sibling that vanishes or outgrows the bound before the final re-read never verifies."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        sibling: Path = _child_dir(tmp_path) / "execution.v1.json"
        real_files_match = FleetStore._files_match

        def break_sibling_then_check(*, child_dir: Path, evidence: ChildExecutionEvidenceDAO) -> bool:
            if change == "vanished":
                sibling.unlink()
            else:
                sibling.write_bytes(b" " * (MAX_EVIDENCE_BYTES + 1))
            return real_files_match(child_dir=child_dir, evidence=evidence)

        with patch.object(FleetStore, "_files_match", side_effect=break_sibling_then_check):
            assert _verified(tmp_path) is None

    def test_oversized_or_malformed_evidence_is_rejected(self, tmp_path: Path) -> None:
        """Evidence files are bounded before decode and malformed bytes never verify."""
        store: FleetStore = _bound_store(tmp_path)
        store.persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)])
        sibling: Path = _child_dir(tmp_path) / "execution.v1.json"
        sibling.parent.mkdir(parents=True, exist_ok=True)
        sibling.write_bytes(b"{" + b" " * (65 * 1024) + b"}")
        assert _verified(tmp_path) is None
        sibling.write_bytes(b"not json")
        assert _verified(tmp_path) is None

    @pytest.mark.parametrize("digested", ["status.json", "spawn_context.json"])
    def test_large_digested_file_verifies(self, tmp_path: Path, digested: str) -> None:
        """Digested old-shaped files carry unbounded answers; size never blocks verification."""
        store: FleetStore = _bound_store(tmp_path)
        child_dir: Path = _child_dir(tmp_path)
        child_dir.mkdir(parents=True, exist_ok=True)
        large: bytes = b'{"answer": "' + b"x" * (MAX_EVIDENCE_BYTES + 5_000) + b'"}'
        small: bytes = b'{"task_id": "t1"}'
        context_bytes, status_bytes = (large, small) if digested == "spawn_context.json" else (small, large)
        (child_dir / "spawn_context.json").write_bytes(context_bytes)
        (child_dir / "status.json").write_bytes(status_bytes)
        stdout_path: Path = child_dir / "stdout.jsonl"
        stdout_path.write_bytes(b"")
        stat = stdout_path.stat()
        terminal = (
            ChildExecutionEvidenceDAO.pending(session_id="child-1", execution_id=_EXEC_A)
            .running(
                stdout_identity=StdoutCaptureIdentityDAO(device=stat.st_dev, inode=stat.st_ino),
                spawn_context_sha256=hashlib.sha256(context_bytes).hexdigest(),
            )
            .terminal(status="completed", status_sha256=hashlib.sha256(status_bytes).hexdigest())
        )
        store.persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", execution_id=_EXEC_A)])
        assert store.publish_execution(evidence=terminal) is True

        verified = _verified(tmp_path)

        assert verified is not None and (verified.phase, verified.status) == ("terminal", "completed")

    @pytest.mark.parametrize("bounded", ["execution.v1.json", "index"])
    def test_oversized_identity_file_is_rejected_without_full_read(
        self, tmp_path: Path, bounded: str
    ) -> None:
        """The sibling and index bound is enforced before their bytes are loaded."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        target: Path = (
            _child_dir(tmp_path) / "execution.v1.json"
            if bounded == "execution.v1.json"
            else tmp_path / "orch-1" / "execution-index.v1.json"
        )
        target.write_bytes(b"{" + b" " * (8 * 1024 * 1024) + b"}")

        tracemalloc.start()
        try:
            verified = _verified(tmp_path)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert verified is None
        assert peak < 1024 * 1024

    @pytest.mark.parametrize("linked", ["execution.v1.json", "index", "status.json"])
    def test_symlinked_evidence_file_is_rejected(self, tmp_path: Path, linked: str) -> None:
        """A final-component symlink never verifies, even to byte-identical content."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_terminal(tmp_path, store, _publish_running(tmp_path, store))
        assert _verified(tmp_path) is not None
        target: Path = _evidence_path(tmp_path, name=linked)
        real: Path = target.with_name(f"{target.name}.real")
        os.replace(target, real)
        target.symlink_to(real)

        assert _verified(tmp_path) is None

    @pytest.mark.parametrize("kind", ["fifo", "directory"])
    @pytest.mark.parametrize("planted", ["execution.v1.json", "index"])
    def test_non_regular_evidence_file_is_rejected_without_blocking(
        self, tmp_path: Path, kind: str, planted: str
    ) -> None:
        """A planted FIFO or directory is refused promptly; opening it never blocks."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        target: Path = _evidence_path(tmp_path, name=planted)
        target.unlink()
        if kind == "fifo":
            os.mkfifo(target)
        else:
            target.mkdir()
        results: list[ChildExecutionEvidenceDAO | None] = []
        reader: threading.Thread = threading.Thread(
            target=lambda: results.append(_verified(tmp_path)), daemon=True
        )

        reader.start()
        reader.join(timeout=_BOUNDED_SECONDS)

        assert not reader.is_alive(), "verification blocked on a non-regular evidence file"
        assert results == [None]

    @pytest.mark.parametrize("planted", ["execution.v1.json", "index"])
    def test_fifo_carrying_valid_evidence_bytes_is_rejected(self, tmp_path: Path, planted: str) -> None:
        """Only regular files verify: a FIFO serving the exact valid bytes is still refused."""
        store: FleetStore = _bound_store(tmp_path)
        _publish_running(tmp_path, store)
        target: Path = _evidence_path(tmp_path, name=planted)
        valid_bytes: bytes = target.read_bytes()
        target.unlink()
        os.mkfifo(target)
        writer: int = os.open(target, os.O_RDWR | os.O_NONBLOCK)
        try:
            os.write(writer, valid_bytes)
            verified = _verified(tmp_path)
        finally:
            os.close(writer)

        assert verified is None

    def test_unsafe_child_identity_is_rejected(self, tmp_path: Path) -> None:
        """A traversal identity never reaches the filesystem."""
        assert (
            FleetStore.load_verified_execution(
                history_root=tmp_path, orchestrator_session_id="orch-1", child_session_id="../x"
            )
            is None
        )
