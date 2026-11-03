"""DC08 stale scan/verification results at a mounted /new boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    LegacyInboxAdmissionDAO,
    MessageErrorDAO,
    MessageIdentityDAO,
    MessagePrincipalDAO,
)
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory, RecordingModel
from tests.tui.test_durable_composer import _wait_until
from tests.tui.test_legacy_inbox_bridge import HeldClaimInboxStore, inbox_message
from tests.tui.test_messaging_session_controls import SuccessorFactory, slash


class HeldVerificationSession(SloAgentSession):
    """Delay a genuine public verification reply after reading real SQLite/history."""

    def hold_next_verification(self) -> None:
        """Arm one test-owned reply gate without changing session authority."""
        self.verification_entered = asyncio.Event()
        self.verification_release = asyncio.Event()
        self.verification_armed = True
        self.verified_identity: MessageIdentityDAO | None = None

    async def get_legacy_inbox_admission(
        self,
        *,
        owner: MessagePrincipalDAO,
        client: LocalSessionMessagingClient,
        admission: LegacyInboxAdmissionDAO,
    ) -> MessageIdentityDAO | MessageErrorDAO:
        """Return the real proof late, as a persistence completion could do."""
        identity = await super().get_legacy_inbox_admission(owner=owner, client=client, admission=admission)
        if getattr(self, "verification_armed", False):
            self.verification_armed = False
            assert isinstance(identity, MessageIdentityDAO)
            self.verified_identity = identity
            self.verification_entered.set()
            await self.verification_release.wait()
        return identity


@pytest.mark.parametrize(argnames="boundary", argvalues=["page", "verification"])
async def test_new_displaces_held_inbox_scan_without_stale_ack(tmp_path: Path, boundary: str) -> None:
    """An ackable claim survives a real /new while its scan or verified reply awaits."""
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent

    store = HeldClaimInboxStore(history_root=tmp_path / "history")
    model = RecordingModel(responses=[])
    session_id = str(uuid4())
    session = HeldVerificationSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=tmp_path / "history", model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    factory = SuccessorFactory()
    app = SloTUI(session=session, inbox_store=store, session_factory=factory, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: app._inbox_timer is not None and session.is_messaging_ready)
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        message = inbox_message(session_id=session_id)
        await store.enqueue(message=message)
        await app._poll_session_inbox()
        assert session._message_store is not None
        async with asyncio.timeout(3):
            while True:
                identity = await session._message_store.find_identity(message_id=message.message_id)
                if identity is not None and identity.receipt.state == "applied":
                    break
                await asyncio.sleep(0.01)
        assert await store.list_done(session_id=session_id) == []
        store.fail = False
        ack_calls = store.ack_calls
        session.hold_next_verification()
        if boundary == "page":
            store.armed = True
            entered, release = store.entered, store.release_page
        else:
            entered, release = session.verification_entered, session.verification_release
        scan = asyncio.create_task(coro=app._scan_recovered_inbox_claims(session=session))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            if boundary == "verification":
                assert session.verified_identity is not None
                assert session.verified_identity.receipt.state == "applied"
            await slash(app=app, pilot=pilot, line="/new")
            successor = app._session
            assert successor is factory.sessions[0] and successor is not session
            await _wait_until(predicate=lambda: app._messaging_session is successor)
            assert not session.is_messaging_ready and successor.is_messaging_ready
            await pilot.pause()
            lines = tuple(app.query_one(ChatTranscriptComponent)._adapter.lines)
            release.set()
            await asyncio.wait_for(scan, timeout=3)
            await pilot.pause()
            assert store.ack_calls == ack_calls
            assert await store.list_done(session_id=session_id) == []
            assert await store.read_claimed(session_id=session_id) == (message,)
            assert tuple(app.query_one(ChatTranscriptComponent)._adapter.lines) == lines
            assert successor._message_store is not None
            assert await successor._message_store.read_identities() == ()
            assert not model.requests
        finally:
            store.release_page.set()
            session.verification_release.set()
            await asyncio.gather(scan, return_exceptions=True)
