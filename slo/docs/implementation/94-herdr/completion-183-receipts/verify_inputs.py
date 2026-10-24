"""Read-only input reconciliation; writes only assessment receipts."""
from pathlib import Path
import hashlib
import subprocess

root = Path.cwd()
out = root / "docs/implementation/94-herdr/completion-183-receipts"
paths = sorted(set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "."], text=True).splitlines()))
files = [name for name in paths if not name.startswith("docs/implementation/") and name not in {"RESEARCH.md", "docs/RESEARCH.md"} and (root / name).is_file() and not (root / name).is_symlink()]
text = "".join(f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n" for name in files)
(out / "current.sha256").write_text(text)
prior = root / "docs/implementation/94-herdr/review-harness-static-181-receipts/after.sha256"
assert text == prior.read_text(), "Current comprehensive inputs differ from independently reviewed 181 inputs"
print(f"Current comprehensive inputs: {len(files)}, all identical to 181; sha256={hashlib.sha256(text.encode()).hexdigest()}")
for name in ["src/tui/app.py", "tests/tui/test_startup_notice_cutoff.py", "tests/implementation_checks/test_conventions_audit_paths.py"]:
    print(f"Current uncommitted input {name}: {hashlib.sha256((root / name).read_bytes()).hexdigest()}")
print(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
