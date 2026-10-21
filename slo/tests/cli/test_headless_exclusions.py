"""Finite launch-boundary HERDR exclusion checks; no workload is spawned."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher
from tests.agents.slo_agent.orchestrator.test_launch_tool import _FakeSpawn, _build_tool
from tests.agents.slo_agent.orchestrator.test_process import _make_process
from tests.agents.slo_agent.orchestrator.test_relaunch import _build_handle


@pytest.mark.parametrize("adoption", [False, True])
async def test_relaunch_excludes_herdr_at_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adoption: bool
) -> None:
    """Check both relaunch APIs at their real spawn call with synthetic parent keys.

    Args:
        tmp_path: Owned capture root.
        monkeypatch: Restores synthetic environment after the test.
        adoption: Select command-owned adoption instead of compatibility invoke.
    """
    excluded = ("HERDR_ENV", "HERDR_PANE_ID", "HERDR_BIN_PATH", "HERDR_SOCKET", "herdrFuture", "HERDR")
    for name in excluded:
        monkeypatch.setenv(name=name, value="synthetic-only")
    monkeypatch.setenv(name="SLO_TEST_TIMEOUT", value="12")
    parent = dict(os.environ)
    spawn = AsyncMock(return_value=SimpleNamespace(pid=4321))
    with patch("src.agents.slo_agent.orchestrator.relaunch.asyncio.create_subprocess_exec", new=spawn):
        if adoption:
            async with WorkflowRelauncher.spawn_for_adoption(handle=_build_handle(), history_root=tmp_path):
                pass
        else:
            outcome = await WorkflowRelauncher.invoke(handle=_build_handle(), history_root=tmp_path)
            assert outcome.pid == 4321
    spawn.assert_awaited_once()
    assert spawn.await_args is not None
    child_env = spawn.await_args.kwargs["env"]
    assert not any(name.upper().startswith("HERDR") for name in child_env)
    assert child_env["SLO_TEST_TIMEOUT"] == "12"
    assert child_env["SLO_WORKFLOW_ID"] == "wf-1"
    assert dict(os.environ) == parent


async def test_subagent_excludes_herdr_at_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the pool child's real run boundary without executing a child.

    Args:
        monkeypatch: Restores synthetic inherited keys after the assertion.
    """
    monkeypatch.setenv(name="HERDR_ENV", value="1")
    monkeypatch.setenv(name="herdrFuture", value="synthetic-only")
    monkeypatch.setenv(name="SLO_TEST_TIMEOUT", value="12")
    parent = dict(os.environ)
    process, _ = _make_process()
    child = MagicMock()
    child.wait = AsyncMock(return_value=0)
    spawn = AsyncMock(return_value=child)
    with (
        patch("src.agents.slo_agent.orchestrator.process.asyncio.create_subprocess_exec", new=spawn),
        patch.object(target=process, attribute="_pump_stdout", new=AsyncMock()),
        patch.object(target=process, attribute="_pump_stderr", new=AsyncMock()),
    ):
        await process.run()
    spawn.assert_awaited_once()
    assert spawn.await_args is not None
    child_env = spawn.await_args.kwargs["env"]
    assert not any(name.upper().startswith("HERDR") for name in child_env)
    assert child_env["SLO_TEST_TIMEOUT"] == "12"
    assert child_env["SLO_PARENT_PID"] == str(os.getpid())
    assert dict(os.environ) == parent


async def test_detached_launch_excludes_herdr_at_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real launch tool with a recording workload spawn.

    Args:
        tmp_path: Owned handle and capture root.
        monkeypatch: Restores synthetic environment after the assertion.
    """
    monkeypatch.setenv(name="HERDR_ENV", value="1")
    monkeypatch.setenv(name="herdrFuture", value="synthetic-only")
    monkeypatch.setenv(name="SLO_TEST_TIMEOUT", value="12")
    parent = dict(os.environ)
    spawn = _FakeSpawn()
    tool = _build_tool(tmp_path=tmp_path, spawn=spawn)
    await tool.ainvoke(input={"brief": "synthetic", "cwd": str(tmp_path)})
    assert spawn.call_count == 1
    child_env = spawn.kwargs["env"]
    assert not any(name.upper().startswith("HERDR") for name in child_env)
    assert child_env["SLO_TEST_TIMEOUT"] == "12"
    assert child_env["SLO_WORKFLOW_ID"].startswith("wf-")
    assert dict(os.environ) == parent
