"""SkillEntryDAO — parsed metadata for one skill sourced from SKILL.md frontmatter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["SkillEntryDAO"]


class SkillEntryDAO(BaseModel):
    """Parsed metadata for one skill, sourced from SKILL.md frontmatter.

    Attributes:
        name (str): Canonical skill identifier (e.g. ``build-routers``).
        description (str): One-line description used in the XML manifest.
        file_path (str): Absolute path to the SKILL.md file.
        disable_model_invocation (bool): True when the skill is slash-only
            and must not be shown in the XML block. Always False for entries
            returned by ``SkillsLoader.load``.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    file_path: str
    disable_model_invocation: bool = False
