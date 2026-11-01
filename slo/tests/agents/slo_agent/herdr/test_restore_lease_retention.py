"""Restore operation cleanup retains unresolved original descriptor ownership."""

import os
import traceback
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease
from tests.agents.slo_agent.herdr.test_restore_save import config_for, SESSION_ID
from tests.agents.slo_agent.herdr.lease_close_fault import LeaseCloseFault


def test_failed_close_retains_store_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed save cannot lose its lease or admit another operation over it."""
    store = HerdrRestoreStore(state_root=tmp_path)
    leases: list[HerdrFileLease] = []
    real_close = HerdrFileLease.close

    def fail_close(lease: HerdrFileLease) -> None:
        """Keep this test's real handle open, preserving the exact owner."""
        leases.append(lease)
        raise OSError("private-close-sentinel")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=HerdrFileLease, name="close", value=fail_close)
            with pytest.raises(HerdrRestoreUnavailableError):
                store.save(config=config_for(tmp_path))
            assert store.retains_external_resources
            assert store._lease is leases[0]
            before = tuple((tmp_path / "restore-v1").iterdir())
            with pytest.raises(HerdrRestoreUnavailableError):
                store.save(config=config_for(tmp_path))
            assert tuple((tmp_path / "restore-v1").iterdir()) == before
            assert store._lease is leases[0]
        store.close()
        assert not store.retains_external_resources
    finally:
        for lease in leases:
            real_close(lease)


@pytest.mark.parametrize(
    argnames="case", argvalues=["held", "released", "reused", "same_inode", "ebadf", "inspection"]
)
@pytest.mark.parametrize(argnames="operation", argvalues=["save", "load"])
def test_operation_close_fault_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, operation: str
) -> None:
    """Real save/load cleanup keeps the same owner and returns only fixed refusal."""
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    faults: list[LeaseCloseFault] = []
    original = HerdrFileLease.close

    def fail_operation_close(lease: HerdrFileLease) -> None:
        """Patch only cleanup after the operation acquired its actual lease."""
        if lease is not store._lease or faults:
            original(lease)
            return
        fault = LeaseCloseFault(lease=lease, root=tmp_path, case=case)
        faults.append(fault)
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="close", value=fault.close)
            original(lease)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=HerdrFileLease, name="close", value=fail_operation_close)
            with pytest.raises(HerdrRestoreUnavailableError) as caught:
                if operation == "save":
                    store.save(config=config_for(tmp_path))
                else:
                    store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
        assert "private-close-sentinel" not in "".join(traceback.format_exception(caught.value))
        fault = faults[0]
        assert store._lease is fault.lease and store.retains_external_resources
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="fstat", value=fault.inspect)
            if case in ("held", "same_inode", "inspection"):
                with pytest.raises(HerdrRestoreUnavailableError):
                    store.close()
                assert store.retains_external_resources
            else:
                store.close()
                assert not store.retains_external_resources
        assert fault.close_calls == 1
        if fault.open:
            assert fault.real_stat(fault.fd)
    finally:
        for fault in faults:
            fault.finish()


def test_active_operation_cannot_be_closed(tmp_path: Path) -> None:
    """A concurrent cleanup request cannot release an operation's active lock."""
    store = HerdrRestoreStore(state_root=tmp_path)
    with store._locked_store(create=True) as lease:
        with pytest.raises(HerdrRestoreUnavailableError):
            store.close()
        assert lease.retains_external_resources
        with pytest.raises(HerdrRestoreUnavailableError):
            store.save(config=config_for(tmp_path))
    assert not store.retains_external_resources
