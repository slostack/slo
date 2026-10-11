"""Tests for ``WorkflowNotifier`` (spec 57.a.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

_TARGET_SESSION_ID: str = "tui-session-1"
_ORCH_SESSION_ID: str = "orch-session-1"
_WORKFLOW_ID: str = "wf-3f2a"


class _ExplodingInboxStore:
    """Inbox store stand-in whose every enqueue raises."""

    def __init__(self) -> None:
        """Track how often the enqueue was attempted."""
        self.enqueue_attempts: int = 0

    async def enqueue(self, *, message: SessionInboxMessageDAO) -> None:
        """Raise unconditionally.

        Args:
            message (SessionInboxMessageDAO): Ignored.

        Raises:
            OSError: Always.
        """
        self.enqueue_attempts += 1
        raise OSError("inbox unavailable")


def _build_notifier(
    *,
    tmp_path: Path,
    store: SessionInboxStore | _ExplodingInboxStore | None = None,
) -> tuple[WorkflowNotifier, SessionInboxStore]:
    """Build a notifier wired to a tmp-path inbox store.

    Args:
        tmp_path (Path): Pytest tmp path.
        store: Optional store override.

    Returns:
        tuple[WorkflowNotifier, SessionInboxStore]: Notifier and its store.
    """
    inbox_store: SessionInboxStore | _ExplodingInboxStore = (
        store if store is not None else SessionInboxStore(history_root=tmp_path / "history")
    )
    notifier: WorkflowNotifier = WorkflowNotifier(
        target_session_id=_TARGET_SESSION_ID,
        orchestrator_session_id=_ORCH_SESSION_ID,
        workflow_id=_WORKFLOW_ID,
        inbox_store=inbox_store,  # type: ignore[arg-type]
    )
    return notifier, inbox_store  # type: ignore[return-value]


async def _pending(*, store: SessionInboxStore) -> list[SessionInboxMessageDAO]:
    """Return the pending inbox items for the target session.

    Args:
        store (SessionInboxStore): Store under inspection.

    Returns:
        list[SessionInboxMessageDAO]: Pending messages oldest-first.
    """
    return await store.list_pending(session_id=_TARGET_SESSION_ID)


class TestStarted:
    """``started()`` — the workflow_started context note."""

    async def test_started_enqueues_context_note_with_identity_payload(self, tmp_path: Path) -> None:
        """The started note is a context_note carrying the identity pair."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.started(brief_preview="run the code-test-review workflow")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert len(pending) == 1
        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_started"
        assert message.delivery_mode == "context_note"
        assert message.session_id == _TARGET_SESSION_ID
        assert message.payload == {
            "workflow_id": _WORKFLOW_ID,
            "orchestrator_session_id": _ORCH_SESSION_ID,
        }
        assert "run the code-test-review workflow" in message.text

    async def test_started_truncates_long_brief_preview(self, tmp_path: Path) -> None:
        """Brief previews are clipped to 200 characters in the note text."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.started(brief_preview="x" * 500)
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert "x" * 200 in pending[0].text
        assert "x" * 201 not in pending[0].text


class TestPhaseUpdate:
    """``phase_update()`` — per-phase context notes."""

    async def test_phase_update_increments_phase_index(self, tmp_path: Path) -> None:
        """Two updates number themselves phase 1 and phase 2."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.phase_update(phase_summary="phase one done")
        await notifier.phase_update(phase_summary="phase two done")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert len(pending) == 2
        assert "phase 1: phase one done" in pending[0].text
        assert "phase 2: phase two done" in pending[1].text
        assert all(message.kind == "workflow_phase_update" for message in pending)
        assert all(message.delivery_mode == "context_note" for message in pending)


class TestFleetUpdate:
    """``fleet_update()`` — lifecycle fleet context notes."""

    async def test_fleet_update_does_not_enqueue_after_terminal_status(self, tmp_path: Path) -> None:
        """A terminal orchestrator status suppresses delayed child fleet traffic."""
        store: SessionInboxStore = SessionInboxStore(history_root=tmp_path / "history")
        status_store: OrchestratorStatusStore = OrchestratorStatusStore(
            history_root=tmp_path / "history",
            orchestrator_session_id=_ORCH_SESSION_ID,
            workflow_id=_WORKFLOW_ID,
        )
        status_store.write_terminal(state="completed", exit_code=0, phase="complete")
        notifier: WorkflowNotifier = WorkflowNotifier(
            target_session_id=_TARGET_SESSION_ID,
            orchestrator_session_id=_ORCH_SESSION_ID,
            workflow_id=_WORKFLOW_ID,
            inbox_store=store,
            status_store=status_store,
        )

        await notifier.fleet_update(entries=[], live_count=0)

        assert await _pending(store=store) == []

    async def test_fleet_update_enqueues_compact_context_note(self, tmp_path: Path) -> None:
        """A fleet transition ships its complete compact snapshot to the inbox."""
        notifier, store = _build_notifier(tmp_path=tmp_path)
        entries: list[dict[str, object]] = [
            {"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"}
        ]

        await notifier.fleet_update(entries=entries, live_count=1)
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert pending[0].kind == "workflow_fleet_update"
        assert pending[0].payload == {
            "workflow_id": _WORKFLOW_ID,
            "orchestrator_session_id": _ORCH_SESSION_ID,
            "entries": entries,
            "live_count": 1,
        }
        assert pending[0].text == "fleet: 1 live (t1 streaming)"


class TestTerminal:
    """``completed()`` / ``failed()`` — the terminal chat_turn messages."""

    async def test_completed_enqueues_chat_turn_with_synthesis_and_json(self, tmp_path: Path) -> None:
        """The completion message carries the synthesis and result JSON."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.completed(synthesis="all phases green", result_json='{"all_completed": true}')
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_completed"
        assert message.delivery_mode == "chat_turn"
        assert "all phases green" in message.text
        assert '{"all_completed": true}' in message.text

    async def test_completed_note_includes_cleanup_summary(self, tmp_path: Path) -> None:
        """The terminal completion note puts cleanup accounting on its own line."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.completed(
            synthesis="all phases green",
            result_json='{"all_completed": true}',
            cleanup_summary="fleet: 1 completed · 0 live",
        )
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert "fleet: 1 completed · 0 live" in pending[0].text

    async def test_failed_enqueues_chat_turn_with_error(self, tmp_path: Path) -> None:
        """The failure message carries the terminal error description."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.failed(error="run_failed: model exhausted")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_failed"
        assert message.delivery_mode == "chat_turn"
        assert "run_failed: model exhausted" in message.text


class TestTerminalCredentialRedaction:
    """Terminal notifier artifacts must not expose the effective OpenRouter credential."""

    async def test_failed_redacts_effective_openrouter_credential_from_pending_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A failure sentinel is redacted before the real inbox store persists it."""
        sentinel: str = "openrouter-notifier-sentinel"
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=sentinel,
        )
        monkeypatch.setattr(CredentialResolver, "resolve", lambda *, provider: credential)
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.failed(error=f"upstream failed: {sentinel}")

        pending: list[SessionInboxMessageDAO] = await _pending(store=store)
        persisted_paths: list[Path] = list((tmp_path / "history").rglob("*.json"))
        persisted_text: str = "\n".join(path.read_text(encoding="utf-8") for path in persisted_paths)
        assert all(path.resolve().is_relative_to(tmp_path.resolve()) for path in persisted_paths)
        assert len(pending) == 1
        assert "[REDACTED]" in pending[0].text
        assert sentinel not in pending[0].text
        assert sentinel not in persisted_text


class TestTerminalCredentialRotation:
    """Notifier output protection during an admitted-key rotation."""

    @pytest.mark.parametrize("terminal", ["completed", "failed"])
    async def test_terminal_redacts_admitted_key_after_effective_key_rotates(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        terminal: str,
    ) -> None:
        """Completed and failed notifications retain no old or newly effective credential."""
        admitted_key: str = "openrouter-notifier-admitted-key-a"
        rotated_key: str = "openrouter-notifier-effective-key-b"
        credential_a: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=admitted_key,
        )
        credential_b: CredentialDAO = credential_a.model_copy(update={"access_token": rotated_key})
        notifier, store = _build_notifier(tmp_path=tmp_path)

        with CredentialResolver.bind_build_credential(credential=credential_a):
            monkeypatch.setattr(CredentialResolver, "resolve", lambda *, provider: credential_b)
            if terminal == "completed":
                await notifier.completed(
                    synthesis=f"completed after {admitted_key}",
                    result_json=f'{{"next":"{admitted_key}"}}',
                )
            else:
                await notifier.failed(error=f"failed after {admitted_key}")

        pending: list[SessionInboxMessageDAO] = await _pending(store=store)
        artifact_text: str = "\n".join(
            path.read_text(encoding="utf-8") for path in (tmp_path / "history").rglob("*") if path.is_file()
        )
        assert len(pending) == 1
        assert "[REDACTED]" in pending[0].text
        assert admitted_key not in artifact_text
        assert rotated_key not in artifact_text

    async def test_failed_notifier_fails_closed_when_resolution_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An unavailable live resolver still redacts the operation-bound credential."""
        admitted_key: str = "openrouter-notifier-resolver-failure-key"
        credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=admitted_key,
        )
        notifier, store = _build_notifier(tmp_path=tmp_path)

        def fail_resolution(*, provider: ProviderName) -> CredentialDAO:
            """Raise the controlled resolver failure during notifier persistence."""
            del provider
            raise OSError("controlled resolver failure")

        with CredentialResolver.bind_build_credential(credential=credential):
            monkeypatch.setattr(CredentialResolver, "resolve", fail_resolution)
            await notifier.failed(error=f"upstream failed: {admitted_key}")

        pending: list[SessionInboxMessageDAO] = await _pending(store=store)
        assert len(pending) == 1
        assert pending[0].text.count("[REDACTED]") == 1
        assert admitted_key not in pending[0].text


class TestFailureSwallowing:
    """A notify failure must never propagate into the workflow."""

    async def test_enqueue_failure_is_swallowed(self, tmp_path: Path) -> None:
        """Every lifecycle method survives a store that always raises."""
        exploding: _ExplodingInboxStore = _ExplodingInboxStore()
        notifier, _ = _build_notifier(tmp_path=tmp_path, store=exploding)

        await notifier.started(brief_preview="b")
        await notifier.phase_update(phase_summary="p")
        await notifier.completed(synthesis="s", result_json="{}")
        await notifier.failed(error="e")

        assert exploding.enqueue_attempts == 4
