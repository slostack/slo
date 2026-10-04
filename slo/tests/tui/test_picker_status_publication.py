"""Offline picker status projection from the existing auth dismissal contract."""

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.tui.app import SloTUI
from src.tui.model_catalog import ModelSuggestionProjection, model_suggestion_entries


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
async def test_verified_dismissal_paints_status_before_long_label(size: tuple[int, int]) -> None:
    """Auth success reaches real cached rows and literal paint without keypress I/O."""
    ModelCatalogService.reset()
    ModelSuggestionProjection.reset()
    snapshot = SeedModelCatalog.load()
    route = "openrouter:vendor/model"
    entry = snapshot.entries["kimi-k3"].model_copy(
        update={
            "model_name": route,
            "provider": ProviderName.OPENROUTER,
            "display_name": "[bold]" + "long label " * 100,
        }
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}, "generation": 980})
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-picker-key"
    )
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[])),
        workdir=Path.cwd(),
        session_id="picker-status",
        enable_history=False,
    )
    app = SloTUI(session=session)
    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(CredentialResolver, "resolve", return_value=credential),
        patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("network")),
        patch.object(httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("network")),
    ):
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            app._on_auth_dismissed(value=credential)
            assert app._input is not None
            app._input.load_text("/model openrouter:")
            await pilot.pause()
            with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("typing I/O")):
                app._refresh_slash_suggestions()
                rows = model_suggestion_entries(active_model_name=session.active_model_name)
                assert next(row for row in rows if row.model_name == route).status_summary.startswith(
                    "key verified"
                )
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "key verified" in painted
                assert "context " in (app._slash_suggestion_state.rows[0].detail or "")
                assert "synthetic-picker-key" not in painted
                assert session.active_model_name != route
                app._input.load_text("/model ")
                await pilot.pause()
                await pilot.press("down", "down")
                selected = app._slash_suggestion_state.highlighted_row
                assert selected is not None
                published = snapshot.model_copy(update={"generation": 981})
                with patch.object(ModelCatalogService, "load", return_value=published):
                    await pilot.pause()
                    highlighted = app._slash_suggestion_state.highlighted_row
                    assert highlighted is not None
                    assert highlighted.insert_text == selected.insert_text
                    assert all(
                        row.catalog_generation == 981
                        for row in model_suggestion_entries(active_model_name=session.active_model_name)
                    )
                blank = snapshot.model_copy(update={"entries": {}, "generation": 982})
                with (
                    patch.object(ModelCatalogService, "load", return_value=blank),
                    patch.object(CredentialResolver, "resolve", return_value=credential),
                ):
                    ModelSuggestionProjection.refresh_authentication(verified_credential=credential)
                    await pilot.pause()
                    assert app._slash_suggestion_state.highlighted_row is None
                    painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "No models match" in painted
    ModelSuggestionProjection.reset()
    ModelCatalogService.reset()


@pytest.mark.parametrize("effective", [None, "rotated"])
def test_auth_dismissal_does_not_verify_missing_or_rotated_key(effective: str | None) -> None:
    """A delayed dismissal cannot lend verification to another effective credential."""
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-original"
    )
    current = credential.model_copy(update={"access_token": effective}) if effective else None
    with patch.object(CredentialResolver, "resolve", return_value=current):
        ModelSuggestionProjection.refresh_authentication(verified_credential=credential)
    assert "key verified" not in ModelSuggestionProjection._statuses[ProviderName.OPENROUTER]
    assert ModelSuggestionProjection._statuses[ProviderName.OPENROUTER] == (
        "credential changed; refresh required" if effective else "requires /auth"
    )
