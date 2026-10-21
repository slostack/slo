"""Mounted offline Herdr journeys; real owners with only external boundaries controlled."""

import asyncio
import difflib
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.message_extension import ProviderMessageExtensionDAO
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease, HerdrSequenceStore
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from src.agents.slo_agent.herdr.dao import (
    HerdrPublicationDAO,
    HerdrCliCommandDAO,
    HerdrCommandAdmission,
    HerdrCommandResultDAO,
    HerdrVisualizerRequestDAO,
    VisualizerLaunchOutcomeDAO,
)
from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.now import NowTool
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from textual.pilot import Pilot

from src.tui.app import SloTUI
from src.tui.visualizer_launcher import VisualizerLauncher
from tests.state_isolation import FakeHerdrFixture
from tests.integration.herdr_transport_observer import ObservedAdmission, TransportObservation
from tests.integration.herdr_parity_124 import (
    IntegrationWriteAttempts,
    ReportingCredentialBlockers,
    SemanticTrace,
)
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory


async def test_reporting_blockers_retain_swallowed_async_lookup() -> None:
    """The external oracle detects even a caught lookup from a separate task."""
    blockers = ReportingCredentialBlockers()

    async def isolated_callback() -> None:
        """Model optional callback exception containment, not reporting behavior."""
        try:
            CredentialResolver.require(provider=ProviderName.OPENAI)
        except AssertionError:
            pass

    with ExitStack() as stack:
        blockers.install(stack=stack)
        await asyncio.create_task(coro=isolated_callback())
    with pytest.raises(AssertionError):
        blockers.assert_unused()
    assert blockers.calls["CredentialResolver.require"].call_count == 1


@pytest.mark.parametrize(
    "field",
    [
        "session_id",
        "event_id",
        "turn_id",
        "block_id",
        "parent_turn_id",
        "entry_id",
        "parent_entry_id",
        "recorded_at",
    ],
)
@pytest.mark.parametrize("channel", ["tool_input", "metadata"])
def test_parity_normalizer_preserves_user_owned_identity_named_fields(field: str, channel: str) -> None:
    """Identity-looking keys inside user payloads are semantics, not generated IDs."""
    before = AgentStreamEventDAO.model_validate(
        {"kind": "tool_call_end", channel: {field: "original-user-value"}}
    )
    after = AgentStreamEventDAO.model_validate(
        {"kind": "tool_call_end", channel: {field: "changed-user-value"}}
    )
    assert SemanticTrace().serialize(records=[before]) != SemanticTrace().serialize(records=[after])


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "run_failed"},
        {"iteration": 2},
        {"content_index": 1},
        {"content": "changed"},
        {"delta": "changed"},
        {"tool_name": "edit"},
        {"tool_call_id": "other-call"},
        {"tool_input": {"count": 2}},
        {"tool_arguments_delta": "changed"},
        {"redacted": True},
        {"metadata": {"duration": 2}},
        {"sub_agent_id": "other-child"},
        {"task_id": "other-task"},
    ],
)
def test_parity_normalizer_detects_stream_semantics(change: dict[str, object]) -> None:
    """Every nonidentity stream field participates in the parity comparison."""
    before = AgentStreamEventDAO(kind="tool_result", content="original")
    after = before.model_copy(update=change)
    assert SemanticTrace().serialize(records=[before]) != SemanticTrace().serialize(records=[after])


@pytest.mark.parametrize(
    "change", [{"sequence": 2}, {"iteration": 2}, {"kind": "run_failed"}, {"schema_version": 2}]
)
def test_parity_normalizer_detects_history_envelope_semantics(change: dict[str, object]) -> None:
    """Sequence, iteration, kind and schema are not unrelated wall-clock noise."""
    before = SessionHistoryEventDAO(session_id="session", kind="tool_result")
    assert SemanticTrace().serialize(records=[before]) != SemanticTrace().serialize(
        records=[before.model_copy(update=change)]
    )


@pytest.mark.parametrize(
    "mutation", ["parent", "order", "missing", "duplicate", "null", "usage", "timestamp"]
)
def test_parity_normalizer_preserves_history_topology_and_payload(mutation: str) -> None:
    """Consistent renaming passes, but changed links, records and payloads cannot."""
    before = [
        SessionHistoryEventDAO(
            session_id="session",
            event_id=f"event-{index}",
            turn_id="turn",
            kind="tool_result",
            payload=SessionHistoryEventPayloadDAO(
                content=str(index),
                token_usage=index,
                metadata={
                    "entry_id": f"entry-{index}",
                    "parent_entry_id": "entry-0" if index else None,
                    "tool_timestamp": "original",
                },
            ),
        )
        for index in range(2)
    ]
    after = [event.model_copy(deep=True) for event in before]
    if mutation == "parent":
        after[1].payload.metadata["parent_entry_id"] = "entry-1"
    elif mutation == "order":
        after.reverse()
    elif mutation == "missing":
        after.pop()
    elif mutation == "duplicate":
        after.append(after[-1])
    elif mutation == "null":
        after[0].payload.content = None
    elif mutation == "usage":
        after[0].payload.token_usage = 100
    else:
        after[0].payload.metadata["tool_timestamp"] = "changed"
    assert SemanticTrace().serialize(records=list(before)) != SemanticTrace().serialize(records=list(after))


@pytest.mark.parametrize(
    "field",
    sorted(set(SessionHistoryEventPayloadDAO.model_fields) - {"block_id"}),
)
def test_parity_normalizer_retains_every_history_payload_field(field: str) -> None:
    """No reviewed payload field may disappear from the semantic oracle."""
    values: dict[str, object] = {
        "tool_calls": [{"id": "semantic-call", "name": "now", "args": {}}],
        "tool_input": {"session_id": "semantic-user-id"},
        "metadata": {"recorded_at": "semantic-user-time"},
        "redacted": True,
        "token_usage": 17,
        "provider_message_extension": None,
    }
    if field == "provider_message_extension":
        value: object = ProviderMessageExtensionDAO(
            provider=ProviderName.OPENROUTER,
            source_model_name="openrouter:semantic-model",
            reasoning_details=[{"private": "semantic-change"}],
        )
    else:
        value = values.get(field, "semantic-change")
    before = SessionHistoryEventDAO(session_id="session", kind="tool_result")
    after = before.model_copy(deep=True)
    after.payload = before.payload.model_copy(update={field: value})
    assert SemanticTrace().serialize(records=[before]) != SemanticTrace().serialize(records=[after])


def test_parity_normalizer_accepts_consistent_generated_identity_renaming() -> None:
    """Renaming identities preserves cross-record links and null topology."""

    def records(prefix: str) -> list[SessionHistoryEventDAO]:
        """Build equivalent two-node histories with distinct generated names."""
        return [
            SessionHistoryEventDAO(
                session_id=f"{prefix}-session",
                event_id=f"{prefix}-event-{index}",
                turn_id=f"{prefix}-turn",
                kind="tool_result",
                sequence=index,
                payload=SessionHistoryEventPayloadDAO(
                    content="unchanged",
                    block_id=f"{prefix}-block",
                    metadata={
                        "entry_id": f"{prefix}-entry-{index}",
                        "parent_entry_id": f"{prefix}-entry-0" if index else None,
                    },
                ),
            )
            for index in range(2)
        ]

    before, after = records("before"), records("after")
    assert SemanticTrace().serialize(records=list(before)) == SemanticTrace().serialize(records=list(after))
    assert before[1].payload.metadata["parent_entry_id"] == "before-entry-0"


@pytest.mark.parametrize("mode", ["enabled", "disabled", "outside"])
@pytest.mark.parametrize("route", ["single", "retry", "fallback"])
async def test_prompt_tool_usage_completes_while_report_cli_is_stalled(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    route: str,
    parity_records: list[tuple[list[object], list[object]]] | None = None,
    mounted_continuation: Callable[[SloTUI, Pilot[None]], Awaitable[None]] | None = None,
) -> None:
    """Pilot submission traverses the real graph, accounting, persistence and reporter."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            "import time\n"
            f"barrier = Path({str(fake_herdr.barrier)!r})\n"
            "assert not barrier.is_symlink() and barrier.resolve().parent == root.resolve()\n"
            "while sys.argv[2] == 'report-agent' and barrier.read_text() == 'hold': time.sleep(.01)\n"
        )
    if mode == "disabled":
        monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    if mode == "outside":
        monkeypatch.delenv(name="HERDR_ENV")
    native_factory.return_value = LLMBuildResult(
        llm=FauxChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "now", "args": {}, "id": "journey-clock"}],
                    usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                ),
                AIMessage(
                    content="journey complete",
                    usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
                ),
            ]
        ),
        supports_explicit_caching=False,
    )
    pool = None
    if route == "fallback":
        pool = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name=name, provider=ProviderName.OPENAI, priority=index)
                for index, name in enumerate(("gpt-5.4", "gpt-4.1"))
            ]
        )
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", model_pool_dao=pool)
    )
    original_stream = FauxChatModel._astream
    attempts = 0

    async def provider_stream(
        model: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Inject only a pre-output provider failure; real pool/retry policy handles it."""
        nonlocal attempts
        attempts += 1
        if route != "single" and attempts == 1:
            raise RuntimeError("429 rate limit retry after 1 seconds")
        async for chunk in original_stream(
            model, messages=messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    events: list[AgentStreamEventDAO] = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Record the same actual stream consumed by the mounted app."""
        events.append(event)

    async def clock() -> str:
        """Hold a harmless default tool without replacing its graph executor."""
        entered.set()
        await release.wait()
        return "2026-10-19T00:00:00+00:00"

    session.subscribe(handler=observe)
    app = SloTUI(session=session)
    with (
        patch.object(NowTool, "invoke", side_effect=clock),
        patch.object(FauxChatModel, "_astream", new=provider_stream),
        patch.object(
            CredentialResolver,
            "resolve",
            return_value=CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-journey-key"
            ),
        ),
    ):
        async with app.run_test() as pilot:
            reporter = session._herdr_reporter
            if mode == "enabled":
                assert isinstance(reporter, HerdrReporter)
                await eventually(predicate=lambda: reporter._display_ack_revision is not None)
                assert reporter._saved is not None
                fake_herdr.guard.require_registered(path=fake_herdr.executable)
                fake_herdr.barrier.write_text("hold" if route == "single" else "release", encoding="utf-8")
            boundary = len(commands(fake_herdr))
            await pilot.pause()
            assert app._input is not None
            app._input.focus()
            app._input.load_text("Run the clock then finish")
            await pilot.press("enter")
            try:
                try:
                    await asyncio.wait_for(entered.wait(), timeout=30)
                except TimeoutError:
                    pytest.fail(
                        f"Tool not reached: factory={native_factory.call_count}; events={events}; screen={type(app.screen)} focus={app.focused} input={app._input.text!r} disabled={app._input.disabled}; lines={app._adapter.lines if app._adapter else None}"
                    )
                assert session.is_running
                if mode == "enabled":
                    await eventually(
                        predicate=lambda: any("working" in row for row in commands(fake_herdr)[boundary:])
                    )
                release.set()
                await eventually(predicate=lambda: any(event.kind == "run_completed" for event in events))
                await eventually(predicate=lambda: not session.is_running)
                assert session.usage_snapshot().session_totals.total_tokens == 8
                assert attempts == (2 if route == "single" else 3)
                if route == "retry":
                    assert any(event.kind == "run_retrying" for event in events)
                if route == "fallback":
                    assert session.usage_snapshot().active_model_name == "gpt-4.1"
                    assert session.model_pool_dao == pool
                assert [event.tool_name for event in events if event.kind == "tool_result"] == ["now"]
                assert session._history_store is not None
                history = await session._history_store.load_events(session_id=session.session_id)
                assert sum(event.kind == "user_message" for event in history) == 1
                assert sum(event.kind == "run_completed" for event in history) == 1
                if parity_records is not None:
                    trace = SemanticTrace()
                    parity_records.append(
                        (trace.serialize(records=list(events)), trace.serialize(records=list(history)))
                    )
                if mode == "enabled" and route == "single":
                    assert fake_herdr.barrier.read_text() == "hold"
                    assert isinstance(reporter, HerdrReporter)
                    assert reporter.retains_external_resources
            finally:
                release.set()
                fake_herdr.guard.require_registered(path=fake_herdr.executable)
                fake_herdr.barrier.write_text("release", encoding="utf-8")
            if mode == "enabled":
                await eventually(
                    predicate=lambda: any(
                        "session_tokens=8" in " ".join(row) for row in commands(fake_herdr)[boundary:]
                    )
                )
                await eventually(
                    predicate=lambda: any("idle" in row for row in commands(fake_herdr)[boundary:])
                )
            else:
                assert commands(fake_herdr) == []
                assert session._herdr_start_task is None
                assert not (Path(os.environ["SLO_HOME"]) / "integrations").exists()
            if mounted_continuation is not None:
                await mounted_continuation(app, pilot)
    if mode == "enabled":
        assert isinstance(reporter, HerdrReporter)
        assert not reporter.retains_external_resources
    assert "gpt-5.4" not in json.dumps(commands(fake_herdr))
    assert str(tmp_path) not in json.dumps(commands(fake_herdr))


@pytest.mark.parametrize("mode", ["disabled", "outside"])
async def test_inactive_prompt_has_zero_integration_attempts(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Record forbidden attempts outside isolated callbacks while real history works."""
    boundaries = [
        (SloAgentSession, "_prepare_herdr_parent"),
        (SloAgentSession, "_prepare_herdr_capture_inputs"),
        (SloAgentSession, "_resolve_herdr_capture_paths"),
        (HerdrRestoreStore, "__init__"),
        (HerdrRestoreStore, "save"),
        (HerdrRestoreStore, "_prepare_directories"),
        (HerdrSequenceStore, "__init__"),
        (HerdrSequenceStore, "acquire"),
        (HerdrSequenceStore, "reserve"),
        (HerdrFileLease, "validate"),
        (HerdrFileLease, "acquire"),
        (HerdrCliTransport, "__init__"),
        (HerdrCliTransport, "invoke"),
        (HerdrCliTransport, "_spawn"),
    ]
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    writes = IntegrationWriteAttempts(home=tmp_path, owned_root=tmp_path)
    with monkeypatch.context() as filesystem_patch, ExitStack() as stack:
        writes.install(monkeypatch=filesystem_patch)
        attempts = [
            stack.enter_context(
                patch.object(owner, name, side_effect=OSError("inactive integration attempted"))
            )
            for owner, name in boundaries
        ]
        await test_prompt_tool_usage_completes_while_report_cli_is_stalled(
            tmp_path=tmp_path,
            fake_herdr=fake_herdr,
            native_factory=native_factory,
            monkeypatch=monkeypatch,
            mode=mode,
            route="single",
        )
        writes.assert_unused()
        assert {
            f"{owner.__name__}.{name}": spy.call_count
            for (owner, name), spy in zip(boundaries, attempts)
            if spy.called
        } == {}


@pytest.mark.parametrize("operation", ["mkdir", "open", "replace"])
def test_integration_write_spy_detects_swallowed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """A controlled caught failure cannot hide the attempted integration mutation."""
    writes = IntegrationWriteAttempts(home=tmp_path, owned_root=tmp_path)
    target = tmp_path / "integrations" / "herdr" / "controlled.json"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    with monkeypatch.context() as scoped:
        writes.install(monkeypatch=scoped)
        try:
            if operation == "mkdir":
                os.mkdir(target)
            elif operation == "open":
                os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
            else:
                os.replace(target, target.with_suffix(".replacement"))
        except OSError:
            pass
    assert writes.attempts == [(operation, str(target))]
    with pytest.raises(AssertionError, match="integration I/O attempts"):
        writes.assert_unused()
    assert not target.exists()


@pytest.mark.parametrize("route", ["single", "retry", "fallback"])
async def test_enabled_disabled_outside_exact_ordered_parity(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    """Compare complete event/history structures from three actual mounted journeys."""
    records: list[tuple[list[object], list[object]]] = []
    for mode in ("disabled", "outside", "enabled"):
        monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="0")
        monkeypatch.setenv(name="HERDR_ENV", value="1")
        await test_prompt_tool_usage_completes_while_report_cli_is_stalled(
            tmp_path=tmp_path,
            fake_herdr=fake_herdr,
            native_factory=native_factory,
            monkeypatch=monkeypatch,
            mode=mode,
            route=route,
            parity_records=records,
        )
    assert len(records) == 3
    for actual in records[1:]:
        assert records[0] == actual, "\n".join(
            difflib.unified_diff(
                json.dumps(records[0], indent=2).splitlines(), json.dumps(actual, indent=2).splitlines()
            )
        )


@pytest.mark.parametrize("cooldown_end", ["zero", "cleared"])
async def test_actual_session_unknown_usage_explicitly_clears_before_patch(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    cooldown_end: str,
) -> None:
    """Real session rebuild and history-unavailable result remove old CLI metadata."""
    native_factory.return_value = LLMBuildResult(
        llm=FauxChatModel(
            responses=[
                AIMessage(
                    content="usage known",
                    usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                )
            ]
        ),
        supports_explicit_caching=False,
    )
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=session)
    with patch.object(
        CredentialResolver,
        "resolve",
        return_value=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-clear-key"
        ),
    ):
        await _assert_usage_clears(
            app=app,
            session=session,
            fake_herdr=fake_herdr,
            native_factory=native_factory,
            cooldown_end=cooldown_end,
        )


async def _assert_usage_clears(
    *,
    app: SloTUI,
    session: SloAgentSession,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    cooldown_end: str,
) -> None:
    """Drive mounted usage transitions with the credential boundary controlled."""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._input is not None
        app._input.focus()
        app._input.load_text("Establish durable context")
        await pilot.press("enter")
        await eventually(predicate=lambda: native_factory.called and not session.is_running)
        await pilot.pause()
        await session.refresh_context_window_snapshot()
        session._set_retry_cooldown(wait_seconds=30)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(
            predicate=lambda: any(
                "cooldown=30s" in row and any(item.startswith("context=") for item in row)
                for row in commands(fake_herdr)
            )
        )
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        boundary = len(commands(fake_herdr))
        assert session._history_store is not None
        with patch.object(
            session._history_store, "load_events", side_effect=OSError("synthetic unavailable history")
        ):
            await session.refresh_context_window_snapshot()
        if cooldown_end == "zero":
            session._set_retry_cooldown(wait_seconds=0)
        else:
            session._clear_retry_cooldown()
        usage = session.usage_snapshot()
        assert usage.context_window_snapshot is not None
        assert not usage.context_window_snapshot.estimate_available
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        assert reporter._latest is not None
        assert not {"context", "cooldown"} & {token.key for token in reporter._latest.snapshot.tokens}
        rows = commands(fake_herdr)[boundary:]
        patches = [
            index
            for index, row in enumerate(rows)
            if "--token" in row and not any(word.startswith("cooldown=") for word in row)
        ]
        assert patches
        patch_index = patches[-1]
        for key in ("context", "cooldown"):
            assert any(
                any(row[i : i + 2] == ["--clear-token", key] for i in range(len(row) - 1))
                for row in rows[:patch_index]
            )
        assert not any(word.startswith(("context=", "cooldown=")) for word in rows[patch_index])


@pytest.mark.parametrize("profile", ["compact", "detail"])
@pytest.mark.parametrize("tool_error", [False, True])
@pytest.mark.parametrize("failed_child", [False, True])
@pytest.mark.parametrize("provider_label", ["openai", "anthropic", "kimi_for_coding", "openrouter"])
async def test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider_label: str,
    failed_child: bool,
    tool_error: bool,
    profile: str,
) -> None:
    """Keep conversation in Slo, private policy in restore, neither in Herdr reports."""
    monkeypatch.setenv(name="SLO_HERDR_METADATA_PROFILE", value=profile)
    secret = f"sk-SYNTHETIC-{provider_label}-credential-124"
    conversation = f"INTENTIONAL-USER-CONTENT-{provider_label}-125"
    child_output = f"PRIVATE-CHILD-ERROR-{provider_label}-125"
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            f"barrier = Path({str(fake_herdr.barrier)!r})\n"
            "assert not barrier.is_symlink() and barrier.resolve().parent == root.resolve()\n"
            "if barrier.read_text() == 'fail':\n"
            f"    print({child_output!r})\n"
            f"    print({secret!r}, file=sys.stderr)\n"
            "    sys.exit(7)\n"
        )
    native_factory.return_value = LLMBuildResult(
        llm=FauxChatModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": "now", "args": {}, "id": "privacy-clock"}]),
                AIMessage(content=conversation),
            ]
        ),
        supports_explicit_caching=False,
    )

    async def private_tool() -> str:
        """Supply intentional text or a configured-secret exception to the real executor."""
        if tool_error:
            raise RuntimeError(f"CONTROLLED-TOOL-ERROR {secret}")
        return conversation

    monkeypatch.setattr(target=NowTool, name="invoke", value=private_tool)
    workspace = tmp_path / f"PRIVATE-{provider_label}.code-workspace"
    plugin = tmp_path / f"PRIVATE-{provider_label}-plugin.py"
    for path, text in ((workspace, '{"folders": []}'), (plugin, "def register(slo):\n    pass\n")):
        assert not path.is_symlink() and path.resolve().parent == tmp_path.resolve()
        path.write_text(text, encoding="utf-8")
    monkeypatch.setenv(name=f"SLO_{provider_label.upper()}_API_KEY", value=secret)
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", workspace_file=workspace, plugin_paths=[plugin]
        )
    )
    await session.rename_session(session_name=secret)
    events: list[AgentStreamEventDAO] = []

    async def observe(event: AgentStreamEventDAO) -> None:
        """Capture public session events without modifying the relay."""
        events.append(event)

    transport_results: list[HerdrCommandResultDAO] = []
    original_transport = HerdrCliTransport.invoke

    async def capture_transport(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Retain all real reporting results, including failure and release."""
        result = await original_transport(transport, command=command, admission=admission)
        transport_results.append(result)
        return result

    monkeypatch.setattr(target=HerdrCliTransport, name="invoke", value=capture_transport)
    publications: list[str] = []
    original_publish = HerdrReporter.publish

    def capture_publication(reporter: HerdrReporter, *, publication: HerdrPublicationDAO) -> None:
        """Retain every public snapshot before coalescing, not the private capture."""
        publications.append(publication.snapshot.model_dump_json())
        original_publish(reporter, publication=publication)

    original_session_publish = SloAgentSession._publish_herdr_snapshot
    lookup_attempts: list[MagicMock] = []

    def guarded_publication(owner: SloAgentSession) -> None:
        """Block resolver and independent store access across every synchronous publication."""
        with ExitStack() as stack:
            for boundary, names in (
                (
                    CredentialResolver,
                    (
                        "resolve",
                        "resolve_with_source",
                        "require",
                        "_from_env",
                        "_from_store",
                        "_from_legacy_claude",
                    ),
                ),
                (CredentialStore, ("load", "_load_owned", "_read_envelope", "_parse_existing")),
            ):
                for name in names:
                    lookup_attempts.append(
                        stack.enter_context(
                            patch.object(
                                boundary, name, side_effect=AssertionError("publication credential lookup")
                            )
                        )
                    )
            original_session_publish(owner)

    monkeypatch.setattr(target=SloAgentSession, name="_publish_herdr_snapshot", value=guarded_publication)
    session.subscribe(handler=observe)
    app = SloTUI(session=session)
    monkeypatch.setattr(target=HerdrReporter, name="publish", value=capture_publication)
    with patch.object(
        CredentialResolver,
        "resolve",
        return_value=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token=secret
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            reporter = session._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            await eventually(
                predicate=lambda: reporter._saved is not None
                and reporter._display_ack_revision == reporter._revision
            )
            assert reporter._latest is not None and reporter._latest.restore_capture is not None
            capture = reporter._latest.restore_capture.config
            assert capture.workspace_file == workspace and capture.plugin_paths == (plugin,)
            stored = list((reporter._config.state_root / "restore-v1").glob("*.json"))
            assert stored
            private_bytes = "".join(path.read_text() for path in stored)
            assert str(workspace) in private_bytes and str(plugin) in private_bytes
            assert secret not in private_bytes
            assert app._input is not None
            app._input.focus()
            if failed_child:
                fake_herdr.guard.require_registered(path=fake_herdr.executable)
                fake_herdr.barrier.write_text("fail", encoding="utf-8")
            app._input.load_text(conversation)
            await pilot.press("enter")
            await eventually(predicate=lambda: any(event.kind == "run_completed" for event in events))
            await eventually(predicate=lambda: not session.is_running)
            if failed_child:
                await eventually(
                    predicate=lambda: any(
                        record.getMessage() == "herdr_command_unavailable" for record in caplog.records
                    )
                )
            else:
                await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
            tool_results = [event for event in events if event.kind == "tool_result"]
            assert len(tool_results) == 1
            if tool_error:
                assert tool_results[0].content == f"Error: CONTROLLED-TOOL-ERROR {secret}"
            else:
                assert tool_results[0].content == conversation
            rotated = f"{secret}-rotated"
            monkeypatch.setenv(name=f"SLO_{provider_label.upper()}_API_KEY", value=rotated)
            await session.rename_session(session_name=rotated)
            # Inject hostile display labels only, without changing executable provider policy.
            session._usage_snapshot = session._usage_snapshot.model_copy(
                update={
                    "active_model_name": rotated,
                    "active_reasoning_level": rotated,
                    "provider_effort": rotated,
                }
            )
            session._publish_herdr_snapshot()
            if not failed_child:
                await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
            assert len(publications) > 1
            assert lookup_attempts and not any(mock.called for mock in lookup_attempts)
            public = "".join(publications) + json.dumps(commands(fake_herdr))
            # Literal user/tool content belongs in Slo's transcript, not reporting.
            assert conversation not in public
            assert child_output not in public
            # D §8 forbids integration-owned private configuration in EVERY event.
            # B §8 treats secret-bearing tool events as reporting inputs, not outputs.
            all_events = "".join(event.model_dump_json() for event in events)
            for private_config in (str(workspace), str(plugin), str(tmp_path)):
                assert private_config not in all_events
            public += "".join(
                str(record.__dict__) for record in caplog.records if "/slo_agent/herdr/" in record.pathname
            )
            for path in reporter._config.state_root.rglob("*"):
                if path.is_file() and "restore-v1" not in path.parts:
                    public += path.read_text()
            outcome = await session.close_external_reporting()
            public += outcome.model_dump_json()
            public += "".join(publications)
            public += json.dumps(commands(fake_herdr))
            public += "".join(
                str(record.__dict__) for record in caplog.records if "/slo_agent/herdr/" in record.pathname
            )
            for private_config in (str(workspace), str(plugin), str(tmp_path)):
                assert private_config not in "".join(event.model_dump_json() for event in events)
            for path in reporter._config.state_root.rglob("*"):
                if path.is_file() and "restore-v1" not in path.parts:
                    public += path.read_text()
            assert transport_results
            assert all(result.json_bytes is None for result in transport_results)
            public += "".join(result.model_dump_json() for result in transport_results)
            if failed_child:
                assert any(result.outcome.status == "rejected" for result in transport_results)
            for forbidden in (secret, rotated, child_output, str(workspace), str(plugin), str(tmp_path)):
                assert forbidden not in public
            assert not any(mock.called for mock in lookup_attempts)


@pytest.mark.parametrize("provider_label", ["openai", "anthropic", "kimi_for_coding", "openrouter"])
async def test_reporter_lifetime_never_looks_up_rotated_credentials(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    provider_label: str,
) -> None:
    """Admit a real Faux prompt before blocking the complete reporting lifetime.

    Provider names label synthetic hostile inputs, not native provider runs.
    No reporter exists during ordinary credential/factory admission.
    """
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(
        CredentialResolver,
        "resolve",
        return_value=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-admission-133"
        ),
    ):
        admitted_events = [event async for event in session.invoke(text="admit before reporting")]
    assert any(event.kind == "run_completed" for event in admitted_events)
    assert native_factory.called
    assert session._herdr_start_task is None
    await session.rename_session(session_name=f"SYNTHETIC-{provider_label}-before-133")
    blockers = ReportingCredentialBlockers()
    with ExitStack() as stack:
        blockers.install(stack=stack)
        try:
            await session.start_external_reporting(interactive=True)
            reporter = session._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            await eventually(
                predicate=lambda: reporter._saved is not None
                and reporter._display_ack_revision == reporter._revision
            )
            for suffix in ("before", "rotated"):
                label = f"SYNTHETIC-{provider_label}-{suffix}-133"
                monkeypatch.setenv(name=f"SLO_{provider_label.upper()}_API_KEY", value=label)
                # Real rename persistence uses ordinary Slo redaction and is
                # covered by the mounted matrix above, outside these blockers.
                # Valid immutable private DAO inputs; never claim execution of an
                # arbitrary model or pretend a free-text provider is a native enum.
                assert reporter._latest is not None
                assert reporter._latest.restore_capture is not None
                config = reporter._latest.restore_capture.config
                from src.agents.slo_agent.herdr.dao import HerdrRestoreCaptureDAO, HerdrRestoreConfigDAO
                from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
                from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO

                private = HerdrRestoreCaptureDAO(
                    config=HerdrRestoreConfigDAO(**{**config.model_dump(), "model_name": label})
                )
                usage = SessionUsageSnapshotDAO(
                    active_model_name=label, active_reasoning_level=label, provider_effort=label
                )
                # Provider labels have no input slot: reject, rather than invent
                # a native-provider execution claim or bypass DAO validation.
                for field in ("provider", "provider_label"):
                    with pytest.raises(ValueError):
                        SessionUsageSnapshotDAO.model_validate({**usage.model_dump(), field: label})
                for profile in ("compact", "detail"):
                    snapshot = HerdrSnapshotProjector.build(
                        session_id=session.session_id,
                        state="idle",
                        history_enabled=True,
                        usage=usage,
                        metadata_profile=profile,
                    )
                    assert label not in snapshot.model_dump_json()
                    assert not {"model", "provider", "effort", "session", "reasoning"} & {
                        token.key for token in snapshot.tokens
                    }
                    reporter.publish(
                        publication=HerdrPublicationDAO(
                            configuration_generation=reporter._latest.configuration_generation + 1,
                            snapshot=snapshot,
                            restore_capture=private,
                        )
                    )
                    await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
                    assert reporter._saved is not None
                    assert reporter._saved.capture == private
                await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
                assert label not in json.dumps(commands(fake_herdr))
            assert reporter._saved is not None
            assert any("--herdr-restore" in row for row in commands(fake_herdr))
        finally:
            outcome = await session.close_external_reporting()
        assert outcome.resources == "drained"
        blockers.assert_unused()
    blockers.assert_unused()


async def test_secret_tool_error_preserves_enabled_disabled_event_parity(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reporting does not sanitize or otherwise change ordinary Slo tool errors."""
    secret = "sk-SYNTHETIC-input-credential-parity-132"
    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value=secret)
    monkeypatch.setattr(
        target=CredentialResolver,
        name="resolve",
        value=MagicMock(
            return_value=CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token=secret
            )
        ),
    )

    async def fail_tool() -> str:
        """Reproduce the separate ordinary-Slo disclosure using a synthetic key."""
        raise RuntimeError(f"CONTROLLED-TOOL-ERROR {secret}")

    monkeypatch.setattr(target=NowTool, name="invoke", value=fail_tool)
    traces: list[list[object]] = []
    for disabled in (False, True):
        monkeypatch.setenv(name="SLO_HERDR_DISABLED", value=str(int(disabled)))
        native_factory.return_value = LLMBuildResult(
            llm=FauxChatModel(
                responses=[
                    AIMessage(content="", tool_calls=[{"name": "now", "args": {}, "id": "privacy-clock"}]),
                    AIMessage(content="completed"),
                ]
            ),
            supports_explicit_caching=False,
        )
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        events: list[AgentStreamEventDAO] = []

        async def observe(event: AgentStreamEventDAO) -> None:
            """Retain full ordinary events for strict semantic comparison."""
            events.append(event)

        session.subscribe(handler=observe)
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.focus()
            app._input.load_text("controlled request")
            await pilot.press("enter")
            await eventually(predicate=lambda: any(event.kind == "run_completed" for event in events))
            await eventually(predicate=lambda: not session.is_running)
        results = [event.content for event in events if event.kind == "tool_result"]
        assert results == [f"Error: CONTROLLED-TOOL-ERROR {secret}"]
        traces.append(SemanticTrace().serialize(records=list(events)))
    assert traces[0] == traces[1]
    assert secret not in json.dumps(commands(fake_herdr))


@pytest.mark.parametrize(
    "mode",
    ["auto_off", "unavailable", "platform_opened", "platform_failed", "discovery_failed", "thread_failed"],
)
async def test_high_level_viewer_public_outcome_privacy(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
) -> None:
    """Exercise high-level skipped/failed/opened outcomes with no real window."""
    secret = "SYNTHETIC-viewer-private-133"
    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value=secret)
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="0" if mode == "auto_off" else "1")
    monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._herdr_destination = "unavailable" if mode == "unavailable" else "platform"
    spawned: list[list[str]] = []

    def spawn(argv: list[str]) -> object:
        """Capture actual platform argv, optionally fail with private exception text."""
        spawned.append(argv)
        if mode == "platform_failed":
            raise OSError(secret)
        return object()

    monkeypatch.setattr(target=VisualizerLauncher, name="_default_spawn", value=staticmethod(spawn))
    monkeypatch.setattr(
        target=VisualizerLauncher,
        name="_resolve_linux_terminal",
        value=classmethod(lambda cls: "synthetic-terminal"),
    )
    if mode == "discovery_failed":
        monkeypatch.setattr(
            target=VisualizerLauncher, name="_slo_entrypoint", value=MagicMock(side_effect=OSError(secret))
        )
    if mode == "thread_failed":
        monkeypatch.setattr(
            target=VisualizerLauncher, name="launch", value=MagicMock(side_effect=RuntimeError(secret))
        )
    outcome = await VisualizerLauncher.launch_async(parent_session_id=session.session_id, session=session)
    assert (
        outcome.status
        == {
            "auto_off": "skipped",
            "unavailable": "failed",
            "platform_opened": "opened",
            "platform_failed": "failed",
            "discovery_failed": "failed",
            "thread_failed": "failed",
        }[mode]
    )
    assert bool(spawned) is mode.startswith("platform")
    assert commands(fake_herdr) == []
    assert secret not in outcome.model_dump_json() + json.dumps(spawned)
    diagnostics = [
        record.__dict__ for record in caplog.records if record.getMessage() == "visualizer_launch_failed"
    ]
    assert secret not in str(diagnostics)
    assert len(diagnostics) == int(mode == "platform_failed")
    for record in diagnostics:
        assert record["category"] == "platform_spawn_failed"
        assert not {"error", "argv", "exception", "error_class"} & record.keys()
        assert record["exc_info"] is None and record["exc_text"] is None
        assert record["args"] == ()
    assert outcome.model_dump() == {"status": outcome.status, "pane_id": None}
    from tests.tui.workflows.test_workflow_renderer import _build_renderer

    renderer, sink, _ = _build_renderer()
    renderer.write_launch_outcome(parent_session_id=session.session_id, outcome=outcome)
    assert len(sink.lines) == 1
    assert secret not in str(sink.lines)
    assert str(tmp_path) not in str(sink.lines)


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("mode", ["platform_opened", "platform_failed", "auto_off", "unavailable"])
async def test_mounted_viewer_destination_privacy(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    detached: bool,
    mode: str,
) -> None:
    """Drive both public event entries through real scheduling and platform continuation."""
    secret = "SYNTHETIC-PRIVATE-CONFIG-135"
    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value=secret)
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="0" if mode == "auto_off" else "1")
    monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="0" if mode == "unavailable" else "1")
    if mode == "unavailable":
        monkeypatch.delenv(name="HERDR_PANE_ID")
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", append_system_prompt=secret)
    )
    await session.rename_session(session_name=secret)
    parent = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    parent_id = parent.session_id if detached else session.session_id
    events: list[str] = []
    outcomes: list[VisualizerLaunchOutcomeDAO] = []
    registrations: list[bool] = []
    spawned: list[list[str]] = []
    publications: list[str] = []
    original_publish = HerdrReporter.publish
    original_schedule = SloTUI._schedule_visualizer_launch
    original_launch = VisualizerLauncher.launch_async

    def capture_publication(reporter: HerdrReporter, *, publication: HerdrPublicationDAO) -> None:
        """Observe every attempted public report, including transient revisions."""
        publications.append(publication.snapshot.model_dump_json())
        original_publish(reporter, publication=publication)

    def capture_schedule(app: SloTUI, *, parent_session_id: str) -> None:
        """Observe registration synchronously, before the real worker can finish."""
        original_schedule(app, parent_session_id=parent_session_id)
        registrations.append(parent_session_id in app._visualizer_launch_tasks)

    async def capture_launch(
        cls: type[VisualizerLauncher], *, parent_session_id: str, session: SloAgentSession
    ) -> VisualizerLaunchOutcomeDAO:
        """Retain the actual destination result without substituting execution."""
        result = await original_launch(parent_session_id=parent_session_id, session=session)
        outcomes.append(result)
        return result

    def spawn(argv: list[str]) -> object:
        """Replace only OS creation; real synchronous construction still runs in its thread."""
        spawned.append(argv)
        if mode == "platform_failed":
            raise OSError(secret)
        return object()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Record every public event during the mounted owner's lifetime."""
        events.append(event.model_dump_json())

    monkeypatch.setattr(target=HerdrReporter, name="publish", value=capture_publication)
    monkeypatch.setattr(target=SloTUI, name="_schedule_visualizer_launch", value=capture_schedule)
    monkeypatch.setattr(target=VisualizerLauncher, name="launch_async", value=classmethod(capture_launch))
    monkeypatch.setattr(target=VisualizerLauncher, name="_default_spawn", value=staticmethod(spawn))
    monkeypatch.setattr(
        target=VisualizerLauncher,
        name="_resolve_linux_terminal",
        value=classmethod(lambda cls: "fake-terminal"),
    )
    session.subscribe(handler=observe)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert session.workflow_visualizer_destination == (
            "unavailable" if mode == "unavailable" else "platform"
        )
        event = AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="controlled-child", task_id="task")
        if detached:
            event = AgentStreamEventDAO(
                kind="tool_result",
                tool_name="launch_workflow",
                tool_call_id="controlled-launch",
                content=json.dumps({"workflow_id": "wf-private", "orchestrator_session_id": parent_id}),
            )
        await session.event_relay(event)
        assert registrations == [mode != "auto_off"]
        if mode != "auto_off":
            await eventually(predicate=lambda: bool(outcomes))
        await eventually(predicate=lambda: not app._visualizer_launch_tasks)
        assert [result.status for result in outcomes] == (
            [] if mode == "auto_off" else ["opened" if mode == "platform_opened" else "failed"]
        )
        assert len(spawned) == int(mode.startswith("platform"))
        assert commands(fake_herdr) == []
        assert app._adapter is not None
        notices = [
            str(content)
            for content, _ in app._adapter.lines
            if "workflow vi" in str(content).lower() or "workflow view" in str(content).lower()
        ]
        expected = {
            "platform_opened": "⊇ Opened workflow visualizer in a new window.",
            "platform_failed": f"⊇ Workflow viewer launch failed; recover manually slo visualize --session {parent_id} --follow",
            "unavailable": f"⊇ Workflow viewer launch failed; recover manually slo visualize --session {parent_id} --follow",
        }
        assert notices == ([] if mode == "auto_off" else [expected[mode]])
        if spawned:
            assert parent_id in str(spawned)
        public = "".join(events) + str(notices) + json.dumps(spawned)
        public += "".join(result.model_dump_json() for result in outcomes)
        public += str(
            [
                record.__dict__
                for record in caplog.records
                if "/slo_agent/herdr/" in record.pathname
                or record.pathname.endswith("visualizer_launcher.py")
            ]
        )
        assert secret not in public
        assert all(result.model_dump() == {"status": result.status, "pane_id": None} for result in outcomes)
    assert not app._visualizer_launch_tasks
    assert publications == []


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("child_mode", ["success", "reject", "oversize", "private_output"])
async def test_pilot_configuration_and_typed_viewer_journey(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    detached: bool,
    child_mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pilot slash actions and public event relay reach both production viewer paths."""
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    secret = "sk-SYNTHETIC-viewer-127"
    child_private = "PRIVATE-CHILD-OUTPUT-127"
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            'if sys.argv[2] == "split":\n'
            f"    print({secret!r}, file=sys.stderr)\n"
            f"    mode = {child_mode!r}\n"
            '    if mode == "oversize":\n'
            '        print("x" * 16385)\n'
            '    elif mode == "private_output":\n'
            f"        print({child_private!r})\n"
            "    else:\n"
            '        print(\'{"result":{"pane":{"pane_id":"journey-viewer"}}}\')\n'
            'if sys.argv[2] == "run":\n'
            f"    print({child_private!r})\n"
            f"    print({secret!r}, file=sys.stderr)\n"
            f'    sys.exit(7 if {child_mode!r} == "reject" else 0)\n'
        )
    observations: list[TransportObservation] = []
    transport_results: list[HerdrCommandResultDAO] = []
    viewer_results: list[VisualizerLaunchOutcomeDAO] = []
    hold_report = False
    report_entered = asyncio.Event()
    original_collect = HerdrCliTransport._collect_result

    async def hold_collection(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO
    ) -> HerdrCommandResultDAO:
        """Hold a spawned report until real replacement cancels its owning worker."""
        if hold_report and not report_entered.is_set() and command.argv[:2] == ("pane", "report-metadata"):
            report_entered.set()
            await asyncio.Event().wait()
        return await original_collect(transport, command=command)

    monkeypatch.setattr(target=HerdrCliTransport, name="_collect_result", value=hold_collection)
    original_transport = HerdrCliTransport.invoke
    original_viewer = HerdrVisualizerLauncher.invoke
    publications: list[str] = []
    viewer_steps: list[tuple[str, int]] = []
    original_publish = HerdrReporter.publish

    def capture_publication(reporter: HerdrReporter, *, publication: HerdrPublicationDAO) -> None:
        """Retain every public revision before the worker can coalesce it."""
        publications.append(publication.snapshot.model_dump_json())
        original_publish(reporter, publication=publication)

    monkeypatch.setattr(target=HerdrReporter, name="publish", value=capture_publication)

    async def capture_transport(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Observe every real command result without bypassing admission or spawning."""
        viewer_steps.append(("command_entry", len(publications)))
        task = asyncio.current_task()
        observation = TransportObservation(task_id=id(task), operation=command.argv[1], task=task)
        observations.append(observation)
        observed_admission = ObservedAdmission(
            delegate=admission, observation=observation, transport=transport
        )
        try:
            result = await original_transport(transport, command=command, admission=observed_admission)
            observation.status = "returned"
            transport_results.append(result)
            return result
        except asyncio.CancelledError:
            observation.status = "cancelled"
            raise
        except BaseException:
            observation.status = "error"
            raise
        finally:
            observation.finish(transport=transport)
            viewer_steps.append(("command_exit", len(publications)))

    async def capture_viewer(
        viewer: HerdrVisualizerLauncher, *, request: HerdrVisualizerRequestDAO
    ) -> VisualizerLaunchOutcomeDAO:
        """Observe the production one-shot ledger result and return it unchanged."""
        viewer_steps.append(("viewer_entry", len(publications)))
        result = await original_viewer(viewer, request=request)
        viewer_steps.append(("viewer_exit", len(publications)))
        viewer_results.append(result)
        return result

    monkeypatch.setattr(target=HerdrCliTransport, name="invoke", value=capture_transport)
    monkeypatch.setattr(target=HerdrVisualizerLauncher, name="invoke", value=capture_viewer)
    native_factory.return_value = LLMBuildResult(
        llm=FauxChatModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": "now", "args": {}, "id": "viewer-clock"}]),
                AIMessage(
                    content="viewer journey complete",
                    usage_metadata={
                        "input_tokens": 4,
                        "output_tokens": 2,
                        "total_tokens": 6,
                    },
                ),
            ]
        ),
        supports_explicit_caching=False,
    )
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    events: list[AgentStreamEventDAO] = []

    async def observe(event: AgentStreamEventDAO) -> None:
        """Retain actual mounted prompt events through configuration and replacement."""
        events.append(event)

    session.subscribe(handler=observe)
    with patch.object(
        CredentialResolver,
        "resolve",
        return_value=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token=secret
        ),
    ):
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("Run the clock before opening workflow viewers")
            await pilot.press("enter")
            await eventually(predicate=lambda: any(event.kind == "run_completed" for event in events))
            await eventually(predicate=lambda: not session.is_running)
            assert [event.tool_name for event in events if event.kind == "tool_result"] == ["now"]
            assert session.usage_snapshot().session_totals.total_tokens == 6
            await eventually(
                predicate=lambda: any("session_tokens=6" in " ".join(row) for row in commands(fake_herdr))
            )
            app._input.load_text("/rename PRIVATE-JOURNEY-LABEL")
            await pilot.press("enter")
            await eventually(predicate=lambda: session.session_name == "PRIVATE-JOURNEY-LABEL")
            app._input.load_text("/model gpt-4.1")
            await pilot.press("enter")
            await eventually(predicate=lambda: session.usage_snapshot().active_model_name == "gpt-4.1")
            parent = session
            if detached:
                parent = SloAgentSession.build(
                    config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
                )
                await parent.rename_session(session_name="PRIVATE-DETACHED-LABEL")
            assert parent.history_root is not None
            context = parent.history_root / parent.session_id / "orchestrator_context.json"
            assert context.resolve().is_relative_to(tmp_path.resolve())
            context.write_text(
                OrchestratorContextDAO.build(
                    system_prompt="PRIVATE-JOURNEY-CONTEXT", user_prompt="PRIVATE-JOURNEY-CONTEXT", model=None
                ).model_dump_json(),
                encoding="utf-8",
            )
            event = AgentStreamEventDAO(
                kind="sub_agent_spawned", sub_agent_id="controlled-child", task_id="task"
            )
            if detached:
                event = AgentStreamEventDAO(
                    kind="tool_result",
                    tool_name="launch_workflow",
                    tool_call_id="controlled-launch",
                    content=json.dumps(
                        {"workflow_id": "wf-journey", "orchestrator_session_id": parent.session_id}
                    ),
                )
            await session.event_relay(event)
            await eventually(predicate=lambda: bool(viewer_results))
            await eventually(predicate=lambda: not app._visualizer_launch_tasks)
            # A second request reaches the real session/adapter ledger, not only TUI deduplication.
            await session.open_workflow_visualizer(parent_session_id=parent.session_id)
            await session.event_relay(event)
            rows = [
                row
                for row in commands(fake_herdr)
                if row[:2] in [["pane", op] for op in ("split", "rename", "run")]
            ]
            expected_rows = [
                ["pane", "split", "--pane", "synthetic-pane", "--direction", "right", "--no-focus"],
                ["pane", "rename", "journey-viewer", f"Slo workflow {parent.session_id[:8]}"],
                ["pane", "run", "journey-viewer", f"slo visualize --session {parent.session_id} --follow"],
            ]
            assert rows == (expected_rows if child_mode in ("success", "reject") else expected_rows[:1])
            assert [result.status for result in viewer_results] == (
                ["submitted" if child_mode == "success" else "failed", "reused"]
                if child_mode in ("success", "reject")
                else ["failed", "failed"]
            )
            assert app._adapter is not None
            assert sum("Submitted workflow viewer command" in str(line) for line in app._adapter.lines) == (
                1 if child_mode == "success" else 0
            )
            hold_report = True
            # The real two-second refresh queues the next report; do not synthesize cancellation.
            await asyncio.wait_for(fut=report_entered.wait(), timeout=5.0)
            app._input.load_text("/new")
            await pilot.press("enter")
            await eventually(predicate=lambda: app._session is not session)
            hold_report = False
            successor = app._session
            await eventually(
                predicate=lambda: any(successor.session_id in row for row in commands(fake_herdr))
            )
            wire = commands(fake_herdr)
            new_claim = next(index for index, row in enumerate(wire) if successor.session_id in row)
            assert any(row[1] == "release-agent" for row in wire[:new_claim])
            assert not any(session.session_id in row for row in wire[new_claim:])
            assert "PRIVATE-JOURNEY" not in json.dumps(wire)
            assert str(tmp_path) not in json.dumps(wire)
        assert not app._visualizer_launch_tasks
        assert transport_results and viewer_results
        # json_bytes is explicitly private parser input; scan the public outcome on
        # EVERY result, including rejected/oversized commands and shutdown release.
        public = "".join(result.model_dump_json(exclude={"json_bytes"}) for result in transport_results)
        assert all(result.json_bytes is None for result in transport_results if result.outcome.status != "ok")
        if child_mode == "private_output":
            assert any(
                result.json_bytes and child_private.encode() in result.json_bytes
                for result in transport_results
            )
        assert publications and viewer_steps
        assert sum(step == "viewer_entry" for step, _ in viewer_steps) == len(viewer_results)
        for observation in observations:
            observation.assert_terminal()
        assert any(row.status == "cancelled" and row.admitted for row in observations), observations
        assert sum(step == "command_entry" for step, _ in viewer_steps) == len(observations)
        assert sum(row.status == "returned" for row in observations) == len(transport_results)
        assert sum(step == "command_exit" for step, _ in viewer_steps) == len(observations)
        public += json.dumps(
            [
                {
                    "task_id": row.task_id,
                    "operation": row.operation,
                    "status": row.status,
                    "admitted": row.admitted,
                    "completions": row.completions,
                    "completion_status": row.completion_status,
                    "drained": row.drained,
                }
                for row in observations
            ]
        )
        public += "".join(publications)
        public += "".join(result.model_dump_json() for result in viewer_results)
        public += "".join(event.model_dump_json() for event in events)
        public += str(
            [
                record.__dict__
                for record in caplog.records
                if "/slo_agent/herdr/" in record.pathname
                or record.pathname.endswith("visualizer_launcher.py")
            ]
        )
        assert app._adapter is not None
        public += str([line for line in app._adapter.lines if "workflow view" in str(line)])
        public += json.dumps(commands(fake_herdr))
        for result in viewer_results:
            assert set(result.model_dump()) == {"status", "pane_id"}
        from tests.tui.workflows.test_workflow_renderer import _build_renderer

        renderer, sink, _ = _build_renderer()
        for result in viewer_results:
            renderer.write_launch_outcome(parent_session_id=parent.session_id, outcome=result)
        public += str(sink.lines)
        for owner in (session, successor):
            reporter = owner._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            if reporter._latest is not None:
                public += reporter._latest.snapshot.model_dump_json()
            for path in reporter._config.state_root.rglob("*"):
                if path.is_file() and "restore-v1" not in path.parts:
                    public += path.read_text()
        for forbidden in (secret, child_private, str(tmp_path), "PRIVATE-JOURNEY", "PRIVATE-DETACHED"):
            assert forbidden not in public
        if child_mode == "reject":
            assert any(result.outcome.status == "rejected" for result in transport_results)
        if child_mode == "oversize":
            assert any(result.outcome.status == "malformed" for result in transport_results)


@pytest.mark.parametrize("route", ["single", "retry", "fallback"])
@pytest.mark.parametrize("uncertain", [False, True])
async def test_unified_mounted_prompt_configuration_both_viewers(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    uncertain: bool,
) -> None:
    """Keep actual prompt, both public viewer routes and configuration in one mounted lifetime."""
    from tests.integration.herdr_unified_141 import UnifiedMountedJourney

    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            'if sys.argv[2] == "split":\n'
            '    splits = sum(json.loads(line)[:2] == ["pane", "split"] for line in capture.read_text().splitlines())\n'
            f'    print("uncertain" if {uncertain!r} and splits == 2 else \'{{"result":{{"pane":{{"pane_id":"unified-viewer"}}}}}}\')\n'
        )
    journey = UnifiedMountedJourney(root=tmp_path, fake=fake_herdr, uncertain=uncertain)
    with patch.object(VisualizerLauncher, "launch", side_effect=AssertionError("OS fallback")) as platform:
        await test_prompt_tool_usage_completes_while_report_cli_is_stalled(
            tmp_path=tmp_path,
            fake_herdr=fake_herdr,
            native_factory=native_factory,
            monkeypatch=monkeypatch,
            mode="enabled",
            route=route,
            mounted_continuation=journey.invoke,
        )
        platform.assert_not_called()
    journey.assert_immutable()
