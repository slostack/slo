"""Explicit Slotui selection with static proof for the persistent isolated host."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.integrations.slotui.dao import (
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreVerificationReceiptDAO,
    SlotuiPresentationName,
    SlotuiPresentationSelectionDAO,
)
from src.integrations.slotui.verifier import SlotuiCoreVerificationError, SlotuiCoreWheelVerificationService

__all__ = ["SlotuiCoreUnavailableError", "SlotuiPresentationSelector"]


class SlotuiCoreUnavailableError(ValueError):
    """Report an explicit Slotui request that cannot complete its isolated core lane."""


class SlotuiPresentationSelector:
    """Select current Textual or verify an exact local core wheel for isolated execution."""

    @classmethod
    def select(
        cls,
        *,
        presentation: SlotuiPresentationName,
        core_reference_path: Path | None,
    ) -> SlotuiPresentationSelectionDAO:
        """Select one interactive presentation without importing Slotui in the Slo process.

        The core branch verifies a complete actual-host export contract statically. The caller
        then starts the persistent host in a fresh installed-wheel interpreter; this selector
        never imports Slotui and never falls back to the current Textual path.

        Args:
            presentation (SlotuiPresentationName): Explicit interactive selection.
            core_reference_path (Path | None): Absolute JSON reference to a pinned adapter fixture.

        Returns:
            SlotuiPresentationSelectionDAO: Current selection or static receipt for host launch.

        Raises:
            SlotuiCoreUnavailableError: If the exact static proof is absent or invalid.
        """
        if presentation == "textual_current":
            return SlotuiPresentationSelectionDAO(presentation="textual_current")
        receipt = cls._verify_core_reference(core_reference_path=core_reference_path)
        return SlotuiPresentationSelectionDAO(
            presentation="slotui_core",
            core_verification_receipt=receipt,
        )

    @classmethod
    def _verify_core_reference(
        cls,
        *,
        core_reference_path: Path | None,
    ) -> SlotuiCoreVerificationReceiptDAO:
        """Build the exact static receipt required by the separate runtime lane.

        Args:
            core_reference_path (Path | None): Candidate local release-reference JSON file.

        Returns:
            SlotuiCoreVerificationReceiptDAO: Static exact-wheel proof.

        Raises:
            SlotuiCoreUnavailableError: If no valid regular local reference proves the artifact.
        """
        if core_reference_path is None:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "provide --slotui-core-reference from protected release CI."
            )
        try:
            reference: SlotuiCoreArtifactReferenceDAO = cls._load_reference(path=core_reference_path)
            return SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)
        except (OSError, ValidationError, SlotuiCoreVerificationError, ValueError) as error:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "the adapter fixture reference, manifest, or local wheel failed static verification."
            ) from error

    @staticmethod
    def _load_reference(*, path: Path) -> SlotuiCoreArtifactReferenceDAO:
        """Load one explicitly supplied typed adapter-fixture reference without fallback discovery.

        Args:
            path (Path): Explicit local JSON reference supplied by the operator.

        Returns:
            SlotuiCoreArtifactReferenceDAO: Strict immutable local fixture reference.

        Raises:
            ValueError: If the requested reference is not one readable regular file.
        """
        resolved_path: Path = path.expanduser().resolve()
        if not resolved_path.is_file() or resolved_path.is_symlink():
            raise ValueError("Slotui core adapter fixture reference is unavailable or is not a regular file")
        return SlotuiCoreArtifactReferenceDAO.model_validate_json(resolved_path.read_text(encoding="utf-8"))
