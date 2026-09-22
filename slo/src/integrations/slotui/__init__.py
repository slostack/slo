"""Fail-closed consumer boundary for an explicit protected Slotui candidate adapter."""

from src.integrations.slotui.dao import (
    REQUIRED_SLOTUI_ADAPTER_CAPABILITIES,
    REQUIRED_SLOTUI_CAPABILITIES,
    SlotuiCandidateAdapterDAO,
    SlotuiCandidateRunnerDAO,
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreBundleDAO,
    SlotuiCoreBundleWheelDAO,
    SlotuiCoreCapabilityDAO,
    SlotuiCoreExportDAO,
    SlotuiCoreManifestDAO,
    SlotuiCoreSourceIdentityDAO,
    SlotuiCoreTestReportHashDAO,
    SlotuiCoreVerificationReceiptDAO,
    SlotuiOpaqueEvidenceDAO,
    SlotuiPresentationSelectionDAO,
)
from src.integrations.slotui.host import (
    InstalledSlotuiHostProcess,
    InstalledSlotuiHostProcessFactory,
    SlotuiCoreHostError,
    SlotuiCoreHostService,
    SlotuiTerminalBridge,
    SlotuiHostProcess,
    SlotuiHostProcessFactory,
)
from src.integrations.slotui.host_protocol import (
    SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
    SlotuiHostCommandDAO,
    SlotuiHostEventDAO,
    SlotuiHostLaunchConfigDAO,
    SlotuiLiveTranscriptMutationDAO,
    SlotuiStreamEventMapper,
)
from src.integrations.slotui.parity import SlotuiParityMatrix, SlotuiParityMatrixEntryDAO
from src.integrations.slotui.reference import (
    SlotuiCoreReferenceDerivationError,
    SlotuiCoreReferenceDerivationService,
)
from src.integrations.slotui.selector import SlotuiCoreUnavailableError, SlotuiPresentationSelector
from src.integrations.slotui.verifier import SlotuiCoreVerificationError, SlotuiCoreWheelVerificationService

__all__ = [
    "InstalledSlotuiHostProcess",
    "InstalledSlotuiHostProcessFactory",
    "REQUIRED_SLOTUI_ADAPTER_CAPABILITIES",
    "REQUIRED_SLOTUI_CAPABILITIES",
    "SLOTUI_HOST_CONTROL_PROTOCOL_VERSION",
    "SlotuiCandidateAdapterDAO",
    "SlotuiCandidateRunnerDAO",
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreBundleDAO",
    "SlotuiCoreBundleWheelDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreExportDAO",
    "SlotuiCoreHostError",
    "SlotuiCoreHostService",
    "SlotuiCoreManifestDAO",
    "SlotuiTerminalBridge",
    "SlotuiCoreReferenceDerivationError",
    "SlotuiCoreReferenceDerivationService",
    "SlotuiCoreSourceIdentityDAO",
    "SlotuiCoreTestReportHashDAO",
    "SlotuiCoreUnavailableError",
    "SlotuiCoreVerificationError",
    "SlotuiCoreVerificationReceiptDAO",
    "SlotuiCoreWheelVerificationService",
    "SlotuiHostCommandDAO",
    "SlotuiHostEventDAO",
    "SlotuiHostLaunchConfigDAO",
    "SlotuiHostProcess",
    "SlotuiHostProcessFactory",
    "SlotuiLiveTranscriptMutationDAO",
    "SlotuiOpaqueEvidenceDAO",
    "SlotuiParityMatrix",
    "SlotuiParityMatrixEntryDAO",
    "SlotuiPresentationSelectionDAO",
    "SlotuiPresentationSelector",
    "SlotuiStreamEventMapper",
]
