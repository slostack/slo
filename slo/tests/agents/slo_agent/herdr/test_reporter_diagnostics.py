"""Fixed diagnostics at real reporter accounting and activation boundaries."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO, HerdrReportOperation
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


@pytest.mark.parametrize(
    "operation,category",
    [
        ("claim", "publication_failed"),
        ("restore", "restore_unavailable"),
        ("replace_release", "release_unavailable"),
        ("activation_release", "activation_unavailable"),
    ],
)
def test_accounting_failure_recovery(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, operation: HerdrReportOperation, category: str
) -> None:
    """Non-ok accounting emits fixed failure then exactly one confirmed recovery."""
    owner = reporter(root=tmp_path)
    ticket = HerdrReportTicketDAO(
        operation=operation,
        sequence=1,
        configuration_generation=0,
        report_revision=1,
        publication=None if operation == "activation_release" else publication(),
    )
    owner._admitted_ticket = ticket
    owner._record_command_result(
        ticket=ticket, result=HerdrCliTransport._failure(status="unavailable", admitted=True)
    )
    assert [record.message for record in caplog.records] == ["herdr_" + category]
    owner._admitted_ticket = ticket
    owner._record_command_result(ticket=ticket, result=HerdrCliTransport._failure(status="ok", admitted=True))
    assert [record.message for record in caplog.records] == [
        "herdr_" + category,
        "herdr_" + category + "_recovered",
    ]


async def test_activation_probe_failure_diagnostic(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Missing executable fails locally with a fixed activation diagnostic."""
    owner = reporter(root=tmp_path)
    await owner.start()
    assert "herdr_activation_unavailable" in caplog.text
    assert str(tmp_path) not in caplog.text
