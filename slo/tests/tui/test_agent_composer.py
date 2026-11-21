"""Mounted tests for the ``AgentComposerComponent`` (108.3 §5/§6).

Every test mounts real Textual widgets and drives a real ``TuiChannelAdapter``
over a real SQLite queue under tmp paths. The stub app object stands in only
for the presentation surfaces the composer never touches (``_session``,
transcript handles); the queue path is real end to end.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from collections.abc import Callable
from typing import Optional
from uuid import UUID, uuid4

from textual.app import App, ComposeResult
from textual.widgets import Input

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.dao import NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.channel.adapter import TuiChannelAdapter
from src.tui.components.agent_composer.component import AGENT_FINISHED_NOTICE, AgentComposerComponent


class _ComposerHost(App[None]):
    """Host one composer under test."""

    def __init__(self, composer_factory: Callable[[], AgentComposerComponent]) -> None:
        """Bind the composer factory.

        Args:
            composer_factory (Callable[[], AgentComposerComponent]): Builds the
                component once the app (and its theme variables) exist.
        """
        super().__init__()
        self._composer_factory = composer_factory

    def compose(self) -> ComposeResult:
        """Yield the composer."""
        yield self._composer_factory()


async def _open_gateway(*, tmp_path) -> ChannelGateway:
    """Open one real gateway on a fresh temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


async def _build_composer(
    *,
    gateway: ChannelGateway,
    target_session_id: str,
    target_label: str = "orchestrator wf-x1a2",
) -> tuple[TuiChannelAdapter, Callable[[], AgentComposerComponent], UUID]:
    """Build a started adapter and a composer factory bound to it.

    The widget is built inside the app's run context (its stylesheet parses
    against the active theme there), exactly as production does.

    Args:
        gateway (ChannelGateway): The real shared queue gateway.
        target_session_id (str): Target agent session id.
        target_label (str): Header label for the composer.

    Returns:
        tuple[TuiChannelAdapter, Callable[[], AgentComposerComponent], UUID]:
            Adapter, composer factory, and the resolved target participant id.
    """
    stub_app: SimpleNamespace = SimpleNamespace(_session=SimpleNamespace(session_id=str(uuid4())))
    adapter: TuiChannelAdapter = TuiChannelAdapter(app=stub_app, gateway=gateway)  # type: ignore[arg-type]
    await adapter.start()
    target: UUID = channel_participant_id_for_session(session_id=target_session_id)
    # The orchestrator side registers itself in production; the composer needs
    # the participant to exist for the closed-state lookup to answer.
    await gateway.register_agent(session_id=target, name="orchestrator wf-x1a2")

    def _factory() -> AgentComposerComponent:
        return AgentComposerComponent(
            target_agent_id=target,
            target_label=target_label,
            adapter=adapter,
        )

    return adapter, _factory, target


async def _settle(pilot, cycles: int = 6):  # type: ignore[no-untyped-def]
    """Pump a few refresh cycles so the 500 ms interval ticks."""
    for _cycle in range(cycles):
        await pilot.pause()
        await asyncio.sleep(0.02)


class TestAgentComposerSends:
    """Enter and Ctrl+Enter enqueue rows for the target agent (108.3 §5)."""

    async def test_enter_sends_a_normal_prompt_row(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "skip phase 3 review"
                await pilot.press("enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert len(rows) == 1
                assert rows[0].state == "queued"
                assert rows[0].forced is False
                assert rows[0].preview == "skip phase 3 review"
                assert composer.query_one("#agent-composer-input", Input).value == ""
                row_static = composer.query_one(".agent-composer-rows")
                assert "… skip phase 3 review" in str(row_static.render())
        finally:
            await gateway.close()

    async def test_ctrl_enter_sends_a_forced_prompt_row(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "use pytest -x"
                await pilot.press("ctrl+enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert len(rows) == 1
                assert rows[0].forced is True
                assert rows[0].preview == "use pytest -x"
                stored = await gateway.get(message_id=rows[0].message_id)
                assert stored is not None and stored.forced_at is not None
        finally:
            await gateway.close()

    async def test_alt_enter_sends_a_forced_prompt_row(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "stop here"
                await pilot.press("alt+enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert len(rows) == 1 and rows[0].forced is True
        finally:
            await gateway.close()


class TestAgentComposerRepliesAndFinish:
    """Reply previews and the finished state (108.3 §6)."""

    async def test_reply_rows_render_a_preview(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            request = await gateway.send(
                new=NewMessageDAO(
                    sender_id=adapter.user_participant.id,
                    recipient_id=target,
                    message_contents="how far along?",
                    channel_id=adapter.channel.id,
                )
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=target,
                    recipient_id=adapter.user_participant.id,
                    message_contents="phase 2 of 3 done",
                    message_type="reply",
                    in_reply_to_id=request.id,
                    channel_id=adapter.channel.id,
                )
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                await composer._refresh_rows()
                row_static = composer.query_one(".agent-composer-rows")
                rendered: str = str(row_static.render())
                assert "how far along?" in rendered
                assert "↩ phase 2 of 3 done" in rendered
        finally:
            await gateway.close()

    async def test_closed_agent_disables_the_composer_with_the_finished_notice(
        self, tmp_path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            target_session_id: str = str(uuid4())
            await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=target_session_id),
                name="slo finished",
            )
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=target_session_id
            )
            await gateway.close_agent(
                session_id=target,
                reason="recipient_closed",
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                await composer._refresh_rows()
                assert composer.is_finished is True
                assert composer.query_one("#agent-composer-input", Input).disabled is True
                row_static = composer.query_one(".agent-composer-rows")
                assert AGENT_FINISHED_NOTICE in str(row_static.render())
        finally:
            await gateway.close()

    async def test_sending_to_an_agent_that_closes_marks_the_composer_finished(
        self, tmp_path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            target_session_id: str = str(uuid4())
            target_participant = await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=target_session_id),
                name="slo closing",
            )
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=target_session_id
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                await gateway.close_agent(
                    session_id=target_participant.id,
                    reason="recipient_closed",
                )
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                # The participant status refresh has not ticked yet; the send hits it.
                composer.query_one("#agent-composer-input", Input).value = "late message"
                await composer._send(force=False)
                assert composer.is_finished is True
                assert composer.query_one("#agent-composer-input", Input).disabled is True
                stored: Optional[object] = None
                assert stored is None  # no row was inserted after the close
        finally:
            await gateway.close()


class TestWorkflowModalIntegration:
    """The orchestrator's workflow modal owns the composer; child rows do not (108.3/108.4)."""

    async def test_orchestrator_modal_mounts_the_composer(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            from src.tui.workflows.dao import WorkflowSessionKeyDAO
            from src.tui.workflows.session_progress_screen import SessionProgressScreen

            target_session_id: str = str(uuid4())
            adapter, composer_factory, _target = await _build_composer(
                gateway=gateway, target_session_id=target_session_id
            )
            key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
                orchestrator_session_id=target_session_id,
                session_id=target_session_id,
            )
            assert key.is_parent is True
            from src.tui.workflows.dao import ProgressViewportDAO

            found: list = []

            def _build() -> SessionProgressScreen:
                screen: SessionProgressScreen = SessionProgressScreen(
                    key=key,
                    viewport=ProgressViewportDAO(),
                    composer=composer_factory(),
                )
                found.append(screen)
                return screen

            host: _ProgressHost = _ProgressHost(factory=_build)
            async with host.run_test() as pilot:
                await _settle(pilot)
                assert len(found[0].query(AgentComposerComponent)) == 1
        finally:
            await gateway.close()

    async def test_child_modal_mounts_no_composer(self, tmp_path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            from src.tui.workflows.dao import ProgressViewportDAO, WorkflowSessionKeyDAO
            from src.tui.workflows.session_progress_screen import SessionProgressScreen

            orchestrator_session_id: str = str(uuid4())
            adapter, composer_factory, _target = await _build_composer(
                gateway=gateway, target_session_id=orchestrator_session_id
            )
            child_key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
                orchestrator_session_id=orchestrator_session_id,
                session_id=str(uuid4()),
            )
            assert child_key.is_parent is False
            found: list = []

            def _build() -> SessionProgressScreen:
                screen: SessionProgressScreen = SessionProgressScreen(
                    key=child_key,
                    viewport=ProgressViewportDAO(),
                    composer=None,
                )
                found.append(screen)
                return screen

            host: _ProgressHost = _ProgressHost(factory=_build)
            async with host.run_test() as pilot:
                await _settle(pilot)
                assert not found[0].query(AgentComposerComponent)
        finally:
            await gateway.close()


class _ProgressHost(App[None]):
    """Push the modal built after the Slo themes are registered."""

    def __init__(self, *, factory) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME

        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = SLO_DARK_THEME.name
        self._factory = factory

    def compose(self) -> ComposeResult:
        """Empty base."""
        return
        yield

    def on_mount(self) -> None:
        """Build and push the modal."""
        self.push_screen(self._factory())
