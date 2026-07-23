"""End-to-end routing tests for the sync and headless dynamic workflow paths.

Pins the full mechanical contract of both operator-visible scenarios:

* Scenario 1 — sync dynamic workflow runs in-session via ``spawn_sub_agents``
  and leaves no detached handle files.
* Scenario 2 — headless dynamic workflow detaches exactly once and produces a
  child that is structurally unable to recurse (structural guard), with
  ``launch_workflow`` also refusing on its own (depth guard).

Parent spec: ``56-orchestrator-routing/overview.md`` §8.2.
Sub-spec:    ``56.a.3-end-to-end-routing-tests.md``.
"""

from __future__ import annotations

import contextlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

import pytest

import config.cfg as cfg_module
from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.bundles import create_extended_tools

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def build_plain_session(*, history_root: Path) -> SloAgentSession:
    """Build a minimal session with no orchestration tools attached.

    Uses the config path so ``OrchestratorSessionBootstrap.attach`` can
    operate on it without triggering the pre-built-agent no-op guard.

    Args:
        history_root (Path): Pytest ``tmp_path`` used as the persisted-
            history root.  History is disabled so nothing is written to
            disk, but the path is threaded through config for seam
            consistency.

    Returns:
        SloAgentSession: A fresh session not yet promoted to orchestrator mode.
    """
    return SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=history_root,
            model_name="claude-sonnet-4-6",
            enable_history=False,
            history_root=history_root,
        )
    )


def build_orchestrator_session(
    *,
    history_root: Path,
    responses: list,
    pool_process_stub: Optional[Any] = None,
    launch_spawn: Optional[Callable] = None,
) -> SloAgentSession:
    """Build a session promoted to orchestrator mode with a scripted LLM.

    Builds a ``SloAgentSession`` via the config path (so bootstrap can
    operate), calls ``OrchestratorSessionBootstrap.attach`` with monkeypatched
    ``default_history_root`` (→ ``history_root``) and an injected
    ``LaunchWorkflowTool.build`` wrapper (→ ``launch_spawn``), then patches
    ``session._build_agent`` to return a ``FauxChatModel``-based ``SloAgent``
    with the orchestration tools baked in.

    Two OS-boundary stubs are installed for the session's lifetime:

    * ``SubAgentProcess.run`` is replaced with ``pool_process_stub`` so no
      real child process is spawned.
    * ``LaunchWorkflowTool.build`` is wrapped so the tool receives
      ``spawn=launch_spawn`` and ``history_root=history_root``, so no real
      detached process is spawned.

    Both stubs are stopped automatically at the end of ``_final_answer``.

    Args:
        history_root (Path): Pytest ``tmp_path`` — both the session history
            root and the workflow handle store root.
        responses (list): Scripted ``AIMessage`` queue for ``FauxChatModel``.
        pool_process_stub (Optional[Any]): Callable that replaces
            ``SubAgentProcess.run``.  ``None`` skips the patch (used for
            headless scenarios where ``spawn_sub_agents`` is never called).
        launch_spawn (Optional[Callable]): Async callable replacing the real
            ``asyncio.create_subprocess_exec`` inside ``launch_workflow``.
            ``None`` skips injection.

    Returns:
        SloAgentSession: A promoted, ready-to-invoke orchestrator session.
    """
    session: SloAgentSession = build_plain_session(history_root=history_root)
    faux: FauxChatModel = FauxChatModel(responses=responses)

    # ---- Install patchers that must survive the whole test lifecycle --------
    _patchers: list = []

    # 1. Enable DETACHED_WORKFLOWS so bootstrap attaches launch/status tools.
    _patchers.append(
        patch.object(cfg_module, "DETACHED_WORKFLOWS", True)
    )

    # 2. Redirect default_history_root → history_root so handle files land in
    #    tmp_path, never in ~/.slo.  The function is a lazy import inside
    #    ``_build_workflow_tools``; patch the source module so every import
    #    picks up the redirected value.
    _patchers.append(
        patch(
            "src.agents.slo_agent.history.filesystem_store.default_history_root",
            return_value=history_root,
        )
    )

    # 3. Wrap LaunchWorkflowTool.build to inject the recording spawn and the
    #    test-scoped history_root.
    original_build = LaunchWorkflowTool.build

    def _injected_build(
        *,
        owner_session_id: str,
        default_model: Optional[str],
        handle_store: Any = None,
        spawn: Optional[Any] = None,
        history_root: Optional[Path] = None,
        **kw: Any,
    ) -> Any:
        """Wrap ``LaunchWorkflowTool.build`` injecting test spawn and root."""
        return original_build(
            owner_session_id=owner_session_id,
            default_model=default_model,
            spawn=launch_spawn or spawn,
            history_root=history_root or _injected_build._history_root,  # type: ignore[attr-defined]
        )

    _injected_build._history_root = history_root  # type: ignore[attr-defined]

    _patchers.append(
        patch.object(LaunchWorkflowTool, "build", side_effect=_injected_build)
    )

    # 4. Patch SubAgentProcess.run if a stub was supplied (Scenario 1).
    if pool_process_stub is not None:
        _patchers.append(
            patch(
                "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
                new=pool_process_stub,
            )
        )

    # Start every patcher and store the stop callbacks on the session.
    for p in _patchers:
        p.start()
    session._test_patchers = _patchers  # type: ignore[attr-defined]

    # ---- Promote to orchestrator mode via the real bootstrap ----------------
    OrchestratorSessionBootstrap.attach(session=session)

    # ---- Patch _build_agent to inject our FauxChatModel with baked tools ---
    # We must defer this until after bootstrap because bootstrap mutates
    # _config.extra_tools; the patch captures the post-bootstrap state.
    _extra_tools = list(session._config.extra_tools or [])
    _all_tools = create_extended_tools() + _extra_tools

    def _patched_build_agent() -> SloAgent:
        """Build a FauxChatModel-backed SloAgent with the orchestrator tools.

        Returns:
            SloAgent: Agent wired to the scripted ``FauxChatModel`` queue.
        """
        return SloAgent(
            llm=faux,
            cwd=str(session._workdir),
            tools=_all_tools,
            system_prompt=session._config.system_prompt,
            append_system_prompt=session._config.append_system_prompt,
        )

    session._build_agent = _patched_build_agent  # type: ignore[method-assign]

    return session


async def _final_answer(*, session: SloAgentSession, text: str) -> str:
    """Drive one turn of ``session.invoke`` and return the assembled answer.

    Drains the async generator yielded by ``SloAgentSession.invoke`` and
    returns the content of the terminal ``run_completed`` event.  Stops all
    test-lifecycle patchers installed by ``build_orchestrator_session`` after
    the invoke completes.

    Args:
        session (SloAgentSession): The orchestrator session under test.
        text (str): Operator prompt text for this submission.

    Returns:
        str: Final assistant text from the ``run_completed`` event, or empty
            when the run completed without explicit content.
    """
    final: str = ""
    async for event in session.invoke(text=text):
        if event.kind == "run_completed":
            final = event.content or ""

    # Stop all patchers installed during session construction.
    for patcher in getattr(session, "_test_patchers", []):
        try:
            patcher.stop()
        except RuntimeError:
            pass  # already stopped

    return final


def _completed_child(*, answer: str) -> Any:
    """Return an async callable that stubs ``SubAgentProcess.run``.

    The returned callable receives ``self`` (the ``SubAgentProcess`` instance)
    and returns a completed ``SubAgentResultDAO`` carrying ``answer``.  No
    real subprocess is created.

    Args:
        answer (str): The synthesized answer the stub child returns.

    Returns:
        Any: Async callable with the same signature as ``SubAgentProcess.run``.
    """

    async def _run(self_proc: Any) -> SubAgentResultDAO:
        """Return a completed result DAO for the given process's task.

        Args:
            self_proc (Any): The ``SubAgentProcess`` instance being stubbed.

        Returns:
            SubAgentResultDAO: Completed terminal result carrying ``answer``.
        """
        return SubAgentResultDAO(
            task_id=self_proc._task.task_id,
            session_id=self_proc._session_id,
            status="completed",
            answer=answer,
            exit_code=0,
        )

    return _run


class _StubProcess:
    """Minimal spawned-process stand-in with a fixed pid.

    Satisfies the ``_ProcessLike`` protocol used by ``LaunchWorkflowTool``
    to read the pid after the spawn completes.
    """

    def __init__(self, *, pid: int) -> None:
        """Bind the stub to a fixed pid.

        Args:
            pid (int): Pid reported to the tool after spawn.
        """
        self.pid: int = pid


def _recording_spawn(*, into: dict, pid: int) -> Callable:
    """Return an async spawn stub that records its arguments.

    The stub records ``argv``, ``env``, and ``start_new_session`` into
    ``into`` and returns a ``_StubProcess`` with the given ``pid``.  No
    real process is created.

    Args:
        into (dict): Mutable dict that receives the recorded call arguments.
        pid (int): Pid the stub process reports.

    Returns:
        Callable: Async callable matching ``SpawnCallable``.
    """

    async def _spawn(*argv: str, **kwargs: Any) -> _StubProcess:
        """Record spawn arguments and return a stub process.

        Args:
            *argv (str): Full child argument vector.
            **kwargs (Any): Spawn keyword arguments (env, start_new_session, …).

        Returns:
            _StubProcess: Stub with the configured pid.
        """
        into["argv"] = list(argv)
        into["kwargs"] = kwargs
        into["env"] = kwargs.get("env", {})
        return _StubProcess(pid=pid)

    return _spawn


@contextmanager
def monkeypatched_env(**env_vars: str):
    """Context manager that temporarily sets environment variables.

    Restores the original values (or removes the variables) when the
    context exits.

    Args:
        **env_vars (str): Environment variables to set for the duration
            of the context.

    Yields:
        None: Control returns to the caller inside the patched environment.
    """
    originals: dict[str, Optional[str]] = {
        key: os.environ.get(key) for key in env_vars
    }
    for key, value in env_vars.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, original in originals.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


# ---------------------------------------------------------------------------
# End-to-end scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_dynamic_workflow_executes_in_session(tmp_path: Path) -> None:
    """A "dynamic workflows" turn runs via spawn_sub_agents inside the session.

    End-to-end contract for the sync route: the scripted model answers the
    operator's unqualified "dynamic workflows" prompt with one
    spawn_sub_agents call; the pool executes it (stubbed child process); the
    synthesis returns in the same turn; and no workflow handle, orchestrator
    capture file, or detached process is ever created.
    """
    spawn_calls: list[tuple] = []
    session: SloAgentSession = build_orchestrator_session(   # promoted with headless=False
        history_root=tmp_path,
        responses=[
            FauxChatModel.assistant_message(
                content="",
                tool_calls=[FauxChatModel.tool_call_dict(
                    name="spawn_sub_agents",
                    args={"mode": "single",
                          "tasks_json": '[{"task_id": "phase-1", "prompt": "explain HEAD"}]'},
                )],
            ),
            FauxChatModel.assistant_message(content="WORKFLOW COMPLETE. Phase summary: done."),
        ],
        pool_process_stub=_completed_child(answer="phase-1 done"),   # no real subprocess
        launch_spawn=lambda *a, **kw: spawn_calls.append((a, kw)),   # would record any detach
    )

    answer: str = await _final_answer(
        session=session,
        text="Use dynamic workflows to run the explain-how-it-works flow on this repo.",
    )

    assert "WORKFLOW COMPLETE" in answer                              # synthesis in the same turn
    assert spawn_calls == []                                          # launch_workflow never fired
    assert list(tmp_path.glob("*/workflows/wf-*.json")) == []         # no detached handle anywhere
    tool_names: list[str] = [t.name for t in session.orchestration_tools]
    assert tool_names == ["spawn_sub_agents", "launch_workflow", "workflow_status"]


@pytest.mark.asyncio
async def test_headless_dynamic_workflow_detaches_without_blocking(tmp_path: Path) -> None:
    """A "headless dynamic workflows" turn detaches once and returns immediately.

    End-to-end contract for the detached route: the scripted model answers
    the detach-qualified prompt with one launch_workflow call; the tool
    writes a launching handle, spawns the detached argv (stubbed, pid 4242),
    patches the pid, and the turn completes while the "process" is still
    running. The detached argv must promote a headless orchestrator that is
    structurally unable to recurse: --orchestrator and --notify-session are
    present, its env carries SLO_WORKFLOW_ID, and re-promoting a session
    from that argv yields a bundle without launch_workflow.
    """
    recorded: dict = {}
    session: SloAgentSession = build_orchestrator_session(
        history_root=tmp_path,
        responses=[
            FauxChatModel.assistant_message(
                content="",
                tool_calls=[FauxChatModel.tool_call_dict(
                    name="launch_workflow",
                    args={"brief": "Run explain-how-it-works on /repo; write EXPLAINED.md",
                          "cwd": "/repo"},
                )],
            ),
            FauxChatModel.assistant_message(content="Headless orchestrator launched."),
        ],
        launch_spawn=_recording_spawn(into=recorded, pid=4242),      # never creates a process
    )

    answer: str = await _final_answer(
        session=session,
        text="Use headless dynamic workflows to document the last commit.",
    )

    assert "Headless orchestrator launched" in answer                # turn ended immediately
    handles: list[Path] = list(tmp_path.glob("*/workflows/wf-*.json"))
    assert len(handles) == 1                                         # exactly one detachment
    handle: dict = json.loads(handles[0].read_text())
    assert handle["pid"] == 4242
    argv: list[str] = recorded["argv"]
    assert "--orchestrator" in argv and "--notify-session" in argv   # inbox completion path wired
    assert recorded["env"]["SLO_WORKFLOW_ID"] == handle["workflow_id"]

    # The detached child is structurally recursion-free: promote a session the
    # way HeadlessRunner does for that argv and inspect its bundle.
    child_session: SloAgentSession = build_plain_session(history_root=tmp_path)
    OrchestratorSessionBootstrap.attach(session=child_session, headless=True)
    child_tools: list[str] = [t.name for t in child_session.orchestration_tools]
    assert child_tools == ["spawn_sub_agents"]

    # And the depth guard holds even if the tool were re-exposed:
    launch_workflow_tool = LaunchWorkflowTool.build(
        owner_session_id=session.session_id,
        default_model=None,
        history_root=tmp_path,
        spawn=_recording_spawn(into={}, pid=9999),
    )
    with monkeypatched_env(SLO_WORKFLOW_ID=handle["workflow_id"]):
        refusal: str = await launch_workflow_tool.ainvoke({"brief": "recurse"})
    assert "refusing to launch" in json.loads(refusal)["error"]
