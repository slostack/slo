"""Read-only reconciliation of retained review inputs and current worktree."""

import ast
import hashlib
import subprocess
from pathlib import Path


def main() -> None:
    """Preserve core acceptance and record exact bytes used by this review."""
    root = Path("docs/implementation/94-herdr")
    manifests: dict[str, dict[str, str]] = {}
    for label, filename in (
        ("171", "gates-171-receipts/after.sha256"),
        ("174", "turn6-code-test-174-receipts/after.sha256"),
    ):
        manifests[label] = {
            line.split("  ", 1)[1]: line.split("  ", 1)[0]
            for line in (root / filename).read_text().splitlines()
        }
    for label, manifest in manifests.items():
        changed = [
            name for name, digest in manifest.items()
            if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest
        ]
        print(label, "current mismatches", changed)
    core = [name for name in manifests["171"] if name.startswith("src/agents/slo_agent/herdr/")]
    assert all(
        hashlib.sha256(Path(name).read_bytes()).hexdigest() == manifests["171"][name]
        for name in core
    )
    print("CORE production unchanged:", len(core))
    paths = [
        "src/tui/app.py", "src/agents/slo_agent/sessions/service.py",
        "tests/tui/test_startup_notice_cutoff.py", "tests/implementation_checks/test_conventions_audit_paths.py",
        "tests/conftest.py", "tests/state_isolation.py",
        str(root / "conventions-revision-159-receipts/audit.py"),
        str(root / "independent-review-wiring-173-receipts/test_startup_cutoff_probe.py"),
        str(root / "review-wiring-175-receipts/test_review_boundaries.py"),
        str(root / "review-wiring-175-receipts/test_activation_contract.py"),
    ]
    for name in paths:
        current = Path(name).read_bytes()
        committed = subprocess.check_output(["git", "show", "HEAD:slo/" + name])
        print(hashlib.sha256(current).hexdigest(), name, "matches HEAD:", current == committed)
    session = ast.parse(Path(paths[1]).read_text())
    for node in ast.walk(session):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "close_external_reporting":
            print("close contract SHA256:", hashlib.sha256(ast.get_docstring(node).encode()).hexdigest())
    print("Git HEAD:", subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())


if __name__ == "__main__":
    main()
