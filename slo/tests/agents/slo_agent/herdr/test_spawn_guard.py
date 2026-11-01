"""Fake capability refuses unsafe files without executing anything."""

from pathlib import Path

import pytest

from tests import state_isolation


def create_owned(*, root: Path, name: str) -> Path:
    """Create a new regular fixture file after proving containment."""
    path = root / name
    assert path.parent.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    assert not path.exists() and not path.is_symlink()
    with path.open(mode="x", encoding="utf-8") as stream:
        stream.write("fixture")
    return path


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "unregistered",
        "relative",
        "traversal",
        "outside",
        "symlink",
        "directory",
        "replaced",
        "capture_replaced",
    ],
)
def test_guard(*, tmp_path: Path, case: str) -> None:
    """Every refusal happens before any subprocess boundary."""
    root = tmp_path / "owned"
    assert root.parent.resolve(strict=True) == tmp_path.resolve(strict=True)
    root.mkdir()
    executable = create_owned(root=root, name="fake")
    executable.chmod(0o700)
    capture = create_owned(root=root, name="capture")
    guard = state_isolation.FakeHerdrSpawnGuard(root=root)
    if case == "unregistered":
        with pytest.raises(AssertionError):
            guard.require_registered(path=executable)
        return
    invalid = {
        "relative": Path("fake"),
        "traversal": root / ".." / "owned" / "fake",
        "outside": create_owned(root=tmp_path, name="outside"),
        "directory": root,
    }
    if case == "symlink":
        link = root / "link"
        assert link.parent.resolve(strict=True) == root.resolve(strict=True)
        link.symlink_to(executable)
        invalid[case] = link
    if case in invalid:
        with pytest.raises(AssertionError):
            guard.register(executable=invalid[case], files=(capture,))
        return
    guard.register(executable=executable, files=(capture,))
    if case in {"replaced", "capture_replaced"}:
        target = executable if case == "replaced" else capture
        replacement = create_owned(root=root, name="replacement")
        assert target.resolve(strict=True).is_relative_to(root)
        replacement.replace(target)
        with pytest.raises(AssertionError):
            guard.require_registered(path=executable)
        return
    guard.require_registered(path=executable)


@pytest.mark.parametrize("case", ["missing", "parent_link", "hardlink", "not_executable"])
def test_guard_additional_refusals(tmp_path: Path, case: str) -> None:
    """No linked inode or non-executable file can receive a spawn capability."""
    import os

    executable = create_owned(root=tmp_path, name="fake")
    executable.chmod(0o700)
    guard = state_isolation.FakeHerdrSpawnGuard(root=tmp_path)
    if case == "missing":
        executable.unlink()
    elif case == "parent_link":
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        executable = link / "fake"
    elif case == "hardlink":
        os.link(src=executable, dst=tmp_path / "alias")
    else:
        executable.chmod(0o600)
    with pytest.raises((AssertionError, FileNotFoundError)):
        guard.register(executable=executable, files=())
