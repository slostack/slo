"""Reproduce missing-stub diagnostics without modifying installed distributions."""
from pathlib import Path
import subprocess
import sys
import tempfile
from importlib import metadata

root = Path.cwd()
receipt = root / "docs/implementation/94-herdr/review-harness-static-181-receipts"
# --python-executable lets mypy ask a separate interpreter for its package paths.
# A temp-owned wrapper reports only a temp package view for that one discovery
# query. The runtime yaml package is copied as bytes; installed packages stay put.
import yaml
import shutil
with tempfile.TemporaryDirectory(prefix="review181-yaml-") as directory:
    owned = Path(directory).resolve()
    packages = owned / "packages"
    packages.mkdir()
    shutil.copytree(Path(yaml.__file__).parent, packages / "yaml", ignore=shutil.ignore_patterns("__pycache__"))
    assert not any(path.is_symlink() for path in packages.rglob("*"))
    wrapper = owned / "python-view"
    wrapper.write_text(f"#!{sys.executable} -I\nimport sys\nassert sys.argv[1:]==['-c', 'import sys; print(sys.executable)'] or 'pyinfo' in ' '.join(sys.argv[1:]), sys.argv[1:]\nprint({repr(([], [str(packages)]))!r})\n")
    wrapper.chmod(0o700)
    probe = owned / "probe.py"
    probe.write_text("import yaml\nvalue = yaml.safe_load('name: offline')\n")
    args = [sys.executable, "-m", "mypy", "--no-incremental", "--config-file", str(root / "pyproject.toml"), "--cache-dir", str(owned / "cache"), "--python-executable", str(wrapper), str(probe)]
    for label in ("red", "green"):
        if label == "green":
            distribution = metadata.distribution("types-PyYAML")
            stub = Path(distribution.locate_file("yaml-stubs"))
            shutil.copytree(stub, packages / "yaml-stubs", ignore=shutil.ignore_patterns("__pycache__"))
        result = subprocess.run(args, capture_output=True, text=True)
        (receipt / f"yaml-{label}-isolated.log").write_text(result.stdout + result.stderr)
        (receipt / f"yaml-{label}-isolated.exit").write_text(f"{result.returncode}\n")
        print(label, result.returncode, result.stdout, result.stderr)
        assert result.returncode == (1 if label == "red" else 0)
        if label == "red":
            assert '[import-untyped]' in result.stdout
print("Only a temp-owned runtime/stub search view changed; no package installation/removal")
