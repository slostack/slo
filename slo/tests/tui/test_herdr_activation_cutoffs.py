"""Finite shared-runtime continuation cutoffs in a mounted, offline Textual app."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI


@pytest.mark.parametrize("phase", ["delivery", "activation", "context"])
@pytest.mark.parametrize("cutoff", ["closing", "identity"])
@pytest.mark.parametrize("fails", [False, True])
async def test_shared_runtime_await_cutoff(tmp_path: Path, phase: str, cutoff: str, fails: bool) -> None:
    """Every shared-runtime await revalidates its captured owner before later work.

    The phase barrier is an orchestration boundary, not reporter wire evidence.
    The app is genuinely mounted; its original delivery resources are cleaned by
    public unmount. No provider or enabled Herdr executable is used.
    """
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        successor = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            entered = asyncio.Event()
            release = asyncio.Event()
            calls: list[str] = []

            async def step(*, name: str) -> None:
                """Pause precisely at the selected await, optionally failing late."""
                calls.append(name)
                if name == phase:
                    entered.set()
                    await release.wait()
                    if fails:
                        raise RuntimeError("private cutoff sentinel")

            async def delivery() -> None:
                """Observe delivery admission."""
                await step(name="delivery")

            async def activation(*, interactive: bool) -> None:
                """Observe captured-session activation admission."""
                assert interactive
                await step(name="activation")

            async def context() -> None:
                """Observe context admission."""
                await step(name="context")

            with (
                patch.object(app, "_initialize_session_delivery", side_effect=delivery),
                patch.object(session, "start_external_reporting", side_effect=activation),
                patch.object(session, "refresh_context_window_snapshot", side_effect=context),
                patch.object(app, "_rollback_session_delivery") as rollback,
                patch.object(app, "_refresh_title_bar") as title,
                patch.object(app, "_refresh_usage_status_bar") as usage,
                patch.object(app, "_start_session_preparation") as preparation,
                patch.object(app, "_write_adapter_line", side_effect=RuntimeError("notice fault")),
            ):
                task = asyncio.create_task(coro=app._finish_replacement_runtime())
                try:
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    if cutoff == "closing":
                        app._app_closing = True
                    else:
                        app._session = successor
                    release.set()
                    await asyncio.wait_for(task, timeout=5)
                    expected = ["delivery", "activation", "context"]
                    assert calls == expected[: expected.index(phase) + 1]
                    title.assert_not_called()
                    usage.assert_not_called()
                    preparation.assert_not_called()
                    assert rollback.await_count == int(fails and phase == "delivery")
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
                    # Restore only the synthetic selection displacement for the
                    # mounted original owner's genuine public cleanup.
                    app._session = session
        await successor.dispose_unmounted_session()


@pytest.mark.parametrize("cutoff", ["closing", "identity"])
@pytest.mark.parametrize("fails", [False, True])
async def test_preparation_completion_cutoff(tmp_path: Path, cutoff: str, fails: bool) -> None:
    """A late catalog success or error cannot repaint either closed or replaced UI."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
    successor = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def prepare() -> None:
            """Hold catalog completion without a remote discovery request."""
            entered.set()
            await release.wait()
            if fails:
                raise RuntimeError("private preparation sentinel")

        with (
            patch.object(session, "prepare_startup", side_effect=prepare),
            patch.object(app, "_write_adapter_line") as notice,
            patch.object(app, "_refresh_title_bar") as title,
            patch.object(app, "_refresh_usage_status_bar") as usage,
        ):
            task = asyncio.create_task(coro=app._prepare_mounted_session(session=session))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                if cutoff == "closing":
                    app._app_closing = True
                else:
                    app._session = successor
                release.set()
                await asyncio.wait_for(task, timeout=5)
                notice.assert_not_called()
                title.assert_not_called()
                usage.assert_not_called()
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                app._session = session
    await successor.dispose_unmounted_session()


@pytest.mark.parametrize(
    ("phase", "fails"),
    [("hydration", False)]
    + [
        (phase, fails) for phase in ("notice", "delivery", "activation", "context") for fails in (False, True)
    ],
)
async def test_mount_public_unmount_blocks_focus_and_auth(tmp_path: Path, phase: str, fails: bool) -> None:
    """Close through the public gateway during each real mount continuation.

    Original operations complete behind deterministic barriers. The hydration
    helper already contains replay faults, so its boundary is success-only.
    """
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        app = SloTUI(session=session)
        entered = asyncio.Event()
        release = asyncio.Event()
        sealed = asyncio.Event()
        calls: list[str] = []
        hydrate = app._hydrate_transcript_from_history
        notice = app._maybe_render_startup_notice
        delivery = app._initialize_session_delivery
        activate = session.start_external_reporting
        context = session.refresh_context_window_snapshot
        begin_close = session.begin_external_reporting_close

        async def barrier(name: str) -> None:
            """Pause the selected completed operation before its caller continues."""
            calls.append(name)
            if name != phase:
                return
            entered.set()
            await release.wait()
            if fails and phase != "hydration":
                raise RuntimeError("private mount sentinel")

        async def hydration() -> None:
            """Run actual replay before its continuation barrier."""
            await hydrate()
            await barrier("hydration")

        async def startup_notice() -> None:
            """Run actual notice before its continuation barrier."""
            try:
                await notice()
            finally:
                await barrier("notice")

        async def initialize() -> None:
            """Run real lease/timer setup before its continuation barrier."""
            await delivery()
            await barrier("delivery")

        async def reporting(*, interactive: bool) -> None:
            """Run the disabled reporting gateway before its barrier."""
            await activate(interactive=interactive)
            await barrier("activation")

        async def refresh_context() -> None:
            """Run real context refresh before its continuation barrier."""
            await context()
            await barrier("context")

        def closing() -> None:
            """Observe the public unmount prefix without assigning closing flags."""
            begin_close()
            assert app._app_closing and app._delivery_quiescing
            sealed.set()

        async def close_at_barrier() -> None:
            """Release mount only after public shutdown has sealed admission."""
            await asyncio.wait_for(entered.wait(), timeout=5)
            shutdown = asyncio.create_task(coro=app.on_unmount())
            try:
                await asyncio.wait_for(sealed.wait(), timeout=5)
            finally:
                release.set()
            await asyncio.wait_for(shutdown, timeout=5)

        with (
            patch.object(app, "_hydrate_transcript_from_history", side_effect=hydration),
            patch.object(app, "_maybe_render_startup_notice", side_effect=startup_notice),
            patch.object(app, "_initialize_session_delivery", side_effect=initialize),
            patch.object(session, "start_external_reporting", side_effect=reporting),
            patch.object(session, "refresh_context_window_snapshot", side_effect=refresh_context),
            patch.object(session, "begin_external_reporting_close", side_effect=closing),
            patch.object(PromptInput, "focus", autospec=True) as focus,
            patch.object(app, "_has_credential_for_active_model", return_value=False) as credential,
            patch.object(app, "_push_auth_modal") as auth,
            patch.object(app, "_start_session_preparation") as preparation,
            patch.object(app, "_write_adapter_line", side_effect=RuntimeError("notice fault")),
        ):
            driver = asyncio.create_task(coro=close_at_barrier())
            try:
                async with app.run_test() as pilot:
                    await driver
                    await pilot.pause()
                    phases = ["hydration", "notice", "delivery", "activation", "context"]
                    assert calls == phases[: phases.index(phase) + 1]
                    focus.assert_not_called()
                    credential.assert_not_called()
                    auth.assert_not_called()
                    preparation.assert_not_called()
                    assert app._lease_timer is None and app._inbox_timer is None
                    assert app._app_shutdown_task is not None and app._app_shutdown_task.done()
                    assert app._app_closing and app._delivery_quiescing
            finally:
                release.set()
                await asyncio.gather(driver, return_exceptions=True)
