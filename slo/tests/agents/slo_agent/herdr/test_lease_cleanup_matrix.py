"""Actual pane final-drain and restore operation ambiguous-close boundaries."""

import os
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from tests.agents.slo_agent.herdr.lease_close_fault import LeaseCloseFault
from tests.agents.slo_agent.herdr.test_reporter import reporter
from tests.agents.slo_agent.herdr.test_restore_save import config_for


@pytest.mark.parametrize(
    argnames="case", argvalues=["held", "released", "reused", "same_inode", "ebadf", "inspection"]
)
@pytest.mark.parametrize(argnames="scope", argvalues=["pane", "restore"])
async def test_cleanup_retains_only_unresolved_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
    scope: str,
) -> None:
    """Never retry ambiguous close, lose an unresolved owner, or close a replacement."""
    owner = reporter(root=tmp_path)
    store = HerdrRestoreStore(state_root=tmp_path)
    owner._restore_store = store
    if scope == "pane":
        owner._sequence_store.acquire()
        owner._lease_held = True
        lease = owner._sequence_store._lease
    else:
        store._prepare_directories()
        store._lease.acquire(path=store._lock_path, create=True)
        lease = store._lease
    fault = LeaseCloseFault(lease=lease, root=tmp_path, case=case)
    retained = case in ("held", "same_inode", "inspection")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="close", value=fault.close)
            patch.setattr(target=os, name="fstat", value=fault.inspect)
            if scope == "restore":
                with pytest.raises(HerdrRestoreUnavailableError):
                    store.close()
                with pytest.raises(HerdrRestoreUnavailableError):
                    store.save(config=config_for(tmp_path))
            initial = await owner.close_transport()
            assert initial.replacement == "uncertain"
            result = await owner.drain_retained_external_resources()
            assert result.resources == ("retained" if retained else "drained")
            assert result.replacement == "uncertain"
            assert owner.retains_external_resources is retained
            assert lease.retains_external_resources is retained
            assert fault.close_calls == 1
            assert await owner.drain_retained_external_resources() is result
            if scope == "pane":
                assert initial.resources == "retained"
            if fault.open:
                assert fault.real_stat(fault.fd)
            assert "private-close-sentinel" not in caplog.text
            assert "private-inspection-sentinel" not in caplog.text
    finally:
        fault.finish()
