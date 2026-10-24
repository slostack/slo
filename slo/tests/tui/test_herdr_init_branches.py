"""Finite INIT branch evidence, separate from enabled reporting acceptance."""

import asyncio
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

from src.agents.slo_agent.sessions.dao import AgentEventSubscriber, SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI


def test_delivery_construction_is_inert_and_reuses_stores(tmp_path: Path) -> None:
    """Construct twice without creating history, tasks, leases or timers.

    Workflow observation now owns service construction independently of delivery.
    Both builders remain inert; delivery must reuse the observation-owned stores.
    Real initialization and teardown are exercised by the mounted ownership suite.
    """
    history_root = tmp_path / "history"
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=history_root))
    app = SloTUI(session=session)
    assert not history_root.exists()
    with patch.object(app, "set_interval") as interval:
        app._build_session_delivery(session=session)
        assert app._lease_store is not None and app._inbox_store is not None
        assert app._workflow_handle_store is None and app._workflow_app_service is None
        app._workflow_app_service = app._build_workflow_service()
        stores = (app._lease_store, app._inbox_store, app._workflow_handle_store, app._workflow_app_service)
        assert all(store is not None for store in stores)
        app._build_session_delivery(session=session)
        assert all(
            left is right
            for left, right in zip(
                stores,
                (app._lease_store, app._inbox_store, app._workflow_handle_store, app._workflow_app_service),
            )
        )
        interval.assert_not_called()
    assert not history_root.exists()
    assert app._mount_runtime_task is None
    assert app._lease_timer is None and app._inbox_timer is None
    assert session._herdr_start_task is None


@pytest.mark.parametrize("missing_root", [False, True])
async def test_historyless_initialization_has_no_delivery_effects(tmp_path: Path, missing_root: bool) -> None:
    """Refuse disabled history or an absent root without constructing collaborators."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", enable_history=False)
    )
    app = SloTUI(session=session)
    with (
        patch.object(type(session), "history_enabled", new_callable=PropertyMock, return_value=missing_root),
        patch.object(type(session), "history_root", new_callable=PropertyMock, return_value=None),
        patch.object(app, "set_interval") as interval,
        patch.object(app, "_acquire_session_lease") as acquire,
    ):
        async with app._prompt_submission_lock:
            await app._initialize_session_delivery()
        interval.assert_not_called()
        acquire.assert_not_awaited()
    assert app._lease_store is None and app._inbox_store is None
    assert app._workflow_handle_store is None and app._workflow_app_service is None
    assert app._lease_timer is None and app._inbox_timer is None
    assert app._delivery_quiescing and app._replacement_delivery_safe
    assert not (tmp_path / "history").exists()


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("pending", [False, True])
async def test_mount_phase_order_and_preparation_branch(tmp_path: Path, history: bool, pending: bool) -> None:
    """Trace mounted INIT through the retained gate for all ready/history branches.

    Reporting and catalog scheduling are recording boundaries, not enabled Herdr
    acceptance. Real delivery setup, lease persistence and unmount still execute.
    """
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", enable_history=history)
    )
    app = SloTUI(session=session)
    calls: list[str] = []
    hydrate = app._hydrate_transcript_from_history
    subscribe = session.subscribe
    delivery = app._initialize_session_delivery

    async def record_hydration() -> None:
        """Retain real replay loading before any subscription."""
        calls.append("hydrate")
        await hydrate()

    async def notice() -> None:
        """Record the optional startup notice without unrelated UI refreshes."""
        calls.append("notice")

    def record_subscription(*, handler: AgentEventSubscriber) -> None:
        """Record the real subscription before retained runtime registration."""
        calls.append("subscribe")
        subscribe(handler=handler)

    async def record_delivery() -> None:
        """Prove the registered mount task owns the gate before real delivery."""
        assert app._mount_runtime_task is asyncio.current_task()
        assert app._prompt_submission_lock.locked()
        calls.append("delivery")
        await delivery()

    async def reporting(*, interactive: bool = False) -> None:
        """Record only the app's activation delegation, not adapter acceptance."""
        assert interactive
        calls.append("reporting")

    async def context() -> None:
        """Record context refresh before presentation and preparation."""
        calls.append("context")

    def credential() -> bool:
        """Observe final focus/auth phase after retained runtime completion."""
        assert app._mount_runtime_task is not None and app._mount_runtime_task.done()
        assert app._input is not None
        focus.assert_called_with(app._input)
        calls.append("focus/auth")
        return True

    with (
        patch.object(
            type(session),
            "preparation_status",
            new_callable=PropertyMock,
            return_value="pending" if pending else "ready",
        ),
        patch.object(app, "_hydrate_transcript_from_history", side_effect=record_hydration),
        patch.object(app, "_maybe_render_startup_notice", side_effect=notice),
        patch.object(session, "subscribe", side_effect=record_subscription),
        patch.object(app, "_initialize_session_delivery", side_effect=record_delivery),
        patch.object(session, "start_external_reporting", side_effect=reporting),
        patch.object(session, "refresh_context_window_snapshot", side_effect=context),
        patch.object(app, "_refresh_title_bar", side_effect=lambda: calls.append("title")),
        patch.object(app, "_refresh_usage_status_bar", side_effect=lambda: calls.append("usage")),
        patch.object(app, "_start_session_preparation", side_effect=lambda: calls.append("prepare")),
        patch.object(app, "_has_credential_for_active_model", side_effect=credential),
        patch.object(PromptInput, "focus", autospec=True) as focus,
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert calls == [
                "hydrate",
                "notice",
                "subscribe",
                "delivery",
                "reporting",
                "context",
                "title",
                "usage",
                *(["prepare"] if pending else []),
                "focus/auth",
            ]
            assert (app._lease_timer is not None) is history
            assert (app._inbox_timer is not None) is history
            assert app._delivery_quiescing is not history
    assert app._lease_timer is None and app._inbox_timer is None
    assert app._app_closing and app._delivery_quiescing
    if history:
        assert app._lease_store is not None
        assert await app._lease_store.read(session_id=session.session_id) is None
