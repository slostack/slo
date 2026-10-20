"""Finite publication cutoffs at real session and immutable-store boundaries."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_stale_startup_never_publishes(tmp_path: Path, outcome: str) -> None:
    """Operation states may publish, but superseded startup cannot restore stale policy."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    previous = session._herdr_capture
    assert previous is not None
    session._herdr_reporting_started = True
    generation = session._herdr_configuration_generation
    session._preparation_status = "pending"
    entered, release = asyncio.Event(), asyncio.Event()
    snapshot = ModelCatalogService.load()
    error = asyncio.CancelledError("original") if outcome == "cancel" else RuntimeError("original")

    async def prepare(**kwargs: object) -> ModelCatalogSnapshotDAO:
        """Pause actual startup at the external catalog boundary."""
        entered.set()
        await release.wait()
        if outcome != "success":
            raise error
        return snapshot

    with (
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare),
        patch.object(session._herdr_reporter, "publish") as publish,
        patch.object(session, "_adopt_herdr_capture") as adopt,
    ):
        task = asyncio.create_task(coro=session.prepare_startup())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            session._config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.5")
            release.set()
            if outcome == "cancel":
                with pytest.raises(asyncio.CancelledError) as caught:
                    await task
                assert caught.value is error
            else:
                await task
            publications = [call.kwargs["publication"] for call in publish.call_args_list]
            assert [item.snapshot.state for item in publications] == ["working", "working", "idle"]
            assert publications[0].restore_capture is previous
            assert publications[0].configuration_generation == generation
            assert all(item.restore_capture is None for item in publications[1:])
            assert all(item.configuration_generation == generation + 1 for item in publications[1:])
            assert all(item.snapshot.block_reason is None for item in publications)
            adopt.assert_not_called()
            assert session._herdr_capture is None
            assert session._herdr_configuration_generation == generation + 1
            assert session.preparation_status == "pending"
            assert not session._reporting_operations
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_caller_pool_mutation_preserves_actual_saved_bytes(tmp_path: Path) -> None:
    """An enqueued capture saves original ordered scalars despite later caller edits."""
    from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
    from tests.agents.slo_agent.herdr.test_session_capture import configured_pool
    from tests.agents.slo_agent.herdr.test_session_publication_compositions import BarrierRestoreStore

    policy = configured_pool()
    config = SessionConfigDAO(workdir=tmp_path, model_pool_dao=policy)
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    capture = session._herdr_capture
    assert capture is not None
    expected = capture.config.model_dump(mode="json")
    root = tmp_path / "private"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    root.mkdir(mode=0o700)
    store = BarrierRestoreStore(state_root=root)
    task = asyncio.create_task(coro=asyncio.to_thread(store.save, config=capture.config))
    try:
        assert await asyncio.to_thread(store.entered.wait, timeout=5)
        policy.entries[0].priority = 33
        policy.entries[0].cooldown_seconds = 99
        policy.entries.reverse()
        policy.entries.pop()
        store.release.set()
        reference = await task
        records = list((root / "restore-v1").glob("*.json"))
        assert len(records) == 1
        original_bytes = records[0].read_bytes()
        loaded = HerdrRestoreStore(state_root=root).load(
            restore_reference=reference.restore_reference, session_id=session.session_id
        )
        assert loaded.model_dump(mode="json") == expected
        session._herdr_reporting_started = True
        session.refresh_usage_snapshot()
        assert session._herdr_capture is None
        assert records[0].read_bytes() == original_bytes
    finally:
        store.release.set()
        await task


@pytest.mark.parametrize("fault", ["projection", "reporter", "diagnostic"])
async def test_full_faux_invoke_survives_publication_fault(tmp_path: Path, fault: str) -> None:
    """Actual config-backed execution retains answer and durable terminal outcome."""
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    faux = FauxChatModel(responses=[AIMessage(content="original answer")])
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        await session._prepare_herdr_capture_inputs(interactive=True)
        session._herdr_reporting_started = True
        owner = session._herdr_reporter
        target = HerdrSnapshotProjector if fault == "projection" else owner
        method = "build" if fault == "projection" else "publish"
        with (
            patch.object(target, method, side_effect=RuntimeError("reporter fault")) as failed,
            patch.object(
                owner,
                "record_publication_failure",
                side_effect=RuntimeError("diagnostic fault") if fault == "diagnostic" else None,
            ),
        ):
            events = [event async for event in session.invoke(text="original prompt")]
        assert failed.called
        assert not session._agent_is_injected
        assert any(event.content == "original answer" for event in events)
        assert session._history_store is not None
        history = await session._history_store.load_events(session_id=session.session_id)
        assert sum(event.kind == "run_completed" for event in history) == 1
        assert not any(event.kind in ("run_failed", "run_aborted") for event in history)
        assert session._herdr_capture is not None


@pytest.mark.parametrize("cancel", [False, True])
async def test_full_invoke_terminal_isolation(tmp_path: Path, cancel: bool) -> None:
    """Reporter failure preserves original run error or existing cancellation-to-abort contract."""
    from collections.abc import AsyncIterator
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    entered = asyncio.Event()
    error = ValueError("original run failure")

    async def stream(**kwargs: object) -> AsyncIterator[AgentStreamEventDAO]:
        """Control the run boundary without bypassing session persistence/finalization."""
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise error
        yield AgentStreamEventDAO(kind="run_completed")

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
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        session._herdr_reporting_started = True

        async def consume() -> list[AgentStreamEventDAO]:
            """Consume the public generator through its terminal finalizers."""
            return [event async for event in session.invoke(text="original prompt")]

        with (
            patch.object(session, "_stream_prompt_with_retries", new=stream),
            patch.object(session._herdr_reporter, "publish", side_effect=RuntimeError("report fault")),
        ):
            task = asyncio.create_task(coro=consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                if cancel:
                    task.cancel()
                    events = await task
                    assert any(event.kind == "run_aborted" for event in events)
                else:
                    with pytest.raises(ValueError) as caught:
                        await task
                    assert caught.value is error
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert session._history_store is not None
        history = await session._history_store.load_events(session_id=session.session_id)
        terminal = [
            event.kind for event in history if event.kind in ("run_completed", "run_failed", "run_aborted")
        ]
        assert terminal == ["run_aborted" if cancel else "run_failed"]


@pytest.mark.parametrize("fault", ["projection", "reporter", "diagnostic"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_faux_terminal_with_publication_fault(tmp_path: Path, fault: str, cancel: bool) -> None:
    """Preserve a terminal provider rejection or external abort through real graph execution."""
    from collections.abc import AsyncIterator
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGenerationChunk
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    entered, release = asyncio.Event(), asyncio.Event()
    original = FauxChatModel._astream
    import httpx
    from openai import APIStatusError

    error = APIStatusError(
        message="original provider rejection",
        response=httpx.Response(
            status_code=413, request=httpx.Request(method="POST", url="https://synthetic.invalid")
        ),
        body=None,
    )

    async def controlled_stream(
        self: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Emit actual Faux chunks before pausing the provider, not the session stream."""
        async for chunk in original(self, messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk
        entered.set()
        await release.wait()
        raise error

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="committed answer")]),
                supports_explicit_caching=False,
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
        patch.object(FauxChatModel, "_astream", new=controlled_stream),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        session._herdr_reporting_started = True
        events: list[AgentStreamEventDAO] = []

        async def consume() -> None:
            """Retain emitted output even when the public generator raises."""
            async for event in session.invoke(text="original prompt"):
                events.append(event)

        target = HerdrSnapshotProjector if fault == "projection" else session._herdr_reporter
        method = "build" if fault == "projection" else "publish"
        with (
            patch.object(target, method, side_effect=RuntimeError("publication fault")) as failed,
            patch.object(
                session._herdr_reporter,
                "record_publication_failure",
                side_effect=RuntimeError("diagnostic fault") if fault == "diagnostic" else None,
            ) as diagnostic,
        ):
            task = asyncio.create_task(coro=consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                if cancel:
                    task.cancel()
                    await asyncio.wait_for(task, timeout=5)
                else:
                    release.set()
                    with pytest.raises(APIStatusError) as caught:
                        await asyncio.wait_for(task, timeout=5)
                    assert caught.value is error
                assert failed.called and diagnostic.called
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert entered.is_set()
        assert not session._agent_is_injected
        assert not session.is_running
        assert session._history_store is not None
        history = await session._history_store.load_events(session_id=session.session_id)
        assert [
            event.kind for event in history if event.kind in ("run_completed", "run_failed", "run_aborted")
        ] == ["run_aborted" if cancel else "run_failed"]


@pytest.mark.parametrize("failure", ["missing", "unreadable", "wrong_identity"])
async def test_metadata_refresh_withdraws_then_recovers(tmp_path: Path, failure: str) -> None:
    """Activation refresh cannot retain eligibility from a previous successful read."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    store = session._history_store
    assert store is not None
    await store.ensure_session(session_id=session.session_id, workdir=tmp_path, model_name="gpt-5.4")
    await session._prepare_herdr_capture_inputs(interactive=True)
    previous = session._herdr_capture
    assert previous is not None
    metadata = await store.read_metadata(session_id=session.session_id)
    wrong = metadata.model_copy(update={"session_id": "00000000-0000-0000-0000-000000000001"})
    error = {"missing": FileNotFoundError(), "unreadable": OSError("private")}.get(failure)
    with patch.object(store, "read_metadata", return_value=wrong, side_effect=error):
        await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is None
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture == previous


async def test_injected_faux_agent_cannot_acquire_standard_provenance(tmp_path: Path) -> None:
    """Actual injected runtime stays nonrestorable through standard bootstrap and invoke."""
    from uuid import uuid4
    from langchain_core.messages import AIMessage
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    agent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="injected answer")]), cwd=str(tmp_path))
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        agent=agent,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        enable_history=True,
    )
    with patch.object(OrchestratorSessionBootstrap, "_build_pool") as build_pool:
        OrchestratorSessionBootstrap.attach(session=session)
        build_pool.assert_not_called()
    await session.rename_session(session_name="injected")
    await session._prepare_herdr_capture_inputs(interactive=True)
    events = [event async for event in session.invoke(text="hello")]
    assert any(event.content == "injected answer" for event in events)
    assert session._agent_is_injected
    assert session._standard_orchestrator_attachment is None
    assert session._herdr_capture is None
    assert not session._herdr_capture_eligible()


@pytest.mark.parametrize("headless", [False, True])
async def test_standard_origin_interactive_gate(tmp_path: Path, headless: bool) -> None:
    """Successful headless provenance is legitimate but never native-restore eligible."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
        OrchestratorSessionBootstrap.attach(session=session, headless=headless)
    assert session._standard_orchestrator_attachment is not None
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=not headless)
    assert (session._herdr_capture is None) is headless
