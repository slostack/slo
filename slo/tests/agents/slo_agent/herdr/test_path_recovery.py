"""PATH recovery is independent of private saves and remote installation."""

from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


async def test_path_recovery_does_not_acknowledge_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A recovered PATH emits once while a failed remote install stays unresolved."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._log_failure(category="restore_unavailable")
    monkeypatch.setattr(owner, "_plain_slo_available", lambda: False)
    await owner._consume_publication(publication=facts)
    await owner._consume_publication(publication=facts)
    monkeypatch.setattr(owner, "_plain_slo_available", lambda: True)
    await owner._consume_publication(publication=facts)
    await owner._consume_publication(publication=facts)
    assert [record.message for record in caplog.records] == [
        "herdr_restore_unavailable",
        "herdr_restore_path_unavailable",
        "herdr_restore_path_unavailable_recovered",
    ]
    assert "restore_unavailable" in owner._diagnostic_failures
    assert owner._restore_ack is None
    assert owner._binding is None
    assert owner._transport._active is None
