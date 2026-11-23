"""108.1 §5.5 / §6 journeys: ``/queue cancel``, ``/queue edit`` and prompts sent before the model is ready.

Each test drives the real mounted ``SloTUI`` with Pilot and a real session,
real SQLite history and the real channel queue. Only the provider boundary is
doubled: ``GatedFauxChatModel`` holds the first model call and records every
provider call, and the model-catalog fetch is held or answered at its client
boundary. Rows are read back from ``channels.db`` and from the recorded calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import patch
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui._scroll_settle import pump_until
from tests.tui.test_channel_adapter import (
    GatedFauxChatModel,
    _build_session,
    _open_gateway,
    _transcript_lines,
    _user_echo_texts,
    _wait_until_db,
)

_QUEUE_SETTLE_SECONDS: float = 15.0


async def _prompts_for(*, gateway: ChannelGateway, session: SloAgentSession) -> list[ChannelMessageDAO]:
    """Return every operator prompt row of one session, in queue order.

    Args:
        gateway (ChannelGateway): Gateway over the queue under test.
        session (SloAgentSession): Session whose conversation is read.

    Returns:
        list[ChannelMessageDAO]: Prompt rows, oldest first.
    """
    agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)
    conversation: list[ChannelMessageDAO] = await gateway.repository.conversation(agent_session_id=agent_id)
    return [row for row in conversation if row.message_type == "prompt"]


def _row_named(*, rows: list[ChannelMessageDAO], text: str) -> ChannelMessageDAO:
    """Return the single row whose body equals ``text``.

    Args:
        rows (list[ChannelMessageDAO]): Rows to search.
        text (str): Exact message body.

    Returns:
        ChannelMessageDAO: The matching row.
    """
    [match] = [row for row in rows if row.message_contents == text]
    return match


class _QueueScenario:
    """One held run ("one") with two pending rows ("two", "three") in a mounted TUI."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Build the held-run model, the real session and the real gateway.

        Args:
            tmp_path (Path): Temp root for history and ``channels.db``.
        """
        self.release_first_run: asyncio.Event = asyncio.Event()
        self.model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="answer one"), AIMessage(content="answer survivor")],
            first_call_release=self.release_first_run,
        )
        self.session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=self.model)
        self.gateway: Optional[ChannelGateway] = None
        self._tmp_path: Path = tmp_path

    async def open(self) -> SloTUI:
        """Open the real gateway and build the mounted app over it.

        Returns:
            SloTUI: The app, not yet mounted.
        """
        self.gateway = await _open_gateway(tmp_path=self._tmp_path)
        return SloTUI(session=self.session, channel_gateway=self.gateway)

    async def close(self) -> None:
        """Release the held provider call, stop delivery and close the gateway."""
        self.release_first_run.set()
        await self.session.stop_channel_delivery(reason="test_done")
        assert self.gateway is not None
        await self.gateway.close()


async def _submit(*, pilot, prompt_input: PromptInputComponent, text: str) -> None:
    """Type one line into the prompt box and press Enter.

    Args:
        pilot: Textual Pilot driving the mounted app.
        prompt_input (PromptInputComponent): The prompt box.
        text (str): Text submitted as an operator line.
    """
    prompt_input.text = text
    await pilot.press("enter")


class TestQueueCancelCommands:
    """A5 / 1081-R03: ``/queue cancel <n>|all`` cancels pending rows with reason ``operator``; they never run."""

    async def test_queue_cancel_n_cancels_that_pending_row_and_it_never_runs(self, tmp_path: Path) -> None:
        """``/queue cancel 1`` removes the first pending row; the other pending row still runs once."""
        scenario: _QueueScenario = _QueueScenario(tmp_path=tmp_path)
        app: SloTUI = await scenario.open()
        assert scenario.gateway is not None
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = scenario.session.channel_poller
                assert poller is not None
                await _submit(pilot=pilot, prompt_input=prompt_input, text="one")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["one"],
                )
                for text in ("two", "three"):
                    await _submit(pilot=pilot, prompt_input=prompt_input, text=text)

                async def _two_rows_pending() -> bool:
                    return [row.message_contents for row in await poller.pending_prompts()] == ["two", "three"]

                await _wait_until_db(predicate=_two_rows_pending, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="/queue cancel 1")

                async def _two_cancelled() -> bool:
                    rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                    return _row_named(rows=rows, text="two").cancelled_at is not None

                await _wait_until_db(predicate=_two_cancelled, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                scenario.release_first_run.set()

                async def _survivor_replied() -> bool:
                    rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                    return await scenario.gateway.reply_for(message_id=_row_named(rows=rows, text="three").id) is not None

                await _wait_until_db(predicate=_survivor_replied, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                await pump_until(pilot=pilot, predicate=lambda: poller.busy is False)
                rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                cancelled = _row_named(rows=rows, text="two")
                survivor = _row_named(rows=rows, text="three")
                assert await scenario.gateway.reply_for(message_id=cancelled.id) is None
        finally:
            await scenario.close()

        assert (cancelled.cancel_reason, cancelled.accepted_at) == ("operator", None)
        assert survivor.accepted_at is not None
        assert all("two" not in call for call in scenario.model.provider_calls)
        assert sum("three" in call for call in scenario.model.provider_calls) == 1

    async def test_queue_cancel_all_cancels_every_pending_row_and_only_the_running_row_runs(
        self, tmp_path: Path
    ) -> None:
        """``/queue cancel all`` cancels every pending row with reason ``operator``; the running row finishes."""
        scenario: _QueueScenario = _QueueScenario(tmp_path=tmp_path)
        app: SloTUI = await scenario.open()
        assert scenario.gateway is not None
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = scenario.session.channel_poller
                assert poller is not None
                await _submit(pilot=pilot, prompt_input=prompt_input, text="one")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["one"],
                )
                for text in ("two", "three"):
                    await _submit(pilot=pilot, prompt_input=prompt_input, text=text)

                async def _two_rows_pending() -> bool:
                    return [row.message_contents for row in await poller.pending_prompts()] == ["two", "three"]

                await _wait_until_db(predicate=_two_rows_pending, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="/queue cancel all")

                async def _both_cancelled() -> bool:
                    rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                    return all(row.cancelled_at is not None for row in rows if row.message_contents != "one")

                await _wait_until_db(predicate=_both_cancelled, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                scenario.release_first_run.set()
                await pump_until(pilot=pilot, predicate=lambda: poller.busy is False)
                rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
        finally:
            await scenario.close()

        by_text = {row.message_contents: row for row in rows}
        assert [by_text[text].cancel_reason for text in ("two", "three")] == ["operator", "operator"]
        assert by_text["one"].accepted_at is not None
        assert all("two" not in call and "three" not in call for call in scenario.model.provider_calls)

    async def test_queue_edit_n_cancels_the_row_and_restores_its_text_to_the_prompt_box(
        self, tmp_path: Path
    ) -> None:
        """``/queue edit 2`` cancels the second pending row (operator reason) and puts its text in the prompt box."""
        scenario: _QueueScenario = _QueueScenario(tmp_path=tmp_path)
        app: SloTUI = await scenario.open()
        assert scenario.gateway is not None
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = scenario.session.channel_poller
                assert poller is not None
                await _submit(pilot=pilot, prompt_input=prompt_input, text="one")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["one"],
                )
                for text in ("two", "three"):
                    await _submit(pilot=pilot, prompt_input=prompt_input, text=text)

                async def _two_rows_pending() -> bool:
                    return [row.message_contents for row in await poller.pending_prompts()] == ["two", "three"]

                await _wait_until_db(predicate=_two_rows_pending, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="/queue edit 2")

                async def _three_cancelled() -> bool:
                    rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                    return _row_named(rows=rows, text="three").cancelled_at is not None

                await _wait_until_db(predicate=_three_cancelled, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                await pump_until(pilot=pilot, predicate=lambda: prompt_input.text == "three")
                scenario.release_first_run.set()
                await _wait_until_db(
                    predicate=lambda: _prompts_settled(scenario=scenario, texts=("one", "two")),
                    timeout_seconds=_QUEUE_SETTLE_SECONDS,
                )
                await pump_until(pilot=pilot, predicate=lambda: poller.busy is False)
                rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
                edited_text: str = prompt_input.text
        finally:
            await scenario.close()

        edited = _row_named(rows=rows, text="three")
        assert (edited.cancel_reason, edited.accepted_at) == ("operator", None)
        assert edited_text == "three"
        assert all("three" not in call for call in scenario.model.provider_calls)


async def _prompts_settled(*, scenario: _QueueScenario, texts: tuple[str, ...]) -> bool:
    """Return whether every named prompt row has a reply.

    Args:
        scenario (_QueueScenario): Scenario whose gateway is read.
        texts (tuple[str, ...]): Bodies of the rows that must have replies.

    Returns:
        bool: True once each named row has its reply.
    """
    assert scenario.gateway is not None
    rows = await _prompts_for(gateway=scenario.gateway, session=scenario.session)
    for text in texts:
        if await scenario.gateway.reply_for(message_id=_row_named(rows=rows, text=text).id) is None:
            return False
    return True


class TestPromptSentBeforeModelReadiness:
    """1081-R04: a prompt sent while the model is not ready is persisted pending, then runs exactly once."""

    async def test_prompt_sent_while_the_model_is_pending_waits_as_a_row_and_runs_once_when_ready(
        self, tmp_path: Path
    ) -> None:
        """Submit while preparation is held: a pending row exists and no provider call is made.

        Releasing the catalog boundary makes the session ready; the poller then runs
        that row exactly once and writes its reply.
        """
        catalog_release: asyncio.Event = asyncio.Event()

        async def _held_catalog(*, model_names: tuple[str, ...]) -> object:
            """Answer the catalog boundary only after the test releases it."""
            await catalog_release.wait()
            return SeedModelCatalog.load()

        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="ready answer")],
            first_call_release=asyncio.Event(),
        )
        model.first_call_release.set()
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
            workdir=tmp_path,
            session_id=str(uuid4()),
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=True),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
            pending_preparation=True,
        )
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            with patch.object(ModelCatalogService, "prepare_models", side_effect=_held_catalog):
                async with app.run_test() as pilot:
                    await pilot.pause()
                    assert session.preparation_status == "pending"
                    prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                    await _submit(pilot=pilot, prompt_input=prompt_input, text="hello")

                    async def _hello_pending() -> bool:
                        rows = await _prompts_for(gateway=gateway, session=session)
                        return [(row.message_contents, row.accepted_at) for row in rows] == [("hello", None)]

                    await _wait_until_db(predicate=_hello_pending, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                    assert model.provider_calls == []

                    catalog_release.set()

                    async def _hello_replied() -> bool:
                        rows = await _prompts_for(gateway=gateway, session=session)
                        return await gateway.reply_for(message_id=rows[0].id) is not None

                    await _wait_until_db(predicate=_hello_replied, timeout_seconds=_QUEUE_SETTLE_SECONDS)
                    await pump_until(pilot=pilot, predicate=lambda: session.preparation_status == "ready")
                    rows = await _prompts_for(gateway=gateway, session=session)
                    reply = await gateway.reply_for(message_id=rows[0].id)
        finally:
            catalog_release.set()
            await session.stop_channel_delivery(reason="test_done")
            await gateway.close()

        assert rows[0].accepted_at is not None
        assert reply is not None and reply.message_contents == "ready answer"
        assert sum("hello" in call for call in model.provider_calls) == 1
        assert len(model.provider_calls) == 1

