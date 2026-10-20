"""ChildAbortStore adapter integration over real temp-owned files and locks (feature 94.a.4, T10).

Every test drives the real adapter against a ``tmp_path`` history root: real
descriptor-relative opens, real ``flock`` admission locks and the real
``AtomicFileWriter``. Replacement races are simulated with two temp-owned
directories only. No process, signal, provider or user history is touched.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO
from src.agents.slo_agent.orchestrator import child_abort
from src.agents.slo_agent.orchestrator.child_abort import (
    MAX_CONTROL_FILE_BYTES,
    MAX_REQUESTS_PER_RUN,
    ChildAbortStore,
)
from src.agents.slo_agent.orchestrator.dao import (
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
)
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

_PARENT: str = "orch-1"
_OWNER: str = "owner-1"
_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_OTHER_RUN_ID: str = "11111111-2222-4333-8444-555555555555"
_EXECUTION_ID: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"


def _capability(
    *, run_id: str = _RUN_ID, accepting: bool = True, **overrides: object
) -> ChildControlCapabilityDAO:
    """Build this run's capability with optional identity overrides."""
    fields: dict[str, object] = {
        "run_id": run_id,
        "owner_session_id": _OWNER,
        "orchestrator_session_id": _PARENT,
        "accepting": accepting,
    }
    return ChildControlCapabilityDAO.model_validate({**fields, **overrides})


def _request(
    *, run_id: str = _RUN_ID, request_id: Optional[str] = None, **overrides: str
) -> ChildAbortRequestDAO:
    """Build one exact child request for this run."""
    fields: dict[str, str] = {
        "request_id": request_id or str(uuid4()),
        "owner_session_id": _OWNER,
        "orchestrator_session_id": _PARENT,
        "session_id": "child-1",
        "run_id": run_id,
        "execution_id": _EXECUTION_ID,
    }
    return ChildAbortRequestDAO.model_validate({**fields, **overrides})


def _store(*, root: Path) -> ChildAbortStore:
    return ChildAbortStore(history_root=root, orchestrator_session_id=_PARENT)


def _capability_path(*, root: Path) -> Path:
    return OrchestrationLayout.child_control_capability_path(
        history_root=root, orchestrator_session_id=_PARENT
    )


def _request_path(*, root: Path, request: ChildAbortRequestDAO) -> Path:
    return OrchestrationLayout.child_abort_request_path(
        history_root=root,
        orchestrator_session_id=_PARENT,
        run_id=request.run_id,
        request_id=request.request_id,
    )


def _receipt_path(*, root: Path, request: ChildAbortRequestDAO) -> Path:
    return OrchestrationLayout.child_abort_receipt_path(
        history_root=root,
        orchestrator_session_id=_PARENT,
        run_id=request.run_id,
        request_id=request.request_id,
    )


def _tree(*, root: Path) -> list[str]:
    """Return every path below ``root`` so forbidden writes are visible."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


class TestCapability:
    """Runner capability publication and pure, bounded reads."""

    async def test_write_then_load_round_trips_privately(self, tmp_path: Path) -> None:
        """The capability is published with private modes and read back exactly."""
        store = _store(root=tmp_path)

        await store.write_capability(capability=_capability())

        assert await store.load_capability() == _capability()
        path = _capability_path(root=tmp_path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700

    async def test_withdrawal_replaces_accepting_flag(self, tmp_path: Path) -> None:
        """A later write replaces the earlier capability atomically."""
        store = _store(root=tmp_path)
        await store.write_capability(capability=_capability())

        await store.write_capability(capability=_capability(accepting=False))

        loaded = await store.load_capability()
        assert loaded is not None and loaded.accepting is False

    async def test_foreign_parent_capability_is_refused_before_write(self, tmp_path: Path) -> None:
        """A capability naming another parent is never written under this parent."""
        store = _store(root=tmp_path)

        with pytest.raises(ValueError):
            await store.write_capability(capability=_capability(orchestrator_session_id="other-orch"))

        assert _tree(root=tmp_path) == []

    async def test_missing_capability_is_none_and_reader_creates_nothing(self, tmp_path: Path) -> None:
        """A pure reader never mkdirs or chmods; absence is None."""
        assert await _store(root=tmp_path).load_capability() is None
        assert _tree(root=tmp_path) == []

    @pytest.mark.parametrize(
        "content",
        [b"{not json", b'{"schema_version": 2}', b"x" * (MAX_CONTROL_FILE_BYTES + 1)],
        ids=["corrupt", "wrong-schema", "oversized"],
    )
    async def test_corrupt_or_oversized_capability_is_none(self, tmp_path: Path, content: bytes) -> None:
        """Corrupt, unknown-schema and oversized capability files mean unavailable."""
        path = _capability_path(root=tmp_path)
        path.parent.mkdir(parents=True)
        path.write_bytes(content)

        assert await _store(root=tmp_path).load_capability() is None

    async def test_capability_for_another_parent_on_disk_is_none(self, tmp_path: Path) -> None:
        """A planted capability naming a different parent never authorizes this one."""
        path = _capability_path(root=tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(_capability(orchestrator_session_id="other-orch").model_dump_json(), encoding="utf-8")

        assert await _store(root=tmp_path).load_capability() is None

    async def test_symlinked_capability_is_not_followed(self, tmp_path: Path) -> None:
        """A symlink planted at the capability path is never followed."""
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(_capability().model_dump_json(), encoding="utf-8")
        path = _capability_path(root=tmp_path)
        path.parent.mkdir(parents=True)
        path.symlink_to(elsewhere)

        assert await _store(root=tmp_path).load_capability() is None

    async def test_symlinked_control_directory_is_not_followed(self, tmp_path: Path) -> None:
        """A replaced control directory pointing at another temp directory is refused."""
        other = tmp_path / "other"
        other.mkdir()
        (other / "capability.json").write_text(_capability().model_dump_json(), encoding="utf-8")
        control_dir = _capability_path(root=tmp_path).parent
        control_dir.parent.mkdir(parents=True)
        control_dir.symlink_to(other, target_is_directory=True)

        assert await _store(root=tmp_path).load_capability() is None
        with pytest.raises(OSError):
            await _store(root=tmp_path).write_capability(capability=_capability())
        assert json.loads((other / "capability.json").read_text(encoding="utf-8"))["accepting"] is True

    def test_unsafe_parent_identity_is_refused(self, tmp_path: Path) -> None:
        """The store binds only a safe parent path component."""
        with pytest.raises(ValueError):
            ChildAbortStore(history_root=tmp_path, orchestrator_session_id="../escape")


async def _accepting_store(*, root: Path) -> ChildAbortStore:
    """Return a store whose parent publishes this run's accepting capability."""
    store = _store(root=root)
    await store.write_capability(capability=_capability())
    return store


def _plant_requests(*, root: Path, count: int) -> None:
    """Commit ``count`` distinct well-formed requests directly on disk."""
    for _ in range(count):
        request = _request()
        path = _request_path(root=root, request=request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(request.model_dump_json(), encoding="utf-8")


def _request_files(*, root: Path, run_id: str = _RUN_ID) -> list[Path]:
    requests_dir = _request_path(root=root, request=_request(run_id=run_id)).parent
    return sorted(requests_dir.glob("*.json")) if requests_dir.is_dir() else []


class TestSubmit:
    """Durable admission: capability, immutable IDs, capacity and storage truth."""

    async def test_submit_commits_private_immutable_request(self, tmp_path: Path) -> None:
        """A committed request decodes to the exact payload and is acknowledged as requested."""
        store = await _accepting_store(root=tmp_path)
        request = _request()

        outcome: ChildAbortOutcomeDAO = await store.submit(request=request)

        assert (outcome.outcome, outcome.request_id, outcome.execution_id) == (
            "requested",
            request.request_id,
            _EXECUTION_ID,
        )
        assert outcome == ChildAbortOutcomeDAO.admitted(request=request, durability_warning=False)
        path = _request_path(root=tmp_path, request=request)
        assert ChildAbortRequestDAO.model_validate_json(path.read_bytes()) == request
        assert path.stat().st_mode & 0o777 == 0o600
        assert not (tmp_path / _PARENT / "abort_request.json").exists()

    @pytest.mark.parametrize(
        "capability",
        [
            None,
            _capability(accepting=False),
            _capability(run_id=_OTHER_RUN_ID),
            _capability(owner_session_id="intruder"),
        ],
        ids=["missing", "withdrawn", "other-run", "other-owner"],
    )
    async def test_submit_requires_matching_accepting_capability(
        self, tmp_path: Path, capability: Optional[ChildControlCapabilityDAO]
    ) -> None:
        """Without this run's accepting capability nothing is committed."""
        store = _store(root=tmp_path)
        if capability is not None:
            await store.write_capability(capability=capability)

        with pytest.raises(ValueError):
            await store.submit(request=_request())

        assert _request_files(root=tmp_path) == []

    async def test_missing_control_directory_creates_nothing(self, tmp_path: Path) -> None:
        """A TUI writer never creates the parent's control tree for an unpublished run."""
        with pytest.raises(ValueError):
            await _store(root=tmp_path).submit(request=_request())

        assert _tree(root=tmp_path) == []

    async def test_request_for_another_parent_is_refused(self, tmp_path: Path) -> None:
        """A store bound to one parent never commits a request naming another."""
        store = await _accepting_store(root=tmp_path)

        with pytest.raises(ValueError):
            await store.submit(request=_request(orchestrator_session_id="other-orch"))

        assert _request_files(root=tmp_path) == []

    async def test_duplicate_same_payload_is_idempotent(self, tmp_path: Path) -> None:
        """Resubmitting identical bytes acknowledges the existing admission without a rewrite."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        await store.submit(request=request)
        path = _request_path(root=tmp_path, request=request)
        first_inode: int = path.stat().st_ino

        outcome = await store.submit(request=request)

        assert outcome.outcome == "requested"
        assert path.stat().st_ino == first_inode
        assert len(_request_files(root=tmp_path)) == 1

    async def test_conflicting_payload_for_same_id_is_refused(self, tmp_path: Path) -> None:
        """An immutable request ID never changes target; the original bytes survive."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        await store.submit(request=request)
        original: bytes = _request_path(root=tmp_path, request=request).read_bytes()

        with pytest.raises(ValueError):
            await store.submit(request=_request(request_id=request.request_id, session_id="child-2"))

        assert _request_path(root=tmp_path, request=request).read_bytes() == original

    async def test_malformed_file_with_same_id_is_never_overwritten(self, tmp_path: Path) -> None:
        """A malformed committed file blocks its ID; it is never replaced."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        path = _request_path(root=tmp_path, request=request)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"{garbage")

        with pytest.raises(ValueError):
            await store.submit(request=request)

        assert path.read_bytes() == b"{garbage"

    async def test_capacity_refuses_new_id_but_duplicate_stays_idempotent(self, tmp_path: Path) -> None:
        """At capacity a new ID is refused; an already committed ID still acknowledges."""
        store = await _accepting_store(root=tmp_path)
        _plant_requests(root=tmp_path, count=MAX_REQUESTS_PER_RUN - 1)
        last = _request()
        assert (await store.submit(request=last)).outcome == "requested"

        with pytest.raises(ValueError):
            await store.submit(request=_request())

        assert (await store.submit(request=last)).outcome == "requested"
        assert len(_request_files(root=tmp_path)) == MAX_REQUESTS_PER_RUN

    async def test_malformed_files_count_toward_capacity(self, tmp_path: Path) -> None:
        """Malformed UUID-named files occupy capacity; they are never pruned to make room."""
        store = await _accepting_store(root=tmp_path)
        _plant_requests(root=tmp_path, count=MAX_REQUESTS_PER_RUN - 1)
        junk = _request_path(root=tmp_path, request=_request())
        junk.write_bytes(b"not json")

        with pytest.raises(ValueError):
            await store.submit(request=_request())

        assert junk.read_bytes() == b"not json"

    async def test_two_concurrent_writers_at_last_slot_admit_exactly_one(self, tmp_path: Path) -> None:
        """The run-scoped admission lock makes count-then-commit atomic across writers."""
        store = await _accepting_store(root=tmp_path)
        _plant_requests(root=tmp_path, count=MAX_REQUESTS_PER_RUN - 1)
        both_counting = threading.Barrier(parties=2, timeout=5.0)
        real_count: Callable[..., int] = ChildAbortStore._request_count

        def counting_together(*args: object, **kwargs: object) -> int:
            try:
                both_counting.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass  # the lock let only one writer count; that is the point
            return real_count(*args, **kwargs)

        with patch.object(ChildAbortStore, "_request_count", side_effect=counting_together, autospec=True):
            outcomes = await asyncio.gather(
                store.submit(request=_request()), store.submit(request=_request()), return_exceptions=True
            )

        admitted = [o for o in outcomes if isinstance(o, ChildAbortOutcomeDAO)]
        refused = [o for o in outcomes if isinstance(o, ValueError)]
        assert (len(admitted), len(refused)) == (1, 1)
        assert len(_request_files(root=tmp_path)) == MAX_REQUESTS_PER_RUN

    async def test_storage_error_before_commit_propagates(self, tmp_path: Path) -> None:
        """A write failure before commit is an OSError; nothing is acknowledged or left behind."""
        store = await _accepting_store(root=tmp_path)

        with patch.object(
            child_abort.AtomicFileWriter, "write_text_with_outcome", side_effect=OSError("disk full")
        ):
            with pytest.raises(OSError):
                await store.submit(request=_request())

        assert _request_files(root=tmp_path) == []

    async def test_durability_warning_is_still_requested(self, tmp_path: Path) -> None:
        """A committed write with unconfirmed fsync is admitted with the fixed durability notice."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        real_write = child_abort.AtomicFileWriter.write_text_with_outcome

        def committed_without_fsync(**kwargs: object) -> AtomicWriteOutcomeDAO:
            real_write(**kwargs)  # type: ignore[arg-type]
            return AtomicWriteOutcomeDAO(committed=True, durability_warning=True)

        with patch.object(
            child_abort.AtomicFileWriter, "write_text_with_outcome", side_effect=committed_without_fsync
        ):
            outcome = await store.submit(request=request)

        assert outcome == ChildAbortOutcomeDAO.admitted(request=request, durability_warning=True)
        assert _request_path(root=tmp_path, request=request).is_file()

    async def test_symlinked_requests_directory_is_refused(self, tmp_path: Path) -> None:
        """A requests directory replaced by a link to another temp directory is never written through."""
        store = await _accepting_store(root=tmp_path)
        other = tmp_path / "other"
        other.mkdir()
        requests_dir = _request_path(root=tmp_path, request=_request()).parent
        requests_dir.parent.mkdir(parents=True)
        requests_dir.symlink_to(other, target_is_directory=True)

        with pytest.raises(OSError):
            await store.submit(request=_request())

        assert list(other.iterdir()) == []

    async def test_run_directory_replaced_after_hold_is_refused_before_commit(self, tmp_path: Path) -> None:
        """A run directory swapped while held is detected before AtomicFileWriter commits."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        run_dir = _request_path(root=tmp_path, request=request).parent.parent
        moved = tmp_path / "moved-run"
        real_count: Callable[..., int] = ChildAbortStore._request_count

        def swap_then_count(*args: object, **kwargs: object) -> int:
            os.rename(run_dir, moved)
            (run_dir / "requests").mkdir(parents=True)
            return real_count(*args, **kwargs)

        with patch.object(ChildAbortStore, "_request_count", side_effect=swap_then_count, autospec=True):
            with pytest.raises(OSError):
                await store.submit(request=request)

        assert list((run_dir / "requests").iterdir()) == []
        assert list((moved / "requests").glob("*.json")) == []


def _write_request_file(
    *, root: Path, request: ChildAbortRequestDAO, run_id: str = _RUN_ID, name: str = ""
) -> Path:
    """Place a request payload in ``run_id``'s directory, optionally under another name."""
    requests_dir = _request_path(root=root, request=_request(run_id=run_id)).parent
    requests_dir.mkdir(parents=True, exist_ok=True)
    path = requests_dir / (name or f"{request.request_id}.json")
    path.write_text(request.model_dump_json(), encoding="utf-8")
    return path


class TestReadPending:
    """Bounded consumer scan: only valid current-run requests reach execution."""

    async def test_valid_requests_are_returned_sorted(self, tmp_path: Path) -> None:
        """Committed requests come back in request-ID order."""
        store = await _accepting_store(root=tmp_path)
        requests = [_request() for _ in range(3)]
        for request in requests:
            await store.submit(request=request)

        pending = await store.read_pending(run_id=_RUN_ID)

        assert pending == sorted(requests, key=lambda r: r.request_id)

    async def test_missing_run_directory_is_empty_and_creates_nothing(self, tmp_path: Path) -> None:
        """A run with no requests yields nothing and the reader creates no directory."""
        store = await _accepting_store(root=tmp_path)
        before = _tree(root=tmp_path)

        assert await store.read_pending(run_id=_RUN_ID) == []
        assert _tree(root=tmp_path) == before

    async def test_non_uuid_names_and_side_files_are_ignored(self, tmp_path: Path) -> None:
        """Lock files, temp siblings and non-UUID names are never decoded as requests."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        await store.submit(request=request)
        requests_dir = _request_path(root=tmp_path, request=request).parent
        (requests_dir / "notes.json").write_text(_request().model_dump_json(), encoding="utf-8")
        (requests_dir / "tmpabc123").write_text("partial", encoding="utf-8")
        (requests_dir / "NESTED").mkdir()

        assert await store.read_pending(run_id=_RUN_ID) == [request]

    @pytest.mark.parametrize("kind", ["malformed", "oversized", "symlink", "fifo", "renamed"])
    async def test_unaddressable_files_are_skipped_without_receipt(self, tmp_path: Path, kind: str) -> None:
        """Files that cannot be safely bound to a request are skipped; no receipt is invented."""
        store = await _accepting_store(root=tmp_path)
        good = _request()
        await store.submit(request=good)
        bad_id = str(uuid4())
        requests_dir = _request_path(root=tmp_path, request=good).parent
        bad_path = requests_dir / f"{bad_id}.json"
        if kind == "malformed":
            bad_path.write_bytes(b"{")
        if kind == "oversized":
            bad_path.write_bytes(b" " * (MAX_CONTROL_FILE_BYTES + 1))
        if kind == "symlink":
            target = tmp_path / "target.json"
            target.write_text(_request(request_id=bad_id).model_dump_json(), encoding="utf-8")
            bad_path.symlink_to(target)
        if kind == "fifo":
            os.mkfifo(bad_path)
        if kind == "renamed":
            bad_path.write_text(_request().model_dump_json(), encoding="utf-8")

        pending = await store.read_pending(run_id=_RUN_ID)

        assert pending == [good]
        receipts_dir = _receipt_path(root=tmp_path, request=good).parent
        assert not receipts_dir.exists() or list(receipts_dir.iterdir()) == []

    @pytest.mark.parametrize(
        "overrides",
        [{"run_id": _OTHER_RUN_ID}, {"orchestrator_session_id": "other-orch"}],
        ids=["stale-run", "other-parent"],
    )
    async def test_addressable_invalid_request_gets_unavailable_receipt_and_never_executes(
        self, tmp_path: Path, overrides: dict[str, str]
    ) -> None:
        """A decodable request whose payload contradicts its directory is refused durably."""
        store = await _accepting_store(root=tmp_path)
        stale = _request(**overrides)
        _write_request_file(root=tmp_path, request=stale, run_id=_RUN_ID)

        pending = await store.read_pending(run_id=_RUN_ID)

        assert pending == []
        receipt_path = OrchestrationLayout.child_abort_receipt_path(
            history_root=tmp_path,
            orchestrator_session_id=_PARENT,
            run_id=_RUN_ID,
            request_id=stale.request_id,
        )
        receipt = ChildAbortOutcomeDAO.model_validate_json(receipt_path.read_bytes())
        assert receipt == ChildAbortOutcomeDAO.for_request(request=stale, outcome="unavailable")
        assert receipt_path.stat().st_mode & 0o777 == 0o600

    async def test_scan_returns_at_most_capacity(self, tmp_path: Path) -> None:
        """Even an over-full directory yields at most the per-run capacity."""
        store = await _accepting_store(root=tmp_path)
        _plant_requests(root=tmp_path, count=MAX_REQUESTS_PER_RUN + 4)

        pending = await store.read_pending(run_id=_RUN_ID)

        assert len(pending) == MAX_REQUESTS_PER_RUN
        assert [r.request_id for r in pending] == sorted(r.request_id for r in pending)


class TestReceipts:
    """Receipts settle only their exact request and never another child."""

    async def test_write_then_load_receipt(self, tmp_path: Path) -> None:
        """A receipt round-trips for its own request with private modes."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        outcome = ChildAbortOutcomeDAO.for_request(
            request=request, outcome="aborted", terminal_status="aborted"
        )

        await store.write_receipt(request=request, outcome=outcome)

        assert await store.load_receipt(request=request) == outcome
        assert _receipt_path(root=tmp_path, request=request).stat().st_mode & 0o777 == 0o600

    async def test_missing_receipt_is_none_and_creates_nothing(self, tmp_path: Path) -> None:
        """No receipt yet means pending; the reader creates no directory."""
        store = await _accepting_store(root=tmp_path)
        before = _tree(root=tmp_path)

        assert await store.load_receipt(request=_request()) is None
        assert _tree(root=tmp_path) == before

    @pytest.mark.parametrize("field", ["request_id", "session_id", "execution_id"])
    async def test_write_receipt_refuses_mismatched_identity(self, tmp_path: Path, field: str) -> None:
        """A receipt can never be written for a different request, child or incarnation."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        replacement = {"request_id": str(uuid4()), "session_id": "child-2", "execution_id": str(uuid4())}[
            field
        ]
        outcome = ChildAbortOutcomeDAO.for_request(request=request, outcome="aborted").model_copy(
            update={field: replacement}
        )

        with pytest.raises(ValueError):
            await store.write_receipt(request=request, outcome=outcome)

        assert not _receipt_path(root=tmp_path, request=request).exists()

    @pytest.mark.parametrize("content", ["mismatch", "malformed"])
    async def test_mismatched_or_corrupt_receipt_loads_as_unavailable(
        self, tmp_path: Path, content: str
    ) -> None:
        """A receipt naming another child, or a corrupt one, never settles this request as done."""
        store = await _accepting_store(root=tmp_path)
        request = _request()
        path = _receipt_path(root=tmp_path, request=request)
        path.parent.mkdir(parents=True)
        other = _request(request_id=request.request_id, session_id="child-2")
        payload = ChildAbortOutcomeDAO.for_request(request=other, outcome="aborted").model_dump_json()
        path.write_text(payload if content == "mismatch" else "{", encoding="utf-8")

        loaded = await store.load_receipt(request=request)

        assert loaded == ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable")

    async def test_receipt_write_failure_propagates(self, tmp_path: Path) -> None:
        """A failed receipt write is an OSError so the controller can retry the write only."""
        store = await _accepting_store(root=tmp_path)
        request = _request()

        with patch.object(child_abort.AtomicFileWriter, "write_text_with_outcome", side_effect=OSError("io")):
            with pytest.raises(OSError):
                await store.write_receipt(
                    request=request,
                    outcome=ChildAbortOutcomeDAO.for_request(request=request, outcome="aborted"),
                )
