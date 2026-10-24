"""Reconcile historical diagnostic and dependency evidence, without rerunning old code."""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.metadata
import json
import re

root = Path("docs/implementation/94-herdr")
def diagnostics(path: Path) -> Counter[str]:
    return Counter(re.sub(r":\d+(?::\d+)?: error:", ": error:", line) for line in path.read_text().splitlines() if ": error:" in line)
base = diagnostics(root / "baseline-lint.log")
red = diagnostics(root / "static-E-152-receipts/red-harness-lint.log")
green = diagnostics(root / "static-E-152-receipts/lint.log")
print("Baseline", sum(base.values()), "pre-E", sum(red.values()), "post-E", sum(green.values()))
print("Pre-E added versus baseline:", dict(red-base))
print("Pre-E removed versus baseline:", sum((base-red).values()))
print("E added:", dict(green-red), "E removed:", dict(red-green))
assert not red-base and not green-red
assert sum((red-green).values()) == 1
before = Counter(map(tuple, json.loads((root / "static-E-152-receipts/installed-before.json").read_text())))
after = Counter(map(tuple, json.loads((root / "static-E-152-receipts/installed-after.json").read_text())))
print("Historical installed delta:", dict(after-before), "removed:", dict(before-after))
assert dict(after-before) == {("types-PyYAML", "6.0.12.20260906"): 1} and not before-after
print("Current stub:", importlib.metadata.version("types-PyYAML"))
wheel = root / "static-E-152-receipts/types_pyyaml-6.0.12.20260906-py3-none-any.whl"
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == "bca893ff0d51df5c9053137d5d0e6ccd36e939a196356f1d5c16372422f5137b"
print("Retained wheel matches lock hash")
collection = (root / "review-harness-static-181-receipts/collection.log").read_text().splitlines()
nodes = [line for line in collection if line.startswith("tests/") and "::" in line]
counts = Counter(line.split("::")[0] for line in nodes)
print("Collected modules:", dict(counts))
matrix = [line for line in nodes if "test_lifetime_cutoff_matrix[" in line]
assert len(matrix) == len(set(matrix)) == 64
print("64 distinct canonical matrix node IDs")
