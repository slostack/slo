"""Mounted tests for the ``AgentComposerComponent`` (108.3 §5/§6).

Every test mounts real Textual widgets and drives a real ``TuiChannelAdapter``
over a real SQLite queue under tmp paths. The stub app object stands in only
for the presentation surfaces the composer never touches (``_session``,
transcript handles); the queue path is real end to end.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from uuid import UUID, uuid4

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import Input, Static

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.channel.adapter import TuiChannelAdapter
from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.components.agent_composer.component import (
    AGENT_FINISHED_NOTICE,
    SEND_FAILED_NOTICE,
    SENDING_NOTICE,
    AgentComposerComponent,
)


class _ComposerHost(App[None]):
    """Host one composer under test."""

    def __init__(self, composer_factory: Callable[[], AgentComposerComponent]) -> None:
        """Bind the composer factory.

        Args:
            composer_factory (Callable[[], AgentComposerComponent]): Builds the
                component once the app (and its theme variables) exist.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name
        self._composer_factory = composer_factory

    def compose(self) -> ComposeResult:
        """Yield the composer."""
        yield self._composer_factory()


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
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


async def _settle(pilot: Pilot[None], cycles: int = 6) -> None:
    """Pump a few cycles and join the composer's queue workers."""
    for _cycle in range(cycles):
        await pilot.pause()
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.02)


class TestAgentComposerPromptAppearance:
    """The modal composer keeps resting rules quiet and brightens them on focus."""

    async def test_prompt_has_focus_sensitive_rules_and_a_visible_editing_line(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            _, composer_factory, _ = await _build_composer(gateway=gateway, target_session_id=str(uuid4()))
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test(size=(60, 20)) as pilot:
                await _settle(pilot)
                prompt: Input = app.query_one("#agent-composer-input", Input)
                for focused in (False, True):
                    app.set_focus(prompt if focused else None)
                    await pilot.pause()
                    assert prompt.styles.border_top[0] == "solid"
                    assert prompt.styles.border_bottom[0] == "solid"
                    assert prompt.styles.border_left[0] in ("", "none")
                    assert prompt.styles.border_right[0] in ("", "none")
                    expected_rule_color: str = (
                        app.get_css_variables()["accent"] if focused else app.get_css_variables()["rule"]
                    )
                    assert prompt.styles.border_top[1].hex.lower() == expected_rule_color.lower()
                    assert prompt.styles.border_bottom[1].hex.lower() == expected_rule_color.lower()
                    assert prompt.region.height == 3
                    assert prompt.content_region.height == 1
                    assert prompt.region.bottom <= app.size.height
        finally:
            await gateway.close()


class TestAgentComposerSends:
    """Enter and Ctrl+Enter enqueue rows for the target agent (108.3 §5)."""

    async def test_enter_sends_a_normal_prompt_row(self, tmp_path: Path) -> None:
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

    async def test_ctrl_enter_sends_a_forced_prompt_row(self, tmp_path: Path) -> None:
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
                stored = await gateway.find_message(message_id=rows[0].message_id)
                assert stored is not None and stored.forced_at is not None
        finally:
            await gateway.close()

    async def test_alt_enter_sends_a_forced_prompt_row(self, tmp_path: Path) -> None:
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


class _GatedSendGateway(ChannelGateway):
    """A real SQLite gateway whose ``send`` waits on a test-held gate.

    The gate is the injected public boundary the composer's outstanding
    submission crosses; every admitted send still lands in the real queue.
    """

    def __init__(self, *, repository: ChannelRepository) -> None:
        """Wrap one real repository and start with the gate closed.

        Args:
            repository (ChannelRepository): Real repository on a temp database.
        """
        super().__init__(repository=repository)
        self.release: asyncio.Event = asyncio.Event()
        self.send_started: asyncio.Event = asyncio.Event()
        self.send_calls: int = 0
        self.failure: Optional[Exception] = None

    async def send(self, *, new: NewMessageDAO) -> ChannelMessageDAO:
        """Record the call, hold until released, then fail or delegate.

        Args:
            new (NewMessageDAO): The row the composer submits.

        Returns:
            ChannelMessageDAO: The row stored by the real gateway.

        Raises:
            Exception: The configured ``failure``, if any.
        """
        self.send_calls += 1
        self.send_started.set()
        await self.release.wait()
        if self.failure is not None:
            raise self.failure
        return await super().send(new=new)


async def _open_gated_gateway(*, tmp_path: Path) -> _GatedSendGateway:
    """Open one gated gateway on a fresh real temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return _GatedSendGateway(repository=repository)


async def _pump_until(*, pilot: Pilot[None], event: asyncio.Event, timeout_seconds: float = 5.0) -> None:
    """Pump the app until a gateway event fires (without joining blocked workers)."""
    async with asyncio.timeout(timeout_seconds):
        while not event.is_set():
            await pilot.pause()
            await asyncio.sleep(0.01)


class TestAgentComposerOutstandingSubmission:
    """R7: the composer owns one outstanding submission; drafts and failures stay safe."""

    async def test_repeated_submit_while_pending_sends_the_draft_once(self, tmp_path: Path) -> None:
        gateway: _GatedSendGateway = await _open_gated_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "skip phase 3"
                await pilot.press("enter")
                await _pump_until(pilot=pilot, event=gateway.send_started)
                await pilot.press("enter")
                await pilot.press("ctrl+enter")
                await pilot.pause()
                assert composer.submission_outstanding is True
                assert SENDING_NOTICE in str(composer.query_one(".agent-composer-status", Static).render())
                gateway.release.set()
                await _settle(pilot)
                assert gateway.send_calls == 1
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert [(row.preview, row.forced) for row in rows] == [("skip phase 3", False)]
                assert composer.submission_outstanding is False
                assert composer.query_one("#agent-composer-input", Input).value == ""
        finally:
            await gateway.close()

    async def test_next_draft_typed_while_pending_survives_the_success(self, tmp_path: Path) -> None:
        gateway: _GatedSendGateway = await _open_gated_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                input_widget: Input = composer.query_one("#agent-composer-input", Input)
                input_widget.value = "first"
                await pilot.press("enter")
                await _pump_until(pilot=pilot, event=gateway.send_started)
                input_widget.value = "second draft"
                gateway.release.set()
                await _settle(pilot)
                assert input_widget.value == "second draft"
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert [row.preview for row in rows] == ["first"]
                # The kept draft is the next submission, sent once.
                await pilot.press("enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert [row.preview for row in rows] == ["second draft", "first"]
                assert input_widget.value == ""
        finally:
            await gateway.close()

    async def test_send_failure_keeps_the_draft_and_shows_a_retryable_error(self, tmp_path: Path) -> None:
        gateway: _GatedSendGateway = await _open_gated_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            gateway.failure = sqlite3.OperationalError("database is locked: /secret/path/channels.db")
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                input_widget: Input = composer.query_one("#agent-composer-input", Input)
                input_widget.value = "retry me"
                await pilot.press("enter")
                gateway.release.set()
                await _settle(pilot)
                status: str = str(composer.query_one(".agent-composer-status", Static).render())
                assert SEND_FAILED_NOTICE in status
                assert "/secret/path" not in status
                assert input_widget.value == "retry me"
                assert input_widget.disabled is False
                assert composer.is_finished is False
                assert await adapter.sent_to_agent(session_id=str(target)) == []
                gateway.failure = None
                await pilot.press("enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert [row.preview for row in rows] == ["retry me"]
                assert input_widget.value == ""
                assert SEND_FAILED_NOTICE not in str(
                    composer.query_one(".agent-composer-status", Static).render()
                )
        finally:
            await gateway.close()

    async def test_unmount_during_a_pending_send_makes_no_stale_update_or_duplicate(
        self, tmp_path: Path
    ) -> None:
        gateway: _GatedSendGateway = await _open_gated_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                input_widget: Input = composer.query_one("#agent-composer-input", Input)
                input_widget.value = "in flight"
                await pilot.press("enter")
                await _pump_until(pilot=pilot, event=gateway.send_started)
                await composer.remove()
                gateway.release.set()
                await _settle(pilot)
                assert len(app.query(AgentComposerComponent)) == 0
                assert composer.submission_outstanding is False
                assert input_widget.value == "in flight"
                assert gateway.send_calls == 1
                assert len(await adapter.sent_to_agent(session_id=str(target))) <= 1
        finally:
            await gateway.close()


class TestAgentComposerRepliesAndFinish:
    """Reply previews and the finished state (108.3 §6)."""

    async def test_reply_rows_render_a_preview(self, tmp_path: Path) -> None:
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
                await composer.refresh_delivery_state()
                row_static = composer.query_one(".agent-composer-rows")
                rendered: str = str(row_static.render())
                assert "how far along?" in rendered
                assert "↩ phase 2 of 3 done" in rendered
        finally:
            await gateway.close()

    async def test_closed_agent_disables_the_composer_with_the_finished_notice(self, tmp_path: Path) -> None:
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
                await composer.refresh_delivery_state()
                assert composer.is_finished is True
                assert composer.query_one("#agent-composer-input", Input).disabled is True
                status_static = composer.query_one(".agent-composer-status")
                assert AGENT_FINISHED_NOTICE in str(status_static.render())
        finally:
            await gateway.close()

    async def test_sending_to_an_agent_that_closes_marks_the_composer_finished(self, tmp_path: Path) -> None:
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
                await composer.send_draft(force=False)
                assert composer.is_finished is True
                assert composer.query_one("#agent-composer-input", Input).disabled is True
                # No row was inserted after the close.
                assert await adapter.sent_to_agent(session_id=str(target)) == []
        finally:
            await gateway.close()


class TestAgentComposerFinalRows:
    """R5: once the target closes, the final ack/reply/cancel rows stay visible."""

    async def test_target_closed_before_first_refresh_still_shows_final_rows(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            answered = await gateway.send(
                new=NewMessageDAO(
                    sender_id=adapter.user_participant.id,
                    recipient_id=target,
                    message_contents="skip phase 3",
                    channel_id=adapter.channel.id,
                    force=True,
                )
            )
            await gateway.accept(message_id=answered.id)
            followed_up = await gateway.send(
                new=NewMessageDAO(
                    sender_id=adapter.user_participant.id,
                    recipient_id=target,
                    message_contents="what happened?",
                    channel_id=adapter.channel.id,
                )
            )
            await gateway.accept(message_id=followed_up.id)
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=target,
                    recipient_id=adapter.user_participant.id,
                    message_contents="phase 3 skipped",
                    message_type="reply",
                    in_reply_to_id=followed_up.id,
                    channel_id=adapter.channel.id,
                )
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=adapter.user_participant.id,
                    recipient_id=target,
                    message_contents="too late",
                    channel_id=adapter.channel.id,
                )
            )
            # W closes before the composer ever mounted or refreshed.
            await gateway.close_agent(session_id=target, reason="recipient_closed")
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                assert composer.is_finished is True
                assert composer.query_one("#agent-composer-input", Input).disabled is True
                assert AGENT_FINISHED_NOTICE in str(
                    composer.query_one(".agent-composer-status", Static).render()
                )
                rendered: str = str(composer.query_one(".agent-composer-rows", Static).render())
                assert "✓ (forced) skip phase 3" in rendered
                assert "✓ what happened? ↩ phase 3 skipped" in rendered
                assert "✗ too late [recipient_closed]" in rendered
        finally:
            await gateway.close()

    async def test_abort_cancels_queued_rows_and_the_composer_shows_them(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "queued behind the run"
                await pilot.press("enter")
                await _settle(pilot)
                assert "… queued behind the run" in str(
                    composer.query_one(".agent-composer-rows", Static).render()
                )
                # W is aborted: its poller stops with reason ``aborted``.
                await gateway.close_agent(session_id=target, reason="aborted")
                await asyncio.sleep(0.6)
                await _settle(pilot)
                assert composer.is_finished is True
                rendered: str = str(composer.query_one(".agent-composer-rows", Static).render())
                assert "✗ queued behind the run [aborted]" in rendered
                composer.query_one("#agent-composer-input", Input).value = "ignored"
                await composer.send_draft(force=True)
                assert len(await adapter.sent_to_agent(session_id=str(target))) == 1
        finally:
            await gateway.close()


class TestChildComposer:
    """108.4: a child's composer sends forced by default and shows notes to the viewed agent."""

    async def test_enter_sends_forced_to_a_child(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, _factory, target = await _build_composer(gateway=gateway, target_session_id=str(uuid4()))
            app: _ComposerHost = _ComposerHost(
                composer_factory=lambda: AgentComposerComponent(
                    target_agent_id=target, target_label="review-1", adapter=adapter, default_force=True
                )
            )
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                composer.query_one("#agent-composer-input", Input).value = "only review src/tui"
                await pilot.press("enter")
                await _settle(pilot)
                rows = await adapter.sent_to_agent(session_id=str(target))
                assert [(row.preview, row.forced) for row in rows] == [("only review src/tui", True)]
                assert "send (forced)" in str(composer.query_one(".agent-composer-header", Static).render())
        finally:
            await gateway.close()

    async def test_notes_to_the_viewed_agent_are_shown(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            adapter, composer_factory, target = await _build_composer(
                gateway=gateway, target_session_id=str(uuid4())
            )
            child = await gateway.register_agent(session_id=uuid4(), name="review-1 (child of abcd1234)")
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=child.id,
                    recipient_id=target,
                    message_contents="question: is src/tui/widgets in scope?",
                    message_type="note",
                )
            )
            app: _ComposerHost = _ComposerHost(composer_factory=composer_factory)
            async with app.run_test() as pilot:
                await _settle(pilot)
                composer: AgentComposerComponent = app.query_one(AgentComposerComponent)
                rendered: str = str(composer.query_one(".agent-composer-notes", Static).render())
                assert "⊛ review-1 (child of abcd1234): question: is src/tui/widgets in scope?" in rendered
        finally:
            await gateway.close()


class TestWorkflowModalIntegration:
    """The orchestrator's workflow modal owns the composer; child rows do not (108.3/108.4)."""

    async def test_orchestrator_modal_mounts_the_composer(self, tmp_path: Path) -> None:
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

    async def test_app_builds_a_forced_by_default_composer_for_child_rows(self, tmp_path: Path) -> None:
        """108.4: the TUI's workflow modal gives child rows a composer that targets the child."""
        from langchain_core.messages import AIMessage

        from src.agents.providers.faux import FauxChatModel
        from src.agents.slo_agent.agent import SloAgent
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.tui.app import SloTUI
        from src.tui.workflows.dao import WorkflowSessionKeyDAO

        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
            ),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        orchestrator_session_id: str = str(uuid4())
        child_session_id: str = str(uuid4())
        try:
            async with app.run_test() as pilot:
                await _settle(pilot)
                child_composer: Optional[AgentComposerComponent] = app.progress_composer_for(
                    key=WorkflowSessionKeyDAO(
                        orchestrator_session_id=orchestrator_session_id, session_id=child_session_id
                    )
                )
                parent_composer: Optional[AgentComposerComponent] = app.progress_composer_for(
                    key=WorkflowSessionKeyDAO(
                        orchestrator_session_id=orchestrator_session_id, session_id=orchestrator_session_id
                    )
                )
                assert child_composer is not None and parent_composer is not None
                assert (child_composer.target_agent_id, child_composer.default_force) == (
                    UUID(child_session_id),
                    True,
                )
                assert (parent_composer.target_agent_id, parent_composer.default_force) == (
                    UUID(orchestrator_session_id),
                    False,
                )
        finally:
            await gateway.close()


class _ProgressHost(App[None]):
    """Push the modal built after the Slo themes are registered."""

    def __init__(self, *, factory: Callable[[], Screen[None]]) -> None:
        """Register the Slo themes and keep the modal factory."""
        super().__init__()
        from src.tui.theme import SLO_DEFAULT_THEME

        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name
        self._factory = factory

    def compose(self) -> ComposeResult:
        """Empty base."""
        return
        yield

    def on_mount(self) -> None:
        """Build and push the modal."""
        self.push_screen(self._factory())
