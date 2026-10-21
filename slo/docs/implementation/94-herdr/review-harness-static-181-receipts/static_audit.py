"""Independent read-only lock, static-repair and retained-input reconciliation."""
from pathlib import Path
import ast
import collections
import hashlib
import json
import re
import subprocess
import tomllib

root = Path.cwd()
receipts = root / "docs/implementation/94-herdr/review-harness-static-181-receipts"
base = "d0e3a756"
prefix = subprocess.check_output(["git", "rev-parse", "--show-prefix"], text=True).strip()
old_lock = tomllib.loads(subprocess.check_output(["git", "show", f"{base}:{prefix}poetry.lock"], text=True))
new_lock = tomllib.loads((root / "poetry.lock").read_text())
old = {row["name"]: row for row in old_lock["package"]}
new = {row["name"]: row for row in new_lock["package"]}
assert all(new[name] == record for name, record in old.items())
assert set(new) - set(old) == {"types-pyyaml"}
assert new["types-pyyaml"]["version"] == "6.0.12.20260906"
print(f"All {len(old)} prior package records byte-value identical; only types-pyyaml dev stub added")
E = root / "docs/implementation/94-herdr/static-E-152-receipts"
for label in ("red-loader", "green-loader"):
    print(label, "exit", (E / f"{label}.exit").read_text().strip(), (E / f"{label}.log").read_text().strip())
for name in ("installed-before.json", "installed-after.json"):
    data = json.loads((E / name).read_text())
    print(name, "entries", len(data))
allocation = root / "docs/implementation/94-herdr/t6-audit-static-plan-142-receipts"
files = set()
for name in ("A-projector.files", "B-auth-compaction.files", "C-provider.files", "D-local-types.files"):
    path = allocation / name
    if not path.exists():
        matches = list(allocation.glob("B*.files"))
        assert name.startswith("B") and len(matches) == 1
        path = matches[0]
    files.update(path.read_text().splitlines())
files.update({"src/auth/oauth_flow.py", "tests/agents/providers/test_anthropic_binding_regression.py", "tests/agents/providers/test_codex_wire_regression.py"})
diff = subprocess.check_output(["git", "diff", base, "--", *sorted(files)], text=True)
(receipts / "static-repair.diff").write_text(diff)
print("Static allocation plus authorized additions:", len(files), "files")
current = ""
for line in diff.splitlines():
    if line.startswith("+++ b/"):
        current = line[6:]
    if line.startswith("+") and not line.startswith("+++") and re.search(r"type:\s*ignore|noqa|pytest\.(skip|xfail)|mark\.(skip|xfail)|ignore_missing_imports|disable_error_code", line):
        print("ADDED SUPPRESSION CANDIDATE", current, line)
old_config = tomllib.loads(subprocess.check_output(["git", "show", f"{base}:{prefix}pyproject.toml"], text=True))
new_config = tomllib.loads((root / "pyproject.toml").read_text())
for key in ("mypy", "pytest", "black"):
    assert old_config["tool"].get(key) == new_config["tool"].get(key)
print("Mypy/pytest/Black configurations identical to feature base")
for path in ("tests/cli/test_install.py", "tests/agents/slo_agent/orchestrator/capture_test_safety.py"):
    previous = subprocess.check_output(["git", "show", f"{base}:{prefix}{path}"])
    assert previous == (root / path).read_bytes()
    print("Unchanged safety helper:", path)
old_manifest = root / "docs/implementation/94-herdr/gates-171-receipts/after.sha256"
changed = []
old_paths = set()
for line in old_manifest.read_text().splitlines():
    digest, name = line.split("  ", 1)
    old_paths.add(name)
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
        changed.append(name)
new_paths = {line.split("  ", 1)[1] for line in (receipts / "before.sha256").read_text().splitlines()}
print("171 -> current changed:", changed)
print("171 -> current added:", sorted(new_paths-old_paths), "removed:", sorted(old_paths-new_paths))
for name in ("tests/conftest.py", "tests/state_isolation.py"):
    assert name not in changed
print("171 registered-fake and terminal guard inputs unchanged")
