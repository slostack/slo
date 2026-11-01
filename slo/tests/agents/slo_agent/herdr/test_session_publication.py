"""Session-owned private bootstrap provenance contracts."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize("custom", [False, True])
def test_standard_bootstrap_records_only_pristine_policy(tmp_path: Path, custom: bool) -> None:
    """Matching standard text cannot certify caller-supplied policy."""
    from src.agents.slo_agent.orchestrator.spawn_tool import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=False,
            system_prompt=DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT if custom else None,
        )
    )
    with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._herdr_policy_is_reproducible() is (not custom)
    if not custom:
        assert session._config is not None
        assert session._config.extra_tools is not None
        session._config = session._config.model_copy(
            update={"extra_tools": list(reversed(session._config.extra_tools))}
        )
        assert not session._herdr_policy_is_reproducible()


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_startup_commits_capture_only_after_success(tmp_path: Path, outcome: str) -> None:
    """Actual startup adoption captures effective reasoning; failed attempts retain policy."""
    import asyncio

    from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low")
    )
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    previous = session._herdr_capture
    generation = session._herdr_configuration_generation
    session._preparation_status = "pending"
    error = {"failure": RuntimeError("synthetic"), "cancel": asyncio.CancelledError()}.get(outcome)
    with (
        patch.object(
            ModelCatalogService, "prepare_models", return_value=ModelCatalogService.load(), side_effect=error
        ),
        patch("src.agents.slo_agent.sessions.service.clamp_reasoning_level", return_value="high"),
    ):
        if outcome == "success":
            await session.prepare_startup()
        else:
            with pytest.raises(
                asyncio.CancelledError if outcome == "cancel" else ModelPreparationRequiredError
            ):
                await session.prepare_startup()
    if outcome == "success":
        assert session._herdr_capture is not None
        assert session._herdr_capture.config.reasoning_level == "high"
        assert session._herdr_configuration_generation == generation + 1
        await session.prepare_startup()
        assert session._herdr_configuration_generation == generation + 1
    else:
        assert session._herdr_capture is previous
        assert session._herdr_configuration_generation == generation


async def test_usage_commit_publishes_latest_without_capture_or_io(
    tmp_path: Path, fake_herdr: object
) -> None:
    """The real reporter receives synchronous usage commits with the same private capture."""
    from src.agents.slo_agent.herdr.reporter import HerdrReporter
    from src.auth.credential_resolver import CredentialResolver

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="persisted")
    try:
        await session.start_external_reporting(interactive=True)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        previous = reporter._latest
        assert previous is not None
        with (
            patch.object(session, "_capture_herdr_restore", side_effect=AssertionError("recapture")),
            patch.object(Path, "resolve", side_effect=AssertionError("path I/O")),
            patch.object(CredentialResolver, "require", side_effect=AssertionError("credentials")),
            patch.object(session, "_build_agent", side_effect=AssertionError("model construction")),
            patch.object(reporter, "publish", wraps=reporter.publish) as publish,
        ):
            session.refresh_usage_snapshot()
        publish.assert_called_once()
        assert publish.call_args.kwargs["publication"].restore_capture is previous.restore_capture
        assert reporter._latest is not None
        assert reporter._latest.restore_capture is previous.restore_capture
        assert reporter._latest.configuration_generation == previous.configuration_generation
    finally:
        await session.close_external_reporting()


@pytest.mark.parametrize("commit", ["rename", "history", "startup", "bootstrap"])
async def test_actual_commit_publishes(tmp_path: Path, fake_herdr: object, commit: str) -> None:
    """Successful session gateways publish through the real reporter, not event payloads."""
    from src.agents.model_catalog.service import ModelCatalogService

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    try:
        await session.start_external_reporting(interactive=True)
        reporter = session._herdr_reporter
        with patch.object(reporter, "publish", wraps=reporter.publish) as publish:
            if commit == "rename":
                await session.rename_session(session_name="private label")
            elif commit == "history":
                await session._ensure_history_session()
            elif commit == "startup":
                session._preparation_status = "pending"
                with patch.object(
                    ModelCatalogService, "prepare_models", return_value=ModelCatalogService.load()
                ):
                    await session.prepare_startup()
            else:
                with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
                    OrchestratorSessionBootstrap.attach(session=session)
            assert publish.called
            publication = publish.call_args.kwargs["publication"]
            assert publication.restore_capture is session._herdr_capture
            assert publication.configuration_generation == session._herdr_configuration_generation
            assert "private label" not in publication.model_dump_json()
    finally:
        await session.close_external_reporting()


@pytest.mark.parametrize(
    "mutation", ["model", "reasoning", "workspace", "plugins", "history", "prompt", "pool"]
)
async def test_usage_withdraws_mutated_capture(tmp_path: Path, fake_herdr: object, mutation: str) -> None:
    """Unsupported edits revoke current eligibility rather than certifying a new policy."""
    from src.agents.slo_agent.herdr.reporter import HerdrReporter
    from tests.agents.slo_agent.herdr.test_session_capture import configured_pool

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", model_pool_dao=configured_pool())
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="existing")
    try:
        await session.start_external_reporting(interactive=True)
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        before = reporter._latest
        assert before is not None and before.restore_capture is not None
        if mutation == "model":
            config.model_name = "gpt-5.5"
        elif mutation == "reasoning":
            config.reasoning_level = "high"
        elif mutation == "workspace":
            config.workspace_file = tmp_path / "other.code-workspace"
        elif mutation == "plugins":
            config.plugin_paths.append(tmp_path / "other.py")
        elif mutation == "history":
            config.enable_history = False
        elif mutation == "prompt":
            config.append_system_prompt = "private override"
        else:
            assert config.model_pool_dao is not None
            config.model_pool_dao.entries[0].priority += 1
        with patch.object(Path, "resolve", side_effect=AssertionError("event I/O")):
            session.refresh_usage_snapshot()
            latest = reporter._latest
            assert latest is not None
            assert latest.restore_capture is None
            assert latest.configuration_generation == before.configuration_generation + 1
            session.refresh_usage_snapshot()
            assert reporter._latest is latest
        assert before.restore_capture is not None
    finally:
        await session.close_external_reporting()


async def test_activation_does_not_skip_explicit_workspace_persistence(
    tmp_path: Path, fake_herdr: object
) -> None:
    """Reading resume metadata must not mark ordinary ensure/update work completed."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", workspace_file=tmp_path / "explicit.code-workspace"
        )
    )
    store = session._history_store
    assert store is not None
    await store.ensure_session(
        session_id=session.session_id,
        workdir=tmp_path,
        model_name="gpt-5.4",
        workspace_file=tmp_path / "stored.code-workspace",
    )
    try:
        await session.start_external_reporting(interactive=True)
        with patch.object(store, "ensure_session", wraps=store.ensure_session) as ensure:
            await session.rename_session(session_name="resumed")
        ensure.assert_awaited_once()
        assert ensure.call_args.kwargs["workspace_file"] == tmp_path / "explicit.code-workspace"
        metadata = await store.read_metadata(session_id=session.session_id)
        # Existing stores intentionally preserve already-persisted workspace metadata.
        assert metadata.workspace_file == tmp_path / "stored.code-workspace"
        assert session._herdr_capture is not None
        assert session._herdr_capture.config.workspace_file == tmp_path / "explicit.code-workspace"
    finally:
        await session.close_external_reporting()


async def test_faux_submission_publishes_committed_usage(
    tmp_path: Path, fake_herdr: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config-backed execution reaches real reporter with numeric usage and frozen policy."""
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.herdr.reporter import HerdrReporter
    from src.auth.credential_resolver import CredentialResolver

    from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-publication-test"
    )
    monkeypatch.setattr(CredentialResolver, "resolve", classmethod(lambda cls, **kwargs: credential))
    faux = FauxChatModel(
        responses=[
            AIMessage(
                content="done",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )
        ]
    )
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=faux,
            supports_explicit_caching=False,
        ),
    ) as factory:
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        try:
            await session.start_external_reporting(interactive=True)
            reporter = session._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            async for _ in session.invoke(text="hello"):
                pass
            assert factory.call_count == 1
            assert not session._agent_is_injected
            assert session.refresh_usage_snapshot().session_totals.total_tokens == 15
            assert reporter._latest is not None
            assert reporter._latest.restore_capture is session._herdr_capture
            assert reporter._latest.restore_capture is not None
            assert reporter._latest.snapshot.tokens
            capture = session._herdr_capture
            generation = session._herdr_configuration_generation
            with (
                patch.object(
                    CredentialResolver, "require", side_effect=AssertionError("credentials")
                ) as credentials,
                patch.object(Path, "resolve", side_effect=AssertionError("path I/O")) as resolve,
                patch.object(
                    session, "_capture_herdr_restore", side_effect=AssertionError("recapture")
                ) as recapture,
            ):
                session.refresh_usage_snapshot()
                session.refresh_usage_snapshot()
                credentials.assert_not_called()
                resolve.assert_not_called()
                recapture.assert_not_called()
            await session.rename_session(session_name="new private name")
            assert session._herdr_capture is capture
            assert session._herdr_configuration_generation == generation
            assert factory.call_count == 1
        finally:
            await session.close_external_reporting()


async def test_bootstrap_preserves_exact_restore_identity(tmp_path: Path, fake_herdr: object) -> None:
    """Standard runtime additions are reproducible, so they cannot revoke equal policy."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    try:
        await session.start_external_reporting(interactive=True)
        capture = session._herdr_capture
        generation = session._herdr_configuration_generation
        with patch.object(OrchestratorSessionBootstrap, "_build_pool"):
            OrchestratorSessionBootstrap.attach(session=session)
        assert session._herdr_capture is capture
        assert session._herdr_configuration_generation == generation
    finally:
        await session.close_external_reporting()


async def test_general_attach_immediately_withdraws_capture(tmp_path: Path, fake_herdr: object) -> None:
    """A successful general attachment revokes before any later usage event."""
    from unittest.mock import MagicMock
    from src.agents.tools.echo import echo_tool

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="existing")
    try:
        await session.start_external_reporting(interactive=True)
        previous = session._herdr_capture
        generation = session._herdr_configuration_generation
        assert previous is not None
        session.attach_sub_agent_pool(pool=MagicMock(), spawn_tools=[echo_tool])
        assert session._herdr_capture is None
        assert session._herdr_configuration_generation == generation + 1
        reporter = session._herdr_reporter
        from src.agents.slo_agent.herdr.reporter import HerdrReporter

        assert isinstance(reporter, HerdrReporter)
        assert reporter._latest is not None
        assert reporter._latest.restore_capture is None
    finally:
        await session.close_external_reporting()


def test_changed_identity_during_bootstrap_cannot_certify(tmp_path: Path) -> None:
    """Permission is tied to the session identity checked before construction."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=False,
        )
    )

    def change_identity(*, session: SloAgentSession, owner_session_id: str) -> object:
        session._session_id = "changed"
        from unittest.mock import MagicMock

        return MagicMock()

    with patch.object(OrchestratorSessionBootstrap, "_build_pool", side_effect=change_identity):
        OrchestratorSessionBootstrap.attach(session=session)
    assert not session._herdr_policy_is_reproducible()
