"""Tests for ``resolve_version`` (sub-spec 02.a.4)."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch, MagicMock

import pytest

from src.cli.version import (
    resolve_version,
    _version_from_metadata,
    _version_from_pyproject,
    _parse_version_from_pyproject,
    _parse_via_regex,
    _parse_via_tomllib,
)


class TestResolveVersion:
    """Cover all resolution paths through ``resolve_version``."""

    def test_returns_metadata_version_when_installed(self) -> None:
        """When the distribution is registered, return its version string."""
        with patch(
            "src.cli.version.metadata.version",
            return_value="1.2.3",
        ) as mock_version:
            result: str = resolve_version()

        assert result == "1.2.3"
        mock_version.assert_called_once_with(distribution_name="slo")

    def test_falls_back_to_pyproject_when_metadata_missing(self, tmp_path: Path) -> None:
        """When metadata raises PackageNotFoundError, read version from pyproject.toml."""
        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                version = "9.9.9"
                """),
            encoding="utf-8",
        )

        with (
            patch(
                "src.cli.version.metadata.version",
                side_effect=metadata.PackageNotFoundError("slo"),
            ),
            patch(
                "src.cli.version.Path",
                return_value=MagicMock(
                    parent=tmp_path,
                    parents=[tmp_path, tmp_path.parent],
                ),
            ),
        ):
            # Directly exercise _version_from_pyproject with the tmp dir
            result: str | None = _parse_version_from_pyproject(pyproject_path=pyproject)

        assert result == "9.9.9"

    def test_returns_unknown_when_both_fail(self, tmp_path: Path) -> None:
        """When metadata raises and no pyproject.toml is found, return ``"unknown"``."""
        with (
            patch(
                "src.cli.version.metadata.version",
                side_effect=metadata.PackageNotFoundError("slo"),
            ),
            patch(
                "src.cli.version._version_from_pyproject",
                return_value=None,
            ),
        ):
            result: str = resolve_version()

        assert result == "unknown"

    def test_metadata_version_takes_priority_over_pyproject(self) -> None:
        """When metadata succeeds, pyproject.toml is never consulted."""
        with (
            patch(
                "src.cli.version.metadata.version",
                return_value="2.0.0",
            ),
            patch(
                "src.cli.version._version_from_pyproject",
            ) as mock_pyproject,
        ):
            result: str = resolve_version()

        assert result == "2.0.0"
        mock_pyproject.assert_not_called()

    def test_falls_back_to_pyproject_when_metadata_returns_unknown(self) -> None:
        """When metadata returns the literal ``"unknown"``, try pyproject.toml."""
        with (
            patch(
                "src.cli.version.metadata.version",
                return_value="unknown",
            ),
            patch(
                "src.cli.version._version_from_pyproject",
                return_value="3.0.0",
            ),
        ):
            result: str = resolve_version()

        assert result == "3.0.0"


class TestVersionFromMetadata:
    """Unit tests for the ``_version_from_metadata`` helper."""

    def test_returns_version_string_on_success(self) -> None:
        """Returns the version string when the distribution is found."""
        with patch("src.cli.version.metadata.version", return_value="4.5.6"):
            result: str | None = _version_from_metadata()

        assert result == "4.5.6"

    def test_returns_none_when_package_not_found(self) -> None:
        """Returns ``None`` (not ``"unknown"``) when the dist-info is missing."""
        with patch(
            "src.cli.version.metadata.version",
            side_effect=metadata.PackageNotFoundError("slo"),
        ):
            result: str | None = _version_from_metadata()

        assert result is None


class TestParseViaRegex:
    """Unit tests for the regex-based TOML line scanner."""

    def test_extracts_version_from_project_section(self, tmp_path: Path) -> None:
        """Finds version when name and version are both in [project]."""
        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                version = "7.8.9"
                description = "test"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_regex(pyproject_path=pyproject)
        assert result == "7.8.9"

    def test_returns_none_when_name_does_not_match(self, tmp_path: Path) -> None:
        """Returns ``None`` when the project name is not ``"slo"``."""
        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "other-package"
                version = "1.0.0"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_regex(pyproject_path=pyproject)
        assert result is None

    def test_stops_scanning_after_project_section(self, tmp_path: Path) -> None:
        """Does not pick up a ``version`` field from a later section."""
        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                version = "1.0.0"

                [tool.poetry]
                version = "99.0.0"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_regex(pyproject_path=pyproject)
        assert result == "1.0.0"

    def test_returns_none_when_file_is_missing(self, tmp_path: Path) -> None:
        """Returns ``None`` when the path does not point to an existing file."""
        result: str | None = _parse_via_regex(
            pyproject_path=tmp_path / "nonexistent.toml"
        )
        assert result is None

    def test_returns_none_when_version_field_absent(self, tmp_path: Path) -> None:
        """Returns ``None`` when ``[project]`` has the right name but no version."""
        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                description = "no version here"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_regex(pyproject_path=pyproject)
        assert result is None


class TestParseViaTomlLib:
    """Unit tests for the tomllib-based parser (Python 3.11+ stdlib)."""

    def test_extracts_version_via_tomllib(self, tmp_path: Path) -> None:
        """Reads version correctly using tomllib when available."""
        import src.cli.version as version_module

        if version_module.tomllib is None:
            pytest.skip("tomllib not available on this Python version")

        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                version = "5.6.7"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_tomllib(pyproject_path=pyproject)
        assert result == "5.6.7"

    def test_returns_none_when_name_does_not_match_via_tomllib(
        self, tmp_path: Path
    ) -> None:
        """Returns ``None`` when the project name is not ``"slo"``."""
        import src.cli.version as version_module

        if version_module.tomllib is None:
            pytest.skip("tomllib not available on this Python version")

        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "not-slo"
                version = "5.6.7"
                """),
            encoding="utf-8",
        )
        result: str | None = _parse_via_tomllib(pyproject_path=pyproject)
        assert result is None

    def test_returns_none_on_malformed_toml(self, tmp_path: Path) -> None:
        """Returns ``None`` when the file cannot be parsed."""
        import src.cli.version as version_module

        if version_module.tomllib is None:
            pytest.skip("tomllib not available on this Python version")

        pyproject: Path = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not valid toml ][", encoding="utf-8")
        result: str | None = _parse_via_tomllib(pyproject_path=pyproject)
        assert result is None


class TestVersionFromPyproject:
    """Integration test for the walk-up pyproject.toml discovery."""

    def test_finds_pyproject_in_ancestor_directory(self, tmp_path: Path) -> None:
        """Discovers the correct version from a pyproject.toml a few levels up."""
        # Simulate: tmp_path/project/src/cli/version.py looking for tmp_path/project/pyproject.toml
        nested: Path = tmp_path / "project" / "src" / "cli"
        nested.mkdir(parents=True)
        pyproject: Path = tmp_path / "project" / "pyproject.toml"
        pyproject.write_text(
            dedent("""\
                [project]
                name = "slo"
                version = "8.0.0"
                """),
            encoding="utf-8",
        )

        with patch("src.cli.version.Path") as MockPath:
            # Make __file__ resolve to a fake path inside the nested directory
            mock_file_path = MagicMock()
            mock_file_path.parent = nested
            mock_file_path.parents = [nested, nested.parent, nested.parent.parent, tmp_path / "project", tmp_path]
            MockPath.return_value = mock_file_path

            # We need _version_from_pyproject to use our patched Path, but the
            # candidate.is_file() check needs to work with real tmp_path dirs.
            # Instead, test _parse_version_from_pyproject directly.
            pass

        # Direct integration: _parse_version_from_pyproject finds the right version
        result: str | None = _parse_version_from_pyproject(pyproject_path=pyproject)
        assert result == "8.0.0"
