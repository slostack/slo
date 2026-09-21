"""Fail-closed static verification for a versioned Slotui candidate adapter wheel.

Verification reads ZIP source and AST only.  It never imports, installs, or
infers candidate runtime constructors from ordinary exports.
"""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from email.message import Message
from email.parser import Parser
from pathlib import Path
from urllib.parse import unquote, urlparse

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import ValidationError

from src.integrations.slotui.dao import (
    SlotuiCandidateAdapterDAO,
    SlotuiCandidateRunnerDAO,
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreBundleDAO,
    SlotuiCoreBundleWheelDAO,
    SlotuiCoreManifestDAO,
    SlotuiCoreVerificationReceiptDAO,
)

__all__ = ["SlotuiCoreVerificationError", "SlotuiCoreWheelVerificationService"]


class SlotuiCoreVerificationError(ValueError):
    """Report an untrusted candidate before package execution."""


class SlotuiCoreWheelVerificationService:
    """Statically verify exact candidate wheel bytes and one adapter entrypoint."""

    @classmethod
    def build_verification_receipt(
        cls, *, reference: SlotuiCoreArtifactReferenceDAO
    ) -> SlotuiCoreVerificationReceiptDAO:
        """Verify a manifest/wheel without candidate installation or import.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Absolute digest-pinned release reference.

        Returns:
            SlotuiCoreVerificationReceiptDAO: Static proof used by the isolated host process.

        Raises:
            SlotuiCoreVerificationError: If bytes, metadata, exports, or adapter contract fail.
        """
        bundle_path: Path = reference.bundle_path
        bundle_bytes: bytes = cls._read_verified_bundle_bytes(reference=reference, bundle_path=bundle_path)
        bundle: SlotuiCoreBundleDAO = cls._parse_bundle(bundle_bytes=bundle_bytes)
        manifest_bytes: bytes = cls._read_verified_manifest_bytes(
            reference=reference,
            bundle=bundle,
            bundle_path=bundle_path,
        )
        manifest: SlotuiCoreManifestDAO = cls._parse_manifest(manifest_bytes=manifest_bytes)
        wheel_path: Path = cls._resolve_local_wheel_path(manifest=manifest)
        cls._verify_bundle_relationship(
            reference=reference,
            bundle=bundle,
            manifest=manifest,
            wheel_path=wheel_path,
            bundle_path=bundle_path,
        )
        verified_wheel_paths: tuple[Path, ...] = cls._verify_bundle_wheel_closure(
            bundle=bundle,
            artifact_directory=bundle_path.parent,
        )
        cls._verify_wheel_file(wheel_path=wheel_path, manifest=manifest)
        cls._verify_complete_offline_dependency_closure(
            bundle=bundle,
            verified_wheel_paths=verified_wheel_paths,
        )
        return SlotuiCoreVerificationReceiptDAO(
            distribution_name=manifest.distribution_name,
            version=manifest.version,
            wheel_path=wheel_path,
            verified_wheel_paths=verified_wheel_paths,
            manifest=manifest,
        )

    @staticmethod
    def _read_verified_bundle_bytes(*, reference: SlotuiCoreArtifactReferenceDAO, bundle_path: Path) -> bytes:
        """Read one exact regular bundle file before trusting its closure declarations.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Release reference pinning the bundle.

        Returns:
            bytes: Exact canonical bundle bytes.

        Raises:
            SlotuiCoreVerificationError: If the pinned local bundle cannot be proven exact.
        """
        if not bundle_path.is_absolute() or not bundle_path.is_file() or bundle_path.is_symlink():
            raise SlotuiCoreVerificationError(
                "Slotui candidate bundle is unavailable or is not a regular absolute file"
            )
        bundle_bytes: bytes = bundle_path.read_bytes()
        if hashlib.sha256(bundle_bytes).hexdigest() != reference.bundle_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui candidate bundle SHA-256 does not match the pinned reference"
            )
        return bundle_bytes

    @staticmethod
    def _parse_bundle(*, bundle_bytes: bytes) -> SlotuiCoreBundleDAO:
        """Parse a canonical complete local offline wheel closure declaration.

        Args:
            bundle_bytes (bytes): Exact bundle bytes pinned by the reference.

        Returns:
            SlotuiCoreBundleDAO: Strict typed immutable dependency closure.

        Raises:
            SlotuiCoreVerificationError: If bundle bytes are malformed, noncanonical, or incomplete.
        """
        try:
            payload: object = json.loads(bundle_bytes.decode("utf-8"))
            bundle: SlotuiCoreBundleDAO = SlotuiCoreBundleDAO.model_validate(payload)
            canonical: bytes = json.dumps(
                bundle.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if bundle_bytes != canonical:
                raise ValueError("candidate bundle bytes must be canonical JSON")
            return bundle
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate bundle has an invalid canonical typed schema or wheel closure"
            ) from error

    @staticmethod
    def _read_verified_manifest_bytes(
        *, reference: SlotuiCoreArtifactReferenceDAO, bundle: SlotuiCoreBundleDAO, bundle_path: Path
    ) -> bytes:
        """Read only one pinned regular manifest file.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Candidate manifest pointer and byte digest.

        Returns:
            bytes: Exact manifest bytes.

        Raises:
            SlotuiCoreVerificationError: If manifest location or digest is invalid.
        """
        manifest_path: Path = reference.manifest_path
        if manifest_path.parent != bundle_path.parent:
            raise SlotuiCoreVerificationError(
                "Slotui candidate manifest must be colocated with its pinned bundle"
            )
        if manifest_path.name != bundle.slo_adapter_manifest.filename:
            raise SlotuiCoreVerificationError(
                "Slotui candidate bundle manifest filename does not match the reference"
            )
        if not manifest_path.is_absolute() or not manifest_path.is_file() or manifest_path.is_symlink():
            raise SlotuiCoreVerificationError(
                "Slotui candidate manifest is unavailable or is not a regular absolute file"
            )
        manifest_bytes: bytes = manifest_path.read_bytes()
        actual_sha256: str = hashlib.sha256(manifest_bytes).hexdigest()
        if actual_sha256 != reference.manifest_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui candidate manifest SHA-256 does not match the pinned reference"
            )
        if actual_sha256 != bundle.slo_adapter_manifest.sha256:
            raise SlotuiCoreVerificationError(
                "Slotui candidate manifest SHA-256 does not match the pinned bundle"
            )
        return manifest_bytes

    @staticmethod
    def _parse_manifest(*, manifest_bytes: bytes) -> SlotuiCoreManifestDAO:
        """Parse canonical typed manifest and verify its non-self projection.

        Args:
            manifest_bytes (bytes): Reference-pinned bytes.

        Returns:
            SlotuiCoreManifestDAO: Validated candidate manifest.

        Raises:
            SlotuiCoreVerificationError: If bytes are malformed or inconsistent.
        """
        try:
            payload: object = json.loads(manifest_bytes.decode("utf-8"))
            manifest: SlotuiCoreManifestDAO = SlotuiCoreManifestDAO.model_validate(payload)
            canonical: bytes = json.dumps(
                manifest.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if manifest_bytes != canonical:
                raise ValueError("candidate manifest bytes must be canonical JSON")
            manifest.require_canonical_manifest_hash()
            return manifest
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate manifest has an invalid canonical typed schema or projection hash"
            ) from error

    @classmethod
    def _verify_bundle_relationship(
        cls,
        *,
        reference: SlotuiCoreArtifactReferenceDAO,
        bundle: SlotuiCoreBundleDAO,
        manifest: SlotuiCoreManifestDAO,
        wheel_path: Path,
        bundle_path: Path,
    ) -> None:
        """Prove reference, bundle, manifest, source identity, and core wheel agree.

        Args:
            reference (SlotuiCoreArtifactReferenceDAO): Top-level immutable release pointer.
            bundle (SlotuiCoreBundleDAO): Complete offline dependency closure.
            manifest (SlotuiCoreManifestDAO): Candidate adapter contract.
            wheel_path (Path): Manifest-declared core wheel location.

        Raises:
            SlotuiCoreVerificationError: If release artifacts name inconsistent identities.
        """
        if bundle.requires_python != manifest.requires_python:
            raise SlotuiCoreVerificationError(
                "Slotui bundle Requires-Python does not match the candidate manifest"
            )
        if bundle.source_identity.commit != manifest.source_identity.commit:
            raise SlotuiCoreVerificationError(
                "Slotui bundle source commit does not match the candidate manifest"
            )
        if bundle.candidate.label != reference.candidate_label:
            raise SlotuiCoreVerificationError("Slotui bundle candidate label does not match the reference")
        core_wheel: SlotuiCoreBundleWheelDAO = next(wheel for wheel in bundle.wheels if wheel.role == "core")
        if (
            wheel_path.parent != bundle_path.parent
            or core_wheel.filename != manifest.wheel_filename
            or core_wheel.sha256 != manifest.wheel_sha256
            or core_wheel.distribution_name != manifest.distribution_name
        ):
            raise SlotuiCoreVerificationError(
                "Slotui bundle core wheel does not exactly match the candidate manifest"
            )

    @staticmethod
    def _verify_bundle_wheel_closure(
        *, bundle: SlotuiCoreBundleDAO, artifact_directory: Path
    ) -> tuple[Path, ...]:
        """Verify every declared offline wheel is a regular exact file in the artifact directory.

        Args:
            bundle (SlotuiCoreBundleDAO): Complete declared dependency closure.
            artifact_directory (Path): Only allowed directory containing dependency wheels.

        Returns:
            tuple[Path, ...]: Exact verified wheel paths in declared bundle order.

        Raises:
            SlotuiCoreVerificationError: If a dependency is absent, linked, renamed, or tampered.
        """
        verified_wheel_paths: list[Path] = []
        for wheel in bundle.wheels:
            wheel_path: Path = artifact_directory / wheel.filename
            if not wheel_path.is_file() or wheel_path.is_symlink():
                raise SlotuiCoreVerificationError(
                    f"Slotui bundle wheel is unavailable or is not a regular file: {wheel.filename}"
                )
            if hashlib.sha256(wheel_path.read_bytes()).hexdigest() != wheel.sha256:
                raise SlotuiCoreVerificationError(
                    f"Slotui bundle wheel SHA-256 does not match: {wheel.filename}"
                )
            verified_wheel_paths.append(wheel_path)
        return tuple(verified_wheel_paths)

    @classmethod
    def _verify_complete_offline_dependency_closure(
        cls,
        *,
        bundle: SlotuiCoreBundleDAO,
        verified_wheel_paths: tuple[Path, ...],
    ) -> None:
        """Prove the declared wheels are exactly the active Python 3.11/Linux dependency graph.

        Args:
            bundle (SlotuiCoreBundleDAO): Typed exact bundle declarations.
            verified_wheel_paths (tuple[Path, ...]): Hash-verified paths matching the declarations.

        Raises:
            SlotuiCoreVerificationError: If active requirements are unavailable, incompatible, or over-declared.
        """
        metadata_by_distribution: dict[str, Message] = cls._read_bundle_wheel_metadata(
            verified_wheel_paths=verified_wheel_paths
        )
        requirements_by_distribution: dict[str, tuple[Requirement, ...]] = {
            distribution_name: cls._read_active_requirements(metadata=metadata)
            for distribution_name, metadata in metadata_by_distribution.items()
        }
        cls._require_bundle_declarations_match_wheel_metadata(
            bundle=bundle,
            metadata_by_distribution=metadata_by_distribution,
        )
        versions_by_distribution: dict[str, Version] = {
            distribution_name: cls._read_metadata_version(
                metadata=metadata,
                distribution_name=distribution_name,
            )
            for distribution_name, metadata in metadata_by_distribution.items()
        }
        bundle_distributions: set[str] = {
            canonicalize_name(wheel.distribution_name) for wheel in bundle.wheels
        }
        core_distribution: str = canonicalize_name("slotui")
        active_distributions: set[str] = cls._derive_active_dependency_closure(
            root_distribution=core_distribution,
            requirements_by_distribution=requirements_by_distribution,
            versions_by_distribution=versions_by_distribution,
        )
        if active_distributions != bundle_distributions:
            missing_distributions: list[str] = sorted(active_distributions - bundle_distributions)
            extra_distributions: list[str] = sorted(bundle_distributions - active_distributions)
            if missing_distributions:
                raise SlotuiCoreVerificationError(
                    "Slotui required dependency is absent from the declared bundle: "
                    + ", ".join(missing_distributions)
                )
            raise SlotuiCoreVerificationError(
                "Slotui bundle contains undeclared active dependency closure wheel(s): "
                + ", ".join(extra_distributions)
            )

    @classmethod
    def _require_bundle_declarations_match_wheel_metadata(
        cls,
        *,
        bundle: SlotuiCoreBundleDAO,
        metadata_by_distribution: dict[str, Message],
    ) -> None:
        """Require every bundle declaration to name the distribution inside its exact wheel.

        Args:
            bundle (SlotuiCoreBundleDAO): Typed bundle declarations.
            metadata_by_distribution (dict[str, Message]): Exact wheel metadata keyed by actual name.

        Raises:
            SlotuiCoreVerificationError: If a declaration and wheel identity diverge.
        """
        declared_distributions: set[str] = {
            canonicalize_name(wheel.distribution_name) for wheel in bundle.wheels
        }
        if declared_distributions == set(metadata_by_distribution):
            return
        raise SlotuiCoreVerificationError(
            "Slotui bundle declarations do not match wheel METADATA distributions"
        )

    @classmethod
    def _derive_active_dependency_closure(
        cls,
        *,
        root_distribution: str,
        requirements_by_distribution: dict[str, tuple[Requirement, ...]],
        versions_by_distribution: dict[str, Version],
    ) -> set[str]:
        """Traverse active wheel requirements from the core distribution without resolver fallback.

        Args:
            root_distribution (str): Canonical core distribution name.
            requirements_by_distribution (dict[str, tuple[Requirement, ...]]): Parsed active requirements.

        Returns:
            set[str]: Canonical distributions reachable from the core, including the core.

        Raises:
            SlotuiCoreVerificationError: If a reachable dependency wheel is missing or version-incompatible.
        """
        active_distributions: set[str] = set()
        pending_distributions: list[str] = [root_distribution]
        while pending_distributions:
            distribution_name: str = pending_distributions.pop()
            if distribution_name in active_distributions:
                continue
            requirements: tuple[Requirement, ...] | None = requirements_by_distribution.get(distribution_name)
            if requirements is None:
                raise SlotuiCoreVerificationError(
                    f"Slotui required dependency is absent from the declared bundle: {distribution_name}"
                )
            active_distributions.add(distribution_name)
            for requirement in requirements:
                dependency_name: str = canonicalize_name(requirement.name)
                cls._require_declared_requirement_is_satisfied(
                    requirement=requirement,
                    dependency_name=dependency_name,
                    requirements_by_distribution=requirements_by_distribution,
                    versions_by_distribution=versions_by_distribution,
                )
                pending_distributions.append(dependency_name)
        return active_distributions

    @classmethod
    def _require_declared_requirement_is_satisfied(
        cls,
        *,
        requirement: Requirement,
        dependency_name: str,
        requirements_by_distribution: dict[str, tuple[Requirement, ...]],
        versions_by_distribution: dict[str, Version],
    ) -> None:
        """Require a declared wheel to satisfy one active requirement without index resolution.

        Args:
            requirement (Requirement): Active PEP 508 requirement from wheel metadata.
            dependency_name (str): Canonical distribution required by the metadata.
            requirements_by_distribution (dict[str, tuple[Requirement, ...]]): Declared wheel graph.

        Raises:
            SlotuiCoreVerificationError: If no declared wheel can satisfy the active requirement.
        """
        if dependency_name not in requirements_by_distribution:
            raise SlotuiCoreVerificationError(
                f"Slotui required dependency is absent from the declared bundle: {dependency_name}"
            )
        dependency_version: Version = versions_by_distribution[dependency_name]
        if requirement.specifier.contains(dependency_version, prereleases=True):
            return
        raise SlotuiCoreVerificationError(
            "Slotui declared dependency wheel does not satisfy active requirement: "
            f"{requirement} (found {dependency_name}=={dependency_version})"
        )

    @classmethod
    def _read_active_requirements(cls, *, metadata: Message) -> tuple[Requirement, ...]:
        """Parse active PEP 508 requirements from one wheel's sole METADATA file.

        Args:
            metadata (Message): Parsed exact wheel metadata.

        Returns:
            tuple[Requirement, ...]: Requirements whose markers are true for Python 3.11/Linux.

        Raises:
            SlotuiCoreVerificationError: If metadata has invalid requirement syntax.
        """
        requirements: list[Requirement] = []
        for raw_requirement in metadata.get_all("Requires-Dist", []):
            try:
                requirement: Requirement = Requirement(raw_requirement)
            except InvalidRequirement as error:
                raise SlotuiCoreVerificationError(
                    f"Slotui wheel has invalid Requires-Dist metadata: {raw_requirement}"
                ) from error
            if requirement.marker is None or requirement.marker.evaluate(
                environment=cls._target_environment()
            ):
                requirements.append(requirement)
        return tuple(requirements)

    @staticmethod
    def _target_environment() -> dict[str, str]:
        """Build the fixed candidate-venv marker environment.

        Returns:
            dict[str, str]: Python 3.11/Linux marker variables used for offline closure proof.
        """
        environment: dict[str, str] = {name: str(value) for name, value in default_environment().items()}
        environment.update(
            {
                "implementation_name": "cpython",
                "implementation_version": "3.11.0",
                "os_name": "posix",
                "platform_python_implementation": "CPython",
                "platform_system": "Linux",
                "python_full_version": "3.11.0",
                "python_version": "3.11",
                "sys_platform": "linux",
            }
        )
        return environment

    @classmethod
    def _read_bundle_wheel_metadata(cls, *, verified_wheel_paths: tuple[Path, ...]) -> dict[str, Message]:
        """Read and normalize each verified wheel's unique distribution metadata.

        Args:
            verified_wheel_paths (tuple[Path, ...]): Exact hash-verified wheel archives.

        Returns:
            dict[str, Message]: Metadata indexed by canonical distribution name.

        Raises:
            SlotuiCoreVerificationError: If wheel metadata has no name or duplicates a distribution.
        """
        metadata_by_distribution: dict[str, Message] = {}
        for wheel_path in verified_wheel_paths:
            metadata: Message = cls._read_wheel_metadata(wheel_path=wheel_path)
            distribution_name: str | None = metadata.get("Name")
            if distribution_name is None:
                raise SlotuiCoreVerificationError("Slotui wheel METADATA is missing Name")
            canonical_name: str = canonicalize_name(distribution_name)
            if canonical_name in metadata_by_distribution:
                raise SlotuiCoreVerificationError(
                    f"Slotui bundle wheel metadata duplicates distribution: {canonical_name}"
                )
            metadata_by_distribution[canonical_name] = metadata
        return metadata_by_distribution

    @staticmethod
    def _read_metadata_version(*, metadata: Message, distribution_name: str) -> Version:
        """Parse one required PEP 440 metadata version.

        Args:
            metadata (Message): Parsed exact wheel metadata.
            distribution_name (str): Canonical distribution named in failure output.

        Returns:
            Version: Parsed declared distribution version.

        Raises:
            SlotuiCoreVerificationError: If the metadata version is absent or invalid.
        """
        version_text: str | None = metadata.get("Version")
        if version_text is None:
            raise SlotuiCoreVerificationError(
                f"Slotui wheel METADATA is missing Version: {distribution_name}"
            )
        try:
            return Version(version_text)
        except InvalidVersion as error:
            raise SlotuiCoreVerificationError(
                f"Slotui wheel METADATA has invalid Version: {distribution_name}"
            ) from error

    @classmethod
    def _read_wheel_metadata(cls, *, wheel_path: Path) -> Message:
        """Read the one METADATA record needed for offline dependency verification.

        Args:
            wheel_path (Path): Exact verified wheel archive.

        Returns:
            Message: Parsed immutable wheel distribution metadata.

        Raises:
            SlotuiCoreVerificationError: If the wheel lacks one readable METADATA record.
        """
        with zipfile.ZipFile(wheel_path) as archive:
            metadata_paths: tuple[str, ...] = tuple(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            if len(metadata_paths) != 1:
                raise SlotuiCoreVerificationError("Slotui wheel must contain exactly one METADATA file")
            try:
                return Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
            except (KeyError, UnicodeDecodeError) as error:
                raise SlotuiCoreVerificationError("Slotui wheel has unreadable METADATA") from error

    @staticmethod
    def _resolve_local_wheel_path(*, manifest: SlotuiCoreManifestDAO) -> Path:
        """Resolve only an absolute local wheel path or local file URL.

        Args:
            manifest (SlotuiCoreManifestDAO): Valid typed candidate manifest.

        Returns:
            Path: Unresolved local candidate wheel path.

        Raises:
            SlotuiCoreVerificationError: If source is remote, VCS, relative, or source-like.
        """
        source: str = manifest.wheel_artifact["source"]
        parsed = urlparse(source)
        if parsed.scheme and parsed.scheme != "file":
            raise SlotuiCoreVerificationError(
                "Slotui candidate requires a local wheel artifact, never registry or VCS"
            )
        if parsed.scheme == "file":
            if parsed.netloc not in ("", "localhost"):
                raise SlotuiCoreVerificationError(
                    "Slotui candidate requires a local wheel artifact, not a remote file URL"
                )
            wheel_path: Path = Path(unquote(parsed.path))
        else:
            wheel_path = Path(source)
        if not wheel_path.is_absolute() or wheel_path.suffix != ".whl":
            raise SlotuiCoreVerificationError("Slotui candidate requires an absolute local wheel artifact")
        return wheel_path

    @classmethod
    def _verify_wheel_file(cls, *, wheel_path: Path, manifest: SlotuiCoreManifestDAO) -> None:
        """Verify exact wheel archive metadata, generic evidence, and adapter signature.

        Args:
            wheel_path (Path): Candidate local wheel.
            manifest (SlotuiCoreManifestDAO): Expected release contract.

        Raises:
            SlotuiCoreVerificationError: If artifact or static source proof is incomplete.
        """
        cls._require_regular_wheel(wheel_path=wheel_path)
        if wheel_path.name != manifest.wheel_filename:
            raise SlotuiCoreVerificationError("Slotui candidate wheel filename does not match the manifest")
        if hashlib.sha256(wheel_path.read_bytes()).hexdigest() != manifest.wheel_sha256:
            raise SlotuiCoreVerificationError("Slotui candidate wheel SHA-256 does not match the manifest")
        with zipfile.ZipFile(wheel_path) as archive:
            names: tuple[str, ...] = tuple(archive.namelist())
            cls._require_safe_archive_members(archive_names=names)
            cls._require_wheel_metadata(archive=archive, manifest=manifest)
            cls._require_only_slotui_package_files(archive_names=names)
            cls._require_declared_exports(archive=archive, manifest=manifest)
            cls._require_candidate_adapter(archive=archive, adapter=manifest.candidate_adapter)
            cls._require_candidate_runner(
                archive=archive,
                adapter=manifest.candidate_adapter,
                runner=manifest.candidate_runner,
            )

    @staticmethod
    def _require_regular_wheel(*, wheel_path: Path) -> None:
        """Reject absent, linked, non-regular, or non-ZIP wheel paths.

        Args:
            wheel_path (Path): Candidate artifact path.

        Raises:
            SlotuiCoreVerificationError: If candidate is not a safe local wheel file.
        """
        if not wheel_path.is_file() or wheel_path.is_symlink() or not zipfile.is_zipfile(wheel_path):
            raise SlotuiCoreVerificationError("Slotui candidate artifact must be a regular valid zip wheel")

    @staticmethod
    def _require_safe_archive_members(*, archive_names: tuple[str, ...]) -> None:
        """Reject duplicate, absolute, traversal, and directory member names.

        Args:
            archive_names (tuple[str, ...]): Exact ZIP members.

        Raises:
            SlotuiCoreVerificationError: If archive member identity is unsafe.
        """
        if len(set(archive_names)) != len(archive_names) or any(
            name.endswith("/") or name.startswith("/") or ".." in Path(name).parts for name in archive_names
        ):
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel archive contains unsafe or duplicate members"
            )

    @staticmethod
    def _require_wheel_metadata(*, archive: zipfile.ZipFile, manifest: SlotuiCoreManifestDAO) -> None:
        """Require exact distribution/version/Requires-Python wheel metadata.

        Args:
            archive (zipfile.ZipFile): Candidate archive.
            manifest (SlotuiCoreManifestDAO): Expected metadata.

        Raises:
            SlotuiCoreVerificationError: If metadata differs from static contract.
        """
        names: tuple[str, ...] = tuple(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        if len(names) != 1:
            raise SlotuiCoreVerificationError("Slotui candidate wheel must contain exactly one METADATA file")
        fields = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
        if (
            fields.get("Name") != manifest.distribution_name
            or fields.get("Version") != manifest.version
            or fields.get("Requires-Python") != manifest.requires_python
        ):
            raise SlotuiCoreVerificationError("Slotui candidate wheel METADATA does not match the manifest")

    @staticmethod
    def _require_only_slotui_package_files(*, archive_names: tuple[str, ...]) -> None:
        """Reject executable Python outside the candidate package.

        Args:
            archive_names (tuple[str, ...]): Archive members after safety validation.

        Raises:
            SlotuiCoreVerificationError: If another package/module is embedded.
        """
        python_names: tuple[str, ...] = tuple(name for name in archive_names if name.endswith(".py"))
        if not python_names or any(not name.startswith("slotui/") for name in python_names):
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains Python files outside the expected slotui package"
            )

    @classmethod
    def _require_declared_exports(cls, *, archive: zipfile.ZipFile, manifest: SlotuiCoreManifestDAO) -> None:
        """Prove static generic capability evidence without treating it as a runtime API.

        Args:
            archive (zipfile.ZipFile): Candidate wheel archive.
            manifest (SlotuiCoreManifestDAO): Generic evidence declarations.

        Raises:
            SlotuiCoreVerificationError: If an evidence export is missing.
        """
        for declaration in manifest.immutable_core_export_signature:
            source: str = cls._read_module_source(archive=archive, module=declaration.module)
            if not cls._module_defines_symbol(source=source, symbol=declaration.symbol):
                raise SlotuiCoreVerificationError(
                    f"Slotui candidate wheel is missing declared export {declaration.declaration}"
                )

    @classmethod
    def _require_candidate_adapter(
        cls, *, archive: zipfile.ZipFile, adapter: SlotuiCandidateAdapterDAO
    ) -> None:
        """Prove one exact async candidate entrypoint signature and declared digest.

        Args:
            archive (zipfile.ZipFile): Candidate wheel archive.
            adapter (SlotuiCandidateAdapterDAO): Manifested adapter entrypoint contract.

        Raises:
            SlotuiCoreVerificationError: If the entrypoint is missing, non-async, or signature-mismatched.
        """
        source: str = cls._read_module_source(archive=archive, module=adapter.module)
        signature: str | None = cls._find_async_keyword_only_signature(source=source, symbol=adapter.symbol)
        if signature is None:
            raise SlotuiCoreVerificationError(
                "Slotui candidate adapter entrypoint is missing or does not have keyword-only launch/control signature"
            )
        if hashlib.sha256(signature.encode("utf-8")).hexdigest() != adapter.signature_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui candidate adapter signature SHA-256 does not match the manifest"
            )

    @classmethod
    def _require_candidate_runner(
        cls,
        *,
        archive: zipfile.ZipFile,
        adapter: SlotuiCandidateAdapterDAO,
        runner: SlotuiCandidateRunnerDAO,
    ) -> None:
        """Prove the manifested runner invokes the manifested adapter over the v2 control contract.

        Args:
            archive (zipfile.ZipFile): Candidate wheel archive.
            adapter (SlotuiCandidateAdapterDAO): Sole runtime adapter declaration.
            runner (SlotuiCandidateRunnerDAO): Sole process runner declaration.

        Raises:
            SlotuiCoreVerificationError: If runner source is inert, mismatched, or unrelated to the adapter.
        """
        source: str = cls._read_module_source(archive=archive, module=runner.module)
        signature: str | None = cls._find_async_runner_signature(source=source, symbol=runner.symbol)
        if signature is None:
            raise SlotuiCoreVerificationError(
                "Slotui candidate runner entrypoint has an invalid v2 signature"
            )
        if hashlib.sha256(signature.encode("utf-8")).hexdigest() != runner.signature_sha256:
            raise SlotuiCoreVerificationError(
                "Slotui candidate runner signature SHA-256 does not match the manifest"
            )
        if not cls._runner_references_adapter(source=source, adapter=adapter, runner=runner):
            raise SlotuiCoreVerificationError(
                "Slotui candidate runner does not directly load and invoke the manifested adapter control contract"
            )
        cls._require_executable_runner_module_bridge(source=source, runner=runner)

    @classmethod
    def _require_executable_runner_module_bridge(
        cls,
        *,
        source: str,
        runner: SlotuiCandidateRunnerDAO,
    ) -> None:
        """Require the exact ``python -m`` bridge used by the host spawn command.

        Args:
            source (str): Candidate runner module source.
            runner (SlotuiCandidateRunnerDAO): Manifested runner declaration.

        Raises:
            SlotuiCoreVerificationError: If the module main guard is absent or invokes an unrelated coroutine.
        """
        if cls._runner_has_executable_module_bridge(source=source, runner=runner):
            return
        if cls._module_has_inert_asyncio_launcher(source=source, runner=runner):
            raise SlotuiCoreVerificationError(
                "Slotui candidate runner may not be an inert asyncio.run launcher"
            )
        raise SlotuiCoreVerificationError(
            "Slotui candidate runner lacks an exact executable module bridge for host CLI flags"
        )

    @staticmethod
    def _read_module_source(*, archive: zipfile.ZipFile, module: str) -> str:
        """Read one declared module source from the wheel without importing it.

        Args:
            archive (zipfile.ZipFile): Candidate archive.
            module (str): Explicit Slotui module.

        Returns:
            str: UTF-8 source text.

        Raises:
            SlotuiCoreVerificationError: If module source is absent/unreadable.
        """
        base: str = module.replace(".", "/")
        choices: tuple[str, ...] = (f"{base}.py", f"{base}/__init__.py")
        matches: tuple[str, ...] = tuple(name for name in choices if name in archive.namelist())
        if len(matches) != 1:
            raise SlotuiCoreVerificationError(f"Slotui candidate wheel is missing declared module {module}")
        try:
            return archive.read(matches[0]).decode("utf-8")
        except (KeyError, UnicodeDecodeError) as error:
            raise SlotuiCoreVerificationError(
                f"Slotui candidate wheel has unreadable declared module {module}"
            ) from error

    @staticmethod
    def _module_defines_symbol(*, source: str, symbol: str) -> bool:
        """Determine whether source has a top-level required public symbol.

        Args:
            source (str): Module source text.
            symbol (str): Required declaration name.

        Returns:
            bool: Whether a class/function/assignment declares it.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        for node in tree.body:
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == symbol
            ):
                return True
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == symbol for target in node.targets
            ):
                return True
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == symbol
            ):
                return True
        return False

    @staticmethod
    def _find_async_runner_signature(*, source: str, symbol: str) -> str | None:
        """Find canonical AST-derived signature for the one candidate-owned runner.

        Args:
            source (str): Candidate runner module source.
            symbol (str): Manifested runner function name.

        Returns:
            str | None: Canonical runner signature or ``None`` if contract shape differs.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        matches: list[ast.AsyncFunctionDef] = [
            node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == symbol
        ]
        if len(matches) != 1:
            return None
        arguments: ast.arguments = matches[0].args
        if arguments.posonlyargs or arguments.args or arguments.vararg or arguments.kwarg:
            return None
        names: tuple[str, ...] = tuple(argument.arg for argument in arguments.kwonlyargs)
        expected_names: tuple[str, ...] = (
            "control_socket",
            "adapter_module",
            "adapter_symbol",
            "protocol_version",
        )
        if names != expected_names or len(arguments.kw_defaults) != len(expected_names):
            return None
        if any(default is not None for default in arguments.kw_defaults):
            return None
        return "async def runner(*, control_socket, adapter_module, adapter_symbol, protocol_version)"

    @staticmethod
    def _runner_references_adapter(
        *, source: str, adapter: SlotuiCandidateAdapterDAO, runner: SlotuiCandidateRunnerDAO
    ) -> bool:
        """Check direct AST evidence that the runner imports and calls the manifested adapter.

        Args:
            source (str): Candidate runner module source.
            adapter (SlotuiCandidateAdapterDAO): Expected runtime adapter.
            runner (SlotuiCandidateRunnerDAO): Expected runner function.

        Returns:
            bool: Whether the runner directly references adapter module/symbol and its control arguments.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        function: ast.AsyncFunctionDef | None = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == runner.symbol
            ),
            None,
        )
        if function is None:
            return False
        constants: set[str] = {
            node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        names: set[str] = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
        calls: list[ast.Call] = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        has_adapter_reference: bool = adapter.module in constants or "adapter_module" in names
        has_symbol_reference: bool = adapter.symbol in constants or "adapter_symbol" in names
        has_control_configuration: bool = "control_socket" in names and "protocol_version" in names
        has_direct_call: bool = any(
            any(keyword.arg == "launch" for keyword in call.keywords)
            and any(keyword.arg == "control" for keyword in call.keywords)
            for call in calls
        )
        return (
            has_adapter_reference and has_symbol_reference and has_control_configuration and has_direct_call
        )

    @classmethod
    def _module_has_inert_asyncio_launcher(cls, *, source: str, runner: SlotuiCandidateRunnerDAO) -> bool:
        """Identify a top-level ``asyncio.run`` that does not execute the manifested runner.

        Args:
            source (str): Candidate runner module source.
            runner (SlotuiCandidateRunnerDAO): Manifested runner declaration.

        Returns:
            bool: Whether the module contains an explicitly inert top-level launcher.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        top_level_runs: list[ast.Call] = [
            node.value
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "asyncio"
            and node.value.func.attr == "run"
        ]
        return bool(top_level_runs) and not any(
            len(call.args) == 1
            and isinstance(call.args[0], ast.Call)
            and isinstance(call.args[0].func, ast.Name)
            and call.args[0].func.id == runner.symbol
            for call in top_level_runs
        )

    @classmethod
    def _runner_has_executable_module_bridge(cls, *, source: str, runner: SlotuiCandidateRunnerDAO) -> bool:
        """Prove the exact ``python -m`` bridge that the host process executes.

        The candidate must own an ``if __name__ == "__main__"`` guard which
        builds an ``argparse.ArgumentParser``, parses precisely the four host
        flags from ``sys.argv[1:]``, and passes the resulting values by keyword
        to ``asyncio.run(manifested_runner(...))``.  This AST shape proves the
        spawned module's bridge rather than accepting unrelated text or a
        merely callable runner function.

        Args:
            source (str): Candidate runner module source.
            runner (SlotuiCandidateRunnerDAO): Manifested runner declaration.

        Returns:
            bool: Whether exact module execution is statically proven.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        guards: list[ast.If] = [
            node for node in tree.body if isinstance(node, ast.If) and cls._is_main_guard(node=node)
        ]
        if len(guards) != 1:
            return False
        return cls._main_guard_invokes_runner(guard=guards[0], runner=runner, tree=tree)

    @staticmethod
    def _is_main_guard(*, node: ast.stmt) -> bool:
        """Identify one exact module-main guard AST node.

        Args:
            node (ast.stmt): One module-level statement.

        Returns:
            bool: Whether the node is ``if __name__ == "__main__":``.
        """
        return (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
        )

    @classmethod
    def _main_guard_invokes_runner(
        cls,
        *,
        guard: ast.If,
        runner: SlotuiCandidateRunnerDAO,
        tree: ast.Module,
    ) -> bool:
        """Validate parser, exact flags, argv source, and async runner invocation.

        Args:
            guard (ast.If): The unique candidate ``__main__`` branch.
            runner (SlotuiCandidateRunnerDAO): Manifested runner declaration.
            tree (ast.Module): Parsed complete candidate runner module.

        Returns:
            bool: Whether every spawned-host bridge invariant is present.
        """
        parser_names: set[str] = cls._main_guard_parser_names(guard=guard)
        if not parser_names:
            return False
        flags_by_destination: dict[str, str] = cls._main_guard_flags(guard=guard, parser_names=parser_names)
        expected_flags: dict[str, str] = {
            "control_socket": "--control-socket",
            "adapter_module": "--adapter-module",
            "adapter_symbol": "--adapter-symbol",
            "protocol_version": "--protocol-version",
        }
        if flags_by_destination != expected_flags:
            return False
        if not cls._main_guard_imports_required_bridge_modules(tree=tree):
            return False
        argument_names: set[str] = cls._main_guard_parsed_argument_names(
            guard=guard,
            parser_names=parser_names,
        )
        return any(
            cls._is_exact_asyncio_runner_call(
                node=node,
                runner=runner,
                argument_names=argument_names,
            )
            for node in ast.walk(guard)
            if isinstance(node, ast.Call)
        )

    @staticmethod
    def _main_guard_imports_required_bridge_modules(*, tree: ast.Module) -> bool:
        """Require direct module imports for the parser, argv source, and coroutine runner.

        Args:
            tree (ast.Module): Parsed complete candidate runner module.

        Returns:
            bool: Whether the bridge's ``argparse``, ``sys``, and ``asyncio`` names are imported.
        """
        imports: set[str] = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name in {"argparse", "asyncio", "sys"}
        }
        return imports == {"argparse", "asyncio", "sys"}

    @staticmethod
    def _main_guard_parser_names(*, guard: ast.If) -> set[str]:
        """Find variables assigned an argparse argument parser in the main guard.

        Args:
            guard (ast.If): Candidate module-main branch.

        Returns:
            set[str]: Parser variable names proved to use ``argparse.ArgumentParser``.
        """
        parser_names: set[str] = set()
        for node in guard.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "argparse"
                and node.value.func.attr == "ArgumentParser"
            ):
                parser_names.add(node.targets[0].id)
        return parser_names

    @staticmethod
    def _main_guard_flags(*, guard: ast.If, parser_names: set[str]) -> dict[str, str]:
        """Extract required ``add_argument`` flags and explicit destinations.

        Args:
            guard (ast.If): Candidate module-main branch.
            parser_names (set[str]): Validated parser variables.

        Returns:
            dict[str, str]: Destination-to-flag map, or an incomplete map on invalid calls.
        """
        flags: dict[str, str] = {}
        for node in ast.walk(guard):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in parser_names
                and node.func.attr == "add_argument"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            destination: str | None = next(
                (
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "dest"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ),
                None,
            )
            required: bool = any(
                keyword.arg == "required"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if destination is None or not required or destination in flags:
                return {}
            flags[destination] = node.args[0].value
        return flags

    @staticmethod
    def _main_guard_parsed_argument_names(*, guard: ast.If, parser_names: set[str]) -> set[str]:
        """Find names assigned from an exact ``parser.parse_args(sys.argv[1:])`` call.

        Args:
            guard (ast.If): Candidate module-main branch.
            parser_names (set[str]): Validated parser variables.

        Returns:
            set[str]: Names holding parser results from the real CLI argument vector.
        """
        argument_names: set[str] = set()
        for node in guard.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and SlotuiCoreWheelVerificationService._is_parse_args_from_sys_argv(
                    call=node.value,
                    parser_names=parser_names,
                )
            ):
                argument_names.add(node.targets[0].id)
        return argument_names

    @staticmethod
    def _is_parse_args_from_sys_argv(*, call: ast.expr, parser_names: set[str]) -> bool:
        """Require ``parser.parse_args(args=sys.argv[1:])`` for the module bridge.

        Args:
            call (ast.expr): Assigned expression from the module-main branch.
            parser_names (set[str]): Validated parser variables.

        Returns:
            bool: Whether the expression parses precisely the process CLI tail.
        """
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in parser_names
            and call.func.attr == "parse_args"
            and not call.args
            and len(call.keywords) == 1
            and call.keywords[0].arg == "args"
        ):
            return False
        argument: ast.expr = call.keywords[0].value
        return (
            isinstance(argument, ast.Subscript)
            and isinstance(argument.value, ast.Attribute)
            and isinstance(argument.value.value, ast.Name)
            and argument.value.value.id == "sys"
            and argument.value.attr == "argv"
            and isinstance(argument.slice, ast.Slice)
            and isinstance(argument.slice.lower, ast.Constant)
            and argument.slice.lower.value == 1
            and argument.slice.upper is None
            and argument.slice.step is None
        )

    @staticmethod
    def _is_exact_asyncio_runner_call(
        *,
        node: ast.Call,
        runner: SlotuiCandidateRunnerDAO,
        argument_names: set[str],
    ) -> bool:
        """Require ``asyncio.run`` of the manifested runner with exact keyword values.

        Args:
            node (ast.Call): Candidate call inside the module-main branch.
            runner (SlotuiCandidateRunnerDAO): Manifested runner declaration.
            argument_names (set[str]): Variables proved to hold parsed host flags.

        Returns:
            bool: Whether the call directly executes the runner with all host arguments.
        """
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
            and node.func.attr == "run"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == runner.symbol
            and not node.args[0].args
        ):
            return False
        expected_names: tuple[str, ...] = (
            "control_socket",
            "adapter_module",
            "adapter_symbol",
            "protocol_version",
        )
        keywords: dict[str, ast.expr] = {
            keyword.arg: keyword.value for keyword in node.args[0].keywords if keyword.arg is not None
        }
        if tuple(keywords) != expected_names:
            return False
        return all(
            SlotuiCoreWheelVerificationService._is_parsed_argument_attribute(
                value=keywords[name],
                argument_names=argument_names,
                field_name=name,
            )
            for name in expected_names
        )

    @staticmethod
    def _is_parsed_argument_attribute(*, value: ast.expr, argument_names: set[str], field_name: str) -> bool:
        """Require one runner keyword to come from the matching parsed CLI field.

        Args:
            value (ast.expr): Candidate runner keyword value.
            argument_names (set[str]): Validated parser-result variables.
            field_name (str): Required parser-result field name.

        Returns:
            bool: Whether the expression is ``arguments.<field_name>``.
        """
        return (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in argument_names
            and value.attr == field_name
        )

    @staticmethod
    def _find_async_keyword_only_signature(*, source: str, symbol: str) -> str | None:
        """Find canonical AST-derived signature for the one candidate adapter function.

        Args:
            source (str): Candidate adapter module source.
            symbol (str): Manifested adapter function name.

        Returns:
            str | None: Canonical signature or ``None`` if contract shape differs.
        """
        try:
            tree: ast.Module = ast.parse(source)
        except SyntaxError as error:
            raise SlotuiCoreVerificationError(
                "Slotui candidate wheel contains invalid Python source"
            ) from error
        matches: list[ast.AsyncFunctionDef] = [
            node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == symbol
        ]
        if len(matches) != 1:
            return None
        arguments: ast.arguments = matches[0].args
        if arguments.posonlyargs or arguments.args or arguments.vararg or arguments.kwarg:
            return None
        names: tuple[str, ...] = tuple(argument.arg for argument in arguments.kwonlyargs)
        if (
            names != ("launch", "control")
            or len(arguments.kw_defaults) != 2
            or any(default is not None for default in arguments.kw_defaults)
        ):
            return None
        return "async def adapter(*, launch, control)"
