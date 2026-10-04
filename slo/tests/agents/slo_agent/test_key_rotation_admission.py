"""Fail-closed admission capture checks; composed wire proof lives in integration."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from tests.agents.slo_agent.test_catalog_generation import _prepared_openrouter_snapshot


@pytest.mark.parametrize("transition", ["missing", "removed", "rotated"])
async def test_changed_capture_during_catalog_admission_preserves_session(
    tmp_path: Path, transition: str
) -> None:
    """Missing or changed credentials cannot partially adopt a new run snapshot."""
    snapshot = _prepared_openrouter_snapshot(generation=4)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="local-a"
    )
    initial = None if transition == "missing" else credential
    current = credential.model_copy(update={"access_token": "local-b"}) if transition == "rotated" else None
    with patch.object(SloAgentSession, "_load_plugins"):
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path, model_name="openrouter:vendor/model", enable_history=False
            ),
            catalog_snapshot=snapshot,
        )
    with (
        patch.object(CredentialResolver, "resolve", side_effect=[initial, current]),
        patch.object(ModelCatalogService, "prepare_models", new=AsyncMock(return_value=snapshot)),
    ):
        with pytest.raises(ModelPreparationRequiredError, match="credential changed"):
            await session._prepare_run_snapshot()
    assert session.catalog_snapshot is snapshot
    assert session._admitted_run_snapshot is None
    assert session._admitted_openrouter_credential is None


class TestOpenRouterCredentialSerializationLifetime:
    """Exercise actual session-owned history writes after OpenRouter admission."""

    @staticmethod
    def _credential(*, access_token: str) -> CredentialDAO:
        """Build one synthetic OpenRouter credential.

        Args:
            access_token (str): Test-only credential token.

        Returns:
            CredentialDAO: OpenRouter API-key credential.
        """
        return CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=access_token,
        )

    @staticmethod
    def _build_session(*, tmp_path: Path) -> SloAgentSession:
        """Build a prepared lazy session with an actual flat history writer.

        Args:
            tmp_path (Path): Resolved pytest-owned root.

        Returns:
            SloAgentSession: Prepared session with real history persistence.
        """
        snapshot = _prepared_openrouter_snapshot(generation=4)
        history_root = (tmp_path / "history").resolve()
        assert history_root.is_relative_to(tmp_path.resolve())
        return SloAgentSession(
            session_id="serialization-lifetime",
            workdir=tmp_path,
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="openrouter:vendor/model",
                enable_history=True,
            ),
            catalog_snapshot=snapshot,
            history_store=FilesystemSessionHistoryStore(root=history_root),
        )

    @staticmethod
    async def _append_terminal_history(*, session: SloAgentSession, content: str) -> None:
        """Write actual opening and terminal history through the session owner.

        Args:
            session (SloAgentSession): Session owning the real writer.
            content (str): Synthetic terminal payload.
        """
        await session._ensure_history_session()
        await session._persist_attempt_opening_events(
            plan=session._build_initial_attempt_plan(text="ordinary prompt"),
            turn_id="turn-1",
        )
        await session._append_history_event(
            event=session._build_event(
                kind="run_completed",
                turn_id="turn-1",
                payload=SessionHistoryEventPayloadDAO(content=content),
            )
        )

    @pytest.mark.asyncio
    async def test_history_terminal_write_when_admitted_key_rotates_after_lazy_build_redacts_admitted_key(
        self,
        tmp_path: Path,
    ) -> None:
        """A post-build rotation must not leave the admitted key in real session history."""
        credential_a = self._credential(access_token="F86_SESSION_ADMITTED_A")
        credential_b = self._credential(access_token="F86_SESSION_EFFECTIVE_B")
        session = self._build_session(tmp_path=tmp_path)

        with (
            patch.object(CredentialResolver, "resolve", return_value=credential_a),
            patch.object(
                ModelCatalogService, "prepare_models", new=AsyncMock(return_value=session.catalog_snapshot)
            ),
            patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
            patch.object(
                session,
                "_build_agent",
                return_value=SloAgent(
                    llm=FauxChatModel(responses=[]),
                    cwd=str(tmp_path),
                    tools=[],
                ),
            ),
        ):
            async with session._session_run_scope():
                await session._ensure_agent_ready()
                assert CredentialResolver._build_credential.get() is credential_a
                with patch.object(CredentialResolver, "resolve", return_value=credential_b):
                    await self._append_terminal_history(session=session, content=credential_a.access_token)
            assert CredentialResolver._build_credential.get() is None

        history_root = session.history_root
        assert history_root is not None
        events_path = history_root / session.session_id / "events.jsonl"
        persisted = events_path.read_text(encoding="utf-8")
        assert "ordinary prompt" in persisted
        assert "[REDACTED]" in persisted
        assert credential_a.access_token not in persisted
        assert credential_b.access_token not in persisted

    @pytest.mark.asyncio
    async def test_history_terminal_write_when_reused_agent_admits_next_credential_redacts_both_values(
        self,
        tmp_path: Path,
    ) -> None:
        """A cached agent's next run must replace A with B without retaining A task state."""
        credential_a = self._credential(access_token="F86_SESSION_REUSE_A")
        credential_b = self._credential(access_token="F86_SESSION_REUSE_B")
        session = self._build_session(tmp_path=tmp_path)
        build_count = 0

        def build_agent() -> SloAgent:
            """Build a test-only lazy agent and count construction.

            Returns:
                SloAgent: Agent with no scripted provider responses.
            """
            nonlocal build_count
            build_count += 1
            return SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path), tools=[])

        with (
            patch.object(CredentialResolver, "resolve", side_effect=[credential_a, credential_a]),
            patch.object(
                ModelCatalogService, "prepare_models", new=AsyncMock(return_value=session.catalog_snapshot)
            ),
            patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
            patch.object(session, "_build_agent", side_effect=build_agent),
        ):
            async with session._session_run_scope():
                await session._ensure_agent_ready()
            assert CredentialResolver._build_credential.get() is None
            with patch.object(CredentialResolver, "resolve", side_effect=[credential_b, credential_b]):
                async with session._session_run_scope():
                    await session._ensure_agent_ready()
                    assert CredentialResolver._build_credential.get() is credential_b
                    await self._append_terminal_history(session=session, content=credential_b.access_token)

        history_root = session.history_root
        assert history_root is not None
        events_path = history_root / session.session_id / "events.jsonl"
        persisted = events_path.read_text(encoding="utf-8")
        assert build_count == 2
        assert "ordinary prompt" in persisted
        assert "[REDACTED]" in persisted
        assert credential_b.access_token not in persisted
        assert CredentialResolver._build_credential.get() is None

    @pytest.mark.asyncio
    async def test_history_terminal_write_when_reused_agent_keeps_admitted_key_and_task_state_resets_on_cancellation(
        self,
        tmp_path: Path,
    ) -> None:
        """A same-key second run reuses one agent and resets its operation capture on cancellation."""
        credential = self._credential(access_token="F86_SESSION_REUSED_B")
        session = self._build_session(tmp_path=tmp_path)
        build_count = 0

        def build_agent() -> SloAgent:
            """Build a counted test-only agent for the first admitted operation.

            Returns:
                SloAgent: Agent with no scripted provider responses.
            """
            nonlocal build_count
            build_count += 1
            return SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path), tools=[])

        with (
            patch.object(CredentialResolver, "resolve", return_value=credential),
            patch.object(
                ModelCatalogService, "prepare_models", new=AsyncMock(return_value=session.catalog_snapshot)
            ),
            patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
            patch.object(session, "_build_agent", side_effect=build_agent),
        ):
            async with session._session_run_scope():
                await session._ensure_agent_ready()
            assert CredentialResolver._build_credential.get() is None
            with pytest.raises(asyncio.CancelledError):
                async with session._session_run_scope():
                    await session._ensure_agent_ready()
                    assert CredentialResolver._build_credential.get() is credential
                    await self._append_terminal_history(session=session, content=credential.access_token)
                    raise asyncio.CancelledError()

        history_root = session.history_root
        assert history_root is not None
        persisted = (history_root / session.session_id / "events.jsonl").read_text(encoding="utf-8")
        assert build_count == 1
        assert "ordinary prompt" in persisted
        assert "[REDACTED]" in persisted
        assert credential.access_token not in persisted
        assert CredentialResolver._build_credential.get() is None
        assert session._is_running is False

    @pytest.mark.asyncio
    async def test_history_terminal_write_when_resolver_fails_after_lazy_build_redacts_admitted_key(
        self,
        tmp_path: Path,
    ) -> None:
        """A resolver fault after admission must retain the session's redaction capture."""
        credential_a = self._credential(access_token="F86_SESSION_FAILURE_A")
        session = self._build_session(tmp_path=tmp_path)

        def fail_resolution(*, provider: ProviderName) -> CredentialDAO:
            """Raise the controlled post-admission resolver fault.

            Args:
                provider (ProviderName): Requested provider.

            Raises:
                OSError: Always, without inspecting a credential source.
            """
            del provider
            raise OSError("controlled resolver failure")

        with (
            patch.object(CredentialResolver, "resolve", return_value=credential_a),
            patch.object(
                ModelCatalogService, "prepare_models", new=AsyncMock(return_value=session.catalog_snapshot)
            ),
            patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
            patch.object(
                session,
                "_build_agent",
                return_value=SloAgent(
                    llm=FauxChatModel(responses=[]),
                    cwd=str(tmp_path),
                    tools=[],
                ),
            ),
        ):
            async with session._session_run_scope():
                await session._ensure_agent_ready()
                with patch.object(CredentialResolver, "resolve", side_effect=fail_resolution):
                    await self._append_terminal_history(session=session, content=credential_a.access_token)

        history_root = session.history_root
        assert history_root is not None
        events_path = history_root / session.session_id / "events.jsonl"
        persisted = events_path.read_text(encoding="utf-8")
        assert "ordinary prompt" in persisted
        assert "[REDACTED]" in persisted
        assert credential_a.access_token not in persisted
