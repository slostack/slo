"""Invocation-local transport failure episodes never disclose private wire data."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrReporterConfigDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.state_isolation import FakeHerdrFixture


async def test_transport_failure_episode_recovers_once(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Real rejected commands log one failure and one subsequent successful recovery."""
    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p",
            binary_path=fake_herdr.executable,
            state_root=tmp_path,
            metadata_profile="compact",
        ),
        environment={},
    )
    assert fake_herdr.executable.resolve().parent == tmp_path.resolve()
    assert not fake_herdr.executable.is_symlink()
    fake_herdr.executable.write_text(
        fake_herdr.executable.read_text() + "\nif sys.argv[2] == 'rename': sys.exit(7)\n"
    )
    failed = HerdrCliCommandDAO(argv=("pane", "rename"))
    good = HerdrCliCommandDAO(argv=("pane", "split"))
    try:
        for _ in range(2):
            result = await transport.invoke(command=failed, admission=RecordingAdmission())
            assert result.outcome.status == "rejected"
        for _ in range(2):
            result = await transport.invoke(command=good, admission=RecordingAdmission())
            assert result.outcome.status == "ok"
        assert [record.message for record in caplog.records if record.message.startswith("herdr_")] == [
            "herdr_command_unavailable",
            "herdr_command_unavailable_recovered",
        ]
        assert str(tmp_path) not in caplog.text
    finally:
        await transport.close()
