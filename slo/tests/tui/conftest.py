"""Shared fixtures for TUI tests.

Default behaviour (02.b.6): every TUI test runs with a fake credential
so the auto-modal added in ``SloTUI.on_mount`` doesn't intercept the
test's assertions. Tests that specifically exercise the modal path
re-monkeypatch the resolver to return ``None``.
"""

from __future__ import annotations

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


@pytest.fixture(autouse=True)
def _suppress_auth_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``CredentialResolver.resolve`` to always return a fake credential.

    Yields the matching DAO so tests that want to assert on its contents
    can read it.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest's monkeypatch fixture.
    """

    def _fake(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(
            provider=provider,
            auth_type=AuthType.API_KEY,
            access_token="sk-fake-default",
        )

    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", _fake)
