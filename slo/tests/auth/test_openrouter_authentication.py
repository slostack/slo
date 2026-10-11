"""Offline temporal contracts for OpenRouter key authentication."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src.agents.model_catalog.dao import CatalogRefreshResultDAO
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_store import CredentialStore
from src.auth.openrouter_authentication import OpenRouterAuthenticationService
from src.integrations.openrouter.client import OpenRouterAPIClient


def credential(*, token: str) -> CredentialDAO:
    """Build a synthetic, never-live OpenRouter credential."""
    return CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=token)


@pytest.mark.parametrize("environment", [False, True])
async def test_verification_precedes_persistence_and_refresh(
    tmp_path: Path, environment: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify only the captured effective key, then pass identical evidence to refresh."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    store.persist(cred=credential(token="old-sentinel"))
    before = store.additional_providers_path.read_bytes()
    effective = (
        ResolvedCredentialDAO(
            credential=credential(token="environment-sentinel"), source=CredentialSource.ENVIRONMENT
        )
        if environment
        else None
    )
    resolver = Mock()
    resolver.resolve_with_source.return_value = effective
    catalog = Mock()
    catalog.refresh = AsyncMock(
        return_value=CatalogRefreshResultDAO(
            status="refreshed", catalog_generation=1, safe_message="Catalog checked."
        )
    )
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Assert old bytes still exist at the actual local verification boundary."""
        assert store.additional_providers_path.read_bytes() == before
        assert request.headers["authorization"] == (
            "Bearer environment-sentinel" if environment else "Bearer candidate-sentinel"
        )
        requests.append(request.url.path)
        return httpx.Response(status_code=200, json={"data": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject the local HTTP boundary without reading credentials."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            resolver=resolver, store=store, client_factory=client_factory, catalog_service=catalog
        )
        result = await service.invoke(submitted_key="candidate-sentinel")
    assert requests == ["/api/v1/key"]
    assert result.key_verified
    assert result.replacement_saved is (not environment)
    assert (store.additional_providers_path.read_bytes() == before) is environment
    capture = catalog.refresh.call_args.kwargs["resolved_credential"]
    assert capture.credential.access_token == (
        "environment-sentinel" if environment else "candidate-sentinel"
    )
    assert catalog.refresh.call_args.kwargs["key_verification"] is not None
    assert "sentinel" not in result.model_dump_json() + repr(result) + repr(service) + caplog.text
    if environment:
        assert "pasted key was not saved" in result.safe_message


@pytest.mark.parametrize("failure", ["unauthorized", "forbidden", "protocol", "timeout", "cancel"])
async def test_verification_failure_preserves_bytes(
    tmp_path: Path, failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Rejected or cancelled verification cannot replace an existing stored row."""
    import asyncio

    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    store.persist(cred=credential(token="old-sentinel"))
    before = store.additional_providers_path.read_bytes()
    resolver = Mock()
    resolver.resolve_with_source.return_value = None
    catalog = Mock()
    catalog.refresh = AsyncMock()

    def respond(request: httpx.Request) -> httpx.Response:
        """Reject locally with secret-bearing wire data that must never escape."""
        if failure == "timeout":
            raise httpx.ReadTimeout("candidate-sentinel")
        if failure == "cancel":
            raise asyncio.CancelledError()
        return httpx.Response(
            status_code={"unauthorized": 401, "forbidden": 403}.get(failure, 200),
            json={"error": "candidate-sentinel"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Build the actual client using only the local transport."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            resolver=resolver, store=store, client_factory=client_factory, catalog_service=catalog
        )
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await service.invoke(submitted_key="candidate-sentinel")
        else:
            result = await service.invoke(submitted_key="candidate-sentinel")
            assert not result.key_verified
            expected_messages: dict[str, str] = {
                "unauthorized": "OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY.",
                "forbidden": "OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY.",
                "protocol": "OpenRouter returned an invalid verification response. Retry authentication later.",
                "timeout": "OpenRouter request timed out. Retry authentication later.",
            }
            assert result.safe_message == expected_messages[failure]
            assert "sentinel" not in repr(result) + result.model_dump_json() + caplog.text
    assert store.additional_providers_path.read_bytes() == before
    catalog.refresh.assert_not_called()


@pytest.mark.parametrize("outcome", ["failed", "exception", "cancel"])
async def test_refresh_failure_keeps_verified_key(tmp_path: Path, outcome: str) -> None:
    """Failure or cancellation after commit reports saved state without raw error copy."""
    import asyncio

    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    resolver = Mock()
    resolver.resolve_with_source.return_value = None
    catalog = Mock()
    catalog.refresh = AsyncMock(
        return_value=CatalogRefreshResultDAO(
            status="failed", catalog_generation=0, safe_message="raw-sentinel"
        )
    )
    if outcome == "exception":
        catalog.refresh.side_effect = RuntimeError("raw-sentinel")
    if outcome == "cancel":
        catalog.refresh.side_effect = asyncio.CancelledError()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"data": {}}))
    ) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Return a locally verified actual client."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            resolver=resolver, store=store, client_factory=client_factory, catalog_service=catalog
        )
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await service.invoke(submitted_key="candidate-sentinel")
            assert "verified key was saved" in service.result.safe_message
        else:
            await service.invoke(submitted_key="candidate-sentinel")
            assert service.result.safe_message == "Key verified; catalog refresh failed."
    assert store.load().providers[ProviderName.OPENROUTER].access_token == "candidate-sentinel"
    assert service.result.key_verified and service.result.replacement_saved
    assert "sentinel" not in repr(service.result) + service.result.model_dump_json()


async def test_listing_credential_change_clears_obsolete_dismissal_evidence(tmp_path: Path) -> None:
    """A listing-time source rotation cannot paint success or dismiss with stale evidence."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    resolver = Mock()
    resolver.resolve_with_source.return_value = None
    catalog = Mock()
    catalog.refresh = AsyncMock(
        return_value=CatalogRefreshResultDAO(
            status="credential_changed", catalog_generation=7, safe_message="unused-sentinel"
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"data": {}}))
    ) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Return the actual local-only verification boundary."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            resolver=resolver, store=store, client_factory=client_factory, catalog_service=catalog
        )
        result = await service.invoke(submitted_key="candidate-sentinel")

    assert result.safe_message == "Credential changed; retry authentication."
    assert not result.key_verified and not result.catalog_checked
    assert result.replacement_saved
    assert service.verified_credential() is None
    assert store.load().providers[ProviderName.OPENROUTER].access_token == "candidate-sentinel"
    assert "sentinel" not in result.model_dump_json() + repr(result)


@pytest.mark.parametrize("replacement", ["environment-b-sentinel", None])
async def test_environment_changes_during_verification_discard_verified_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str | None
) -> None:
    """Reject an obsolete environment verification before exposing success or refreshing."""
    from src.auth.credential_resolver import CredentialResolver

    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    store.persist(cred=credential(token="old-sentinel"))
    before = store.additional_providers_path.read_bytes()
    monkeypatch.setattr("src.auth.credential_resolver.CredentialStore", lambda: store)
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", "environment-a-sentinel")
    catalog = Mock()
    catalog.refresh = AsyncMock()

    def respond(request: httpx.Request) -> httpx.Response:
        """Change the effective source while the actual local key request completes."""
        assert request.headers["authorization"] == "Bearer environment-a-sentinel"
        if replacement is None:
            monkeypatch.delenv("SLO_OPENROUTER_API_KEY")
        else:
            monkeypatch.setenv("SLO_OPENROUTER_API_KEY", replacement)
        return httpx.Response(status_code=200, json={"data": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Use the real verifier with only an in-memory transport."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            resolver=CredentialResolver(), store=store, client_factory=client_factory, catalog_service=catalog
        )
        result = await service.invoke(submitted_key="candidate-sentinel")
    assert result.safe_message == "Credential changed; retry authentication."
    assert not result.key_verified and not result.replacement_saved
    assert service.verified_credential() is None
    assert store.additional_providers_path.read_bytes() == before
    catalog.refresh.assert_not_called()
    assert "sentinel" not in result.model_dump_json() + repr(result)


async def test_environment_appearing_before_commit_discards_candidate(tmp_path: Path) -> None:
    """The final source check must reject a newly shadowed verified candidate."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    store.persist(cred=credential(token="old-sentinel"))
    before = store.additional_providers_path.read_bytes()
    resolver = Mock()
    resolver.resolve_with_source.side_effect = [
        None,
        ResolvedCredentialDAO(
            credential=credential(token="environment-sentinel"), source=CredentialSource.ENVIRONMENT
        ),
    ]
    catalog = Mock()
    catalog.refresh = AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"data": {}}))
    ) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Return a local verification client."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        result = await OpenRouterAuthenticationService(
            resolver=resolver, store=store, client_factory=client_factory, catalog_service=catalog
        ).invoke(submitted_key="candidate-sentinel")
    assert result.safe_message == "Credential changed; retry authentication."
    assert store.additional_providers_path.read_bytes() == before
    catalog.refresh.assert_not_called()
