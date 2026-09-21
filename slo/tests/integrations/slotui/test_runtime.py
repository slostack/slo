"""Candidate-gated real adapter integration; no toy wheel is runtime evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.integrations.slotui.dao import SlotuiCoreArtifactReferenceDAO
from src.integrations.slotui.host import InstalledSlotuiHostProcess, SlotuiCoreHostService
from src.integrations.slotui.host_protocol import SLOTUI_HOST_CONTROL_PROTOCOL_VERSION
from src.integrations.slotui.verifier import SlotuiCoreWheelVerificationService

_CANDIDATE_REFERENCE_ENV: str = "SLO_SLOTUI_CANDIDATE_REFERENCE"


@pytest.mark.e2e
def test_real_bundle_static_verification_accepts_the_supplied_complete_closure(tmp_path: Path) -> None:
    """Verify the supplied v2 reference and every pinned offline wheel without importing Slotui."""
    reference_path: Path = _require_production_pinned_candidate_reference()
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
    reference_path: Path = _require_production_pinned_candidate_reference()
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


def test_runtime_gate_when_supplied_reference_is_legacy_rejects_without_deriving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep production E2E aligned with selector behavior for missing bundle pins."""
    legacy_reference: Path = tmp_path / "legacy-reference.json"
    legacy_reference.write_text(
        """{
  \"schema_version\": \"slo-slotui-candidate-adapter-v2\",
  \"candidate_label\": \"legacy\",
  \"manifest_path\": \"/absolute/manifest.json\",
  \"manifest_sha256\": \"0000000000000000000000000000000000000000000000000000000000000000\"
}""",
        encoding="utf-8",
    )
    monkeypatch.setenv(_CANDIDATE_REFERENCE_ENV, str(legacy_reference))

    with pytest.raises(pytest.fail.Exception, match="production-compatible v2 reference"):
        _require_production_pinned_candidate_reference()


def _require_production_pinned_candidate_reference() -> Path:
    """Require the exact production v2 release reference without test-local derivation.

    A legacy pointer lacks its independent bundle path and digest, so Slo's
    production selector rejects it. Tests must prove the same input the operator
    could launch; they never manufacture a temporary release reference.

    Returns:
        Path: Existing fully pinned regular v2 reference supplied by release CI.
    """
    reference_path: Path = _require_candidate_reference_path()
    try:
        SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as error:
        pytest.fail(
            f"{_CANDIDATE_REFERENCE_ENV} is not a production-compatible v2 reference: {error}. "
            "It must supply bundle_path and bundle_sha256; Slo will not derive those fields at runtime."
        )
    return reference_path


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
