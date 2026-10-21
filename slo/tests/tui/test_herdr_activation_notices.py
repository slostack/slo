"""Mounted C14 optional-notice continuation, with controlled session boundaries."""

import asyncio
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


@pytest.mark.parametrize("fault", ["delivery", "activation", "context", "title", "usage", "transcript"])
async def test_open_runtime_notice_failure_preserves_preparation(tmp_path: Path, fault: str) -> None:
    """Keep later phases and real worker registration independent of optional copy.

    The mounted app uses actual delivery and public shutdown. Session operations
    are controlled orchestration boundaries, not native reporter acceptance.
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
        async with app.run_test() as pilot:
            await pilot.pause()
            calls: list[str] = []
            preparing = asyncio.Event()
            cancelled = asyncio.Event()
            delivery = app._initialize_session_delivery

            def record(name: str) -> None:
                """Record the phase before injecting its private ordinary failure."""
                calls.append(name)
                if name == fault:
                    raise RuntimeError("private runtime sentinel")

            async def initialize() -> None:
                """Keep the real delivery owner unless its boundary fails."""
                record("delivery")
                await delivery()

            async def activate(*, interactive: bool) -> None:
                """Record interactive activation without enabling an executable."""
                assert interactive
                record("activation")

            async def context() -> None:
                """Record the context boundary."""
                record("context")

            async def transcript() -> None:
                """Isolate the replacement transcript boundary."""
                record("transcript")

            async def prepare() -> None:
                """Remain owned until public shutdown cancels and retrieves us."""
                preparing.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()

            with (
                patch.object(
                    type(session), "preparation_status", new_callable=PropertyMock, return_value="pending"
                ),
                patch.object(app, "_initialize_session_delivery", side_effect=initialize),
                patch.object(session, "start_external_reporting", side_effect=activate),
                patch.object(session, "refresh_context_window_snapshot", side_effect=context),
                patch.object(app, "_refresh_title_bar", side_effect=lambda: record("title")),
                patch.object(app, "_refresh_usage_status_bar", side_effect=lambda: record("usage")),
                patch.object(app, "_refresh_replacement_ui", side_effect=transcript),
                patch.object(session, "prepare_startup", side_effect=prepare),
                patch.object(
                    app, "_write_adapter_line", side_effect=RuntimeError("private notice sentinel")
                ) as notice,
            ):
                await app._finish_replacement_ui()
                await asyncio.wait_for(preparing.wait(), timeout=5)
                task = app._preparation_task
                assert task is not None and not task.done()
                assert calls == [
                    "transcript",
                    "delivery",
                    "activation",
                    "context",
                    *([] if fault == "context" else ["title"]),
                    *([] if fault in {"context", "title"} else ["usage"]),
                ]
                assert notice.call_count == (1 if fault == "delivery" else 2)
                assert all("sentinel" not in str(call) for call in notice.call_args_list)
                await asyncio.wait_for(app.on_unmount(), timeout=5)
                assert cancelled.is_set() and task.done()
                assert app._app_shutdown_task is not None and app._app_shutdown_task.done()
                assert app._lease_timer is None and app._inbox_timer is None
                assert app._app_closing and app._delivery_quiescing
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=session.session_id) is None


@pytest.mark.parametrize("success", [False, True])
async def test_public_unmount_refuses_late_auth(tmp_path: Path, success: bool) -> None:
    """A mounted modal completion cannot refresh or reopen auth after public close."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.on_unmount()
            value = (
                CredentialDAO(
                    provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
                )
                if success
                else None
            )
            with (
                patch("src.tui.app.ModelSuggestionProjection.refresh_authentication") as projection,
                patch.object(app, "_refresh_slash_suggestions") as suggestions,
                patch.object(app, "_refresh_title_bar") as title,
                patch.object(session, "refresh_usage_snapshot") as usage,
                patch.object(app, "push_screen") as screen,
            ):
                app._on_auth_dismissed(value)
                app._push_auth_modal()
                projection.assert_not_called()
                suggestions.assert_not_called()
                title.assert_not_called()
                usage.assert_not_called()
                screen.assert_not_called()
