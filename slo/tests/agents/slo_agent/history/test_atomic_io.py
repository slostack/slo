"""Tests for the shared atomic durable-file writer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter


class _ExampleDAO(BaseModel):
    """Small serializable model used by atomic writer tests."""

    name: str


def test_write_text_creates_and_replaces(tmp_path: Path) -> None:
    """Write text creates parents and replaces an existing destination."""
    path: Path = tmp_path / "nested" / "state.txt"
    path.parent.mkdir(parents=True)
    path.write_text("old", encoding="utf-8")

    AtomicFileWriter.write_text(path=path, text="new")

    assert path.read_text(encoding="utf-8") == "new"
    assert not list(path.parent.glob("*.tmp"))


def test_write_text_applies_private_modes(tmp_path: Path) -> None:
    """Private writes normalize the destination directory and file modes."""
    path: Path = tmp_path / "private" / "state.txt"

    AtomicFileWriter.write_text(path=path, text="state", private=True)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_write_text_non_private_leaves_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-private writes do not normalize destination modes."""
    path: Path = tmp_path / "public" / "state.txt"
    chmod_calls: list[tuple[Path, int]] = []
    original_chmod = Path.chmod

    def record_chmod(self: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        """Record mode normalization without changing Path chmod behavior."""
        chmod_calls.append((self, mode))
        original_chmod(self, mode, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "chmod", record_chmod)

    AtomicFileWriter.write_text(path=path, text="state", private=False)

    assert chmod_calls == []


def test_write_json_round_trip(tmp_path: Path) -> None:
    """JSON writes serialize an indented Pydantic model."""
    path: Path = tmp_path / "state.json"

    AtomicFileWriter.write_json(path=path, model=_ExampleDAO(name="slo"))

    assert path.read_text(encoding="utf-8") == '{\n  "name": "slo"\n}'


def test_write_text_raises_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Filesystem failures propagate to the durable-state owner."""
    path: Path = tmp_path / "state.txt"

    def raise_replace(*, src: str, dst: Path) -> None:
        """Raise the simulated named-argument replacement failure."""
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", raise_replace)

    with pytest.raises(OSError, match="replace failed"):
        AtomicFileWriter.write_text(path=path, text="state")
