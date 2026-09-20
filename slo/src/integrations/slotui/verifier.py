"""Fail-closed verification of immutable local Slotui core wheel artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from src.integrations.slotui.dao import (
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreInstallationPlanDAO,
    SlotuiCoreManifestDAO,
)

__all__ = ["SlotuiCoreVerificationError", "SlotuiCoreWheelVerificationService"]


class SlotuiCoreVerificationError(ValueError):
    """Report a rejected Slotui core proof before package import or installation."""


class SlotuiCoreWheelVerificationService:
    """Build safe installation plans from independently verified local release artifacts."""

    @classmethod
    def build_installation_plan(
        cls,
        *,
        reference: SlotuiCoreArtifactReferenceDAO,
    ) -> SlotuiCoreInstallationPlanDAO:
        """Verify a manifest and wheel, then describe its no-index pip invocation.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Absolute manifest path plus expected digest.

        Returns:
            SlotuiCoreInstallationPlanDAO: Verified artifact details and a fresh-venv pip command.

        Raises:
            SlotuiCoreVerificationError: If any manifest, path, wheel, digest, or metadata proof fails.
        """
        manifest_bytes: bytes = cls._read_verified_manifest_bytes(reference=reference)
        manifest: SlotuiCoreManifestDAO = cls._parse_manifest(manifest_bytes=manifest_bytes)
        wheel_path: Path = cls._resolve_local_wheel_path(manifest=manifest)
        cls._verify_wheel_file(wheel_path=wheel_path, manifest=manifest)
        return SlotuiCoreInstallationPlanDAO(
            distribution_name=manifest.distribution_name,
            version=manifest.version,
            wheel_path=wheel_path,
            manifest=manifest,
            argv=(
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                str(wheel_path),
            ),
        )

    @staticmethod
    def _read_verified_manifest_bytes(*, reference: SlotuiCoreArtifactReferenceDAO) -> bytes:
        """Read manifest bytes and reject a missing, non-file, or digest-mismatched proof.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Immutable local manifest reference.

        Returns:
            bytes: Exact verified manifest bytes.

        Raises:
            SlotuiCoreVerificationError: If the reference cannot prove immutable bytes.
        """
        manifest_path: Path = reference.manifest_path.resolve()
        if not manifest_path.is_file():
            raise SlotuiCoreVerificationError("Slotui core manifest is unavailable or is not a regular file")
        manifest_bytes: bytes = manifest_path.read_bytes()
        actual_sha256: str = hashlib.sha256(manifest_bytes).hexdigest()
        if actual_sha256 != reference.manifest_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui core manifest SHA-256 does not match the pinned reference"
            )
        return manifest_bytes

    @staticmethod
    def _parse_manifest(*, manifest_bytes: bytes) -> SlotuiCoreManifestDAO:
        """Parse strict typed manifest bytes without discovering any Python package.

        Args:
            manifest_bytes (bytes): Digest-verified core release manifest bytes.

        Returns:
            SlotuiCoreManifestDAO: Fully validated release manifest.

        Raises:
            SlotuiCoreVerificationError: If bytes are not the exact allowed schema.
        """
        try:
            payload: object = json.loads(manifest_bytes.decode("utf-8"))
            return SlotuiCoreManifestDAO.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise SlotuiCoreVerificationError("Slotui core manifest has an invalid typed schema") from error

    @staticmethod
    def _resolve_local_wheel_path(*, manifest: SlotuiCoreManifestDAO) -> Path:
        """Resolve only an absolute file URL or absolute local wheel path.

        Args:
            manifest (SlotuiCoreManifestDAO): Typed artifact declaration.

        Returns:
            Path: Resolved local candidate wheel path.

        Raises:
            SlotuiCoreVerificationError: If the declaration can reach source, VCS, or a registry.
        """
        source: str = manifest.wheel_artifact["source"]
        if source.startswith("file://"):
            parsed = urlparse(source)
            if parsed.netloc not in ("", "localhost"):
                raise SlotuiCoreVerificationError(
                    "Slotui core requires a local wheel artifact, not a remote file URL"
                )
            wheel_path: Path = Path(unquote(parsed.path))
        else:
            wheel_path = Path(source)
        if not wheel_path.is_absolute():
            raise SlotuiCoreVerificationError("Slotui core requires an absolute local wheel artifact path")
        if wheel_path.suffix != ".whl":
            raise SlotuiCoreVerificationError(
                "Slotui core requires a local wheel artifact, never a source checkout"
            )
        return wheel_path

    @classmethod
    def _verify_wheel_file(cls, *, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Verify the exact regular wheel file, digest, and core package metadata.

        Args:
            wheel_path (Path): Local artifact path allowed by the manifest.
            manifest (SlotuiCoreManifestDAO): Typed exact artifact contract.

        Raises:
            SlotuiCoreVerificationError: If artifact bytes or wheel metadata are untrusted.
        """
        cls._require_regular_wheel(wheel_path=wheel_path)
        cls._require_exact_filename(wheel_path=wheel_path, manifest=manifest)
        cls._require_exact_sha256(wheel_path=wheel_path, manifest=manifest)
        cls._require_wheel_metadata(wheel_path=wheel_path, manifest=manifest)

    @staticmethod
    def _require_regular_wheel(*, wheel_path: Path) -> None:
        """Reject absent directories, symlinks, and non-zip files before metadata parsing.

        Args:
            wheel_path (Path): Candidate local artifact.

        Raises:
            SlotuiCoreVerificationError: If the artifact is not a regular zip wheel.
        """
        if not wheel_path.is_file() or wheel_path.is_symlink() or not zipfile.is_zipfile(wheel_path):
            raise SlotuiCoreVerificationError("Slotui core artifact must be a regular valid zip wheel")

    @staticmethod
    def _require_exact_filename(*, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Reject a local wheel whose filename differs from the release manifest.

        Args:
            wheel_path (Path): Candidate wheel.
            manifest (SlotuiCoreManifestDAO): Expected exact filename.

        Raises:
            SlotuiCoreVerificationError: If artifact identity can drift.
        """
        if wheel_path.name != manifest.wheel_filename:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel filename does not match the release manifest"
            )

    @staticmethod
    def _require_exact_sha256(*, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Reject a local wheel whose bytes differ from the release manifest digest.

        Args:
            wheel_path (Path): Candidate wheel.
            manifest (SlotuiCoreManifestDAO): Expected artifact digest.

        Raises:
            SlotuiCoreVerificationError: If the artifact bytes are not pinned.
        """
        actual_sha256: str = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        if actual_sha256 != manifest.wheel_sha256:
            raise SlotuiCoreVerificationError("Slotui core wheel SHA-256 does not match the release manifest")

    @staticmethod
    def _require_wheel_metadata(*, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Require the declared package name and version from wheel metadata.

        Args:
            wheel_path (Path): Digest-verified local wheel.
            manifest (SlotuiCoreManifestDAO): Expected core distribution identity.

        Raises:
            SlotuiCoreVerificationError: If package metadata does not exactly identify core.
        """
        try:
            with zipfile.ZipFile(wheel_path) as archive:
                metadata_name: str = next(
                    name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
                )
                metadata: str = archive.read(metadata_name).decode("utf-8")
        except (KeyError, StopIteration, UnicodeDecodeError, zipfile.BadZipFile) as error:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel lacks readable distribution metadata"
            ) from error
        fields: dict[str, str] = {
            key.strip(): value.strip()
            for line in metadata.splitlines()
            if ":" in line
            for key, value in [line.split(":", maxsplit=1)]
        }
        if fields.get("Name") != manifest.distribution_name:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel METADATA name does not match the release manifest"
            )
        if fields.get("Version") != manifest.version:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel METADATA version does not match the release manifest"
            )
