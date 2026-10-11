"""Focused admission and catalog-generation tests for OpenRouter sessions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.model_catalog.dao import ModelCapabilitiesDAO, ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import ProviderName


def _prepared_openrouter_snapshot(*, generation: int) -> ModelCatalogSnapshotDAO:
    """Build one synthetic, eligible OpenRouter generation without discovery.

    Args:
        generation (int): Immutable catalog generation to place in the snapshot.

    Returns:
        ModelCatalogSnapshotDAO: Synthetic exact-route catalog generation.
    """
    seed: ModelCatalogSnapshotDAO = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    entry = template.model_copy(
        update={
            "model_name": "openrouter:vendor/model",
            "api_model_name": "vendor/model",
            "provider": ProviderName.OPENROUTER,
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
            ),
        }
    )
    return seed.model_copy(
        update={
            "entries": {**seed.entries, entry.model_name: entry},
            "generation": generation,
        }
    )


class TestOpenRouterSessionSelection:
    """Async session selection and refresh boundaries."""

    @pytest.mark.asyncio
    async def test_prepare_model_selection_when_catalog_rejects_route_preserves_current_state(
        self, tmp_path: Path
    ) -> None:
        """An unavailable selection does not partially mutate the active route or pool."""
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        session = SloAgentSession.build(config=config)
        original_model_name: str = session.active_model_name

        with (
            patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=MagicMock()),
            patch.object(
                ModelCatalogService,
                "prepare_models",
                new=AsyncMock(side_effect=ModelPreparationRequiredError("missing")),
            ),
        ):
            result: str = await session.prepare_model_selection(model_name="openrouter:vendor/missing")

        assert result == "model 'openrouter:vendor/missing' is unavailable; run /model refresh or /auth"
        assert session.active_model_name == original_model_name
        assert session._config is not None
        assert session._config.model_pool_dao is None

    @pytest.mark.asyncio
    async def test_prepare_model_selection_when_missing_credential_preserves_current_state(
        self, tmp_path: Path
    ) -> None:
        """A real missing provider credential rejects selection before catalog preparation."""
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        session = SloAgentSession.build(config=config)

        with patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=None):
            result: str = await session.prepare_model_selection(model_name="openrouter:vendor/model")

        assert (
            result == "No OpenRouter credentials found. Run /auth in the TUI or set SLO_OPENROUTER_API_KEY."
        )
        assert session.active_model_name == "gpt-5.4"

    @pytest.mark.asyncio
    async def test_prepare_model_selection_when_catalog_accepts_route_commits_after_admission(
        self, tmp_path: Path
    ) -> None:
        """A prepared route clears any pool only after the exact route admits successfully."""
        snapshot = _prepared_openrouter_snapshot(generation=5)
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        session = SloAgentSession.build(config=config)

        with (
            patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=MagicMock()),
            patch.object(ModelCatalogService, "prepare_models", new=AsyncMock(return_value=snapshot)),
            patch("src.agents.slo_agent.sessions.service.UserPreferencesStore.upsert"),
        ):
            result: str = await session.prepare_model_selection(model_name="openrouter:vendor/model")

        assert result == "active model switched to openrouter:vendor/model. Preference saved."
        assert session.active_model_name == "openrouter:vendor/model"
        assert session.catalog_snapshot == snapshot

    @pytest.mark.asyncio
    async def test_prepare_model_selection_when_prompt_starts_during_preparation_preserves_current_state(
        self, tmp_path: Path
    ) -> None:
        """The post-preparation prompt-lock check prevents a stale selection commit."""
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        session = SloAgentSession.build(config=config)
        snapshot = _prepared_openrouter_snapshot(generation=5)

        async def prepare_with_race(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
            """Simulate a prompt admission completing while selection awaits catalog work."""
            session._is_running = True
            return snapshot

        with (
            patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=MagicMock()),
            patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_with_race),
        ):
            result: str = await session.prepare_model_selection(model_name="openrouter:vendor/model")

        assert result == "cannot switch models while a prompt is in flight"
        assert session.active_model_name == "gpt-5.4"

    @pytest.mark.asyncio
    async def test_refresh_model_catalog_when_publish_succeeds_adopts_only_future_snapshot(
        self, tmp_path: Path
    ) -> None:
        """Manual refresh delegates to catalog service and stores its newest read view for later admission."""
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        session = SloAgentSession.build(config=config)
        refreshed_snapshot = _prepared_openrouter_snapshot(generation=9)
        result = MagicMock(status="refreshed", safe_message="OpenRouter catalog refreshed.")

        with (
            patch.object(ModelCatalogService, "refresh", new=AsyncMock(return_value=result)) as refresh,
            patch.object(ModelCatalogService, "load", return_value=refreshed_snapshot) as load,
        ):
            message: str = await session.refresh_model_catalog()

        refresh.assert_awaited_once_with(provider=ProviderName.OPENROUTER, force=True)
        load.assert_called_once_with()
        assert message.startswith("OpenRouter catalog refreshed.")
        assert "models; last complete check:" in message
        assert session.catalog_snapshot == refreshed_snapshot


class TestOpenRouterSessionPreparation:
    """Strict direct-route preparation and immutable admission boundaries."""

    def test_build_when_openrouter_route_is_unprepared_raises(self, tmp_path: Path) -> None:
        """Default synchronous construction refuses unknown qualified routes."""
        config = SessionConfigDAO(
            workdir=tmp_path, model_name="openrouter:vendor/missing", enable_history=False
        )

        with pytest.raises(ModelPreparationRequiredError, match="Catalog preparation required"):
            SloAgentSession.build(config=config)

    @pytest.mark.asyncio
    async def test_prepare_when_openrouter_route_is_configured_uses_catalog_gateway(
        self, tmp_path: Path
    ) -> None:
        """The session-owned async gateway prepares exact configured routes before build."""
        config = SessionConfigDAO(
            workdir=tmp_path, model_name="openrouter:vendor/model", enable_history=False
        )
        snapshot = _prepared_openrouter_snapshot(generation=4)

        with patch.object(
            ModelCatalogService,
            "prepare_models",
            new=AsyncMock(return_value=snapshot),
        ) as prepare_models:
            session = await SloAgentSession.prepare(config=config)

        prepare_models.assert_awaited_once_with(model_names=("openrouter:vendor/model",))
        assert session.catalog_snapshot == snapshot

    @pytest.mark.asyncio
    async def test_invoke_when_future_generation_publishes_keeps_admitted_snapshot(
        self, tmp_path: Path
    ) -> None:
        """A later publication cannot replace the generation held by an admitted prompt."""
        config = SessionConfigDAO(
            workdir=tmp_path, model_name="openrouter:vendor/model", enable_history=False
        )
        admitted_snapshot = _prepared_openrouter_snapshot(generation=4)
        future_snapshot = _prepared_openrouter_snapshot(generation=5)
        built_snapshots: list[ModelCatalogSnapshotDAO | None] = []

        class _Agent:
            """Minimal session-agent fixture that exposes only the build boundary."""

            last_usage_totals = None
            usage_capture_version = 0
            llm = None

        def build_agent() -> _Agent:
            """Capture the snapshot passed to the actual lazy agent-build boundary."""
            built_snapshots.append(session.catalog_snapshot)
            return _Agent()

        with patch.object(
            ModelCatalogService,
            "prepare_models",
            new=AsyncMock(return_value=admitted_snapshot),
        ):
            session = await SloAgentSession.prepare(config=config)
            session._admit_run_snapshot()
            ModelCatalogService._snapshot = future_snapshot
            with (
                patch.object(session, "_build_agent", side_effect=build_agent),
                patch.object(session, "_refresh_oauth_credential_if_needed", new=AsyncMock()),
            ):
                await session._ensure_agent_ready()

        assert built_snapshots == [admitted_snapshot]
