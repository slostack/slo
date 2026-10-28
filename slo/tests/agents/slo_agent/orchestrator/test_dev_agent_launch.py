"""Finite import-only evidence through the detached launch boundary."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import IO, Optional

import pytest

from src.agents.slo_agent.orchestrator import spawn_env
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore


class ImportOnlySpawn:
    """Replace only the CLI workload; retain the production prefix, env and captures."""

    def __init__(self, *, cwd: Path) -> None:
        """Bind a foreign cwd; the caller owns its disposable directory."""
        self.cwd = cwd
        self.argv: tuple[str, ...] = ()
        self.env: dict[str, str] = {}

    async def __call__(
        self, *argv: str, start_new_session: bool, stdout: IO[bytes], stderr: IO[bytes], env: dict[str, str]
    ) -> asyncio.subprocess.Process:
        """Run imports, not a CLI agent, and reap the finite child even on timeout."""
        self.argv, self.env = argv, env
        script = (
            "import json,sys,src,config,src.cli; "
            "print(json.dumps({'origins':[src.__file__,config.__file__,src.cli.__file__],"
            "'safe_path':sys.flags.safe_path,'no_user_site':sys.flags.no_user_site}))"
        )
        process = await asyncio.create_subprocess_exec(
            *argv[: argv.index("-m")],
            "-B",
            "-c",
            script,
            cwd=self.cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=start_new_session,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=15)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0
        return process


async def test_detached_development_launch_imports_running_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real tool persists identity and captures imports despite hostile cwd/env."""
    root_owned = tmp_path.resolve(strict=True)
    foreign = tmp_path / "foreign"
    assert foreign.resolve().is_relative_to(root_owned)
    foreign.mkdir()
    for name in ("src", "config"):
        package = foreign / name
        assert package.resolve().is_relative_to(root_owned)
        package.mkdir()
        assert (package / "__init__.py").resolve().is_relative_to(root_owned)
        (package / "__init__.py").write_text("raise RuntimeError('hostile import')\n", encoding="utf-8")
    monkeypatch.setenv(name="SLO_DEV_MODE", value="1")
    monkeypatch.setenv(name="PYTHONPATH", value=str(foreign))
    monkeypatch.setenv(name="PYTHONHOME", value=str(foreign))
    monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)
    history = tmp_path / "history"
    assert history.resolve().is_relative_to(root_owned)
    store = WorkflowHandleStore(history_root=history)
    spawn = ImportOnlySpawn(cwd=foreign)
    tool = LaunchWorkflowTool.build(
        owner_session_id="owner",
        default_model=None,
        history_root=history,
        handle_store=store,
        spawn=spawn,
    )
    result = await tool.ainvoke({"brief": "import probe only", "cwd": str(foreign)})
    handle = WorkflowHandleDAO.model_validate_json(result)
    persisted = await store.read(owner_session_id="owner", workflow_id=handle.workflow_id)
    assert persisted == handle
    assert handle.pid > 0 and handle.cwd == str(foreign)
    assert spawn.argv[:5] == (sys.executable, "-P", "-s", "-m", "src.cli")
    assert spawn.argv[5:] == (
        "run",
        "--orchestrator",
        "--json",
        "--enable-history",
        "-p",
        "import probe only",
        "--session-id",
        handle.orchestrator_session_id,
        "--notify-session",
        "owner",
        "--cwd",
        str(foreign),
    )
    assert spawn.env["SLO_WORKFLOW_ID"] == handle.workflow_id
    assert "PYTHONHOME" not in spawn.env
    root = Path(spawn_env.__file__).resolve().parents[4]
    assert spawn.env["PYTHONPATH"] == str(root)
    capture = history / handle.orchestrator_session_id / "stdout.jsonl"
    observed = json.loads(capture.read_text(encoding="utf-8"))
    assert observed["origins"] == [
        str(root / p) for p in ("src/__init__.py", "config/__init__.py", "src/cli/__init__.py")
    ]
    assert observed["safe_path"] and observed["no_user_site"]


class ManagedImportSpawn:
    """Finite import substitute retaining managed pipe and cwd semantics."""

    def __init__(self) -> None:
        """Record the actual launch boundary."""
        self.argv: tuple[str, ...] = ()
        self.env: dict[str, str] = {}

    async def __call__(
        self,
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: Optional[str],
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Start only imports; the real process owner drains and reaps it."""
        self.argv, self.env = argv, env
        script = (
            "import json,sys,src,config,src.cli; "
            "print(json.dumps({'origins':[src.__file__,config.__file__,src.cli.__file__]}))"
        )
        return await asyncio.create_subprocess_exec(
            *argv[: argv.index("-m")],
            "-B",
            "-c",
            script,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            cwd=cwd,
            env=env,
        )


async def test_managed_development_launch_imports_and_persists_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Managed run reaches real subprocess imports and writes its terminal evidence."""
    monkeypatch.setenv(name="SLO_DEV_MODE", value="1")
    history = tmp_path / "history"
    assert history.resolve().is_relative_to(tmp_path.resolve())
    task = SubAgentTaskDAO(
        task_id="probe", task_summary="Verify checkout imports", prompt="import only", cwd=str(tmp_path)
    )
    registry = ProcessRegistry()
    dispatch_id = "44444444-4444-4444-8444-444444444444"
    registry.begin_dispatch(dispatch_id=dispatch_id)
    execution_id = registry.register(dispatch_id=dispatch_id, task_id="probe", session_id="child", task=task)

    async def relay(event: AgentStreamEventDAO) -> None:
        """Imports emit no agent events."""

    spawn = ManagedImportSpawn()
    process = SubAgentProcess(
        task=task,
        session_id="child",
        model=None,
        relay=relay,
        registry=registry,
        execution_id=execution_id,
        parent_session_id="parent",
        history_root=history,
        spawn=spawn,
    )
    result = await asyncio.wait_for(process.run(), timeout=20)
    assert result.status == "completed"
    assert spawn.argv == (
        sys.executable,
        "-P",
        "-s",
        "-m",
        "src.cli",
        "run",
        "--json",
        "-p",
        "import only",
        "--session-id",
        "child",
        "--enable-history",
        "--cwd",
        str(tmp_path),
    )
    capture = history / "parent" / "children" / "child"
    root = Path(spawn_env.__file__).resolve().parents[4]
    assert spawn.env["PYTHONPATH"] == str(root)
    observed = json.loads((capture / "stdout.jsonl").read_text())
    assert observed["origins"] == [
        str(root / p) for p in ("src/__init__.py", "config/__init__.py", "src/cli/__init__.py")
    ]
    assert json.loads((capture / "status.json").read_text())["status"] == "completed"


@pytest.mark.parametrize("adoption", [False, True])
async def test_resume_imports_with_current_parent_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adoption: bool
) -> None:
    """Both resume boundaries preserve durable inputs and append real import output."""
    monkeypatch.setenv(name="SLO_DEV_MODE", value="1")
    history = tmp_path / "history"
    assert history.resolve().is_relative_to(tmp_path.resolve())
    handle = WorkflowHandleDAO(
        workflow_id="wf-probe",
        owner_session_id="owner",
        orchestrator_session_id="original",
        pid=123,
        brief="original brief",
        cwd=str(tmp_path),
    )
    spawn = ImportOnlySpawn(cwd=tmp_path)

    async def change_parent_after_yield() -> None:
        """Change ambient mode while adoption is awaiting capture setup."""
        await asyncio.sleep(0)
        monkeypatch.setenv(name="SLO_DEV_MODE", value="0")

    change = asyncio.create_task(change_parent_after_yield()) if adoption else None
    if adoption:
        async with WorkflowRelauncher.spawn_for_adoption(
            handle=handle, history_root=history, spawn=spawn
        ) as owned:
            assert owned.process.pid > 0
        assert change is not None
        await change
    else:
        outcome = await WorkflowRelauncher.invoke(handle=handle, history_root=history, spawn=spawn)
        assert outcome.pid is not None and outcome.error is None
    assert spawn.argv == (
        sys.executable,
        "-P",
        "-s",
        "-m",
        "src.cli",
        "run",
        "--orchestrator",
        "--json",
        "--enable-history",
        "-p",
        "original brief",
        "--resume",
        "original",
        "--notify-session",
        "owner",
        "--cwd",
        str(tmp_path),
    )
    assert spawn.env["SLO_DEV_MODE"] == "1"
    assert spawn.env["SLO_WORKFLOW_ID"] == "wf-probe"
    root = Path(spawn_env.__file__).resolve().parents[4]
    observed = json.loads((history / "original" / "stdout.jsonl").read_text())
    assert observed["origins"] == [
        str(root / p) for p in ("src/__init__.py", "config/__init__.py", "src/cli/__init__.py")
    ]


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 1", "1 ", "1"])
def test_launch_policy_requires_exact_opt_in(value: Optional[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the exact flag enables source imports; DEV and ambient paths do not."""
    monkeypatch.delenv("SLO_DEV_MODE", raising=False)
    if value is not None:
        monkeypatch.setenv(name="SLO_DEV_MODE", value=value)
    monkeypatch.setenv(name="DEV", value="1")
    monkeypatch.setenv(name="PYTHONPATH", value="/hostile")
    monkeypatch.setenv(name="PYTHONHOME", value="/hostile")
    policy = spawn_env.AgentLaunchPolicy()
    expected = ["-P", "-s"] if value == "1" else ["-I"]
    assert policy.build_argv(arguments=["run"]) == [sys.executable, *expected, "-m", "src.cli", "run"]
    environment = policy.build_environment()
    assert "PYTHONHOME" not in environment
    assert ("PYTHONPATH" in environment) == (value == "1")
    # A launch's argv and environment must not diverge if the parent changes later.
    monkeypatch.setenv(name="SLO_DEV_MODE", value="0" if value == "1" else "1")
    assert policy.build_environment() == environment
    assert policy.build_argv(arguments=["run"]) == [sys.executable, *expected, "-m", "src.cli", "run"]
    environment["SLO_DEV_MODE"] = "mutated"
    assert policy.build_environment().get("SLO_DEV_MODE") == value


@pytest.mark.parametrize("value", [None, "0", "1"])
def test_launch_policy_reserves_mode_and_import_environment(
    value: Optional[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identity extras cannot change interpreter policy or descendant opt-in."""
    monkeypatch.delenv("SLO_DEV_MODE", raising=False)
    if value is not None:
        monkeypatch.setenv(name="SLO_DEV_MODE", value=value)
    monkeypatch.setenv(name="SLO_OPENROUTER_API_KEY", value="synthetic-preserved")
    policy = spawn_env.AgentLaunchPolicy()
    environment = policy.build_environment(
        extra={
            "SLO_DEV_MODE": "0" if value == "1" else "1",
            "PYTHONHOME": "/hostile",
            "PYTHONPATH": "/hostile",
            "SLO_PARENT_PID": "123",
            "SLO_CAPTURE_DIR": "/capture",
        }
    )
    assert environment.get("SLO_DEV_MODE") == value
    assert "PYTHONHOME" not in environment
    assert environment.get("PYTHONPATH") == (
        str(Path(spawn_env.__file__).resolve().parents[4]) if value == "1" else None
    )
    assert environment["SLO_PARENT_PID"] == "123"
    assert environment["SLO_CAPTURE_DIR"] == "/capture"
    assert environment["SLO_OPENROUTER_API_KEY"] == "synthetic-preserved"


@pytest.mark.e2e
async def test_development_descendant_imports_running_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finite child builds its own policy and imports the same code in a grandchild."""
    monkeypatch.setenv(name="SLO_DEV_MODE", value="1")
    policy = spawn_env.AgentLaunchPolicy()
    leaf = (
        "import json,sys,os,src,config,src.cli; "
        "print(json.dumps({'origins':[src.__file__,config.__file__,src.cli.__file__],"
        "'mode':os.environ.get('SLO_DEV_MODE'),'safe':sys.flags.safe_path,"
        "'user':sys.flags.no_user_site,'isolated':sys.flags.isolated}))"
    )
    script = (
        "import subprocess; from src.agents.slo_agent.orchestrator.spawn_env import AgentLaunchPolicy; "
        "p=AgentLaunchPolicy(); a=p.build_argv(arguments=[]); "
        f"r=subprocess.run(a[:a.index('-m')]+['-B','-c',{leaf!r}],env=p.build_environment(),"
        "capture_output=True,text=True,timeout=15,check=True); print(r.stdout,end='')"
    )
    argv = policy.build_argv(arguments=[])
    child = await asyncio.create_subprocess_exec(
        *argv[: argv.index("-m")],
        "-B",
        "-c",
        script,
        cwd=tmp_path,
        env=policy.build_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=20)
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
    assert child.returncode == 0, stderr.decode()
    observed = json.loads(stdout)
    root = Path(spawn_env.__file__).resolve().parents[4]
    assert observed == {
        "origins": [str(root / p) for p in ("src/__init__.py", "config/__init__.py", "src/cli/__init__.py")],
        "mode": "1",
        "safe": True,
        "user": 1,
        "isolated": 0,
    }
