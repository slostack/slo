"""Atomic durable-file writer shared by orchestration state owners.

Sub-spec 71.a.0.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

__all__ = ["AtomicFileWriter", "AtomicWriteOutcomeDAO"]

_FILE_MODE: int = 0o600
_DIR_MODE: int = 0o700


class AtomicWriteOutcomeDAO(BaseModel):
    """Describe whether an atomic write became visible on disk."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    committed: bool
    durability_warning: bool = False


class AtomicFileWriter:
    """Write complete durable-state files through a temporary sibling."""

    @classmethod
    def write_text(cls, *, path: Path, text: str, private: bool = True) -> None:
        """Atomically write complete text to a destination file.

        Args:
            path (Path): Final destination path.
            text (str): Complete text content to persist.
            private (bool): Apply private directory and file modes when True.

        Raises:
            OSError: If creation, writing, or replacement fails before commit.
        """
        cls.write_text_with_outcome(path=path, text=text, private=private)

    @classmethod
    def write_text_with_outcome(
        cls,
        *,
        path: Path,
        text: str,
        private: bool = True,
    ) -> AtomicWriteOutcomeDAO:
        """Write text with a truthful post-replace durability outcome.

        Args:
            path (Path): Final destination path.
            text (str): Complete text content to persist.
            private (bool): Apply private directory and file modes when True.

        Returns:
            AtomicWriteOutcomeDAO: Whether replacement committed and whether
                directory durability could not be confirmed.

        Raises:
            OSError: If the write fails before replacement commits.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if private:
            path.parent.chmod(_DIR_MODE)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, delete=False, mode="w", encoding="utf-8"
            ) as tmp:
                temporary_path = Path(tmp.name)
                if private:
                    os.chmod(temporary_path, _FILE_MODE)
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(src=temporary_path, dst=path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        try:
            directory_fd: int = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            return AtomicWriteOutcomeDAO(committed=True, durability_warning=True)
        return AtomicWriteOutcomeDAO(committed=True)

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
