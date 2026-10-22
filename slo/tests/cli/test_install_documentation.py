"""Documentation contracts for the supported isolated-launcher lifecycle."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
RESEARCH: Path = REPOSITORY_ROOT / "RESEARCH.md"


def _research_text() -> str:
    """Return RESEARCH.md with whitespace collapsed so wrapped bullets compare as one line."""
    return " ".join(RESEARCH.read_text(encoding="utf-8").split())


def test_install_guide_describes_launcher_finalization_and_no_envrc_requirement() -> None:
    """The operator reference names the supported repair boundary and excludes target ``.envrc`` changes."""
    content: str = _research_text()

    assert "--finalize-launcher" in content
    assert "re-run matching tagged public installer" in content
    assert "Direct `pipx install|upgrade|reinstall`" in content
    assert "unsupported as repair" in content
    assert "Slo never reads/changes a project's `.envrc`" in content


def test_install_guide_distinguishes_initial_wrapper_environment_from_child_sanitation() -> None:
    """The reference makes no false claim that ``-I`` scrubs process environment or child launches."""
    content: str = _research_text()

    assert "Import isolation only: `os.environ` (incl. `SLO_*`, credentials) remains" in content
    assert "sanitized child environment" in content
    assert "sys.executable -I -m src.cli" in content
    assert "`-I` does not propagate to project interpreters" in content
    assert "trusted source fallback" in content
