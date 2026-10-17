"""Tests for ``LaunchWorkflowTool`` (spec 57.a.2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional, get_args, cast
from unittest.mock import AsyncMock, patch
from pydantic import BaseModel, ValidationError
from langchain_core.tools import BaseTool

from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from src.agents.reasoning_capabilities import ReasoningLevel

import pytest

import config.cfg as cfg_module
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool, _build_argv
from src.agents.slo_agent.orchestrator.spawn_env import build_headless_child_env, open_capture_file_append
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowStatusTool,
)

_OWNER_SESSION_ID: str = "tui-session-1"


@pytest.fixture(autouse=True)
def _clear_enclosing_workflow_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate normal detached-launch tests from an enclosing workflow process.

    The production depth guard must reject recursive detached launches when
    ``SLO_WORKFLOW_ID`` is set. This test module verifies both that guard and
    the normal launch path, so each test begins without an inherited workflow
    id; depth-guard tests explicitly set one when exercising the refusal.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest environment patch helper.
    """
    monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)


class _StubProcess:
    """Minimal spawned-process stand-in with a fixed pid."""

    def __init__(self, *, pid: int = 4242) -> None:
        """Bind the stub to its pid.

        Args:
            pid (int, optional): Reported process id. Defaults to ``4242``.
        """
        self.pid: int = pid


class _FakeSpawn:
    """Recording spawn callable returning a stub process."""

    def __init__(self, *, pid: int = 4242, error: Optional[OSError] = None) -> None:
        """Configure the fake.

        Args:
            pid (int, optional): Pid for the stub process. Defaults to ``4242``.
            error (Optional[OSError]): When set, raise instead of spawning.
        """
        self.pid: int = pid
        self.error: Optional[OSError] = error
        self.argv: Optional[tuple[str, ...]] = None
        self.kwargs: dict[str, Any] = {}
        self.call_count: int = 0

    async def __call__(self, *argv: str, **kwargs: Any) -> _StubProcess:
        """Record the spawn request and return a stub process.

        Args:
            *argv (str): Full child argv.
            **kwargs (Any): Spawn keyword arguments.

        Returns:
            _StubProcess: Stub process with the configured pid.
        """
        self.call_count += 1
        self.argv = argv
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _StubProcess(pid=self.pid)


def _build_store(*, tmp_path: Path, pid_alive: bool = True) -> WorkflowHandleStore:
    """Build a handle store rooted under ``tmp_path``.

    Args:
        tmp_path (Path): Pytest tmp path.
        pid_alive (bool, optional): Fixed liveness result. Defaults to ``True``.

    Returns:
        WorkflowHandleStore: Test-scoped handle store.
    """
    return WorkflowHandleStore(
        history_root=tmp_path / "history",
        pid_alive=lambda pid: pid_alive,
    )


def _build_tool(
    *,
    tmp_path: Path,
    spawn: _FakeSpawn,
    store: Optional[WorkflowHandleStore] = None,
    default_model: Optional[str] = None,
    default_reasoning_level: Optional[ReasoningLevel] = None,
) -> BaseTool:
    """Build a ``launch_workflow`` tool wired to a tmp store and fake spawn.

    Args:
        tmp_path (Path): Pytest tmp path.
        spawn (_FakeSpawn): Recording spawn callable.
        store (Optional[WorkflowHandleStore]): Store override.
        default_model (Optional[str]): Session default model.
        default_reasoning_level (Optional[ReasoningLevel]): Bound reasoning snapshot.

    Returns:
        BaseTool: Bound ``launch_workflow`` tool.
    """
    return LaunchWorkflowTool.build(
        owner_session_id=_OWNER_SESSION_ID,
        default_model=default_model,
        default_reasoning_level=default_reasoning_level,
        handle_store=store or _build_store(tmp_path=tmp_path),
        spawn=spawn,
        history_root=tmp_path / "history",
    )


_VALIDATION_ERROR = {
    "error": "invalid launch_workflow arguments; use brief, cwd, model and canonical reasoning_level"
}


class TestReasoningTransport:
    """Canonical requests travel unchanged; defaults never acquire call-local state."""

    @pytest.mark.parametrize("level", get_args(ReasoningLevel))
    async def test_launch_passes_each_explicit_reasoning_level(
        self, tmp_path: Path, level: ReasoningLevel
    ) -> None:
        """Explicit off and all other canonical tokens win over the bound high default."""
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn, default_reasoning_level="high")
        result = await launch.ainvoke({"brief": "bounded", "reasoning_level": level})
        handle = WorkflowHandleDAO.model_validate_json(result)
        assert spawn.call_count == 1
        assert spawn.argv is not None
        assert spawn.argv.count("--reasoning") == 1
        assert spawn.argv[spawn.argv.index("--reasoning") + 1] == level
        assert spawn.argv[spawn.argv.index("--session-id") + 1] == handle.orchestrator_session_id
        assert spawn.argv[spawn.argv.index("-p") + 1] == "bounded"

    @pytest.mark.parametrize("arguments", [{}, {"reasoning_level": None}])
    async def test_launch_inherits_default_when_omitted_or_null(
        self, tmp_path: Path, arguments: dict[str, object]
    ) -> None:
        """Both absent and null inherit medium, rather than bypassing the snapshot."""
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn, default_reasoning_level="medium")
        payload: dict[str, object] = {"brief": "bounded", **arguments}
        await launch.ainvoke(payload)
        assert spawn.argv is not None
        assert spawn.argv.count("--reasoning") == 1
        assert spawn.argv is not None
        assert spawn.argv[-2:] == ("--reasoning", "medium")

    @pytest.mark.parametrize("arguments", [{}, {"reasoning_level": None}])
    @pytest.mark.parametrize("defaults", [{}, {"default_reasoning_level": None}])
    async def test_launch_omits_reasoning_without_factory_default(
        self, tmp_path: Path, arguments: dict[str, object], defaults: dict[str, None]
    ) -> None:
        """Both legacy factory forms retain the child preference/seed path."""
        spawn = _FakeSpawn()
        launch = LaunchWorkflowTool.build(
            owner_session_id=_OWNER_SESSION_ID,
            default_model="gpt-5.4",
            spawn=spawn,
            history_root=tmp_path,
            handle_store=_build_store(tmp_path=tmp_path),
            **defaults,
        )
        payload: dict[str, object] = {"brief": "bounded", "cwd": str(tmp_path), "model": "", **arguments}
        await launch.ainvoke(payload)
        assert spawn.argv is not None
        assert "--reasoning" not in spawn.argv
        assert spawn.argv is not None
        assert spawn.argv[-2:] == ("--model", "gpt-5.4")

    async def test_explicit_override_does_not_mutate_default(self, tmp_path: Path) -> None:
        """A subsequent omitted invocation still uses the construction snapshot."""
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn, default_reasoning_level="medium")
        first = json.loads(await launch.ainvoke({"brief": "first", "reasoning_level": "high"}))
        assert spawn.argv is not None
        assert spawn.argv[-2:] == ("--reasoning", "high")
        second = json.loads(await launch.ainvoke({"brief": "second"}))
        assert spawn.argv is not None
        assert spawn.argv[-2:] == ("--reasoning", "medium")
        assert first["workflow_id"] != second["workflow_id"]
        assert spawn.call_count == 2


class TestReasoningDefaults:
    """Validate immutable construction defaults before resolving dependencies."""

    @pytest.mark.parametrize("invalid", ["HIGH", " high ", "", True, 1, 1.5, [], {}])
    def test_invalid_bound_default_fails_before_tool_publication(self, invalid: object) -> None:
        """Programmer errors fail before even resolving the history-root dependency."""
        with (
            patch("src.agents.slo_agent.orchestrator.launch_tool.default_history_root") as root,
            patch("src.agents.slo_agent.orchestrator.launch_tool.WorkflowHandleStore") as store,
        ):
            with pytest.raises(ValidationError):
                LaunchWorkflowTool.build(
                    owner_session_id="owner",
                    default_model=None,
                    default_reasoning_level=cast(ReasoningLevel, invalid),
                )
        root.assert_not_called()
        store.assert_not_called()

    @pytest.mark.parametrize("level", [None, *get_args(ReasoningLevel)])
    def test_canonical_bound_defaults_publish(self, tmp_path: Path, level: Optional[ReasoningLevel]) -> None:
        """Every canonical default and legacy None publishes a real tool."""
        assert (
            _build_tool(tmp_path=tmp_path, spawn=_FakeSpawn(), default_reasoning_level=level).name
            == "launch_workflow"
        )


class TestReasoningSchema:
    """Separate runtime rejection from provider-visible field projection."""

    def test_schema_exposes_canonical_optional_reasoning(self, tmp_path: Path) -> None:
        """The runtime schema advertises nullable canonical input and forbids extras."""
        launch = _build_tool(tmp_path=tmp_path, spawn=_FakeSpawn())
        assert isinstance(launch.args_schema, type) and issubclass(launch.args_schema, BaseModel)
        schema = launch.args_schema.model_json_schema()
        field = schema["properties"]["reasoning_level"]
        assert field["anyOf"] == [
            {"enum": list(get_args(ReasoningLevel)), "type": "string"},
            {"type": "null"},
        ]
        assert field["default"] is None
        assert "reasoning_level" not in schema["required"]
        assert "reasoning" not in schema["properties"]
        assert schema["additionalProperties"] is False

    def test_provider_projection_exposes_optional_canonical_reasoning(self, tmp_path: Path) -> None:
        """The actual provider converter retains the field, not necessarily extra policy."""
        launch = _build_tool(tmp_path=tmp_path, spawn=_FakeSpawn())
        schema = convert_to_openai_tool(launch)["function"]["parameters"]
        field = schema["properties"]["reasoning_level"]
        assert field["anyOf"] == [
            {"enum": list(get_args(ReasoningLevel)), "type": "string"},
            {"type": "null"},
        ]
        assert field["default"] is None
        assert "reasoning_level" not in schema["required"]
        assert "reasoning" not in schema["properties"]

    @pytest.mark.parametrize("invalid", ["", " ", "HIGH", " high ", "bogus", True, 1, 1.5, [], {}])
    async def test_invalid_reasoning_has_no_launch_side_effects(
        self, tmp_path: Path, invalid: object
    ) -> None:
        """Reject malformed inputs before reconciliation, registration, captures or spawn."""
        store = _build_store(tmp_path=tmp_path)
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)
        with (
            patch.object(store, "reconcile", new_callable=AsyncMock) as reconcile,
            patch.object(store, "write", new_callable=AsyncMock) as write,
            patch("src.agents.slo_agent.orchestrator.launch_tool.open_capture_file_append") as capture,
        ):
            result = await launch.ainvoke({"brief": "bounded", "reasoning_level": invalid})
        assert json.loads(result) == _VALIDATION_ERROR
        reconcile.assert_not_called()
        write.assert_not_called()
        capture.assert_not_called()
        assert spawn.call_count == 0
        assert not (tmp_path / "history").exists()

    @pytest.mark.parametrize(
        "extras",
        [
            {"reasoning": "high"},
            {"reasoning": "high", "reasoning_level": "low"},
            {"other": "secret-sentinel"},
        ],
    )
    async def test_unknown_launch_key_is_rejected(self, tmp_path: Path, extras: dict[str, str]) -> None:
        """Unknown keys cannot silently launch with unintended settings."""
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn)
        with patch.object(LaunchWorkflowTool, "_cap_refusal", new_callable=AsyncMock) as cap:
            payload: dict[str, object] = {"brief": "bounded", **extras}
            result = await launch.ainvoke(payload)
        assert json.loads(result) == _VALIDATION_ERROR
        cap.assert_not_called()
        assert spawn.call_count == 0
        assert not (tmp_path / "history").exists()

    async def test_reasoning_validation_toolcall_envelope(self, tmp_path: Path) -> None:
        """LangChain preserves call identity/error status without reflecting invalid input."""
        spawn = _FakeSpawn()
        launch = _build_tool(tmp_path=tmp_path, spawn=spawn)
        result = await launch.ainvoke(
            {
                "type": "tool_call",
                "name": "launch_workflow",
                "id": "invalid-95",
                "args": {"brief": "b", "reasoning_level": "private-sentinel"},
            }
        )
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "invalid-95"
        assert result.status == "error"
        assert isinstance(result.content, str)
        assert json.loads(result.content) == _VALIDATION_ERROR
        assert spawn.call_count == 0
        assert not (tmp_path / "history").exists()


class TestBuildArgv:
    """The detached orchestrator argv contract."""

    def test_argv_contains_required_flags(self) -> None:
        """All mandatory flags and their values are present in order-safe pairs."""
        argv: list[str] = _build_argv(
            brief="run the workflow",
            orchestrator_session_id="orch-1",
            owner_session_id="tui-1",
            model=None,
            cwd="/repo",
        )

        assert argv[:4] == [sys.executable, "-m", "src.cli", "run"]
        assert "-I" not in argv
        assert "--orchestrator" in argv
        assert "--json" in argv
        assert "--enable-history" in argv
        assert argv[argv.index("-p") + 1] == "run the workflow"
        assert argv[argv.index("--session-id") + 1] == "orch-1"
        assert argv[argv.index("--notify-session") + 1] == "tui-1"
        assert argv[argv.index("--cwd") + 1] == "/repo"

    def test_argv_includes_model_when_set(self) -> None:
        """A model override appends ``--model <name>``."""
        argv: list[str] = _build_argv(
            brief="b",
            orchestrator_session_id="orch-1",
            owner_session_id="tui-1",
            model="claude-sonnet-4-6",
            cwd="/repo",
        )

        assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"

    def test_argv_omits_model_when_none(self) -> None:
        """No model override means no ``--model`` flag."""
        argv: list[str] = _build_argv(
            brief="b",
            orchestrator_session_id="orch-1",
            owner_session_id="tui-1",
            model=None,
            cwd="/repo",
        )

        assert "--model" not in argv


class TestAllowlistedEnv:
    """The non-secret ``SLO_*`` env allowlist."""

    def test_env_forwards_slo_vars_and_exact_names(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-secret ``SLO_*`` vars and exact allowlist names are forwarded."""
        monkeypatch.setenv("SLO_HOME", "/tmp/slo-home")
        monkeypatch.setenv("SLO_DEFAULT_MODEL_NAME", "claude-sonnet-4-6")
        monkeypatch.setenv("PATH", "/usr/bin")

        env: dict[str, str] = build_headless_child_env(workflow_id="wf-3f2a")

        assert env["SLO_HOME"] == "/tmp/slo-home"
        assert env["SLO_DEFAULT_MODEL_NAME"] == "claude-sonnet-4-6"
        assert env["PATH"] == "/usr/bin"

    @pytest.mark.parametrize(
        "secret_name",
        [
            "SLO_ANTHROPIC_API_KEY",
            "SLO_OPENAI_API_KEY",
            "SLO_DEPLOY_TOKEN",
            "SLO_DB_SECRET",
            "SLO_SMTP_PASSWORD",
        ],
    )
    def test_env_strips_secret_marked_vars(
        self,
        monkeypatch: pytest.MonkeyPatch,
        secret_name: str,
    ) -> None:
        """Secret-marked ``SLO_*`` names never reach the child env."""
        monkeypatch.setenv(secret_name, "super-secret")

        env: dict[str, str] = build_headless_child_env(workflow_id="wf-3f2a")

        assert secret_name not in env

    def test_env_strips_foreign_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-``SLO_`` vars outside the exact allowlist are dropped."""
        monkeypatch.setenv("AWS_PROFILE", "prod")
        monkeypatch.setenv("MY_RANDOM_VAR", "x")

        env: dict[str, str] = build_headless_child_env(workflow_id="wf-3f2a")

        assert "AWS_PROFILE" not in env
        assert "MY_RANDOM_VAR" not in env

    def test_env_injects_workflow_id(self) -> None:
        """``SLO_WORKFLOW_ID`` is always set for the notifier (57.a.3)."""
        env: dict[str, str] = build_headless_child_env(workflow_id="wf-3f2a")

        assert env["SLO_WORKFLOW_ID"] == "wf-3f2a"


class TestLaunchWorkflowHappyPath:
    """Detached launch: handle write, spawn kwargs, pid patch, result JSON."""

    async def test_result_json_parses_to_handle(self, tmp_path: Path) -> None:
        """The tool result round-trips through ``WorkflowHandleDAO``."""
        spawn: _FakeSpawn = _FakeSpawn(pid=5150)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow", "cwd": "/repo"})
        handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(result)

        assert handle.workflow_id.startswith("wf-")
        assert handle.owner_session_id == _OWNER_SESSION_ID
        assert handle.pid == 5150
        assert handle.state == "launching"
        assert handle.brief == "run the workflow"
        assert handle.cwd == "/repo"

    async def test_launch_warns_when_owner_session_has_no_history(self, tmp_path: Path) -> None:
        """A successful launch discloses when owner monitoring cannot be backed."""
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})

        assert "warning" in json.loads(result)
        assert "history" in json.loads(result)["warning"]

    async def test_launch_omits_warning_with_history_backing(self, tmp_path: Path) -> None:
        """A history-backed owner receives a normal handle response without warning."""
        history_root: Path = tmp_path / "history"
        (history_root / _OWNER_SESSION_ID).mkdir(parents=True)
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})

        assert "warning" not in json.loads(result)

    async def test_spawn_uses_start_new_session_true(self, tmp_path: Path) -> None:
        """The child is detached into its own process group."""
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        await launch_tool.ainvoke({"brief": "run the workflow"})

        assert spawn.kwargs["start_new_session"] is True

    async def test_spawn_argv_matches_handle_identity(self, tmp_path: Path) -> None:
        """The spawned argv carries the same ids the handle records."""
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow", "cwd": "/repo"})
        handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(result)

        assert spawn.argv is not None
        argv: list[str] = list(spawn.argv)
        assert argv[argv.index("--session-id") + 1] == handle.orchestrator_session_id
        assert argv[argv.index("--notify-session") + 1] == _OWNER_SESSION_ID
        assert spawn.kwargs["env"]["SLO_WORKFLOW_ID"] == handle.workflow_id

    async def test_spawn_env_is_allowlisted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The spawn env never contains secret-marked variables."""
        monkeypatch.setenv("SLO_ANTHROPIC_API_KEY", "sk-secret")
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        await launch_tool.ainvoke({"brief": "run the workflow"})

        assert "SLO_ANTHROPIC_API_KEY" not in spawn.kwargs["env"]

    async def test_model_falls_back_to_session_default(self, tmp_path: Path) -> None:
        """No per-call model → the session default flows into argv."""
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, default_model="claude-sonnet-4-6")

        await launch_tool.ainvoke({"brief": "run the workflow"})

        assert spawn.argv is not None
        argv: list[str] = list(spawn.argv)
        assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"

    async def test_handle_written_with_launching_before_spawn(self, tmp_path: Path) -> None:
        """The handle file exists (state launching) before the spawn call runs."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        observed_states: list[str] = []

        class _SpyingSpawn(_FakeSpawn):
            async def __call__(self, *argv: str, **kwargs: Any) -> _StubProcess:
                session_id: str = argv[list(argv).index("--session-id") + 1]
                handles: list[WorkflowHandleDAO] = await store.list(
                    owner_session_id=_OWNER_SESSION_ID,
                )
                observed_states.extend(
                    handle.state for handle in handles if handle.orchestrator_session_id == session_id
                )
                return await super().__call__(*argv, **kwargs)

        launch_tool = _build_tool(tmp_path=tmp_path, spawn=_SpyingSpawn(), store=store)

        await launch_tool.ainvoke({"brief": "run the workflow"})

        assert observed_states == ["launching"]

    async def test_handle_pid_patched_after_spawn(self, tmp_path: Path) -> None:
        """The on-disk handle carries the spawned pid."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=_FakeSpawn(pid=6001), store=store)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(result)
        loaded: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id=handle.workflow_id,
        )

        assert loaded is not None
        assert loaded.pid == 6001

    async def test_capture_files_created_under_orchestrator_session(self, tmp_path: Path) -> None:
        """stdout/stderr capture files land under the orchestrator's history dir."""
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(result)
        capture_dir: Path = tmp_path / "history" / handle.orchestrator_session_id

        assert (capture_dir / "stdout.jsonl").exists()
        assert (capture_dir / "stderr.log").exists()


class TestLaunchWorkflowDepthGuard:
    """Depth guard: ``SLO_WORKFLOW_ID`` prevents recursive detachment."""

    async def test_depth_guard_refuses_inside_workflow(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With ``SLO_WORKFLOW_ID`` set the tool returns a refusal error JSON.

        The depth guard must fire as the first check in the tool body: the
        spawn callable must never be invoked, no handle file must be written
        under the store, and the returned JSON must contain the enclosing
        workflow id so the caller can trace the recursion attempt.
        """
        monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-outer")
        spawn: _FakeSpawn = _FakeSpawn()
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)

        result: str = await launch_tool.ainvoke({"brief": "recurse into the void"})
        parsed: dict = json.loads(result)

        assert "error" in parsed
        assert "wf-outer" in parsed["error"]
        assert spawn.call_count == 0
        handles: list[WorkflowHandleDAO] = await store.list(
            owner_session_id=_OWNER_SESSION_ID,
        )
        assert handles == []

    async def test_depth_guard_inactive_outside_workflow(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without ``SLO_WORKFLOW_ID`` the depth guard is inactive and launch proceeds.

        Confirms the guard does not interfere with the normal TUI-originating
        launch path: when the env var is absent the tool runs its full happy
        path and returns a valid workflow handle JSON.
        """
        monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)
        spawn: _FakeSpawn = _FakeSpawn(pid=9001)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(result)

        assert handle.workflow_id.startswith("wf-")
        assert handle.pid == 9001
        assert spawn.call_count == 1


class TestLaunchWorkflowGuards:
    """Cap, blank-brief, and spawn-failure branches — all JSON, never raised."""

    async def test_blank_brief_returns_error_no_spawn(self, tmp_path: Path) -> None:
        """A blank brief is refused before any handle write or spawn."""
        spawn: _FakeSpawn = _FakeSpawn()
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)

        result: str = await launch_tool.ainvoke({"brief": "   "})

        assert "error" in json.loads(result)
        assert spawn.call_count == 0
        assert await store.list(owner_session_id=_OWNER_SESSION_ID) == []

    async def test_cap_reached_returns_refusal_no_spawn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """At the live-workflow cap the tool refuses and spawns nothing."""
        monkeypatch.setattr(cfg_module, "MAX_DETACHED_WORKFLOWS", 1)
        spawn: _FakeSpawn = _FakeSpawn()
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        await store.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-live",
                owner_session_id=_OWNER_SESSION_ID,
                orchestrator_session_id="orch-live",
                pid=999,
                brief="already running",
                cwd="/repo",
                state="running",
            )
        )
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)

        result: str = await launch_tool.ainvoke({"brief": "one more"})
        parsed: dict = json.loads(result)

        assert "workflow cap reached" in parsed["error"]
        assert spawn.call_count == 0

    async def test_cap_ignores_terminal_and_stalled_handles(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Terminal handles do not count against the cap (dead running reconciles to stalled)."""
        monkeypatch.setattr(cfg_module, "MAX_DETACHED_WORKFLOWS", 1)
        spawn: _FakeSpawn = _FakeSpawn()
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await store.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-dead",
                owner_session_id=_OWNER_SESSION_ID,
                orchestrator_session_id="orch-dead",
                pid=999,
                brief="died earlier",
                cwd="/repo",
                state="running",
            )
        )
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)

        result: str = await launch_tool.ainvoke({"brief": "fresh workflow"})

        assert "error" not in json.loads(result)
        assert spawn.call_count == 1

    async def test_spawn_oserror_marks_failed_and_returns_error(self, tmp_path: Path) -> None:
        """A spawn OSError marks the handle failed and returns an error JSON."""
        spawn: _FakeSpawn = _FakeSpawn(error=OSError("exec format error"))
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store)

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        parsed: dict = json.loads(result)
        handles: list[WorkflowHandleDAO] = await store.list(owner_session_id=_OWNER_SESSION_ID)

        assert "workflow launch failed" in parsed["error"]
        assert len(handles) == 1
        assert handles[0].state == "failed"


class TestLaunchToStatusRoundTrip:
    """Integration: launch tool → handle store → workflow_status tool."""

    async def test_workflow_status_sees_launched_handle(self, tmp_path: Path) -> None:
        """A launched workflow is immediately visible through ``workflow_status``."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=_FakeSpawn(pid=7777), store=store)
        status_tool = WorkflowStatusTool.build(owner_session_id=_OWNER_SESSION_ID, store=store)

        launch_result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        launched: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(launch_result)
        status_result: str = await status_tool.ainvoke({"workflow_id": launched.workflow_id})
        status: dict = json.loads(status_result)

        assert status["workflow_id"] == launched.workflow_id
        assert status["orchestrator_session_id"] == launched.orchestrator_session_id
        assert status["pid"] == 7777
        assert status["state"] == "launching"


class TestLaunchNeverRaisesIntoGraph:
    """Every launch failure returns an error JSON string — never an exception."""

    async def test_capture_file_error_returns_error_json_and_marks_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unwritable capture path fails the launch as error JSON, no spawn."""

        def _unwritable(
            *,
            history_root: Path,
            session_id: str,
            name: str,
            credential: str = "",
            completion_context: object = None,
        ) -> None:
            del completion_context
            raise OSError("read-only history root")

        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.launch_tool.open_capture_file_append",
            _unwritable,
        )
        spawn: _FakeSpawn = _FakeSpawn()
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store, default_reasoning_level="high")

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        parsed: dict = json.loads(result)

        assert "workflow launch failed" in parsed["error"]
        assert spawn.call_count == 0
        handles = await store.list(owner_session_id=_OWNER_SESSION_ID)
        assert [handle.state for handle in handles] == ["failed"]

    async def test_pid_patch_conflict_returns_error_json_not_raise(self, tmp_path: Path) -> None:
        """A handle state flipped mid-spawn yields error JSON, not a raise.

        Simulates a reconcile pass reaping the handle while the spawn await is
        in flight — the post-spawn pid-patch write then conflicts with the
        changed state and must surface as an error string.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        class _StateFlippingSpawn(_FakeSpawn):
            """Spawn stub that flips the handle state before returning."""

            async def __call__(self, *argv: str, **kwargs: Any) -> _StubProcess:
                """Flip the freshly written handle to ``failed`` mid-spawn."""
                handles = await store.list(owner_session_id=_OWNER_SESSION_ID)
                await store.update_state(
                    owner_session_id=_OWNER_SESSION_ID,
                    workflow_id=handles[0].workflow_id,
                    state="failed",
                )
                return await super().__call__(*argv, **kwargs)

        launch_tool = _build_tool(
            tmp_path=tmp_path,
            spawn=_StateFlippingSpawn(pid=6001),
            store=store,
            default_reasoning_level="high",
        )

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        parsed: dict = json.loads(result)

        assert "handle update failed" in parsed["error"]
        assert "6001" in parsed["error"]

    async def test_mark_failed_error_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second failure while recording the first never raises."""
        spawn: _FakeSpawn = _FakeSpawn(error=OSError("exec format error"))
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        async def _broken_update_state(**kwargs: Any) -> None:
            raise RuntimeError("store exploded")

        monkeypatch.setattr(store, "update_state", _broken_update_state)
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, store=store, default_reasoning_level="high")

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})
        parsed: dict = json.loads(result)

        assert "workflow launch failed" in parsed["error"]

    async def test_stdout_capture_closed_when_stderr_open_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stdout handle is not leaked when the stderr open raises."""
        opened: list[Any] = []
        real_open = __import__(
            "src.agents.slo_agent.orchestrator.launch_tool",
            fromlist=["open_capture_file_append"],
        ).open_capture_file_append

        def _stderr_fails(
            *,
            history_root: Path,
            session_id: str,
            name: str,
            credential: str = "",
            completion_context: object = None,
        ) -> Any:
            if name == "stderr.log":
                raise OSError("disk full")
            handle = real_open(
                history_root=history_root,
                session_id=session_id,
                name=name,
                credential=credential,
                completion_context=completion_context,
            )
            opened.append(handle)
            return handle

        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.launch_tool.open_capture_file_append",
            _stderr_fails,
        )
        spawn: _FakeSpawn = _FakeSpawn()
        launch_tool = _build_tool(tmp_path=tmp_path, spawn=spawn, default_reasoning_level="high")

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})

        assert "workflow launch failed" in json.loads(result)["error"]
        assert spawn.call_count == 0
        assert len(opened) == 1
        assert opened[0].closed is True

    async def test_abort_mid_spawn_reaps_fresh_process_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator abort landing mid-spawn SIGTERMs the fresh process group.

        The handle went terminal ``aborted`` while the spawn await was in
        flight, so /workflows will never reconcile it again — the tool must
        honour the recorded abort by terminating the orphan it just created.
        """
        import os as os_module
        import signal as signal_module

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(
            os_module,
            "killpg",
            lambda pid, sig: killed.append((pid, sig)),
        )

        class _AbortingSpawn(_FakeSpawn):
            """Spawn stub simulating /workflows abort during the spawn window."""

            async def __call__(self, *argv: str, **kwargs: Any) -> _StubProcess:
                """Abort the freshly written launching handle mid-spawn."""
                handles = await store.list(owner_session_id=_OWNER_SESSION_ID)
                await store.update_state(
                    owner_session_id=_OWNER_SESSION_ID,
                    workflow_id=handles[0].workflow_id,
                    state="aborted",
                )
                return await super().__call__(*argv, **kwargs)

        launch_tool = _build_tool(
            tmp_path=tmp_path,
            spawn=_AbortingSpawn(pid=6002),
            store=store,
            default_reasoning_level="high",
        )

        result: str = await launch_tool.ainvoke({"brief": "run the workflow"})

        assert "handle update failed" in json.loads(result)["error"]
        assert killed == [(6002, signal_module.SIGTERM)]
