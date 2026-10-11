"""Real credential precedence through the public Platform factory and locked SDK."""

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from tests.auth.test_credential_resolver import _reload_cfg
from tests.agents.providers.feature89_responses import answer_frames
from tests.agents.providers.test_openai_platform import block_default_transports


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
async def test_environment_key_beats_real_stored_oauth(
    model_name: str,
    isolated_slo_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate one real resolution and send its key without searching stored OAuth."""
    path = isolated_slo_home / "global/authentication.json"
    assert path.resolve().is_relative_to(isolated_slo_home.resolve())
    store = CredentialStore(path=path)
    store.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="fixture-stored-oauth-89",
        )
    )
    before = path.read_bytes()
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-env-platform-89")
    _reload_cfg()
    monkeypatch.setattr("src.auth.credential_resolver.CredentialStore", lambda: store)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve complete SSE only for the effective Platform key and URL."""
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer fixture-env-platform-89"
        requests.append(request)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=answer_frames(model_name=model_name),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
        with (
            patch.object(CredentialResolver, "require", wraps=CredentialResolver.require) as require,
            patch.object(CredentialResolver, "resolve", wraps=CredentialResolver.resolve) as resolve,
            patch.object(CredentialStore, "load", side_effect=AssertionError("fallback lookup")),
            patch.object(
                ModelCatalogEntryDAO,
                "require_backend_eligibility",
                autospec=True,
                side_effect=ModelCatalogEntryDAO.require_backend_eligibility,
            ) as guard,
        ):
            result = LLMFactory.create(model_name=model_name, http_async_client=client)
            answer = await result.llm.ainvoke(input="hello")
        require.assert_called_once_with(provider=ProviderName.OPENAI)
        resolve.assert_called_once_with(provider=ProviderName.OPENAI)
        assert guard.call_args.kwargs == {"auth_type": AuthType.API_KEY}
        assert guard.call_count == 1
    assert answer.content == [{"type": "text", "text": "complete-89", "id": "msg_89", "index": 0}]
    assert len(requests) == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
def test_missing_credential_keeps_existing_guidance(
    isolated_slo_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
) -> None:
    """Missing effective authentication fails before either SDK construction."""
    monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reload_cfg()
    with patch("src.agents.base.OpenAIPlatformChatOpenAI") as constructor:
        with pytest.raises(ValueError, match="No OpenAI credentials found"):
            LLMFactory.create(model_name=model_name)
    constructor.assert_not_called()


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6-sol"])
def test_oauth_constructor_policy_retains_codex_conflict_semantics(
    isolated_slo_home: Path, monkeypatch: pytest.MonkeyPatch, model_name: str
) -> None:
    """OAuth keeps the existing SDK field conflict, not Platform option rejection."""
    from tests.agents.providers.test_openai_codex import _build_jwt

    monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reload_cfg()
    path = isolated_slo_home / "global/authentication.json"
    assert path.resolve().is_relative_to(isolated_slo_home.resolve())
    CredentialStore(path=path).persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token=_build_jwt(
                claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-account-89"}}
            ),
        )
    )
    with pytest.raises(ValueError, match="Found temperature supplied twice"):
        LLMFactory.create(model_name=model_name, reasoning_level="off", model_kwargs={"temperature": 0.3})


@pytest.mark.parametrize("key", ["max_tokens", "max_completion_tokens", "max_output_tokens"])
@pytest.mark.parametrize("value", [None, 1234])
def test_constructor_cap_extras_reject_before_sdk(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: object,
) -> None:
    """Constructor cap aliases must use the factory's explicit cap parameter."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-env-platform-89")
    _reload_cfg()
    options = {key: value}
    with patch("src.agents.base.OpenAIPlatformChatOpenAI") as constructor:
        with pytest.raises(ValueError, match="^OpenAI request options conflict with catalog policy\\.$"):
            LLMFactory.create(model_name="gpt-6-luna", model_kwargs=options)
    constructor.assert_not_called()
    assert options == {key: value}


def test_invalid_off_temperature_fails_real_sdk_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict off consumes extras once but still delegates value validation to the SDK."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "fixture-env-platform-89")
    _reload_cfg()
    value = object()
    options = {"temperature": value}
    with pytest.raises(ValueError):
        LLMFactory.create(model_name="gpt-6-luna", reasoning_level="off", model_kwargs=options)
    assert options["temperature"] is value
