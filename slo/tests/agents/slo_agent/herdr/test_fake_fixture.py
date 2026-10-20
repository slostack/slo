"""The fake capability is explicit, private and usable by T2's spawn wrapper."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.state_isolation import FakeHerdrSpawnGuard


def test_fake_fixture_executes_only_registered_files(fake_herdr: object) -> None:
    """A registered regular fake records argv without reaching real Herdr."""
    executable = getattr(fake_herdr, "executable")
    guard = getattr(fake_herdr, "guard")
    guard.require_registered(path=executable)
    result = subprocess.run(args=[str(executable), "pane", "split"], capture_output=True, timeout=5)
    assert result.returncode == 0
    assert getattr(fake_herdr, "capture").read_text().strip() == '["pane", "split"]'
    assert os.environ["HERDR_BIN_PATH"] == str(executable)
    assert os.environ["SLO_HERDR_DISABLED"] == "0"


def test_default_capability_denies(tmp_path: Path, fake_herdr_guard: FakeHerdrSpawnGuard) -> None:
    """Environment opt-in alone grants no executable permission."""
    with pytest.raises(AssertionError):
        fake_herdr_guard.require_registered(path=tmp_path / "fake")


@pytest.mark.parametrize("target", ["executable", "capture", "barrier"])
def test_fixture_substitution_refused(fake_herdr: object, target: str) -> None:
    """Every registered output and executable inode is rechecked before spawn."""
    path: Path = getattr(fake_herdr, target)
    replacement = path.parent / "replacement"
    assert replacement.parent.resolve(strict=True) == path.parent.resolve(strict=True)
    with replacement.open(mode="x") as stream:
        stream.write("replacement")
    replacement.replace(path)
    with pytest.raises(AssertionError):
        getattr(fake_herdr, "guard").require_registered(path=getattr(fake_herdr, "executable"))
