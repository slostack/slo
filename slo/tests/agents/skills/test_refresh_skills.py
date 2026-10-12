"""Refresh the current skill tree without importing or rewriting guidance."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import build_skill_index, refresh_skills

ROOT = Path(__file__).resolve().parents[3]


def _write(*, root: Path, relative: str, text: str) -> Path:
    """Write only within the resolved temporary fixture root."""
    path = root / relative
    assert path.resolve().is_relative_to(root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skill(*, root: Path, relative: str, name: str, group: str) -> None:
    """Create a skill in a current language or non-code family."""
    _write(
        root=root,
        relative=f"skills/{relative}/SKILL.md",
        text=(
            f"---\nname: {name}\ndescription: Guidance for {name}.\n"
            f"when_to_use: Use for {name}.\ngroup: {group}\nkind: skill\n---\n"
            "# Authored guidance\n\nKeep this content unchanged.\n"
        ),
    )


def _tree(*, root: Path) -> Path:
    """Build a representative tree including non-SKILL resources."""
    _skill(root=root, relative="languages/go/go-conventions", name="go-conventions", group="languages")
    _skill(root=root, relative="engineering/testing", name="testing", group="engineering")
    _skill(root=root, relative="presentation/pdf", name="pdf", group="presentation")
    _write(root=root, relative="skills/presentation/pdf/assets/style.css", text="body { color: navy; }\n")
    _write(root=root, relative="skills/design-and-analysis/workflows/example.md", text="# Pipeline\n")
    _write(root=root, relative="skills/samples/example.md", text="# Sample\n")
    return root / "skills"


def _snapshot(*, root: Path) -> dict[str, bytes]:
    """Read authored files, excluding the generated index."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "INDEX.md"
    }


def test_refresh_preserves_current_tree_and_ignores_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = _tree(root=tmp_path)
    before = _snapshot(root=skills)
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: skills)
    monkeypatch.setenv("SLO_CODE_PROMPTS_DIR", str(tmp_path / "nonexistent-upstream"))
    monkeypatch.setenv("SLO_SKILLS_DIR", str(tmp_path / "unrelated-install"))

    assert refresh_skills.main() == 0
    first = (skills / "INDEX.md").read_bytes()
    assert refresh_skills.main() == 0
    assert (skills / "INDEX.md").read_bytes() == first
    assert _snapshot(root=skills) == before
    for name in ("go-conventions", "testing", "pdf"):
        assert f"**{name}**" in first.decode()


def test_refresh_discovers_new_nested_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills = _tree(root=tmp_path)
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: skills)
    assert refresh_skills.main() == 0
    _skill(root=tmp_path, relative="languages/rust/conventions", name="rust-conventions", group="languages")
    assert refresh_skills.main() == 0
    assert "skills/languages/rust/conventions/SKILL.md" in (skills / "INDEX.md").read_text()


def test_refresh_returns_builder_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: missing)
    assert refresh_skills.main() == 1
    assert not missing.exists()


@pytest.mark.parametrize("script_name", ["refresh_skills.py", "build_skill_index.py"])
def test_script_runs_from_other_directory_without_upstream(tmp_path: Path, script_name: str) -> None:
    """Run real entry points against a copied temporary tree, never the checkout."""
    skills = _tree(root=tmp_path)
    before = _snapshot(root=skills)
    for relative in (
        "scripts/refresh_skills.py",
        "scripts/build_skill_index.py",
        "src/agents/skills/registry.py",
    ):
        _write(root=tmp_path, relative=relative, text=(ROOT / relative).read_text())
    result = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / script_name)],
        cwd=skills,
        env={
            **os.environ,
            "PYTHONPATH": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SLO_CODE_PROMPTS_DIR": str(tmp_path / "missing-upstream"),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "3 skills" in result.stdout
    assert _snapshot(root=skills) == before
    assert (skills / "INDEX.md").is_file()
