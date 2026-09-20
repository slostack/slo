"""Fail-closed Slo consumer scaffold for a future protected Slotui core release.

The package only verifies Slo-owned typed adapter fixtures.  It never imports,
installs, or claims ownership of Slotui's future b.1 schema or runtime.
"""

from src.integrations.slotui.dao import (
    REQUIRED_SLOTUI_CAPABILITIES,
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreCapabilityDAO,
    SlotuiCoreExportDAO,
    SlotuiCoreManifestDAO,
    SlotuiCoreSourceIdentityDAO,
    SlotuiCoreTestReportHashDAO,
    SlotuiCoreVerificationReceiptDAO,
    SlotuiOpaqueEvidenceDAO,
    SlotuiPresentationSelectionDAO,
)
from src.integrations.slotui.parity import SlotuiParityMatrix, SlotuiParityMatrixEntryDAO
from src.integrations.slotui.selector import SlotuiCoreUnavailableError, SlotuiPresentationSelector
from src.integrations.slotui.verifier import SlotuiCoreVerificationError, SlotuiCoreWheelVerificationService

__all__ = [
    "REQUIRED_SLOTUI_CAPABILITIES",
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreExportDAO",
    "SlotuiCoreManifestDAO",
    "SlotuiCoreSourceIdentityDAO",
    "SlotuiCoreTestReportHashDAO",
    "SlotuiCoreUnavailableError",
    "SlotuiCoreVerificationError",
    "SlotuiCoreVerificationReceiptDAO",
    "SlotuiCoreWheelVerificationService",
    "SlotuiOpaqueEvidenceDAO",
    "SlotuiParityMatrix",
    "SlotuiParityMatrixEntryDAO",
    "SlotuiPresentationSelectionDAO",
    "SlotuiPresentationSelector",
]
