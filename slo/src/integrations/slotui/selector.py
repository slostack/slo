"""Explicit Slotui selection that fails closed until runtime assembly is delivered."""

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
    """Report an explicit Slotui request that cannot start a Slotui presentation."""


class SlotuiPresentationSelector:
    """Select current Textual or statically verify and reject unavailable future core selection."""

    @classmethod
    def select(
        cls,
        *,
        presentation: SlotuiPresentationName,
        core_reference_path: Path | None,
    ) -> SlotuiPresentationSelectionDAO:
        """Select one interactive presentation without importing or installing Slotui.

        A verified core adapter fixture remains an error because Slo has no core
        presentation factory or session assembly yet.  This prevents verified
        opt-in from silently launching the current Textual presentation.

        Args:
            presentation (SlotuiPresentationName): Explicit interactive selection.
            core_reference_path (Path | None): Absolute JSON reference to a pinned adapter fixture.

        Returns:
            SlotuiPresentationSelectionDAO: Textual selection only.

        Raises:
            SlotuiCoreUnavailableError: If core proof is absent, invalid, or verified but unassembled.
        """
        if presentation == "textual_current":
            return SlotuiPresentationSelectionDAO(presentation="textual_current")
        cls._verify_then_reject_unavailable_core(core_reference_path=core_reference_path)
        raise AssertionError("unreachable after Slotui core unavailable error")

    @classmethod
    def _verify_then_reject_unavailable_core(cls, *, core_reference_path: Path | None) -> None:
        """Verify the local adapter fixture then stop before current Textual assembly.

        Args:
            core_reference_path (Path | None): Candidate local release-reference JSON file.

        Raises:
            SlotuiCoreUnavailableError: If proof fails or core integration is not assembled.
        """
        if core_reference_path is None:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "provide --slotui-core-reference from protected release CI."
            )
        try:
            reference: SlotuiCoreArtifactReferenceDAO = cls._load_reference(path=core_reference_path)
            SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)
        except (OSError, ValidationError, SlotuiCoreVerificationError, ValueError) as error:
            raise SlotuiCoreUnavailableError(
                "Slotui core was requested, but a verified Slotui core wheel is unavailable; "
                "the adapter fixture reference, manifest, or local wheel failed static verification."
            ) from error
        raise SlotuiCoreUnavailableError(
            "Slotui core wheel was verified, but Slo core presentation integration is not available yet; "
            "Slo will not fall back to the Textual presentation."
        )

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
