"""Final finite restore ownership and collision acceptance rows."""

import os
import traceback
import warnings
from uuid import UUID
from pathlib import Path
from unittest.mock import patch

import pytest

from src.auth.credential_dao import ProviderName
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


@pytest.mark.parametrize("level", ["state", "records"])
@pytest.mark.parametrize("operation", ["save", "load"])
def test_distinct_directory_owner(tmp_path: Path, level: str, operation: str) -> None:
    """Reject each owned level independently, without chmod or writer invocation."""
    assert tmp_path.resolve() == tmp_path
    state = tmp_path / "state"
    store = HerdrRestoreStore(state_root=state)
    saved = store.save(config=config_for(tmp_path))
    record = state / "restore-v1" / f"{saved.restore_reference}.json"
    before = record.read_bytes()
    target = state if level == "state" else record.parent
    original = Path.lstat
    inspected: list[Path] = []

    def inspect(path: Path) -> os.stat_result:
        """Alter only the selected owned directory's observed owner."""
        info = original(path)
        if path == target:
            inspected.append(path)
            fields = list(info)
            fields[4] = info.st_uid + 1
            return os.stat_result(fields)
        return info

    with (
        patch.object(Path, "lstat", inspect),
        patch.object(AtomicFileWriter, "write_text_with_outcome") as writer,
    ):
        with pytest.raises(HerdrRestoreUnavailableError):
            if operation == "save":
                store.save(config=config_for(tmp_path))
            else:
                store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
        writer.assert_not_called()
    assert inspected and record.read_bytes() == before


@pytest.mark.parametrize("parent", ["private", "public", "foreign", "missing"])
def test_creation_parent_depth(tmp_path: Path, parent: str) -> None:
    """Creation validates the immediate existing parent; it never mkdirs ancestors."""
    assert tmp_path.resolve() == tmp_path
    ancestor = tmp_path / "integrations"
    if parent != "missing":
        ancestor.mkdir(mode=0o755 if parent == "public" else 0o700)
    state = ancestor / "herdr"
    original = Path.lstat

    def inspect(path: Path) -> os.stat_result:
        """Inject foreign ownership only on the creation parent."""
        info = original(path)
        if path == ancestor and parent == "foreign":
            fields = list(info)
            fields[4] = info.st_uid + 1
            return os.stat_result(fields)
        return info

    with patch.object(Path, "lstat", inspect):
        store = HerdrRestoreStore(state_root=state)
        if parent == "private":
            saved = store.save(config=config_for(tmp_path))
            assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
                tmp_path
            )
        else:
            with pytest.raises(HerdrRestoreUnavailableError):
                store.save(config=config_for(tmp_path))
            assert not state.exists()
    assert ancestor.exists() == (parent != "missing")


@pytest.mark.parametrize("stage", ["allocation", "commit_file", "commit_link"])
def test_occupied_name_never_calls_writer(tmp_path: Path, stage: str) -> None:
    """Dangling allocation collisions and late occupied targets never reach replace."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    old = store.save(config=config_for(tmp_path))
    root = tmp_path / "restore-v1"
    old_path = root / f"{old.restore_reference}.json"
    before = old_path.read_bytes()
    value = UUID(int=1)
    target = root / f"r1-{value.hex}.json"
    original = store._require_capacity

    def occupy(*, record_bytes: int) -> None:
        """Populate the chosen name after capacity inspection, before commit."""
        original(record_bytes=record_bytes)
        assert target.parent.resolve().is_relative_to(tmp_path)
        if stage == "commit_file":
            target.touch(mode=0o600)
            target.write_bytes(b"occupied")
        else:
            target.symlink_to(tmp_path / "absent")

    if stage == "allocation":
        target.symlink_to(tmp_path / "absent")
    with patch("src.agents.slo_agent.herdr.restore.uuid4", return_value=value) as draw:
        with patch.object(store, "_require_capacity", side_effect=occupy):
            with patch.object(AtomicFileWriter, "write_text_with_outcome") as writer:
                with pytest.raises(HerdrRestoreUnavailableError):
                    store.save(config=config_for(tmp_path))
                writer.assert_not_called()
        assert draw.call_count == (3 if stage == "allocation" else 1)
    assert old_path.read_bytes() == before
    if stage == "commit_file":
        assert target.read_bytes() == b"occupied"
    else:
        assert target.is_symlink() and not target.exists()


@pytest.mark.parametrize("fault", ["create", "write", "open", "fstat", "flock"])
def test_acquire_stage_refuses_and_releases(tmp_path: Path, fault: str) -> None:
    """Actual lease acquisition faults refuse before writer and release opened fds."""
    import fcntl

    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    old = store.save(config=config_for(tmp_path))
    record = tmp_path / "restore-v1" / f"{old.restore_reference}.json"
    before = record.read_bytes()
    lock = tmp_path / "restore-v1.lock"
    if fault in {"create", "write"}:
        lock.unlink()
    original = os.open
    opened: list[int] = []

    def open_lock(path: Path, flags: int, mode: int = 0o777) -> int:
        """Observe only the restore lock; inject its exact open stage."""
        assert path == lock
        if fault == "create" or (fault == "open" and not flags & os.O_CREAT):
            raise OSError("PRIVATE-ACQUIRE-SENTINEL")
        fd = original(path, flags, mode)
        opened.append(fd)
        return fd

    def fail(*args: object) -> None:
        """Simulate one syscall's private error without performing its operation."""
        raise OSError("PRIVATE-ACQUIRE-SENTINEL")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(os, "open", open_lock)
        target = {"write": "write", "fstat": "fstat"}.get(fault)
        if target is not None:
            monkeypatch.setattr(os, target, fail)
        if fault == "flock":
            monkeypatch.setattr(fcntl, "flock", fail)
        with patch.object(AtomicFileWriter, "write_text_with_outcome") as writer:
            with pytest.raises(HerdrRestoreUnavailableError) as caught:
                store.save(config=config_for(tmp_path))
            writer.assert_not_called()
    assert "PRIVATE-ACQUIRE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert record.read_bytes() == before
    store.save(config=config_for(tmp_path))


@pytest.mark.parametrize("invalid", ["provider", "priority", "entries"])
def test_copied_invalid_nested_pool_private(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, invalid: str
) -> None:
    """Copied bypassed nested values are revalidated without public diagnostics."""
    from src.agents.slo_agent.herdr.dao import HerdrRestorePoolDAO, HerdrRestorePoolEntryDAO

    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    before = path.read_bytes()
    sentinel = "PRIVATE-NESTED-POOL-SENTINEL"
    entry = HerdrRestorePoolEntryDAO(
        model_name="gpt-5.4",
        provider=ProviderName.OPENAI,
        priority=1,
        cooldown_seconds=300,
        rate_limit_cooldown_seconds=60,
    )
    bad = entry.model_copy(update={invalid: sentinel}) if invalid != "entries" else entry
    pool = HerdrRestorePoolDAO.model_construct(entries=(bad,) if invalid == "entries" else (bad, entry))
    config = config_for(tmp_path).model_copy(update={"model_pool_dao": pool})
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        with patch.object(AtomicFileWriter, "write_text_with_outcome") as writer:
            with pytest.raises(HerdrRestoreUnavailableError) as caught:
                store.save(config=config)
            writer.assert_not_called()
    assert all(sentinel not in str(warning.message) for warning in emitted)
    public = (
        str(caught.value)
        + repr(caught.value)
        + "".join(traceback.format_exception(caught.value))
        + caplog.text
    )
    assert sentinel not in public
    assert str(tmp_path) not in public
    assert path.read_bytes() == before
    assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
        tmp_path
    )
