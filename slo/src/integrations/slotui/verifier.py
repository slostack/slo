"""Fail-closed static verification of a future Slotui core adapter fixture.

This consumer scaffold verifies bytes and Python source stored in a wheel archive.
It never imports Slotui, never installs a wheel, and does not claim clean-venv execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from email.parser import Parser
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from src.integrations.slotui.dao import (
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreManifestDAO,
    SlotuiCoreVerificationReceiptDAO,
)

__all__ = ["SlotuiCoreVerificationError", "SlotuiCoreWheelVerificationService"]


class SlotuiCoreVerificationError(ValueError):
    """Report a rejected Slotui core adapter fixture before package execution."""


class SlotuiCoreWheelVerificationService:
    """Statically verify exact local core wheel bytes against Slo's adapter fixture contract."""

    @classmethod
    def build_verification_receipt(
        cls,
        *,
        reference: SlotuiCoreArtifactReferenceDAO,
    ) -> SlotuiCoreVerificationReceiptDAO:
        """Verify a manifest and wheel without installation, import, or runtime assembly.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Absolute manifest path plus byte digest.

        Returns:
            SlotuiCoreVerificationReceiptDAO: Static proof consumed only by the unavailable selector path.

        Raises:
            SlotuiCoreVerificationError: If a fixture byte, contract, archive, or export proof fails.
        """
        manifest_bytes: bytes = cls._read_verified_manifest_bytes(reference=reference)
        manifest: SlotuiCoreManifestDAO = cls._parse_manifest(manifest_bytes=manifest_bytes)
        wheel_path: Path = cls._resolve_local_wheel_path(manifest=manifest)
        cls._verify_wheel_file(wheel_path=wheel_path, manifest=manifest)
        return SlotuiCoreVerificationReceiptDAO(
            distribution_name=manifest.distribution_name,
            version=manifest.version,
            wheel_path=wheel_path,
            manifest=manifest,
        )

    @staticmethod
    def _read_verified_manifest_bytes(*, reference: SlotuiCoreArtifactReferenceDAO) -> bytes:
        """Read manifest bytes and reject a missing, non-file, or digest-mismatched reference.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Immutable local adapter-fixture reference.

        Returns:
            bytes: Exact reference-pinned manifest bytes.

        Raises:
            SlotuiCoreVerificationError: If Slo cannot prove the referenced bytes.
        """
        manifest_path: Path = reference.manifest_path.resolve()
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise SlotuiCoreVerificationError(
                "Slotui adapter fixture manifest is unavailable or is not a regular file"
            )
        manifest_bytes: bytes = manifest_path.read_bytes()
        actual_sha256: str = hashlib.sha256(manifest_bytes).hexdigest()
        if actual_sha256 != reference.manifest_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui adapter fixture manifest SHA-256 does not match the pinned reference"
            )
        return manifest_bytes

    @staticmethod
    def _parse_manifest(*, manifest_bytes: bytes) -> SlotuiCoreManifestDAO:
        """Parse and prove a strict canonical adapter-fixture manifest before wheel access.

        Args:
            manifest_bytes (bytes): Digest-verified local manifest bytes.

        Returns:
            SlotuiCoreManifestDAO: Strict manifest whose self hash has also been verified.

        Raises:
            SlotuiCoreVerificationError: If bytes are invalid, non-canonical, or inconsistent.
        """
        try:
            payload: object = json.loads(manifest_bytes.decode("utf-8"))
            manifest: SlotuiCoreManifestDAO = SlotuiCoreManifestDAO.model_validate(payload)
            canonical_bytes: bytes = json.dumps(
                manifest.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if manifest_bytes != canonical_bytes:
                raise ValueError("Slotui adapter fixture manifest bytes must be canonical JSON")
            manifest.require_canonical_manifest_hash()
            return manifest
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise SlotuiCoreVerificationError(
                "Slotui adapter fixture manifest has an invalid canonical typed schema or projection hash"
            ) from error

    @staticmethod
    def _resolve_local_wheel_path(*, manifest: SlotuiCoreManifestDAO) -> Path:
        """Resolve only an absolute local file URL or absolute wheel path.

        Args:
            manifest (SlotuiCoreManifestDAO): Typed adapter-fixture artifact declaration.

        Returns:
            Path: Unresolved local candidate path, preserving symlink checks.

        Raises:
            SlotuiCoreVerificationError: If the declaration can select source, VCS, or a registry.
        """
        source: str = manifest.wheel_artifact["source"]
        if source.startswith("file://"):
            parsed = urlparse(source)
            if parsed.netloc not in ("", "localhost"):
                raise SlotuiCoreVerificationError(
                    "Slotui adapter fixture requires a local wheel artifact, not a remote file URL"
                )
            wheel_path: Path = Path(unquote(parsed.path))
        else:
            wheel_path = Path(source)
        if not wheel_path.is_absolute():
            raise SlotuiCoreVerificationError(
                "Slotui adapter fixture requires an absolute local wheel artifact path"
            )
        if wheel_path.suffix != ".whl":
            raise SlotuiCoreVerificationError(
                "Slotui adapter fixture requires a local wheel artifact, never a source checkout"
            )
        return wheel_path

    @classmethod
    def _verify_wheel_file(cls, *, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Verify exact archive bytes, metadata, package boundary, and static export declarations.

        Args:
            wheel_path (Path): Candidate local wheel.
            manifest (SlotuiCoreManifestDAO): Strict expected adapter-fixture contract.

        Raises:
            SlotuiCoreVerificationError: If artifact bytes, archive contents, or source declarations are untrusted.
        """
        cls._require_regular_wheel(wheel_path=wheel_path)
        cls._require_exact_filename(wheel_path=wheel_path, manifest=manifest)
        cls._require_exact_sha256(wheel_path=wheel_path, manifest=manifest)
        with zipfile.ZipFile(wheel_path) as archive:
            archive_names: tuple[str, ...] = tuple(archive.namelist())
            cls._require_safe_archive_members(archive_names=archive_names)
            cls._require_wheel_metadata(archive=archive, manifest=manifest)
            cls._require_only_slotui_package_files(archive_names=archive_names)
            cls._require_declared_exports(archive=archive, manifest=manifest)

    @staticmethod
    def _require_regular_wheel(*, wheel_path: Path) -> None:
        """Reject absent directories, symlinks, and non-zip files before archive parsing.

        Args:
            wheel_path (Path): Candidate local artifact.

        Raises:
            SlotuiCoreVerificationError: If the artifact is not a regular zip wheel.
        """
        if not wheel_path.is_file() or wheel_path.is_symlink() or not zipfile.is_zipfile(wheel_path):
            raise SlotuiCoreVerificationError("Slotui core artifact must be a regular valid zip wheel")

    @staticmethod
    def _require_exact_filename(*, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Reject a local wheel whose filename differs from the adapter fixture.

        Args:
            wheel_path (Path): Candidate wheel.
            manifest (SlotuiCoreManifestDAO): Expected exact filename.

        Raises:
            SlotuiCoreVerificationError: If artifact identity can drift.
        """
        if wheel_path.name != manifest.wheel_filename:
            raise SlotuiCoreVerificationError("Slotui core wheel filename does not match the adapter fixture")

    @staticmethod
    def _require_exact_sha256(*, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Reject wheel bytes that differ from the declared artifact digest.

        Args:
            wheel_path (Path): Candidate wheel.
            manifest (SlotuiCoreManifestDAO): Expected artifact digest.

        Raises:
            SlotuiCoreVerificationError: If artifact bytes are not pinned.
        """
        actual_sha256: str = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        if actual_sha256 != manifest.wheel_sha256:
            raise SlotuiCoreVerificationError("Slotui core wheel SHA-256 does not match the adapter fixture")

    @staticmethod
    def _require_safe_archive_members(*, archive_names: tuple[str, ...]) -> None:
        """Reject duplicate, absolute, parent-traversal, and directory archive entries.

        Args:
            archive_names (tuple[str, ...]): Exact ZIP member names.

        Raises:
            SlotuiCoreVerificationError: If archive member identity or confinement is ambiguous.
        """
        if len(set(archive_names)) != len(archive_names):
            raise SlotuiCoreVerificationError("Slotui core wheel archive may not contain duplicate members")
        if any(
            name.endswith("/") or name.startswith("/") or ".." in Path(name).parts for name in archive_names
        ):
            raise SlotuiCoreVerificationError("Slotui core wheel archive contains an unsafe member path")

    @staticmethod
    def _require_wheel_metadata(*, archive: zipfile.ZipFile, manifest: SlotuiCoreManifestDAO) -> None:
        """Require exact distribution name, version, and Python requirement in wheel metadata.

        Args:
            archive (zipfile.ZipFile): Already digest-verified local wheel archive.
            manifest (SlotuiCoreManifestDAO): Expected distribution and metadata contract.

        Raises:
            SlotuiCoreVerificationError: If package metadata does not exactly identify generic core.
        """
        metadata_names: tuple[str, ...] = tuple(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            raise SlotuiCoreVerificationError("Slotui core wheel must contain exactly one METADATA file")
        try:
            metadata: str = archive.read(metadata_names[0]).decode("utf-8")
        except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as error:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel lacks readable distribution metadata"
            ) from error
        fields = Parser().parsestr(metadata)
        if fields.get("Name") != manifest.distribution_name:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel METADATA name does not match the adapter fixture"
            )
        if fields.get("Version") != manifest.version:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel METADATA version does not match the adapter fixture"
            )
        if fields.get("Requires-Python") != manifest.requires_python:
            raise SlotuiCoreVerificationError(
                "Slotui core wheel METADATA Requires-Python does not match the adapter fixture"
            )

    @staticmethod
    def _require_only_slotui_package_files(*, archive_names: tuple[str, ...]) -> None:
        """Reject Python packages outside ``slotui`` while allowing wheel metadata only.

        Args:
            archive_names (tuple[str, ...]): Exact archive members after path validation.

        Raises:
            SlotuiCoreVerificationError: If the core artifact embeds an unexpected Python package.
        """
        python_members: tuple[str, ...] = tuple(name for name in archive_names if name.endswith(".py"))
        if not python_members or any(not name.startswith("slotui/") for name in python_members):
            raise SlotuiCoreVerificationError(
                "Slotui core wheel contains Python files outside the expected slotui package"
            )

    @classmethod
    def _require_declared_exports(cls, *, archive: zipfile.ZipFile, manifest: SlotuiCoreManifestDAO) -> None:
        """Prove every manifest export exists at its named module using static AST inspection.

        Args:
            archive (zipfile.ZipFile): Static wheel archive; never imported.
            manifest (SlotuiCoreManifestDAO): Immutable module-qualified export signature.

        Raises:
            SlotuiCoreVerificationError: If a named module or symbol is unavailable in wheel source.
        """
        for declaration in manifest.immutable_core_export_signature:
            module_source: str = cls._read_module_source(archive=archive, module=declaration.module)
            if not cls._module_defines_symbol(source=module_source, symbol=declaration.symbol):
                raise SlotuiCoreVerificationError(
                    f"Slotui core wheel is missing declared export {declaration.declaration}"
                )

    @staticmethod
    def _read_module_source(*, archive: zipfile.ZipFile, module: str) -> str:
        """Read one explicitly declared Slotui module source without importing it.

        Args:
            archive (zipfile.ZipFile): Static wheel archive.
            module (str): Explicit dotted Slotui module from the manifest signature.

        Returns:
            str: UTF-8 source text for the declared module.

        Raises:
            SlotuiCoreVerificationError: If the declared module file is absent or unreadable.
        """
        module_path: str = module.replace(".", "/")
        candidates: tuple[str, ...] = (f"{module_path}.py", f"{module_path}/__init__.py")
        matching_names: tuple[str, ...] = tuple(name for name in candidates if name in archive.namelist())
        if len(matching_names) != 1:
            raise SlotuiCoreVerificationError(f"Slotui core wheel is missing declared module {module}")
        try:
            return archive.read(matching_names[0]).decode("utf-8")
        except (KeyError, UnicodeDecodeError) as error:
            raise SlotuiCoreVerificationError(
                f"Slotui core wheel has unreadable declared module {module}"
            ) from error

    @staticmethod
    def _module_defines_symbol(*, source: str, symbol: str) -> bool:
        """Determine whether module source statically declares a named public symbol.

        Args:
            source (str): UTF-8 module source read directly from the wheel.
            symbol (str): Required module-level public symbol.

        Returns:
            bool: ``True`` only for a class, function, async function, or assignment declaration.

        Raises:
            SlotuiCoreVerificationError: If static source syntax is invalid.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError("Slotui core wheel contains invalid Python source") from error
        for node in tree.body:
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == symbol
            ):
                return True
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and _assignment_defines_symbol(
                node=node, symbol=symbol
            ):
                return True
        return False


def _assignment_defines_symbol(*, node: ast.Assign | ast.AnnAssign, symbol: str) -> bool:
    """Determine whether a top-level source assignment defines the required symbol.

    Args:
        node (ast.Assign | ast.AnnAssign): Parsed module-level assignment node.
        symbol (str): Required symbol name.

    Returns:
        bool: ``True`` if the assignment directly declares the required name.
    """
    targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(target, ast.Name) and target.id == symbol for target in targets)
