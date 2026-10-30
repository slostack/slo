"""Private immutable restore revisions; never a history owner or latest pointer."""

from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import re
import os
import threading
from uuid import uuid4

from ..history.atomic_io import AtomicFileWriter

from ..sessions.identity import is_canonical_uuid_session_id

from .dao import (
    HerdrRestoreConfigDAO,
    HerdrRestoreRecordDAO,
    HerdrRestoreReferenceDAO,
    HerdrRestoreUnavailableError,
    RESTORE_UNAVAILABLE_MESSAGE,
)
from .sequence_store import HerdrFileLease, HerdrSequenceUnavailableError

__all__ = ["HerdrRestoreStore", "HerdrRestoreUnavailableError", "RESTORE_UNAVAILABLE_MESSAGE"]


class HerdrRestoreStore:
    """Own private immutable configuration records under a distinct nonblocking lease."""

    def __init__(self, *, state_root: Path) -> None:
        """Bind an inert store; save/load/close belong off the event loop.

        Args:
            state_root (Path): Absolute private integration root. Save may create
                integration directories beneath a verified existing private parent;
                load never initializes storage.
        """
        self._root = state_root / "restore-v1"
        self._lock_path = state_root / "restore-v1.lock"
        self._lease = HerdrFileLease()
        self._operation_lock = threading.Lock()

    @contextmanager
    def _exclusive_operation(self) -> Iterator[None]:
        """Refuse overlapping operations/cleanup without waiting on another thread."""
        if not self._operation_lock.acquire(blocking=False):
            raise HerdrRestoreUnavailableError()
        try:
            yield
        finally:
            self._operation_lock.release()

    @contextmanager
    def _locked_store(self, *, create: bool = False) -> Iterator[HerdrFileLease]:
        """Serialize the retained lease owner across operation and cleanup threads."""
        with self._exclusive_operation():
            with self._acquired_store(create=create) as lease:
                yield lease

    @contextmanager
    def _acquired_store(self, *, create: bool) -> Iterator[HerdrFileLease]:
        """Validate private directories and release the operation lease on every exit."""
        if self.retains_external_resources:
            raise HerdrRestoreUnavailableError()
        lease = self._lease
        try:
            if create:
                self._prepare_directories()
            HerdrFileLease.validate(path=self._root.parent, directory=True)
            HerdrFileLease.validate(path=self._root, directory=True)
            lease.acquire(path=self._lock_path, create=create)
            lease.require_held(path=self._lock_path)
            yield lease
        except (OSError, ValueError, HerdrSequenceUnavailableError):
            raise HerdrRestoreUnavailableError() from None
        finally:
            try:
                lease.close()
            except (OSError, HerdrSequenceUnavailableError):
                raise HerdrRestoreUnavailableError() from None

    @property
    def retains_external_resources(self) -> bool:
        """Expose unresolved operation ownership to the reporter's final drain."""
        return self._lease.retains_external_resources

    def close(self) -> None:
        """Reconcile a retained operation lease after all store operations have joined.

        The reporter calls this off-loop during final cleanup. Callers must serialize
        save/load/close. An ambiguous descriptor is inspected, never closed again;
        failed operations remain failed even if subsequent inspection proves release.

        Raises:
            HerdrRestoreUnavailableError: Another operation is active, original
                ownership is unresolved, or descriptor cleanup/inspection fails.
        """
        with self._exclusive_operation():
            try:
                self._lease.close()
            except (OSError, HerdrSequenceUnavailableError):
                raise HerdrRestoreUnavailableError() from None

    def _prepare_directories(self) -> None:
        """Create only owned integration directories beneath an existing private parent."""
        for path in (self._root.parent, self._root):
            if not path.exists():
                HerdrFileLease.validate(path=path.parent, directory=True)
                path.mkdir(mode=0o700, exist_ok=True)
            HerdrFileLease.validate(path=path, directory=True)

    def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
        """Commit a fresh private revision, returning only confirmed durable identity.

        Called off-loop by the reporter after capture. Uses a nonblocking operation
        lease; overlapping calls or retained cleanup ownership refuse. Records are
        immutable: no overwrite, eviction, latest pointer or history mutation.
        A failure may leave an unadvertised durable orphan; callers must not adopt it.

        Args:
            config (HerdrRestoreConfigDAO): Exact private policy, revalidated and copied.

        Returns:
            HerdrRestoreReferenceDAO: New opaque reference after durable commit and
                successful operation cleanup, never a private path.

        Raises:
            HerdrRestoreUnavailableError: Policy, storage, quota, durability or
                operation cleanup is unsafe; retain this store for explicit close.
        """
        with self._locked_store(create=True) as lease:
            # Invalid copied nested values must reach validation without warning output.
            copied = HerdrRestoreConfigDAO.model_validate(config.model_dump(warnings=False))
            if not is_canonical_uuid_session_id(value=copied.session_id):
                raise HerdrRestoreUnavailableError()
            record = self._allocate_record(config=copied)
            text = record.model_dump_json()
            self._require_capacity(record_bytes=len(text.encode(encoding="utf-8")))
            lease.require_held(path=self._lock_path)
            HerdrFileLease.validate(path=self._root, directory=True)
            self._commit_new_record(record=record, text=text)
        return HerdrRestoreReferenceDAO(restore_reference=record.restore_reference)

    def _allocate_record(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreRecordDAO:
        """Try three independent random names without adopting any existing entry."""
        for _ in range(3):
            reference = f"r1-{uuid4().hex}"
            path = self._root / f"{reference}.json"
            if not path.exists() and not path.is_symlink():
                return HerdrRestoreRecordDAO(
                    schema_version=1, restore_reference=reference, config=config.model_copy(deep=True)
                )
        raise HerdrRestoreUnavailableError()

    def _require_capacity(self, *, record_bytes: int) -> None:
        """Bound every entry, including corrupt/orphan data, without eviction."""
        if record_bytes > 65536:
            raise HerdrRestoreUnavailableError()
        count, total = 0, record_bytes
        with os.scandir(self._root) as entries:
            for entry in entries:
                count += 1
                if count > 1024:
                    raise HerdrRestoreUnavailableError()
                info = HerdrFileLease.validate(path=Path(entry.path))
                total += info.st_size
        if count + 1 > 1024 or total > 67108864:
            raise HerdrRestoreUnavailableError()

    def _commit_new_record(self, *, record: HerdrRestoreRecordDAO, text: str) -> None:
        """Never invoke the unchanged writer on an existing reference."""
        path = self._root / f"{record.restore_reference}.json"
        if path.exists() or path.is_symlink():
            raise HerdrRestoreUnavailableError()
        outcome = AtomicFileWriter.write_text_with_outcome(path=path, text=text, private=True)
        if not outcome.committed or outcome.durability_warning:
            raise HerdrRestoreUnavailableError()

    @staticmethod
    def _validate_reference(*, restore_reference: str) -> None:
        """Refuse noncanonical references before constructing any record pathname."""
        if re.fullmatch(pattern=r"r1-[0-9a-f]{32}", string=restore_reference) is None:
            raise HerdrRestoreUnavailableError()

    def load(self, *, restore_reference: str, session_id: str) -> HerdrRestoreConfigDAO:
        """Load an exact private revision or refuse without initializing storage.

        CLI admission calls this before runtime construction. This read-only path
        creates no directory/record/lock file and never repairs missing state.
        It takes the existing nonblocking operation lease and does not read history.

        Args:
            restore_reference (str): Exact canonical r1 revision identifier.
            session_id (str): Canonical UUID that must match the saved policy.

        Returns:
            HerdrRestoreConfigDAO: Independent frozen saved policy, not a historical
                conversation checkpoint or permission to bypass current admission.

        Raises:
            HerdrRestoreUnavailableError: Invalid identity, unsafe/missing record,
                contention, retained ownership or cleanup failure. Retain the store
                until explicit close can establish local release.
        """
        self._validate_reference(restore_reference=restore_reference)
        with self._locked_store():
            record = self._read_record(restore_reference=restore_reference)
            return self._require_identity(record=record, session_id=session_id)

    def _read_record(self, *, restore_reference: str) -> HerdrRestoreRecordDAO:
        """Read at most one bounded private regular file through its verified descriptor."""
        path = self._root / f"{restore_reference}.json"
        before = HerdrFileLease.validate(path=path)
        if not hasattr(os, "O_NOFOLLOW"):
            raise HerdrRestoreUnavailableError()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            after = os.fstat(fd)
            if before != after:
                raise HerdrRestoreUnavailableError()
            content = self._read_bounded(fd=fd)
            if len(content) > 65536:
                raise HerdrRestoreUnavailableError()
            record = HerdrRestoreRecordDAO.model_validate_json(content)
            if record.restore_reference != restore_reference:
                raise HerdrRestoreUnavailableError()
            return record
        finally:
            os.close(fd)

    @staticmethod
    def _read_bounded(*, fd: int) -> bytes:
        """Accumulate short reads through EOF or the single overflow sentinel byte."""
        content = bytearray()
        while len(content) < 65537:
            chunk = os.read(fd, 65537 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        return bytes(content)

    @staticmethod
    def _require_identity(*, record: HerdrRestoreRecordDAO, session_id: str) -> HerdrRestoreConfigDAO:
        """Bind an exact revision to canonical history identity without name resolution."""
        if not is_canonical_uuid_session_id(value=session_id):
            raise HerdrRestoreUnavailableError()
        if not is_canonical_uuid_session_id(value=record.config.session_id):
            raise HerdrRestoreUnavailableError()
        if record.config.session_id != session_id:
            raise HerdrRestoreUnavailableError()
        return record.config.model_copy(deep=True)
