"""TUI command and footer coverage for Context Window Snapshot (spec 62.a.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.compaction.compacter import Compacter
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.slash_router import SlashRouter
from src.tui.widgets.usage_status_bar import UsageStatusBar


def _usage_snapshot(*, snapshot: ContextWindowSnapshotDAO) -> SessionUsageSnapshotDAO:
    """Build a minimal usage snapshot carrying a context-window snapshot.

    Args:
        snapshot (ContextWindowSnapshotDAO): Snapshot to publish.

    Returns:
        SessionUsageSnapshotDAO: Usage snapshot with the context field set.
    """
    return SessionUsageSnapshotDAO(
        active_model_name="gpt-5.4",
        active_reasoning_level="high",
        context_window_snapshot=snapshot,
    )


def _session(monkeypatch: pytest.MonkeyPatch) -> SloAgentSession:
    """Build a prebuilt-agent session for the /context-window advisory boundary.

    Args:
        monkeypatch (pytest.MonkeyPatch): Environment mutator; pins the global
            default model so the advisory's model identity is deterministic.

    Returns:
        SloAgentSession: Session wrapping a faux model.
    """
    # cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
    # is captured at config.cfg import, before this helper's patch.
    monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _snapshot(*, estimate_available: bool = True) -> ContextWindowSnapshotDAO:
    """Build a stable snapshot for presentation tests.

    Args:
        estimate_available (bool): Whether the durable estimate is available.

    Returns:
        ContextWindowSnapshotDAO: Presentation fixture.
    """
    return ContextWindowSnapshotDAO(
        model_name="gpt-5.6-terra",
        context_window_tokens=1_050_000,
        estimated_used_tokens=782_250 if estimate_available else 0,
        available_tokens=267_750 if estimate_available else 1_050_000,
        consumed_percent=74.5 if estimate_available else 0.0,
        estimate_available=estimate_available,
    )


@pytest.mark.asyncio
async def test_context_window_renders_snapshot_and_requests_measurement() -> None:
    """The command formats absolute Context Window Snapshot values exactly."""
    session: MagicMock = MagicMock()
    session.refresh_context_window_snapshot = AsyncMock(
        return_value=_usage_snapshot(snapshot=_snapshot()),
    )
    session.context_window_snapshot = AsyncMock()

    result = await SlashRouter.dispatch(line="/context-window", session=session)

    assert result.rendered == (
        "context window (gpt-5.6-terra): 1,050,000 tok total · 782,250 tok used"
        " · 267,750 tok available · 74.5% used"
    )
    assert result.refresh_context_window is True
    assert result.refresh_usage_status is False
    session.context_window_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_window_at_threshold_emits_one_advisory_without_compacting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/context-window enters the snapshot-refresh advisory boundary."""
    session: SloAgentSession = _session(monkeypatch=monkeypatch)
    advised: list[AgentStreamEventDAO] = []

    async def _capture(event: AgentStreamEventDAO) -> None:
        """Append one dispatched event."""
        advised.append(event)

    session.subscribe(handler=_capture)
    snapshot: ContextWindowSnapshotDAO = ContextWindowSnapshotDAO(
        model_name="gpt-5.4",
        context_window_tokens=1_000_000,
        estimated_used_tokens=256_000,
        available_tokens=744_000,
        consumed_percent=25.6,
        estimate_available=True,
    )
    with (
        patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(return_value=snapshot),
        ),
        patch.object(Compacter, "compact", new=AsyncMock()) as mock_compact,
    ):
        result = await SlashRouter.dispatch(line="/context-window", session=session)

    advisories: list[AgentStreamEventDAO] = [event for event in advised if event.kind == "compaction_advised"]
    assert len(advisories) == 1
    assert result.rendered == (
        "context window (gpt-5.4): 1,000,000 tok total · 256,000 tok used"
        " · 744,000 tok available · 25.6% used"
    )
    assert result.refresh_context_window is True
    mock_compact.assert_not_called()


@pytest.mark.asyncio
async def test_compact_renders_session_detail_and_only_requests_cached_repaint() -> None:
    """Manual Compaction output comes from the typed session result."""
    session: MagicMock = MagicMock()
    session.compact_context = AsyncMock(
        return_value=ManualCompactionResultDAO(
            status="unavailable",
            detail="cannot compact while a prompt is in flight; run /abort first",
        )
    )

    result = await SlashRouter.dispatch(line="/compact", session=session)

    assert result.rendered == "cannot compact while a prompt is in flight; run /abort first"
    assert result.refresh_context_window is False
    assert result.refresh_usage_status is True


@pytest.mark.parametrize(
    ("status", "detail", "expected"),
    [
        ("compacted", None, "compaction complete"),
        ("nothing_to_compact", None, "nothing to compact"),
        ("unavailable", None, "compaction is unavailable"),
        ("failed", None, "compaction failed"),
    ],
)
def test_compaction_formatters_have_distinct_status_fallbacks(
    status: Literal["compacted", "nothing_to_compact", "unavailable", "failed"],
    detail: str | None,
    expected: str,
) -> None:
    """Unavailable and failed statuses keep separate exact fallback text.

    Args:
        status (str): Terminal Manual Compaction status.
        detail (str | None): Optional session-supplied detail.
        expected (str): Required formatter output.
    """
    result = ManualCompactionResultDAO(status=status, detail=detail)
    assert SlashRouter._format_manual_compaction(result=result) == expected


def test_compaction_failure_detail_is_returned_when_present() -> None:
    """A failed /compact shows the session's safe detail, not the generic fallback."""
    result = ManualCompactionResultDAO(
        status="failed",
        detail="RuntimeError: Unsupported parameter: max_output_tokens",
    )
    assert (
        SlashRouter._format_manual_compaction(result=result)
        == "RuntimeError: Unsupported parameter: max_output_tokens"
    )


def test_slash_router_imports_no_history_or_compaction_primitives() -> None:
    """The router consumes session contracts rather than lower-layer primitives."""
    source = Path("src/tui/slash_router.py").read_text(encoding="utf-8")
    for forbidden in ("Compacter", "CompactedSessionUpdater", "CompactionChecker", "SessionHistoryProjector"):
        assert forbidden not in source


async def test_context_commands_reject_arguments_before_touching_session() -> None:
    """Both zero-argument commands preserve their exact usage strings."""
    session: MagicMock = MagicMock()
    session.refresh_context_window_snapshot = AsyncMock()
    session.compact_context = AsyncMock()

    context_result = await SlashRouter.dispatch(line="/context-window now", session=session)
    compact_result = await SlashRouter.dispatch(line="/compact all", session=session)

    assert context_result.rendered == "usage: /context-window"
    assert compact_result.rendered == "usage: /compact"
    session.refresh_context_window_snapshot.assert_not_awaited()
    session.compact_context.assert_not_awaited()


def test_usage_status_bar_renders_context_percentage_without_provider_usage() -> None:
    """Footer Context Window Snapshot is independent from billing telemetry."""
    snapshot = SessionUsageSnapshotDAO(
        active_model_name="gpt-5.6-terra",
        active_reasoning_level="high",
        usage_available=False,
        context_window_snapshot=_snapshot(),
    )

    rendered = UsageStatusBar._render_snapshot(snapshot=snapshot)

    assert "usage unavailable" in rendered
    assert rendered.endswith("74.5% context used")
