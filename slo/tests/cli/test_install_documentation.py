"""Documentation contracts for the supported isolated-launcher lifecycle."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
INSTALL_GUIDE: Path = REPOSITORY_ROOT / "docs" / "INSTALL.md"


def test_install_guide_describes_launcher_finalization_and_no_envrc_requirement() -> None:
    """The operator guide names the supported repair boundary and excludes target ``.envrc`` changes."""
    content: str = INSTALL_GUIDE.read_text()

    assert "--finalize-launcher" in content
    assert "matching tagged public installer" in content
    assert "Direct `pipx install`, `upgrade`, or `reinstall`" in content
    assert "not a supported repair path" in content
    assert "never requires, reads, or changes a target project's `.envrc`" in content


def test_install_guide_distinguishes_initial_wrapper_environment_from_child_sanitation() -> None:
    """The guide makes no false claim that ``-I`` scrubs process environment or child launches."""
    content: str = INSTALL_GUIDE.read_text()

    assert "import isolation, not environment scrubbing" in content
    assert "initial\nwrapped CLI process" in content
    assert "sanitized child environment" in " ".join(content.split())
    assert "sys.executable -I -m src.cli" in content
    assert "does not propagate to project interpreters" in " ".join(content.split())
    assert "trusted source fallback" in content
