"""Skill registry — dev-time helper for managing the committed skills tree.

This module is **not invoked at runtime**. It recursively discovers authored
``SKILL.md`` files to generate the grouped ``skills/INDEX.md``. Runtime manifest
loading is owned separately by ``SkillsLoader``; agents read selected skill
bodies on demand.

The authored skills tree is the source of truth; ``INDEX.md`` is derived.
Both ``scripts/build_skill_index.py`` and ``scripts/refresh_skills.py`` use
this registry through the same index builder without rewriting skill content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Skill", "SkillRegistry"]


SkillKind = Literal["skill", "workflow"]

_FRONTMATTER_RE = re.compile(
    r"\A[ \t]*---\s*\n(?P<body>.*?)\n[ \t]*---\s*\n",
    re.DOTALL,
)
_GROUP_ORDER: tuple[str, ...] = (
    "orientation",
    "engineering",
    "languages",
    "design-and-analysis",
    "coding",
    "git-ops",
    "cli",
    "tui",
    "integration-tests",
    "frontend-vue",
    "presentation",
    "user-content",
)
_GROUP_TITLES: dict[str, str] = {
    "orientation": "Orientation",
    "engineering": "Shared Engineering",
    "languages": "Language Conventions and Recipes",
    "design-and-analysis": "Design and Analysis",
    "coding": "Coding",
    "git-ops": "Git Ops",
    "cli": "CLI",
    "tui": "TUI",
    "integration-tests": "Integration Tests",
    "frontend-vue": "Frontend / Vue",
    "presentation": "Presentation",
    "user-content": "User Content",
}
_KIND_TITLES: dict[SkillKind, str] = {
    "workflow": "Workflows",
    "skill": "Individual Skills",
}


class Skill(BaseModel):
    """One committed skill — frontmatter + location parsed from a ``SKILL.md`` file."""

    name: str = Field(description="Slug used in skills/<group>/<name>/SKILL.md")
    description: str = Field(description="Short summary of what the skill covers.")
    when_to_use: str = Field(description="Explicit routing hint for when the skill applies.")
    group: str = Field(description="Logical group shown in the generated index.")
    kind: SkillKind = Field(description="Whether this entry is a workflow or an individual skill.")
    location: str = Field(description="Repo-relative path to SKILL.md")

    model_config = ConfigDict(title="Skill", extra="ignore", from_attributes=True)


class SkillRegistry:
    """Load and format committed skills for the dev-time INDEX regenerator.

    Used only by ``scripts/build_skill_index.py``; never imported at runtime.
    """

    @classmethod
    def load(cls, *, skills_dir: Path) -> list[Skill]:
        """Scan ``skills_dir/**/SKILL.md`` files and return parsed ``Skill`` entries.

        Args:
            skills_dir: Absolute path to the committed ``skills/`` directory.

        Returns:
            A sorted list of valid ``Skill`` entries. Files with invalid or
            missing frontmatter are skipped silently — the regenerator script
            logs the skip count separately if needed.
        """
        results: list[Skill] = []
        if not skills_dir.is_dir():
            return results

        skill_files: list[Path] = sorted(path for path in skills_dir.rglob("SKILL.md") if path.is_file())
        for skill_file in skill_files:
            parsed = cls._parse_skill_file(
                path=skill_file,
                skills_dir=skills_dir,
            )
            if parsed is not None:
                results.append(parsed)
        return sorted(
            results,
            key=lambda skill: (
                0 if skill.kind == "workflow" else 1,
                cls._group_sort_key(group=skill.group),
                skill.name,
            ),
        )

    @classmethod
    def format_for_prompt(cls, *, skills: list[Skill]) -> str:
        """Render the grouped human-readable index body for ``skills/INDEX.md``.

        Each skill is rendered on one bullet line so the runtime ``read`` tool
        can scan the file efficiently while still surfacing the route-selection
        hints (`description`, `when_to_use`) and the concrete ``SKILL.md`` path.

        Args:
            skills: Skills to render, in the order they should appear.

        Returns:
            Grouped Markdown, terminated by a trailing newline.
        """
        if not skills:
            return "\n"

        sections: list[str] = []
        for kind in ("workflow", "skill"):
            kind_skills = [skill for skill in skills if skill.kind == kind]
            if not kind_skills:
                continue

            sections.append(f"## {cls._kind_title_for(kind=kind)}")
            sections.append("")
            for group in cls._groups_for(skills=kind_skills):
                group_skills = [skill for skill in kind_skills if skill.group == group]
                sections.append(f"### {cls._group_title_for(group=group)}")
                for skill in group_skills:
                    description = " ".join(skill.description.split())
                    when_to_use = " ".join(skill.when_to_use.split())
                    sections.append(
                        f"- **{skill.name}** — {description} When to use: {when_to_use} "
                        f"Path: `{skill.location}`"
                    )
                sections.append("")

        return "\n".join(sections).rstrip() + "\n"

    @classmethod
    def _parse_skill_file(
        cls,
        *,
        path: Path,
        skills_dir: Path,
    ) -> Optional[Skill]:
        """Parse the YAML frontmatter of one ``SKILL.md`` into a ``Skill``.

        Args:
            path: Absolute path to the ``SKILL.md`` file.
            skills_dir: The root skills directory; used to compute the
                ``location`` field as a repo-relative path.

        Returns:
            A ``Skill`` instance, or ``None`` if frontmatter is missing,
            malformed, or lacks the required metadata keys.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        frontmatter_match = _FRONTMATTER_RE.search(text)
        if frontmatter_match is None:
            return None

        frontmatter = frontmatter_match.group("body")
        try:
            data = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return None

        if not isinstance(data, dict):
            return None

        name = cls._string_field(data=data, key="name")
        description = cls._string_field(data=data, key="description")
        when_to_use = cls._string_field(data=data, key="when_to_use")
        group = cls._string_field(data=data, key="group") or "coding"
        kind_value = cls._string_field(data=data, key="kind") or "skill"
        if kind_value not in {"skill", "workflow"}:
            kind_value = "skill"

        if not name or not description or not when_to_use:
            return None

        location = cls._location_for(path=path, skills_dir=skills_dir)
        return Skill(
            name=name,
            description=description,
            when_to_use=when_to_use,
            group=group,
            kind=kind_value,
            location=location,
        )

    @classmethod
    def _string_field(cls, *, data: dict[object, object], key: str) -> str:
        """Return ``data[key]`` as a normalized string or ``""`` when absent.

        Args:
            data: Parsed frontmatter mapping.
            key: Field name to extract.

        Returns:
            Collapsed string value, or ``""`` when the field is missing or blank.
        """
        value = data.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return " ".join(value.split())

    @classmethod
    def _groups_for(cls, *, skills: list[Skill]) -> list[str]:
        """Return group names ordered by the registry's preferred display order."""
        unique_groups = {skill.group for skill in skills}
        return sorted(unique_groups, key=lambda group: cls._group_sort_key(group=group))

    @classmethod
    def _group_sort_key(cls, *, group: str) -> tuple[int, str]:
        """Return a stable sort key for a skill group."""
        try:
            return (_GROUP_ORDER.index(group), group)
        except ValueError:
            return (len(_GROUP_ORDER), group)

    @classmethod
    def _group_title_for(cls, *, group: str) -> str:
        """Humanize a group slug for the rendered index heading."""
        return _GROUP_TITLES.get(group, group.replace("-", " ").title())

    @classmethod
    def _kind_title_for(cls, *, kind: SkillKind) -> str:
        """Return the section title for a skill kind."""
        return _KIND_TITLES[kind]

    @classmethod
    def _location_for(cls, *, path: Path, skills_dir: Path) -> str:
        """Return the repo-relative path to ``SKILL.md`` for the index entry.

        The location is anchored at the parent of ``skills_dir`` so the
        rendered path reads ``skills/<group>/<name>/SKILL.md`` for the standard layout.
        """
        try:
            return str(path.relative_to(skills_dir.parent))
        except ValueError:
            return str(path)
