"""Refresh the index from the current authored skills tree.

Run ``make refresh-skills`` after editing ``skills/**/SKILL.md``. The tree is
source of truth: this command delegates to the index builder and never imports
upstream prompts, rewrites skill bodies, or removes resources. Language,
workflow, presentation and other families are discovered recursively.
"""

from __future__ import annotations

from scripts import build_skill_index


def main() -> int:
    """Rebuild the current tree's index using the shared index entry point.

    Returns:
        int: The index builder's exit status; zero indicates success.
    """
    return build_skill_index.main()


if __name__ == "__main__":
    raise SystemExit(main())
