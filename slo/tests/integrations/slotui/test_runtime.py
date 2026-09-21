"""Candidate-gated real adapter integration; no toy wheel is runtime evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.integrations.slotui.dao import SlotuiCoreArtifactReferenceDAO
from src.integrations.slotui.host import InstalledSlotuiHostProcess, SlotuiCoreHostService
from src.integrations.slotui.host_protocol import SLOTUI_HOST_CONTROL_PROTOCOL_VERSION
from src.integrations.slotui.reference import SlotuiCoreReferenceDerivationService
from src.integrations.slotui.verifier import SlotuiCoreWheelVerificationService

_CANDIDATE_REFERENCE_ENV: str = "SLO_SLOTUI_CANDIDATE_REFERENCE"


@pytest.mark.e2e
def test_real_bundle_static_verification_accepts_the_supplied_complete_closure(tmp_path: Path) -> None:
    """Verify the supplied v2 reference and every pinned offline wheel without importing Slotui."""
    reference_path: Path = _require_pinned_candidate_reference(tmp_path=tmp_path)
    reference = SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))

    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert receipt.wheel_path.name == "slotui-0.1.0-py3-none-any.whl"
    assert receipt.wheel_path.parent == reference.manifest_path.parent


@pytest.mark.e2e
async def test_real_candidate_adapter_roundtrips_editor_submit_and_actual_slo_session(
    tmp_path: Path,
) -> None:
    """Run the supplied wheel in a fresh venv and PTY through the candidate's test hook.

    The actual candidate owns the terminal, mounted transcript, test-hook editor
    submission, and acknowledgements.  Slo owns the real deterministic session;
    the assertions below intentionally inspect only Slo's installed-process
    boundary and never import or emulate candidate code.
    """
    reference_path: Path = _require_pinned_candidate_reference(tmp_path=tmp_path)
    reference = SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))
    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)
    process = InstalledSlotuiHostProcess(receipt=receipt)
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="candidate-gated response")])),
        workdir=tmp_path,
        session_id="slotui-candidate-gated-session",
        enable_history=False,
    )
    service = SlotuiCoreHostService(
        session=session,
        process=process,
        workdir=tmp_path,
        resume_session_id=None,
    )
    original_test_prompt: str | None = os.environ.get("SLO_SLOTUI_PROTOCOL_TEST_PROMPT")
    os.environ["SLO_SLOTUI_PROTOCOL_TEST_PROMPT"] = "candidate-gated editor submission"
    try:
        await service.invoke()
    finally:
        if original_test_prompt is None:
            os.environ.pop("SLO_SLOTUI_PROTOCOL_TEST_PROMPT", None)
        else:
            os.environ["SLO_SLOTUI_PROTOCOL_TEST_PROMPT"] = original_test_prompt
        await process.aclose()

    assert process._shutdown_sent is False
    assert process._closed is True
    assert process._process is None
    assert process._runtime_root is None
    assert process._terminal_master_fd is None
    assert process._terminal_slave_fd is None
    assert process._sent_mutation_ids == set()
    assert process._acknowledged_mutation_ids == set()
    assert process._receipt.wheel_path.parent == reference.manifest_path.parent
    assert receipt.manifest.candidate_adapter.protocol_version == SLOTUI_HOST_CONTROL_PROTOCOL_VERSION


def _require_pinned_candidate_reference(*, tmp_path: Path | None) -> Path:
    """Resolve a supplied v2 reference or derive a separate pinned one from a legacy input.

    Args:
        tmp_path (Path | None): Test-local output root for legacy conversion. ``None`` rejects
            an unpinned legacy environment reference.

    Returns:
        Path: Existing or newly derived absolute v2 pinned reference.
    """
    reference_path: Path = _require_candidate_reference_path()
    payload: dict[str, object] = _load_reference_payload(path=reference_path)
    if "bundle_path" in payload and "bundle_sha256" in payload:
        return reference_path
    if tmp_path is None:
        pytest.fail(
            f"{_CANDIDATE_REFERENCE_ENV} is a legacy unpinned reference; run the runtime roundtrip "
            "test to derive a temporary v2 reference with its colocated bundle"
        )
    return _derive_pinned_reference(
        legacy_reference_path=reference_path,
        bundle_path=reference_path.parent / "slotui-local-core-candidate.bundle.json",
        output_path=tmp_path / "slotui-derived-pinned-reference.json",
    )


def _require_candidate_reference_path() -> Path:
    """Resolve the absolute protected-candidate release reference from the test environment.

    Returns:
        Path: Existing absolute reference supplied by protected CI or the operator.
    """
    reference_text: str | None = os.environ.get(_CANDIDATE_REFERENCE_ENV)
    if reference_text is None:
        pytest.skip(f"set {_CANDIDATE_REFERENCE_ENV} to run protected candidate adapter integration")
    reference_path: Path = Path(reference_text).expanduser()
    if not reference_path.is_absolute():
        pytest.fail("candidate runtime reference must be absolute")
    if not reference_path.is_file() or reference_path.is_symlink():
        pytest.fail("candidate runtime reference must name an existing regular non-symlink file")
    return reference_path


def _load_reference_payload(*, path: Path) -> dict[str, object]:
    """Load the environment reference only to determine whether its v2 bundle pins exist.

    Args:
        path (Path): Existing regular candidate reference file.

    Returns:
        dict[str, object]: JSON object used to select direct validation or explicit derivation.
    """
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        pytest.fail(f"candidate runtime reference must contain JSON: {error}")
    if not isinstance(payload, dict):
        pytest.fail("candidate runtime reference must contain a JSON object")
    return payload


def _derive_pinned_reference(*, legacy_reference_path: Path, bundle_path: Path, output_path: Path) -> Path:
    """Write and return a test-local v2 reference without changing legacy candidate artifacts.

    Args:
        legacy_reference_path (Path): Supplied legacy candidate reference.
        bundle_path (Path): Explicit colocated local candidate bundle to pin.
        output_path (Path): New test-local reference destination.

    Returns:
        Path: New absolute fully pinned v2 reference.
    """
    SlotuiCoreReferenceDerivationService.derive(
        legacy_reference_path=legacy_reference_path,
        bundle_path=bundle_path,
        output_path=output_path,
    )
    return output_path
