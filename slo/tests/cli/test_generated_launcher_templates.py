"""Recognize supported console-script templates without executing their contents."""

from pathlib import Path
import shlex
import subprocess

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "install.sh"
MODERN_BODY = """import sys
from src.cli import main
if __name__ == '__main__':
    sys.argv[0] = sys.argv[0].removesuffix('.exe')
    sys.exit(main())
"""
LEGACY_BODY = """# -*- coding: utf-8 -*-
import re
import sys
from src.cli import main
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])
    sys.exit(main())
"""


@pytest.mark.parametrize("body", [MODERN_BODY, LEGACY_BODY])
@pytest.mark.parametrize("mutation", ["none", "extra-code", "wrong-import", "wrong-shebang"])
def test_generated_launcher_recognition(tmp_path: Path, body: str, mutation: str) -> None:
    """The installer accepts known templates but refuses modified executable content."""
    python = tmp_path / "venv" / "bin" / "python"
    launcher = tmp_path / "slo-entry"
    sentinel = tmp_path / "executed"
    if mutation == "extra-code":
        body += f"open({str(sentinel)!r}, 'w').close()\n"
    if mutation == "wrong-import":
        body = body.replace("from src.cli", "from foreign.cli")
    shebang = str(python) if mutation != "wrong-shebang" else "/untrusted/python"
    assert launcher.resolve().is_relative_to(tmp_path.resolve())
    launcher.write_text(f"#!{shebang}\n{body}")
    result = subprocess.run(
        args=[
            "/bin/bash",
            "-c",
            f"source {shlex.quote(str(INSTALLER))}; "
            f"slo_is_recognized_generated_launcher {shlex.quote(str(launcher))} "
            f"{shlex.quote(str(python))}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) == (mutation == "none"), result.stderr
    assert not sentinel.exists()
