"""Real pytest invocation coverage for worker state and test entry points."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

import pytest
import yaml

PROJECT: Path = Path(__file__).resolve().parents[1]
CI_OAUTH_IGNORES: tuple[str, ...] = (
    "tests/auth/test_authorization_response.py",
    "tests/auth/test_device_authorization.py",
    "tests/auth/test_headless_readme_oauth_timeouts.py",
    "tests/auth/test_oauth_errors.py",
    "tests/auth/test_oauth_flow.py",
    "tests/auth/test_oauth_provider.py",
    "tests/auth/test_oauth_provider_refresh.py",
    "tests/auth/test_pkce.py",
    "tests/auth/test_provider_factory.py",
    "tests/auth/providers/test_anthropic_provider.py",
    "tests/auth/providers/test_openai_codex_device_authorization.py",
    "tests/auth/providers/test_openai_codex_provider.py",
    "tests/tui/authentication/test_auth_screen.py",
    "tests/tui/authentication/test_authentication_device_e2e.py",
    "tests/tui/authentication/test_authentication_headless_e2e.py",
    "tests/tui/authentication/widgets/test_authorization_link.py",
    "tests/tui/authentication/widgets/test_oauth_status.py",
)


def test_parallel_dependency_and_ci_are_declared() -> None:
    """Require reproducible dev installation and parallel canonical CI invocation."""
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(dependency.startswith("pytest-xdist ") for dependency in project["dependency-groups"]["dev"])
    pipeline = yaml.safe_load((PROJECT.parent / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    exclusions: str = " ".join(f"--ignore={path}" for path in CI_OAUTH_IGNORES)
    assert pipeline["pytest"]["script"] == [
        f'PYTEST_ADDOPTS="-q --junitxml=../report.xml {exclusions}" make test PYTEST_WORKERS=12'
    ]


def test_ci_oauth_exclusions_preserve_mixed_auth_and_readiness_collection(tmp_path: Path) -> None:
    """Apply CI's real options to bounded collection, never executing OAuth or process tests.

    Args:
        tmp_path (Path): Owns child pytest state; no reports or caches touch the checkout.
    """
    pipeline = yaml.safe_load((PROJECT.parent / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assignment: str = shlex.split(pipeline["pytest"]["script"][0])[0]
    options: list[str] = shlex.split(assignment.removeprefix("PYTEST_ADDOPTS="))
    collection_options: list[str] = [option for option in options if not option.startswith("--junitxml=")]
    retained_nodes: tuple[str, ...] = (
        "tests/agents/test_base.py::TestLLMFactoryOpenAIRouting::test_oauth_credential_routes_to_chatgpt_backend",
        "tests/agents/providers/test_feature89_credentials.py::test_environment_key_beats_real_stored_oauth",
        "tests/agents/providers/test_openai_responses_sequencing.py::test_calls_keep_arguments_and_replay_when_streams_interleave",
        "tests/integration/test_herdr_restore_harness_safety.py::test_supervisor_reaps_real_descendants[early]",
    )
    assert (tmp_path / "pytest").resolve().is_relative_to(tmp_path.resolve())
    completed = subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "pytest"),
            "tests/auth",
            "tests/tui/authentication",
            *retained_nodes,
        ],
        cwd=PROJECT,
        env={
            **{name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"},
            "PYTEST_ADDOPTS": shlex.join(collection_options),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    collected: list[str] = [line for line in completed.stdout.splitlines() if line.startswith("tests/")]
    assert collected
    assert not any(node.startswith(path + "::") for path in CI_OAUTH_IGNORES for node in collected)
    for module in (
        "tests/auth/test_browser_host.py",
        "tests/auth/test_credential_dao.py",
        "tests/auth/test_credential_store.py",
        "tests/auth/test_credential_resolver.py",
        "tests/auth/test_credential_refresher.py",
        "tests/auth/test_openrouter_authentication.py",
        "tests/tui/authentication/test_openrouter_authentication.py",
        "tests/tui/authentication/widgets/test_method_select.py",
        "tests/tui/authentication/widgets/test_api_key_input.py",
    ):
        assert any(node.startswith(module + "::") for node in collected), module
    for node in retained_nodes:
        assert any(item == node or item.startswith(node + "[") for item in collected), node


@pytest.mark.parametrize(
    argnames="arguments, worker_environment, expected",
    argvalues=[
        (["test"], {}, 'pytest -n auto -m "not e2e"'),
        (["test-serial"], {}, 'pytest -n 0 -m "not e2e"'),
        (["test", "PYTEST_WORKERS=0"], {}, 'pytest -n 0 -m "not e2e"'),
        (["test"], {"PYTEST_WORKERS": "3"}, 'pytest -n 3 -m "not e2e"'),
        (["test", "PYTEST_WORKERS=0"], {"PYTEST_WORKERS": "3"}, 'pytest -n 0 -m "not e2e"'),
        (["smoke"], {}, 'pytest -m "not e2e" tests/test_smoke.py -v'),
    ],
)
def test_make_selects_worker_mode(
    arguments: list[str], worker_environment: dict[str, str], expected: str
) -> None:
    """Inspect each Make invocation independently of the outer suite's worker mode.

    Only the nested probe loses inherited Make controls; the actual suite retains
    its operator-selected mode. Case-specific exports still exercise real Make
    environment precedence, including command-line overrides of exported values.

    Args:
        arguments (list[str]): Target and command-line overrides for the nested Make.
        worker_environment (dict[str, str]): Worker controls exported to the nested Make.
        expected (str): Expected pytest command in the dry-run output.
    """
    environment: dict[str, str] = {
        name: value
        for name, value in os.environ.items()
        if name not in {"MAKEFLAGS", "MAKEOVERRIDES", "MFLAGS", "GNUMAKEFLAGS", "MAKELEVEL", "PYTEST_WORKERS"}
    }
    environment.update(worker_environment)
    completed = subprocess.run(
        args=["make", "--no-print-directory", "-n", *arguments],
        cwd=PROJECT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert expected in completed.stdout


@pytest.mark.parametrize(argnames="workers", argvalues=["0", "2"])
@pytest.mark.parametrize(argnames="outer_options", argvalues=["", "selection", "relative-path", "report"])
def test_pytest_workers_own_collection_and_test_state(
    tmp_path: Path, workers: str, outer_options: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real conftest in child pytest processes and read disk receipts.

    Each worker runs the specimen with dist=each so the assertion cannot pass
    merely because one worker was idle. Only temp-owned files are written.
    Parent selection and report settings must not control the child invocation.

    Args:
        tmp_path (Path): Temporary directory owning the specimen and all child outputs.
        workers (str): Explicit child worker count, serial zero or two workers.
        outer_options (str): Inherited pytest option scenario; empty retains caller options.
        monkeypatch (pytest.MonkeyPatch): Restore scenario environment changes after the test.
    """
    parent_report: Path = tmp_path / "parent-report.xml"
    assert parent_report.resolve().is_relative_to(tmp_path.resolve())
    parent_report.write_text(data="parent-report-sentinel", encoding="utf-8")
    inherited_options: dict[str, str] = {
        "selection": "-k test_pytest_workers_own_collection_and_test_state",
        "relative-path": "tests/test_parallel_invocation.py",
        "report": f"--junitxml={parent_report}",
    }
    if outer_options:
        monkeypatch.setenv(name="PYTEST_ADDOPTS", value=inherited_options[outer_options])
    scratch: Path = tmp_path / "scratch"
    assert scratch.resolve().is_relative_to(tmp_path.resolve())
    scratch.mkdir()
    conftest: Path = tmp_path / "conftest.py"
    assert conftest.resolve().is_relative_to(tmp_path.resolve())
    conftest.write_text(data=(PROJECT / "tests/conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    specimen: Path = tmp_path / "test_worker.py"
    assert specimen.resolve().is_relative_to(tmp_path.resolve())
    specimen.write_text(
        data="""import json, os
from pathlib import Path
COLLECTION_HOME = Path(os.environ["SLO_HOME"])
COLLECTION_ENV = {name: os.environ[name] for name in ("HOME", "SLO_HOME", "SLO_AUTH_FILE")}

def test_worker(isolated_slo_home: Path) -> None:
    '''Verify worker-owned state and persist a receipt for the parent pytest test.

    Args:
        isolated_slo_home (Path): Per-test home supplied by the real isolation fixture.
    '''
    receipt_root = Path(__file__).parent.resolve()
    root = isolated_slo_home.resolve()
    assert root.is_relative_to(receipt_root)
    assert COLLECTION_HOME.is_relative_to(receipt_root)
    assert Path(COLLECTION_ENV["HOME"]) == COLLECTION_HOME / "home"
    assert Path(COLLECTION_ENV["SLO_AUTH_FILE"]).is_relative_to(COLLECTION_HOME)
    assert root != COLLECTION_HOME
    assert Path(os.environ["HOME"]) == root / "home"
    auth = Path(os.environ["SLO_AUTH_FILE"])
    assert auth.resolve().is_relative_to(root)
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("synthetic-worker-state")
    assert auth.read_text() == "synthetic-worker-state"
    worker = os.environ.get("PYTEST_XDIST_WORKER", "serial")
    receipt = receipt_root / (worker + ".json")
    assert receipt.resolve().is_relative_to(receipt_root)
    receipt.write_text(json.dumps({"collection": str(COLLECTION_HOME), "test": str(root)}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-n",
            workers,
            "--dist=each",
            "--basetemp",
            str(scratch / "pytest"),
            str(specimen),
        ],
        cwd=tmp_path,
        env={
            # The specimen owns selection and output; parent pytest options do not apply.
            **{name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"},
            "PYTHONPATH": str(PROJECT),
            "TMPDIR": str(scratch),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert parent_report.read_text(encoding="utf-8") == "parent-report-sentinel"
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipts: list[dict[str, str]] = [json.loads(path.read_text()) for path in tmp_path.glob("*.json")]
    expected_count: int = 1 if workers == "0" else 2
    assert len(receipts) == expected_count
    assert len({receipt["collection"] for receipt in receipts}) == expected_count
    assert len({receipt["test"] for receipt in receipts}) == expected_count
    assert all(not Path(receipt["collection"]).exists() for receipt in receipts)
