"""Offline managed-launch composition; never launch native agent workloads."""

from __future__ import annotations

import asyncio
import importlib
import os
import json
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import Result
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.reasoning_capabilities import ReasoningLevel
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowHandleDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_store import CredentialStore
from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType
from pathlib import Path
from typing import AsyncIterator

import pytest

from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.orchestrator.spawn_env import _CapturePipe, open_capture_file_append
from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment


@pytest.fixture
async def managed_launch_root(
    isolated_slo_home: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Path]:
    """Isolate lifecycle identity before creating any owner or capture writer.

    The canonical suite fixture owns imported state roots. This local fixture
    adds only managed-journey policy and always drains the catalog before reset.
    """
    root = isolated_slo_home.resolve(strict=True)
    monkeypatch.delenv(name="SLO_PARENT_PID", raising=False)
    monkeypatch.setenv(name="SLO_PLUGINS_DISABLED", value="1")
    for name in (
        "SLO_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "SLO_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "SLO_KIMI_FOR_CODING_API_KEY",
        "SLO_OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name=name, raising=False)
    monkeypatch.setenv(name="SLO_OPENROUTER_API_KEY", value="synthetic-capture-key")
    workdir = root / "workdir"
    assert workdir.resolve().is_relative_to(root)
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    ModelCatalogService.reset()
    try:
        yield root
    finally:
        await ModelCatalogService.shutdown()
        ModelCatalogService.reset()


async def test_managed_fixture_uses_canonical_roots(managed_launch_root: Path) -> None:
    """All imported history-root consumers agree before owner construction."""
    expected = managed_launch_root / "sessions" / "history"
    for module_name in (
        "src.agents.slo_agent.history.filesystem_store",
        "src.agents.slo_agent.sessions.dao",
        "src.agents.slo_agent.orchestrator.launch_tool",
        "src.agents.slo_agent.orchestrator.notifier",
        "src.cli.headless",
    ):
        module = importlib.import_module(module_name)
        assert module.default_history_root() == expected
    assert "SLO_PARENT_PID" not in os.environ
    assert os.environ["SLO_PLUGINS_DISABLED"] == "1"
    assert Path.cwd() == managed_launch_root / "workdir"
    assert not expected.exists()


async def test_managed_capture_fixture_drains_owned_writers(
    managed_launch_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the finite writer ownership seam before composing an owner graph."""
    guard = CaptureLaunchContainment(root=managed_launch_root, monkeypatch=monkeypatch)
    guard.register_writer_bootstrap()
    endpoints: list[_CapturePipe] = []
    history_root = managed_launch_root / "sessions" / "history"
    try:
        for name in ("stdout.jsonl", "stderr.log"):
            endpoint = await asyncio.to_thread(
                open_capture_file_append,
                history_root=history_root,
                session_id="contained-child",
                name=name,
                credential="synthetic-capture-key",
            )
            assert isinstance(endpoint, _CapturePipe)
            endpoints.append(endpoint)
        for endpoint in endpoints:
            await asyncio.to_thread(endpoint.close)
        assert all(endpoint.closed for endpoint in endpoints)
        for name in ("stdout.jsonl", "stderr.log"):
            path = history_root / "contained-child" / name
            assert path.resolve().is_relative_to(managed_launch_root)
            assert path.read_bytes() == b""
    finally:
        for endpoint in endpoints:
            if not endpoint.closed:
                await asyncio.to_thread(endpoint.close)
            assert await asyncio.to_thread(endpoint._process.wait, timeout=25) == 0
        assert set(guard.writer_pids) == {endpoint._process.pid for endpoint in endpoints}


_ORIGINAL_LAUNCH_BUILD = LaunchWorkflowTool.build


class ManagedJourney:
    """Own recorded workload boundaries; real sessions, stores and writers remain intact."""

    def __init__(self, *, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bind one temporary journey and install only typed external boundaries."""
        self.root = root
        self.pid = os.getpid()
        self.alive = True
        self.argv: list[str] = []
        self.environment: dict[str, str] = {}
        self.endpoints: list[_CapturePipe] = []
        self.factories: list[tuple[str, str, ReasoningLevel | None]] = []
        self.owner_messages: list[AIMessage] = []
        self.child_messages: list[AIMessage] = [AIMessage(content="child complete")]
        self.stores: list[WorkflowHandleStore] = []
        self.guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        self.guard.register_writer_bootstrap()
        original_init = WorkflowHandleStore.__init__

        def initialize(store: WorkflowHandleStore, *, history_root: Path, pid_alive: object = None) -> None:
            """Preserve store class identity and persistence while containing PID probes."""
            assert history_root.resolve().is_relative_to(root)
            original_init(store, history_root=history_root, pid_alive=self.probe)
            self.stores.append(store)

        monkeypatch.setattr(WorkflowHandleStore, "__init__", initialize)
        monkeypatch.setattr("src.agents.slo_agent.graph.service.LLMFactory.create", self.factory)
        for provider in (ProviderName.OPENAI, ProviderName.KIMI_FOR_CODING):
            CredentialStore().persist(
                cred=CredentialDAO(
                    provider=provider, auth_type=AuthType.API_KEY, access_token="synthetic-test-key"
                )
            )

    async def spawn(self, *argv: str, **kwargs: object) -> SimpleNamespace:
        """Record the reserved identity and real endpoints without spawning a workload."""
        assert not self.argv
        self.argv = list(argv)
        for name in ("stdout", "stderr"):
            endpoint = kwargs[name]
            assert isinstance(endpoint, _CapturePipe) and not endpoint.closed
            self.endpoints.append(endpoint)
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        self.environment = dict(environment)
        assert "SLO_PARENT_PID" not in self.environment
        handles = await self.stores[0].list(owner_session_id="managed-owner")
        assert len(handles) == 1 and handles[0].pid == 0
        assert handles[0].orchestrator_session_id == argv[argv.index("--session-id") + 1]
        return SimpleNamespace(pid=self.pid)

    async def close(self) -> None:
        """Close and boundedly join only retained capture writers, including failures."""
        for endpoint in self.endpoints:
            if not endpoint.closed:
                await asyncio.to_thread(endpoint.close)
            assert await asyncio.to_thread(endpoint._process.wait, timeout=25) == 0
        assert set(self.guard.writer_pids) == {endpoint._process.pid for endpoint in self.endpoints}

    def probe(self, pid: int) -> bool:
        """Only the test PID is a permitted positive workload identity."""
        assert pid in (0, self.pid)
        return pid == self.pid and self.alive

    def factory(
        self,
        *,
        model_name: str,
        temperature: float,
        streaming: bool,
        max_retries: int,
        max_tokens: int | None,
        reasoning_level: ReasoningLevel | None,
        session_id: str | None,
        snapshot: ModelCatalogSnapshotDAO | None,
    ) -> LLMBuildResult:
        """Record real lazy graph construction without constructing a network client."""
        assert session_id is not None
        assert session_id == "managed-owner" or session_id == self.argv[self.argv.index("--session-id") + 1]
        self.factories.append((session_id, model_name, reasoning_level))
        messages = self.owner_messages if session_id == "managed-owner" else self.child_messages
        return LLMBuildResult(llm=FauxChatModel(responses=messages), supports_explicit_caching=False)


async def test_managed_typed_factory_preserves_lazy_owner(
    managed_launch_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise real config/readiness/graph construction before adding managed transport."""
    journey = ManagedJourney(root=managed_launch_root, monkeypatch=monkeypatch)
    journey.owner_messages = [AIMessage(content="owner complete")]
    owner = SloAgentSession.build(
        config=SessionConfigDAO(
            session_id="managed-owner",
            workdir=Path.cwd(),
            model_name="gpt-5.4",
            reasoning_level="low",
            enable_history=True,
        )
    )
    OrchestratorSessionBootstrap.attach(session=owner)
    assert journey.factories == []
    try:
        events = [event async for event in owner.invoke(text="characterize lazy owner")]
        assert events[-1].kind == "run_completed"
        assert journey.factories == [(owner.session_id, "gpt-5.4", "low")]
    finally:
        assert owner._sub_agent_pool is not None
        await owner._sub_agent_pool.abort_and_drain()


@pytest.fixture
async def managed_journey(
    managed_launch_root: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ManagedJourney]:
    """Inject recording workload transport through the real bootstrap factory."""
    journey = ManagedJourney(root=managed_launch_root, monkeypatch=monkeypatch)
    original_build = LaunchWorkflowTool.build

    def build(
        *,
        owner_session_id: str,
        default_model: str | None,
        default_reasoning_level: ReasoningLevel | None,
        handle_store: WorkflowHandleStore,
    ) -> BaseTool:
        """Keep bootstrap snapshots and shared store intact while injecting transport."""
        return original_build(
            owner_session_id=owner_session_id,
            default_model=default_model,
            default_reasoning_level=default_reasoning_level,
            handle_store=handle_store,
            spawn=journey.spawn,
        )

    monkeypatch.setattr(LaunchWorkflowTool, "build", build)
    try:
        yield journey
    finally:
        await journey.close()


async def launch_from_owner(journey: ManagedJourney, *, arguments: dict[str, object]) -> SloAgentSession:
    """Complete the real owner's scripted tool turn before any child CLI invocation."""
    journey.owner_messages = [
        AIMessage(
            content="", tool_calls=[{"name": "launch_workflow", "args": arguments, "id": "managed-launch"}]
        ),
        AIMessage(content="owner complete"),
    ]
    owner = SloAgentSession.build(
        config=SessionConfigDAO(
            session_id="managed-owner",
            workdir=Path.cwd(),
            model_name="gpt-5.4",
            reasoning_level="low",
            enable_history=True,
        )
    )
    OrchestratorSessionBootstrap.attach(session=owner)
    try:
        events = [event async for event in owner.invoke(text="launch the bounded workflow")]
        assert events[-1].kind == "run_completed"
        return owner
    finally:
        assert owner._sub_agent_pool is not None
        await owner._sub_agent_pool.abort_and_drain()


async def test_managed_owner_records_reserved_identity_and_capture(managed_journey: ManagedJourney) -> None:
    """Real bootstrap/tool execution reserves before spawn and closes real capture endpoints."""
    owner = await launch_from_owner(
        managed_journey, arguments={"brief": "bounded", "reasoning_level": "high"}
    )
    journey = managed_journey
    assert journey.argv[-2:] == ["--reasoning", "high"]
    handles = await journey.stores[0].list(owner_session_id=owner.session_id)
    assert len(handles) == 1 and handles[0].pid == journey.pid
    assert handles[0].state == "launching"
    assert all(endpoint.closed for endpoint in journey.endpoints)
    assert owner.active_reasoning_level == "low"


async def run_recorded_child(
    journey: ManagedJourney, *, expected_active_reasoning: ReasoningLevel | None = None
) -> "Result":
    """Await one CLI worker with exact recorded argv/env; never overlap stdio mutations."""
    from typer.testing import CliRunner
    from src.cli.app import app
    from src.cli.headless import HeadlessRunner

    from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier

    original_init = HeadlessRunner.__init__
    original_shutdown = HeadlessRunner._shutdown_model_catalog
    runners: list[HeadlessRunner] = []

    def initialize(
        runner: HeadlessRunner,
        *,
        config: SessionConfigDAO,
        orchestrator_mode: bool = False,
        notify_session_id: str | None = None,
        notifier: WorkflowNotifier | None = None,
    ) -> None:
        """Retain the real runner, without substituting session preparation or readiness."""
        original_init(
            runner,
            config=config,
            orchestrator_mode=orchestrator_mode,
            notify_session_id=notify_session_id,
            notifier=notifier,
        )
        runners.append(runner)

    async def shutdown(runner: HeadlessRunner) -> None:
        """Drain retained pools on their owning child loop before catalog shutdown."""
        if runner._session is not None and runner._session._sub_agent_pool is not None:
            await runner._session._sub_agent_pool.abort_and_drain()
        await original_shutdown(runner)

    def invoke() -> Result:
        """Scope env and worker-incompatible signal hooks to this serial CLI call."""
        with (
            patch.dict(os.environ, journey.environment, clear=True),
            patch.object(HeadlessRunner, "_install_sigterm_handler", return_value=None),
            patch.object(HeadlessRunner, "_restore_sigterm_handler", return_value=None),
            patch.object(HeadlessRunner, "__init__", initialize),
            patch.object(HeadlessRunner, "_shutdown_model_catalog", shutdown),
        ):
            result = CliRunner().invoke(app=app, args=journey.argv[3:])
            assert len(runners) == 1
            if expected_active_reasoning is not None:
                assert runners[0]._session is not None
                assert runners[0]._session.active_reasoning_level == expected_active_reasoning
            if runners[0]._session is not None:
                assert runners[0]._session._sub_agent_pool is not None
                assert runners[0]._session._sub_agent_pool._sealed
            return result

    return await asyncio.to_thread(invoke)


async def test_managed_child_cli_completes_registered_lifecycle(managed_journey: ManagedJourney) -> None:
    """Captured high reaches real child lazy factory and registered terminal/inbox state."""
    from src.agents.slo_agent.preferences.service import UserPreferencesStore
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore
    from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

    journey = managed_journey
    UserPreferencesStore.upsert(reasoning_level="low")
    owner = await launch_from_owner(journey, arguments={"brief": "bounded", "reasoning_level": "high"})
    handle = (await journey.stores[0].list(owner_session_id=owner.session_id))[0]
    result = await run_recorded_child(journey)
    assert result.exit_code == 0, (result.output, result.exception)
    assert journey.factories == [
        (owner.session_id, "gpt-5.4", "low"),
        (handle.orchestrator_session_id, "gpt-5.4", "high"),
    ]
    history = journey.root / "sessions/history"
    status = OrchestratorStatusStore.load_status(
        path=history / handle.orchestrator_session_id / "orchestrator.json"
    )
    assert status is not None
    assert (
        status.workflow_id,
        status.orchestrator_session_id,
        status.pid,
        status.state,
        status.exit_code,
    ) == (handle.workflow_id, handle.orchestrator_session_id, journey.pid, "completed", 0)
    messages = await SessionInboxStore(history_root=history).list_pending(session_id=owner.session_id)
    assert [(message.kind, message.delivery_mode) for message in messages] == [
        ("workflow_started", "context_note"),
        ("workflow_completed", "chat_turn"),
    ]
    assert all(message.payload["workflow_id"] == handle.workflow_id for message in messages)
    assert all(
        message.payload["orchestrator_session_id"] == handle.orchestrator_session_id for message in messages
    )
    status_tool = next(tool for tool in owner.orchestration_tools if tool.name == "workflow_status")
    status_result = json.loads(await status_tool.ainvoke({"workflow_id": handle.workflow_id}))
    assert status_result["state"] == "completed"
    assert owner.active_reasoning_level == "low"


async def test_managed_phase_medium_is_independent_of_high_parent(
    managed_journey: ManagedJourney, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real pool/fleet/notifier consumes matching transport result with independent argv."""
    # Patch the pool's consumer binding: timeout tests reload process.py, which
    # replaces its class without replacing the class already imported by the pool.
    from src.agents.slo_agent.orchestrator.pool import SubAgentProcess
    from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore

    journey = managed_journey
    phases: list[SubAgentResultDAO] = []

    async def run(process: SubAgentProcess) -> SubAgentResultDAO:
        """Replace only phase workload transport, retaining real task and argv construction.

        Like production ``run``, the fake publishes its terminal result through the
        canonical registry gateway, so the pool emits the winner without reconciling.
        """
        argv = process._build_argv()
        assert process._task.reasoning_level == "medium"
        assert argv[argv.index("--reasoning") + 1] == "medium"
        assert argv[argv.index("--session-id") + 1] == process._session_id
        result = process._publish_terminal(
            candidate=SubAgentResultDAO(
                task_id=process._task.task_id,
                session_id=process._session_id,
                execution_id=process.execution_id,
                status="completed",
                answer="phase complete",
                exit_code=0,
            ),
            terminal_reason="completed",
            terminated_by="natural",
        )
        phases.append(result)
        return result

    monkeypatch.setattr(SubAgentProcess, "run", run)
    journey.child_messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "spawn_sub_agents",
                    "id": "phase-call",
                    "args": {
                        "mode": "single",
                        "tasks": [
                            {
                                "task_id": "phase-medium",
                                "task_summary": "Exercise child dispatch transport",
                                "prompt": "bounded phase",
                                "model": "gpt-5.4",
                                "reasoning_level": "medium",
                            }
                        ],
                    },
                }
            ],
        ),
        AIMessage(content="child complete"),
    ]
    owner = await launch_from_owner(journey, arguments={"brief": "bounded", "reasoning_level": "high"})
    result = await run_recorded_child(journey)
    assert result.exit_code == 0, (result.output, result.exception)
    assert len(phases) == 1 and phases[0].task_id == "phase-medium"
    assert journey.factories[-1][2] == "high"
    history = journey.root / "sessions/history"
    messages = await SessionInboxStore(history_root=history).list_pending(session_id=owner.session_id)
    lifecycle = [
        (message.kind, message.delivery_mode)
        for message in messages
        if message.kind != "workflow_fleet_update"
    ]
    assert lifecycle == [
        ("workflow_started", "context_note"),
        ("workflow_phase_update", "context_note"),
        ("workflow_completed", "chat_turn"),
    ]
    child_id = journey.factories[-1][0]
    fleet = json.loads((history / child_id / "fleet.json").read_text())
    assert fleet["orchestrator_session_id"] == child_id
    assert fleet["workflow_id"] == journey.environment["SLO_WORKFLOW_ID"]
    assert len(fleet["entries"]) == 1
    entry = fleet["entries"][0]
    assert (entry["session_id"], entry["task_id"], entry["status"], entry["exit_code"]) == (
        phases[0].session_id,
        "phase-medium",
        "completed",
        0,
    )


@pytest.mark.parametrize(
    ("model", "requested", "effective"),
    [
        ("gpt-5.4", "high", "high"),
        ("kimi-k3", "medium", "high"),
        ("kimi-for-coding", "high", "off"),
    ],
)
async def test_managed_child_applies_real_model_clamping(
    managed_journey: ManagedJourney, model: str, requested: str, effective: str
) -> None:
    """Transport preserves canonical request while the actual child resolves its model policy."""
    journey = managed_journey
    await launch_from_owner(
        journey, arguments={"brief": "bounded", "model": model, "reasoning_level": requested}
    )
    assert journey.argv[-2:] == ["--reasoning", requested]
    result = await run_recorded_child(journey)
    assert result.exit_code == 0, (result.output, result.exception)
    assert journey.factories[-1][1:] == (model, effective)


@pytest.mark.parametrize(
    "arguments",
    [
        {"brief": "bounded", "reasoning_level": "HIGH"},
        {"brief": "bounded", "reasoning_level": True},
        {"brief": "bounded", "reasoning": "high"},
    ],
)
async def test_managed_malformed_arguments_have_no_launch_effects(
    managed_journey: ManagedJourney, arguments: dict[str, object]
) -> None:
    """The real graph observes strict schema rejection without registration/capture/spawn."""
    journey = managed_journey
    await launch_from_owner(journey, arguments=arguments)
    assert journey.argv == [] and journey.endpoints == [] and journey.guard.writer_pids == []
    assert await journey.stores[0].list(owner_session_id="managed-owner") == []
    history = journey.root / "sessions/history/managed-owner/events.jsonl"
    assert "invalid launch_workflow arguments" in history.read_text()
    assert journey.factories == [("managed-owner", "gpt-5.4", "low")]


@pytest.mark.parametrize("model", ["unknown-managed-model", "kimi-for-coding"])
async def test_managed_direct_failures_keep_distinct_lifecycle(
    managed_journey: ManagedJourney, model: str
) -> None:
    """Unknown construction has no lifecycle; missing credential fails after started, before factory."""
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore

    journey = managed_journey
    CredentialStore().remove(provider=ProviderName.KIMI_FOR_CODING)
    owner = await launch_from_owner(
        journey, arguments={"brief": "bounded", "model": model, "reasoning_level": "high"}
    )
    handle = (await journey.stores[0].list(owner_session_id=owner.session_id))[0]
    result = await run_recorded_child(
        journey, expected_active_reasoning="off" if model == "kimi-for-coding" else None
    )
    assert result.exit_code == 1
    assert journey.factories == [(owner.session_id, "gpt-5.4", "low")]
    history = journey.root / "sessions/history"
    messages = await SessionInboxStore(history_root=history).list_pending(session_id=owner.session_id)
    status_path = history / handle.orchestrator_session_id / "orchestrator.json"
    if model == "unknown-managed-model":
        assert isinstance(result.exception, ValueError)
        assert str(result.exception) == "Unsupported reasoning model 'unknown-managed-model'."
        assert messages == [] and not status_path.exists()
        output_events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        assert not any(event.get("kind") == "run_failed" for event in output_events)
        journey.alive = False
        reconciled = await journey.stores[0].reconcile(owner_session_id=owner.session_id)
        assert reconciled[0].state == "failed"
    else:
        assert [(message.kind, message.delivery_mode) for message in messages] == [
            ("workflow_started", "context_note"),
            ("workflow_failed", "chat_turn"),
        ]
        output_events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        failed = [event for event in output_events if event.get("kind") == "run_failed"]
        assert len(failed) == 1
        assert failed[0]["content"] == (
            "No Kimi For Coding credentials found. Set SLO_KIMI_FOR_CODING_API_KEY "
            "or store the API key via /auth in the TUI."
        )
        assert json.loads(status_path.read_text())["state"] == "failed"
        events_path = history / handle.orchestrator_session_id / "events.jsonl"
        assert not events_path.exists() or "run_started" not in events_path.read_text()


async def test_managed_abort_targets_registered_identity_only(managed_journey: ManagedJourney) -> None:
    """Supported abort writes durable request before injected signal and deterministic escalation."""
    import signal
    from typing import Callable
    from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowCommandService

    journey = managed_journey
    owner = await launch_from_owner(journey, arguments={"brief": "bounded", "reasoning_level": "high"})
    handle = (await journey.stores[0].list(owner_session_id=owner.session_id))[0]
    request = journey.root / "sessions/history" / handle.orchestrator_session_id / "abort_request.json"
    signals: list[tuple[int, int]] = []
    callbacks: list[Callable[[], None]] = []

    def kill(*, pid: int, signal_number: int) -> None:
        """Record only the registered test PID after durable ordering evidence exists."""
        assert pid == journey.pid and request.exists()
        signals.append((pid, signal_number))

    def schedule(*, delay_seconds: float, callback: Callable[[], None]) -> None:
        """Retain escalation without starting a background timer."""
        assert delay_seconds > 0
        callbacks.append(callback)

    commands = WorkflowCommandService(
        store=journey.stores[0],
        owner_session_id=owner.session_id,
        kill=kill,
        pid_alive=journey.probe,
        schedule=schedule,
    )
    confirmation = await commands.abort(workflow_id=handle.workflow_id)
    assert handle.workflow_id in confirmation
    assert signals == [(journey.pid, signal.SIGTERM)]
    assert (await journey.stores[0].list(owner_session_id=owner.session_id))[0].state == "aborted"
    assert len(callbacks) == 1
    callbacks[0]()
    assert signals[-1] == (journey.pid, signal.SIGKILL)
    journey.alive = False
    callbacks[0]()
    assert len(signals) == 2


async def test_managed_openrouter_preparation_failure_is_child_owned(
    managed_journey: ManagedJourney, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty real metadata responses fail admission before started, phase or child factory."""
    import httpx
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore

    journey = managed_journey
    requests: list[str] = []
    clients: list[httpx.AsyncClient] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve only the two synthetic authenticated metadata endpoints."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer synthetic-capture-key"
        requests.append(request.url.path)
        assert request.url.path in ("/api/v1/key", "/api/v1/models/user")
        return httpx.Response(status_code=200, json={"data": {} if request.url.path.endswith("/key") else []})

    original_ensure = OpenRouterAPIClient._ensure_http_client

    def ensure(client: OpenRouterAPIClient) -> httpx.AsyncClient:
        """Create mock transport on the child loop; production retains client-close ownership."""
        if client._http_client is None:
            client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            clients.append(client._http_client)
        return original_ensure(client)

    monkeypatch.setattr(OpenRouterAPIClient, "_ensure_http_client", ensure)
    owner = await launch_from_owner(
        journey,
        arguments={"brief": "bounded", "model": "openrouter:missing/route", "reasoning_level": "high"},
    )
    assert requests == []
    result = await run_recorded_child(journey)
    assert result.exit_code == 1
    assert requests == ["/api/v1/key", "/api/v1/models/user"]
    assert all(client.is_closed for client in clients)
    assert journey.factories == [(owner.session_id, "gpt-5.4", "low")]
    output_events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    failed = [event for event in output_events if event.get("kind") == "run_failed"]
    assert len(failed) == 1 and failed[0]["metadata"]["failure_scope"] == "model_preparation"
    messages = await SessionInboxStore(history_root=journey.root / "sessions/history").list_pending(
        session_id=owner.session_id
    )
    assert [(message.kind, message.delivery_mode) for message in messages] == [
        ("workflow_failed", "chat_turn")
    ]
    handle = (await journey.stores[0].list(owner_session_id=owner.session_id))[0]
    status = json.loads(
        (journey.root / "sessions/history" / handle.orchestrator_session_id / "orchestrator.json").read_text()
    )
    assert (status["state"], status["exit_code"], status["pid"]) == ("failed", 1, journey.pid)
    assert status["workflow_id"] == handle.workflow_id
    assert messages[0].payload["orchestrator_session_id"] == handle.orchestrator_session_id


@pytest.mark.parametrize(("requested", "effective"), [(None, "low"), ("off", "off"), ("high", "high")])
async def test_managed_snapshot_and_explicit_precedence_over_saved_preference(
    managed_journey: ManagedJourney, requested: str | None, effective: str
) -> None:
    """Omission binds owner low; explicit off/high wins over the child's saved medium."""
    from src.agents.slo_agent.preferences.service import UserPreferencesStore

    journey = managed_journey
    UserPreferencesStore.upsert(reasoning_level="medium")
    arguments: dict[str, object] = {"brief": "bounded"}
    if requested is not None:
        arguments["reasoning_level"] = requested
    await launch_from_owner(journey, arguments=arguments)
    assert journey.argv[-2:] == ["--reasoning", effective]
    result = await run_recorded_child(journey)
    assert result.exit_code == 0, (result.output, result.exception)
    assert journey.factories[-1][2] == effective


@pytest.mark.parametrize(("saved", "effective"), [("medium", "medium"), (None, "high")])
async def test_managed_legacy_no_flag_uses_child_preference_or_seed(
    managed_journey: ManagedJourney, saved: ReasoningLevel | None, effective: str
) -> None:
    """Legacy factory without bound reasoning retains the actual CLI preference/seed contract."""
    from src.agents.slo_agent.preferences.service import UserPreferencesStore

    journey = managed_journey
    if saved is not None:
        UserPreferencesStore.upsert(reasoning_level=saved)
    store = WorkflowHandleStore(history_root=journey.root / "sessions/history")
    # Use the original class implementation, not the fixture's bootstrap injection.
    with patch.object(LaunchWorkflowTool, "build", _ORIGINAL_LAUNCH_BUILD):
        tool = LaunchWorkflowTool.build(
            owner_session_id="managed-owner", default_model="gpt-5.4", handle_store=store, spawn=journey.spawn
        )
    handle = WorkflowHandleDAO.model_validate_json(await tool.ainvoke({"brief": "legacy"}))
    assert "--reasoning" not in journey.argv
    result = await run_recorded_child(journey)
    assert result.exit_code == 0, (result.output, result.exception)
    assert journey.factories == [(handle.orchestrator_session_id, "gpt-5.4", effective)]
