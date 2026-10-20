"""Test-only state boundaries; import this before any config or application module."""

import os
import tempfile
import stat
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

SLO_HOME_BINDINGS: tuple[tuple[str, str], ...] = (
    ("src.agents.model_catalog.store", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.filesystem_store", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.migration.token_usage_backfiller", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.migration.tree_migrator", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.preferences.service", "_CFG_SLO_HOME"),
    ("src.auth.credential_refresher", "_CFG_SLO_HOME"),
    ("src.cli.typer_dispatch", "_CFG_SLO_HOME"),
    ("src.integrations.connectors.store", "_CFG_SLO_HOME"),
    ("src.scheduling.os.logs", "_CFG_SLO_HOME"),
    ("src.scheduling.store", "_CFG_SLO_HOME"),
)
"""Module-level SLO_HOME imports; an AST regression guard keeps this exhaustive."""

INHERITED_STATE_OVERRIDES: tuple[str, ...] = (
    "SLO_WORKFLOW_ID",
    "SLO_CAPTURE_DIR",
    "SLO_CAPTURE_COMPLETION",
    "SLO_PREFERENCES_FILE",
    "SLO_SCHEDULES_DIR",
    "SLO_CONNECTORS_DIR",
    "SLO_MODEL_CATALOG_OVERRIDES_FILE",
    "SLO_USER_SKILLS_DIR",
    "SLO_USER_WORKFLOWS_DIR",
    "SLO_KB_DIR",
    "KB_DIR",
    "SLO_SKILLS_DIR",
    "SLO_KB_SOURCE",
    "SLO_TOOL_BASE_DIR",
    "SLO_SESSION_ID",
    "SLO_HERDR_METADATA_PROFILE",
)
"""State and content overrides that must not escape the test-owned home."""


def inherited_herdr_names() -> tuple[str, ...]:
    """Select inherited integration keys without retaining their values.

    Returns:
        tuple[str, ...]: Names to remove before imports and per-test rebinding.
    """
    return tuple(
        name
        for name in os.environ
        if name.upper().startswith("HERDR_") or name.upper() == "SLO_HERDR_METADATA_PROFILE"
    )


class FakeHerdrSpawnGuard:
    """Grant only test-local, identity-bound fake executable capabilities."""

    def __init__(self, *, root: Path) -> None:
        """Bind the existing test root without granting execution permission."""
        self._root = root.resolve(strict=True)
        self._identities: dict[Path, tuple[int, int]] = {}
        self._executable: Optional[Path] = None

    def register(self, *, executable: Path, files: tuple[Path, ...]) -> None:
        """Validate executable and all capture/barrier identities before granting."""
        identities = {path: self._identity(path=path) for path in (executable,) + files}
        if not executable.stat().st_mode & stat.S_IXUSR:
            raise AssertionError("Nonexecutable Herdr fixture")
        self._identities = identities
        self._executable = executable

    def require_registered(self, *, path: Path) -> None:
        """Refuse missing permission or substituted files before delegation."""
        if self._executable is None or path != self._executable:
            raise AssertionError("Unregistered Herdr executable")
        if not path.stat().st_mode & stat.S_IXUSR:
            raise AssertionError("Nonexecutable Herdr fixture")
        for target, identity in self._identities.items():
            if self._identity(path=target) != identity:
                raise AssertionError("Changed Herdr fixture file")

    def _identity(self, *, path: Path) -> tuple[int, int]:
        """Require contained regular files without traversal or symbolic links."""
        if not path.is_absolute() or ".." in path.parts:
            raise AssertionError("Unsafe Herdr fixture path")
        if any(component.is_symlink() for component in (path, *path.parents)):
            raise AssertionError("Linked Herdr fixture path")
        resolved = path.resolve(strict=True)
        if resolved == self._root or not resolved.is_relative_to(self._root):
            raise AssertionError("Outside Herdr fixture root")
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise AssertionError("Nonregular Herdr fixture file")
        return metadata.st_dev, metadata.st_ino


@dataclass(frozen=True)
class FakeHerdrFixture:
    """Immutable test capability shared with the future transport boundary."""

    executable: Path
    capture: Path
    barrier: Path
    guard: FakeHerdrSpawnGuard


def isolate_suite_slo_home() -> Path:
    """Redirect default state before conftest imports application modules.

    WHO: The root conftest calls this once before collection. Its unconfigure
    hook removes the returned directory after pytest finishes.

    Returns:
        Path: A fresh, resolved suite root under the command's temporary root.
    """
    for name in inherited_herdr_names():
        del os.environ[name]
    os.environ["SLO_HERDR_DISABLED"] = "1"
    root: Path = Path(tempfile.mkdtemp(prefix="slo-test-home-")).resolve()
    os.environ["SLO_HOME"] = str(root)
    os.environ["SLO_AUTH_FILE"] = str(root / "global" / "authentication.json")
    os.environ["HOME"] = str(root / "home")
    for name in INHERITED_STATE_OVERRIDES:
        os.environ.pop(name, None)
    return root
