"""Documentary contracts for one evidence-gated workflow progression."""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]
OBSOLETE = re.compile(
    r"\b(?:auto(?:matic)?|manual)[\s_-]*mode\b"
    r"|\bmanual\s*(?:/|vs\.?)\s*auto\b"
    r"|\bauto\s*(?:/|vs\.?)\s*manual\b"
    r"|\b(?:automatic|manual)\s+confirmation\b"
    r"|confirmation-behavior|confirmation behavior"
    r"|\[(?:AUTO|MANUAL)\]"
    r"|pause at (?:the )?end of each (?:step|phase)"
    r"|Wait for confirmation before continuing",
    flags=re.IGNORECASE,
)
SURFACES = sorted(
    path
    for directory in ("skills", "src", "docs", "config", "scripts")
    for path in (ROOT / directory).rglob("*")
    if path.is_file()
    and path.suffix in {".md", ".json", ".py", ".yaml", ".yml"}
    and "implementation" not in path.relative_to(ROOT).parts
) + sorted(ROOT.glob("*.md"))


@pytest.mark.parametrize(argnames="path", argvalues=SURFACES, ids=lambda path: str(path.relative_to(ROOT)))
def test_active_surfaces_have_no_confirmation_modes(path: Path) -> None:
    """Reject obsolete labels, links, metadata and phase-pause instructions."""
    assert not OBSOLETE.search(path.read_text(encoding="utf-8")), str(path.relative_to(ROOT))


def test_progression_retains_gates_and_external_authorization() -> None:
    """Progress requires artifacts, not pauses; external effects retain permission."""
    text = (ROOT / "skills/orchestration/workflows/SKILL.md").read_text()
    for required in (
        "## Progression and authorization",
        "READY/COMPLETE",
        "required artifacts",
        "blocking clarification",
        "commit",
        "push",
        "publish",
        "merge",
        "PR",
        "destructive",
        "Never retry an aborted task",
        "3 retries per failed task",
    ):
        assert required in text
    for name in ("code-test-review", "specification-development", "gitlab-code-test-review"):
        workflow = (ROOT / f"skills/orchestration/workflows/{name}.md").read_text()
        assert "READY condition" in workflow
        assert "retest and re-review" in workflow
        assert "Never retry an aborted task" in workflow
        assert "#progression-and-authorization" in workflow
