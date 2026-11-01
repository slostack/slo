"""Shared fixtures for TUI tests.

Default behaviour (02.b.6): every TUI test runs with a fake credential
so the auto-modal added in ``SloTUI.on_mount`` doesn't intercept the
test's assertions. Tests that specifically exercise the modal path
re-monkeypatch the resolver to return ``None``.
"""

from __future__ import annotations

from typing import Iterator
import hashlib
import os
import sys

from tests.tui.selection_observer import SelectionObserver

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.event_renderer import EventRenderer


@pytest.fixture
def theme_colors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable theme colors for exact paint assertions before constructing the app.

    Args:
        monkeypatch: Restores the caller's terminal preference after the test.
    """
    monkeypatch.delenv(name="NO_COLOR", raising=False)


@pytest.fixture(autouse=True)
def _observe_mr116_selection(request: pytest.FixtureRequest) -> Iterator[None]:
    """TEMP: capture the exact case only when opted in; preserve all natural scheduling.

    JUnit user properties carry bounded sanitized evidence on pass and failure.
    No file writes, application text, credentials, or environment dump occurs here.
    """
    target = (
        "tests/tui/test_selection_scroll_highlight.py::TestPilotVisibleSelection::"
        "test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme[slo-dark-answer]"
    )
    if os.environ.get("SLO_TEST_SELECTION_OBSERVER") != "1" or request.node.nodeid != target:
        yield
        return
    observer = SelectionObserver()
    order = "\n".join(item.nodeid for item in request.session.items)
    observer.append(
        event="collection",
        fields={
            "count": len(request.session.items),
            "sha256": hashlib.sha256(order.encode()).hexdigest(),
            "target_index": request.session.items.index(request.node),
            "preceding": [
                item.nodeid[:256]
                for item in request.session.items[
                    max(0, request.session.items.index(request.node) - 8) : request.session.items.index(
                        request.node
                    )
                ]
            ],
        },
    )
    previous = sys.getprofile()
    assert previous is None, "TEMP observer must not replace another profiler"
    sys.setprofile(observer.profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
        request.node.user_properties.append(("selection_observer", observer.serialize()))


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
