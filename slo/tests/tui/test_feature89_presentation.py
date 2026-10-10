"""Feature89 presentation reads pinned policy and lifecycle-only auth evidence."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import httpx

from tests.agents.model_catalog.test_feature89_jev_lifecycle import NOW, ROUTE, jev_transport
from tests.integration.test_openrouter_full_flow import isolated_catalog
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_store import CredentialStore
from src.auth.credential_resolver import CredentialResolver

_REAL_RESOLVE = CredentialResolver.resolve


@pytest.fixture(autouse=True)
def real_presentation_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the TUI-wide auth fake so synthetic stores govern admission and paint."""
    monkeypatch.setattr(CredentialResolver, "resolve", _REAL_RESOLVE)


from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO, ReasoningLevel
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.model_catalog import ModelSuggestionProjection
from src.tui.slash_router import SlashRouter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize(
    "name,effort",
    [
        ("gpt-6-luna", "none (disabled)"),
        ("gpt-6-sol", "none (disabled)"),
        ("gpt-6.1-sol", "low (reasoning required)"),
    ],
)
async def test_reasoning_off_reports_effective_policy(
    isolated_slo_home: Path, name: str, effort: str
) -> None:
    """Public router state explains provider semantics without changing canonical off."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home, model_name=name, reasoning_level="off", enable_history=False
        )
    )
    result = await SlashRouter.dispatch(line="/reasoning", session=session)
    assert result.rendered is not None
    assert "reasoning: off" in result.rendered
    assert f"effective provider effort: {effort}" in result.rendered
    for command in ("/reasoning off", "/reasoning medium", "/reasoning off"):
        result = await SlashRouter.dispatch(line=command, session=session)
        assert result.rendered is not None
        if command.endswith("off"):
            assert f"effective provider effort: {effort}" in result.rendered


@pytest.mark.parametrize("token,expected", [("on", "medium"), ("max", "max")])
async def test_reasoning_alias_uses_session_view(isolated_slo_home: Path, token: str, expected: str) -> None:
    """Alias resolution and mutation must not consult a newly published global view."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home, model_name="gpt-6-luna", reasoning_level="off", enable_history=False
        )
    )
    session._catalog_snapshot = SeedModelCatalog.load()
    with patch(
        "src.agents.model_catalog.service.ModelCatalogService.load", side_effect=AssertionError("global")
    ):
        result = await SlashRouter.dispatch(line=f"/reasoning {token}", session=session)
    assert session.active_reasoning_level == expected
    assert result.refresh_title is True


@pytest.mark.parametrize("size", [(60, 20), (120, 40)])
@pytest.mark.parametrize(
    "name,effort",
    [
        ("gpt-6-luna", "effort none"),
        ("gpt-6.1-sol", "effort low"),
        (ROUTE, "no provider-native reasoning extras"),
    ],
)
@pytest.mark.parametrize("global_change", ["removed", "controls"])
async def test_startup_uses_admitted_snapshot_across_global_publication(
    isolated_slo_home: Path,
    size: tuple[int, int],
    name: str,
    effort: str,
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    global_change: str,
) -> None:
    """Mounted startup resolves A and paints explicit none with no resolver-global read."""
    from src.tui.app import SloTUI
    from src.agents.reasoning_capabilities import resolve_reasoning_config
    from src.auth.credential_store import CredentialStore
    from tests.tui.authentication._painted_output import wait_until_painted

    store = isolated_catalog
    assert store.path.resolve().is_relative_to(isolated_slo_home.parent.resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-startup"
        )
    )
    pinned_snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    assert len(jev_transport) == 2
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name=name,
            reasoning_level="off",
            enable_history=True,
            history_root=isolated_slo_home / "history",
        ),
        catalog_snapshot=pinned_snapshot,
    )

    def resolve(
        *,
        model_name: str,
        requested_level: ReasoningLevel,
        snapshot: ModelCatalogSnapshotDAO | None = None,
    ) -> ResolvedReasoningConfigDAO:
        """Delegate while forbidding an unpinned startup lookup."""
        assert snapshot is pinned_snapshot
        with patch(
            "src.agents.model_catalog.service.ModelCatalogService.load", side_effect=AssertionError("global")
        ):
            return resolve_reasoning_config(
                model_name=model_name, requested_level=requested_level, snapshot=snapshot
            )

    entered, release = asyncio.Event(), asyncio.Event()
    original_eligibility = session.should_show_startup_notice

    async def eligibility() -> bool:
        """Hold the actual eligibility await until another generation is published."""
        entered.set()
        await release.wait()
        return await original_eligibility()

    async def publish() -> None:
        """Publish differing global policy while the startup eligibility call waits."""
        await entered.wait()
        entry = pinned_snapshot.entries[name]
        profile = entry.reasoning_profile.model_copy(
            update={"provider_effort_map": {**entry.reasoning_profile.provider_effort_map, "off": "medium"}}
        )
        entries = dict(pinned_snapshot.entries)
        if name == ROUTE and global_change == "removed":
            entries.pop(name)
        elif name == ROUTE:
            assert entry.capabilities is not None
            detailed = entry.reasoning_profile.model_copy(
                update={
                    "supported_levels": ("off", "medium"),
                    "default_level": "medium",
                    "provider_effort_map": {"medium": "medium"},
                }
            )
            entries[name] = entry.model_copy(
                update={
                    "reasoning_profile": detailed,
                    "capabilities": entry.capabilities.model_copy(
                        update={"reasoning_controls_available": True}
                    ),
                }
            )
        else:
            entries[name] = entry.model_copy(update={"reasoning_profile": profile})
        ModelCatalogService._snapshot = pinned_snapshot.model_copy(
            update={
                "generation": pinned_snapshot.generation + 1,
                "entries": entries,
            }
        )
        release.set()

    with (
        patch("src.tui.app.resolve_reasoning_config", side_effect=resolve) as resolver,
        patch.object(session, "should_show_startup_notice", side_effect=eligibility),
        patch.object(session, "mark_startup_notice_shown", wraps=session.mark_startup_notice_shown) as mark,
        patch.object(ModelCatalogService, "_snapshot", pinned_snapshot),
    ):
        publisher = asyncio.create_task(publish())
        try:
            app = SloTUI(session=session)
            async with app.run_test(size=size) as pilot:
                painted = await wait_until_painted(pilot=pilot, text=f"Provider detail: {effort}.")
                await publisher
                assert publisher.done() and not publisher.cancelled()
                assert ModelCatalogService._snapshot is not pinned_snapshot
                assert "".join(f"Provider detail: {effort}.".split()) in painted
                assert f"Initializedmodel:{name}." in painted
                await app._maybe_render_startup_notice()
                assert painted.count("Tip:use/help") == 1
                assert resolver.call_count == mark.await_count == 1
                marker = isolated_slo_home / "history" / session.session_id / "session.json"
                assert marker.resolve().is_relative_to(isolated_slo_home.resolve())
                assert json.loads(marker.read_text())["startup_notice_shown_at"] is not None
        finally:
            if not publisher.done():
                publisher.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await publisher
            else:
                await publisher


@pytest.mark.parametrize("pending", [True, False])
async def test_startup_pending_and_already_shown_do_not_resolve(
    isolated_slo_home: Path, pending: bool
) -> None:
    """Exercise startup guards before rendering; neither may resolve or mark again."""
    from src.tui.app import SloTUI

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-6-luna",
            enable_history=True,
            history_root=isolated_slo_home / "history",
        )
    )
    assert (isolated_slo_home / "history").resolve().is_relative_to(isolated_slo_home.resolve())
    if pending:
        session._preparation_status = "pending"
    else:
        await session.mark_startup_notice_shown()
    with (
        patch.object(
            session, "should_show_startup_notice", wraps=session.should_show_startup_notice
        ) as eligible,
        patch.object(
            session, "mark_startup_notice_shown", side_effect=AssertionError("marked again")
        ) as mark,
        patch("src.tui.app.resolve_reasoning_config", side_effect=AssertionError("resolved")) as resolve,
    ):
        await SloTUI(session=session)._maybe_render_startup_notice()
    assert eligible.await_count == (0 if pending else 1)
    mark.assert_not_called()
    resolve.assert_not_called()


@pytest.mark.parametrize("failure", ["invalid", "mutation", "preference"])
async def test_reasoning_errors_keep_validation_and_commit_boundaries(
    isolated_slo_home: Path,
    failure: str,
) -> None:
    """Invalid input is feedback; mutation and post-mutation save errors propagate."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-6-luna",
            reasoning_level="off",
            enable_history=False,
        )
    )
    with (
        patch.object(session, "switch_reasoning_level", wraps=session.switch_reasoning_level) as switch,
        patch("src.tui.slash_router.UserPreferencesStore.upsert") as save,
    ):
        if failure == "invalid":
            result = await SlashRouter.dispatch(line="/reasoning bogus", session=session)
            assert result.rendered is not None and "usage: /reasoning" in result.rendered
            switch.assert_not_called()
            save.assert_not_called()
            return
        if failure == "mutation":
            switch.side_effect = RuntimeError("mutation rejected")
            with pytest.raises(RuntimeError, match="mutation rejected"):
                await SlashRouter.dispatch(line="/reasoning medium", session=session)
            save.assert_not_called()
            assert session.active_reasoning_level == "off"
            return
        save.side_effect = OSError("save rejected")
        with pytest.raises(OSError, match="save rejected"):
            await SlashRouter.dispatch(line="/reasoning medium", session=session)
        assert session.active_reasoning_level == "medium"
        switch.assert_called_once_with(reasoning_level="medium")


@pytest.mark.parametrize("controls,disable", [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize("auth_type", [None, AuthType.API_KEY, AuthType.OAUTH])
async def test_projection_preserves_order_and_control_evidence(
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    controls: bool,
    disable: bool,
    auth_type: AuthType | None,
) -> None:
    """Public projection filters hidden rows and preserves independent control evidence."""
    snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    gateway = snapshot.entries[ROUTE]
    assert gateway.capabilities is not None
    gateway = gateway.model_copy(
        update={
            "capabilities": gateway.capabilities.model_copy(
                update={
                    "reasoning_controls_available": controls,
                    "reasoning_disable_available": disable,
                }
            )
        }
    )
    direct = snapshot.entries["gpt-6-luna"]
    hidden = direct.model_copy(update={"model_name": "hidden", "visible_in_picker": False})
    snapshot = snapshot.model_copy(
        update={"entries": {ROUTE: gateway, "hidden": hidden, direct.model_name: direct}}
    )
    ModelSuggestionProjection.reset()
    ModelSuggestionProjection._auth_types = {} if auth_type is None else {ProviderName.OPENAI: auth_type}
    try:
        with patch("src.tui.model_catalog.CredentialResolver.resolve", side_effect=AssertionError("row IO")):
            rows = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=ROUTE)
        assert [row.model_name for row in rows] == ["gpt-6-luna", ROUTE]
        assert rows[0].reasoning_summary == "off, minimal, low, medium, high, xhigh, max"
        assert rows[0].reasoning_controls_available and not rows[0].reasoning_disable_available
        assert "unavailable for ChatGPT/Codex" not in rows[0].status_summary
        assert rows[1].reasoning_summary == ("off" if disable else "")
        assert rows[1].reasoning_controls_available == (controls or disable)
        assert rows[1].reasoning_disable_available == disable
        assert rows[1].support_tier_label == "auto-discovered" and rows[1].is_active
        rows.clear()
        assert len(ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=ROUTE)) == 2
    finally:
        ModelSuggestionProjection.reset()


def test_picker_distinct_ineligible_record_retains_oauth_denial() -> None:
    """Cached OAuth presentation denies only the distinct synthetic ineligible row."""
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(
        update={"model_name": "gpt-fixture-ineligible-89", "supports_chatgpt_codex": False}
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, entry.model_name: entry}})
    ModelSuggestionProjection.reset()
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.OAUTH, access_token="fixture-picker-negative-89"
    )
    with patch("src.tui.model_catalog.CredentialResolver.resolve", return_value=credential):
        ModelSuggestionProjection.refresh_authentication()
    try:
        with patch("src.tui.model_catalog.CredentialResolver.resolve", side_effect=AssertionError("row IO")):
            rows = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name="gpt-6-luna")
        denied = next(row for row in rows if row.model_name == entry.model_name)
        assert "unavailable for ChatGPT/Codex" in denied.status_summary
        for name in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol"):
            allowed = next(row for row in rows if row.model_name == name)
            assert allowed.status_summary == "subscription configured; not checked"
            assert not allowed.requires_auth
    finally:
        ModelSuggestionProjection.reset()


@pytest.mark.parametrize("auth_type", [None, AuthType.API_KEY, AuthType.OAUTH])
def test_picker_auth_policy_is_lifecycle_bound(auth_type: AuthType | None) -> None:
    """Repeated typing never resolves auth; both configured lanes remain available."""
    ModelSuggestionProjection.reset()
    credential = (
        None
        if auth_type is None
        else CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=auth_type, access_token="fixture-picker-89"
        )
    )
    snapshot = SeedModelCatalog.load()
    with patch("src.tui.model_catalog.CredentialResolver.resolve", return_value=credential) as resolve:
        ModelSuggestionProjection.refresh_authentication()
        assert resolve.call_count == len(ProviderName)
    with patch("src.tui.model_catalog.CredentialResolver.resolve", side_effect=AssertionError("typing IO")):
        rows = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name="gpt-5.4")
        assert rows == ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name="gpt-5.4")
    for name in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol"):
        matching = [row for row in rows if row.model_name == name]
        assert len(matching) == 1
        assert matching[0].requires_auth == (auth_type is None)
        assert "unavailable for ChatGPT/Codex" not in matching[0].status_summary
        if auth_type is AuthType.OAUTH:
            assert matching[0].status_summary == "subscription configured; not checked"
        assert matching[0].context_window == 1050000
    ModelSuggestionProjection.reset()


@pytest.mark.parametrize("change", ["identity", "generation", "active", "authentication", "lifecycle"])
def test_projection_cache_invalidates_each_key_component(change: str) -> None:
    """Rebuild exactly once per invalidation, never resolving credentials on row reads."""
    from src.agents.model_catalog.dao import CatalogLifecycleStatusDAO

    ModelSuggestionProjection.reset()
    snapshot = SeedModelCatalog.load()
    active = "gpt-5.4"
    lifecycle = CatalogLifecycleStatusDAO(state="historical", revision=1)
    try:
        with (
            patch.object(ModelCatalogService, "lifecycle_status", return_value=lifecycle) as status,
            patch("src.tui.model_catalog.CredentialResolver.resolve", side_effect=AssertionError("row IO")),
            patch.object(
                ModelSuggestionProjection, "_build_rows", wraps=ModelSuggestionProjection._build_rows
            ) as build,
        ):
            first = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=active)
            cached = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=active)
            assert cached is not first and cached[0] is first[0]
            assert build.call_count == 1
            if change == "identity":
                snapshot = snapshot.model_copy()
            elif change == "generation":
                snapshot = snapshot.model_copy(update={"generation": snapshot.generation + 1})
                ModelSuggestionProjection._snapshot = snapshot  # isolate generation from identity
            elif change == "active":
                active = "gpt-6-luna"
            elif change == "authentication":
                with patch("src.tui.model_catalog.CredentialResolver.resolve", return_value=None) as resolve:
                    ModelSuggestionProjection.refresh_authentication()
                    assert resolve.call_count == len(ProviderName)
            else:
                status.return_value = lifecycle.model_copy(update={"revision": 2})
            refreshed = ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=active)
            assert build.call_count == 2
            assert refreshed[0] is not first[0]
            assert next(row for row in refreshed if row.model_name == active).is_active
            assert all(row.catalog_generation == snapshot.generation for row in refreshed)
            if change == "authentication":
                assert all(row.requires_auth for row in refreshed)
                assert ModelSuggestionProjection._auth_types == {}
            assert ModelSuggestionProjection.rows(snapshot=snapshot, active_model_name=active) == refreshed
            assert build.call_count == 2
    finally:
        ModelSuggestionProjection.reset()


@pytest.mark.parametrize("size", [(60, 20), (120, 40)])
async def test_admitted_jev_picker_keyboard_and_cropped_paint(
    isolated_slo_home: Path,
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    size: tuple[int, int],
) -> None:
    """Select genuinely admitted display-name search results with visible policy and footer."""
    from src.tui.app import SloTUI
    from tests.tui.authentication._painted_output import wait_until_painted

    snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    assert len(jev_transport) == 2
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=isolated_slo_home, model_name=ROUTE, enable_history=False),
        catalog_snapshot=snapshot,
    )
    app = SloTUI(session=session)
    async with app.run_test(size=size) as pilot:
        assert app._input is not None
        app._input.load_text("/model TypeSafe")
        menu = app.query_one(".slash-suggestion-lines")
        painted = await wait_until_painted(
            pilot=pilot, widget=menu, text="provider default; controls unavailable"
        )
        for text in (
            "provider default; controls unavailable",
            "context 1000000",
            "Showing 1 of 1",
            "catalog checked",
        ):
            assert "".join(text.split()) in painted
        assert "reasoning disabled" not in painted
        await pilot.press("down")
        await pilot.press("tab")
        await pilot.pause()
        assert app._input.text == f"/model {ROUTE}"
        await pilot.press("enter")
        await pilot.pause()
        assert session.active_model_name == ROUTE
        assert session._catalog_snapshot is not None
        assert session._catalog_snapshot.entries[ROUTE].runtime_profile.max_tokens == 4096


@pytest.mark.parametrize("size", [(60, 20), (120, 40)])
@pytest.mark.parametrize("auth_type", [None, AuthType.OAUTH])
async def test_direct_picker_cropped_auth_context_and_footer(
    isolated_slo_home: Path,
    isolated_catalog: CredentialStore,
    jev_transport: list[httpx.Request],
    size: tuple[int, int],
    auth_type: AuthType | None,
) -> None:
    """Paint missing versus incompatible direct credentials without opening a modal."""
    from src.tui.app import SloTUI
    from tests.tui.authentication._painted_output import wait_until_painted

    snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    if auth_type is not None:
        assert isolated_catalog.path.resolve().is_relative_to(isolated_slo_home.parent.resolve())
        isolated_catalog.persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=auth_type, access_token="fixture-oauth"
            )
        )
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=isolated_slo_home, model_name=ROUTE, enable_history=False),
        catalog_snapshot=snapshot,
    )
    app = SloTUI(session=session)
    expected = "requires /auth" if auth_type is None else "subscription configured; not checked"
    async with app.run_test(size=size) as pilot:
        assert app._input is not None
        app._input.load_text("/model gpt-6-luna")
        menu = app.query_one(".slash-suggestion-lines")
        painted = await wait_until_painted(pilot=pilot, widget=menu, text=expected)
        for text in (expected, "context 1050000", "Showing 1 of 1"):
            assert "".join(text.split()) in painted
        assert ("requires/auth" in painted) == (auth_type is None)


@pytest.mark.parametrize("size", [(60, 20), (120, 40)])
@pytest.mark.parametrize("auth_type", [AuthType.API_KEY, AuthType.OAUTH])
async def test_direct_picker_keyboard_paints_and_selects_exact_route(
    isolated_slo_home: Path,
    size: tuple[int, int],
    auth_type: AuthType,
) -> None:
    """Keyboard selection consumes unique projected direct rows at both viewport sizes."""
    from src.tui.app import SloTUI
    from tests.tui.authentication._painted_output import wait_until_painted

    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=auth_type,
            access_token="fixture-picker",
        )
    )
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-5.4",
            enable_history=False,
        )
    )
    app = SloTUI(session=session)
    async with app.run_test(size=size) as pilot:
        assert app._input is not None
        app._input.load_text("/model gpt-6")
        painted = await wait_until_painted(pilot=pilot, text="gpt-6-luna")
        for label in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol"):
            assert "".join(label.split()) in painted
        assert "context1050000" in painted
        await pilot.press("down")
        await pilot.pause()
        selected = app._slash_suggestion_state.highlighted_index
        assert selected == 1
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert session.active_model_name == "gpt-6-luna"
