"""Feature89 selection rejects incompatible credentials before any state mutation."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from typing import Optional

import httpx

import pytest

from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.model_catalog.dao import ModelCatalogEntryDAO, ModelCatalogSnapshotDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from tests.agents.model_catalog.test_feature89_jev_lifecycle import jev_transport, ROUTE
from tests.integration.test_openrouter_full_flow import isolated_catalog


@pytest.fixture(autouse=True)
def isolated_openai_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep store-driven selection tests independent of earlier config reloads."""
    import importlib

    configuration = importlib.import_module("config.cfg")
    monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(configuration.__cfg__, "OPENAI_API_KEY", None)


@pytest.fixture
def ineligible_snapshot(monkeypatch: pytest.MonkeyPatch) -> ModelCatalogSnapshotDAO:
    """Publish a distinct synthetic denied record without mutating any real seed."""
    snapshot = ModelCatalogService.load()
    name = "gpt-fixture-ineligible-89"
    entry = snapshot.entries["gpt-5.4"].model_copy(
        update={"model_name": name, "supports_chatgpt_codex": False}
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, name: entry}})
    monkeypatch.setattr(ModelCatalogService, "_snapshot", snapshot)
    return snapshot


def _pooled_session(*, root: Path) -> SloAgentSession:
    """Build nondefault selection state and persist real contained preference bytes."""
    assert UserPreferencesStore._preferences_path().resolve().is_relative_to(root.resolve())
    UserPreferencesStore.upsert(model_name="gpt-5.4", reasoning_level="high")
    pool = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name=name, provider=ProviderName.OPENAI, priority=index)
            for index, name in enumerate(("gpt-5.4", "gpt-5.6-sol"))
        ]
    )
    return SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=root, model_pool_dao=pool, reasoning_level="high", enable_history=False
        )
    )


@pytest.mark.parametrize("failure", ["missing", "preparation", "value"])
async def test_selection_preparation_failure_preserves_state(isolated_slo_home: Path, failure: str) -> None:
    """Reject initial auth or admission failures before selection and preference writes."""
    session = _pooled_session(root=isolated_slo_home)
    before = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    preferences = UserPreferencesStore._preferences_path().read_bytes()
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-selection"
    )
    error = (
        ModelPreparationRequiredError("not admitted")
        if failure == "preparation"
        else ValueError("safe failure")
    )
    with (
        patch("src.auth.credential_resolver.CredentialResolver.require", return_value=credential) as require,
        patch.object(ModelCatalogService, "prepare_models", side_effect=error) as prepare,
        patch.object(session, "_commit_model_selection") as commit,
        patch.object(UserPreferencesStore, "upsert") as save,
    ):
        if failure == "missing":
            require.side_effect = ValueError("missing auth")
        result = await session.prepare_model_selection(model_name="gpt-6-luna")
        expected = {
            "missing": "missing auth",
            "value": "safe failure",
            "preparation": "unavailable; run /model refresh or /auth",
        }
        assert expected[failure] in result
        assert prepare.await_count == int(failure != "missing")
        commit.assert_not_called()
        save.assert_not_called()
    after = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    assert all(left is right for left, right in zip(before, after))
    assert UserPreferencesStore._preferences_path().read_bytes() == preferences
    assert not session._lock.locked()


async def test_cold_gateway_selection_admits_before_entry_lookup(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request]
) -> None:
    """A cold gateway route reaches real authenticated preparation before record lookup."""
    root = isolated_catalog.path.parent
    session = _pooled_session(root=root)
    assert ROUTE not in ModelCatalogService.load().entries
    original = ModelCatalogService.entry_for_model

    def entry_for_model(
        *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> ModelCatalogEntryDAO:
        """Prohibit premature gateway lookup while delegating admitted lookups."""
        if model_name == ROUTE:
            assert snapshot is not None and ROUTE in snapshot.entries
            assert len(jev_transport) == 2
        return original(model_name=model_name, snapshot=snapshot)

    with patch.object(ModelCatalogService, "entry_for_model", side_effect=entry_for_model):
        result = await session.prepare_model_selection(model_name=ROUTE)
    assert result == f"active model switched to {ROUTE}. Preference saved."
    assert session.active_model_name == ROUTE
    assert session.active_reasoning_level == "off"
    assert session._config is not None and session._config.model_pool_dao is None
    assert session.catalog_snapshot is not None
    assert session.catalog_snapshot.entries[ROUTE].runtime_profile.max_tokens == 4096
    assert UserPreferencesStore.load().default_model_name == ROUTE
    assert [request.url.path for request in jev_transport] == ["/api/v1/key", "/api/v1/models/user"]


@pytest.mark.parametrize("guard", ["pending", "prebuilt"])
def test_sync_switch_guards_precede_credential_lookup(isolated_slo_home: Path, guard: str) -> None:
    """Unready or injected sessions reject switching before any auth or mutation."""
    session = _pooled_session(root=isolated_slo_home)
    before = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    if guard == "pending":
        session._preparation_status = "pending"
    else:
        session._allows_model_switching = False
    with patch.object(session, "_validate_model_selection_credential", side_effect=AssertionError("auth")):
        with pytest.raises(RuntimeError, match="preparation required|pre-built"):
            session.switch_model(model_name="gpt-6-luna")
    after = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    assert all(left is right for left, right in zip(before, after))


@pytest.mark.parametrize("pooled", [False, True])
def test_sync_switch_and_reasoning_use_session_snapshot(isolated_slo_home: Path, pooled: bool) -> None:
    """Successful switching and no-op/changed/clamped reasoning retain admitted A, not global B."""
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent

    session = _pooled_session(root=isolated_slo_home)
    assert session._config is not None
    if not pooled:
        session._config = session._config.model_copy(update={"model_pool_dao": None})
    snapshot = ModelCatalogService.load()
    session._catalog_snapshot = snapshot
    target = snapshot.entries["gpt-6-luna"]
    global_snapshot = snapshot.model_copy(
        update={
            "generation": snapshot.generation + 1,
            "entries": {
                **snapshot.entries,
                "gpt-6-luna": target.model_copy(
                    update={
                        "reasoning_profile": snapshot.entries["kimi-for-coding"].reasoning_profile,
                        "runtime_profile": target.runtime_profile.model_copy(update={"context_window": 2000}),
                    }
                ),
            },
        }
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-switch-89"
    )
    preferences = UserPreferencesStore._preferences_path().read_bytes()
    with (
        patch.object(ModelCatalogService, "_snapshot", global_snapshot),
        patch("src.auth.credential_resolver.CredentialResolver.require", return_value=credential),
    ):
        session.switch_model(model_name="gpt-6-luna")
        assert session.catalog_snapshot is snapshot
        assert session.active_model_name == "gpt-6-luna"
        assert session.active_reasoning_level == "high"
        assert session._config.model_pool_dao is None
        agent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(isolated_slo_home))
        session._agent = agent
        assert session.switch_reasoning_level(reasoning_level="high") == "high"
        assert session._agent is agent
        assert session.switch_reasoning_level(reasoning_level="max") == "max"
        assert session._agent is None
        session.switch_model(model_name="kimi-for-coding")
        assert session.active_reasoning_level == "off"
        session._agent = agent
        assert session.switch_reasoning_level(reasoning_level="max") == "off"
        assert session._agent is agent
    assert session.catalog_snapshot is snapshot
    assert UserPreferencesStore._preferences_path().read_bytes() == preferences


@pytest.mark.parametrize("mode", ["existing", "no-config", "non-openai"])
async def test_lazy_precheck_short_circuits(isolated_slo_home: Path, mode: str) -> None:
    """Existing clients and configurations without OpenAI require no new OpenAI auth."""
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.providers.faux import FauxChatModel

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=isolated_slo_home, model_name="kimi-for-coding", enable_history=False)
    )
    if mode == "no-config":
        session._config = None
    if mode == "existing":
        session._agent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(isolated_slo_home))
    with (
        patch(
            "src.auth.credential_resolver.CredentialResolver.require", side_effect=AssertionError("require")
        ),
        patch.object(session, "_refresh_oauth_credential_if_needed", side_effect=AssertionError("refresh")),
        patch.object(session, "_build_agent", side_effect=AssertionError("build")),
    ):
        if mode == "existing":
            await session._ensure_agent_ready()
        else:
            session._validate_configured_backend_eligibility()


@pytest.mark.parametrize("auth_type", [AuthType.OAUTH, AuthType.API_KEY])
@pytest.mark.parametrize("gateway_binding", [False, True])
async def test_lazy_allowed_credentials_preserve_build_binding_and_fingerprint(
    isolated_slo_home: Path, auth_type: AuthType, gateway_binding: bool
) -> None:
    """Allowed prechecks precede refresh and preserve the existing build-scoped capture."""
    from src.auth.credential_resolver import CredentialResolver
    from src.integrations.openrouter.dao import credential_fingerprint
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent

    session = _pooled_session(root=isolated_slo_home)
    session._catalog_snapshot = ModelCatalogService.load()
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=auth_type, access_token="fixture-allowed-89"
    )
    capture = (
        CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-capture-89"
        )
        if gateway_binding
        else None
    )
    session._admitted_openrouter_credential = capture
    agent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(isolated_slo_home))
    order: list[str] = []

    async def refresh() -> None:
        """Record refresh after the one precheck credential has been consumed."""
        require.assert_called_once_with(provider=ProviderName.OPENAI)
        order.append("refresh")

    def build() -> SloAgent:
        """Observe the real binding inside lazy construction without inference."""
        assert order == ["refresh"]
        assert CredentialResolver.operation_credential() is capture
        order.append("build")
        return agent

    with (
        patch.object(CredentialResolver, "require", return_value=credential) as require,
        patch.object(session, "_refresh_oauth_credential_if_needed", side_effect=refresh),
        patch.object(session, "_build_agent", side_effect=build),
    ):
        await session._ensure_agent_ready()
    assert order == ["refresh", "build"]
    assert session._agent is agent
    assert session._agent_catalog_snapshot is session.catalog_snapshot
    assert session._agent_openrouter_fingerprint == (
        credential_fingerprint(access_token=capture.access_token) if capture is not None else None
    )
    assert CredentialResolver.operation_credential() is None


@pytest.mark.parametrize("synchronous", [False, True])
async def test_incompatible_selection_is_atomic(
    isolated_slo_home: Path, ineligible_snapshot: ModelCatalogSnapshotDAO, synchronous: bool
) -> None:
    """Both public selection paths leave the prior config and lazy state untouched."""
    session = _pooled_session(root=isolated_slo_home)
    preferences = UserPreferencesStore._preferences_path().read_bytes()
    before = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.OAUTH, access_token="fixture-oauth-89"
    )
    with patch("src.auth.credential_resolver.CredentialResolver.require", return_value=credential):
        if synchronous:
            with pytest.raises(ValueError, match="requires an OpenAI Platform API key"):
                session.switch_model(model_name="gpt-fixture-ineligible-89")
        else:
            result = await session.prepare_model_selection(model_name="gpt-fixture-ineligible-89")
            assert "requires an OpenAI Platform API key" in result
    assert session.active_model_name == "gpt-5.4"
    assert session.active_reasoning_level == "high"
    after = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    assert all(left is right for left, right in zip(before, after))
    assert session._config is not None and session._config.model_pool_dao is not None
    assert UserPreferencesStore._preferences_path().read_bytes() == preferences


@pytest.mark.parametrize("change", ["oauth", "api_key", "removal"])
async def test_selection_rechecks_credential_after_preparation(isolated_slo_home: Path, change: str) -> None:
    """A deterministic preparation barrier exposes API-key to OAuth rotation."""
    session = _pooled_session(root=isolated_slo_home)
    before = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    preferences = UserPreferencesStore._preferences_path().read_bytes()
    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    entered, release = asyncio.Event(), asyncio.Event()
    original = ModelCatalogService.prepare_models

    async def prepare(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Delegate actual preparation, then hold its result until credential rotation."""
        snapshot = await original(model_names=model_names)
        entered.set()
        await release.wait()
        return snapshot

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-key-89"
    )
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

    oauth = _oauth_cred(
        access_token=_build_jwt(
            claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-rotation89"}}
        )
    )
    store.persist(cred=oauth if change == "api_key" else credential)
    with patch.object(ModelCatalogService, "prepare_models", side_effect=prepare):
        task = asyncio.create_task(session.prepare_model_selection(model_name="gpt-6-sol"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        if change == "oauth":
            store.persist(cred=oauth)
        elif change == "api_key":
            store.persist(cred=credential)
        else:
            store.remove(provider=ProviderName.OPENAI)
        release.set()
        result = await task
        if change != "removal":
            assert "switched" in result
            assert session.active_model_name == "gpt-6-sol"
            await session._ensure_agent_ready()
            assert session._agent is not None
            assert not session._lock.locked()
            return
        assert "/auth" in result
        assert "switched" not in result
    assert session.active_model_name == "gpt-5.4"
    assert session.active_reasoning_level == "high"
    after = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    assert all(left is right for left, right in zip(before, after))
    assert UserPreferencesStore._preferences_path().read_bytes() == preferences
    assert not session._lock.locked()


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
@pytest.mark.parametrize("synchronous", [False, True, "primary", "secondary"])
@pytest.mark.parametrize("token_state", ["refresh", "fresh", "no-expiry", "no-refresh-token"])
async def test_oauth_selection_and_near_expiry_refresh_build(
    isolated_slo_home: Path,
    model_name: str,
    synchronous: bool | str,
    token_state: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Real resolver/store selection refreshes a valid token before the actual lazy build."""
    from datetime import timedelta
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
    from src.auth.providers.openai_codex_provider import OpenAICodexOAuthProvider

    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    token = _build_jwt(
        claims={
            "https://api.openai.com/auth": {"chatgpt_account_id": "fixture-refresh-account"},
            "jti": "old-89",
        }
    )
    fresh_token = _build_jwt(
        claims={
            "https://api.openai.com/auth": {"chatgpt_account_id": "fixture-refresh-account"},
            "jti": "new-89",
        }
    )
    fresh = _oauth_cred(access_token=fresh_token)
    store.persist(
        cred=fresh.model_copy(
            update={"access_token": token, "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30)}
        )
    )
    if token_state != "refresh":
        credential = store.load().providers[ProviderName.OPENAI]
        updates: dict[str, dict[str, Optional[datetime]]] = {
            "fresh": {"expires_at": datetime.now(timezone.utc) + timedelta(hours=1)},
            "no-expiry": {"expires_at": None},
            "no-refresh-token": {"refresh_token": None},
        }
        store.persist(cred=credential.model_copy(update=updates[token_state]))
    before = store.path.read_bytes()
    session = _pooled_session(root=isolated_slo_home)
    if isinstance(synchronous, str):
        names = (model_name, "gpt-5.4") if synchronous == "primary" else ("gpt-5.4", model_name)
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=isolated_slo_home,
                enable_history=False,
                reasoning_level="high",
                model_pool_dao=ModelPoolDAO(
                    entries=[
                        ModelPoolEntryDAO(model_name=name, provider=ProviderName.OPENAI, priority=index)
                        for index, name in enumerate(names)
                    ]
                ),
            )
        )
    elif synchronous:
        session.switch_model(model_name=model_name)
    else:
        assert "switched" in await session.prepare_model_selection(model_name=model_name)
    assert session.active_model_name == ("gpt-5.4" if synchronous == "secondary" else model_name)
    assert session._agent is None
    assert session._config is not None
    history_root = isolated_slo_home / "refresh-history"
    assert history_root.resolve().is_relative_to(isolated_slo_home.resolve())
    session = SloAgentSession.build(
        config=session._config.model_copy(update={"enable_history": True, "history_root": history_root})
    )
    from src.agents.base import LLMFactory
    from tests.agents.providers.feature89_responses import answer_frames

    from aiohttp import web
    from unittest.mock import PropertyMock
    from tests.auth.test_oauth_provider_refresh import _spin_up_token_endpoint

    refresh_forms: list[dict[str, str]] = []

    async def token_response(request: web.Request) -> web.Response:
        """Receive production aiohttp form serialization and return a distinct synthetic JWT."""
        assert request.content_type == "application/x-www-form-urlencoded"
        refresh_forms.append({key: str(value) for key, value in (await request.post()).items()})
        return web.json_response(
            data={"access_token": fresh_token, "refresh_token": "rt-new-89", "expires_in": 3600}
        )

    token_url, server = await _spin_up_token_endpoint(handler=token_response)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the post-refresh SDK bearer without making any network request."""
        requests.append(request)
        if synchronous == "secondary" and len(requests) <= 4:
            return httpx.Response(
                status_code=429,
                headers={"retry-after-ms": "1"},
                json={"error": {"message": "synthetic rate limit"}},
            )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=answer_frames(model_name=model_name),
        )

    original = LLMFactory.create
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        with (
            patch.object(
                OpenAICodexOAuthProvider, "token_endpoint", new_callable=PropertyMock, return_value=token_url
            ),
            patch.object(
                OpenAICodexOAuthProvider, "refresh", wraps=OpenAICodexOAuthProvider().refresh
            ) as refresh,
            patch.object(
                LLMFactory,
                "create",
                side_effect=lambda **kwargs: original(**{**kwargs, "http_async_client": client}),
            ),
        ):
            try:
                events = [event async for event in session.invoke(text="after refresh")]
            finally:
                await server.cleanup()
    assert refresh_forms == (
        [
            {
                "grant_type": "refresh_token",
                "refresh_token": "rt-test",
                "client_id": OpenAICodexOAuthProvider().client_id,
            }
        ]
        if token_state == "refresh"
        else []
    )
    assert refresh.await_count == int(token_state == "refresh")
    if token_state == "refresh":
        refresh.assert_awaited_once_with(refresh_token="rt-test")
    else:
        assert store.path.read_bytes() == before
    assert any(event.kind == "run_completed" for event in events)
    assert len(requests) == (5 if synchronous == "secondary" else 1) and token != fresh_token
    assert all(
        request.headers["authorization"] == requests[0].headers["authorization"] for request in requests
    )
    import json

    assert json.loads(requests[-1].content)["model"] == model_name
    captured = capsys.readouterr()
    public = (
        captured.out + captured.err + caplog.text + "\n".join(event.model_dump_json() for event in events)
    )
    artifacts = list(history_root.rglob("*"))
    assert any(artifact.name == "events.jsonl" for artifact in artifacts)
    for artifact in artifacts:
        assert artifact.resolve().is_relative_to(isolated_slo_home.resolve())
        if artifact.is_file():
            public += artifact.read_text(encoding="utf-8")
    for sentinel in (token, fresh_token, "rt-test", "rt-new-89", "fixture-refresh-account"):
        assert sentinel not in public
    assert (
        requests[0].headers["authorization"] == f"Bearer {fresh_token if token_state == 'refresh' else token}"
    )
    assert str(requests[0].url) == "https://chatgpt.com/backend-api/codex/responses"
    assert not session.is_running and not session._lock.locked()
    assert store.load().providers[ProviderName.OPENAI].access_token == (
        fresh_token if token_state == "refresh" else token
    )
    assert session._agent is not None
    assert session.active_reasoning_level == "high"
    session.switch_reasoning_level(reasoning_level="off")
    assert session._agent is None
    assert not session._lock.locked()


@pytest.mark.parametrize("failure", ["refresh", "cancel", "malformed", "missing-account"])
async def test_oauth_public_invoke_failure_preserves_store_and_unlocks(
    isolated_slo_home: Path,
    failure: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failed refresh or local JWT parsing leaves lazy state unset and public lock released."""
    from datetime import timedelta
    from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
    from src.auth.providers.openai_codex_provider import OpenAICodexOAuthProvider

    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "failure-account-89"}})
    if failure == "malformed":
        token = "malformed-jwt-89"
    if failure == "missing-account":
        token = _build_jwt(claims={"sub": "missing-account-89"})
    credential = _oauth_cred(access_token=token)
    if failure in ("refresh", "cancel"):
        credential = credential.model_copy(
            update={"expires_at": datetime.now(timezone.utc) + timedelta(seconds=30)}
        )
    store.persist(cred=credential)
    before = store.path.read_bytes()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-6-luna",
            enable_history=True,
            history_root=isolated_slo_home / "failure-history",
        )
    )
    error = asyncio.CancelledError() if failure == "cancel" else ValueError("synthetic refresh failure")
    with patch.object(OpenAICodexOAuthProvider, "refresh", side_effect=error) as refresh:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError) as caught:
            async for _ in session.invoke(text="fail locally"):
                pytest.fail("pre-build failure must not yield provider events")
    captured = capsys.readouterr()
    public = captured.out + captured.err + caplog.text + str(caught.value) + repr(caught.value)
    for artifact in (isolated_slo_home / "failure-history").rglob("*"):
        assert artifact.resolve().is_relative_to(isolated_slo_home.resolve())
        if artifact.is_file():
            public += artifact.read_text(encoding="utf-8")
    for sentinel in (token, "rt-test", "failure-account-89", "missing-account-89", "malformed-jwt-89"):
        assert sentinel not in public
    assert refresh.await_count == int(failure in ("refresh", "cancel"))
    assert store.path.read_bytes() == before
    assert session._agent is None
    assert not session.is_running and not session._lock.locked()


@pytest.mark.parametrize("failure", ["none", "preferences", "commit"])
async def test_selection_commit_exception_boundary(isolated_slo_home: Path, failure: str) -> None:
    """Only preference IO errors become selected-but-unsaved; commit errors propagate."""
    session = _pooled_session(root=isolated_slo_home)
    before = UserPreferencesStore._preferences_path().read_bytes()
    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-selection"
        )
    )
    with (
        patch.object(session, "_commit_model_selection", wraps=session._commit_model_selection) as commit,
        patch.object(UserPreferencesStore, "upsert", wraps=UserPreferencesStore.upsert) as save,
    ):
        if failure == "commit":
            commit.side_effect = RuntimeError("commit sentinel")
            with pytest.raises(RuntimeError, match="commit sentinel"):
                await session.prepare_model_selection(model_name="gpt-6-luna")
            save.assert_not_called()
            assert session.active_model_name == "gpt-5.4"
        else:
            if failure == "preferences":
                save.side_effect = OSError("save sentinel")
            result = await session.prepare_model_selection(model_name="gpt-6-luna")
            assert session.active_model_name == "gpt-6-luna"
            assert session.active_reasoning_level == "high"
            assert session._config is not None and session._config.model_pool_dao is None
            assert ("Preference was not saved" in result) == (failure == "preferences")
    assert not session._lock.locked()
    assert (UserPreferencesStore._preferences_path().read_bytes() == before) == (failure != "none")


@pytest.mark.parametrize("secondary", [False, True])
async def test_lazy_incompatible_oauth_never_refreshes(
    isolated_slo_home: Path, ineligible_snapshot: ModelCatalogSnapshotDAO, secondary: bool
) -> None:
    """Reject locally before refresh even when the saved route is built lazily."""
    from unittest.mock import AsyncMock

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-fixture-ineligible-89",
            enable_history=False,
            model_pool_dao=(
                ModelPoolDAO(
                    entries=[
                        ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                        ModelPoolEntryDAO(
                            model_name="gpt-fixture-ineligible-89", provider=ProviderName.OPENAI, priority=1
                        ),
                    ]
                )
                if secondary
                else None
            ),
        )
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token="fixture-expired-89",
        expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    with (
        patch("src.auth.credential_resolver.CredentialResolver.require", return_value=credential) as require,
        patch.object(session, "_refresh_oauth_credential_if_needed", new_callable=AsyncMock) as refresh,
        patch.object(session, "_build_agent") as build,
    ):
        with pytest.raises(ValueError, match="requires an OpenAI Platform API key"):
            await session._ensure_agent_ready()
        require.assert_called_once_with(provider=ProviderName.OPENAI)
        refresh.assert_not_called()
        build.assert_not_called()
    assert session._agent is None


@pytest.mark.parametrize("guard", ["busy", "pending"])
@pytest.mark.parametrize("after_prepare", [False, True])
async def test_selection_guards_preserve_state(
    isolated_slo_home: Path,
    guard: str,
    after_prepare: bool,
) -> None:
    """Guard both sides of preparation without adopting a candidate or saving bytes."""
    session = _pooled_session(root=isolated_slo_home)
    before = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    preferences = UserPreferencesStore._preferences_path().read_bytes()
    entered, release = asyncio.Event(), asyncio.Event()
    snapshot = ModelCatalogService.load()

    async def prepare(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Expose the await boundary without admitting the unused guarded candidate."""
        entered.set()
        await release.wait()
        return snapshot

    def set_guard() -> None:
        """Simulate competing lifecycle ownership at the deterministic boundary."""
        if guard == "busy":
            session._is_running = True
        else:
            session._preparation_status = "pending"

    name = "openrouter:typesafe/jev-router" if guard == "pending" else "gpt-6-luna"
    with (
        patch.object(session, "_validate_model_selection_credential") as validate,
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare) as preparation,
        patch.object(UserPreferencesStore, "upsert") as save,
    ):
        if after_prepare:
            task = asyncio.create_task(session.prepare_model_selection(model_name=name))
            await asyncio.wait_for(entered.wait(), timeout=2)
            set_guard()
            release.set()
            result = await task
        else:
            set_guard()
            result = await session.prepare_model_selection(model_name=name)
        assert ("prompt is in flight" if guard == "busy" else "preparation is pending") in result
        assert preparation.await_count == validate.call_count == int(after_prepare)
        save.assert_not_called()
    after = (session._config, session.catalog_snapshot, session._agent, session._usage_snapshot)
    assert all(left is right for left, right in zip(before, after))
    assert UserPreferencesStore._preferences_path().read_bytes() == preferences
    assert not session._lock.locked()


@pytest.mark.parametrize("expired", [False, True])
async def test_public_invoke_local_rejection_releases_lock_and_recovers(
    isolated_slo_home: Path, ineligible_snapshot: ModelCatalogSnapshotDAO, expired: bool
) -> None:
    """An expired incompatible lane fails once; explicit reselection permits a later Faux turn."""
    from src.agents.providers.faux import FauxChatModel
    from src.agents.base import LLMBuildResult
    from langchain_core.messages import AIMessage

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_slo_home,
            model_name="gpt-fixture-ineligible-89",
            enable_history=False,
        )
    )
    store = CredentialStore()
    assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token="fixture-expired",
        refresh_token="fixture-refresh",
        expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc) if expired else None,
    )
    store.persist(cred=credential)
    with (
        patch.object(
            session, "_refresh_oauth_credential_if_needed", side_effect=AssertionError("refresh")
        ) as refresh,
        patch.object(session, "_build_agent", side_effect=AssertionError("build")) as build,
    ):
        with pytest.raises(
            ValueError, match="No OpenAI credentials" if expired else "requires an OpenAI Platform API key"
        ):
            async for _ in session.invoke(text="must reject locally"):
                pytest.fail("local rejection must precede provider events")
        refresh.assert_not_called()
        build.assert_not_called()
    assert not session.is_running and not session._lock.locked()
    store.persist(cred=credential.model_copy(update={"auth_type": AuthType.API_KEY, "expires_at": None}))
    assert "switched" in await session.prepare_model_selection(model_name="gpt-6-sol")
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="recovered-89")]),
            supports_explicit_caching=False,
        ),
    ):
        events = [event async for event in session.invoke(text="retry explicitly")]
    assert any(event.kind == "run_completed" for event in events)
    assert not session.is_running and not session._lock.locked()
