"""Real filesystem and process evidence for private sequence ownership."""

import os
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease, HerdrSequenceUnavailableError
from src.agents.slo_agent.herdr import sequence_store


def owned_file(*, root: Path, name: str, text: str = "", mode: int = 0o600) -> Path:
    """Write only a new contained regular file in this test's root."""
    path = root / name
    assert path.parent.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    assert not path.exists() and not path.is_symlink()
    with path.open(mode="x", encoding="utf-8") as stream:
        stream.write(text)
    path.chmod(mode)
    return path


def test_lease_contention_and_distinct_restore_scope(tmp_path: Path) -> None:
    """One mechanism excludes a second pane owner without blocking restore."""
    first, second, restore = HerdrFileLease(), HerdrFileLease(), HerdrFileLease()
    path = tmp_path / "pane.lock"
    try:
        first.acquire(path=path, create=True)
        with pytest.raises(HerdrSequenceUnavailableError):
            second.acquire(path=path, create=False)
        restore.acquire(path=tmp_path / "restore.lock", create=True)
        assert path.stat().st_mode & 0o777 == 0o600
        first.close()
        second.acquire(path=path, create=False)
    finally:
        first.close()
        second.close()
        restore.close()


@pytest.mark.parametrize("case", ["missing", "symlink", "directory", "public", "hardlink", "parent_public"])
def test_lease_refuses_unsafe_files(tmp_path: Path, case: str) -> None:
    """Unsafe paths are refused without fixing permissions or stealing files."""
    path = tmp_path / "pane.lock"
    if case == "symlink":
        target = owned_file(root=tmp_path, name="target")
        path.symlink_to(target)
    elif case == "directory":
        path.mkdir()
    elif case == "hardlink":
        target = owned_file(root=tmp_path, name="target")
        os.link(src=target, dst=path)
    elif case != "missing":
        owned_file(root=tmp_path, name="pane.lock", mode=0o644 if case == "public" else 0o600)
    if case == "parent_public":
        tmp_path.chmod(0o755)
    lease = HerdrFileLease()
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            lease.acquire(path=path, create=False)
    finally:
        lease.close()
        tmp_path.chmod(0o700)


def test_reservations_survive_restart(tmp_path: Path) -> None:
    """Both source counters persist before returning and never contain pane text."""
    store = sequence_store.HerdrSequenceStore(
        state_root=tmp_path, socket_namespace="secret-socket", pane_id="secret-pane"
    )
    assert list(tmp_path.iterdir()) == []
    store.acquire()
    try:
        assert store.reserve(source="custom:slo") == 1
        assert store.reserve(source="custom:slo-display") == 1
        assert store.reserve(source="custom:slo") == 2
        (path,) = (tmp_path / "sequence-v1").glob("*.json")
        assert len(path.stem) == 64
        assert '"lifecycle_sequence":2' in path.read_text()
        assert "secret" not in path.read_text()
    finally:
        store.close()
    store = sequence_store.HerdrSequenceStore(
        state_root=tmp_path, socket_namespace="secret-socket", pane_id="secret-pane"
    )
    store.acquire()
    try:
        assert store.reserve(source="custom:slo") == 3
        assert store.reserve(source="custom:slo-display") == 2
    finally:
        store.close()


@pytest.mark.parametrize("value", [True, -1, "3", 1.5, 2**63, None])
def test_corrupt_counter_refused_without_reset(tmp_path: Path, value: object) -> None:
    """Strict signed-64 counters reject corruption and preserve exact bytes."""
    import json

    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    text = json.dumps(dict(schema_version=1, lifecycle_sequence=value, display_sequence=0))
    path.write_text(text)
    with pytest.raises(HerdrSequenceUnavailableError):
        store.acquire()
    assert path.read_text() == text


def test_overflow_and_substitution_disable_reservations(tmp_path: Path) -> None:
    """Overflow cannot return a sendable value or rewrite existing evidence."""
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    text = '{"schema_version":1,"lifecycle_sequence":9223372036854775807,"display_sequence":0}'
    path.write_text(text)
    store.acquire()
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            store.reserve(source="custom:slo")
        with pytest.raises(HerdrSequenceUnavailableError):
            store.reserve(source="custom:slo-display")
        assert path.read_text() == text
    finally:
        store.close()


def test_replaced_lock_refused_and_repeated_acquire_retains_lock(tmp_path: Path) -> None:
    """Reentrant misuse must not silently release the original lease."""
    lease = HerdrFileLease()
    lease.acquire(path=tmp_path / "lock", create=True)
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            lease.acquire(path=tmp_path / "other", create=True)
        contender = HerdrFileLease()
        try:
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire(path=tmp_path / "lock", create=False)
        finally:
            contender.close()
    finally:
        lease.close()


@pytest.mark.parametrize("target", ["state_link", "state_mode", "lock_replace", "directory_mode", "deleted"])
def test_reservation_revalidates_owned_files(tmp_path: Path, target: str) -> None:
    """No atomic writer may follow or repair a compromised state path."""
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    replacement = owned_file(root=tmp_path, name="untouched", text="sentinel")
    if target == "state_link":
        path.unlink()
        path.symlink_to(replacement)
    elif target == "state_mode":
        path.chmod(0o644)
    elif target == "lock_replace":
        replacement.replace(path.with_suffix(".lock"))
    elif target == "directory_mode":
        path.parent.chmod(0o755)
    else:
        path.unlink()
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            store.reserve(source="custom:slo")
    finally:
        store.close()


def test_missing_private_root_and_repeat_acquisition(tmp_path: Path) -> None:
    """Activation may create private state but reentry cannot surrender ownership."""
    root = tmp_path / "herdr"
    store = sequence_store.HerdrSequenceStore(state_root=root, socket_namespace="default", pane_id="pane")
    store.acquire()
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            store.acquire()
        assert store.reserve(source="custom:slo") == 1
    finally:
        store.close()


def test_windows_byte_lock_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the platform branch using a recording byte-lock adapter."""
    import sys
    from types import SimpleNamespace

    calls: list[tuple[int, int]] = []

    def locking(fd: int, operation: int, count: int) -> None:
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert os.fstat(fd).st_size == 1
        calls.append((operation, count))

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=2))
    monkeypatch.setattr(sequence_store, "_PLATFORM", "nt", raising=False)
    lease = HerdrFileLease()
    lease.acquire(path=tmp_path / "lock", create=True)
    lease.close()
    assert calls == [(2, 1)]


@pytest.mark.parametrize("failure", ["write", "warning", "uncommitted"])
def test_writer_refusal_never_returns_sendable_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Failure remains sticky while held; committed warning consumes a safe gap."""
    from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO

    writer = sequence_store.AtomicFileWriter.write_text_with_outcome
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()

    def fail(*, path: Path, text: str, private: bool = True) -> AtomicWriteOutcomeDAO:
        if failure == "write":
            raise OSError("private-sentinel")
        if failure == "warning":
            writer(path=path, text=text, private=private)
        return AtomicWriteOutcomeDAO(committed=failure == "warning", durability_warning=failure == "warning")

    with monkeypatch.context() as patch:
        patch.setattr(sequence_store.AtomicFileWriter, "write_text_with_outcome", fail)
        for _ in range(2):
            with pytest.raises(HerdrSequenceUnavailableError, match="^Herdr sequence unavailable.$"):
                store.reserve(source="custom:slo")
    store.close()
    store.acquire()
    try:
        assert store.reserve(source="custom:slo") == (2 if failure == "warning" else 1)
    finally:
        store.close()


@pytest.mark.parametrize(
    "text",
    [
        "not-json",
        "{}",
        '{"schema_version":2,"lifecycle_sequence":0,"display_sequence":0}',
        '{"schema_version":true,"lifecycle_sequence":0,"display_sequence":0}',
    ],
)
def test_malformed_state_preserved(tmp_path: Path, text: str) -> None:
    """Malformed/version data is never repaired and failed acquisition unlocks."""
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.write_text(text)
    for _ in range(2):
        with pytest.raises(HerdrSequenceUnavailableError):
            store.acquire()
        assert path.read_text() == text


@pytest.mark.parametrize("crash", [False, True])
def test_actual_process_contention_restart_and_crash(tmp_path: Path, crash: bool) -> None:
    """Two fresh OS processes cannot steal a pane; death releases its lock only."""
    import subprocess
    import sys
    import select

    script = """
import sys
from pathlib import Path
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
store = HerdrSequenceStore(state_root=Path(sys.argv[1]), socket_namespace="default", pane_id="pane")
try:
    store.acquire()
except HerdrSequenceUnavailableError:
    print("refused", flush=True)
    sys.exit(7)
print(store.reserve(source="custom:slo"), flush=True)
if sys.argv[2] == "hold":
    sys.stdin.readline()
store.close()
"""
    owner = subprocess.Popen(
        args=[sys.executable, "-c", script, str(tmp_path), "hold"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout is not None
        assert select.select([owner.stdout], [], [], 10)[0]
        assert owner.stdout.readline().strip() == "1"
        contender = subprocess.run(
            args=[sys.executable, "-c", script, str(tmp_path), "once"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert contender.returncode == 7, contender.stderr
        assert contender.stdout.strip() == "refused"
        if crash:
            owner.kill()
            owner.wait(timeout=10)
        else:
            owner.communicate(input="close\n", timeout=10)
            assert owner.returncode == 0
        restarted = subprocess.run(
            args=[sys.executable, "-c", script, str(tmp_path), "once"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert restarted.returncode == 0, restarted.stderr
        assert restarted.stdout.strip() == "2"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def test_oversized_state_refused_without_reading_unbounded_data(tmp_path: Path) -> None:
    """Counter files have a bounded read independent of their declared schema."""
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.write_text(" " * 5000 + '{"schema_version":1,"lifecycle_sequence":1,"display_sequence":0}')
    with pytest.raises(HerdrSequenceUnavailableError):
        store.acquire()


@pytest.mark.parametrize(
    "namespace,pane", [("other", "pane"), ("default", "other"), ("a:b", "c"), ("a", "b:c")]
)
def test_namespaces_have_independent_leases(tmp_path: Path, namespace: str, pane: str) -> None:
    """Canonical hashed tuples isolate socket/pane identities without raw filenames."""
    first = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    second = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace=namespace, pane_id=pane)
    first.acquire()
    try:
        second.acquire()
        assert first.reserve(source="custom:slo") == second.reserve(source="custom:slo") == 1
        assert len(list((tmp_path / "sequence-v1").glob("*.json"))) == 2
    finally:
        second.close()
        first.close()


def test_unsupported_locking_closes_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported semantics refuse locally and leave no retained lock."""
    lease = HerdrFileLease()
    with monkeypatch.context() as patch:
        patch.setattr(sequence_store, "_PLATFORM", "unsupported")
        with pytest.raises(HerdrSequenceUnavailableError):
            lease.acquire(path=tmp_path / "lock", create=True)
    lease.acquire(path=tmp_path / "lock", create=False)
    lease.close()


@pytest.mark.parametrize("operation", ["lease_open", "state_open"])
def test_substitution_between_validation_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Descriptor identity mismatch refuses a newly substituted regular inode."""
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (state,) = (tmp_path / "sequence-v1").glob("*.json")
    target = state if operation == "state_open" else state.with_suffix(".lock")
    replacement = owned_file(root=tmp_path, name="replacement", text=state.read_text())
    original = os.open

    def substitute(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == target and replacement.exists():
            assert target.parent.resolve().is_relative_to(tmp_path.resolve())
            replacement.replace(target)
        return original(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", substitute)
        with pytest.raises(HerdrSequenceUnavailableError):
            store.acquire()
    store.close()


def test_unheld_and_invalid_source_refused(tmp_path: Path) -> None:
    """No caller can manufacture a reservation outside the held source inventory."""
    from typing import cast, Literal

    lease = HerdrFileLease()
    with pytest.raises(HerdrSequenceUnavailableError):
        lease.require_held(path=tmp_path / "missing")
    store = sequence_store.HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    with pytest.raises(HerdrSequenceUnavailableError):
        store.reserve(source="custom:slo")
    store.acquire()
    try:
        with pytest.raises(HerdrSequenceUnavailableError):
            store.reserve(source=cast(Literal["custom:slo"], "invalid"))
        assert not list((tmp_path / "sequence-v1").glob("*.json"))
    finally:
        store.close()
