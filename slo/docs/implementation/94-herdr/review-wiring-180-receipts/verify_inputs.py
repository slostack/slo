"""Read-only byte and assertion reconciliation for bounded wiring review180."""

import ast
import hashlib
import subprocess
from pathlib import Path

ROOT = Path("docs/implementation/94-herdr")


def digest(data: bytes) -> str:
    """Return the SHA256 of observed bytes."""
    return hashlib.sha256(data).hexdigest()


def committed(path: str) -> bytes:
    """Read the current committed product blob without changing Git."""
    return subprocess.check_output(["git", "show", "HEAD:slo/" + path])


def functions(text: str) -> dict[str, str]:
    """Index top-level function bodies without line-number sensitivity."""
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in ast.parse(text).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def main() -> None:
    """Check core preservation, audit identity, old assertions and current author inputs."""
    manifest = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in (ROOT / "gates-171-receipts/after.sha256").read_text().splitlines()
    }
    core = [path for path in manifest if path.startswith("src/agents/slo_agent/herdr/")]
    for path in core:
        assert digest(Path(path).read_bytes()) == manifest[path], path
    print("CORE172 production retains171 hashes:", len(core))
    for path in (
        "src/agents/slo_agent/sessions/service.py",
        "tests/cli/test_headless.py",
        "tests/conftest.py",
        "tests/state_isolation.py",
        str(ROOT / "conventions-revision-159-receipts/audit.py"),
        str(ROOT / "review-wiring-175-receipts/test_review_boundaries.py"),
        str(ROOT / "review-wiring-175-receipts/test_activation_contract.py"),
        str(ROOT / "independent-review-wiring-173-receipts/test_startup_cutoff_probe.py"),
    ):
        data = Path(path).read_bytes()
        assert data == committed(path), path
        print(digest(data), path, "byte-identical HEAD")
    path = "tests/tui/test_startup_notice_cutoff.py"
    old = functions(committed(path).decode())
    current = functions(Path(path).read_text())
    assert all(current[name] == body for name, body in old.items())
    print("All prior startup helper/test ASTs retained:", len(old))
    print("Added top-level startup tests:", sorted(set(current) - set(old)))
    for line in (ROOT / "turn6-code-test-179-receipts/manifest-after.txt").read_text().splitlines():
        expected, name = line.split("  ", 1)
        actual = digest(Path(name).read_bytes())
        if name.endswith(("turn6-code-test-176.md", "turn6-code-test-177.md")):
            print(actual, name, "documentation matches179 manifest:", actual == expected)
            prefix = Path(name).read_bytes().split(b"\n## Correction (turn6-179)", 1)[0]
            assert digest(prefix.rstrip() + b"\n") == expected, name
            print("Manifest matches exact pre-correction prefix; only179 correction appended:", name)
            continue
        assert actual == expected, name
        print(expected, name, "matches179 final input")
    for name in ("src/tui/app.py", path, "tests/implementation_checks/test_conventions_audit_paths.py"):
        diff = subprocess.check_output(["git", "diff", "--", name], text=True)
        additions = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
        assert not any(token in line for token in ("type: ignore", "noqa", "pytest.mark.skip", "pytest.mark.xfail", "Any") for line in additions)
    print("No added Any/ignore/skip/xfail in bounded delta")
    print("HEAD:", subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())


if __name__ == "__main__":
    main()
