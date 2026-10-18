"""Versioned child-control protocol: durable requests/receipts and their runner consumer.

Feature 94.a.4 (T10). A detached TUI cannot call the owning ``SubAgentPool``
directly, so it commits an immutable request file below the parent's
``child-control.v1`` directory. The runner's ``ChildAbortController`` consumes
those requests, hands them to ``SubAgentPool.abort_child`` (the sole execution
authority) and persists one receipt per request.

``ChildAbortStore`` is a file adapter, never state authority. It owns bounded
reads, immutable request IDs and run capacity; ``OrchestrationLayout`` owns path
names and ``AtomicFileWriter`` owns replace/fsync. The old existence-triggered
``abort_request.json`` is never read, written or deleted here.

Threat boundary: the history root is a trusted private directory. Inside it,
every open walks descriptor-relative with ``O_NOFOLLOW`` so a planted symlink is
never followed, and a write first proves the path still names the held
directory, rejecting a detected replacement before commit.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import islice
from pathlib import Path
from types import TracebackType
from typing import Optional, Protocol

from pydantic import BaseModel

from config.logger import log_warning
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter, AtomicWriteOutcomeDAO
from src.agents.slo_agent.orchestrator.dao import (
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    canonical_uuid,
    safe_identifier,
)
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

__all__ = [
    "MAX_CONTROL_FILE_BYTES",
    "MAX_REQUESTS_PER_RUN",
    "POLL_INTERVAL_SECONDS",
    "ChildAbortController",
    "ChildAbortGateway",
    "ChildAbortStore",
    "ChildControlPollClock",
    "IntervalPollClock",
]

MAX_CONTROL_FILE_BYTES: int = 64 * 1024
"""Largest capability, request or receipt file decoded; larger files are refused unread."""

MAX_REQUESTS_PER_RUN: int = 256
"""Explicit per-run request capacity; a full run refuses new IDs as unavailable."""

POLL_INTERVAL_SECONDS: float = 1.0
"""Controller poll period; independent of provider and dispatch awaits."""

_OPEN_DIRECTORY_FLAGS: int = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_OPEN_FILE_FLAGS: int = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_PRIVATE_DIRECTORY_MODE: int = 0o700
_PRIVATE_FILE_MODE: int = 0o600
_ADMISSION_LOCK_NAME: str = "admission.lock"
"""Run-scoped lock serializing capacity counting, immutable-ID checks and commits."""
_MAX_SCANNED_ENTRIES: int = 4 * MAX_REQUESTS_PER_RUN
"""Directory scan bound. Writer temp siblings also occupy entries, so the bound
exceeds capacity; a scan that reaches it is treated as a full run."""
_ABSENT_ERRNOS: frozenset[int] = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})
"""Open failures that mean "no trustworthy object here": missing, or a refused symlink."""


class _HeldDirectory:
    """One open, no-follow directory descriptor inside the trusted history root.

    The descriptor is the authority for reads; ``path`` is only used to hand a
    destination to ``AtomicFileWriter`` after proving it still names this
    descriptor. Use as a context manager; the descriptor closes on exit.

    Attributes:
        fd (int): Open directory descriptor owned by this object.
        path (Path): Path the descriptor was opened through.
    """

    def __init__(self, *, fd: int, path: Path) -> None:
        """Adopt an already opened directory descriptor.

        Args:
            fd (int): Directory descriptor; closed by ``__exit__``.
            path (Path): Path the descriptor was opened through.
        """
        self.fd: int = fd
        self.path: Path = path

    @classmethod
    def open_existing(cls, *, root: Path, directory: Path) -> Optional["_HeldDirectory"]:
        """Hold an existing directory for a pure read; never mkdir or chmod.

        WHO: ChildAbortStore readers and the TUI submit path's control directory.
        WHEN: Before every capability, request or receipt read.

        Args:
            root (Path): Trusted history root.
            directory (Path): Target below ``root`` built by OrchestrationLayout.

        Returns:
            Optional[_HeldDirectory]: Held target, or None when a component is
                missing or a refused symlink.

        Raises:
            OSError: Genuine I/O failure other than absence.
        """
        try:
            return cls(fd=cls._walk(root=root, directory=directory, create=False), path=directory)
        except OSError as error:
            return cls._absent_or_raise(error=error, create=False)

    @classmethod
    def open_created(cls, *, root: Path, directory: Path) -> "_HeldDirectory":
        """Hold a directory for a write, creating missing components privately.

        WHO: ChildAbortStore writers (capability, run admission, receipts).
        WHEN: Before every durable child-control write.

        Args:
            root (Path): Trusted history root; created when missing.
            directory (Path): Target below ``root`` built by OrchestrationLayout.

        Returns:
            _HeldDirectory: Held target directory.

        Raises:
            OSError: A component is a refused symlink or the filesystem failed.
        """
        root.mkdir(parents=True, exist_ok=True)
        return cls(fd=cls._walk(root=root, directory=directory, create=True), path=directory)

    @classmethod
    def _walk(cls, *, root: Path, directory: Path, create: bool) -> int:
        """Open ``directory`` one descriptor-relative, no-follow component at a time.

        Args:
            root (Path): Trusted history root (the only path opened by name).
            directory (Path): Target below ``root``.
            create (bool): Create missing components with private modes.

        Returns:
            int: Open descriptor of ``directory``.

        Raises:
            OSError: A component is missing (reader), a symlink, or unreadable.
        """
        return cls._walk_from(
            fd=os.open(root, os.O_RDONLY | os.O_DIRECTORY),
            components=directory.relative_to(root).parts,
            create=create,
        )

    @classmethod
    def _walk_from(cls, *, fd: int, components: tuple[str, ...], create: bool) -> int:
        """Descend ``components`` from an owned descriptor without following links.

        Args:
            fd (int): Starting directory descriptor; ownership passes to this call.
            components (tuple[str, ...]): Single path components to descend.
            create (bool): Create missing components with private modes.

        Returns:
            int: Open descriptor of the final component.

        Raises:
            OSError: A component is missing (reader), a symlink, or unreadable.
        """
        for component in components:
            fd = cls._open_child(parent_fd=fd, name=component, create=create)
        return fd

    def descend_created(self, *, directory: Path) -> "_HeldDirectory":
        """Hold a directory below this one, creating missing components privately.

        Args:
            directory (Path): Target below ``self.path``.

        Returns:
            _HeldDirectory: Held target directory.

        Raises:
            OSError: A component is a refused symlink or the filesystem failed.
        """
        fd: int = self._walk_from(
            fd=os.dup(self.fd), components=directory.relative_to(self.path).parts, create=True
        )
        return _HeldDirectory(fd=fd, path=directory)

    @contextmanager
    def exclusive_lock(self, *, name: str) -> Iterator[None]:
        """Hold a cross-process ``flock`` on a private lock file inside this directory.

        WHAT: The lock file is opened no-follow relative to this descriptor, so
            a planted link cannot redirect it; the lock releases on exit.
        WHO: ChildAbortStore run admission.
        WHEN: Around count-then-commit and immutable-payload checks.

        Args:
            name (str): Lock file name inside this directory.

        Yields:
            None: While the exclusive lock is held.

        Raises:
            OSError: The lock file cannot be opened or locked.
        """
        lock_fd: int = os.open(
            name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, _PRIVATE_FILE_MODE, dir_fd=self.fd
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(lock_fd)

    def scan_names(self) -> list[str]:
        """Return the names of at most ``_MAX_SCANNED_ENTRIES`` entries, without recursion.

        Returns:
            list[str]: Entry names in directory order; a full list means the scan
                stopped at its bound.

        Raises:
            OSError: The directory cannot be listed.
        """
        with os.scandir(self.fd) as entries:
            return [entry.name for entry in islice(entries, _MAX_SCANNED_ENTRIES)]

    @staticmethod
    def _open_child(*, parent_fd: int, name: str, create: bool) -> int:
        """Open one child directory without following links, closing the parent.

        Args:
            parent_fd (int): Parent descriptor; always closed by this call.
            name (str): Single path component.
            create (bool): Create the component privately when missing.

        Returns:
            int: Child directory descriptor.

        Raises:
            OSError: The component is missing (reader), a symlink, or unreadable.
        """
        try:
            if create:
                try:
                    os.mkdir(name, mode=_PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
                except FileExistsError:
                    pass
            return os.open(name, _OPEN_DIRECTORY_FLAGS, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)

    @staticmethod
    def _absent_or_raise(*, error: OSError, create: bool) -> None:
        """Translate a reader's missing/refused component into absence.

        Args:
            error (OSError): Failure raised while opening a component.
            create (bool): True for writers, which never treat failure as absence.

        Raises:
            OSError: For writers, and for readers on genuine I/O faults.
        """
        if create or error.errno not in _ABSENT_ERRNOS:
            raise error
        return None

    def __enter__(self) -> "_HeldDirectory":
        """Return self for a ``with`` block that owns the descriptor."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Close the held descriptor."""
        os.close(self.fd)

    def read_bounded(self, *, name: str) -> Optional[bytes]:
        """Read one regular file below this directory, stopping past the byte budget.

        Args:
            name (str): File name inside this directory.

        Returns:
            Optional[bytes]: File bytes, or None when absent or a refused symlink.

        Raises:
            ValueError: The entry is not a regular file or exceeds the budget.
            OSError: Genuine read failure.
        """
        try:
            descriptor: int = os.open(name, _OPEN_FILE_FLAGS, dir_fd=self.fd)
        except OSError as error:
            return self._absent_or_raise(error=error, create=False)
        with os.fdopen(descriptor, "rb") as control_file:
            if not stat.S_ISREG(os.fstat(control_file.fileno()).st_mode):
                raise ValueError("child control entry is not a regular file")
            data: bytes = control_file.read(MAX_CONTROL_FILE_BYTES + 1)
        if len(data) > MAX_CONTROL_FILE_BYTES:
            raise ValueError("child control file exceeds its byte budget")
        return data

    def write_model(self, *, name: str, model: BaseModel) -> AtomicWriteOutcomeDAO:
        """Atomically publish one model below this directory after a replacement check.

        Args:
            name (str): Destination file name inside this directory.
            model (BaseModel): Complete record to serialize.

        Returns:
            AtomicWriteOutcomeDAO: Commit and durability outcome from AtomicFileWriter.

        Raises:
            OSError: The path no longer names the held directory, or the write failed.
        """
        self.require_unreplaced()
        return AtomicFileWriter.write_text_with_outcome(
            path=self.path / name, text=model.model_dump_json(), private=True
        )

    def require_unreplaced(self) -> None:
        """Prove the path still resolves to the held directory before a commit.

        Raises:
            OSError: The directory was replaced or re-pointed since it was opened.
        """
        current: os.stat_result = os.stat(self.path)
        held: os.stat_result = os.fstat(self.fd)
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise OSError(errno.ESTALE, "child control directory was replaced")


class ChildAbortStore:
    """File adapter for one parent's versioned child-control capability, requests and receipts.

    Bound once per parent orchestrator; ``run_id`` is always a method input.
    The TUI submits through it and reads receipts; the runner's controller
    reads pending requests and writes the capability and receipts. Blocking
    leaf I/O is offloaded with ``asyncio.to_thread``.

    Attributes:
        _history_root (Path): Trusted private history root shared with the session store.
        _orchestrator_session_id (str): Validated parent session identity.
    """

    def __init__(self, *, history_root: Path, orchestrator_session_id: str) -> None:
        """Bind the trusted root and one validated parent identity.

        Args:
            history_root (Path): Same history root the session/handle stores use.
            orchestrator_session_id (str): Parent orchestrator session.

        Raises:
            ValueError: The parent identity is unsafe as a path component.
        """
        self._history_root: Path = history_root
        self._orchestrator_session_id: str = safe_identifier(value=orchestrator_session_id)

    # ── capability ───────────────────────────────────────────────────────────

    async def write_capability(self, *, capability: ChildControlCapabilityDAO) -> None:
        """Publish or withdraw this parent's child-control capability.

        WHAT: Atomically replaces ``capability.json`` with private modes.
        WHO: ChildAbortController.start (accepting) and close (withdrawn).
        WHEN: After the pool is ready, and again at runner shutdown.

        Args:
            capability (ChildControlCapabilityDAO): Capability for this parent.

        Raises:
            ValueError: The capability names another parent.
            OSError: The write failed or a control directory was refused.
        """
        if capability.orchestrator_session_id != self._orchestrator_session_id:
            raise ValueError("child control capability names another parent")
        await asyncio.to_thread(self._write_capability_sync, capability=capability)

    def _write_capability_sync(self, *, capability: ChildControlCapabilityDAO) -> None:
        """Write the capability below a held, created control directory.

        Args:
            capability (ChildControlCapabilityDAO): Validated capability.
        """
        with _HeldDirectory.open_created(root=self._history_root, directory=self._control_dir()) as held:
            held.write_model(name=self._capability_name(), model=capability)

    async def load_capability(self) -> Optional[ChildControlCapabilityDAO]:
        """Read this parent's capability without creating or chmodding anything.

        WHAT: Missing, symlinked, corrupt, oversized or foreign-parent files all
            mean "no valid capability" so callers report unavailable.
        WHO: ChildAbortStore.submit under its admission lock; the TUI service.
        WHEN: At confirmation and immediately before committing a request.

        Returns:
            Optional[ChildControlCapabilityDAO]: Valid capability, or None.

        Raises:
            OSError: Genuine I/O failure other than absence.
        """
        return await asyncio.to_thread(self._load_capability_sync)

    def _load_capability_sync(self) -> Optional[ChildControlCapabilityDAO]:
        """Read and validate the capability synchronously.

        Returns:
            Optional[ChildControlCapabilityDAO]: Valid capability for this parent, or None.
        """
        held: Optional[_HeldDirectory] = _HeldDirectory.open_existing(
            root=self._history_root, directory=self._control_dir()
        )
        if held is None:
            return None
        with held:
            return self._decode_capability(held=held)

    def _decode_capability(self, *, held: _HeldDirectory) -> Optional[ChildControlCapabilityDAO]:
        """Decode the held directory's capability, refusing invalid content.

        Args:
            held (_HeldDirectory): Held control directory.

        Returns:
            Optional[ChildControlCapabilityDAO]: Valid capability for this parent, or None.
        """
        try:
            data: Optional[bytes] = held.read_bounded(name=self._capability_name())
            capability: Optional[ChildControlCapabilityDAO] = (
                None if data is None else ChildControlCapabilityDAO.model_validate_json(data)
            )
        except ValueError:
            log_warning(msg="child_control_capability_invalid")
            return None
        if capability is None or capability.orchestrator_session_id != self._orchestrator_session_id:
            return None
        return capability

    # ── submission (TUI side) ────────────────────────────────────────────────

    async def submit(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Commit one immutable request for the TUI without running cancellation.

        WHAT: Durable request commit is the admission boundary: ``requested`` is
            returned only after atomic visibility (with a fixed notice when
            durability is unconfirmed). Cancellation stays with the runner's pool.
        WHO: The TUI workflow service after it revalidated the confirmed target.
        WHEN: Once per confirmed target; an identical retry is idempotent.

        Args:
            request (ChildAbortRequestDAO): Validated owner/run/execution request.

        Returns:
            ChildAbortOutcomeDAO: Durable ``requested`` acknowledgement.

        Raises:
            OSError: Write failed before commit, or a control directory was refused.
            ValueError: No matching accepting capability, foreign parent,
                immutable-ID conflict, or capacity refusal.
        """
        self._require_own_parent(request=request)
        return await asyncio.to_thread(self._submit_sync, request=request)

    def _submit_sync(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Serialize capacity admission and immutable-ID validation for submit.

        Args:
            request (ChildAbortRequestDAO): Request captured before off-loop work.

        Returns:
            ChildAbortOutcomeDAO: Requested only after atomic visibility.

        Raises:
            ValueError: The parent never published a control directory.
        """
        control: Optional[_HeldDirectory] = _HeldDirectory.open_existing(
            root=self._history_root, directory=self._control_dir()
        )
        if control is None:
            raise ValueError("child control unavailable for this run")
        with control, self._admitted_requests_dir(control=control, run_id=request.run_id) as requests_dir:
            self._require_accepting(control=control, request=request)
            existing: Optional[ChildAbortRequestDAO] = self._read_request(
                requests_dir=requests_dir, request_id=request.request_id
            )
            if existing is not None:
                return self._acknowledge_duplicate(existing=existing, request=request)
            return self._commit_request(requests_dir=requests_dir, request=request)

    @contextmanager
    def _admitted_requests_dir(self, *, control: _HeldDirectory, run_id: str) -> Iterator[_HeldDirectory]:
        """Hold the run's requests directory under the run-scoped admission lock.

        Args:
            control (_HeldDirectory): Held, pre-existing control directory.
            run_id (str): Canonical run UUID addressed by the request.

        Yields:
            _HeldDirectory: Requests directory, valid while the lock is held.
        """
        requests_path: Path = self._requests_dir(run_id=run_id)
        with control.descend_created(directory=requests_path.parent) as run_dir:
            with run_dir.exclusive_lock(name=_ADMISSION_LOCK_NAME):
                with run_dir.descend_created(directory=requests_path) as requests_dir:
                    yield requests_dir

    def _require_accepting(self, *, control: _HeldDirectory, request: ChildAbortRequestDAO) -> None:
        """Reread the capability under the lock and require this exact accepting run.

        Args:
            control (_HeldDirectory): Held control directory.
            request (ChildAbortRequestDAO): Request being admitted.

        Raises:
            ValueError: Capability missing, withdrawn, or for another run/owner.
        """
        capability: Optional[ChildControlCapabilityDAO] = self._decode_capability(held=control)
        if capability is None or not capability.accepting:
            raise ValueError("child control unavailable for this run")
        if (capability.run_id, capability.owner_session_id) != (request.run_id, request.owner_session_id):
            raise ValueError("child control unavailable for this run")

    @staticmethod
    def _read_request(*, requests_dir: _HeldDirectory, request_id: str) -> Optional[ChildAbortRequestDAO]:
        """Read an already committed request with this ID, if any.

        Args:
            requests_dir (_HeldDirectory): Held requests directory.
            request_id (str): Canonical request UUID.

        Returns:
            Optional[ChildAbortRequestDAO]: Committed request, or None when absent.

        Raises:
            ValueError: The committed file is malformed, oversized or not regular.
        """
        data: Optional[bytes] = requests_dir.read_bounded(name=f"{request_id}.json")
        if data is None:
            return None
        return ChildAbortRequestDAO.model_validate_json(data)

    def _commit_request(
        self, *, requests_dir: _HeldDirectory, request: ChildAbortRequestDAO
    ) -> ChildAbortOutcomeDAO:
        """Enforce run capacity and atomically publish under the admission lock.

        Args:
            requests_dir (_HeldDirectory): Held requests directory.
            request (ChildAbortRequestDAO): New immutable request.

        Returns:
            ChildAbortOutcomeDAO: Admission with truthful durability notice.

        Raises:
            ValueError: The run already holds its maximum request count.
        """
        if self._request_count(requests_dir=requests_dir) >= MAX_REQUESTS_PER_RUN:
            raise ValueError("child control capacity reached")
        written: AtomicWriteOutcomeDAO = requests_dir.write_model(
            name=f"{request.request_id}.json", model=request
        )
        return ChildAbortOutcomeDAO.admitted(request=request, durability_warning=written.durability_warning)

    def _request_count(self, *, requests_dir: _HeldDirectory) -> int:
        """Count committed request files, malformed ones included.

        Args:
            requests_dir (_HeldDirectory): Held requests directory.

        Returns:
            int: Number of ``<uuid>.json`` entries; a scan that hit its bound
                reports full capacity.
        """
        names: list[str] = requests_dir.scan_names()
        if len(names) >= _MAX_SCANNED_ENTRIES:
            return MAX_REQUESTS_PER_RUN
        return len(_request_ids(names=names))

    @staticmethod
    def _acknowledge_duplicate(
        *, existing: ChildAbortRequestDAO, request: ChildAbortRequestDAO
    ) -> ChildAbortOutcomeDAO:
        """Accept an identical ID retry without overwriting conflicting intent.

        Args:
            existing (ChildAbortRequestDAO): Previously committed request.
            request (ChildAbortRequestDAO): Current submitted payload.

        Returns:
            ChildAbortOutcomeDAO: Existing admission, never a second cancellation.

        Raises:
            ValueError: Same request ID carries different content.
        """
        if existing != request:
            raise ValueError("child control request conflict")
        return ChildAbortOutcomeDAO.admitted(request=request, durability_warning=False)

    def _require_own_parent(self, *, request: ChildAbortRequestDAO) -> None:
        """Refuse a request addressed to a different parent than this store's.

        Args:
            request (ChildAbortRequestDAO): Request to check.

        Raises:
            ValueError: The request names another parent orchestrator.
        """
        if request.orchestrator_session_id != self._orchestrator_session_id:
            raise ValueError("child control request names another parent")

    # ── consumption (runner side) ────────────────────────────────────────────

    async def read_pending(self, *, run_id: str) -> list[ChildAbortRequestDAO]:
        """Return this run's decodable requests, refusing contradictory ones durably.

        WHAT: Scans at most ``MAX_REQUESTS_PER_RUN`` sorted ``<uuid>.json`` names
            without recursion. Malformed, oversized, non-regular, symlinked or
            renamed files are skipped. A decodable request whose payload names
            another run or parent receives an ``unavailable`` receipt and is
            never returned for execution.
        WHO: ChildAbortController on every poll tick.
        WHEN: Once per second while the controller accepts requests.

        Args:
            run_id (str): Canonical UUID of the consuming runner invocation.

        Returns:
            list[ChildAbortRequestDAO]: Current-run requests sorted by request ID.

        Raises:
            OSError: The directory scan or a refusal receipt write failed.
        """
        return await asyncio.to_thread(self._read_pending_sync, run_id=run_id)

    def _read_pending_sync(self, *, run_id: str) -> list[ChildAbortRequestDAO]:
        """Partition decodable requests into current-run work and durable refusals.

        Args:
            run_id (str): Canonical UUID of the consuming runner invocation.

        Returns:
            list[ChildAbortRequestDAO]: Current-run requests sorted by request ID.
        """
        decoded: list[ChildAbortRequestDAO] = self._decodable_requests(run_id=run_id)
        for contradicting in (
            request for request in decoded if not self._belongs(request=request, run_id=run_id)
        ):
            self._refuse_contradicting(request=contradicting, run_id=run_id)
        return [request for request in decoded if self._belongs(request=request, run_id=run_id)]

    def _decodable_requests(self, *, run_id: str) -> list[ChildAbortRequestDAO]:
        """Decode the bounded, sorted request files of one run directory.

        Args:
            run_id (str): Canonical run UUID naming the directory.

        Returns:
            list[ChildAbortRequestDAO]: Requests whose payload ID matches its file name.
        """
        held: Optional[_HeldDirectory] = _HeldDirectory.open_existing(
            root=self._history_root, directory=self._requests_dir(run_id=run_id)
        )
        if held is None:
            return []
        with held:
            request_ids: list[str] = _request_ids(names=held.scan_names())[:MAX_REQUESTS_PER_RUN]
            candidates: list[Optional[ChildAbortRequestDAO]] = [
                self._decode_named_request(requests_dir=held, request_id=request_id)
                for request_id in request_ids
            ]
        return [request for request in candidates if request is not None]

    def _decode_named_request(
        self, *, requests_dir: _HeldDirectory, request_id: str
    ) -> Optional[ChildAbortRequestDAO]:
        """Decode one request file, skipping anything not safely bound to its name.

        Args:
            requests_dir (_HeldDirectory): Held requests directory.
            request_id (str): Request UUID taken from the file name.

        Returns:
            Optional[ChildAbortRequestDAO]: The request, or None when it must be skipped.
        """
        try:
            request: Optional[ChildAbortRequestDAO] = self._read_request(
                requests_dir=requests_dir, request_id=request_id
            )
        except ValueError:
            log_warning(msg="child_control_request_invalid")
            return None
        if request is not None and request.request_id != request_id:
            log_warning(msg="child_control_request_invalid")
            return None
        return request

    def _belongs(self, *, request: ChildAbortRequestDAO, run_id: str) -> bool:
        """Report whether a decoded payload agrees with the directory that holds it.

        Args:
            request (ChildAbortRequestDAO): Decoded request.
            run_id (str): Run UUID naming the directory.

        Returns:
            bool: True when payload run and parent match the directory.
        """
        return (request.run_id, request.orchestrator_session_id) == (run_id, self._orchestrator_session_id)

    def _refuse_contradicting(self, *, request: ChildAbortRequestDAO, run_id: str) -> None:
        """Settle an addressable but contradictory request as unavailable, once.

        Args:
            request (ChildAbortRequestDAO): Request whose payload contradicts its directory.
            run_id (str): Run UUID of the directory holding it.
        """
        if self._load_receipt_sync(request=request, run_id=run_id) is not None:
            return
        log_warning(msg="child_control_request_refused")
        self._write_receipt_sync(
            request=request,
            run_id=run_id,
            outcome=ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable"),
        )

    # ── receipts ─────────────────────────────────────────────────────────────

    async def write_receipt(self, *, request: ChildAbortRequestDAO, outcome: ChildAbortOutcomeDAO) -> None:
        """Atomically persist the settled outcome of one request.

        WHO: ChildAbortController after a pool operation settles, retried on later ticks.
        WHEN: Once per admitted request; a failure is retried as a write only.

        Args:
            request (ChildAbortRequestDAO): Admitted request.
            outcome (ChildAbortOutcomeDAO): Pool truth or fixed refusal for that request.

        Raises:
            ValueError: The outcome names another request, child or incarnation.
            OSError: The receipt write failed.
        """
        self._require_matching_outcome(request=request, outcome=outcome)
        await asyncio.to_thread(
            self._write_receipt_sync, request=request, run_id=request.run_id, outcome=outcome
        )

    def _write_receipt_sync(
        self, *, request: ChildAbortRequestDAO, run_id: str, outcome: ChildAbortOutcomeDAO
    ) -> None:
        """Write one receipt below the run's held receipts directory.

        Args:
            request (ChildAbortRequestDAO): Request the receipt settles.
            run_id (str): Run UUID of the directory holding the request.
            outcome (ChildAbortOutcomeDAO): Validated outcome.
        """
        with _HeldDirectory.open_created(
            root=self._history_root, directory=self._receipts_dir(run_id=run_id)
        ) as held:
            held.write_model(name=f"{request.request_id}.json", model=outcome)

    async def load_receipt(self, *, request: ChildAbortRequestDAO) -> Optional[ChildAbortOutcomeDAO]:
        """Read the receipt of one request without creating anything.

        WHAT: A receipt naming another child or incarnation, or a corrupt one,
            loads as ``unavailable`` for this request; it never settles the
            wrong child as aborted.
        WHO: ChildAbortController before admitting; the TUI service on refresh.
        WHEN: On every poll tick / observation refresh while a request is pending.

        Args:
            request (ChildAbortRequestDAO): Request whose receipt to read.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Settled outcome, or None while pending.

        Raises:
            OSError: Genuine I/O failure other than absence.
        """
        return await asyncio.to_thread(self._load_receipt_sync, request=request, run_id=request.run_id)

    def _load_receipt_sync(
        self, *, request: ChildAbortRequestDAO, run_id: str
    ) -> Optional[ChildAbortOutcomeDAO]:
        """Read and validate one receipt synchronously.

        Args:
            request (ChildAbortRequestDAO): Request whose receipt to read.
            run_id (str): Run UUID of the directory holding the request.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Validated receipt, unavailable on
                mismatch/corruption, or None when absent.
        """
        held: Optional[_HeldDirectory] = _HeldDirectory.open_existing(
            root=self._history_root, directory=self._receipts_dir(run_id=run_id)
        )
        if held is None:
            return None
        with held:
            return self._decode_receipt(receipts_dir=held, request=request)

    def _decode_receipt(
        self, *, receipts_dir: _HeldDirectory, request: ChildAbortRequestDAO
    ) -> Optional[ChildAbortOutcomeDAO]:
        """Decode one receipt and bind it to the exact request.

        Args:
            receipts_dir (_HeldDirectory): Held receipts directory.
            request (ChildAbortRequestDAO): Request the receipt must settle.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Receipt, unavailable on mismatch/corruption, or None.
        """
        try:
            data: Optional[bytes] = receipts_dir.read_bounded(name=f"{request.request_id}.json")
            receipt: Optional[ChildAbortOutcomeDAO] = (
                None if data is None else ChildAbortOutcomeDAO.model_validate_json(data)
            )
            if receipt is not None:
                self._require_matching_outcome(request=request, outcome=receipt)
        except ValueError:
            log_warning(msg="child_control_receipt_invalid")
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable")
        return receipt

    @staticmethod
    def _require_matching_outcome(*, request: ChildAbortRequestDAO, outcome: ChildAbortOutcomeDAO) -> None:
        """Require an outcome to name exactly the request, child and incarnation.

        Args:
            request (ChildAbortRequestDAO): Request being settled.
            outcome (ChildAbortOutcomeDAO): Candidate outcome.

        Raises:
            ValueError: Any of request_id, session_id or execution_id differs.
        """
        expected: tuple[str, str, str] = (request.request_id, request.session_id, request.execution_id)
        if (outcome.request_id, outcome.session_id, outcome.execution_id) != expected:
            raise ValueError("child control receipt names another request")

    # ── paths ────────────────────────────────────────────────────────────────

    def _requests_dir(self, *, run_id: str) -> Path:
        """Return the run's requests directory from the layout owner.

        Args:
            run_id (str): Canonical run UUID.

        Returns:
            Path: ``child-control.v1/<run_id>/requests``.
        """
        return OrchestrationLayout.child_abort_requests_dir(
            history_root=self._history_root,
            orchestrator_session_id=self._orchestrator_session_id,
            run_id=run_id,
        )

    def _control_dir(self) -> Path:
        """Return this parent's ``child-control.v1`` directory from the layout owner."""
        return OrchestrationLayout.child_control_dir(
            history_root=self._history_root, orchestrator_session_id=self._orchestrator_session_id
        )

    def _receipts_dir(self, *, run_id: str) -> Path:
        """Return the run's receipts directory from the layout owner.

        Args:
            run_id (str): Canonical run UUID.

        Returns:
            Path: ``child-control.v1/<run_id>/receipts``.
        """
        return OrchestrationLayout.child_abort_receipts_dir(
            history_root=self._history_root,
            orchestrator_session_id=self._orchestrator_session_id,
            run_id=run_id,
        )

    def _capability_name(self) -> str:
        """Return the capability file name chosen by the layout owner."""
        return OrchestrationLayout.child_control_capability_path(
            history_root=self._history_root, orchestrator_session_id=self._orchestrator_session_id
        ).name


def _request_ids(*, names: list[str]) -> list[str]:
    """Return canonical request UUIDs named ``<uuid>.json``; other names are ignored.

    Args:
        names (list[str]): Directory entry names from a bounded scan.

    Returns:
        list[str]: Sorted request IDs.
    """
    return sorted(
        stem for stem, suffix in map(os.path.splitext, names) if suffix == ".json" and _is_uuid(value=stem)
    )


def _is_uuid(*, value: str) -> bool:
    """Report whether ``value`` is a canonical request UUID.

    Args:
        value (str): Candidate file stem.

    Returns:
        bool: True for a canonical UUID string.
    """
    try:
        canonical_uuid(value=value)
    except ValueError:
        return False
    return True


class ChildAbortGateway(Protocol):
    """Consumer-owned view of the execution owner; ``SubAgentPool`` satisfies it."""

    async def abort_child(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Stop one owned child and return the observed outcome.

        Args:
            request (ChildAbortRequestDAO): Exact current-run child identity.

        Returns:
            ChildAbortOutcomeDAO: Observed terminal or refusal outcome.
        """
        ...


class ChildControlPollClock(Protocol):
    """Paces the controller's poll loop; tests inject a manual clock."""

    async def wait_next_tick(self, *, stop: asyncio.Event) -> None:
        """Return when the next poll tick is due or ``stop`` is set.

        Args:
            stop (asyncio.Event): Set by close; must end the wait promptly.
        """
        ...


class IntervalPollClock:
    """Default clock: one tick every ``POLL_INTERVAL_SECONDS``, independent of dispatch awaits."""

    async def wait_next_tick(self, *, stop: asyncio.Event) -> None:
        """Wait one poll interval, returning early when close sets ``stop``.

        Args:
            stop (asyncio.Event): Controller stop event.
        """
        try:
            await asyncio.wait_for(fut=stop.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


class ChildAbortController:
    """Consume this runner's child-abort requests and persist outcomes until shutdown.

    A lifecycle controller, not an HTTP controller or application service: it
    owns admission and receipt persistence while the injected pool owns
    cancellation. HeadlessRunner constructs it after the pool is attached,
    awaits ``start`` before streaming, and awaits ``close`` in its ``finally``
    before the final fleet drain. Task maps are bounded by the store's
    per-run request capacity.

    Attributes:
        _pool (ChildAbortGateway): Sole execution owner for this run.
        _store (ChildAbortStore): Same-root private control adapter.
        _capability (ChildControlCapabilityDAO): Immutable run and owner identity.
        _clock (ChildControlPollClock): Poll pacing seam.
        _stop (asyncio.Event): Set once close begins; ends admission and polling.
        _poller (Optional[asyncio.Task[None]]): The single poll loop, once started.
        _closing (Optional[asyncio.Task[None]]): The single shared shutdown task.
        _operations (dict[str, asyncio.Task[ChildAbortOutcomeDAO]]): Admitted
            request operations by request ID; retained so repeats join, not rerun.
        _requests (dict[str, ChildAbortRequestDAO]): Admitted requests by ID.
        _persisted (set[str]): Request IDs whose receipt is durably written.
    """

    def __init__(
        self,
        *,
        pool: ChildAbortGateway,
        store: ChildAbortStore,
        capability: ChildControlCapabilityDAO,
        clock: Optional[ChildControlPollClock] = None,
    ) -> None:
        """Bind runner-owned collaborators; no work starts until ``start``.

        Args:
            pool (ChildAbortGateway): Sole execution owner for this run.
            store (ChildAbortStore): Same-root private control adapter.
            capability (ChildControlCapabilityDAO): Accepting capability built at
                the runner composition root.
            clock (Optional[ChildControlPollClock], optional): Poll pacing seam.
                Defaults to IntervalPollClock.
        """
        self._pool: ChildAbortGateway = pool
        self._store: ChildAbortStore = store
        self._capability: ChildControlCapabilityDAO = capability
        self._clock: ChildControlPollClock = clock if clock is not None else IntervalPollClock()
        self._stop: asyncio.Event = asyncio.Event()
        self._poller: Optional[asyncio.Task[None]] = None
        self._closing: Optional[asyncio.Task[None]] = None
        self._operations: dict[str, asyncio.Task[ChildAbortOutcomeDAO]] = {}
        self._requests: dict[str, ChildAbortRequestDAO] = {}
        self._persisted: set[str] = set()

    async def start(self) -> None:
        """Publish readiness, then start the single poll loop.

        WHO: HeadlessRunner after the pool is attached, before streaming.
        WHEN: Once; repeated starts and starts after close are no-ops.

        Raises:
            OSError: Capability publication failed; no poller is started.
            ValueError: The capability names another parent than the store.
        """
        if self._poller is not None or self._stop.is_set():
            return
        await self._store.write_capability(capability=self._capability)
        self._poller = asyncio.create_task(self._poll())

    async def _poll(self) -> None:
        """Consume disk requests once per tick until close stops admission.

        LIFETIME: Created by ``start``; exits when ``_stop`` is set; awaited by ``_close``.
        """
        while not self._stop.is_set():
            await self._tick()
            await self._clock.wait_next_tick(stop=self._stop)

    async def _tick(self) -> None:
        """Run one scan/admission pass and retry pending receipt writes."""
        try:
            requests: list[ChildAbortRequestDAO] = await self._store.read_pending(
                run_id=self._capability.run_id
            )
            await self._admit_requests(requests=requests)
        except (OSError, ValueError):
            self._diagnose(reason="child_control_read_failed")
        await self._persist_completed()

    async def _admit_requests(self, *, requests: list[ChildAbortRequestDAO]) -> None:
        """Admit each request once; never wait for a reap inside the scan.

        Args:
            requests (list[ChildAbortRequestDAO]): Bounded validated current-run requests.
        """
        for request in requests:
            if self._stop.is_set():
                return
            await self._admit_request(request=request)

    async def _admit_request(self, *, request: ChildAbortRequestDAO) -> None:
        """Skip settled or in-flight requests; otherwise track one pool operation.

        Args:
            request (ChildAbortRequestDAO): Immutable request from this run directory.
        """
        if request.request_id in self._operations:
            return
        receipt: Optional[ChildAbortOutcomeDAO] = await self._store.load_receipt(request=request)
        if receipt is not None or self._stop.is_set():
            return
        self._requests[request.request_id] = request
        self._operations[request.request_id] = asyncio.create_task(self._execute_request(request=request))

    async def _execute_request(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Hand one admitted request to the pool, translating unexpected failures.

        Args:
            request (ChildAbortRequestDAO): Admitted request; the pool rechecks authority.

        Returns:
            ChildAbortOutcomeDAO: Pool truth, or a fixed ``unresolved`` outcome.
        """
        try:
            return await self._pool.abort_child(request=request)
        except Exception:
            self._diagnose(reason="child_control_operation_unresolved")
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unresolved")

    async def _persist_completed(self) -> None:
        """Write receipts for settled operations not yet persisted (write-only retry)."""
        for request_id, operation in tuple(self._operations.items()):
            if operation.done() and request_id not in self._persisted:
                await self._persist_one(request_id=request_id, operation=operation)

    async def _persist_one(self, *, request_id: str, operation: asyncio.Task[ChildAbortOutcomeDAO]) -> None:
        """Retrieve one settled operation and write its receipt, keeping it on failure.

        Args:
            request_id (str): Key of the immutable admitted request.
            operation (asyncio.Task[ChildAbortOutcomeDAO]): Completed controller-owned task.
        """
        if operation.cancelled():
            self._diagnose(reason="child_control_operation_cancelled")
            self._persisted.add(request_id)
            return
        outcome: ChildAbortOutcomeDAO = operation.result()
        try:
            await self._store.write_receipt(request=self._requests[request_id], outcome=outcome)
        except (OSError, ValueError):
            self._diagnose(reason="child_control_receipt_write_failed")
            return
        self._persisted.add(request_id)

    async def close(self) -> None:
        """Join the single shutdown even if this caller is cancelled while waiting.

        WHO: HeadlessRunner's ``finally`` on success, error and cancellation.
        WHEN: Before the runner's final fleet drain; repeated calls join one task.

        Raises:
            asyncio.CancelledError: This caller was cancelled; shutdown continues.
        """
        if self._closing is None:
            self._stop.set()
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        """Withdraw capability, stop polling, join operations, flush receipts."""
        await self._withdraw_capability()
        if self._poller is not None:
            await asyncio.gather(self._poller, return_exceptions=True)
        await asyncio.gather(*self._operations.values(), return_exceptions=True)
        await self._persist_completed()

    async def _withdraw_capability(self) -> None:
        """Publish ``accepting=False`` without letting a write failure skip joins."""
        try:
            await self._store.write_capability(
                capability=self._capability.model_copy(update={"accepting": False})
            )
        except (OSError, ValueError):
            self._diagnose(reason="child_control_capability_close_failed")

    @staticmethod
    def _diagnose(*, reason: str) -> None:
        """Log a fixed protocol reason at a controller failure boundary.

        Args:
            reason (str): Developer-owned constant, never request or exception text.
        """
        log_warning(msg=reason)
