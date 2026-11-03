"""Mounted binding retirement and bounded memory handoff (96 revised DC04)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessageSubmissionDAO,
    MessageReceiptDAO,
)
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate
from tests.integration.test_session_messaging import read_closed_message_rows
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.commands import ReplacePromptDAO, SubmitDraftDAO
from src.tui.components.prompt_input.submission import (
    DraftHandoffDAO,
    DraftHandoffAckDAO,
    DraftHandoffError,
    DraftSubmissionDAO,
    DraftCapacityError,
    SubmissionUnavailableError,
    RetrySubmissionDAO,
    draft_submission_bytes,
)
from tests.tui.test_durable_composer import (
    ScriptedMessagingClient,
    _wait_until,
    _transcript_notices,
)
from tests.tui.test_prompt_component_protocol import build_session


def refusal(submission: MessageSubmissionDAO) -> MessageErrorDAO:
    """Keep a snapshot uncertain rather than restoring its editor text."""
    return MessageErrorDAO(code="storage_unavailable", message_id=submission.message_id)


async def submit(*, prompt: PromptInputComponent, text: str) -> DraftSubmissionDAO:
    """Capture and register through the same public component commands as Enter."""
    await prompt.handle(command=ReplacePromptDAO(text=text))
    draft = prompt.build_draft_submission(text=text, intent_revision=prompt._draft_revision)
    assert draft is not None
    await prompt.handle(command=SubmitDraftDAO(draft_submission=draft))
    return draft


async def bind_script(*, app: SloTUI, client: ScriptedMessagingClient) -> PromptInputComponent:
    """Replace the initial empty binding without swapping private collaborators."""
    await _wait_until(predicate=lambda: app._messaging_client is not None)
    prompt = app.query_one(PromptInputComponent)
    assert app._session.messaging_target is not None
    await prompt.replace_submission_binding(client=client, address=app._session.messaging_target)
    return prompt


async def test_reset_joins_waits_and_keeps_binding(tmp_path: Path) -> None:
    """Reset waits for rejection, invalidates restoration, and preserves the borrower."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(hold=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        adapter = prompt._submission_adapter
        draft = await submit(prompt=prompt, text="old")
        await _wait_until(predicate=lambda: bool(client.submit_calls))
        reset = asyncio.create_task(coro=prompt.reset())
        await _wait_until(predicate=lambda: prompt.text == "")
        assert not reset.done()
        reset_owned = prompt._reset_task
        for _ in range(3):
            reset.cancel()
            await asyncio.sleep(0)
            assert not reset.done() and prompt._reset_task is reset_owned
        client._outcomes[draft.message_submission.message_id] = MessageErrorDAO(
            code="queue_full", message_id=draft.message_submission.message_id
        )
        client.release(message_id=draft.message_submission.message_id)
        with pytest.raises(asyncio.CancelledError):
            await reset
        assert prompt.text == ""
        assert prompt.list_recoverable_drafts()[0].state == "recoverable"
        assert prompt._submission_adapter is adapter
        assert client.close_calls == 0
        next_draft = await submit(prompt=prompt, text="next")
        client._outcomes[next_draft.message_submission.message_id] = refusal(next_draft.message_submission)
        client.release(message_id=next_draft.message_submission.message_id)
        assert adapter is not None
        await adapter.reset()
        assert len(client.submit_calls) == 2


async def test_rebind_hands_off_then_registers_fresh_adapter(tmp_path: Path) -> None:
    """Acknowledged old snapshots retain identity and count against successor capacity."""
    old = build_session(tmp_path=tmp_path / "old")
    successor = build_session(tmp_path=tmp_path / "new")
    app = SloTUI(session=old, messaging_enabled=True)
    client = ScriptedMessagingClient(always=refusal)
    try:
        async with app.run_test():
            prompt = await bind_script(app=app, client=client)
            adapter = prompt._submission_adapter
            drafts = [await submit(prompt=prompt, text=text) for text in ("one", "two")]
            assert adapter is not None
            await adapter.reset()
            await successor.start_messaging()
            from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient

            assert successor.messaging_target is not None
            successor_client = LocalSessionMessagingClient(
                session=successor,
                target=successor.messaging_target,
                principal=successor.messaging_owner_principal,
            )
            try:
                await prompt.replace_submission_binding(
                    client=successor_client, address=successor.messaging_target
                )
                assert adapter._closed and adapter._client is None
                assert client.close_calls == 0
                assert app.count_retained_drafts().draft_count == 2
                held = app.list_retained_drafts()
                assert [entry.draft_submission for entry in held] == drafts
                assert all(entry.state == "host_held" for entry in held)
                assert not prompt.list_recoverable_drafts()
                fresh = await submit(prompt=prompt, text="successor input")
                assert fresh.message_submission.target == successor.messaging_target
                assert prompt._submission_adapter is not None
                await prompt._submission_adapter.reset()
                assert successor.history_store is not None
                await _wait_until(predicate=lambda: not successor.is_running)
                events = await successor.history_store.load_events(session_id=successor.session_id)
                assert any(event.payload.content == "successor input" for event in events)
                await prompt.retire_submission_binding()
            finally:
                await successor_client.close()
    finally:
        await successor.close_messaging()


async def test_full_handoff_blocks_replacement_and_preserves_drafts(tmp_path: Path) -> None:
    """A full host refuses transfer without destroying the usable old adapter."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(always=refusal)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        original = await submit(prompt=prompt, text="component owned")
        adapter = prompt._submission_adapter
        assert adapter is not None
        await adapter.reset()
        # Model an independently retained view; each snapshot keeps its exact route.
        assert app._session.messaging_target is not None
        drafts = tuple(
            DraftSubmissionDAO(
                message_submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=app._session.messaging_target,
                    kind="agent_input",
                    text=f"held {index}",
                ),
                draft_revision=0,
                binding_version=0,
            )
            for index in range(16)
        )
        ack = await app.retain_unresolved_drafts(
            handoff=DraftHandoffDAO(
                handoff_id=str(uuid4()),
                target=app._session.messaging_target,
                binding_version=0,
                drafts=drafts,
            )
        )
        assert ack.accepted
        with pytest.raises(DraftHandoffError):
            await prompt.replace_submission_binding(
                client=ScriptedMessagingClient(), address=app._session.messaging_target
            )
        assert prompt._submission_adapter is adapter and not adapter._closed
        assert not prompt._submission_sealed
        assert prompt.list_recoverable_drafts()[0].draft_submission == original
        # A retry needs no extra reservation; the same adapter remains usable.
        client._outcomes[original.message_submission.message_id] = refusal(original.message_submission)
        await prompt.handle(command=RetrySubmissionDAO(message_id=original.message_submission.message_id))
        await adapter.reset()
        assert client.receipt_calls == [original.message_submission.message_id]
        with pytest.raises(DraftCapacityError):
            await submit(prompt=prompt, text="over budget")
        assert prompt.text == "over budget"


async def test_unmount_close_joins_through_repeated_cancellation(tmp_path: Path) -> None:
    """One close barrier joins late rejection before sealing, never closing borrowed resources."""
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session, messaging_enabled=True)
    client = ScriptedMessagingClient(hold=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="pending")
        await _wait_until(predicate=lambda: bool(client.submit_calls))
        close = asyncio.create_task(coro=prompt.close())
        await _wait_until(predicate=lambda: prompt._delivery_closing)
        owned = prompt._close_task
        for _ in range(3):
            close.cancel()
            await asyncio.sleep(0)
            assert not close.done() and not prompt._delivery_closed

        async def remove_prompt() -> None:
            """Exercise actual mounted Textual pruning while close is still joining."""
            await prompt.remove()

        other = asyncio.create_task(coro=remove_prompt())
        client._outcomes[draft.message_submission.message_id] = MessageErrorDAO(
            code="queue_full", message_id=draft.message_submission.message_id
        )
        client.release(message_id=draft.message_submission.message_id)
        with pytest.raises(asyncio.CancelledError):
            await close
        await other
        assert prompt._close_task is owned
        assert not prompt.is_attached
        assert prompt._delivery_closed and prompt.text == ""
        assert app.count_retained_drafts().draft_count == 1
        assert client.close_calls == 0
        assert session.messaging_target is not None
        assert app._messaging_client is not None
        receipt = await app._messaging_client.get_receipt(message_id=str(uuid4()))
        assert isinstance(receipt, MessageErrorDAO) and receipt.code == "not_found"


async def test_late_old_binding_outcome_never_paints_successor(tmp_path: Path) -> None:
    """Rebind cannot publish a successor before the old wait settles and hands off."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(hold=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="old binding")
        await _wait_until(predicate=lambda: bool(client.submit_calls))
        assert app._session.messaging_target is not None
        fresh_client = ScriptedMessagingClient(always=refusal)
        successor_target = MessageAddressDAO(
            kind="agent_session", session_id=str(uuid4()), generation=str(uuid4())
        )
        replacement = asyncio.create_task(
            coro=prompt.replace_submission_binding(
                client=fresh_client,
                address=successor_target,
            )
        )
        await _wait_until(predicate=lambda: prompt._submission_sealed)
        await prompt.handle(command=ReplacePromptDAO(text="successor typing"))
        assert not replacement.done()
        replacement_owned = prompt._submission_replacement_task
        for _ in range(3):
            replacement.cancel()
            await asyncio.sleep(0)
            assert not replacement.done() and prompt._submission_replacement_task is replacement_owned
        client._outcomes[draft.message_submission.message_id] = MessageErrorDAO(
            code="queue_full", message_id=draft.message_submission.message_id
        )
        client.release(message_id=draft.message_submission.message_id)
        with pytest.raises(asyncio.CancelledError):
            await replacement
        assert prompt.text == "successor typing"
        assert app.list_retained_drafts()[0].draft_submission == draft
        assert fresh_client.submit_calls == []
        assert prompt._submission_address == successor_target
        assert draft.message_submission.target != successor_target


async def test_host_handoff_is_idempotent_and_refuses_conflicts(tmp_path: Path) -> None:
    """Exact duplicate acknowledgements do not reserve twice; conflicting keys refuse."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
        draft = await submit(prompt=prompt, text="kept")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        handoff = DraftHandoffDAO(
            handoff_id=str(uuid4()),
            target=draft.message_submission.target,
            binding_version=draft.binding_version,
            drafts=(draft,),
        )
        first = await app.retain_unresolved_drafts(handoff=handoff)
        assert first.accepted
        assert await app.retain_unresolved_drafts(handoff=handoff) == first
        conflict = handoff.model_copy(update={"binding_version": handoff.binding_version + 1})
        assert not (await app.retain_unresolved_drafts(handoff=conflict)).accepted
        assert app.count_retained_drafts().draft_count == 1


async def test_intentional_exit_warns_once_about_unsent_drafts(tmp_path: Path) -> None:
    """The first public exit warns and remains open; the next request actually exits."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    async with app.run_test() as pilot:
        prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
        await submit(prompt=prompt, text="unsent")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        await app._dispatch_slash_command(line="/exit")
        await pilot.pause()
        assert app.is_running and not app._app_closing
        assert any("1 unsent drafts will be lost" in line for line in _transcript_notices(app))
        await app._dispatch_slash_command(line="/exit")
    assert app._messaging_client is None and app._messaging_session is None


async def test_forced_teardown_reports_memory_only_drafts(tmp_path: Path) -> None:
    """Pre-pruning joins prompt retirement while its transcript host still exists."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
        await submit(prompt=prompt, text="memory only")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        await app._join_observation_before_superclass_pruning()
        await app._join_observation_before_superclass_pruning()
        assert prompt._delivery_closed
        assert app._messaging_observation_task is None
        assert sum("not saved" in line for line in _transcript_notices(app)) == 1


@pytest.mark.parametrize(argnames="operation", argvalues=["reset", "close"])
async def test_real_admission_joins_before_lifecycle_returns(tmp_path: Path, operation: str) -> None:
    """Mounted Enter held in the real SQLite executor settles before reset/close returns."""
    gate = CompletionGate(hold_before=True)
    history_root = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    model = FauxChatModel(responses=[FauxChatModel.assistant_message(content="settled")])
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        messaging_executor_factory=lambda: gate,
        enable_history=True,
    )
    app = SloTUI(session=session, messaging_enabled=True)
    message_id: str = ""
    try:
        async with app.run_test() as pilot:
            await _wait_until(predicate=lambda: app._messaging_client is not None)
            # Let initial replay's queue reads finish before arming the one-operation gate.
            await pilot.pause()
            prompt = app.query_one(PromptInputComponent)
            adapter = prompt._submission_adapter
            gate.armed = True
            prompt.load_text("real gated admission")
            await pilot.press("enter")
            await _wait_until(predicate=gate.started.is_set)
            assert prompt.text == ""
            message_id = prompt.list_recoverable_drafts()[0].draft_submission.message_submission.message_id
            lifecycle = asyncio.create_task(coro=prompt.reset() if operation == "reset" else prompt.close())
            await asyncio.sleep(0.02)
            assert not lifecycle.done()
            if operation == "close":
                for _ in range(3):
                    lifecycle.cancel()
                    await asyncio.sleep(0)
                    assert not lifecycle.done() and not prompt._delivery_closed
            gate.release.set()
            if operation == "close":
                with pytest.raises(asyncio.CancelledError):
                    await lifecycle
            else:
                await lifecycle
                assert prompt._submission_adapter is adapter
            assert prompt.text == "" and not prompt.list_recoverable_drafts()
            client = app._messaging_client
            assert client is not None
            receipt = await client.get_receipt(message_id=message_id)
            assert isinstance(receipt, MessageReceiptDAO)
            assert receipt.target == session.messaging_target
            await _wait_until(predicate=lambda: not session.is_running)
    finally:
        gate.release.set()
    rows = await asyncio.to_thread(
        read_closed_message_rows,
        database_path=history_root / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    )
    assert len(rows) == 1 and rows[0][0] == message_id
    assert rows[0][2] in ("accepted", "applied")


class UncertainHandoffApp(SloTUI):
    """Injected host acknowledgement boundary; records exact attempts and fails once."""

    CSS_PATH = str(Path(__file__).resolve().parents[2] / "src/tui/app.tcss")

    def __init__(self, *, session: SloAgentSession, failure: str) -> None:
        """Select refusal, mismatched key, exception or lost positive acknowledgement."""
        super().__init__(session=session, messaging_enabled=True)
        self.failure: str = failure
        self.handoffs: list[DraftHandoffDAO] = []

    async def retain_unresolved_drafts(self, *, handoff: DraftHandoffDAO) -> DraftHandoffAckDAO:
        """Fail the first acknowledgement without letting the component release snapshots."""
        self.handoffs.append(handoff)
        if len(self.handoffs) > 1:
            return await super().retain_unresolved_drafts(handoff=handoff)
        if self.failure == "lost_ack":
            await super().retain_unresolved_drafts(handoff=handoff)
            raise OSError("acknowledgement lost")
        if self.failure == "exception":
            raise OSError("receiver unavailable")
        return DraftHandoffAckDAO(
            handoff_id=str(uuid4()) if self.failure == "wrong_id" else handoff.handoff_id,
            accepted=self.failure != "refused",
        )


@pytest.mark.parametrize(argnames="failure", argvalues=["refused", "wrong_id", "exception", "lost_ack"])
async def test_ack_failure_preserves_binding_and_exact_retry(tmp_path: Path, failure: str) -> None:
    """No uncertain acknowledgement may release old snapshots or publish a successor."""
    app = UncertainHandoffApp(session=build_session(tmp_path=tmp_path), failure=failure)
    client = ScriptedMessagingClient(always=refusal)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="original target")
        adapter = prompt._submission_adapter
        assert adapter is not None
        await adapter.reset()
        new_client = ScriptedMessagingClient(always=refusal)
        with pytest.raises(DraftHandoffError, match="Unsent drafts could not be kept"):
            await prompt.replace_submission_binding(
                client=new_client, address=draft.message_submission.target
            )
        assert prompt._submission_adapter is adapter and not adapter._closed
        assert not prompt._submission_sealed
        assert prompt.list_recoverable_drafts()[0].draft_submission == draft
        assert not new_client.submit_calls and not client.close_calls
        await prompt.retire_submission_binding()
        assert app.handoffs[0] == app.handoffs[1]
        assert app.count_retained_drafts().draft_count == 1
        assert app.list_retained_drafts()[0].draft_submission == draft
        assert not prompt.list_recoverable_drafts()


async def test_host_held_actions_never_retry_into_successor(tmp_path: Path) -> None:
    """Draft list/discard include host memory, but explicit retry never redirects it."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(always=refusal)
    async with app.run_test() as pilot:
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="previous session body")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        new_client = ScriptedMessagingClient(always=refusal)
        await prompt.replace_submission_binding(client=new_client, address=draft.message_submission.target)
        await app._dispatch_slash_command(line="/messages drafts")
        await app._dispatch_slash_command(line=f"/messages retry {draft.message_submission.message_id[:8]}")
        await pilot.pause()
        notices = _transcript_notices(app)
        assert any("host_held" in line and "previous session body" in line for line in notices)
        assert any("Draft belongs to a previous session; copy its text" in line for line in notices)
        assert new_client.submit_calls == [] and new_client.receipt_calls == []
        await app._dispatch_slash_command(line=f"/messages discard {draft.message_submission.message_id}")
        assert app.count_retained_drafts().draft_count == 0


async def test_retirement_refuses_capture_retry_and_survives_cancellation(tmp_path: Path) -> None:
    """Public concurrent retire calls share a shielded task and seal new sends immediately."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(hold=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="pending")
        await _wait_until(predicate=lambda: bool(client.submit_calls))
        retire = asyncio.create_task(coro=prompt.retire_submission_binding())
        await _wait_until(predicate=lambda: prompt._submission_sealed)
        owned = prompt._submission_retirement_task
        sibling = asyncio.create_task(coro=prompt.retire_submission_binding())
        with pytest.raises(SubmissionUnavailableError):
            prompt.build_draft_submission(text="new", intent_revision=None)
        with pytest.raises(SubmissionUnavailableError):
            await prompt.handle(command=RetrySubmissionDAO(message_id=draft.message_submission.message_id))
        await app._dispatch_slash_command(line=f"/messages retry {draft.message_submission.message_id}")
        assert any("Session is changing; your text was kept." in line for line in _transcript_notices(app))
        for _ in range(3):
            retire.cancel()
            await asyncio.sleep(0)
            assert not retire.done() and prompt._submission_retirement_task is owned
        client._outcomes[draft.message_submission.message_id] = refusal(draft.message_submission)
        client.release(message_id=draft.message_submission.message_id)
        with pytest.raises(asyncio.CancelledError):
            await retire
        await sibling
        assert prompt._submission_adapter is None and not prompt._delivery_closed
        assert app.count_retained_drafts().draft_count == 1


async def test_handoff_and_component_share_canonical_byte_budget(tmp_path: Path) -> None:
    """Exact canonical cost, not text length, gates both host and successor reservations."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
        target = app._session.messaging_target
        assert target is not None
        drafts = tuple(
            DraftSubmissionDAO(
                message_submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=target,
                    kind="agent_input",
                    text="x" * 65000,
                ),
                draft_revision=0,
                binding_version=0,
            )
            for _ in range(15)
        )
        handoff = DraftHandoffDAO(handoff_id=str(uuid4()), target=target, binding_version=0, drafts=drafts)
        assert (await app.retain_unresolved_drafts(handoff=handoff)).accepted
        usage = app.count_retained_drafts()
        assert usage.canonical_bytes == sum(
            draft_submission_bytes(draft_submission=draft) for draft in drafts
        )
        candidate = DraftSubmissionDAO(
            message_submission=MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=target,
                kind="agent_input",
                text="y" * 65000,
            ),
            draft_revision=0,
            binding_version=0,
        )
        assert (
            await app.retain_unresolved_drafts(
                handoff=DraftHandoffDAO(
                    handoff_id=str(uuid4()),
                    target=target,
                    binding_version=0,
                    drafts=(candidate,),
                )
            )
        ).accepted
        assert app.count_retained_drafts().canonical_bytes == (
            usage.canonical_bytes + draft_submission_bytes(draft_submission=candidate)
        )
        assert app.count_retained_drafts().canonical_bytes <= 1_048_576
        with pytest.raises(DraftCapacityError):
            await submit(prompt=prompt, text="beyond host reservations")
        assert prompt.text == "beyond host reservations"


class RefusingHandoffApp(SloTUI):
    """Host failure boundary for forced-close discard feedback."""

    CSS_PATH = str(Path(__file__).resolve().parents[2] / "src/tui/app.tcss")

    async def retain_unresolved_drafts(self, *, handoff: DraftHandoffDAO) -> DraftHandoffAckDAO:
        """Refuse without taking ownership, including forced teardown."""
        return DraftHandoffAckDAO(handoff_id=handoff.handoff_id, accepted=False)


async def test_close_refusal_discards_only_after_join_and_reports_loss(tmp_path: Path) -> None:
    """Forced close cannot preserve failed handoff but must announce discarded drafts."""
    app = RefusingHandoffApp(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(always=refusal)
    async with app.run_test() as pilot:
        prompt = await bind_script(app=app, client=client)
        await submit(prompt=prompt, text="cannot retain")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        await prompt.close()
        await pilot.pause()
        assert prompt._delivery_closed and prompt._submission_adapter is None
        assert prompt._dropped_draft_count == 1 and not prompt.list_recoverable_drafts()
        assert app.count_retained_drafts().draft_count == 0 and client.close_calls == 0
        assert any("could not be kept and were discarded" in line for line in _transcript_notices(app))


async def test_concurrent_rebind_calls_share_one_replacement(tmp_path: Path) -> None:
    """Concurrent public replacements never overwrite an already published adapter."""
    app = SloTUI(session=build_session(tmp_path=tmp_path), messaging_enabled=True)
    client = ScriptedMessagingClient(hold=True)
    async with app.run_test():
        prompt = await bind_script(app=app, client=client)
        draft = await submit(prompt=prompt, text="held predecessor")
        await _wait_until(predicate=lambda: bool(client.submit_calls))
        successor = ScriptedMessagingClient(always=refusal)
        ignored = ScriptedMessagingClient(always=refusal)
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        first = asyncio.create_task(coro=prompt.replace_submission_binding(client=successor, address=target))
        await _wait_until(predicate=lambda: prompt._submission_sealed)
        owned = prompt._submission_replacement_task
        second = asyncio.create_task(coro=prompt.replace_submission_binding(client=ignored, address=target))
        await asyncio.sleep(0)
        assert prompt._submission_replacement_task is owned
        client._outcomes[draft.message_submission.message_id] = refusal(draft.message_submission)
        client.release(message_id=draft.message_submission.message_id)
        await first
        await second
        fresh = await submit(prompt=prompt, text="only successor")
        assert prompt._submission_adapter is not None
        await prompt._submission_adapter.reset()
        assert successor.submit_calls == [fresh.message_submission]
        assert ignored.submit_calls == [] and client.close_calls == 0
