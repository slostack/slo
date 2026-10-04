"""Mounted picker follows public lifecycle revision without entry publication."""

from pathlib import Path
from unittest.mock import patch

import pytest

from datetime import datetime, timezone

from src.agents.model_catalog.dao import CatalogLifecycleStatusDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.tui.app import SloTUI
from src.tui.model_catalog import model_suggestion_entries


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
async def test_equal_entries_status_revision_paints(size: tuple[int, int]) -> None:
    """A real no-key refresh invalidates existing rows at both supported viewports."""
    ModelCatalogService.reset()
    ModelCatalogService._publish_status(
        status=CatalogLifecycleStatusDAO(
            state="historical",
            key_verified_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            catalog_checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    snapshot = SeedModelCatalog.load()
    route = "openrouter:vendor/model"
    entry = snapshot.entries["kimi-k3"].model_copy(
        update={
            "model_name": route,
            "provider": ProviderName.OPENROUTER,
            "display_name": "[bold]literal[/bold]",
        }
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}, "generation": 999})
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[])),
        workdir=Path.cwd(),
        session_id="status-revision",
        enable_history=False,
    )
    app = SloTUI(session=session)
    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(CredentialResolver, "resolve", return_value=object()),
    ):
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("/model openrouter:")
            await pilot.pause()
            before = next(
                row
                for row in model_suggestion_entries(active_model_name=session.active_model_name)
                if row.model_name == route
            )
            assert before.status_summary == "cached history; current key not checked"
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "current key not checked" in painted
            with patch.object(CredentialResolver, "resolve_with_source", return_value=None):
                await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER)
            with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("typing I/O")):
                app._refresh_slash_suggestions()
                await pilot.pause()
                after = next(
                    row
                    for row in model_suggestion_entries(active_model_name=session.active_model_name)
                    if row.model_name == route
                )
                assert after is not before
                assert after.status_summary == "requires /auth"
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "requires /auth" in painted
                assert session.active_model_name != route
    ModelCatalogService.reset()
