"""Failed pane acquisition preserves real rollback ownership through disposal."""

import asyncio
import fcntl
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceUnavailableError
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.herdr.lease_close_fault import LeaseCloseFault
from tests.agents.slo_agent.herdr.test_reporter import reporter


@pytest.mark.parametrize(argnames="session_owned", argvalues=[False, True])
@pytest.mark.parametrize(argnames="phase", argvalues=["lock", "load"])
@pytest.mark.parametrize(
    argnames="case", argvalues=["held", "released", "reused", "same_inode", "ebadf", "inspection"]
)
async def test_failed_acquisition_final_ownership(
    tmp_path: Path, phase: str, case: str, session_owned: bool
) -> None:
    """Failed start cannot hide a lease, authorize work, or reclose a recycled fd."""
    owner = reporter(root=tmp_path)
    store = owner._sequence_store
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._herdr_reporter = owner
    faults: list[LeaseCloseFault] = []
    retained = case in ("held", "same_inode", "inspection")
    with (
        patch.object(owner, "_validate_executable"),
        patch.object(owner._transport, "_spawn", side_effect=AssertionError("forbidden spawn")) as spawn,
        patch.object(store, "reserve", wraps=store.reserve) as reserve,
    ):
        with pytest.MonkeyPatch.context() as hooks:

            def fail_acquisition(fd: int = -1, operation: int = 0) -> None:
                """Install faults only after the actual owned descriptor is opened."""
                fault = LeaseCloseFault(lease=store._lease, root=tmp_path, case=case)
                faults.append(fault)
                hooks.setattr(target=os, name="close", value=fault.close)
                hooks.setattr(target=os, name="fstat", value=fault.inspect)
                raise OSError("private-acquisition-fault")

            hooks.setattr(
                target=fcntl if phase == "lock" else store,
                name="flock" if phase == "lock" else "_load",
                value=fail_acquisition,
            )
            try:
                await asyncio.wait_for(owner.start(), timeout=5)
                assert not owner._lease_held
                assert not owner.allows_viewer_admission()
                assert owner._transport.closed and owner._transport.resources_drained
                await owner.close()
                if session_owned:
                    final = await session.close_external_reporting()
                    drained = await session.drain_retained_external_resources()
                    assert session._herdr_reporter is owner
                else:
                    final = await owner.close_transport()
                    drained = await owner.drain_retained_external_resources()
                assert final.resources == drained.resources == ("retained" if retained else "drained")
                assert final.replacement == drained.replacement == "uncertain"
                assert owner.retains_external_resources is retained
                assert store.retains_external_resources is retained
                assert store._lease is faults[0].lease
                assert store._lease.retains_external_resources is retained
                assert faults[0].close_calls == 1
                spawn.assert_not_called()
                reserve.assert_not_called()
                with pytest.raises(HerdrSequenceUnavailableError):
                    store.reserve(source="custom:slo")
                if faults[0].open:
                    assert faults[0].real_stat(faults[0].fd)
                if case in ("reused", "same_inode"):
                    os.write(faults[0].fd, b"still usable")
                    os.lseek(faults[0].fd, 0, os.SEEK_SET)
                    assert os.read(faults[0].fd, 12) == b"still usable"
                assert not store._path.exists()
            finally:
                hooks.undo()
                for fault in faults:
                    fault.finish()
