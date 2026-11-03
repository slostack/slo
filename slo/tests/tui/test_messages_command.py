"""Mounted retained-input slash confirmation journeys through real persistence."""

from pathlib import Path
from uuid import uuid4

import pytest
from textual.pilot import Pilot

from src.agents.slo_agent.messaging.dao import MessageErrorDAO
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.slash_router import MessagesCommandDAO, SlashCommandResultDAO, SlashRouter
from tests.agents.slo_agent.messaging.test_retained_recovery import restart_retained
from tests.integration.test_session_messaging import read_closed_message_rows


def test_slash_result_schema_describes_optional_messages_intent() -> None:
    """Messages intent remains nullable and optional with a documented None default."""
    schema = SlashCommandResultDAO.model_json_schema()
    field = schema["properties"]["messages_command"]
    assert field["description"].strip()
    assert field["default"] is None
    assert "messages_command" not in schema.get("required", [])
    assert {"type": "null"} in field["anyOf"]
    assert SlashCommandResultDAO().messages_command is None
    assert SlashCommandResultDAO(messages_command=None).messages_command is None
    command = MessagesCommandDAO(action="list")
    assert SlashCommandResultDAO(messages_command=command).messages_command == command
    with pytest.raises(ValueError):
        SlashCommandResultDAO.model_validate({"messages_command": {"action": "unknown"}})
    with pytest.raises(ValueError, match="only one context refresh"):
        SlashCommandResultDAO(refresh_context_window=True, refresh_usage_status=True)


async def slash(*, app: SloTUI, pilot: Pilot, line: str) -> None:
    """Submit a slash line through the real mounted editor's Enter route."""
    app.query_one(PromptInputComponent).load_text(text=line)
    await pilot.press("enter")
    await pilot.pause()


def notices(*, app: SloTUI) -> str:
    """Read the existing transcript adapter's logical notice surface."""
    return app.query_one(ChatTranscriptComponent).logical_copy_text()


async def test_slash_recovery_flow_with_confirm_and_decline(tmp_path: Path) -> None:
    """Listing constrains selection; decline writes nothing and confirm executes exactly once."""
    session, model, originals, _, _, _ = await restart_retained(root=tmp_path)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await slash(app=app, pilot=pilot, line="/messages list")
        assert originals[0].message_id[:8] in notices(app=app)
        await slash(app=app, pilot=pilot, line=f"/messages continue {originals[0].message_id[:8]}")
        assert "Type /messages confirm or /messages decline" in notices(app=app)
        await slash(app=app, pilot=pilot, line="/messages decline")
        assert "Declined; nothing changed." in notices(app=app)
        assert not model.requests
        page = await session.list_retained_messages(principal=session.messaging_owner_principal)
        assert not isinstance(page, MessageErrorDAO) and len(page.items) == 2
        await slash(app=app, pilot=pilot, line=f"/messages cancel {uuid4()}")
        assert "/messages list [after]" in notices(app=app)
        await slash(app=app, pilot=pilot, line=f"/messages continue {originals[0].message_id[:8]}")
        await slash(app=app, pilot=pilot, line="/messages confirm")
        await pilot.pause()
        assert len(model.requests) == 1
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert "Nothing to confirm." in notices(app=app)
        await slash(app=app, pilot=pilot, line="/messages list")
        await slash(app=app, pilot=pilot, line=f"/messages cancel {originals[1].message_id[:8]}")
        await slash(app=app, pilot=pilot, line="/messages decline")
        await slash(app=app, pilot=pilot, line=f"/messages cancel {originals[1].message_id[:8]}")
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert "Cancelled retained messages." in notices(app=app)
    path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert read_closed_message_rows(database_path=path, temporary_root=tmp_path) == (
        (originals[0].message_id, 0, "applied"),
        (originals[1].message_id, 0, "cancelled"),
    )


async def test_messages_router_validates_recovery_arguments(tmp_path: Path) -> None:
    """Malformed cursors and action arity render usage, never a mutation intent."""
    session, _, _, _, _, _ = await restart_retained(root=tmp_path)
    try:
        for line in (
            "/messages list -1",
            "/messages list x",
            "/messages confirm extra",
            "/messages continue",
            "/messages decline extra",
            "/messages list 1 2",
        ):
            result = await SlashRouter.dispatch(line=line, session=session)
            assert result.messages_command is None and result.rendered is not None
        result = await SlashRouter.dispatch(line="/messages list 12", session=session)
        assert result.messages_command is not None and result.messages_command.after_sequence == 12
    finally:
        await session.close_messaging()


async def test_confirm_retries_identical_consent_after_lost_reply(tmp_path: Path) -> None:
    """A host-visible failure after commit retains identical consent and retries without execution duplication."""
    from src.agents.slo_agent.messaging.dao import (
        RecoveryConfirmationDAO,
        RecoveryOutcomeDAO,
        MessagePrincipalDAO,
    )
    from src.agents.slo_agent.sessions.service import SloAgentSession

    class LostRecoveryReplySession(SloAgentSession):
        """Injected real-session variant loses exactly the first committed recovery reply."""

        confirmations: list[RecoveryConfirmationDAO]

        async def recover_message(
            self, *, confirmation: RecoveryConfirmationDAO, principal: MessagePrincipalDAO
        ) -> RecoveryOutcomeDAO | MessageErrorDAO:
            """Commit through the real session, then simulate one lost response."""
            if not hasattr(self, "confirmations"):
                self.confirmations = []
            self.confirmations.append(confirmation)
            outcome = await super().recover_message(confirmation=confirmation, principal=principal)
            if len(self.confirmations) == 1:
                raise OSError("simulated lost response")
            return outcome

    session, model, originals, _, _, _ = await restart_retained(
        root=tmp_path, session_type=LostRecoveryReplySession
    )
    assert isinstance(session, LostRecoveryReplySession)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await slash(app=app, pilot=pilot, line="/messages list")
        await slash(app=app, pilot=pilot, line=f"/messages continue {originals[0].message_id[:8]}")
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert "Could not confirm; /messages confirm retries the same confirmation." in notices(app=app)
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert len(session.confirmations) == 2 and session.confirmations[0] is session.confirmations[1]
        assert "Continued retained message." in notices(app=app)
        assert len(model.requests) == 1


async def test_expired_confirmation_clears_host_selection(tmp_path: Path) -> None:
    """Expiry paints fixed feedback and requires fresh listing and consent."""
    from datetime import timedelta

    session, model, originals, _, clock, _ = await restart_retained(root=tmp_path)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await slash(app=app, pilot=pilot, line="/messages list")
        await slash(app=app, pilot=pilot, line=f"/messages continue {originals[0].message_id[:8]}")
        clock.now += timedelta(minutes=5)
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert "Selection changed or expired; list again." in notices(app=app)
        await slash(app=app, pilot=pilot, line="/messages confirm")
        assert "Nothing to confirm." in notices(app=app) and not model.requests
