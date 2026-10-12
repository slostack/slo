"""Compile and race-test self-contained Go examples in the curated skill family.

Run with ``python scripts/verify_skill_examples.py``; Go must be installed.
Framework snippets are intentionally not claimed to be standalone programs.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GO_SKILLS = ROOT / "skills/languages/go"
CASES: dict[str, tuple[tuple[str, str], ...]] = {
    "activation": (
        ("go-build-application-services", "service.go"),
        ("go-test-orchestration", "service_test.go"),
    ),
    "background": (
        ("go-build-lifecycle", "service.go"),
        ("go-test-lifecycle", "service_test.go"),
    ),
    "order": (("go-build-domain-features", "service.go"),),
    "envelope": (("go-recipe-api-response-conventions", "envelope.go"),),
}


def main() -> int:
    """Extract the documented standalone examples and run Go build/test gates."""
    with tempfile.TemporaryDirectory(prefix="slo-skill-examples-") as directory:
        root = Path(directory)
        (root / "go.mod").write_text("module skill-examples\n\ngo 1.22\n")
        for package, entries in CASES.items():
            target = root / package
            target.mkdir()
            for slug, filename in entries:
                text = (GO_SKILLS / slug / "SKILL.md").read_text()
                blocks = re.findall(r"```go\n(.*?)\n```", text, flags=re.DOTALL)
                assert len(blocks) == 1, slug
                (target / filename).write_text(blocks[0] + "\n")
        for command in (["go", "test", "-race", "-count=1", "./..."], ["go", "vet", "./..."]):
            subprocess.run(command, cwd=root, check=True, timeout=180)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
