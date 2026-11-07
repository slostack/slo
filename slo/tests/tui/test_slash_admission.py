"""Exact preparation admission policy belongs to the slash router."""

import pytest

from src.tui.slash_router import SlashRouter


@pytest.mark.parametrize("token", ["auth", "help", "quit", "exit", "q", "clear", "model", "code"])
def test_preparing_accepts_exact_existing_allowlist(token: str) -> None:
    """Preparation permits only the documented raw tokens, including arguments."""
    admission = SlashRouter.admit(line=f"/{token} argument", preparation_status="pending")
    assert admission.action == "dispatch"
    assert not admission.refresh_model_context


@pytest.mark.parametrize("line", ["/h", "/?", "/new", "/abort", "/cwd", "/unknown", "/HELP", ""])
def test_preparing_does_not_expand_aliases(line: str) -> None:
    """Registry aliases do not widen the preparation exception list."""
    assert SlashRouter.admit(line=line, preparation_status="pending").action == "reject"
    assert SlashRouter.admit(line=line, preparation_status="ready").action == "dispatch"


@pytest.mark.parametrize("status", ["pending", "failed", "ready"])
def test_exact_model_refresh_returns_typed_intent(status: str) -> None:
    """Only the exact stripped spelling asks the app to prepare or refresh context."""
    admission = SlashRouter.admit(line=" /model refresh ", preparation_status=status)
    assert admission.action == ("dispatch" if status == "ready" else "prepare")
    assert admission.refresh_model_context is (status == "ready")
    for line in ["/model  refresh", "/model Refresh", "/model refresh extra"]:
        variant = SlashRouter.admit(line=line, preparation_status=status)
        assert variant.action == "dispatch"
        assert not variant.refresh_model_context
