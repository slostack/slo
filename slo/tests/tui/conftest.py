"""Shared fixtures for TUI tests.

Default behaviour (02.b.6): every TUI test runs with a fake credential
so the auto-modal added in ``SloTUI.on_mount`` doesn't intercept the
test's assertions. Tests that specifically exercise the modal path
re-monkeypatch the resolver to return ``None``.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.event_renderer import EventRenderer


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


@pytest.fixture(autouse=True)
def _reset_event_renderer_overrides() -> Iterator[None]:
    """Keep one test's plugin renderer overrides out of the next test.

    ``EventRenderer._RENDERER_OVERRIDES`` is class-level mutable state, and
    ``SloAgentSession.build`` fills it from the plugin registry. Since the
    bundled ``bash_live_output`` plugin registers a ``bash`` renderer, any
    test that builds a real session installs a process-wide override that
    outlives it — which made
    ``test_summarize_bash_reports_exit_zero_and_line_count`` pass alone and
    fail in the full suite. Clearing around every TUI test makes each one
    start from the shipped renderers regardless of run order.

    Yields:
        None: Control to the test, with no overrides registered.
    """
    EventRenderer.set_renderer_overrides(renderers={})
    yield
    EventRenderer.set_renderer_overrides(renderers={})
