"""Reporter cleanup includes unresolved private restore operation ownership."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease
from tests.agents.slo_agent.herdr.test_reporter import reporter
from tests.agents.slo_agent.herdr.test_restore_save import config_for


async def test_reporter_retains_restore_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A restore-only retained lease prevents false drained final outcomes."""
    owner = reporter(root=tmp_path)
    store = HerdrRestoreStore(state_root=tmp_path)
    owner._restore_store = store
    original = HerdrFileLease.close

    def fail_close(lease: HerdrFileLease) -> None:
        """Retain the exact restore descriptor without any remote effects."""
        if lease is store._lease:
            raise OSError("private-close-sentinel")
        original(lease)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=HerdrFileLease, name="close", value=fail_close)
            with pytest.raises(HerdrRestoreUnavailableError):
                store.save(config=config_for(tmp_path))
            result = await owner.close_transport()
            assert result.resources == "retained"
            assert result.replacement == "uncertain"
            assert owner.retains_external_resources
        result = await owner.drain_retained_external_resources()
        assert result.resources == "drained"
        assert result.replacement == "uncertain"
        assert not store.retains_external_resources
    finally:
        original(store._lease)
