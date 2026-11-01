"""Private restore storage uses real contained files and fail-closed admission."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrRestoreConfigDAO,
    HerdrRestoreRecordDAO,
    HerdrRestoreUnavailableError,
)
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore

SESSION_ID = "12345678-1234-1234-1234-123456789abc"
REFERENCE = "r1-" + "a" * 32


def test_constructor_and_missing_load_are_inert(tmp_path: Path) -> None:
    """Neither binding nor reading absent state initializes private storage."""
    store = HerdrRestoreStore(state_root=tmp_path / "absent")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(HerdrRestoreUnavailableError):
        store.load(restore_reference=REFERENCE, session_id=SESSION_ID)
    assert list(tmp_path.iterdir()) == []


def test_load_exact_record(tmp_path: Path) -> None:
    """Load copies exact policy without rewriting or creating history."""
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    root = tmp_path / "restore-v1"
    root.mkdir(mode=0o700)
    lock = tmp_path / "restore-v1.lock"
    lock.touch(mode=0o600)
    config = HerdrRestoreConfigDAO(
        session_id=SESSION_ID,
        model_name="gpt-5.4",
        reasoning_level="high",
        workdir=tmp_path,
    )
    record = HerdrRestoreRecordDAO(schema_version=1, restore_reference=REFERENCE, config=config)
    path = root / f"{REFERENCE}.json"
    path.touch(mode=0o600)
    path.write_text(record.model_dump_json())
    before = path.read_bytes()
    loaded = HerdrRestoreStore(state_root=tmp_path).load(
        restore_reference=REFERENCE,
        session_id=SESSION_ID,
    )
    assert loaded == config and loaded is not config
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == {root, lock}


@pytest.mark.parametrize("reference", ["../private", "", REFERENCE.upper(), REFERENCE + "\n"])
def test_reference_rejected_before_io(tmp_path: Path, reference: str) -> None:
    """Untrusted references never form paths or initialize storage."""
    with pytest.raises(HerdrRestoreUnavailableError):
        HerdrRestoreStore(state_root=tmp_path).load(restore_reference=reference, session_id=SESSION_ID)
    assert list(tmp_path.iterdir()) == []
