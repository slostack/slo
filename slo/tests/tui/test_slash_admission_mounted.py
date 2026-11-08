"""Mounted command admission with a controlled preparation boundary."""

import asyncio
from pathlib import Path

import pytest

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui.test_code_command import transcript_lines


class HeldPreparationSession(SloAgentSession):
    """Keep startup pending without network work; record explicit refresh requests."""

    def __init__(self, *, workdir: Path, pending: bool) -> None:
        """Inject a model that must remain unused by these slash commands."""
        super().__init__(
            agent=SloAgent(llm=FauxChatModel(responses=[]), cwd=str(workdir), tools=[]),
            workdir=workdir,
            session_id="admission-session",
            pending_preparation=pending,
        )
        self.preparation_entered = asyncio.Event()
        self.refresh_calls: int = 0

    async def prepare_startup(self) -> None:
        """Hold app-owned startup until its normal shutdown cancellation."""
        self.preparation_entered.set()
        await asyncio.Event().wait()

    async def refresh_model_catalog(self) -> str:
        """Record catalog refresh without invoking a vendor catalog endpoint."""
        self.refresh_calls += 1
        return "Catalog refresh recorded."


@pytest.mark.parametrize("pending", [True, False])
@pytest.mark.parametrize(
    "line",
    [
        "/auth",
        "/help",
        "/quit",
        "/exit",
        "/q",
        "/clear",
        "/model",
        "/code missing-file",
        "/h",
        "/?",
        "/unknown",
        "/HELP",
        "/cwd",
        "/abort",
        "/model refresh",
        "/model  refresh",
        "/model Refresh",
        "/model refresh extra",
    ],
)
async def test_mounted_preparing_and_ready_command_matrix(tmp_path: Path, pending: bool, line: str) -> None:
    """Enter reaches real routing and UI effects without broadening pending aliases."""
    session = HeldPreparationSession(workdir=tmp_path, pending=pending)
    app = SloTUI(session=session)
    allowed: set[str] = {"/auth", "/help", "/quit", "/exit", "/q", "/clear", "/model", "/code"}
    rejected: bool = pending and line.split()[0] not in allowed
    async with app.run_test() as pilot:
        await pilot.pause()
        if pending:
            assert session.preparation_entered.is_set()
        app.query_one(PromptInputComponent).text = line
        await pilot.press("enter")
        await pilot.pause()
        lines: list[str] = [text for text, _ in transcript_lines(app=app)]
        assert ("Model preparation required." in lines) is rejected
        assert session.refresh_calls == int(
            line == "/model  refresh" or (line == "/model refresh" and not pending)
        )
        if rejected or (pending and line == "/model refresh"):
            return
        if line in {"/quit", "/exit", "/q"}:
            assert not app.is_running
        elif line == "/auth":
            assert len(app.screen_stack) == 2
        elif line in {"/help", "/h", "/?"}:
            assert any("/help" in text and "/clear" in text for text in lines)
        elif line == "/model":
            assert any(text.startswith("models:") for text in lines)
        elif line == "/cwd":
            assert any(str(tmp_path) in text for text in lines)
        elif line == "/clear":
            assert not lines
        elif line in {"/unknown", "/HELP"}:
            assert any("unknown command:" in text for text in lines)
        elif line.startswith("/model") and "refresh recorded" not in " ".join(lines):
            assert any("model" in text.lower() for text in lines)
        assert not session.is_running
