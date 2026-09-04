"""Atomic durable-file writer shared by orchestration state owners.

Sub-spec 71.a.0.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

__all__ = ["AtomicFileWriter"]

_FILE_MODE: int = 0o600
_DIR_MODE: int = 0o700


class AtomicFileWriter:
    """Write complete durable-state files through a temporary sibling."""

    @classmethod
    def write_text(cls, *, path: Path, text: str, private: bool = True) -> None:
        """Atomically write complete text to a destination file.

        WHAT: Creates the destination parent, writes a temporary sibling, then
            replaces the destination so readers cannot observe partial text.
        WHO: Called by durable-state owners such as workflow and fleet stores.
        WHEN: On each durable state transition.

        Args:
            path (Path): Final destination path.
            text (str): Complete text content to persist.
            private (bool): Apply private directory and file modes when True.

        Raises:
            OSError: If filesystem creation, writing, replacement, or chmod fails.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if private:
            path.parent.chmod(_DIR_MODE)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(text)
            temporary_path: str = tmp.name
        os.replace(src=temporary_path, dst=path)
        if private:
            path.chmod(_FILE_MODE)

    @classmethod
    def write_json(cls, *, path: Path, model: BaseModel, private: bool = True) -> None:
        """Serialize a Pydantic model and atomically write its JSON.

        WHAT: Converts the complete model into indented JSON and delegates its
            atomic replacement to write_text.
        WHO: Called by durable-state owners persisting Pydantic records.
        WHEN: When a state transition has a model-shaped payload.

        Args:
            path (Path): Final JSON destination.
            model (BaseModel): Model to serialize.
            private (bool): Apply private directory and file modes when True.

        Raises:
            OSError: If the delegated durable write fails.
        """
        cls.write_text(path=path, text=model.model_dump_json(indent=2), private=private)
