"""Active-session channel acceptance through actual scheduler, mounted TUI and local SDK (108.6).

No headless child, capture writer, fleet or notifier is exercised here. Synthetic
HTTP-400 bodies test adapter normalization, not arbitrary old-key text sanitation.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscriptComponent
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from collections.abc import Iterator
from textual.pilot import Pilot
from uuid import UUID
from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.auth.credential_dao import AuthType, ProviderName
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

import httpx
import pytest
from langchain_core.tools import tool

from src.agents.base import LLMFactory
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import CredentialDAO, CredentialSource, ResolvedCredentialDAO
from src.auth.credential_resolver import CredentialResolver
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.fresh_run import FreshRunInvoker, SubprocessFreshRunLauncher
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.tick_app_service import ScheduleTickAppService
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.channel_delivery import ScheduleChannelSender
from src.tui.app import SloTUI


@pytest.fixture
def contained_writes(tmp_path: Path) -> Iterator[list[Path]]:
    """Reject filesystem mutation outside this test's resolved root before I/O.

    The audit hook remains installed but becomes inert after fixture teardown.
    This is scoped to the in-process scheduled-delivery test; it is not a subprocess sandbox.
    """
    root = tmp_path.resolve()
    active = True
    writes: list[Path] = []

    def audit(event: str, args: tuple[object, ...]) -> None:
        """Check actual write targets, including symlink and descriptor resolution."""
        if not active:
            return
        targets: tuple[object, ...] = ()
        if event == "open" and isinstance(args[2], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                targets = args[:1]
        if event in {"os.mkdir", "os.chmod", "os.remove", "os.rmdir"}:
            targets = args[:1]
        if event == "os.rename":
            targets = args[:2]
        for target in targets:
            path = Path(f"/proc/self/fd/{target}") if isinstance(target, int) else Path(str(target))
            resolved = path.resolve()
            assert resolved.is_relative_to(root), f"write outside owned root: {resolved}"
            writes.append(resolved)
        assert event not in {"subprocess.Popen", "os.system", "socket.connect"}, event

    # A module first imported inside the guarded window would otherwise have the
    # import system cache its bytecode under src/, which the guard rightly rejects.
    # That write belongs to Python, not to the code under test, so disable it here.
    writes_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    try:
        yield writes
    finally:
        active = False
        sys.dont_write_bytecode = writes_bytecode


@tool
def scheduled_acceptance_echo() -> str:
    """Return the deterministic tool output used by the local SDK fixture."""
    return "scheduled acceptance tool output"


async def _wait_for_scheduled_turn(
    *, app: SloTUI, pilot: Pilot[None], gateway: ChannelGateway, message_id: object
) -> ChannelMessageDAO:
    """Wait until the session's poller has taken the scheduled row and its run has ended.

    Args:
        app (SloTUI): The mounted app whose session poller runs the row.
        pilot (Pilot[None]): Textual pilot driving the app's event loop.
        gateway (ChannelGateway): A gateway on the shared queue, for read-back.
        message_id (object): The scheduled row's id (the run record's ``run_id``).

    Returns:
        ChannelMessageDAO: The accepted scheduled row.
    """
    for _ in range(600):
        await pilot.pause(delay=0.05)
        row = await gateway.find_message(message_id=UUID(str(message_id)))
        poller = app._session.channel_poller
        if row is not None and row.accepted_at is not None and poller is not None and not poller.busy:
            if not app._session.is_running:
                return row
    raise AssertionError("mounted scheduled channel turn did not finish")


class RecordingInvocationQueue:
    """Test double recording tick enqueue calls; the deliver loop drains them."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[UUID, UUID]] = []

    async def enqueue_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Record one enqueue call."""
        self.calls.append((invocation_id, schedule_id))


@pytest.mark.parametrize("gateway_failure", [False, True])
@pytest.mark.parametrize("model_cwd", [False, True])
async def test_active_schedule_channel_prompt_drives_mounted_prepared_openrouter_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    gateway_failure: bool,
    model_cwd: bool,
    contained_writes: list[Path],
) -> None:
    """Queue via the active scheduler path, then consume it through the mounted session's poller."""
    root = tmp_path.resolve()
    history_root = root / "history"
    schedules_root = root / "schedules"
    route = "openrouter:vendor/scheduled-mounted"
    key_a = "F86_DELIVERABLE2_KEY_A"
    key_b = "F86_DELIVERABLE2_KEY_B"
    private_reasoning = "F86_DELIVERABLE2_PRIVATE_REASONING"
    raw_sentinel = "F86_DELIVERABLE2_RAW_BODY"
    request_bodies: list[dict[str, object]] = []
    wire_keys: list[str] = []
    stream_events: list[AgentStreamEventDAO] = []
    raw_errors: list[str] = []
    history_store = FilesystemSessionHistoryStore(root=history_root)
    leases = SessionOwnershipLeaseStore(history_root=history_root)
    channels_db: Path = root / "channels" / "channels.db"

    for target in (history_root, schedules_root):
        assert target.resolve().is_relative_to(root)
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(schedules_root))
    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    monkeypatch.setattr("src.agents.model_catalog.store._CFG_SLO_HOME", root)
    monkeypatch.setattr("src.agents.model_catalog.store._cfg", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.agents.slo_agent.preferences.service._CFG_SLO_HOME", root)
    monkeypatch.setattr("src.agents.slo_agent.preferences.service._cfg", lambda *args, **kwargs: None)

    def responder(request: httpx.Request) -> httpx.Response:
        """Serve discovery and the two real SDK turns through only MockTransport."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer " + key_a
        if request.method == "GET" and request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        if request.method == "GET" and request.url.path == "/api/v1/models/user":
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/scheduled-mounted",
                            "name": "Scheduled Mounted",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        }
                    ]
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chat/completions"
        body = json.loads(request.content)
        request_bodies.append(body)
        wire_keys.append(request.headers["authorization"])
        if len(request_bodies) == 1:
            effective[0] = ResolvedCredentialDAO(
                credential=CredentialDAO(
                    provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=key_b
                ),
                source=CredentialSource.ENVIRONMENT,
            )
        assert body["model"] == "vendor/scheduled-mounted"
        if gateway_failure and len(request_bodies) == 2:
            raw_errors.append(f"{key_a} {key_b} {raw_sentinel}")
            return httpx.Response(status_code=400, json={"error": {"message": raw_errors[-1]}})
        if len(request_bodies) == 1:
            delta: dict[str, object] = {
                "role": "assistant",
                "reasoning_details": [{"type": "encrypted", "data": private_reasoning}],
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-scheduled",
                        "type": "function",
                        "function": {"name": "scheduled_acceptance_echo", "arguments": "{}"},
                    }
                ],
            }
            finish_reason: str | None = None
        else:
            delta = {"role": "assistant", "content": "scheduled mounted answer"}
            finish_reason = "stop"
        chunk = {
            "id": "scheduled-mounted",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/scheduled-mounted",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    resolved_credential = ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=key_a
        ),
        source=CredentialSource.ENVIRONMENT,
    )
    effective = [resolved_credential]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http_client:
        original_builder = LLMFactory._build_openrouter

        def catalog_client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject the local transport into the existing catalog client owner."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        def build_with_transport(
            *, model_name: str, resolved: dict[str, object], entry: ModelCatalogEntryDAO
        ) -> OpenRouterChatOpenAI:
            """Inject the local SDK transport without replacing factory behavior."""
            resolved["http_async_client"] = http_client
            return original_builder(model_name=model_name, resolved=resolved, entry=entry)

        with (
            patch.object(
                CredentialResolver, "resolve_with_source", side_effect=lambda **kwargs: effective[0]
            ),
            patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=catalog_client),
            patch.object(LLMFactory, "_build_openrouter", side_effect=build_with_transport),
            patch.object(
                httpx.AsyncHTTPTransport,
                "handle_async_request",
                side_effect=AssertionError("network forbidden"),
            ),
            patch.object(
                httpx.HTTPTransport, "handle_request", side_effect=AssertionError("network forbidden")
            ),
        ):
            ModelCatalogService.reset()
            try:
                await ModelCatalogService.refresh(provider=resolved_credential.credential.provider)
                await history_store.ensure_session(
                    session_id="scheduled-target", workdir=root, model_name=route
                )
                session = await SloAgentSession.prepare(
                    config=SessionConfigDAO(
                        workdir=root,
                        model_name=route,
                        session_id="scheduled-target",
                        history_root=history_root,
                        enable_history=True,
                        extra_tools=[scheduled_acceptance_echo],
                        system_prompt="Use scheduled_acceptance_echo before answering.",
                    )
                )

                async def collect(event: AgentStreamEventDAO) -> None:
                    """Observe actual public session events without replacing TUI delivery."""
                    stream_events.append(event)

                session.subscribe(handler=collect)
                original_route = session.active_model_name
                app = SloTUI(
                    session=session,
                    lease_store=leases,
                    channel_gateway=ChannelGateway(repository=ChannelRepository(db_path=channels_db)),
                )
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    assert await leases.is_active(session_id="scheduled-target")
                    schedules_db = ScheduleDatabase(db_path=schedules_root / "schedules.db")
                    schedules_service = ScheduleService(
                        database=schedules_db,
                        schedules=ScheduleRepository(),
                        invocations=ScheduleInvocationRepository(),
                        session_history=history_store,
                    )
                    schedule_fields: dict[str, object] = {}
                    if model_cwd:
                        # D9: the schedule's model and cwd must never touch the
                        # open session's route; they belong to fresh runs only.
                        schedule_fields = {
                            "model": "openrouter:vendor/schedule-only",
                            "cwd": str(root),
                        }
                    created = await schedules_service.create(
                        new_schedule=NewScheduleDAO(
                            name="Scheduled mounted acceptance",
                            prompt="scheduled mounted prompt",
                            trigger=OneShotTriggerDAO(
                                run_at=datetime.now(tz=timezone.utc) + timedelta(seconds=60)
                            ),
                            session_mode="continuous",
                            session_reference="scheduled-target",
                            **schedule_fields,  # type: ignore[arg-type]
                        ),
                        now=datetime.now(tz=timezone.utc),
                    )
                    assert created.session_reference == "scheduled-target"
                    if model_cwd:
                        assert created.model == "openrouter:vendor/schedule-only"
                        assert created.cwd == str(root)
                    # The scheduler is another process in production: it reaches the
                    # same channels.db through its own gateway connection.
                    scheduler_gateway = ChannelGateway(repository=ChannelRepository(db_path=channels_db))
                    await scheduler_gateway.open()
                    sender = ScheduleChannelSender(gateway=scheduler_gateway)
                    reconciler = InvocationOutcomeReconciler(
                        database=schedules_db,
                        gateway=scheduler_gateway,
                        invocations=ScheduleInvocationRepository(),
                    )
                    queue = RecordingInvocationQueue()
                    tick = ScheduleTickAppService(
                        database=schedules_db,
                        schedules=ScheduleRepository(),
                        schedule_service=schedules_service,
                        invocations=ScheduleInvocationRepository(),
                        queue=queue,
                        reconciler=reconciler,
                    )
                    deliver = DeliverScheduleInvocationAppService(
                        database=schedules_db,
                        schedules=schedules_service,
                        invocations=ScheduleInvocationRepository(),
                        sender=sender,
                        fresh_runs=FreshRunInvoker(launcher=SubprocessFreshRunLauncher()),
                        now_provider=lambda: datetime.now(tz=timezone.utc),
                    )
                    try:
                        now = datetime.now(tz=timezone.utc)
                        await schedules_service.trigger_now(reference=str(created.id), now=now)
                        await tick.invoke(now=now, batch_limit=50)
                        delivered: ScheduleInvocationDAO | None = None
                        for invocation, _schedule_id in queue.calls:
                            delivered = await deliver.invoke(invocation_id=invocation, now=now)
                        assert delivered is not None
                        assert delivered.status == "delivered"
                        assert delivered.channel_message_id == delivered.id
                        assert not (history_root / "scheduled-target" / "inbox").exists()
                        accepted = await _wait_for_scheduled_turn(
                            app=app,
                            pilot=pilot,
                            gateway=scheduler_gateway,
                            message_id=str(delivered.id),
                        )
                    finally:
                        await scheduler_gateway.close()
                        await schedules_db.close()
                    assert accepted.message_type == "prompt"
                    assert accepted.message_contents == "scheduled mounted prompt"
                    assert accepted.sender_name == "scheduler Scheduled mounted acceptance"
                    # The schedule's own model route never replaces the open session's route
                    # (A17; and with model/cwd set on the schedule, the D9 assertion, LEG-A7).
                    assert session.active_model_name == original_route == route
                    transcript = app.query_one(ChatTranscriptComponent).logical_copy_text()
                    if gateway_failure:
                        assert "scheduled mounted answer" not in transcript
                    else:
                        assert "scheduled mounted answer" in transcript
                    assert "scheduled acceptance tool output" in transcript
                    assert private_reasoning not in transcript
                    if gateway_failure:
                        assert "OpenRouter request failed" in transcript
                    assert effective[0].credential.access_token == key_b
                    await history_store.rebuild_transcript(session_id="scheduled-target", markdown=transcript)
            finally:
                ModelCatalogService.reset()

    assert effective[0].credential.access_token == key_b
    assert wire_keys == ["Bearer " + key_a] * 2
    if gateway_failure:
        assert raw_errors == [f"{key_a} {key_b} {raw_sentinel}"]
    assert len(request_bodies) == 2
    continuation_messages = request_bodies[1]["messages"]
    assert isinstance(continuation_messages, list)
    anchor = next(message for message in continuation_messages if message["role"] == "assistant")
    assert anchor["reasoning_details"] == [{"type": "encrypted", "data": private_reasoning}]
    tool_result = next(message for message in continuation_messages if message["role"] == "tool")
    assert tool_result["tool_call_id"] == "call-scheduled"
    assert tool_result["content"] == "scheduled acceptance tool output"
    events_path = history_root / "scheduled-target" / "events.jsonl"
    assert events_path.resolve().is_relative_to(root) and events_path.exists()
    history_text = events_path.read_text(encoding="utf-8")
    assert ("run_failed" if gateway_failure else "run_completed") in history_text
    rows = [json.loads(line) for line in history_text.splitlines()]
    extensions = [
        row["payload"]["provider_message_extension"]
        for row in rows
        if row["payload"].get("provider_message_extension")
    ]
    assert len(extensions) == 1
    assert extensions[0]["source_model_name"] == route
    assert extensions[0]["reasoning_details"] == [{"type": "encrypted", "data": private_reasoning}]
    expected = {
        history_root / "scheduled-target/session.json": route,
        history_root / "scheduled-target/transcript.md": "scheduled acceptance tool output",
        root / "global/model_catalog_cache.v2.json": "vendor/scheduled-mounted",
    }
    for path, ordinary in expected.items():
        assert path.resolve().is_relative_to(root)
        assert path.is_file() and ordinary in path.read_text(encoding="utf-8")
    assert any("HTTP/1.1 400" in record.message for record in caplog.records) == gateway_failure
    assert contained_writes
    assert all(path.is_relative_to(root) for path in contained_writes)
    assert stream_events
    assert any(event.kind == "tool_result" for event in stream_events)
    public = caplog.text + transcript + "".join(event.model_dump_json() for event in stream_events)
    assert private_reasoning not in public
    for path in root.rglob("*"):
        assert path.resolve().is_relative_to(root)
        if not path.is_file():
            continue
        data = path.read_bytes()
        # Binary files (SQLite queues, WAL files, locks) can't be decoded as
        # UTF-8; scan their raw bytes so the containment assertions still hold.
        assert raw_sentinel.encode() not in data
        if path.name != "events.jsonl":
            assert private_reasoning.encode() not in data
        if path.name.startswith("channels.db"):
            continue
        try:
            public += data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    assert key_a not in public and key_b not in public and raw_sentinel not in public
