"""SkillsLoader — scan a skills directory tree and return parsed SkillEntryDAO objects.

Scans a skills directory tree for ``SKILL.md`` files, parses their YAML
frontmatter, and returns ``SkillEntryDAO`` objects that the system-prompt
builder can render as a structured ``<available_skills>`` XML block.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from config.logger import log_error, log_info
from src.agents.slo_agent.skills.dao import SkillEntryDAO

__all__ = ["SkillsLoader"]


class SkillsLoader:
    """Scan a skills directory tree and return parsed SkillEntryDAO objects.

    Discovery:
    - Walks SKILLS_DIR recursively looking for SKILL.md files.
    - Parses YAML frontmatter (name, description, disable-model-invocation).
    - Falls back to parent directory name when frontmatter.name is absent.
    - Skips skills whose frontmatter lacks description (logs a warning).
    - Skips skills with disable-model-invocation: true (they are slash-only).
    """

    @classmethod
    def load(cls, *, skills_dir: str) -> list[SkillEntryDAO]:
        """Load all invocable skills from skills_dir.

        Args:
            skills_dir (str): Absolute path to the skills root directory.

        Returns:
            list[SkillEntryDAO]: Parsed, invocation-eligible skills in
                filesystem order. Empty list when skills_dir does not exist.
        """
        skills_path = Path(skills_dir)
        if not skills_path.is_dir():
            log_info(
                msg="SkillsLoader: skills_dir not found, returning empty list",
                skills_dir=skills_dir,
            )
            return []
        skill_files: list[Path] = sorted(skills_path.rglob("SKILL.md"))
        results: list[SkillEntryDAO] = []
        for skill_file in skill_files:
            entry: Optional[SkillEntryDAO] = cls._parse_skill_file(skill_file=skill_file)
            if entry is not None:
                results.append(entry)
        log_info(
            msg="SkillsLoader: loaded skills",
            count=len(results),
            skills_dir=skills_dir,
        )
        return results

    @classmethod
    def load_merged(
        cls,
        *,
        vendored_skills_dir: str,
        user_skills_dir: str,
        user_workflows_dir: str,
    ) -> list[SkillEntryDAO]:
        """Merge vendored skills with user-defined skills and workflows.

        Loads from three source directories and produces a single deduplicated
        list. User entries with the same ``name`` frontmatter field as a
        vendored entry take precedence — the vendored entry is replaced in the
        result. Vendored files on disk are not modified. Directory absence is
        not an error: ``load`` returns ``[]`` for a non-existent directory.

        Override events are logged individually so operators can audit which
        vendored skills were displaced at session start.

        Args:
            vendored_skills_dir (str): Absolute path to the installed vendored
                skills root (typically ``SKILLS_DIR`` from ``config.cfg``).
            user_skills_dir (str): Absolute path to the user skills directory
                (typically ``~/.slo/user_skills``). May not exist.
            user_workflows_dir (str): Absolute path to the user workflows
                directory (typically ``~/.slo/user_workflows``). May not exist.

        Returns:
            list[SkillEntryDAO]: Merged, deduplicated entries. Vendored entries
                that were not overridden appear first in their original
                filesystem order. Overridden positions hold the user entry.
                User-only additions are appended in load order.
        """
        vendored: list[SkillEntryDAO] = cls.load(skills_dir=vendored_skills_dir)
        user_skills: list[SkillEntryDAO] = cls.load(skills_dir=user_skills_dir)
        user_workflows: list[SkillEntryDAO] = cls.load(skills_dir=user_workflows_dir)

        merged: dict[str, SkillEntryDAO] = {entry.name: entry for entry in vendored}

        user_entry: SkillEntryDAO
        for user_entry in user_skills + user_workflows:
            if user_entry.name in merged:
                log_info(
                    msg="SkillsLoader: user skill overrides vendored skill",
                    skill_name=user_entry.name,
                    vendored_path=merged[user_entry.name].file_path,
                    user_path=user_entry.file_path,
                )
            merged[user_entry.name] = user_entry

        cls._warn_when_no_vendored_skills(
            vendored=vendored,
            vendored_skills_dir=vendored_skills_dir,
        )
        log_info(
            msg="SkillsLoader.load_merged: complete",
            vendored_count=len(vendored),
            user_skills_count=len(user_skills),
            user_workflows_count=len(user_workflows),
            total_count=len(merged),
        )
        return list(merged.values())

    @classmethod
    def _warn_when_no_vendored_skills(
        cls,
        *,
        vendored: list[SkillEntryDAO],
        vendored_skills_dir: str,
    ) -> None:
        """Log an error when the vendored skills tree resolved to nothing.

        An agent with zero vendored skills still runs — it just silently loses
        every workflow and convention skill, which reads as the model making
        bad choices rather than as a packaging fault. This is the loud signal
        that distinguishes the two.

        Args:
            vendored (list[SkillEntryDAO]): Entries loaded from the vendored tree.
            vendored_skills_dir (str): The directory that was searched.
        """
        if vendored:
            return
        log_error(
            msg=(
                "SkillsLoader: no vendored skills found at "
                f"{vendored_skills_dir!r} — the agent is running without any "
                "vendored skill or workflow. Check that skills/ shipped with "
                "the install, or set SLO_SKILLS_DIR."
            ),
            stack_trace=False,
            vendored_skills_dir=vendored_skills_dir,
        )

    @classmethod
    def _parse_skill_file(cls, *, skill_file: Path) -> Optional[SkillEntryDAO]:
        """Parse one SKILL.md file and return a SkillEntryDAO or None.

        Args:
            skill_file (Path): Absolute path to the SKILL.md file.

        Returns:
            Optional[SkillEntryDAO]: Parsed entry, or None on missing
                description or YAML error.
        """
        try:
            raw: str = skill_file.read_text(encoding="utf-8")
            frontmatter: dict = cls._extract_frontmatter(raw=raw)
            description: Optional[str] = frontmatter.get("description")
            if not description or not description.strip():
                log_info(
                    msg="SkillsLoader: skipping skill with no description",
                    path=str(skill_file),
                )
                return None
            if frontmatter.get("disable-model-invocation") is True:
                return None
            name: str = str(frontmatter.get("name") or skill_file.parent.name)
            return SkillEntryDAO(
                name=name,
                description=description.strip(),
                file_path=str(skill_file),
                disable_model_invocation=False,
            )
        except Exception as exc:
            log_error(
                msg="SkillsLoader: failed to parse skill file",
                path=str(skill_file),
                e=exc,
                stack_trace=False,
            )
            return None

    @classmethod
    def _extract_frontmatter(cls, *, raw: str) -> dict:
        """Extract and parse YAML frontmatter from a markdown file.

        Args:
            raw (str): Raw file contents, possibly starting with ---...---
                frontmatter.

        Returns:
            dict: Parsed frontmatter keys, or empty dict when no frontmatter
                is present or when the block does not parse to a mapping.
        """
        if not raw.startswith("---"):
            return {}
        end_index: int = raw.find("---", 3)
        if end_index == -1:
            return {}
        yaml_block: str = raw[3:end_index].strip()
        parsed = yaml.safe_load(yaml_block)
        return parsed if isinstance(parsed, dict) else {}
