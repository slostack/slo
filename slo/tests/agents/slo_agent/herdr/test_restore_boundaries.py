"""Exact allocation and capacity boundaries on private test-owned files."""

from pathlib import Path
import os
from contextlib import contextmanager
from collections.abc import Iterator
from unittest.mock import patch
from uuid import UUID

import pytest

from src.agents.slo_agent.herdr.dao import HerdrRestoreRecordDAO, HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


@pytest.mark.parametrize("collisions", [0, 1, 2, 3])
def test_three_allocation_attempts(tmp_path: Path, collisions: int) -> None:
    """Each collision consumes one draw; exhaustion never calls the writer."""
    assert tmp_path.resolve() == tmp_path
    root = tmp_path / "restore-v1"
    root.mkdir(mode=0o700)
    values = [UUID(int=number) for number in range(1, 4)]
    for value in values[:collisions]:
        path = root / f"r1-{value.hex}.json"
        path.touch(mode=0o600)
        path.write_bytes(b"retained")
    with patch("src.agents.slo_agent.herdr.restore.uuid4", side_effect=values) as draw:
        with patch.object(
            AtomicFileWriter, "write_text_with_outcome", wraps=AtomicFileWriter.write_text_with_outcome
        ) as writer:
            store = HerdrRestoreStore(state_root=tmp_path)
            if collisions == 3:
                with pytest.raises(HerdrRestoreUnavailableError):
                    store.save(config=config_for(tmp_path))
                writer.assert_not_called()
            else:
                saved = store.save(config=config_for(tmp_path))
                assert saved.restore_reference == f"r1-{values[collisions].hex}"
                assert writer.call_count == 1
        assert draw.call_count == min(collisions + 1, 3)
    for value in values[:collisions]:
        assert (root / f"r1-{value.hex}.json").read_bytes() == b"retained"


@pytest.mark.parametrize("size", [65535, 65536, 65537])
def test_exact_record_bytes(tmp_path: Path, size: int) -> None:
    """Serialized UTF-8 size, not model character count, controls admission."""
    assert tmp_path.resolve() == tmp_path
    config = config_for(tmp_path)
    reference = "r1-" + "a" * 32
    baseline = HerdrRestoreRecordDAO(schema_version=1, restore_reference=reference, config=config)
    extra = size - len(baseline.model_dump_json().encode())
    config = config.model_copy(update={"model_name": config.model_name + "x" * extra})
    store = HerdrRestoreStore(state_root=tmp_path)
    if size > 65536:
        with pytest.raises(HerdrRestoreUnavailableError):
            store.save(config=config)
        assert list((tmp_path / "restore-v1").iterdir()) == []
        return
    saved = store.save(config=config)
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    assert path.stat().st_size == size
    assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config


@pytest.mark.parametrize("projected", [1023, 1024, 1025])
def test_exact_record_count(tmp_path: Path, projected: int) -> None:
    """Corrupt unrecognized regular entries count, including zero-byte orphans."""
    assert tmp_path.resolve() == tmp_path
    root = tmp_path / "restore-v1"
    root.mkdir(mode=0o700)
    for number in range(projected - 1):
        (root / str(number)).touch(mode=0o600)
    store = HerdrRestoreStore(state_root=tmp_path)
    if projected > 1024:
        with pytest.raises(HerdrRestoreUnavailableError):
            store.save(config=config_for(tmp_path))
        assert len(list(root.iterdir())) == projected - 1
    else:
        store.save(config=config_for(tmp_path))
        assert len(list(root.iterdir())) == projected


def test_scan_stops_at_overflow_entry(tmp_path: Path) -> None:
    """Count actual iterator advancement, not merely the final refusal."""
    assert tmp_path.resolve() == tmp_path
    root = tmp_path / "restore-v1"
    root.mkdir(mode=0o700)
    for number in range(1030):
        (root / str(number)).touch(mode=0o600)
    original = os.scandir
    inspected: list[str] = []

    @contextmanager
    def scan(path: Path) -> Iterator[Iterator[os.DirEntry[str]]]:
        """Wrap the real directory iterator without eagerly consuming it."""
        with original(path) as entries:

            def counted() -> Iterator[os.DirEntry[str]]:
                """Observe each actual next call made by the store."""
                for entry in entries:
                    inspected.append(entry.name)
                    yield entry

            yield counted()

    with patch("src.agents.slo_agent.herdr.restore.os.scandir", side_effect=scan):
        with pytest.raises(HerdrRestoreUnavailableError):
            HerdrRestoreStore(state_root=tmp_path).save(config=config_for(tmp_path))
    assert len(inspected) == 1025
    assert len(list(root.iterdir())) == 1030


@pytest.mark.parametrize("size", [65535, 65536, 65537])
def test_independently_padded_load(tmp_path: Path, size: int) -> None:
    """Load quota counts trailing JSON whitespace as physical bytes."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    content = path.read_bytes()
    path.write_bytes(content + b" " * (size - len(content)))
    if size > 65536:
        with pytest.raises(HerdrRestoreUnavailableError):
            store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
    else:
        assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
            tmp_path
        )
    assert path.stat().st_size == size


@pytest.mark.parametrize("projected", [67108863, 67108864, 67108865])
def test_exact_total_bytes(tmp_path: Path, projected: int) -> None:
    """Sparse corrupt regular bytes participate in the exact projected quota."""
    assert tmp_path.resolve() == tmp_path
    root = tmp_path / "restore-v1"
    root.mkdir(mode=0o700)
    config = config_for(tmp_path)
    record = HerdrRestoreRecordDAO(schema_version=1, restore_reference="r1-" + "a" * 32, config=config)
    orphan = root / "orphan"
    orphan.touch(mode=0o600)
    with orphan.open("wb") as stream:
        stream.truncate(projected - len(record.model_dump_json().encode()))
    store = HerdrRestoreStore(state_root=tmp_path)
    if projected > 67108864:
        with pytest.raises(HerdrRestoreUnavailableError):
            store.save(config=config)
        assert list(root.iterdir()) == [orphan]
    else:
        store.save(config=config)
        assert sum(path.stat().st_size for path in root.iterdir()) == projected
