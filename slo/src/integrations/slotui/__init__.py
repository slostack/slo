"""Fail-closed consumer scaffolding for a released Slotui core wheel.

This package validates release artifacts and presentation selection without
importing, installing, or otherwise executing Slotui from Slo's checkout.
"""

from src.integrations.slotui.dao import (
    REQUIRED_SLOTUI_CAPABILITIES,
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreCapabilityDAO,
    SlotuiCoreInstallationPlanDAO,
    SlotuiCoreManifestDAO,
    SlotuiPresentationSelectionDAO,
)
from src.integrations.slotui.parity import SlotuiParityMatrix, SlotuiParityMatrixEntryDAO
from src.integrations.slotui.selector import SlotuiCoreUnavailableError, SlotuiPresentationSelector
from src.integrations.slotui.verifier import SlotuiCoreVerificationError, SlotuiCoreWheelVerificationService

__all__ = [
    "REQUIRED_SLOTUI_CAPABILITIES",
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreInstallationPlanDAO",
    "SlotuiCoreManifestDAO",
    "SlotuiCoreUnavailableError",
    "SlotuiCoreVerificationError",
    "SlotuiCoreWheelVerificationService",
    "SlotuiParityMatrix",
    "SlotuiParityMatrixEntryDAO",
    "SlotuiPresentationSelectionDAO",
    "SlotuiPresentationSelector",
]
