"""Documentation contracts for the supported isolated-launcher lifecycle."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
README: Path = REPOSITORY_ROOT / "README.md"


def _readme_text() -> str:
    """Return README.md with whitespace collapsed so wrapped prose compares as one line."""
    return " ".join(README.read_text(encoding="utf-8").split())


def test_install_guide_describes_launcher_finalization_and_no_envrc_requirement() -> None:
    """The install chapter names the supported repair boundary and excludes target ``.envrc`` changes."""
    content: str = _readme_text()

    assert "install.sh --finalize-launcher" in content
    assert "matching tagged public installer" in content
    assert "Direct `pipx install`, `upgrade`, or `reinstall`" in content
    assert "It is not a supported repair path" in content
    assert "Slo never requires, reads, or changes a target project's `.envrc`" in content


def test_install_guide_distinguishes_initial_wrapper_environment_from_child_sanitation() -> None:
    """The install chapter makes no false claim that ``-I`` scrubs process environment or child launches."""
    content: str = _readme_text()

    assert "it is import isolation, not environment scrubbing" in content
    assert "sanitized child environment" in content
    assert "sys.executable -I -m src.cli" in content
    assert "Isolation applies to the agent interpreter, not to project commands the agent launches" in content
    assert "visualizer source fallback remains trusted-source-only" in content
