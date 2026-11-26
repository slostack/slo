"""Real admitted session/history to delayed headless queue regression (108.3)."""

import asyncio
from uuid import UUID
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_dao import CredentialDAO
from src.cli.headless import HeadlessRunner
from tests.agents.slo_agent.test_key_rotation_admission import (
    TestOpenRouterCredentialSerializationLifetime as Fixture,
)


@pytest.mark.parametrize("cleanup", ["success", "error", "cancel"])
@pytest.mark.parametrize("kind", ["run_completed", "run_failed"])
@pytest.mark.parametrize("resolver_failure", [False, True])
async def test_terminal_after_stream_exit_retains_admitted_redaction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: StreamEventKind,
    resolver_failure: bool,
    cleanup: str,
) -> None:
    """Actual runner completion must persist a redacted ordinary terminal inbox item."""
    first = Fixture._credential(access_token="TERMINAL_ADMITTED_A")
    second = Fixture._credential(access_token="TERMINAL_EFFECTIVE_B")
    session = Fixture._build_session(tmp_path=tmp_path)
    assert session._config is not None
    root = (tmp_path / "channels").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    repository: ChannelRepository = ChannelRepository(db_path=root / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    target = await gateway.register_agent(
        session_id=UUID("44444444-4444-4444-4444-444444444444"), name="slo owner"
    )
    notifier = WorkflowNotifier(
        gateway=gateway,
        target_session_id=str(target.id),
        orchestrator_session_id=session.session_id,
        workflow_id="wf-terminal",
    )
    runner = HeadlessRunner(config=session._config, notify_session_id="owner", notifier=notifier)
    stream_exited = asyncio.Event()

    async def drain(*, session: object, prompt: str) -> None:
        """Use shipped session admission/lazy history in the real runner child task."""
        del session, prompt
        async with actual_session._session_run_scope():
            await actual_session._ensure_agent_ready()
            resolver.return_value = second
            if resolver_failure:
                resolver.side_effect = OSError("controlled resolver failure")
            await Fixture._append_terminal_history(session=actual_session, content=first.access_token)
            await runner._emit(
                AgentStreamEventDAO(kind=kind, content="ordinary terminal " + first.access_token)
            )
        assert CredentialResolver._build_credential.get() is None
        stream_exited.set()

    actual_session = session
    original_notify = runner._notify_terminal
    notified = asyncio.Event()

    async def notify() -> None:
        """Assert the child has exited before the actual notifier writes."""
        assert stream_exited.is_set()
        assert CredentialResolver._build_credential.get() is None
        await original_notify()
        notified.set()
        if cleanup == "error":
            raise RuntimeError("controlled cleanup failure")
        if cleanup == "cancel":
            await asyncio.Event().wait()

    with (
        patch.object(CredentialResolver, "resolve", return_value=first) as resolver,
        patch.object(
            ModelCatalogService, "prepare_models", new=AsyncMock(return_value=session.catalog_snapshot)
        ),
        patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
        patch.object(
            session,
            "_build_agent",
            return_value=SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path), tools=[]),
        ),
        patch.object(runner, "_prepare_session", new=AsyncMock(return_value=session)),
        patch.object(runner, "_drain_session_stream", new=drain),
        patch.object(runner, "_notify_terminal", new=notify),
        patch("src.cli.headless.HeadlessWatchdog"),
    ):
        task = asyncio.create_task(runner.invoke(prompt="ordinary prompt"))
        if cleanup == "cancel":
            await asyncio.wait_for(notified.wait(), timeout=5)
            task.cancel()
        if cleanup != "success":
            expected_error = asyncio.CancelledError if cleanup == "cancel" else RuntimeError
            with pytest.raises(expected_error):
                await task
        else:
            assert await task == (0 if kind == "run_completed" else 1)
    pending = await gateway.list_pending_inbound_messages(recipient_id=target.id)
    terminals = [row for row in pending if row.message_type == "prompt"]
    assert len(terminals) == 1
    assert "ordinary terminal [REDACTED]" in terminals[0].message_contents
    await gateway.close()
    persisted = capsys.readouterr().out
    artifacts = None
    assert "ordinary terminal" in persisted
    assert first.access_token not in persisted
    assert CredentialResolver._build_credential.get() is None
    assert getattr(runner, "_operation_credential", None) is None


async def test_concurrent_runners_keep_distinct_admitted_captures(tmp_path: Path) -> None:
    """Concurrent session tasks hand off only their own capture to delayed notification."""
    from contextvars import ContextVar

    current: ContextVar[CredentialDAO | None] = ContextVar("test_effective_credential", default=None)
    both_admitted = asyncio.Event()
    admitted: list[str] = []

    async def run_one(name: str) -> None:
        """Admit through a real session and notify only after both scopes exit."""
        root = (tmp_path / name).resolve()
        assert root.is_relative_to(tmp_path.resolve())
        root.mkdir()
        credential = Fixture._credential(access_token=f"CONCURRENT_{name}")
        current.set(credential)
        session = Fixture._build_session(tmp_path=root)
        assert session._config is not None
        repository: ChannelRepository = ChannelRepository(db_path=root / "channels.db")
        await repository.open()
        gateway: ChannelGateway = ChannelGateway(repository=repository)
        target = await gateway.register_agent(
            session_id=UUID("55555555-5555-5555-5555-555555555555"), name="slo owner"
        )
        runner = HeadlessRunner(config=session._config)
        runner._notifier = WorkflowNotifier(
            gateway=gateway,
            target_session_id=str(target.id),
            orchestrator_session_id=name,
            workflow_id="wf-isolation",
        )
        with patch.object(session, "_prepare_run_snapshot", wraps=session._prepare_run_snapshot):
            async with session._session_run_scope():
                await runner._emit(AgentStreamEventDAO(kind="run_completed", content=credential.access_token))
        admitted.append(name)
        if len(admitted) == 2:
            both_admitted.set()
        await both_admitted.wait()
        current.set(None)
        assert CredentialResolver.operation_credential() is None
        await runner._notify_terminal()
        assert CredentialResolver.operation_credential() is None
        messages = await gateway.list_pending_inbound_messages(recipient_id=target.id)
        assert len(messages) == 1 and "[REDACTED]" in messages[0].message_contents
        assert credential.access_token not in messages[0].model_dump_json()
        await gateway.close()
        runner._operation_credential = None

    with (
        patch.object(CredentialResolver, "resolve", side_effect=lambda **kwargs: current.get()),
        patch.object(
            ModelCatalogService,
            "prepare_models",
            new=AsyncMock(return_value=Fixture._build_session(tmp_path=tmp_path).catalog_snapshot),
        ),
    ):
        await asyncio.gather(run_one("A"), run_one("B"))
