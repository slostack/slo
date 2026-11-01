"""Terminal accounting matrix separates actual effects from desired acknowledgements."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrReportOperation,
    HerdrReportTicketDAO,
    HerdrRemoteBindingDAO,
    HerdrSavedRestoreDAO,
    HerdrRestoreReferenceDAO,
    HerdrCommandStatus,
)
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.agents.slo_agent.herdr.test_reporter import reporter, publication


@pytest.mark.parametrize(
    "operation",
    [
        "claim",
        "lifecycle",
        "restore",
        "clear",
        "set",
        "replace_release",
        "activation_release",
        "shutdown_release",
        "shutdown_clear",
    ],
)
@pytest.mark.parametrize("status", ["ok", "rejected", "timeout", "cancelled", "unavailable", "malformed"])
@pytest.mark.parametrize("stale", [False, True])
def test_terminal_operation_matrix(
    tmp_path: Path,
    operation: HerdrReportOperation,
    status: HerdrCommandStatus,
    stale: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every admitted result consumes its slot; only current success acknowledges facts."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    assert facts.restore_capture is not None
    saved = HerdrSavedRestoreDAO(
        configuration_generation=0,
        capture=facts.restore_capture,
        reference=HerdrRestoreReferenceDAO(restore_reference="r1-" + "0" * 32),
    )
    binding = HerdrRemoteBindingDAO(
        configuration_generation=0,
        session_id=facts.snapshot.session_id,
        capture=facts.restore_capture,
        reference=saved.reference,
        certainty="confirmed",
    )
    owner._saved = saved
    owner._binding = binding
    lifetime = operation in ("activation_release", "shutdown_release", "shutdown_clear")
    ticket = HerdrReportTicketDAO(
        operation=operation,
        sequence=1,
        configuration_generation=0,
        report_revision=1,
        publication=None if lifetime else facts,
        saved=saved if operation == "restore" else None,
        binding=binding,
        display_final=operation in ("clear", "set"),
        close_token=1 if operation.startswith("shutdown_") else None,
    )
    owner._admitted_ticket = ticket
    owner._mark_admitted(ticket=ticket)
    if stale:
        owner.publish(publication=publication(generation=1, eligible=True))
    category = {
        "activation_release": "activation_unavailable",
        "replace_release": "release_unavailable",
        "shutdown_release": "release_unavailable",
        "shutdown_clear": "release_unavailable",
        "restore": "restore_unavailable",
    }.get(operation, "publication_failed")
    if status == "cancelled":
        owner._diagnostic_failures.add(category)
    before_messages = list(caplog.messages)
    before_failures = set(owner._diagnostic_failures)
    owner._record_command_result(
        ticket=ticket,
        result=HerdrCliTransport._failure(status=status, admitted=True),
    )
    if status == "cancelled":
        assert caplog.messages == before_messages
        assert owner._diagnostic_failures == before_failures
    assert owner._admitted_ticket is None and owner._before_admission_binding is None
    success = status == "ok"
    semantic = operation in ("claim", "lifecycle", "restore")
    assert (owner._lifecycle_ack is not None) == (success and not stale and semantic)
    assert (owner._restore_ack is not None) == (success and not stale and operation == "restore")
    assert (owner._display_ack_revision == 1) == (success and not stale and operation in ("clear", "set"))
    released = success and operation in ("replace_release", "shutdown_release")
    assert (owner._binding is None) == released
    if owner._binding is not None:
        assert owner._binding.reference == saved.reference
        assert owner._binding.configuration_generation == 0
        assert owner._binding.certainty == (
            "possible" if operation == "claim" and not success else "confirmed"
        )
    assert owner._activation_released == (success and operation == "activation_release")
    assert owner._shutdown_released == (success and operation == "shutdown_release")
