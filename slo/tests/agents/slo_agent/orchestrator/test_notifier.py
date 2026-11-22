"""Tests for the channel-transport ``WorkflowNotifier`` (108.3 §4; was spec 57.a.3).

Every lifecycle message goes through a real ``ChannelGateway`` to the owning
TUI session's agent participant: ``started``/``phase_update`` ship as ``note``
rows, ``fleet_update`` ships as a coalescible ``notice`` row, and the terminal
messages ship as normal ``prompt`` rows. Message ids are deterministic
``uuid5(NS_WORKFLOW, "<workflow>:<event>:<phase>")`` so a crashed notifier's
retry hits the duplicate-id rule instead of creating a second row. Real SQLite;
no mocks.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid5

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.orchestrator.notifier import NS_WORKFLOW, WorkflowNotifier
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository

_TARGET_SESSION_ID: str = "11111111-1111-1111-1111-111111111111"
_ORCH_SESSION_ID: str = "22222222-2222-2222-2222-222222222222"
_WORKFLOW_ID: str = "wf-3f2a"


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one real gateway on a fresh temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


async def _register_target(*, gateway: ChannelGateway) -> UUID:
    """Register the TUI-side agent participant the notifier writes to."""
    participant: object = await gateway.register_agent(
        session_id=UUID(_TARGET_SESSION_ID),
        name="slo 11111111",
    )
    return participant.id  # type: ignore[attr-defined]


def _build_notifier(
    *,
    gateway: ChannelGateway,
    status_store: OrchestratorStatusStore | None = None,
) -> WorkflowNotifier:
    """Build a notifier wired to the real gateway."""
    return WorkflowNotifier(
        gateway=gateway,
        target_session_id=_TARGET_SESSION_ID,
        orchestrator_session_id=_ORCH_SESSION_ID,
        workflow_id=_WORKFLOW_ID,
        status_store=status_store,
    )


def _expected_id(*, event: str, phase_index: int) -> UUID:
    """Return the deterministic message id the notifier must use."""
    return uuid5(NS_WORKFLOW, f"{_WORKFLOW_ID}:{event}:{phase_index}")


async def _pending_for_target(*, gateway: ChannelGateway) -> list[ChannelMessageDAO]:
    """Return the pending rows addressed to the target session."""
    return await gateway.pending_inbound(recipient_id=UUID(_TARGET_SESSION_ID))


class TestStarted:
    """``started()`` — the workflow_started note row."""

    async def test_started_sends_a_note_with_the_deterministic_id(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.started(brief_preview="run the code-test-review workflow")

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            note: ChannelMessageDAO = pending[0]
            assert note.message_type == "note"
            assert note.id == _expected_id(event="started", phase_index=0)
            assert note.sender_id == channel_participant_id_for_session(session_id=_ORCH_SESSION_ID)
            assert note.agent_session_id == UUID(_TARGET_SESSION_ID)
            assert "[workflow wf-3f2a] started" in note.message_contents
            assert "run the code-test-review workflow" in note.message_contents
        finally:
            await gateway.close()

    async def test_started_retry_hits_the_duplicate_id_rule(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.started(brief_preview="brief")
            await notifier.started(brief_preview="brief")

            assert len(await _pending_for_target(gateway=gateway)) == 1
        finally:
            await gateway.close()

    async def test_started_truncates_long_brief_preview(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.started(brief_preview="x" * 500)
            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)

            assert "x" * 200 in pending[0].message_contents
            assert "x" * 201 not in pending[0].message_contents
        finally:
            await gateway.close()


class TestPhaseUpdate:
    """``phase_update()`` — per-phase note rows."""

    async def test_phase_updates_send_numbered_note_rows(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.phase_update(phase_summary="phase one done")
            await notifier.phase_update(phase_summary="phase two done")

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 2
            assert all(row.message_type == "note" for row in pending)
            assert "phase 1: phase one done" in pending[0].message_contents
            assert "phase 2: phase two done" in pending[1].message_contents
            assert pending[0].id == _expected_id(event="phase", phase_index=1)
            assert pending[1].id == _expected_id(event="phase", phase_index=2)
        finally:
            await gateway.close()


class TestFleetUpdate:
    """``fleet_update()`` — coalescible notice rows."""

    async def test_fleet_update_sends_a_notice_with_the_fleet_coalesce_key(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)
            entries: list[dict[str, object]] = [
                {"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"}
            ]

            await notifier.fleet_update(entries=entries, live_count=1)

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            notice: ChannelMessageDAO = pending[0]
            assert notice.message_type == "notice"
            assert notice.coalesce_key == f"wf:{_WORKFLOW_ID}:fleet"
            assert notice.message_contents == "fleet: 1 live (t1 streaming)"
            assert notice.id == _expected_id(event="fleet", phase_index=1)
        finally:
            await gateway.close()

    async def test_a_burst_of_fleet_notices_leaves_only_the_newest_pending(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.fleet_update(entries=[], live_count=2)
            await notifier.fleet_update(entries=[], live_count=1)

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            assert pending[0].message_contents == "fleet: 1 live ()"
        finally:
            await gateway.close()

    async def test_fleet_update_is_suppressed_after_terminal_status(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            status_store: OrchestratorStatusStore = OrchestratorStatusStore(
                history_root=tmp_path / "history",
                orchestrator_session_id=_ORCH_SESSION_ID,
                workflow_id=_WORKFLOW_ID,
            )
            status_store.write_terminal(state="completed", exit_code=0, phase="complete")
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway, status_store=status_store)

            await notifier.fleet_update(entries=[], live_count=0)

            assert await _pending_for_target(gateway=gateway) == []
        finally:
            await gateway.close()


class TestTerminal:
    """``completed()`` / ``failed()`` / ``aborted()`` — terminal normal prompts."""

    async def test_completed_sends_a_normal_prompt_with_the_synthesis(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.completed(
                synthesis="all phases green",
                result_json='{"all_completed": true}',
                cleanup_summary="fleet: 1 completed · 0 live",
            )

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            prompt: ChannelMessageDAO = pending[0]
            assert prompt.message_type == "prompt"
            assert prompt.forced_at is None
            assert prompt.id == _expected_id(event="completed", phase_index=0)
            assert "all phases green" in prompt.message_contents
            assert '{"all_completed": true}' in prompt.message_contents
            assert "fleet: 1 completed · 0 live" in prompt.message_contents
        finally:
            await gateway.close()

    async def test_failed_sends_a_normal_prompt_with_the_error(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.failed(error="run_failed: model exhausted")

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            assert pending[0].message_type == "prompt"
            assert "run_failed: model exhausted" in pending[0].message_contents
            assert pending[0].id == _expected_id(event="failed", phase_index=0)
        finally:
            await gateway.close()

    async def test_aborted_sends_a_normal_prompt_with_the_finality_instruction(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.aborted(reason="run_aborted: stopped", cleanup_summary="fleet: done")

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            prompt: ChannelMessageDAO = pending[0]
            assert prompt.message_type == "prompt"
            assert prompt.id == _expected_id(event="aborted", phase_index=0)
            assert prompt.message_contents == (
                "Workflow wf-3f2a was aborted. Reason: run_aborted: stopped. "
                "An aborted workflow is final: do not retry, resume or relaunch it. "
                "Tell the user it was aborted and suggest /workflows for its final state."
                "\n\nfleet: done"
            )
        finally:
            await gateway.close()


class TestReceivePaths:
    """Rows wait in the DB when the target is gone or closed."""

    async def test_unknown_target_is_swallowed_and_logged(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)
            # The TUI participant has never registered: the row cannot be
            # inserted, and the workflow must keep running anyway.
            await notifier.started(brief_preview="brief")
            assert await gateway.pending_outbound(recipient_ids=[]) == []
        finally:
            await gateway.close()

    async def test_closed_target_is_swallowed(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await gateway.register_agent(session_id=UUID(_TARGET_SESSION_ID), name="slo 11111111")
            await gateway.register_agent(session_id=UUID(_ORCH_SESSION_ID), name="orchestrator wf-3f2a")
            await gateway.close_agent(session_id=UUID(_TARGET_SESSION_ID), reason="session_closed")
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)
            with pytest.raises(RecipientClosedError):
                await gateway.send(
                    new=NewMessageDAO(
                        sender_id=UUID(_ORCH_SESSION_ID),
                        recipient_id=UUID(_TARGET_SESSION_ID),
                        message_contents="x",
                    )
                )
            await notifier.started(brief_preview="brief")
        finally:
            await gateway.close()


class TestFailureSwallowing:
    """A notify failure must never propagate into the workflow."""

    async def test_gateway_failure_is_swallowed(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        notifier: WorkflowNotifier = _build_notifier(gateway=gateway)
        await gateway.close()  # every send now raises: the repository is not open
        await notifier.started(brief_preview="b")
        await notifier.phase_update(phase_summary="p")
        await notifier.fleet_update(entries=[], live_count=1)
        await notifier.completed(synthesis="s", result_json="{}")
        await notifier.failed(error="e")
        await notifier.aborted(reason="stopped")


class TestCredentialRedaction:
    """Terminal notifier artifacts must not expose the effective credential."""

    async def test_failed_redacts_the_effective_openrouter_credential(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sentinel: str = "openrouter-notifier-sentinel"
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=sentinel,
        )
        monkeypatch.setattr(CredentialResolver, "resolve", lambda *, provider: credential)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await _register_target(gateway=gateway)
            notifier: WorkflowNotifier = _build_notifier(gateway=gateway)

            await notifier.failed(error=f"upstream failed: {sentinel}")

            pending: list[ChannelMessageDAO] = await _pending_for_target(gateway=gateway)
            assert len(pending) == 1
            assert "[REDACTED]" in pending[0].message_contents
            assert sentinel not in pending[0].message_contents
        finally:
            await gateway.close()


class TestNoInboxImports:
    """O6 (static): ``WorkflowNotifier`` no longer uses the file inbox."""

    async def test_notifier_module_has_no_history_inbox_import(self) -> None:
        import inspect

        source: str = inspect.getsource(
            __import__("src.agents.slo_agent.orchestrator.notifier", fromlist=["WorkflowNotifier"])
        )
        assert "history.inbox" not in source
        assert "SessionInboxStore" not in source
        assert "SessionInboxMessageDAO" not in source

    async def test_unknown_participant_error_is_the_expected_failure_kind(self) -> None:
        assert UnknownParticipantError(participant_id=UUID(_TARGET_SESSION_ID)) is not None
