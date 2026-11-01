"""Real private filesystem save contracts; all artifacts stay under tmp_path."""

from pathlib import Path
import stat
from unittest.mock import patch

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter, AtomicWriteOutcomeDAO

import pytest

from src.agents.slo_agent.herdr.dao import HerdrRestoreUnavailableError

from src.agents.slo_agent.herdr.dao import HerdrRestoreConfigDAO, HerdrRestoreRecordDAO
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore

SESSION_ID = "12345678-1234-1234-1234-123456789abc"


def config_for(root: Path) -> HerdrRestoreConfigDAO:
    """Build synthetic private policy without touching history or providers."""
    return HerdrRestoreConfigDAO(
        session_id=SESSION_ID, model_name="gpt-5.4", reasoning_level="high", workdir=root
    )


def test_save_allocates_private_immutable_revisions(tmp_path: Path) -> None:
    """Two saves retain independent exact records and never initialize history."""
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    state = tmp_path / "herdr"
    store = HerdrRestoreStore(state_root=state)
    config = config_for(tmp_path)
    first = store.save(config=config)
    path = state / "restore-v1" / f"{first.restore_reference}.json"
    before = path.read_bytes()
    second = store.save(config=config)
    assert first != second
    assert path.read_bytes() == before
    assert store.load(restore_reference=first.restore_reference, session_id=SESSION_ID) == config
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert set(tmp_path.iterdir()) == {state}


@pytest.mark.parametrize("kind", ["record", "count", "bytes", "directory"])
def test_quota_refuses_without_eviction(tmp_path: Path, kind: str) -> None:
    """Oversize input and all unrelated entries count without deletion."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    config = config_for(tmp_path)
    old = store.save(config=config)
    root = tmp_path / "restore-v1"
    old_path = root / f"{old.restore_reference}.json"
    before = old_path.read_bytes()
    if kind == "record":
        config = config.model_copy(update={"model_name": "x" * 65536})
    elif kind == "count":
        for number in range(1023):
            (root / f"orphan-{number}").touch(mode=0o600)
    elif kind == "bytes":
        path = root / "corrupt"
        path.touch(mode=0o600)
        with path.open("wb") as stream:
            stream.truncate(67108864)
    else:
        (root / "unexpected").mkdir(mode=0o700)
    names = set(root.iterdir())
    with pytest.raises(HerdrRestoreUnavailableError):
        store.save(config=config)
    assert set(root.iterdir()) == names
    assert old_path.read_bytes() == before


@pytest.mark.parametrize("fault", ["exception", "uncommitted", "warning"])
def test_writer_failure_preserves_old_revision(tmp_path: Path, fault: str) -> None:
    """Writer failures return no reference and preserve all advertised bytes."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    config = config_for(tmp_path)
    old = store.save(config=config)
    path = tmp_path / "restore-v1" / f"{old.restore_reference}.json"
    before = path.read_bytes()
    original = AtomicFileWriter.write_text_with_outcome

    def fail(*, path: Path, text: str, private: bool) -> AtomicWriteOutcomeDAO:
        """Inject only the writer boundary; warning retains the real visible orphan."""
        if fault == "exception":
            raise OSError("PRIVATE-SENTINEL")
        if fault == "warning":
            original(path=path, text=text, private=private)
            return AtomicWriteOutcomeDAO(committed=True, durability_warning=True)
        return AtomicWriteOutcomeDAO(committed=False)

    with patch.object(AtomicFileWriter, "write_text_with_outcome", side_effect=fail):
        with pytest.raises(HerdrRestoreUnavailableError) as caught:
            store.save(config=config)
    assert "PRIVATE-SENTINEL" not in str(caught.value)
    assert caught.value.__suppress_context__ or caught.value.__context__ is None
    assert path.read_bytes() == before
    assert store.load(restore_reference=old.restore_reference, session_id=SESSION_ID) == config


def test_lock_substitution_refuses_commit(tmp_path: Path) -> None:
    """A replaced lease pathname cannot authorize a write on the old descriptor."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    original = store._allocate_record

    def substitute(*, config: HerdrRestoreConfigDAO) -> HerdrRestoreRecordDAO:
        """Replace only a contained regular lock at the allocation boundary."""
        record = original(config=config)
        lock = tmp_path / "restore-v1.lock"
        lock.rename(tmp_path / "retired-lock")
        lock.touch(mode=0o600)
        return record

    with patch.object(store, "_allocate_record", side_effect=substitute):
        with pytest.raises(HerdrRestoreUnavailableError):
            store.save(config=config_for(tmp_path))
    assert list((tmp_path / "restore-v1").iterdir()) == []
