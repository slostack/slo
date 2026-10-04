"""The released runner must isolate environment, imports and writable directories."""

from pathlib import Path

import pytest

from tests.compat.released_runner import REPOSITORY_ROOT, run_released_slo


def test_run_released_slo_when_parent_is_hostile_uses_only_owned_state(
    released_slo_source: Path, isolated_slo_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic ambient overrides cannot change the child identity or state roots."""
    monkeypatch.setenv(name="SLO_CAPTURE_DIR", value=str(isolated_slo_home / "forbidden"))
    result = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script="""
import json, os
from pathlib import Path
import src.auth.credential_dao as dao
print(json.dumps({"source": dao.__file__, "cwd": str(Path.cwd()), "home": os.environ["HOME"],
                  "capture": os.environ.get("SLO_CAPTURE_DIR"), "providers": [p.value for p in dao.ProviderName]}))
""",
    )
    assert result.returncode == 0, result.stderr
    assert Path(str(result.result["source"])).is_relative_to(released_slo_source)
    assert Path(str(result.result["cwd"])).is_relative_to(isolated_slo_home)
    assert Path(str(result.result["home"])).is_relative_to(isolated_slo_home)
    assert result.result["capture"] is None
    assert result.result["providers"] == ["anthropic", "openai", "kimi_for_coding"]


def test_run_released_slo_when_override_is_not_script_input_refuses_it(isolated_slo_home: Path) -> None:
    """The caller cannot replace HOME or PYTHONPATH through script inputs."""
    with pytest.raises(AssertionError):
        run_released_slo(
            source=isolated_slo_home, slo_home=isolated_slo_home, script="", extra_env={"HOME": "/"}
        )


def test_run_released_slo_when_child_fails_retains_exit_and_stderr(
    released_slo_source: Path, isolated_slo_home: Path
) -> None:
    """An unsuccessful released program cannot be reported as a successful empty result."""
    result = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script='import sys; sys.stderr.write("synthetic refusal"); sys.exit(7)',
    )
    assert result.returncode == 7
    assert result.stderr == "synthetic refusal"
    assert result.result == {}


def test_ci_when_running_compatibility_fetches_full_history_and_tags() -> None:
    """The default CI pytest job has the frozen release available without optional skips."""
    pipeline = (REPOSITORY_ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    pytest_job = pipeline.split("\npytest:\n", maxsplit=1)[1].split("\npublish-installer:\n", maxsplit=1)[0]
    assert "    GIT_DEPTH: '0'" in pytest_job
    assert "    GIT_FETCH_EXTRA_FLAGS: '--tags'" in pytest_job
