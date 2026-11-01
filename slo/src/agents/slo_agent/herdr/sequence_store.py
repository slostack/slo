"""Private advisory leases and durable pane-scoped sequence reservations."""

import errno
import os
import stat
from pathlib import Path
from typing import Literal, Optional, Protocol, cast
import importlib

from .dao import HerdrSequenceStateDAO
from ..history.atomic_io import AtomicFileWriter

_PLATFORM = os.name

if os.name == "posix":
    import fcntl


class _WindowsByteLock(Protocol):
    """Typed native adapter available only on Windows at runtime."""

    LK_NBLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None:
        """Acquire a nonblocking byte range on the supplied descriptor."""
        ...


class HerdrSequenceUnavailableError(RuntimeError):
    """Refuse unsafe local state without exposing paths or input values."""

    def __init__(self) -> None:
        """Create the fixed adapter failure boundary."""
        super().__init__("Herdr sequence unavailable.")


class HerdrFileLease:
    """Own one nonblocking lock fd; pane and restore owners supply distinct paths."""

    def __init__(self) -> None:
        """Construct inert ownership; acquisition belongs off the event loop."""
        self._fd: Optional[int] = None
        self._close_ambiguous = False
        self._identity: Optional[tuple[int, int]] = None

    @staticmethod
    def validate(*, path: Path, directory: bool = False) -> os.stat_result:
        """Inspect existing private state without creating or repairing it.

        Args:
            path (Path): Absolute, link-free path owned by the current user.
            directory (bool): Require mode 0700 directory rather than mode 0600
                singly linked regular file. Defaults to False.

        Returns:
            os.stat_result: Validated lstat evidence, not an open-handle guarantee.

        Raises:
            HerdrSequenceUnavailableError: Unsafe path, ownership, mode or kind.
            OSError: Filesystem inspection failed.
        """
        if not path.is_absolute() or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
            raise HerdrSequenceUnavailableError()
        info = path.lstat()
        expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (
            not expected
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        ):
            raise HerdrSequenceUnavailableError()
        if not directory and info.st_nlink != 1:
            raise HerdrSequenceUnavailableError()
        return info

    def acquire(self, *, path: Path, create: bool) -> None:
        """Acquire a private lock off-loop without waiting or stealing ownership.

        Callers serialize use and retain this owner after any cleanup failure.
        No external code may duplicate, close or replace its descriptor.

        Args:
            path (Path): Absolute private lock path under an existing private parent.
            create (bool): Permit creation of an absent lock file; never overwrite.

        Raises:
            HerdrSequenceUnavailableError: Already owned, contended or unsafe state.
            OSError: Acquisition rollback could not close its descriptor; retain
                the owner for inspection-only reconciliation.
        """
        if self._fd is not None:
            raise HerdrSequenceUnavailableError()
        self._close_ambiguous = False
        self._identity = None
        try:
            self.validate(path=path.parent, directory=True)
            if create and not path.exists():
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    os.write(fd, b"\0")
                finally:
                    os.close(fd)
            before = self.validate(path=path)
            self._fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            after = os.fstat(self._fd)
            self._identity = (after.st_dev, after.st_ino)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise HerdrSequenceUnavailableError()
            self._lock(fd=self._fd)
        except (OSError, HerdrSequenceUnavailableError):
            self.close()
            raise HerdrSequenceUnavailableError() from None

    @staticmethod
    def _lock(*, fd: int) -> None:
        """Use the native nonblocking primitive; unsupported platforms refuse."""
        if _PLATFORM == "posix":
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        if _PLATFORM == "nt":
            msvcrt = cast(_WindowsByteLock, importlib.import_module("msvcrt"))

            if os.fstat(fd).st_size != 1:
                raise HerdrSequenceUnavailableError()
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        raise HerdrSequenceUnavailableError()

    def require_held(self, *, path: Path) -> None:
        """Refuse pathname substitution without releasing the original handle.

        Args:
            path (Path): Previously acquired private lock path.

        Raises:
            HerdrSequenceUnavailableError: No handle or substituted/unsafe path.
            OSError: Path or descriptor inspection failed.
        """
        if self._fd is None:
            raise HerdrSequenceUnavailableError()
        self.validate(path=path.parent, directory=True)
        current = self.validate(path=path)
        held = os.fstat(self._fd)
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise HerdrSequenceUnavailableError()

    @property
    def retains_external_resources(self) -> bool:
        """Report unresolved ownership without inspecting or acting on the descriptor."""
        return self._fd is not None

    def close(self) -> None:
        """Release this exclusively owned handle without retrying an ambiguous close.

        Callers serialize acquisition/use/close and retain this owner after failure.
        A failed close can have released its descriptor on POSIX. Later calls only
        inspect that slot: EBADF or a different inode proves the original is gone;
        matching identity does NOT prove descriptor generation and never allows a
        retry. Inspection failure or same-inode reuse remains conservatively held.
        No external code may close, duplicate or replace this owner's descriptor.
        Persistent lock/counter files are never removed.

        Raises:
            OSError: Initial close or inspection failed; retain this owner.
            HerdrSequenceUnavailableError: Original ownership remains ambiguous.
        """
        if self._fd is None:
            return
        if self._close_ambiguous:
            self._reconcile_close()
            return
        self._close_ambiguous = True
        os.close(self._fd)
        self._fd = None

    def _reconcile_close(self) -> None:
        """Clear only demonstrated absence; never operate on a possibly recycled fd."""
        assert self._fd is not None
        try:
            current = os.fstat(self._fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
            self._fd = None
            return
        if self._identity is not None and (current.st_dev, current.st_ino) != self._identity:
            self._fd = None
            return
        raise HerdrSequenceUnavailableError()


class HerdrSequenceStore:
    """Reserve independent source counters under one lifetime pane lease."""

    def __init__(self, *, state_root: Path, socket_namespace: str, pane_id: str) -> None:
        """Capture a pane namespace without I/O; session identity is intentionally absent.

        Args:
            state_root (Path): Absolute private integration root, validated on acquire.
            socket_namespace (str): Captured socket namespace hashed into storage identity.
            pane_id (str): Captured pane identity shared across session replacement.
        """
        import hashlib
        import json

        digest = hashlib.sha256(
            json.dumps([socket_namespace, pane_id, "custom:slo"], ensure_ascii=True).encode()
        ).hexdigest()
        self._root = state_root
        self._path = state_root / "sequence-v1" / f"{digest}.json"
        self._lease = HerdrFileLease()
        self._state: Optional[HerdrSequenceStateDAO] = None

    def acquire(self) -> None:
        """Acquire the lifetime pane lease and load counters off-loop.

        Creates private state directories only beneath a verified private parent.
        Missing counters start at zero; corrupt bytes are never reset or repaired.
        Callers serialize acquisition/reservation/close and retain failed cleanup.

        Raises:
            HerdrSequenceUnavailableError: Contention, unsafe or invalid state.
            OSError: Rollback close failed; this owner must remain reachable.
        """
        if self._state is not None:
            raise HerdrSequenceUnavailableError()
        try:
            if not self._root.exists():
                HerdrFileLease.validate(path=self._root.parent, directory=True)
                self._root.mkdir(mode=0o700)
            HerdrFileLease.validate(path=self._root, directory=True)
            self._path.parent.mkdir(mode=0o700, exist_ok=True)
            self._lease.acquire(path=self._path.with_suffix(".lock"), create=True)
            self._state = self._load()
        except (OSError, ValueError, HerdrSequenceUnavailableError):
            self.close()
            raise HerdrSequenceUnavailableError() from None

    @property
    def retains_external_resources(self) -> bool:
        """Report unresolved pane ownership, including failed acquisition rollback.

        Reporter disposal reads this after acquisition/cleanup joins. This pure
        predicate grants no reservation or admission authority and performs no I/O.
        """
        return self._lease.retains_external_resources

    def _load(self) -> HerdrSequenceStateDAO:
        """Missing state begins at zero; invalid existing bytes never reset."""
        if not self._path.exists() and not self._path.is_symlink():
            return HerdrSequenceStateDAO(schema_version=1, lifecycle_sequence=0, display_sequence=0)
        state = HerdrSequenceStateDAO.model_validate_json(self._read_state())
        self._validate_bounds(state=state)
        return state

    def _read_state(self) -> bytes:
        """Read a bounded no-follow descriptor after matching the validated inode."""
        before = HerdrFileLease.validate(path=self._path)
        fd = os.open(self._path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise HerdrSequenceUnavailableError()
            content = bytearray()
            while len(content) < 4097:
                chunk = os.read(fd, 4097 - len(content))
                if not chunk:
                    break
                content.extend(chunk)
            if len(content) > 4096:
                raise HerdrSequenceUnavailableError()
            return bytes(content)
        finally:
            os.close(fd)

    @staticmethod
    def _validate_bounds(*, state: HerdrSequenceStateDAO) -> None:
        """Keep persisted and newly reserved counters within the wire integer range."""
        if max(state.lifecycle_sequence, state.display_sequence) > 2**63 - 1:
            raise HerdrSequenceUnavailableError()

    def reserve(self, *, source: Literal["custom:slo", "custom:slo-display"]) -> int:
        """Reserve durably under the acquired lifetime lease before a command can send.

        Rechecks complete bounded counter bytes and path ownership. Failure disables
        further reservations until acquisition; a committed but unreturned number
        is a legal gap, never permission to send or reset state.

        Args:
            source (Literal["custom:slo", "custom:slo-display"]): Independent
                lifecycle or display counter namespace.

        Returns:
            int: Newly persisted positive signed-64-bit sequence number.

        Raises:
            HerdrSequenceUnavailableError: Missing lease, changed/corrupt counter,
                overflow, invalid source or unconfirmed durability.
        """
        try:
            if self._state is None:
                raise HerdrSequenceUnavailableError()
            self._lease.require_held(path=self._path.with_suffix(".lock"))
            HerdrFileLease.validate(path=self._root, directory=True)
            if self._load() != self._state:
                raise HerdrSequenceUnavailableError()
            field = {"custom:slo": "lifecycle_sequence", "custom:slo-display": "display_sequence"}[source]
            number = int(getattr(self._state, field)) + 1
            candidate = HerdrSequenceStateDAO.model_validate({**self._state.model_dump(), field: number})
            self._validate_bounds(state=candidate)
            outcome = AtomicFileWriter.write_text_with_outcome(
                path=self._path, text=candidate.model_dump_json()
            )
            if not outcome.committed or outcome.durability_warning:
                raise HerdrSequenceUnavailableError()
            self._state = candidate
            return number
        except (OSError, ValueError, KeyError, HerdrSequenceUnavailableError):
            self._state = None
            raise HerdrSequenceUnavailableError() from None

    def close(self) -> None:
        """Release the pane lease after reservations and transport have drained.

        Caller must serialize use and preserve this owner on failure. Durable
        counter/lock files remain. Ambiguous close is never retried on its raw fd.

        Raises:
            OSError: Initial close or later inspection failed.
            HerdrSequenceUnavailableError: Original handle remains unresolved.
        """
        self._state = None
        self._lease.close()
