"""File-per-schedule on-disk store under ``~/.slo/schedules``."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from config.cfg import SLO_HOME as _CFG_SLO_HOME, cfg as _cfg
from config.logger import log_info
from src.scheduling.dao import (
    LoadedScheduleDAO,
    ScheduleDefinitionDAO,
    ScheduleRunRecordDAO,
    ScheduleStateDAO,
)
from src.scheduling.exceptions import ScheduleNotFoundError, ScheduleStoreCorruptError

__all__ = ["ScheduleStore"]

_FRONTMATTER_RE: re.Pattern[str] = re.compile(
    r"\A[ \t]*---\s*\n(?P<body>.*?)\n[ \t]*---\s*\n",
    re.DOTALL,
)


class ScheduleStore:
    """File-per-schedule reader/writer under ``~/.slo/schedules/<schedule_id>/``."""

    _DIR_MODE: int = 0o700
    _FILE_MODE: int = 0o600

    @classmethod
    def _schedules_root(cls) -> Path:
        """Resolve the schedules root directory.

        Checks ``SLO_SCHEDULES_DIR`` first, then falls back to
        ``$SLO_HOME/schedules``.

        Returns:
            Path: The schedules root, not guaranteed to exist yet.
        """
        schedules_dir: str | None = _cfg("SLO_SCHEDULES_DIR")
        if schedules_dir:
            return Path(schedules_dir)
        return _CFG_SLO_HOME / "schedules"

    @classmethod
    def directory_for(cls, *, schedule_id: str) -> Path:
        """Return the directory path for one schedule.

        Args:
            schedule_id (str): The schedule's stable identifier.

        Returns:
            Path: ``$SLO_HOME/schedules/<schedule_id>``.
        """
        return cls._schedules_root() / schedule_id

    @classmethod
    def _schedule_dir(cls, *, schedule_id: str) -> Path:
        """Return the internal directory path for one schedule.

        Args:
            schedule_id (str): The schedule's stable identifier.

        Returns:
            Path: Schedule directory path.
        """
        return cls.directory_for(schedule_id=schedule_id)

    @classmethod
    def _ensure_dir(cls, *, path: Path) -> None:
        """Create a directory with ``0700`` mode or re-chmod an existing one.

        Args:
            path (Path): Directory to ensure.
        """
        if not path.exists():
            path.mkdir(parents=True, mode=cls._DIR_MODE)
            return
        path.chmod(cls._DIR_MODE)

    @classmethod
    def _render_schedule_md(cls, *, definition: ScheduleDefinitionDAO) -> str:
        """Serialise a definition to YAML frontmatter plus markdown prompt body.

        Args:
            definition (ScheduleDefinitionDAO): Definition to render.

        Returns:
            str: Full ``schedule.md`` text.
        """
        data: dict[str, object] = definition.model_dump(mode="json", exclude={"prompt"})
        frontmatter: str = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        return f"---\n{frontmatter}---\n\n{definition.prompt.strip()}\n"

    @classmethod
    def _parse_schedule_md(cls, *, path: Path, text: str) -> ScheduleDefinitionDAO:
        """Parse ``schedule.md`` text into a definition DAO.

        Args:
            path (Path): Source file path for error context.
            text (str): Full file contents.

        Returns:
            ScheduleDefinitionDAO: Parsed schedule definition.

        Raises:
            ScheduleStoreCorruptError: When frontmatter is missing or invalid.
        """
        match: Optional[re.Match[str]] = _FRONTMATTER_RE.search(text)
        if match is None:
            raise ScheduleStoreCorruptError(path=path)

        try:
            frontmatter_payload: object = yaml.safe_load(match.group("body")) or {}
        except yaml.YAMLError as exc:
            raise ScheduleStoreCorruptError(path=path) from exc

        if not isinstance(frontmatter_payload, dict):
            raise ScheduleStoreCorruptError(path=path)

        data: dict[str, object] = dict(frontmatter_payload)
        data["prompt"] = text[match.end() :].strip()
        try:
            return ScheduleDefinitionDAO.model_validate(data)
        except ValidationError as exc:
            raise ScheduleStoreCorruptError(path=path) from exc

    @staticmethod
    def normalize_name_key(*, name: str) -> str:
        """Normalise a schedule name to a case-insensitive lookup key.

        Args:
            name (str): Human-facing schedule name.

        Returns:
            str: Lower-cased, whitespace-collapsed hyphenated name.
        """
        collapsed: str = re.sub(r"\s+", "-", name.strip().lower())
        return re.sub(r"-{2,}", "-", collapsed)

    @classmethod
    def _atomic_write_text(cls, *, path: Path, text: str) -> None:
        """Atomically write UTF-8 text to ``path`` with ``0600`` permissions.

        Args:
            path (Path): Destination file path.
            text (str): Text content to write.
        """
        cls._ensure_dir(path=path.parent)
        tmp: Path = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(cls._FILE_MODE)
        tmp.replace(path)

    @classmethod
    def _schedule_md_path(cls, *, schedule_id: str) -> Path:
        """Return the ``schedule.md`` path for a schedule.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            Path: The schedule definition file path.
        """
        return cls._schedule_dir(schedule_id=schedule_id) / "schedule.md"

    @classmethod
    def _state_path(cls, *, schedule_id: str) -> Path:
        """Return the ``state.json`` path for a schedule.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            Path: The schedule state file path.
        """
        return cls._schedule_dir(schedule_id=schedule_id) / "state.json"

    @classmethod
    def _write_definition(cls, *, definition: ScheduleDefinitionDAO) -> None:
        """Persist ``schedule.md`` for one definition.

        Args:
            definition (ScheduleDefinitionDAO): Definition to write.
        """
        cls._atomic_write_text(
            path=cls._schedule_md_path(schedule_id=definition.schedule_id),
            text=cls._render_schedule_md(definition=definition),
        )

    @classmethod
    def _write_state(cls, *, schedule_id: str, state: ScheduleStateDAO) -> None:
        """Persist ``state.json`` for one schedule.

        Args:
            schedule_id (str): Schedule identifier.
            state (ScheduleStateDAO): State to persist.
        """
        cls._atomic_write_text(
            path=cls._state_path(schedule_id=schedule_id),
            text=state.model_dump_json(indent=2),
        )

    @classmethod
    def _load_definition(cls, *, schedule_id: str) -> ScheduleDefinitionDAO:
        """Load and parse ``schedule.md`` for one schedule.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            ScheduleDefinitionDAO: Parsed definition.

        Raises:
            ScheduleStoreCorruptError: When the definition file cannot be read or parsed.
        """
        path: Path = cls._schedule_md_path(schedule_id=schedule_id)
        try:
            text: str = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ScheduleStoreCorruptError(path=path) from exc
        return cls._parse_schedule_md(path=path, text=text)

    @classmethod
    def _load_state(cls, *, directory: Path) -> ScheduleStateDAO:
        """Load ``state.json`` for one schedule.

        Args:
            directory (Path): Schedule directory.

        Returns:
            ScheduleStateDAO: Persisted state, or the default empty state when absent.

        Raises:
            ScheduleStoreCorruptError: When ``state.json`` exists but is unreadable or invalid.
        """
        state_path: Path = directory / "state.json"
        if not state_path.exists():
            return ScheduleStateDAO()

        try:
            payload: str = state_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ScheduleStoreCorruptError(path=state_path) from exc

        try:
            return ScheduleStateDAO.model_validate_json(payload)
        except ValidationError as exc:
            raise ScheduleStoreCorruptError(path=state_path) from exc

    @classmethod
    def create(
        cls,
        *,
        definition: ScheduleDefinitionDAO,
        initial_next_run_at: Optional[datetime],
    ) -> ScheduleDefinitionDAO:
        """Persist a new schedule and its initial state.

        Args:
            definition (ScheduleDefinitionDAO): Fully-built schedule definition.
            initial_next_run_at (Optional[datetime]): First fire instant, or ``None`` for terminal schedules.

        Returns:
            ScheduleDefinitionDAO: The stored definition.
        """
        directory: Path = cls._schedule_dir(schedule_id=definition.schedule_id)
        cls._ensure_dir(path=directory)
        cls._ensure_dir(path=directory / "runs")
        cls._write_definition(definition=definition)
        cls._write_state(
            schedule_id=definition.schedule_id,
            state=ScheduleStateDAO(next_run_at=initial_next_run_at),
        )
        return definition

    @classmethod
    def load(cls, *, reference: str) -> LoadedScheduleDAO:
        """Load one schedule by schedule id or normalised name.

        Args:
            reference (str): Schedule identifier or name.

        Returns:
            LoadedScheduleDAO: The loaded schedule triple.

        Raises:
            ScheduleNotFoundError: When nothing matches ``reference``.
            ScheduleStoreCorruptError: When a matched schedule cannot be parsed.
        """
        schedule_id: str = cls.resolve_reference(reference=reference)
        directory: Path = cls._schedule_dir(schedule_id=schedule_id)
        definition: ScheduleDefinitionDAO = cls._load_definition(schedule_id=schedule_id)
        state: ScheduleStateDAO = cls._load_state(directory=directory)
        return LoadedScheduleDAO(schedule_id=schedule_id, definition=definition, state=state)

    @classmethod
    def load_all(cls) -> list[LoadedScheduleDAO]:
        """Load every parseable schedule and skip malformed entries.

        Returns:
            list[LoadedScheduleDAO]: All valid schedules currently on disk.
        """
        root: Path = cls._schedules_root()
        if not root.exists():
            return []

        results: list[LoadedScheduleDAO] = []
        for md_path in sorted(root.glob("*/schedule.md")):
            schedule_id: str = md_path.parent.name
            try:
                definition: ScheduleDefinitionDAO = cls._load_definition(schedule_id=schedule_id)
                state: ScheduleStateDAO = cls._load_state(directory=md_path.parent)
            except (ScheduleStoreCorruptError, ValidationError, OSError) as exc:
                log_info(msg="schedule_skipped_malformed", path=str(md_path), reason=str(exc))
                continue
            results.append(
                LoadedScheduleDAO(
                    schedule_id=schedule_id,
                    definition=definition,
                    state=state,
                )
            )
        return results

    @classmethod
    def update_state(cls, *, schedule_id: str, state: ScheduleStateDAO) -> None:
        """Atomically rewrite ``state.json`` only.

        Args:
            schedule_id (str): Schedule identifier.
            state (ScheduleStateDAO): Replacement state.
        """
        cls._write_state(schedule_id=schedule_id, state=state)

    @classmethod
    def set_enabled(cls, *, schedule_id: str, enabled: bool) -> ScheduleDefinitionDAO:
        """Flip the ``enabled`` flag by rewriting only ``schedule.md``.

        Args:
            schedule_id (str): Schedule identifier.
            enabled (bool): Desired enabled state.

        Returns:
            ScheduleDefinitionDAO: Updated definition.
        """
        current: ScheduleDefinitionDAO = cls._load_definition(schedule_id=schedule_id)
        updated: ScheduleDefinitionDAO = current.model_copy(update={"enabled": enabled})
        cls._write_definition(definition=updated)
        return updated

    @classmethod
    def delete(cls, *, schedule_id: str) -> bool:
        """Recursively remove a schedule directory.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            bool: ``True`` when the directory existed, else ``False``.
        """
        directory: Path = cls._schedule_dir(schedule_id=schedule_id)
        if not directory.exists():
            return False
        shutil.rmtree(path=directory)
        return True

    @classmethod
    def resolve_reference(cls, *, reference: str) -> str:
        """Resolve a schedule id or schedule name to a schedule id.

        Args:
            reference (str): Candidate schedule id or human-facing name.

        Returns:
            str: Resolved schedule id.

        Raises:
            ScheduleNotFoundError: When no schedule matches.
        """
        if cls._schedule_dir(schedule_id=reference).exists():
            return reference

        wanted: str = cls.normalize_name_key(name=reference)
        for loaded in cls.load_all():
            if loaded.definition.name_key == wanted:
                return loaded.schedule_id

        raise ScheduleNotFoundError(reference=reference)

    @classmethod
    def append_run_record(cls, *, schedule_id: str, record: ScheduleRunRecordDAO) -> None:
        """Persist one immutable run record under ``runs/<run_id>.json``.

        Args:
            schedule_id (str): Parent schedule identifier.
            record (ScheduleRunRecordDAO): Run record to append.
        """
        directory: Path = cls._schedule_dir(schedule_id=schedule_id) / "runs"
        cls._ensure_dir(path=directory)
        cls._atomic_write_text(
            path=directory / f"{record.run_id}.json",
            text=record.model_dump_json(indent=2),
        )

    @classmethod
    def touch_last_tick(cls, *, moment: datetime) -> None:
        """Record the scheduler's last tick moment.

        Args:
            moment (datetime): Time the current tick began.
        """
        root: Path = cls._schedules_root()
        cls._ensure_dir(path=root)
        cls._atomic_write_text(path=root / ".last_tick", text=moment.isoformat())
