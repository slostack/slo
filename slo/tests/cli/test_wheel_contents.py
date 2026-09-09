"""The built wheel must carry ``skills/`` (packaging regression guard).

``skills/`` is not a Python package, so nothing about the normal ``packages``
declaration pulls it into the artifact — it ships only because
``[tool.poetry] include`` names it. When that declaration was absent, a
non-editable ``pipx install`` produced an agent that started with
``vendored_count=0``: every workflow and convention skill silently missing,
which reads as the model choosing badly rather than as a broken install.

The build is slow, so this is opt-in like the install smoke test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

_REQUIRED_ENTRIES: tuple[str, ...] = (
    "skills/INDEX.md",
    "skills/design-and-analysis/workflows/specification-development.md",
    "skills/design-and-analysis/workflows/code-test-review.md",
    "skills/coding/declarative-method-structure/SKILL.md",
)


def _build_wheel(*, output_dir: Path) -> Path:
    """Build the project wheel into ``output_dir`` and return its path.

    Args:
        output_dir (Path): Directory to write the wheel into.

    Returns:
        Path: The built ``.whl`` file.

    Raises:
        AssertionError: If the build fails or produces no wheel.
    """
    result = subprocess.run(
        [sys.executable, "-m", "poetry", "build", "-f", "wheel", "-o", str(output_dir)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"poetry build failed:\n{result.stderr}"
    wheels: list[Path] = sorted(output_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {output_dir}"
    return wheels[-1]


def _repo_is_a_git_checkout() -> bool:
    """Return whether ``_REPO_ROOT`` is inside a git work tree.

    Returns:
        bool: False when git is unavailable or the tree is not a checkout,
            in which case the committed-file comparison cannot run.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


@pytest.mark.skipif(
    os.environ.get("SLO_PACKAGING_E2E") != "1",
    reason="opt-in only: set SLO_PACKAGING_E2E=1 (runs a full poetry build)",
)
class TestWheelShipsSkills:
    """``[tool.poetry] include`` must place skills/ inside the wheel."""

    def test_wheel_contains_every_committed_skill_file(self, tmp_path: Path) -> None:
        """Each committed file under skills/ appears in the wheel."""
        if not _repo_is_a_git_checkout():
            pytest.skip("not a git checkout; cannot enumerate committed skill files")
        wheel: Path = _build_wheel(output_dir=tmp_path)
        with zipfile.ZipFile(wheel) as archive:
            shipped: set[str] = {name for name in archive.namelist() if name.startswith("skills/")}

        committed = subprocess.run(
            ["git", "ls-files", "skills"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert committed.returncode == 0, committed.stderr
        expected: set[str] = {line for line in committed.stdout.splitlines() if line.strip()}

        assert expected, "no committed files under skills/ — check the checkout"
        assert expected - shipped == set(), (
            "committed skill files missing from the wheel: " f"{sorted(expected - shipped)}"
        )

    def test_wheel_contains_the_workflow_entry_points(self, tmp_path: Path) -> None:
        """The named workflows the routing table depends on are present."""
        wheel: Path = _build_wheel(output_dir=tmp_path)
        with zipfile.ZipFile(wheel) as archive:
            names: set[str] = set(archive.namelist())

        missing: list[str] = [entry for entry in _REQUIRED_ENTRIES if entry not in names]
        assert missing == [], f"wheel is missing required skill files: {missing}"
