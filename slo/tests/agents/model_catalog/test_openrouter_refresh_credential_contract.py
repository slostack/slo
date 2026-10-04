"""Credential-capture refresh contracts for the OpenRouter catalog lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)


class RecordingOpenRouterClient:
    """Record metadata calls made for one already-captured credential."""

    def __init__(self, *, credential: CredentialDAO) -> None:
        """Retain the captured credential and initialize call counters."""
        self.credential: CredentialDAO = credential
        self.key_calls: int = 0
        self.models_calls: int = 0

    async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
        """Return matching fresh evidence while recording one verification request."""
        self.key_calls += 1
        return OpenRouterKeyVerificationDAO(
            credential_fingerprint=credential_fingerprint(access_token=self.credential.access_token),
            verified_at=datetime.now(tz=timezone.utc),
        )

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Return one suitable synthetic authenticated model while recording the list request."""
        self.models_calls += 1
        return OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/captured-model",
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        )


@pytest.mark.asyncio
async def test_refresh_when_auth_supplies_fresh_matching_capture_rechecks_effective_identity_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supplied captures remain fetch identity but cannot publish after effective-key rotation."""
    cache_path: Path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="candidate-not-yet-persisted",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    client = RecordingOpenRouterClient(credential=credential)
    evidence = OpenRouterKeyVerificationDAO(
        credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
        verified_at=datetime.now(tz=timezone.utc),
    )

    original = ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token="effective-key-at-admission",
        ),
        source=CredentialSource.STORE,
    )
    rotated = ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token="rotated-effective-key",
        ),
        source=CredentialSource.STORE,
    )
    resolver_calls: int = 0

    def resolve_rotated_effective_credential(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Return baseline identity first and the rotated identity at publication."""
        nonlocal resolver_calls
        resolver_calls += 1
        return original if resolver_calls == 1 else rotated

    monkeypatch.setattr(CredentialResolver, "resolve_with_source", resolve_rotated_effective_credential)
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        key_verification=evidence,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    assert result.status == "credential_changed"
    assert client.key_calls == 0
    assert client.models_calls == 1
    # Admission baseline, verified-status boundary, commit guard, failure-status boundary.
    assert resolver_calls == 4
    assert ModelCatalogService.lifecycle_status().state == "credential_changed"
    assert ModelCatalogService.lifecycle_status().key_verified_at is None
    assert not cache_path.exists()


@pytest.mark.asyncio
async def test_refresh_when_auth_supplies_stale_matching_evidence_verifies_once_and_rechecks_effective_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale private evidence is refreshed exactly once using the supplied auth credential."""
    cache_path: Path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    client = RecordingOpenRouterClient(credential=credential)
    evidence = OpenRouterKeyVerificationDAO(
        credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
        verified_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    )
    monkeypatch.setattr(CredentialResolver, "resolve_with_source", lambda *, provider: resolved)
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        key_verification=evidence,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    assert result.status == "refreshed"
    assert client.key_calls == 1
    assert client.models_calls == 1


@pytest.mark.asyncio
async def test_refresh_when_supplied_evidence_fingerprint_mismatches_rejects_before_any_metadata_request(
    tmp_path: Path,
) -> None:
    """Fingerprint-mismatched auth evidence cannot authorize a different captured key."""
    cache_path: Path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    client = RecordingOpenRouterClient(credential=credential)
    evidence = OpenRouterKeyVerificationDAO(
        credential_fingerprint=credential_fingerprint(access_token="key-b"),
        verified_at=datetime.now(tz=timezone.utc),
    )
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE),
        key_verification=evidence,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    assert result.status == "credential_changed"
    assert client.key_calls == 0
    assert client.models_calls == 0
