"""Smoke test: every production module must import cleanly.

Catches broken imports introduced by sibling sub-specs in flight.
"""

import importlib
import pkgutil

import pytest


def _walk_imports(package_name: str) -> list[str]:
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        return []
    return [m.name for m in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}.")]


_MODULES_TO_IMPORT: list[str] = [
    *_walk_imports("config"),
    *_walk_imports("src"),
]


@pytest.mark.parametrize("module_name", _MODULES_TO_IMPORT)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


class TestAuthFirstLaunchSmoke:
    """End-to-end first-launch flow: clean machine → modal → API key → persist."""

    @pytest.mark.asyncio
    async def test_clean_machine_authenticates_via_api_key(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """Modal opens on mount, API-key paste persists, store carries the row."""
        from pathlib import Path
        from uuid import uuid4
        from langchain_core.messages import AIMessage
        from textual.widgets import Input
        from src.agents.slo_agent.agent import SloAgent
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.providers.faux import FauxChatModel
        from src.auth.credential_dao import ProviderName
        from src.auth.credential_store import CredentialStore
        from src.tui.app import SloTUI
        from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget

        monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        store_path: Path = tmp_path / "global" / "authentication.json"
        legacy_missing: Path = tmp_path / "claude-credentials.json"
        monkeypatch.setattr(
            "src.auth.credential_resolver.CredentialResolver._CLAUDE_CREDENTIALS_PATH",
            legacy_missing,
        )
        monkeypatch.setattr(
            "src.tui.app.CredentialResolver.resolve",
            lambda *, provider: None,
        )
        monkeypatch.setattr(
            "src.tui.authentication.auth_screen.CredentialStore",
            lambda: CredentialStore(path=store_path),
        )

        agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="hi")]))
        session: SloAgentSession = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert any(screen.__class__.__name__ == "AuthenticationScreen" for screen in app.screen_stack)
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-api-key")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()
            pilot.app.screen.query_one(
                ApiKeyInputWidget,
            ).query_one("#api-key-input", Input).value = "sk-smoke"
            await pilot.click("#api-key-save")
            await pilot.pause()
            await pilot.click("#success-close")
            await pilot.pause()

            envelope = CredentialStore(path=store_path).load()
            assert ProviderName.ANTHROPIC in envelope.providers
            assert envelope.providers[ProviderName.ANTHROPIC].access_token == "sk-smoke"
