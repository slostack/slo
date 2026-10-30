"""T5 publication compositions; no operation/attention readiness is implied."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.echo import echo_tool
import asyncio
import json
import threading

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from tests.state_isolation import FakeHerdrFixture
from tests.agents.slo_agent.herdr.test_reporter import plain_slo, reporter
from src.agents.slo_agent.herdr.dao import HerdrRestoreConfigDAO, HerdrRestoreReferenceDAO


class BarrierRestoreStore(HerdrRestoreStore):
    """Hold the first real immutable save until the session commits newer facts."""

    def __init__(self, *, state_root: Path) -> None:
        """Allocate bounded synchronization without starting any worker."""
        super().__init__(state_root=state_root)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[HerdrRestoreConfigDAO] = []

    def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
        """Save exact captured bytes after the explicit first-save barrier."""
        self.calls.append(config)
        if len(self.calls) == 1:
            self.entered.set()
            assert self.release.wait(timeout=10)
        return super().save(config=config)


async def test_cancellation_joins_actual_reporter_save(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path
) -> None:
    """Cancel the reporter consumer only after its real filesystem save has entered."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    owner = reporter(root=tmp_path)
    store = BarrierRestoreStore(state_root=tmp_path)
    owner._restore_store = store
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    session._herdr_reporter = owner
    session._herdr_reporting_started = True
    session.refresh_usage_snapshot()
    publication = owner._latest
    assert publication is not None and publication.restore_capture is not None
    task = asyncio.create_task(coro=owner._consume_publication(publication=publication))
    try:
        assert await asyncio.to_thread(store.entered.wait, timeout=5)
        save_task = owner._save_task
        assert save_task is not None and not save_task.done()
        task.cancel()
        # A loop callback barrier proves cancellation was delivered, without sleeps.
        delivered = asyncio.Event()
        asyncio.get_running_loop().call_soon(delivered.set)
        await delivered.wait()
        assert not task.done() and not save_task.done()
        assert owner._save_task is save_task
        assert fake_herdr.capture.read_text() == ""
        store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert save_task.done() and not save_task.cancelled()
        assert owner._save_task is None and owner._restore_ack is None
        assert fake_herdr.capture.read_text() == ""
        records = list((tmp_path / "restore-v1").glob("*.json"))
        assert len(records) == 1
        loaded = store.load(restore_reference=records[0].stem, session_id=session.session_id)
        assert loaded == publication.restore_capture.config
    finally:
        store.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await session.close_external_reporting()


async def test_actual_prompt_cancellation_during_running_save(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path
) -> None:
    """A blocked reporter save cannot delay the actual Faux prompt's abort finalizer."""
    from collections.abc import AsyncIterator
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGenerationChunk
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    entered = asyncio.Event()
    original = FauxChatModel._astream

    async def blocked_provider(
        self: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Hold actual model execution until the owning prompt is cancelled."""
        entered.set()
        await asyncio.Event().wait()
        async for chunk in original(self, messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]), supports_explicit_caching=False
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
        patch.object(FauxChatModel, "_astream", new=blocked_provider),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        await session.rename_session(session_name="existing")
        await session._prepare_herdr_capture_inputs(interactive=True)
        owner = reporter(root=tmp_path)
        store = BarrierRestoreStore(state_root=tmp_path)
        owner._restore_store = store
        owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
        assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
        tmp_path.chmod(0o700)
        owner._sequence_store.acquire()
        owner._lease_held = True
        session._herdr_reporter = owner
        session._herdr_reporting_started = True
        session.refresh_usage_snapshot()
        publication = owner._latest
        assert publication is not None and publication.restore_capture is not None
        save_consumer = asyncio.create_task(coro=owner._consume_publication(publication=publication))

        async def consume() -> list[AgentStreamEventDAO]:
            """Drive public session execution, including durable abort finalization."""
            return [event async for event in session.invoke(text="cancel this prompt")]

        prompt = asyncio.create_task(coro=consume())
        try:
            assert await asyncio.to_thread(store.entered.wait, timeout=5)
            await asyncio.wait_for(entered.wait(), timeout=5)
            prompt.cancel()
            events = await asyncio.wait_for(prompt, timeout=5)
            assert any(event.kind == "run_aborted" for event in events)
            assert not session.is_running and not session._agent_is_injected
            assert not save_consumer.done()
            assert owner._save_task is not None and not owner._save_task.done()
            assert not store.release.is_set()
            assert session._history_store is not None
            history = await session._history_store.load_events(session_id=session.session_id)
            assert [
                event.kind
                for event in history
                if event.kind in ("run_completed", "run_aborted", "run_failed")
            ] == ["run_aborted"]
            store.release.set()
            await asyncio.wait_for(save_consumer, timeout=5)
            assert owner._restore_ack is not None
            assert owner._restore_ack.capture == publication.restore_capture
        finally:
            store.release.set()
            if not prompt.done():
                prompt.cancel()
            await asyncio.gather(prompt, save_consumer, return_exceptions=True)
            await session.close_external_reporting()


@pytest.mark.parametrize("change", ["usage_rename", "reasoning"])
async def test_real_session_save_barrier_latest_publication(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path, change: str
) -> None:
    """G1 uses real session usage, real immutable files and actual guarded commands."""
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    owner = reporter(root=tmp_path)
    store = BarrierRestoreStore(state_root=tmp_path)
    owner._restore_store = store
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    faux = FauxChatModel(
        responses=[
            AIMessage(
                content="done", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
            )
        ]
    )
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low")
        )
        await session.rename_session(session_name="original")
        await session._prepare_herdr_capture_inputs(interactive=True)
        session._herdr_reporter = owner
        session._herdr_reporting_started = True
        session.refresh_usage_snapshot()
        first = owner._latest
        assert first is not None and first.restore_capture is not None
        task = asyncio.create_task(coro=owner._consume_publication(publication=first))
        try:
            assert await asyncio.to_thread(store.entered.wait, timeout=5)
            async with asyncio.timeout(5):
                async for _ in session.invoke(text="private prompt sentinel"):
                    pass
            assert session.refresh_usage_snapshot().session_totals.total_tokens == 15
            await session.rename_session(session_name="private label sentinel")
            if change == "reasoning":
                session.switch_reasoning_level(reasoning_level="high")
            latest = owner._latest
            assert latest is not None and latest.snapshot.tokens != first.snapshot.tokens
            store.release.set()
            await task
            if change == "reasoning":
                assert owner._restore_ack is None
                assert not fake_herdr.capture.read_text()
                await owner._consume_publication(publication=latest)
            else:
                assert latest.restore_capture is first.restore_capture
                assert latest.configuration_generation == first.configuration_generation
            assert len(store.calls) == (2 if change == "reasoning" else 1)
            assert owner._restore_ack is not None
            assert owner._restore_ack.capture == latest.restore_capture
            assert owner._display_ack_revision == owner._revision
            commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
            wire = json.dumps(commands)
            assert "private prompt sentinel" not in wire and "private label sentinel" not in wire
            assert str(tmp_path) not in wire
            assert all(f"{token.key}={token.value}" in wire for token in latest.snapshot.tokens)
            records = list((tmp_path / "restore-v1").glob("*.json"))
            assert len(records) == len(store.calls)
            assert not session._agent_is_injected
        finally:
            store.release.set()
            await task
            await session.close_external_reporting()


@pytest.mark.parametrize("provider", ["anthropic", "openai", "kimi", "openrouter"])
async def test_four_provider_publication_privacy_after_rotation(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    plain_slo: Path,
    provider: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Real session publications omit arbitrary labels without consulting credentials."""
    from src.auth.credential_resolver import CredentialResolver
    from src.auth.credential_store import CredentialStore
    from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="initial")
    await session._prepare_herdr_capture_inputs(interactive=True)
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    session._herdr_reporter = owner
    session._herdr_reporting_started = True
    sentinels = [f"synthetic-{provider}-secret-before", f"synthetic-{provider}-secret-after"]
    try:
        for sentinel in sentinels:
            # Rename's ordinary history redaction is outside the pure publication boundary.
            await session.rename_session(session_name=sentinel)
            session._usage_snapshot = SessionUsageSnapshotDAO(
                active_model_name=sentinel,
                provider_effort=sentinel,
                active_reasoning_level=sentinel,
                usage_available=True,
                session_totals=TokenUsageTotalsDAO(input_tokens=12, output_tokens=3, total_tokens=15),
            )
            with (
                patch.object(
                    CredentialResolver, "resolve", side_effect=AssertionError("credential lookup")
                ) as resolve,
                patch.object(
                    CredentialResolver, "require", side_effect=AssertionError("credential require")
                ) as require,
                patch.object(CredentialStore, "load", side_effect=AssertionError("credential store")) as load,
            ):
                session._publish_herdr_snapshot()
                publication = owner._latest
                assert publication is not None
                assert publication.snapshot.tokens
                assert all(
                    token.key not in {"model", "provider", "effort", "session", "reasoning"}
                    for token in publication.snapshot.tokens
                )
                assert sentinel not in publication.snapshot.model_dump_json()
                await owner._consume_publication(publication=publication)
                from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector

                detail = HerdrSnapshotProjector.build(
                    session_id=session.session_id,
                    state="idle",
                    history_enabled=True,
                    usage=session._usage_snapshot,
                    metadata_profile="detail",
                )
                assert sentinel not in detail.model_dump_json()
                assert all(
                    token.key not in {"model", "provider", "effort", "session", "reasoning"}
                    for token in detail.tokens
                )
                # Exercise the real fixed diagnostic sink rather than scan an empty log.
                owner.record_publication_failure()
                resolve.assert_not_called()
                require.assert_not_called()
                load.assert_not_called()
        wire = fake_herdr.capture.read_text()
        assert "session_tokens=15" in wire
        for secret in (*sentinels, str(tmp_path)):
            assert secret not in wire
        diagnostic_records = [
            record.getMessage() for record in caplog.records if "herdr" in record.pathname.lower()
        ]
        assert diagnostic_records
        assert all(secret not in line for secret in sentinels for line in diagnostic_records)
    finally:
        await session.close_external_reporting()


async def test_catalog_only_adoption_does_not_save_or_release(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path
) -> None:
    """Repeated genuine catalog adoption preserves installed private identity."""
    from src.agents.model_catalog.service import ModelCatalogService

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    session._herdr_reporter = owner
    session._herdr_reporting_started = True
    session.refresh_usage_snapshot()
    first = owner._latest
    assert first is not None
    try:
        await owner._consume_publication(publication=first)
        binding = owner._binding
        count = len(fake_herdr.capture.read_text().splitlines())
        with patch.object(owner._restore_store, "save", wraps=owner._restore_store.save) as save:
            for _ in range(2):
                session._adopt_prepared_snapshot(
                    snapshot=ModelCatalogService.load(), model_names=("gpt-5.4",)
                )
                assert owner._latest is not None
                await owner._consume_publication(publication=owner._latest)
            save.assert_not_called()
        assert owner._binding == binding
        assert owner._latest is not None
        assert owner._latest.restore_capture is first.restore_capture
        assert owner._latest.configuration_generation == first.configuration_generation
        later = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][count:]
        assert all("release-agent" not in command for command in later)
    finally:
        await session.close_external_reporting()


@pytest.mark.parametrize("stage", ["_build_pool", "_build_workflow_tools", "_attach_sub_agent_pool"])
def test_bootstrap_failure_never_mints_provenance(tmp_path: Path, stage: str) -> None:
    """Every failing standard construction step leaves provenance untrusted."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    owner = session if stage == "_attach_sub_agent_pool" else OrchestratorSessionBootstrap
    error = RuntimeError("synthetic attachment failure")
    with (
        patch.object(owner, stage, side_effect=error),
        patch.object(session, "_finish_standard_orchestrator_attachment") as finish,
    ):
        with pytest.raises(RuntimeError) as raised:
            OrchestratorSessionBootstrap.attach(session=session)
    assert raised.value is error
    finish.assert_not_called()
    assert session._standard_orchestrator_attachment is None


async def test_real_routed_fallback_keeps_configured_capture(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path
) -> None:
    """A real pool's pre-output fallback changes telemetry, not saved pool policy."""
    from collections.abc import AsyncIterator
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatGenerationChunk
    from src.agents.providers.faux import FauxChatModel
    from src.agents.providers.model_pool import ModelPool
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver
    from tests.agents.slo_agent.herdr.test_session_capture import configured_pool

    policy = configured_pool()
    policy.entries[1].model_name = "gpt-5.5"
    primary = "gpt-5.5"
    secondary = "gpt-5.4"
    models: dict[str, BaseChatModel] = {
        primary: FauxChatModel(responses=[AIMessage(content="fail-primary")]),
        secondary: FauxChatModel(
            responses=[
                AIMessage(
                    content="done",
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                )
            ]
        ),
    }
    pool = ModelPool(pool_dao=policy, models=models)
    original = FauxChatModel._astream

    async def fail_primary(
        self: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Raise a real classifier-recognized pre-output rate limit on primary only."""
        if self.queue[0].content == "fail-primary":
            raise RuntimeError("rate limit 429")
        async for chunk in original(self, messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    with (
        patch("src.agents.slo_agent.graph.LLMFactory.create_pool", return_value=pool),
        patch.object(CredentialResolver, "resolve", return_value=credential),
        patch.object(FauxChatModel, "_astream", new=fail_primary),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_pool_dao=policy))
        await session.rename_session(session_name="existing")
        await session._prepare_herdr_capture_inputs(interactive=True)
        owner = reporter(root=tmp_path)
        owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
        tmp_path.chmod(0o700)
        owner._sequence_store.acquire()
        owner._lease_held = True
        session._herdr_reporter = owner
        session._herdr_reporting_started = True
        session.refresh_usage_snapshot()
        first = owner._latest
        assert first is not None and first.restore_capture is not None
        try:
            await owner._consume_publication(publication=first)
            count = len(fake_herdr.capture.read_text().splitlines())
            with patch.object(owner._restore_store, "save", wraps=owner._restore_store.save) as save:
                async for _ in session.invoke(text="hello"):
                    pass
                assert session.refresh_usage_snapshot().session_totals.total_tokens == 15
                assert session.active_model_name == secondary
                assert owner._latest is not None
                await owner._consume_publication(publication=owner._latest)
                save.assert_not_called()
            assert owner._latest.restore_capture is first.restore_capture
            assert owner._latest.configuration_generation == first.configuration_generation
            assert first.restore_capture.config.model_pool_dao == session._capture_herdr_pool(pool=policy)
            later = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][count:]
            assert all("release-agent" not in command for command in later)
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=session.session_id)
            assert any(event.kind == "route_switched" for event in events)
        finally:
            await session.close_external_reporting()


@pytest.mark.parametrize("custom", ["append_system_prompt", "extra_tools", "should_stop_after_turn_hook"])
def test_custom_origin_never_mints_provenance(tmp_path: Path, custom: str) -> None:
    """Pre-existing custom additions cannot be certified by the standard bootstrap."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    values = {
        "append_system_prompt": "private",
        "extra_tools": [echo_tool],
        "should_stop_after_turn_hook": lambda **kwargs: True,
    }
    setattr(config, custom, values[custom])
    session = SloAgentSession.build(config=config)
    with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._standard_orchestrator_attachment is None
    assert not session._herdr_policy_is_reproducible()


@pytest.mark.parametrize("state", ["active", "inactive", "closing"])
async def test_publication_has_no_io_credentials_or_model_build(
    tmp_path: Path, fake_herdr: object, state: str
) -> None:
    """Publication itself is memory-only, including its inactive early returns."""
    from contextlib import ExitStack
    from src.auth.credential_resolver import CredentialResolver

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    await session.start_external_reporting(interactive=True)
    owner = session._herdr_reporter
    assert isinstance(owner, HerdrReporter)
    capture = session._herdr_capture
    assert capture is not None
    try:
        session._herdr_reporting_started = state != "inactive"
        session._herdr_closing = state == "closing"
        with ExitStack() as stack:
            spies = [
                stack.enter_context(patch.object(target, method, side_effect=AssertionError(method)))
                for target, method in (
                    (Path, "resolve"),
                    (Path, "open"),
                    (CredentialResolver, "resolve"),
                    (CredentialResolver, "require"),
                    (session, "_build_agent"),
                    (session, "_capture_herdr_restore"),
                    (owner._restore_store, "save"),
                    (asyncio, "create_task"),
                )
            ]
            publish = stack.enter_context(patch.object(owner, "publish", wraps=owner.publish))
            diagnostic = stack.enter_context(patch.object(owner, "record_publication_failure"))
            session._publish_herdr_snapshot()
            for spy in spies:
                spy.assert_not_called()
            diagnostic.assert_not_called()
            assert publish.call_count == (1 if state == "active" else 0)
        assert session._herdr_capture is capture
    finally:
        session._herdr_closing = False
        await session.close_external_reporting()


@pytest.mark.parametrize("fault", ["projection", "reporter", "diagnostic"])
async def test_publication_failure_preserves_rename_and_history(
    tmp_path: Path, fake_herdr: object, fault: str
) -> None:
    """Optional synchronous failures cannot replace a successful durable rename."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="before")
    await session.start_external_reporting(interactive=True)
    owner = session._herdr_reporter
    target = HerdrSnapshotProjector if fault == "projection" else owner
    method = "build" if fault == "projection" else "publish"
    try:
        with (
            patch.object(target, method, side_effect=RuntimeError("private failure")),
            patch.object(
                owner,
                "record_publication_failure",
                side_effect=RuntimeError("sink failed") if fault == "diagnostic" else None,
            ) as diagnostic,
        ):
            result = await session.rename_session(session_name="after")
            session.refresh_usage_snapshot()
        assert result.session_name == "after"
        assert diagnostic.call_count == 2
        assert session._history_store is not None
        assert (
            await session._history_store.read_metadata(session_id=session.session_id)
        ).session_name == "after"
        assert await session._history_store.load_events(session_id=session.session_id) == []
    finally:
        await session.close_external_reporting()


@pytest.mark.parametrize("existing", ["_agent", "_sub_agent_pool"])
def test_bootstrap_early_return_never_mints_provenance(tmp_path: Path, existing: str) -> None:
    """Already-owned runtime resources bypass both provenance boundaries."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    setattr(session, existing, MagicMock())
    with (
        patch.object(session, "_begin_standard_orchestrator_attachment") as begin,
        patch.object(session, "_finish_standard_orchestrator_attachment") as finish,
    ):
        OrchestratorSessionBootstrap.attach(session=session)
    begin.assert_not_called()
    finish.assert_not_called()
    assert session._standard_orchestrator_attachment is None


@pytest.mark.parametrize("mutation", ["replaced_tool", "removed_tool", "system", "append", "hook"])
def test_standard_provenance_rejects_later_mutation(tmp_path: Path, mutation: str) -> None:
    """Object identity, cardinality and exact additions all remain authoritative."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._herdr_policy_is_reproducible()
    config = session._config
    assert config is not None and config.extra_tools
    if mutation == "replaced_tool":
        config.extra_tools[0] = config.extra_tools[0].model_copy()
    elif mutation == "removed_tool":
        config.extra_tools.pop()
    elif mutation == "system":
        config.system_prompt = "private changed system"
    elif mutation == "append":
        config.append_system_prompt = "private changed append"
    else:
        config.should_stop_after_turn_hook = lambda **kwargs: True
    assert not session._herdr_policy_is_reproducible()


@pytest.mark.parametrize("gateway", ["history", "rename"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_persistence_does_not_publish(
    tmp_path: Path, fake_herdr: object, gateway: str, cancel: bool
) -> None:
    """Persistence exceptions retain their identity and cannot publish a false commit."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    if gateway == "rename":
        await session.rename_session(session_name="original")
    await session.start_external_reporting(interactive=True)
    store = session._history_store
    assert store is not None
    before = session._herdr_capture
    generation = session._herdr_configuration_generation
    error = asyncio.CancelledError() if cancel else OSError("synthetic persistence failure")
    method = "ensure_session" if gateway == "history" else "rename_session"
    try:
        with (
            patch.object(store, method, side_effect=error),
            patch.object(
                session._herdr_reporter, "publish", wraps=session._herdr_reporter.publish
            ) as publish,
        ):
            with pytest.raises(type(error)) as raised:
                if gateway == "history":
                    await session._ensure_history_session()
                else:
                    await session.rename_session(session_name="rejected")
        assert raised.value is error
        publish.assert_not_called()
        assert session._herdr_capture is before
        assert session._herdr_configuration_generation == generation
        if gateway == "rename":
            assert (await store.read_metadata(session_id=session.session_id)).session_name == "original"
        else:
            assert not (store.root / session.session_id).exists()
    finally:
        await session.close_external_reporting()


async def test_supported_reasoning_commit_cannot_certify_unrelated_pool_mutation(
    tmp_path: Path, fake_herdr: object
) -> None:
    """An unrelated supported commit must not bless caller-edited pool policy."""
    from tests.agents.slo_agent.herdr.test_session_capture import configured_pool

    config = SessionConfigDAO(workdir=tmp_path, model_pool_dao=configured_pool(), reasoning_level="low")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="original")
    await session.start_external_reporting(interactive=True)
    try:
        before = session._herdr_capture
        assert before is not None and config.model_pool_dao is not None
        config.model_pool_dao.entries[0].priority += 1
        session.refresh_usage_snapshot()
        assert session._herdr_capture is None
        session.switch_reasoning_level(reasoning_level="high")
        assert session._herdr_capture is None
        assert before.config.model_pool_dao is not None
        assert before.config.model_pool_dao.entries[0].priority == 9
    finally:
        await session.close_external_reporting()
