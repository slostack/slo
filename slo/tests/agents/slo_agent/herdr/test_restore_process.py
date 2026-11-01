"""Real process lease/crash evidence with temp-contained state only."""

import multiprocessing
from unittest.mock import patch
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


def _hold_lease(root: str, ready: Connection, release: Connection) -> None:
    """Hold this child's own lock until parent releases the deterministic barrier."""
    store = HerdrRestoreStore(state_root=Path(root))
    with store._locked_store():
        ready.send(True)
        release.recv()


def _save_then_wait(root: str, ready: Connection, release: Connection) -> None:
    """Commit a real orphan before pausing at the pre-advertisement boundary."""
    path = Path(root)
    saved = HerdrRestoreStore(state_root=path).save(config=config_for(path))
    ready.send(saved.restore_reference)
    release.recv()


def _pause_before_replace(root: str, ready: Connection, release: Connection) -> None:
    """Pause a real atomic write after file fsync but before final replacement."""
    path = Path(root)
    assert path.resolve() == path

    def pause(*, src: str, dst: Path) -> None:
        """Expose only test-owned writer paths to the controlling parent."""
        assert Path(src).resolve().is_relative_to(path)
        assert dst.resolve().is_relative_to(path)
        ready.send((str(src), str(dst)))
        release.recv()

    with patch("src.agents.slo_agent.history.atomic_io.os.replace", side_effect=pause):
        HerdrRestoreStore(state_root=path).save(config=config_for(path))


def _save_and_load(root: str, channel: Connection) -> None:
    """Run independent commands in a spawned process; refusal is not retried."""
    path = Path(root)
    assert path.resolve() == path
    store = HerdrRestoreStore(state_root=path)
    channel.send("ready")
    while True:
        operation, reference = channel.recv()
        if operation == "stop":
            return
        try:
            if operation == "save":
                saved = store.save(config=config_for(path))
                channel.send(("saved", saved.restore_reference))
            else:
                loaded = store.load(restore_reference=reference, session_id=SESSION_ID)
                channel.send(("loaded", loaded.model_dump_json()))
        except HerdrRestoreUnavailableError:
            channel.send(("busy", ""))


def test_concurrent_process_save_load(tmp_path: Path) -> None:
    """Concurrent callers either succeed exactly or refuse; later commands succeed."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    config = config_for(tmp_path)
    old = store.save(config=config)
    path = tmp_path / "restore-v1" / f"{old.restore_reference}.json"
    before = path.read_bytes()
    context = multiprocessing.get_context("spawn")
    pairs = [context.Pipe() for _ in range(2)]
    children = [context.Process(target=_save_and_load, args=(str(tmp_path), pair[1])) for pair in pairs]
    for child in children:
        child.start()
    try:
        for parent, _ in pairs:
            assert parent.poll(15) and parent.recv() == "ready"
        pairs[0][0].send(("save", ""))
        pairs[1][0].send(("load", old.restore_reference))
        results = []
        for parent, _ in pairs:
            assert parent.poll(15)
            results.append(parent.recv())
        assert results[0][0] in {"saved", "busy"}
        assert results[1][0] in {"loaded", "busy"}
        assert any(result[0] != "busy" for result in results)
        if results[1][0] == "loaded":
            assert results[1][1] == config.model_dump_json()
        # Fresh explicit operations after contention, not an automatic product retry.
        pairs[0][0].send(("save", ""))
        assert pairs[0][0].poll(15)
        status, reference = pairs[0][0].recv()
        assert status == "saved"
        pairs[1][0].send(("load", reference))
        assert pairs[1][0].poll(15)
        assert pairs[1][0].recv() == ("loaded", config.model_dump_json())
        assert path.read_bytes() == before
        for parent, _ in pairs:
            parent.send(("stop", ""))
        for child in children:
            child.join(15)
            assert child.exitcode == 0
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(15)
            child.close()
        for pair in pairs:
            for connection in pair:
                connection.close()


def test_pre_replace_child_crash(tmp_path: Path) -> None:
    """Child death leaves no new final revision and preserves the prior revision."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    old = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    before = old.read_bytes()
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    release_read, release_write = context.Pipe(duplex=False)
    child = context.Process(target=_pause_before_replace, args=(str(tmp_path), send, release_read))
    child.start()
    try:
        assert receive.poll(15)
        temporary, destination = receive.recv()
        assert Path(temporary).is_file()
        assert not Path(destination).exists()
        child.terminate()
        child.join(15)
        assert not child.is_alive()
        assert old.read_bytes() == before
        assert not Path(destination).exists()
        assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
            tmp_path
        )
    finally:
        if child.is_alive():
            child.terminate()
        child.join(15)
        for connection in (receive, send, release_read, release_write):
            connection.close()
        child.close()


@pytest.mark.parametrize("crash", [False, True])
def test_restore_lock_contention_and_crash(tmp_path: Path, crash: bool) -> None:
    """Contenders refuse promptly; child death frees only its advisory ownership."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    config = config_for(tmp_path)
    old = store.save(config=config)
    old_path = tmp_path / "restore-v1" / f"{old.restore_reference}.json"
    before = old_path.read_bytes()
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    release_read, release_write = context.Pipe(duplex=False)
    child = context.Process(
        target=_save_then_wait if crash else _hold_lease,
        args=(str(tmp_path), send, release_read),
    )
    child.start()
    try:
        assert receive.poll(15)
        result = receive.recv()
        if crash:
            child.terminate()
            child.join(15)
            assert not child.is_alive()
            assert store.load(restore_reference=result, session_id=SESSION_ID) == config
        else:
            with pytest.raises(HerdrRestoreUnavailableError):
                store.load(restore_reference=old.restore_reference, session_id=SESSION_ID)
            with pytest.raises(HerdrRestoreUnavailableError):
                store.save(config=config)
            release_write.send(True)
            child.join(15)
            assert child.exitcode == 0
        assert old_path.read_bytes() == before
        assert store.load(restore_reference=old.restore_reference, session_id=SESSION_ID) == config
    finally:
        if child.is_alive():
            child.terminate()
        child.join(15)
        for connection in (receive, send, release_read, release_write):
            connection.close()
        child.close()
