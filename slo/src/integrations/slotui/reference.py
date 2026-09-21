"""Generate immutable v2 Slotui release references from a legacy local reference."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from src.integrations.slotui.dao import SlotuiCoreArtifactReferenceDAO

__all__ = ["SlotuiCoreReferenceDerivationError", "SlotuiCoreReferenceDerivationService"]


class SlotuiCoreReferenceDerivationError(ValueError):
    """Report a legacy candidate reference that cannot safely produce a v2 reference."""


class SlotuiCoreReferenceDerivationService:
    """Create a separate v2 release reference that explicitly pins its local bundle."""

    @classmethod
    def derive(
        cls,
        *,
        legacy_reference_path: Path,
        bundle_path: Path,
        output_path: Path,
    ) -> SlotuiCoreArtifactReferenceDAO:
        """Write an immutable v2 reference from a legacy manifest pointer and explicit bundle.

        WHAT: Reads a legacy v2-shaped reference only to retain its candidate label and manifest
            digest, then writes separate canonical v2 reference bytes with an explicit bundle path
            and SHA-256.
        WHO: Protected CI and operators use this before passing a candidate to ``slotui_core``.
        WHEN: Runs before Slo static verification; the legacy source reference remains unmodified.

        Args:
            legacy_reference_path (Path): Existing absolute regular legacy reference JSON file.
            bundle_path (Path): Existing absolute regular offline bundle to pin.
            output_path (Path): Absolute new reference path that must not already exist.

        Returns:
            SlotuiCoreArtifactReferenceDAO: Newly written fully pinned v2 reference.

        Raises:
            SlotuiCoreReferenceDerivationError: If inputs are not safe immutable local artifacts.
        """
        legacy_payload: dict[str, object] = cls._load_legacy_payload(path=legacy_reference_path)
        manifest_path: Path = cls._load_absolute_path(payload=legacy_payload, key="manifest_path")
        manifest_sha256: str = cls._load_sha256(payload=legacy_payload, key="manifest_sha256")
        candidate_label: str = cls._load_candidate_label(payload=legacy_payload)
        cls._require_regular_absolute_file(path=manifest_path, name="manifest")
        cls._require_manifest_digest(path=manifest_path, expected_sha256=manifest_sha256)
        cls._require_regular_absolute_file(path=bundle_path, name="bundle")
        cls._require_new_absolute_output_path(path=output_path)
        reference = SlotuiCoreArtifactReferenceDAO(
            schema_version="slo-slotui-candidate-adapter-v2",
            candidate_label=candidate_label,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            bundle_path=bundle_path,
            bundle_sha256=hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        )
        cls._write_canonical_reference(path=output_path, reference=reference)
        return reference

    @staticmethod
    def _load_legacy_payload(*, path: Path) -> dict[str, object]:
        """Load a legacy JSON object without treating it as a v2 pinned reference.

        Args:
            path (Path): Existing legacy reference path.

        Returns:
            dict[str, object]: Untrusted legacy JSON fields used only for retained manifest facts.

        Raises:
            SlotuiCoreReferenceDerivationError: If the legacy reference is unavailable or malformed.
        """
        SlotuiCoreReferenceDerivationService._require_regular_absolute_file(path=path, name="legacy reference")
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SlotuiCoreReferenceDerivationError("legacy Slotui reference must contain one JSON object") from error
        if not isinstance(payload, dict):
            raise SlotuiCoreReferenceDerivationError("legacy Slotui reference must contain one JSON object")
        return payload

    @staticmethod
    def _load_absolute_path(*, payload: dict[str, object], key: str) -> Path:
        """Read one required absolute path from untrusted legacy JSON.

        Args:
            payload (dict[str, object]): Legacy JSON object.
            key (str): Required path field name.

        Returns:
            Path: Validated absolute path.

        Raises:
            SlotuiCoreReferenceDerivationError: If the field is absent or relative.
        """
        value: object | None = payload.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise SlotuiCoreReferenceDerivationError(f"legacy Slotui reference {key} must be an absolute path")
        return Path(value)

    @staticmethod
    def _load_sha256(*, payload: dict[str, object], key: str) -> str:
        """Read one required lower-case SHA-256 string from legacy JSON.

        Args:
            payload (dict[str, object]): Legacy JSON object.
            key (str): Required digest field name.

        Returns:
            str: Validated SHA-256 digest.

        Raises:
            SlotuiCoreReferenceDerivationError: If the digest has an invalid shape.
        """
        value: object | None = payload.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise SlotuiCoreReferenceDerivationError(f"legacy Slotui reference {key} must be a lower-case SHA-256")
        return value

    @staticmethod
    def _load_candidate_label(*, payload: dict[str, object]) -> str:
        """Read the retained human candidate label from legacy JSON.

        Args:
            payload (dict[str, object]): Legacy JSON object.

        Returns:
            str: Nonempty candidate label.

        Raises:
            SlotuiCoreReferenceDerivationError: If the label is absent or blank.
        """
        value: object | None = payload.get("candidate_label")
        if not isinstance(value, str) or not value:
            raise SlotuiCoreReferenceDerivationError("legacy Slotui reference candidate_label must be nonempty")
        return value

    @staticmethod
    def _require_regular_absolute_file(*, path: Path, name: str) -> None:
        """Require one non-symlink absolute regular input file.

        Args:
            path (Path): Candidate input path.
            name (str): Human-readable artifact name for diagnostics.

        Raises:
            SlotuiCoreReferenceDerivationError: If the path is not a safe local regular file.
        """
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise SlotuiCoreReferenceDerivationError(
                f"Slotui {name} must be an existing absolute regular non-symlink file"
            )

    @staticmethod
    def _require_manifest_digest(*, path: Path, expected_sha256: str) -> None:
        """Require legacy manifest bytes to match the legacy reference before retaining its claim.

        Args:
            path (Path): Existing regular manifest file retained by the derived reference.
            expected_sha256 (str): Legacy reference manifest digest.

        Raises:
            SlotuiCoreReferenceDerivationError: If retained manifest bytes are no longer authentic.
        """
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
            raise SlotuiCoreReferenceDerivationError(
                "legacy Slotui reference manifest SHA-256 does not match manifest bytes"
            )

    @staticmethod
    def _require_new_absolute_output_path(*, path: Path) -> None:
        """Require a new absolute regular-file destination without overwriting source evidence.

        Args:
            path (Path): Requested derived reference destination.

        Raises:
            SlotuiCoreReferenceDerivationError: If output would be relative, linked, or overwrite a file.
        """
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise SlotuiCoreReferenceDerivationError(
                "derived Slotui reference path must be absolute, non-symlink, and not already exist"
            )

    @staticmethod
    def _write_canonical_reference(*, path: Path, reference: SlotuiCoreArtifactReferenceDAO) -> None:
        """Persist one canonical v2 reference without modifying candidate artifacts.

        Args:
            path (Path): New destination for the derived reference.
            reference (SlotuiCoreArtifactReferenceDAO): Complete immutable v2 reference content.

        Raises:
            SlotuiCoreReferenceDerivationError: If the destination cannot be written atomically enough.
        """
        serialized_reference: str = reference.model_dump_json() + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=False)
            path.write_text(serialized_reference, encoding="utf-8")
        except OSError as error:
            raise SlotuiCoreReferenceDerivationError("could not write derived Slotui reference") from error
        try:
            persisted_reference: SlotuiCoreArtifactReferenceDAO = SlotuiCoreArtifactReferenceDAO.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as error:
            raise SlotuiCoreReferenceDerivationError("could not reread derived Slotui reference") from error
        if persisted_reference != reference:
            raise SlotuiCoreReferenceDerivationError("derived Slotui reference bytes changed during creation")
