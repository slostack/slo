"""G8 regressions through the real catalog projection and menu."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from src.auth.credential_dao import ProviderName

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_resolver import CredentialResolver
from src.tui.model_catalog import model_suggestion_entries
from src.tui.slash_command_registry import SlashCommandRegistry
from src.tui.slash_suggestion_engine import SlashSuggestionEngine
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu


def test_projection_and_input_do_not_resolve_credentials() -> None:
    """Repeated input evaluation must not touch the private resolver."""
    snapshot = SeedModelCatalog.load()
    engine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("secret I/O")),
    ):
        rows = model_suggestion_entries(active_model_name="kimi-k3")
        assert rows
        state = engine.evaluate(buffer_text="  /model kimi-k3", active_model_name="kimi-k3")
        assert state.replacement_start == 9
        assert state.replacement_end == 16
        empty = engine.evaluate(buffer_text="/model no-such-model", active_model_name="kimi-k3")
        assert empty.visible and not empty.rows


class MenuApp(App[None]):
    """Mount only the real menu without session or persistence side effects."""

    def compose(self) -> ComposeResult:
        """Yield the production renderer."""
        yield SlashSuggestionMenu()


async def test_menu_windows_literal_rows_and_retains_highlight_on_resize() -> None:
    """One thousand real projected rows feed a small literal scrolling viewport."""
    snapshot = SeedModelCatalog.load()
    template = snapshot.entries["kimi-k3"]
    entries = {
        f"model-{index:04}": template.model_copy(
            update={
                "model_name": f"model-{index:04}",
                "display_name": "[bold]literal[/bold]",
            }
        )
        for index in range(1000)
    }
    snapshot = snapshot.model_copy(update={"entries": entries, "generation": 901})
    engine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("secret I/O")),
    ):
        state = engine.evaluate(buffer_text="/model literal", active_model_name="model-0000")
    assert len(state.rows) == 25 and state.total_matches == 1000
    app = MenuApp()
    async with app.run_test(size=(80, 24)) as pilot:
        menu = app.query_one(SlashSuggestionMenu)
        menu.update_state(state=state)
        await pilot.pause()
        assert menu.size.height <= 26
        for _ in range(20):
            state = state.with_highlight_delta(delta=1)
        menu.update_state(state=state)
        await pilot.resize_terminal(width=60, height=15)
        await pilot.pause()
        assert menu.size.height <= 13
        assert menu.window_start > 0
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "model-0020" in painted
        assert "model-0000" not in painted
        assert "context " in painted


def test_empty_order_cache_and_revision() -> None:
    """Active, recent and first-class rows precede lexical discoveries; revision invalidates."""
    from src.tui.model_catalog import ModelSuggestionProjection

    snapshot = SeedModelCatalog.load()
    engine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    engine.record_selection(model_name="kimi-for-coding")
    with patch.object(ModelCatalogService, "load", return_value=snapshot):
        with patch.object(CredentialResolver, "resolve", return_value=None) as resolver:
            ModelSuggestionProjection.refresh_authentication()
            assert resolver.call_count == len(ProviderName)
        with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("typing I/O")):
            first = model_suggestion_entries(active_model_name="kimi-k3")
            second = model_suggestion_entries(active_model_name="kimi-k3")
            assert first[0] is second[0]
            state = engine.evaluate(buffer_text="/model ", active_model_name="kimi-k3")
            assert [row.insert_text for row in state.rows[:2]] == ["kimi-k3", "kimi-for-coding"]
            assert "requires /auth" in (state.rows[0].detail or "")
        with patch.object(CredentialResolver, "resolve", return_value=object()):
            ModelSuggestionProjection.refresh_authentication()
        assert model_suggestion_entries(active_model_name="kimi-k3")[0] is not first[0]


async def test_app_paints_real_projection_inserts_and_handles_empty_search() -> None:
    """Real app selection is literal and exact; typing cannot reach credentials or HTTP."""
    import httpx
    from pathlib import Path
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.tui.app import SloTUI

    snapshot = SeedModelCatalog.load()
    template = snapshot.entries["kimi-k3"]
    snapshot = snapshot.model_copy(
        update={
            "entries": {
                **snapshot.entries,
                **{
                    f"model-{index:04}": template.model_copy(
                        update={
                            "model_name": f"model-{index:04}",
                            "display_name": "[bold]literal[/bold]",
                        }
                    )
                    for index in range(1000)
                },
            },
            "generation": 902,
        }
    )
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[])),
        workdir=Path.cwd(),
        session_id="picker-g8",
        enable_history=False,
    )
    app = SloTUI(session=session)
    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("network")),
        patch.object(httpx.Client, "send", side_effect=AssertionError("network")),
    ):
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("secret I/O")):
                assert app._input is not None
                app._input.load_text("  /model literal")
                await pilot.pause()
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "context " in painted
                await pilot.press("down", "down")
                await pilot.resize_terminal(width=60, height=15)
                await pilot.pause()
                assert app._slash_suggestion_state.highlighted_index == 2
                await pilot.press("tab")
                assert app._input.text == "  /model model-0002"
                app._input.load_text("/model missing")
                await pilot.pause()
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "No models match" in painted
                app._input.load_text("")
                await pilot.pause()
                await app._dispatch_slash_command(line="/model")
                await pilot.pause()
                from src.tui.slash_router import SlashRouter

                result = await SlashRouter.dispatch(line="/model", session=session)
                assert len((result.rendered or "").splitlines()) <= 7
