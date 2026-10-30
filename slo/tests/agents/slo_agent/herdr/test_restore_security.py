"""Finite security/refusal matrix at the real store public boundary."""

import os
import traceback
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


@pytest.mark.parametrize("fault", ["mkdir", "race_private", "race_insecure", "linked_root", "linked_parent"])
def test_directory_preparation(tmp_path: Path, fault: str) -> None:
    """Creation races validate the winner; linked owned chains never authorize saves."""
    assert tmp_path.resolve() == tmp_path
    state = tmp_path / "state"
    original = Path.mkdir
    if fault.startswith("linked"):
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        if fault == "linked_parent":
            state.symlink_to(target, target_is_directory=True)
        else:
            state.mkdir(mode=0o700)
            (state / "restore-v1").symlink_to(target, target_is_directory=True)

    def create(path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        """Create a competing contained directory exactly at the mkdir seam."""
        if path == state and fault == "mkdir":
            raise OSError("PRIVATE-SENTINEL")
        if path == state and fault.startswith("race"):
            original(path, mode=0o700 if fault == "race_private" else 0o755)
        original(path, mode=mode, parents=parents, exist_ok=exist_ok)

    store = HerdrRestoreStore(state_root=state)
    with patch.object(Path, "mkdir", create):
        if fault == "race_private":
            saved = store.save(config=config_for(tmp_path))
            assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
                tmp_path
            )
        else:
            with pytest.raises(HerdrRestoreUnavailableError) as caught:
                store.save(config=config_for(tmp_path))
            assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    if fault.startswith("linked"):
        assert list(target.iterdir()) == []


@pytest.mark.parametrize("fault", ["stat", "mode", "hardlink", "fifo", "symlink", "owner"])
def test_scan_entry_refusal(tmp_path: Path, fault: str) -> None:
    """Every unsafe scan entry refuses saving without changing prior revision bytes."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    old = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    before = old.read_bytes()
    entry = old.parent / "unexpected"
    entry.touch(mode=0o600)
    if fault == "mode":
        entry.chmod(0o644)
    elif fault == "hardlink":
        os.link(entry, tmp_path / "alias")
    elif fault in {"fifo", "symlink"}:
        entry.unlink()
        if fault == "fifo":
            os.mkfifo(entry, mode=0o600)
        else:
            entry.symlink_to(tmp_path / "absent")
    original = Path.lstat

    def inspect(path: Path) -> os.stat_result:
        """Inject only this scan entry's inspection/ownership failure."""
        info = original(path)
        if path == entry and fault == "stat":
            raise OSError("PRIVATE-SENTINEL")
        if path == entry and fault == "owner":
            fields = list(info)
            fields[4] = info.st_uid + 1
            return os.stat_result(fields)
        return info

    with patch.object(Path, "lstat", inspect):
        with pytest.raises(HerdrRestoreUnavailableError) as caught:
            store.save(config=config_for(tmp_path))
    assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    assert old.read_bytes() == before
    assert entry.exists() or entry.is_symlink()


@pytest.mark.parametrize(
    "identity", ["slug", SESSION_ID.upper(), "{" + SESSION_ID + "}", SESSION_ID.replace("-", ""), ""]
)
@pytest.mark.parametrize("operation", ["save", "load", "stored"])
def test_noncanonical_identity(tmp_path: Path, identity: str, operation: str) -> None:
    """Neither stored nor supplied identities may use ordinary resume normalization."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    if operation == "stored":
        path.write_text(path.read_text().replace(SESSION_ID, identity))
    with pytest.raises(HerdrRestoreUnavailableError):
        if operation == "save":
            store.save(config=config_for(tmp_path).model_copy(update={"session_id": identity}))
        else:
            store.load(
                restore_reference=saved.restore_reference,
                session_id=identity if operation == "load" else SESSION_ID,
            )


@pytest.mark.parametrize("operation", ["save", "load"])
@pytest.mark.parametrize(
    "fault",
    [
        "root_mode",
        "parent_mode",
        "owner",
        "platform",
        "missing_lock",
        "missing_root",
        "scan",
        "open",
        "read",
        "nofollow",
    ],
)
def test_security_and_io_refusal(tmp_path: Path, operation: str, fault: str) -> None:
    """Private errors never escape through formatted traceback or mutate old bytes."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    root = tmp_path / "restore-v1"
    path = root / f"{saved.restore_reference}.json"
    before = path.read_bytes()
    if fault == "root_mode":
        root.chmod(0o755)
    if fault == "parent_mode":
        tmp_path.chmod(0o755)
    if fault == "missing_lock":
        (tmp_path / "restore-v1.lock").unlink()
    if fault == "missing_root":
        root.rename(tmp_path / "retained")
    targets: dict[str, tuple[str, dict[str, object]]] = {
        "owner": ("src.agents.slo_agent.herdr.sequence_store.os.getuid", {"return_value": os.getuid() + 1}),
        "platform": ("src.agents.slo_agent.herdr.sequence_store._PLATFORM", {"new": "unsupported"}),
        "scan": (
            "src.agents.slo_agent.herdr.restore.os.scandir",
            {"side_effect": OSError("PRIVATE-SENTINEL")},
        ),
        "open": ("src.agents.slo_agent.herdr.restore.os.open", {"side_effect": OSError("PRIVATE-SENTINEL")}),
        "read": ("src.agents.slo_agent.herdr.restore.os.read", {"side_effect": OSError("PRIVATE-SENTINEL")}),
    }
    from contextlib import nullcontext

    context = nullcontext() if fault not in targets else patch(target=targets[fault][0])
    # Missing state can be recreated only by save; unrelated operation faults are inert.
    succeeds = (operation == "save" and fault in {"missing_lock", "missing_root", "read", "nofollow"}) or (
        operation == "load" and fault == "scan"
    )
    with context as mocked:
        if fault == "owner":
            assert mocked is not None
            mocked.return_value = os.getuid() + 1
        elif fault in {"scan", "open", "read"}:
            assert mocked is not None
            mocked.side_effect = OSError("PRIVATE-SENTINEL")
        with pytest.MonkeyPatch.context() as monkeypatch:
            if fault == "platform":
                monkeypatch.setattr("src.agents.slo_agent.herdr.sequence_store._PLATFORM", "unsupported")
            if fault == "nofollow":
                monkeypatch.delattr(os, "O_NOFOLLOW")
            if succeeds:
                if operation == "save":
                    store.save(config=config_for(tmp_path))
                else:
                    store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
            else:
                with pytest.raises(HerdrRestoreUnavailableError) as caught:
                    if operation == "save":
                        store.save(config=config_for(tmp_path))
                    else:
                        store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
                assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    retained = tmp_path / "retained" / path.name if fault == "missing_root" else path
    assert retained.read_bytes() == before
