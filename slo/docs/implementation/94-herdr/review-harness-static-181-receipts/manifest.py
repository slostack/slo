"""Freeze comprehensive nonignored inputs; receipts and mutable indexes are excluded."""
from pathlib import Path
import hashlib
import subprocess
import sys

ROOT = Path.cwd()
OUT = ROOT / "docs/implementation/94-herdr/review-harness-static-181-receipts"
paths = sorted(set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "."], text=True).splitlines()))
files = [name for name in paths if not name.startswith("docs/implementation/") and name not in {"RESEARCH.md", "docs/RESEARCH.md"} and (ROOT / name).is_file() and not (ROOT / name).is_symlink()]
text = "".join(f"{hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}  {name}\n" for name in files)
label = sys.argv[1]
(OUT / f"{label}.sha256").write_text(text)
print(f"{label}: {len(files)} files; digest {hashlib.sha256(text.encode()).hexdigest()}")
if label == "after":
    assert text == (OUT / "before.sha256").read_text(), "Input membership or bytes changed"
    print("Comprehensive before/after membership and bytes identical")
