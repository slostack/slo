"""Fixed configuration diagnostics never expose captured environment values."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO
from src.agents.slo_agent.herdr.service import HerdrEnvironmentGate, NullHerdrReporter


@pytest.fixture(autouse=True)
def isolated_gate_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own fixed-category diagnostic episode history."""
    monkeypatch.setattr(target=HerdrEnvironmentGate, name="_failure_times", value={}, raising=False)


@pytest.mark.parametrize(argnames="case", argvalues=["switch", "pane", "binary", "profile"])
def test_invalid_gate_emits_fixed_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """Refuse invalid activation or default the profile without logging its value."""
    environment = {"HERDR_ENV": "1", "HERDR_PANE_ID": "p", "HERDR_BIN_PATH": str(tmp_path / "absent")}
    key, value = {
        "switch": ("SLO_HERDR_DISABLED", "private-switch-sentinel"),
        "pane": ("HERDR_PANE_ID", "private-pane\nsentinel"),
        "binary": ("HERDR_BIN_PATH", "private-relative-sentinel"),
        "profile": ("SLO_HERDR_METADATA_PROFILE", "private-profile-sentinel"),
    }[case]
    environment[key] = value
    result = HerdrEnvironmentGate.build(environment=environment, state_root=tmp_path / "state")
    if case == "profile":
        assert isinstance(result, HerdrReporterConfigDAO)
        assert result.metadata_profile == "compact"
    else:
        assert isinstance(result, NullHerdrReporter)
        assert result.destination == "unavailable"
    expected = "herdr_invalid_metadata_profile" if case == "profile" else "herdr_invalid_configuration"
    assert [record.getMessage() for record in caplog.records] == [expected]
    assert "private" not in caplog.text and str(tmp_path) not in caplog.text
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("category", ["invalid_configuration", "invalid_metadata_profile"])
def test_gate_cross_build_category_window(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, category: str
) -> None:
    """Independent builds share a 60-second fixed-category warning window."""
    environment = {"HERDR_ENV": "1", "HERDR_PANE_ID": "p", "HERDR_BIN_PATH": str(tmp_path / "absent")}
    key = "SLO_HERDR_DISABLED" if category == "invalid_configuration" else "SLO_HERDR_METADATA_PROFILE"
    environment[key] = "private-sentinel"
    with patch("src.agents.slo_agent.herdr.service.time.monotonic", side_effect=[100.0, 159.999, 160.0]):
        for _ in range(3):
            HerdrEnvironmentGate.build(environment=environment, state_root=tmp_path)
    assert [record.getMessage() for record in caplog.records] == ["herdr_" + category] * 2
    assert "private-sentinel" not in caplog.text


@pytest.mark.parametrize("category", ["invalid_configuration", "invalid_metadata_profile"])
def test_gate_recovery_is_once_per_episode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, category: str
) -> None:
    """Valid capture recovers only its fixed category, without exposing prior values."""
    valid = {"HERDR_ENV": "1", "HERDR_PANE_ID": "p", "HERDR_BIN_PATH": str(tmp_path / "absent")}
    invalid = dict(valid)
    key = "SLO_HERDR_DISABLED" if category == "invalid_configuration" else "SLO_HERDR_METADATA_PROFILE"
    invalid[key] = "private-sentinel"
    for environment in (invalid, valid, valid, invalid, valid):
        HerdrEnvironmentGate.build(environment=environment, state_root=tmp_path)
    assert [record.getMessage() for record in caplog.records] == [
        "herdr_" + category,
        "herdr_" + category + "_recovered",
        "herdr_" + category,
        "herdr_" + category + "_recovered",
    ]


@pytest.mark.parametrize("inactive", [{"SLO_HERDR_DISABLED": "1"}, {"HERDR_ENV": "0"}])
def test_gate_categories_and_inactive_builds_are_independent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, inactive: dict[str, str]
) -> None:
    """Inactive capture neither fails nor recovers either outstanding category."""
    valid = {"HERDR_ENV": "1", "HERDR_PANE_ID": "p", "HERDR_BIN_PATH": str(tmp_path / "absent")}
    invalid = dict(valid, HERDR_PANE_ID="private\nsentinel", SLO_HERDR_METADATA_PROFILE="private-profile")
    HerdrEnvironmentGate.build(environment=invalid, state_root=tmp_path)
    assert set(HerdrEnvironmentGate._failure_times) == {"invalid_configuration", "invalid_metadata_profile"}
    HerdrEnvironmentGate.build(environment=dict(invalid, **inactive), state_root=tmp_path)
    assert len(caplog.records) == 2
    result = HerdrEnvironmentGate.build(
        environment=dict(valid, SLO_HERDR_METADATA_PROFILE="private-profile"), state_root=tmp_path
    )
    assert isinstance(result, HerdrReporterConfigDAO) and result.metadata_profile == "compact"
    assert set(HerdrEnvironmentGate._failure_times) == {"invalid_metadata_profile"}
    for profile in ("detail", "compact"):
        result = HerdrEnvironmentGate.build(
            environment=dict(valid, SLO_HERDR_METADATA_PROFILE=profile), state_root=tmp_path
        )
        assert isinstance(result, HerdrReporterConfigDAO) and result.metadata_profile == profile
    assert [record.getMessage() for record in caplog.records] == [
        "herdr_invalid_metadata_profile",
        "herdr_invalid_configuration",
        "herdr_invalid_configuration_recovered",
        "herdr_invalid_metadata_profile_recovered",
    ]
    assert HerdrEnvironmentGate._failure_times == {}
    assert "private" not in caplog.text and str(tmp_path) not in caplog.text


def test_gate_sink_recovery_is_not_retried(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A failed sink consumes an episode without fallback logging or repeated recovery."""
    valid = {"HERDR_ENV": "1", "HERDR_PANE_ID": "p", "HERDR_BIN_PATH": str(tmp_path / "absent")}
    with patch("logging.Logger.warning", side_effect=RuntimeError("private-sink")) as sink:
        HerdrEnvironmentGate.build(environment=dict(valid, SLO_HERDR_DISABLED="invalid"), state_root=tmp_path)
        HerdrEnvironmentGate.build(environment=valid, state_root=tmp_path)
        assert sink.call_count == 2
    HerdrEnvironmentGate.build(environment=valid, state_root=tmp_path)
    assert not caplog.records and not HerdrEnvironmentGate._failure_times


def test_gate_diagnostic_sink_failure_is_isolated(tmp_path: Path) -> None:
    """A broken logging sink cannot turn optional observation into a startup error."""
    with patch("logging.Logger.warning", side_effect=RuntimeError("private-sink")):
        result = HerdrEnvironmentGate.build(
            environment={"HERDR_ENV": "1", "SLO_HERDR_DISABLED": "invalid"}, state_root=tmp_path
        )
    assert isinstance(result, NullHerdrReporter)
    assert result.destination == "unavailable"
