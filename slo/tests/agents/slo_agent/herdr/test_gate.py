"""Pure disabled construction never creates the later reporter scheduler."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.service import HerdrEnvironmentGate, NullHerdrReporter
from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO


@pytest.mark.parametrize(argnames="value", argvalues=["1", "true", " YES ", "on", "invalid"])
async def test_disabled_build_is_inert(tmp_path: Path, value: str) -> None:
    """Disabled/invalid switches require no executable lookup or store construction."""
    reporter = HerdrEnvironmentGate.build(
        environment={"SLO_HERDR_DISABLED": value, "HERDR_ENV": "1"}, state_root=tmp_path / "absent"
    )
    assert isinstance(reporter, NullHerdrReporter)
    assert reporter.destination == ("unavailable" if value == "invalid" else "platform")
    await reporter.start()
    assert (await reporter.close()).replacement == "safe"
    assert (await reporter.close_transport()).resources == "drained"
    assert (await reporter.drain_retained_external_resources()).resources == "drained"
    assert not reporter.retains_external_resources and not reporter.allows_viewer_admission()
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(argnames="value", argvalues=["", "0", "false", "no", "off"])
def test_enabled_gate_only_captures_config(tmp_path: Path, value: str) -> None:
    """Valid lexical configuration is captured without probing its nonexistent binary."""
    result = HerdrEnvironmentGate.build(
        environment={
            "SLO_HERDR_DISABLED": value,
            "HERDR_ENV": "1",
            "HERDR_PANE_ID": "pane-1",
            "HERDR_BIN_PATH": str(tmp_path / "absent"),
        },
        state_root=tmp_path,
    )
    assert isinstance(result, HerdrReporterConfigDAO)
    assert result.metadata_profile == "compact"
    assert not result.binary_path.exists()
