"""Resolve the ``slo`` package version (sub-spec 02.a.4)."""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Optional

try:
    import tomllib  # stdlib from Python 3.11+
except ImportError:  # pragma: no cover — only reachable on Python < 3.11
    tomllib = None  # type: ignore[assignment]


__all__ = ["resolve_version"]


def resolve_version() -> str:
    """Return the installed package version, or ``"unknown"`` if not packaged.

    Resolution order:
    1. ``importlib.metadata.version("slo")`` — authoritative for pipx and
       properly reinstalled editable installs.
    2. Walk up from this file's directory looking for a ``pyproject.toml``
       whose ``[project]`` section declares ``name = "slo"``.  This handles
       stale editable installs where the dist-info is missing or behind.
    3. Return ``"unknown"`` if both strategies fail.

    Returns:
        str: Package version (e.g. ``"0.1.0"``) or the literal
            ``"unknown"`` when neither ``importlib.metadata`` nor the
            ``pyproject.toml`` fallback can resolve a version.
    """
    version: Optional[str] = _version_from_metadata()
    if version and version != "unknown":
        return version

    version = _version_from_pyproject()
    if version:
        return version

    return "unknown"


def _version_from_metadata() -> Optional[str]:
    """Return the version recorded in the installed dist-info, or ``None``.

    Returns:
        Optional[str]: The version string on success, or ``None`` when
            ``importlib.metadata`` raises ``PackageNotFoundError``.
    """
    try:
        return metadata.version(distribution_name="slo")
    except metadata.PackageNotFoundError:
        return None


def _version_from_pyproject() -> Optional[str]:
    """Walk up from this file's directory to find a matching ``pyproject.toml``.

    Walks parent directories starting from ``Path(__file__).parent`` until it
    either finds a ``pyproject.toml`` that declares ``name = "slo"`` in its
    ``[project]`` section, or exhausts all ancestors.

    Returns:
        Optional[str]: The ``version`` value from ``[project]``, or ``None``
            when no suitable file is found.
    """
    search_root: Path = Path(__file__).parent
    for directory in [search_root, *search_root.parents]:
        candidate: Path = directory / "pyproject.toml"
        if candidate.is_file():
            version: Optional[str] = _parse_version_from_pyproject(pyproject_path=candidate)
            if version is not None:
                return version
    return None


def _parse_version_from_pyproject(*, pyproject_path: Path) -> Optional[str]:
    """Extract the ``version`` from the ``[project]`` section of a TOML file.

    Tries ``tomllib`` (stdlib on Python 3.11+) first for correctness; falls
    back to a line-by-line regex scan that avoids any third-party dependency.

    Args:
        pyproject_path (Path): Absolute path to the ``pyproject.toml`` to parse.

    Returns:
        Optional[str]: The version string when ``name = "slo"`` is found under
            ``[project]``, or ``None`` if the file is not for this package or
            the version field is absent.
    """
    if tomllib is not None:
        return _parse_via_tomllib(pyproject_path=pyproject_path)
    return _parse_via_regex(pyproject_path=pyproject_path)


def _parse_via_tomllib(*, pyproject_path: Path) -> Optional[str]:
    """Parse ``pyproject.toml`` using the stdlib ``tomllib`` module.

    Args:
        pyproject_path (Path): Path to the TOML file.

    Returns:
        Optional[str]: Version string from ``[project].version`` when
            ``[project].name`` equals ``"slo"``, otherwise ``None``.
    """
    try:
        with pyproject_path.open(mode="rb") as fh:
            data: dict = tomllib.load(fh)
        project: dict = data.get("project", {})
        if project.get("name") == "slo":
            return project.get("version")
    except Exception:  # noqa: BLE001 — any parse or IO error → fall through
        pass
    return None


def _parse_via_regex(*, pyproject_path: Path) -> Optional[str]:
    """Scan ``pyproject.toml`` line-by-line to find ``[project].version``.

    Reads the ``[project]`` block and stops at the next section header.
    Requires ``name = "slo"`` to appear in the same block before returning
    the version, so we do not accidentally pick up a nested tool's version.

    Args:
        pyproject_path (Path): Path to the TOML file.

    Returns:
        Optional[str]: Version string extracted by regex, or ``None`` if the
            file cannot be read or the expected fields are not present.
    """
    _SECTION_PATTERN: re.Pattern = re.compile(r"^\[(.+)\]")
    _KV_PATTERN: re.Pattern = re.compile(r'^(\w+)\s*=\s*"([^"]+)"')

    try:
        lines: list[str] = pyproject_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_project_section: bool = False
    found_name: bool = False
    found_version: Optional[str] = None

    for line in lines:
        section_match: Optional[re.Match] = _SECTION_PATTERN.match(line)
        if section_match:
            section_name: str = section_match.group(1).strip()
            if section_name == "project":
                in_project_section = True
                continue
            if in_project_section:
                # Left the [project] block — stop scanning.
                break

        if not in_project_section:
            continue

        kv_match: Optional[re.Match] = _KV_PATTERN.match(line)
        if kv_match:
            key: str = kv_match.group(1)
            value: str = kv_match.group(2)
            if key == "name" and value == "slo":
                found_name = True
            elif key == "version":
                found_version = value

    if found_name and found_version:
        return found_version
    return None
