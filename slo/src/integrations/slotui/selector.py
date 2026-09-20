"""Explicit interactive Slotui selection that never changes default Slo behavior."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.integrations.slotui.dao import (
    SlotuiCoreArtifactReferenceDAO,
    SlotuiPresentationName,
    SlotuiPresentationSelectionDAO,
)
from src.integrations.slotui.verifier import SlotuiCoreVerificationError, SlotuiCoreWheelVerificationService

__all__ = ["SlotuiCoreUnavailableError", "SlotuiPresentationSelector"]


class SlotuiCoreUnavailableError(ValueError):
    """Report an explicit Slotui request that lacks a verified released core wheel."""


class SlotuiPresentationSelector:
    """Select the current Textual default or verify an explicit released Slotui core request."""

    @classmethod
    def select(
        cls,
        *,
        presentation: SlotuiPresentationName,
        core_reference_path: Path | None,
    ) -> SlotuiPresentationSelectionDAO:
        """Select one interactive presentation without importing the Slotui package.

        Args:
            presentation (SlotuiPresentationName): Explicit requested interactive presentation.
            core_reference_path (Path | None): Absolute JSON reference to a pinned core manifest.

        Returns:
            SlotuiPresentationSelectionDAO: Current default or verified future-core selection.

        Raises:
            SlotuiCoreUnavailableError: If an opt-in core request lacks a trusted local release proof.
        """
        if presentation == "textual_current":
            return SlotuiPresentationSelectionDAO(presentation="textual_current")
        return cls._select_verified_core(core_reference_path=core_reference_path)

    @classmethod
    def _select_verified_core(cls, *, core_reference_path: Path | None) -> SlotuiPresentationSelectionDAO:
        """Load and verify a typed local core reference for the opt-in route.

        Args:
            core_reference_path (Path | None): Candidate local release-reference JSON file.

        Returns:
            SlotuiPresentationSelectionDAO: Verified core selection with a safe fresh-venv plan.

        Raises:
            SlotuiCoreUnavailableError: If proof is missing, malformed, or cannot verify exact wheel bytes.
        """
        if core_reference_path is None:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "provide --slotui-core-reference from protected release CI."
            )
        try:
            reference: SlotuiCoreArtifactReferenceDAO = cls._load_reference(path=core_reference_path)
            plan = SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)
        except (OSError, ValidationError, SlotuiCoreVerificationError, ValueError) as error:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "the reference, manifest, or local wheel failed verification."
            ) from error
        return SlotuiPresentationSelectionDAO(presentation="slotui_core", core_installation_plan=plan)

    @staticmethod
    def _load_reference(*, path: Path) -> SlotuiCoreArtifactReferenceDAO:
        """Load the typed, absolute local manifest reference without fallback discovery.

        Args:
            path (Path): Explicit local JSON reference supplied by the operator.

        Returns:
            SlotuiCoreArtifactReferenceDAO: Strict immutable manifest reference.

        Raises:
            ValueError: If the requested reference is not one readable regular file.
        """
        resolved_path: Path = path.expanduser().resolve()
        if not resolved_path.is_file():
            raise ValueError("Slotui core reference is unavailable or is not a regular file")
        return SlotuiCoreArtifactReferenceDAO.model_validate_json(resolved_path.read_text(encoding="utf-8"))
