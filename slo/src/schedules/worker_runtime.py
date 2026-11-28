"""Shared schedule worker runtime — one detached worker per schedules directory (OPS111).

Creating or enabling a schedule must leave scheduling operational without a
second terminal. This module is the one owner of how that happens: it starts
or reuses one detached ``slo schedule worker`` per canonical schedules
directory, proves it healthy through a live challenge, and lets the worker
hold its ownership for its whole life. Callers see only typed health results.

Mechanics, all private to this module and all inside the schedules directory:

- **Lifetime lock** (``.schedule-worker.lock``): the worker holds an exclusive
  ``flock`` on it from before engine admission until exit. Every worker —
  detached or a manual foreground one — takes it, so two can never run on one
  directory. The file is never unlinked, so its inode stays stable.
- **Launch lock** (``.schedule-worker-launch.lock``): serializes every
  start-or-reuse and stale cleanup across processes.
- **Metadata** (``.schedule-worker.json``): written atomically by the worker
  once its control channel listens; binds a unique launch id to the store.
- **Control socket** (``.schedule-worker.sock``): a private Unix socket. A
  health check sends a fresh random challenge; the worker's event loop answers
  with the challenge, its launch id, its store paths and engine readiness. A
  lock, a PID, a file or a bare connect never counts as healthy.

The PID is diagnostic only: nothing is ever signalled by PID. Only a child this
runtime itself launched and still holds unreaped is ever terminated.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import secrets
import socket
import stat
import struct
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.schedules.dao import EngineReadinessPhase, ScheduleEngineReadinessDAO
from src.schedules.engine_admission import ScheduleEngineAdmission
from src.schedules.exceptions import ScheduleWorkerStartError
from src.schedules.fresh_run import FreshRunCommand

__all__ = [
    "HEALTH_PROBE_TIMEOUT_SECONDS",
    "LAUNCH_LOCK_TIMEOUT_SECONDS",
    "STARTUP_TIMEOUT_SECONDS",
    "ScheduleWorkerHealthDAO",
    "ScheduleWorkerLauncher",
    "ScheduleWorkerLifetime",
    "ScheduleWorkerLocationDAO",
    "ScheduleWorkerRuntime",
    "ScheduleWorkerState",
    "ScheduleWorkerUnavailableError",
    "SubprocessScheduleWorkerLauncher",
]

STARTUP_TIMEOUT_SECONDS: float = 30.0
"""Launch to healthy: the worker imports, passes admission, recovers and leads."""
LAUNCH_LOCK_TIMEOUT_SECONDS: float = 45.0
"""Longer than one startup, so a concurrent creator waits for the first launch."""
HEALTH_PROBE_TIMEOUT_SECONDS: float = 2.0
"""One connect + challenge + answer."""
UNRESPONSIVE_PROBE_ATTEMPTS: int = 3
"""Silent probes before an owned worker is reported unresponsive."""
LIFETIME_LOCK_WAIT_SECONDS: float = 2.0
"""A starting worker retries this long; a concurrent probe holds the lock only for an instant."""
REAP_GRACE_SECONDS: float = 5.0
RETIRE_TIMEOUT_SECONDS: float = 15.0
CONTROL_MESSAGE_LIMIT_BYTES: int = 4096
STORE_WATCH_INTERVAL_SECONDS: float = 2.0
LOG_LIMIT_BYTES: int = 1 << 20

_POLL_INTERVAL_SECONDS: float = 0.1
_LOCK_POLL_SECONDS: float = 0.05
_SOCKET_PATH_LIMIT_BYTES: int = 100
_FILE_MODE: int = 0o600
_DIRECTORY_MODE: int = 0o700
_CAUSE_LIMIT_CHARACTERS: int = 400

_LIFETIME_LOCK_NAME: str = ".schedule-worker.lock"
_LAUNCH_LOCK_NAME: str = ".schedule-worker-launch.lock"
_METADATA_NAME: str = ".schedule-worker.json"
_SOCKET_NAME: str = ".schedule-worker.sock"
_LOG_NAME: str = ".schedule-worker.log"

_ALREADY_RUNNING_REASON: str = (
    "a schedule worker is already running for this schedules directory; check it with `slo schedule status`"
)

_STILL_STARTING_REASON: str = "another command is still starting the schedule worker"

_SESSION_CONTROL_NAMES: frozenset[str] = frozenset(
    {"SLO_WORKFLOW_ID", "SLO_SESSION_ID", "SLO_CHANNEL_PARENT_ID", "SLO_CHANNEL_PARTICIPANT_NAME"}
)
"""Inherited identity of the creating session; the shared worker belongs to no session."""

ScheduleWorkerState = Literal["healthy", "starting", "retiring", "stopped", "unresponsive", "blocked"]

_STATE_BY_ENGINE_PHASE: dict[EngineReadinessPhase, ScheduleWorkerState] = {
    "ready": "healthy",
    "starting": "starting",
    "stalled": "unresponsive",
    "retiring": "retiring",
    "failed": "retiring",
}
"""A stalled owner still holds the directory: never replaced. A stopping or
failed engine is exiting: a start waits (bounded) for it to release, then launches."""


class ScheduleWorkerLocationDAO(BaseModel):
    """The resolved stores one shared worker serves; the schedules directory is its key."""

    model_config = ConfigDict(frozen=True)

    schedules_dir: Path = Field(
        description="Canonical absolute schedules directory; the worker's identity key."
    )
    db_path: Path = Field(description="Absolute schedules.db path inside schedules_dir.")
    channel_db_path: Path = Field(description="Absolute channels.db the worker delivers into.")
    history_root: Path = Field(description="Absolute session history root used to resolve session names.")

    @classmethod
    def from_paths(
        cls, *, db_path: Path, channel_db_path: Path, history_root: Path
    ) -> "ScheduleWorkerLocationDAO":
        """Resolve the given store paths to canonical absolute paths.

        Args:
            db_path (Path): The schedules database file.
            channel_db_path (Path): The channels database file.
            history_root (Path): The session history root.

        Returns:
            ScheduleWorkerLocationDAO: The resolved location.
        """
        resolved_db: Path = Path(os.path.abspath(db_path)).resolve()
        return cls(
            schedules_dir=resolved_db.parent,
            db_path=resolved_db,
            channel_db_path=Path(os.path.abspath(channel_db_path)).resolve(),
            history_root=Path(os.path.abspath(history_root)).resolve(),
        )

    @classmethod
    def at_default_paths(cls) -> "ScheduleWorkerLocationDAO":
        """Resolve the configured stores (``SLO_SCHEDULES_DIR`` / ``SLO_HOME``).

        Returns:
            ScheduleWorkerLocationDAO: The location every CLI command and the
                worker itself resolve from the same environment.
        """
        from src.agents.slo_agent.history.filesystem_store import default_history_root
        from src.channels.gateway import ChannelGateway
        from src.schedules.database import default_database_path

        return cls.from_paths(
            db_path=default_database_path(),
            channel_db_path=ChannelGateway.default_channels_dir() / "channels.db",
            history_root=default_history_root(),
        )

    @property
    def lifetime_lock_path(self) -> Path:
        """Return the lifetime lock file the running worker holds."""
        return self.schedules_dir / _LIFETIME_LOCK_NAME

    @property
    def launch_lock_path(self) -> Path:
        """Return the lock that serializes start-or-reuse and cleanup."""
        return self.schedules_dir / _LAUNCH_LOCK_NAME

    @property
    def metadata_path(self) -> Path:
        """Return the running worker's metadata file."""
        return self.schedules_dir / _METADATA_NAME

    @property
    def socket_path(self) -> Path:
        """Return the worker's private control socket."""
        return self.schedules_dir / _SOCKET_NAME

    @property
    def log_path(self) -> Path:
        """Return the detached worker's private, bounded diagnostics file."""
        return self.schedules_dir / _LOG_NAME


class ScheduleWorkerHealthDAO(BaseModel):
    """One bounded observation of the shared worker (OPS111-03, OPS111-07).

    ``healthy`` means a live worker answered a fresh challenge with a ready
    engine for this exact store: it leads and its ticks progress. It does not
    prove any invocation ran.
    """

    model_config = ConfigDict(frozen=True)

    state: ScheduleWorkerState = Field(
        description="healthy, starting, retiring (owner stopping), stopped (no owner), unresponsive (owner"
        " silent, or answering without scheduler leadership or tick progress) or blocked."
    )
    observed_at: datetime = Field(description="UTC instant of the observation.")
    launch_id: Optional[str] = Field(default=None, description="The worker generation's unique launch id.")
    pid: Optional[int] = Field(default=None, description="The worker process id; diagnostic only.")
    reason: Optional[str] = Field(default=None, description="Safe explanation when not healthy.")
    last_tick_at: Optional[datetime] = Field(
        default=None, description="When the worker last finished a tick pass, from its own answer."
    )

    @property
    def is_healthy(self) -> bool:
        """Return True when the worker answered with a ready engine for this store."""
        return self.state == "healthy"


class ScheduleWorkerUnavailableError(RuntimeError):
    """The shared worker could not be started or reused; carries the observation."""

    def __init__(self, *, health: ScheduleWorkerHealthDAO) -> None:
        """Record the observation that explains the failure.

        Args:
            health (ScheduleWorkerHealthDAO): The final observation.
        """
        super().__init__(health.reason or f"the schedule worker is {health.state}")
        self.health: ScheduleWorkerHealthDAO = health


class ScheduleWorkerLauncher(Protocol):
    """Starts one detached worker process for a location (the runtime's launch seam)."""

    def launch(self, *, launch_id: str, location: ScheduleWorkerLocationDAO) -> subprocess.Popen[bytes]:
        """Start the worker and return its unreaped process handle.

        Args:
            launch_id (str): The unique generation id the worker must report.
            location (ScheduleWorkerLocationDAO): The stores it serves.

        Returns:
            subprocess.Popen[bytes]: The child; the runtime reaps it if it is never adopted.
        """
        ...


class _WorkerMetadataDAO(BaseModel):
    """The running worker's metadata record."""

    model_config = ConfigDict(frozen=True)

    launch_id: str = Field(description="Unique id of this worker generation.")
    pid: int = Field(description="Worker process id; diagnostic only.")
    schedules_dir: str = Field(description="The canonical schedules directory the worker serves.")
    started_at: datetime = Field(description="UTC instant the worker began serving its control channel.")


class _ControlRequestDAO(BaseModel):
    """One control request line."""

    op: Literal["health", "retire"] = Field(
        description="health answers; retire also asks the worker to stop."
    )
    challenge: str = Field(
        min_length=16, max_length=128, description="Fresh random nonce the answer must echo."
    )
    launch_id: Optional[str] = Field(default=None, description="For retire: the generation that must stop.")


class _ControlAnswerDAO(BaseModel):
    """One control answer line, produced live by the worker's event loop."""

    challenge: str = Field(description="The request's nonce, echoed.")
    launch_id: str = Field(description="The answering worker's generation id.")
    pid: int = Field(description="The answering process id.")
    schedules_dir: str = Field(description="The schedules directory the worker serves.")
    channel_db_path: str = Field(description="The channels database the worker delivers into.")
    history_root: str = Field(description="The session history root the worker resolves names with.")
    readiness: ScheduleEngineReadinessDAO = Field(description="The engine's own readiness at answer time.")
    retiring: bool = Field(default=False, description="True when this answer accepted a retire request.")


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(tz=timezone.utc)


@contextmanager
def _control_address(*, location: ScheduleWorkerLocationDAO) -> Iterator[str]:
    """Yield a bindable/connectable address for the control socket.

    Unix socket paths are limited to about 100 bytes. A longer directory path
    is reached through this process's open directory descriptor on Linux.

    Args:
        location (ScheduleWorkerLocationDAO): The worker location.

    Yields:
        str: The address to bind or connect.

    Raises:
        OSError: When the path is too long and no descriptor alias exists.
    """
    direct: Path = location.socket_path
    if len(os.fsencode(direct)) < _SOCKET_PATH_LIMIT_BYTES:
        yield str(direct)
        return
    if not Path("/proc/self/fd").is_dir():
        raise OSError(
            errno.ENAMETOOLONG, "the schedules directory path is too long for the worker control socket"
        )
    directory_fd: int = os.open(location.schedules_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield f"/proc/self/fd/{directory_fd}/{_SOCKET_NAME}"
    finally:
        os.close(directory_fd)


def _peer_uid(*, connection: socket.socket) -> Optional[int]:
    """Return the connected peer's uid where the platform reports it.

    Args:
        connection (socket.socket): A connected Unix socket.

    Returns:
        Optional[int]: The peer uid, or None when unavailable on this platform.
    """
    peer_credentials: Optional[int] = getattr(socket, "SO_PEERCRED", None)
    if peer_credentials is None:
        return None
    raw: bytes = connection.getsockopt(socket.SOL_SOCKET, peer_credentials, struct.calcsize("3i"))
    return int(struct.unpack("3i", raw)[1])


def _same_user(*, connection: Optional[socket.socket]) -> bool:
    """Tell whether the peer runs as this user (True where it cannot be told).

    Args:
        connection (Optional[socket.socket]): The connected socket.

    Returns:
        bool: False only when the peer is provably another user.
    """
    if connection is None:
        return False
    peer: Optional[int] = _peer_uid(connection=connection)
    return peer is None or peer == os.getuid()


def _open_lock_file(*, path: Path, create: bool) -> Optional[int]:
    """Open a lock file without following symlinks.

    Args:
        path (Path): The lock file.
        create (bool): Create it (mode 0600) when missing.

    Returns:
        Optional[int]: The descriptor, or None when missing and not created.
    """
    flags: int = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_CREAT if create else 0)
    try:
        return os.open(path, flags, _FILE_MODE)
    except FileNotFoundError:
        return None


def _try_exclusive(*, descriptor: int) -> bool:
    """Take an exclusive flock without blocking.

    Args:
        descriptor (int): An open lock file descriptor.

    Returns:
        bool: True when the lock was taken.
    """
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _remove_if_kind(*, path: Path, is_kind: Callable[[int], bool]) -> None:
    """Remove a path only when it is of the expected kind (never following links).

    Args:
        path (Path): The path to remove.
        is_kind (Callable[[int], bool]): Mode predicate such as ``stat.S_ISREG``.
    """
    with suppress(FileNotFoundError):
        if is_kind(path.lstat().st_mode):
            path.unlink()


_WORKER_BOOTSTRAP: str = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from src.cli.app import main; main()"
)
"""Runs the CLI from an explicit code root under ``python -I``: cwd and PYTHON* are ignored."""


def _running_code_root() -> Path:
    """Return the directory that holds the running ``src`` package.

    Returns:
        Path: The resolved code root (a site-packages directory when installed).
    """
    return Path(__file__).resolve().parents[2]


class SubprocessScheduleWorkerLauncher:
    """Starts ``schedule worker --launch-id`` detached with the creator's own interpreter and code.

    The worker must run the very build that created the schedule, never
    whichever ``slo`` happens to be first on PATH. It is started as
    ``<this interpreter> -I -c <bootstrap> <code root> schedule worker ...``:
    import isolation ignores the cwd and every ``PYTHON*`` variable, and the
    code root is the resolved location of the running ``src`` package. The
    child gets a new session, no terminal stdin/stdout/stderr, a private
    truncated diagnostics file and the home directory (or ``/`` when that is
    missing) as its working directory.
    """

    def __init__(
        self,
        *,
        interpreter: Optional[Path] = None,
        code_root: Optional[Path] = None,
        command: Optional[FreshRunCommand] = None,
    ) -> None:
        """Bind the interpreter, the code root and the shared environment policy.

        Args:
            interpreter (Optional[Path]): The Python to run; this process's when None.
            code_root (Optional[Path]): The directory holding ``src``; the running one when None.
            command (Optional[FreshRunCommand]): The child-environment policy shared with fresh runs.
        """
        self._interpreter: Path = interpreter if interpreter is not None else Path(sys.executable).absolute()
        self._code_root: Path = code_root if code_root is not None else _running_code_root()
        self._command: FreshRunCommand = command if command is not None else FreshRunCommand()

    def launch(self, *, launch_id: str, location: ScheduleWorkerLocationDAO) -> subprocess.Popen[bytes]:
        """Start the detached worker.

        Args:
            launch_id (str): The generation id the worker must report.
            location (ScheduleWorkerLocationDAO): The stores it serves.

        Returns:
            subprocess.Popen[bytes]: The unreaped child.

        Raises:
            OSError: When the diagnostics file or the process cannot be created.
        """
        argv: list[str] = [
            str(self._interpreter),
            "-I",
            "-c",
            _WORKER_BOOTSTRAP,
            str(self._code_root),
            "schedule",
            "worker",
            "--launch-id",
            launch_id,
        ]
        log_descriptor: int = os.open(
            location.log_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
            _FILE_MODE,
        )
        try:
            return subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_descriptor,
                stderr=log_descriptor,
                cwd=self._working_directory(),
                env=self._environment(location=location),
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(log_descriptor)

    @staticmethod
    def _working_directory() -> str:
        """Return a working directory independent of the creating terminal.

        Returns:
            str: The home directory, or ``/`` when it does not exist.
        """
        home: str = os.path.expanduser("~")
        return home if os.path.isdir(home) else os.sep

    def _environment(self, *, location: ScheduleWorkerLocationDAO) -> dict[str, str]:
        """Build the worker environment: no session identity, pinned absolute stores.

        Args:
            location (ScheduleWorkerLocationDAO): The stores it serves.

        Returns:
            dict[str, str]: The child environment.
        """
        environment: dict[str, str] = {
            name: value
            for name, value in self._command.child_environment().items()
            if name not in _SESSION_CONTROL_NAMES and not name.startswith("SLO_CAPTURE_")
        }
        environment["SLO_SCHEDULES_DIR"] = str(location.schedules_dir)
        if environment.get("SLO_HOME"):
            environment["SLO_HOME"] = str(Path(os.path.abspath(environment["SLO_HOME"])).resolve())
        return environment


class ScheduleWorkerLifetime:
    """The worker side: held lifetime lock, control channel and own-generation files.

    Built only by ``ScheduleWorkerRuntime.claim_lifetime``. The worker keeps it
    for its whole life and calls ``release`` last.
    """

    def __init__(
        self, *, location: ScheduleWorkerLocationDAO, launch_id: str, lock_descriptor: int, detached: bool
    ) -> None:
        """Bind the held lock and this generation's identity.

        Args:
            location (ScheduleWorkerLocationDAO): The stores this worker serves.
            launch_id (str): This generation's unique id.
            lock_descriptor (int): The descriptor holding the lifetime flock.
            detached (bool): Started by the runtime; caps the private log.
        """
        self._location: ScheduleWorkerLocationDAO = location
        self._launch_id: str = launch_id
        self._lock_descriptor: Optional[int] = lock_descriptor
        self._lock_inode: int = os.fstat(lock_descriptor).st_ino
        self._detached: bool = detached
        self._socket_inode: Optional[int] = None

    @property
    def launch_id(self) -> str:
        """Return this generation's unique id."""
        return self._launch_id

    @asynccontextmanager
    async def serve(
        self, *, readiness: Callable[[], ScheduleEngineReadinessDAO], stop_event: asyncio.Event
    ) -> AsyncIterator[None]:
        """Answer health challenges and watch the store while the body runs.

        The control socket listens before the metadata is published, so a
        published record always has a listener. On exit the server closes and
        only this generation's metadata and socket are removed.

        Args:
            readiness (Callable[[], ScheduleEngineReadinessDAO]): The engine's live readiness.
            stop_event (asyncio.Event): Set to stop the worker (retire, lost store).

        Yields:
            None: While the worker runs.
        """
        server: asyncio.AbstractServer = await self._start_control_server(
            readiness=readiness, stop_event=stop_event
        )
        watch: asyncio.Task[None] = asyncio.create_task(self._watch_store(stop_event=stop_event))
        try:
            self._publish_metadata()
            yield
        finally:
            watch.cancel()
            with suppress(asyncio.CancelledError):
                await watch
            server.close()
            await server.wait_closed()
            self._remove_own_files()

    def release(self) -> None:
        """Release the lifetime lock; the lock file itself is never unlinked."""
        descriptor: Optional[int] = self._lock_descriptor
        self._lock_descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    async def _start_control_server(
        self, *, readiness: Callable[[], ScheduleEngineReadinessDAO], stop_event: asyncio.Event
    ) -> asyncio.AbstractServer:
        """Bind the private control socket (replacing a dead generation's) and listen.

        Args:
            readiness (Callable[[], ScheduleEngineReadinessDAO]): The engine's live readiness.
            stop_event (asyncio.Event): Set by an accepted retire request.

        Returns:
            asyncio.AbstractServer: The serving control server.
        """
        _remove_if_kind(path=self._location.socket_path, is_kind=stat.S_ISSOCK)
        listener: socket.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with _control_address(location=self._location) as address:
                listener.bind(address)
            os.chmod(self._location.socket_path, _FILE_MODE)
            self._socket_inode = self._location.socket_path.lstat().st_ino

            async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                await self._answer(reader=reader, writer=writer, readiness=readiness, stop_event=stop_event)

            return await asyncio.start_unix_server(answer, sock=listener, limit=CONTROL_MESSAGE_LIMIT_BYTES)
        except BaseException:
            listener.close()
            raise

    async def _answer(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        readiness: Callable[[], ScheduleEngineReadinessDAO],
        stop_event: asyncio.Event,
    ) -> None:
        """Answer one bounded control request from the same user.

        Args:
            reader (asyncio.StreamReader): The request stream.
            writer (asyncio.StreamWriter): The answer stream.
            readiness (Callable[[], ScheduleEngineReadinessDAO]): The engine's live readiness.
            stop_event (asyncio.Event): Set when a retire names this generation.
        """
        try:
            if not _same_user(connection=writer.get_extra_info("socket")):
                return
            line: bytes = await asyncio.wait_for(reader.readline(), timeout=HEALTH_PROBE_TIMEOUT_SECONDS)
            request: _ControlRequestDAO = _ControlRequestDAO.model_validate_json(line)
            retiring: bool = request.op == "retire" and request.launch_id == self._launch_id
            if retiring:
                stop_event.set()
            answer = _ControlAnswerDAO(
                challenge=request.challenge,
                launch_id=self._launch_id,
                pid=os.getpid(),
                schedules_dir=str(self._location.schedules_dir),
                channel_db_path=str(self._location.channel_db_path),
                history_root=str(self._location.history_root),
                readiness=readiness(),
                retiring=retiring,
            )
            writer.write(answer.model_dump_json().encode("utf-8") + b"\n")
            await writer.drain()
        except (OSError, ValueError, ValidationError, asyncio.TimeoutError):
            return
        finally:
            writer.close()

    def _publish_metadata(self) -> None:
        """Atomically publish this generation's private metadata record."""
        record = _WorkerMetadataDAO(
            launch_id=self._launch_id,
            pid=os.getpid(),
            schedules_dir=str(self._location.schedules_dir),
            started_at=_utc_now(),
        )
        staging: Path = self._location.schedules_dir / f"{_METADATA_NAME}.{self._launch_id}.tmp"
        descriptor: int = os.open(
            staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, _FILE_MODE
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(record.model_dump_json())
        os.replace(staging, self._location.metadata_path)

    def _remove_own_files(self) -> None:
        """Remove only this generation's metadata and socket."""
        metadata: Optional[_WorkerMetadataDAO] = _read_metadata(location=self._location)
        if metadata is not None and metadata.launch_id == self._launch_id:
            _remove_if_kind(path=self._location.metadata_path, is_kind=stat.S_ISREG)
        with suppress(FileNotFoundError):
            if self._location.socket_path.lstat().st_ino == self._socket_inode:
                self._location.socket_path.unlink()

    async def _watch_store(self, *, stop_event: asyncio.Event) -> None:
        """Stop the worker when its lifetime lock file is gone or replaced; cap the log.

        A removed schedules directory must not keep an orphaned worker alive.

        Args:
            stop_event (asyncio.Event): Set when the store disappears.
        """
        while not stop_event.is_set():
            await asyncio.sleep(STORE_WATCH_INTERVAL_SECONDS)
            if not self._holds_current_lock_file():
                stop_event.set()
                return
            self._cap_log()

    def _holds_current_lock_file(self) -> bool:
        """Tell whether the lock path still names the file this worker holds."""
        try:
            return self._location.lifetime_lock_path.lstat().st_ino == self._lock_inode
        except FileNotFoundError:
            return False

    def _cap_log(self) -> None:
        """Truncate a detached worker's private log past its size bound."""
        if not self._detached:
            return
        status: os.stat_result = os.fstat(2)
        if stat.S_ISREG(status.st_mode) and status.st_size > LOG_LIMIT_BYTES:
            os.ftruncate(2, 0)


def _read_metadata(*, location: ScheduleWorkerLocationDAO) -> Optional[_WorkerMetadataDAO]:
    """Read the metadata record; None when absent.

    Args:
        location (ScheduleWorkerLocationDAO): The worker location.

    Returns:
        Optional[_WorkerMetadataDAO]: The record.

    Raises:
        ValueError: When the record exists but is unreadable or corrupt.
    """
    try:
        descriptor: int = os.open(location.metadata_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"unreadable worker metadata: {error}") from error
    with os.fdopen(descriptor, "rb") as stream:
        raw: bytes = stream.read(CONTROL_MESSAGE_LIMIT_BYTES + 1)
    if len(raw) > CONTROL_MESSAGE_LIMIT_BYTES:
        raise ValueError("oversized worker metadata")
    return _WorkerMetadataDAO.model_validate_json(raw)


class ScheduleWorkerRuntime:
    """Start-or-reuse, observe and retire the one shared worker of a schedules directory."""

    def __init__(
        self,
        *,
        location: ScheduleWorkerLocationDAO,
        launcher: Optional[ScheduleWorkerLauncher] = None,
        startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS,
        probe_timeout_seconds: float = HEALTH_PROBE_TIMEOUT_SECONDS,
    ) -> None:
        """Bind the location and the launch seam; nothing is opened yet.

        Args:
            location (ScheduleWorkerLocationDAO): The stores the worker serves.
            launcher (Optional[ScheduleWorkerLauncher]): The launch seam; the
                detached installed entrypoint when None.
            startup_timeout_seconds (float): Launch-to-healthy deadline.
            probe_timeout_seconds (float): Bound of one health probe.
        """
        self._location: ScheduleWorkerLocationDAO = location
        self._launcher: ScheduleWorkerLauncher = (
            launcher if launcher is not None else SubprocessScheduleWorkerLauncher()
        )
        self._startup_timeout_seconds: float = startup_timeout_seconds
        self._probe_timeout_seconds: float = probe_timeout_seconds

    @property
    def location(self) -> ScheduleWorkerLocationDAO:
        """Return the location this runtime serves."""
        return self._location

    async def start_or_reuse(self) -> ScheduleWorkerHealthDAO:
        """Reuse the healthy shared worker or launch one and prove it healthy.

        Serialized across processes. An owned but silent worker is never
        replaced; a just-launched child that is not adopted (deadline,
        failure or cancellation) is reaped before this returns or raises.

        Returns:
            ScheduleWorkerHealthDAO: A healthy observation.

        A control file this runtime cannot use (a symlink, a directory, a
        permission failure) is reported as ``blocked``; nothing is followed,
        replaced or launched. Cancellation propagates unchanged.

        Raises:
            ScheduleWorkerUnavailableError: With the observation that explains why not.
        """
        try:
            return await self._start_or_reuse_serialized()
        except OSError as error:
            raise ScheduleWorkerUnavailableError(health=self._unusable_files(error=error)) from error

    async def inspect_health(self) -> ScheduleWorkerHealthDAO:
        """Observe the shared worker once (bounded); never launches or creates files.

        Returns:
            ScheduleWorkerHealthDAO: The observation; ``blocked`` when a control
                file cannot be used.
        """
        try:
            return await self._observe()
        except OSError as error:
            return self._unusable_files(error=error)

    async def _start_or_reuse_serialized(self) -> ScheduleWorkerHealthDAO:
        """Run one start-or-reuse decision under the cross-process launch lock.

        Returns:
            ScheduleWorkerHealthDAO: A healthy observation.

        Raises:
            ScheduleWorkerUnavailableError: With the observation that explains why not.
            OSError: When a control file cannot be used; the caller normalizes it.
        """
        self._location.schedules_dir.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
        async with self._launch_lock():
            observed: ScheduleWorkerHealthDAO = await self._observe()
            if observed.is_healthy:
                return observed
            if observed.state in ("starting", "retiring"):
                return await self._await_healthy(child=None, launch_id=None)
            if observed.state != "stopped":
                raise ScheduleWorkerUnavailableError(health=observed)
            return await self._launch()

    def _unusable_files(self, *, error: OSError) -> ScheduleWorkerHealthDAO:
        """Explain a control file this runtime cannot use, without exposing more than its name.

        Args:
            error (OSError): The filesystem failure.

        Returns:
            ScheduleWorkerHealthDAO: A ``blocked`` observation with a safe cause.
        """
        culprit: str = f" ({Path(error.filename).name})" if error.filename else ""
        cause: str = error.strerror or type(error).__name__
        return self._health(
            state="blocked",
            metadata=None,
            reason=f"the schedule worker's control files in {self._location.schedules_dir} are unusable: "
            f"{cause}{culprit}; fix or remove that path, then run `slo schedule start`",
        )

    async def retire(self) -> ScheduleWorkerHealthDAO:
        """Ask the running generation, by its launch id, to stop; wait for its lock to free.

        Returns:
            ScheduleWorkerHealthDAO: The stopped observation (also when none ran).

        Raises:
            ScheduleWorkerUnavailableError: When the worker did not accept or did not stop in time.
        """
        metadata: Optional[_WorkerMetadataDAO] = self._metadata_or_none()
        if metadata is None or not self._lifetime_owned():
            return await self._observe()
        answer: Optional[_ControlAnswerDAO] = await self._ask(op="retire", launch_id=metadata.launch_id)
        if answer is None or not answer.retiring:
            raise ScheduleWorkerUnavailableError(
                health=self._health(
                    state="unresponsive", metadata=metadata, reason="the worker did not accept retirement"
                )
            )
        deadline: float = time.monotonic() + RETIRE_TIMEOUT_SECONDS
        while self._lifetime_owned():
            if time.monotonic() > deadline:
                raise ScheduleWorkerUnavailableError(
                    health=self._health(
                        state="unresponsive", metadata=metadata, reason="the worker did not stop in time"
                    )
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        return await self._observe()

    def claim_lifetime(self, *, launch_id: Optional[str]) -> ScheduleWorkerLifetime:
        """Take the lifetime lock for a starting worker (detached or manual).

        Startup admission is shared: a manual worker first waits for the
        launch lock, so it can never take ownership between an automatic
        start's last check and its spawn; it then finds the launched worker's
        lock held and is refused. A detached worker is the child of the start
        that holds the launch lock on its behalf until it is healthy, so it
        takes only the lifetime lock (waiting for it would deadlock).

        Args:
            launch_id (Optional[str]): The runtime-issued generation id of a
                detached worker; None for a manual foreground worker.

        Returns:
            ScheduleWorkerLifetime: The held lifetime.

        Raises:
            ScheduleWorkerStartError: When another worker already runs or
                starts here, or a control file cannot be used.
        """
        try:
            self._location.schedules_dir.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
            if launch_id is not None:
                return self._take_lifetime_lock(launch_id=launch_id)
            with self._waiting_launch_lock():
                return self._take_lifetime_lock(launch_id=None)
        except OSError as error:
            raise ScheduleWorkerStartError(
                reason=self._unusable_files(error=error).reason or str(error)
            ) from error

    def _take_lifetime_lock(self, *, launch_id: Optional[str]) -> ScheduleWorkerLifetime:
        """Take the lifetime lock within its short wait, or refuse.

        Args:
            launch_id (Optional[str]): The detached generation id; None for a manual worker.

        Returns:
            ScheduleWorkerLifetime: The held lifetime.

        Raises:
            ScheduleWorkerStartError: When another worker holds it.
        """
        descriptor: Optional[int] = _open_lock_file(path=self._location.lifetime_lock_path, create=True)
        assert descriptor is not None
        deadline: float = time.monotonic() + LIFETIME_LOCK_WAIT_SECONDS
        while not _try_exclusive(descriptor=descriptor):
            if time.monotonic() > deadline:
                os.close(descriptor)
                raise ScheduleWorkerStartError(reason=_ALREADY_RUNNING_REASON)
            time.sleep(_LOCK_POLL_SECONDS)
        return ScheduleWorkerLifetime(
            location=self._location,
            launch_id=launch_id or uuid.uuid4().hex,
            lock_descriptor=descriptor,
            detached=launch_id is not None,
        )

    @contextmanager
    def _waiting_launch_lock(self) -> Iterator[None]:
        """Hold the cross-process launch lock for a manual worker's claim (bounded, blocking wait).

        Yields:
            None: While the lock is held.

        Raises:
            ScheduleWorkerStartError: When another command holds it past the bound.
        """
        descriptor: Optional[int] = _open_lock_file(path=self._location.launch_lock_path, create=True)
        assert descriptor is not None
        try:
            deadline: float = time.monotonic() + LAUNCH_LOCK_TIMEOUT_SECONDS
            while not _try_exclusive(descriptor=descriptor):
                if time.monotonic() > deadline:
                    raise ScheduleWorkerStartError(reason=_STILL_STARTING_REASON)
                time.sleep(_LOCK_POLL_SECONDS)
            yield
        finally:
            os.close(descriptor)

    @asynccontextmanager
    async def _launch_lock(self) -> AsyncIterator[None]:
        """Hold the cross-process launch lock (bounded wait).

        Yields:
            None: While the lock is held.

        Raises:
            ScheduleWorkerUnavailableError: When another command holds it past the bound.
        """
        descriptor: Optional[int] = _open_lock_file(path=self._location.launch_lock_path, create=True)
        assert descriptor is not None
        try:
            deadline: float = time.monotonic() + LAUNCH_LOCK_TIMEOUT_SECONDS
            while not _try_exclusive(descriptor=descriptor):
                if time.monotonic() > deadline:
                    raise ScheduleWorkerUnavailableError(
                        health=self._health(state="starting", metadata=None, reason=_STILL_STARTING_REASON)
                    )
                await asyncio.sleep(_LOCK_POLL_SECONDS)
            yield
        finally:
            os.close(descriptor)

    async def _launch(self) -> ScheduleWorkerHealthDAO:
        """Clear a dead generation's files, launch a new worker and adopt it once healthy.

        Returns:
            ScheduleWorkerHealthDAO: The healthy observation.

        Upgrade admission is decided first, with the same rules the worker
        applies, so a directory an earlier worker may still serve never gets
        a competing process; an automatic launch never confirms the upgrade.

        Raises:
            ScheduleWorkerUnavailableError: When admission refused, or the
                launch or startup failed.
        """
        self._ensure_launch_admitted()
        if not self._clear_dead_generation():
            return await self._await_healthy(child=None, launch_id=None)
        launch_id: str = uuid.uuid4().hex
        try:
            child: subprocess.Popen[bytes] = self._launcher.launch(
                launch_id=launch_id, location=self._location
            )
        except (OSError, RuntimeError) as error:
            raise ScheduleWorkerUnavailableError(
                health=self._health(
                    state="stopped",
                    metadata=None,
                    reason=f"the schedule worker could not be launched: {error}",
                )
            ) from error
        try:
            return await self._await_healthy(child=child, launch_id=launch_id)
        except BaseException:
            self._reap(child=child)
            raise

    def _ensure_launch_admitted(self) -> None:
        """Refuse a launch that upgrade admission would refuse in the worker.

        Raises:
            ScheduleWorkerUnavailableError: A ``blocked`` observation with the admission cause.
        """
        try:
            ScheduleEngineAdmission(db_path=self._location.db_path).ensure_admitted(
                earlier_workers_stopped=False
            )
        except ScheduleWorkerStartError as error:
            raise ScheduleWorkerUnavailableError(
                health=self._health(state="blocked", metadata=None, reason=error.reason)
            ) from error

    def _clear_dead_generation(self) -> bool:
        """Remove a dead generation's metadata and socket while holding its lifetime lock.

        Holding the lifetime lock during cleanup proves no worker published
        those files in between. A worker that took the lock first wins.

        Returns:
            bool: True when cleaned; False when a worker now owns the directory.
        """
        descriptor: Optional[int] = _open_lock_file(path=self._location.lifetime_lock_path, create=True)
        assert descriptor is not None
        try:
            if not _try_exclusive(descriptor=descriptor):
                return False
            _remove_if_kind(path=self._location.metadata_path, is_kind=stat.S_ISREG)
            _remove_if_kind(path=self._location.socket_path, is_kind=stat.S_ISSOCK)
            return True
        finally:
            os.close(descriptor)

    async def _await_healthy(
        self, *, child: Optional[subprocess.Popen[bytes]], launch_id: Optional[str]
    ) -> ScheduleWorkerHealthDAO:
        """Wait (bounded) until the owner answers healthy.

        Args:
            child (Optional[subprocess.Popen[bytes]]): The just-launched child, if any.
            launch_id (Optional[str]): Its generation id.

        Returns:
            ScheduleWorkerHealthDAO: The healthy observation.

        Raises:
            ScheduleWorkerUnavailableError: On blocked, exit, silent owner or deadline.
        """
        deadline: float = time.monotonic() + self._startup_timeout_seconds
        while True:
            observed: ScheduleWorkerHealthDAO = await self._observe()
            if observed.is_healthy:
                self._release_unadopted(
                    child=child, adopted_launch_id=observed.launch_id, launch_id=launch_id
                )
                return observed
            if observed.state == "blocked" or (observed.state == "unresponsive" and child is None):
                raise ScheduleWorkerUnavailableError(health=observed)
            if observed.state == "stopped" and child is None:
                return await self._launch()
            if child is not None and child.poll() is not None:
                if observed.state != "starting":
                    raise ScheduleWorkerUnavailableError(
                        health=self._health(
                            state="stopped", metadata=None, reason=self._exit_cause(child=child)
                        )
                    )
                child = None
            if time.monotonic() > deadline:
                raise ScheduleWorkerUnavailableError(
                    health=observed.model_copy(
                        update={
                            "reason": f"the schedule worker did not become healthy within "
                            f"{self._startup_timeout_seconds:g} seconds"
                            + (f" ({observed.reason})" if observed.reason else "")
                        }
                    )
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    def _release_unadopted(
        self,
        *,
        child: Optional[subprocess.Popen[bytes]],
        adopted_launch_id: Optional[str],
        launch_id: Optional[str],
    ) -> None:
        """Reap our child when another generation won the directory.

        Args:
            child (Optional[subprocess.Popen[bytes]]): The just-launched child.
            adopted_launch_id (Optional[str]): The healthy generation's id.
            launch_id (Optional[str]): Our child's generation id.
        """
        if child is not None and adopted_launch_id != launch_id:
            self._reap(child=child)

    @staticmethod
    def _reap(*, child: subprocess.Popen[bytes]) -> None:
        """Terminate, then kill past the grace, and wait for an unadopted child.

        Synchronous on purpose: no cancellation can cut the reap short. The
        handle is unreaped until this wait, so its PID cannot have been reused.

        Args:
            child (subprocess.Popen[bytes]): The child this runtime launched.
        """
        if child.poll() is not None:
            return
        with suppress(ProcessLookupError):
            child.terminate()
        try:
            child.wait(timeout=REAP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                child.kill()
            child.wait()

    def _exit_cause(self, *, child: subprocess.Popen[bytes]) -> str:
        """Explain a child that exited before becoming healthy, from its own last words.

        Args:
            child (subprocess.Popen[bytes]): The exited child.

        Returns:
            str: The worker's last diagnostic line (bounded), or its exit code.
        """
        fallback: str = f"the schedule worker exited with code {child.returncode} before it became healthy"
        try:
            with open(self._location.log_path, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(stream.tell() - 4096, 0))
                tail: str = stream.read().decode("utf-8", errors="replace")
        except OSError:
            return fallback
        lines: list[str] = [line.strip() for line in tail.splitlines() if line.strip()]
        return lines[-1][:_CAUSE_LIMIT_CHARACTERS] if lines else fallback

    def _lifetime_owned(self) -> bool:
        """Tell whether a live process holds the lifetime lock (never creates the file).

        Returns:
            bool: True when the lock is held.
        """
        descriptor: Optional[int] = _open_lock_file(path=self._location.lifetime_lock_path, create=False)
        if descriptor is None:
            return False
        try:
            if _try_exclusive(descriptor=descriptor):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                return False
            return True
        finally:
            os.close(descriptor)

    def _metadata_or_none(self) -> Optional[_WorkerMetadataDAO]:
        """Read the metadata, treating a corrupt record as absent."""
        try:
            return _read_metadata(location=self._location)
        except (ValueError, ValidationError):
            return None

    async def _observe(self) -> ScheduleWorkerHealthDAO:
        """Observe the worker: lock ownership, metadata, then a live challenge.

        Returns:
            ScheduleWorkerHealthDAO: The observation.
        """
        if not self._lifetime_owned():
            stale: bool = self._location.metadata_path.exists()
            reason: str = "the schedule worker stopped" if stale else "no schedule worker is running"
            return self._health(state="stopped", metadata=None, reason=reason)
        try:
            metadata: Optional[_WorkerMetadataDAO] = _read_metadata(location=self._location)
        except (ValueError, ValidationError):
            return self._health(
                state="unresponsive", metadata=None, reason="the schedule worker's record is unreadable"
            )
        if metadata is None:
            return self._health(state="starting", metadata=None, reason="the schedule worker is starting")
        answer: Optional[_ControlAnswerDAO] = await self._probe()
        return self._judge(metadata=metadata, answer=answer)

    async def _probe(self) -> Optional[_ControlAnswerDAO]:
        """Challenge the worker up to the attempt bound.

        Returns:
            Optional[_ControlAnswerDAO]: The first valid answer, or None.
        """
        for _attempt in range(UNRESPONSIVE_PROBE_ATTEMPTS):
            answer: Optional[_ControlAnswerDAO] = await self._ask(op="health", launch_id=None)
            if answer is not None:
                return answer
        return None

    def _judge(
        self, *, metadata: _WorkerMetadataDAO, answer: Optional[_ControlAnswerDAO]
    ) -> ScheduleWorkerHealthDAO:
        """Turn one answer into an observation, checking identity and store.

        Args:
            metadata (_WorkerMetadataDAO): The published record.
            answer (Optional[_ControlAnswerDAO]): The live answer, if any.

        Returns:
            ScheduleWorkerHealthDAO: The observation.
        """
        if answer is None:
            return self._health(
                state="unresponsive",
                metadata=metadata,
                reason=f"the schedule worker holds this directory but did not answer within "
                f"{self._probe_timeout_seconds:g} seconds",
            )
        if answer.launch_id != metadata.launch_id or answer.schedules_dir != str(
            self._location.schedules_dir
        ):
            return self._health(
                state="blocked",
                metadata=metadata,
                reason="the answering worker does not match this directory's record",
            )
        if answer.channel_db_path != str(self._location.channel_db_path) or answer.history_root != str(
            self._location.history_root
        ):
            return self._health(
                state="blocked",
                metadata=metadata,
                reason="the running schedule worker uses a different channel or session store than this command; "
                "use the same SLO_HOME, or stop that worker first",
            )
        return ScheduleWorkerHealthDAO(
            state=_STATE_BY_ENGINE_PHASE[answer.readiness.phase],
            observed_at=_utc_now(),
            launch_id=answer.launch_id,
            pid=answer.pid,
            reason=answer.readiness.reason,
            last_tick_at=answer.readiness.last_tick_at,
        )

    async def _ask(
        self, *, op: Literal["health", "retire"], launch_id: Optional[str]
    ) -> Optional[_ControlAnswerDAO]:
        """Send one challenge and read one bounded answer.

        Args:
            op (Literal["health", "retire"]): The request.
            launch_id (Optional[str]): The generation a retire must name.

        Returns:
            Optional[_ControlAnswerDAO]: The answer echoing the challenge, or None.
        """
        challenge: str = secrets.token_hex(16)
        request = _ControlRequestDAO(op=op, challenge=challenge, launch_id=launch_id)
        try:
            async with asyncio.timeout(self._probe_timeout_seconds):
                return await self._exchange(request=request)
        except (OSError, ValueError, ValidationError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None

    async def _exchange(self, *, request: _ControlRequestDAO) -> Optional[_ControlAnswerDAO]:
        """Connect, verify the peer user, send the request and parse the answer.

        Args:
            request (_ControlRequestDAO): The request to send.

        Returns:
            Optional[_ControlAnswerDAO]: The answer when it echoes the challenge.
        """
        with _control_address(location=self._location) as address:
            reader, writer = await asyncio.open_unix_connection(
                path=address, limit=CONTROL_MESSAGE_LIMIT_BYTES
            )
        try:
            if not _same_user(connection=writer.get_extra_info("socket")):
                return None
            writer.write(request.model_dump_json().encode("utf-8") + b"\n")
            await writer.drain()
            line: bytes = await reader.readline()
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
        answer: _ControlAnswerDAO = _ControlAnswerDAO.model_validate_json(line)
        return answer if answer.challenge == request.challenge else None

    def _health(
        self, *, state: ScheduleWorkerState, metadata: Optional[_WorkerMetadataDAO], reason: Optional[str]
    ) -> ScheduleWorkerHealthDAO:
        """Build an observation from the local facts alone.

        Args:
            state (ScheduleWorkerState): The observed state.
            metadata (Optional[_WorkerMetadataDAO]): The published record, if any.
            reason (Optional[str]): The safe explanation.

        Returns:
            ScheduleWorkerHealthDAO: The observation.
        """
        return ScheduleWorkerHealthDAO(
            state=state,
            observed_at=_utc_now(),
            launch_id=metadata.launch_id if metadata is not None else None,
            pid=metadata.pid if metadata is not None else None,
            reason=reason,
        )
