"""Presentation translation has no application or session lifetime dependencies."""

from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind


def test_reconnect_uses_safe_metadata_not_provider_content() -> None:
    """Reconnect copy never includes raw provider content."""
    from src.tui.session_event_presentation import SessionEventPresentation

    presentation = SessionEventPresentation.build(
        event=AgentStreamEventDAO(kind="stream_reconnecting", content="private provider text")
    )
    assert presentation.notice is not None
    assert presentation.notice.content == "(reconnecting after provider_stream_disconnected: transport error)"
    assert presentation.spinner_status == "Reconnecting provider stream…"
    assert presentation.notice_only


def test_special_notices_preserve_spinner_and_normal_projection_resets_it() -> None:
    """Bypass/advice preserve status; regular output clears transient status."""
    from src.tui.session_event_presentation import SessionEventPresentation

    kinds: list[StreamEventKind] = ["preflight_bypassed", "compaction_advised"]
    for kind in kinds:
        presentation = SessionEventPresentation.build(event=AgentStreamEventDAO(kind=kind))
        assert presentation.notice is not None
        assert presentation.notice_only
        assert not presentation.update_spinner
    ordinary = SessionEventPresentation.build(event=AgentStreamEventDAO(kind="text_delta", delta="answer"))
    assert ordinary.notice is None
    assert not ordinary.notice_only
    assert ordinary.update_spinner
    assert ordinary.spinner_status is None


def test_compaction_failure_and_retry_preserve_existing_status_copy() -> None:
    """Lifecycle status translation does not consume projector-owned notices."""
    from src.tui.session_event_presentation import SessionEventPresentation

    failed = SessionEventPresentation.build(
        event=AgentStreamEventDAO(kind="compaction_failed", content="busy")
    )
    assert failed.spinner_status == "Compaction failed: busy"
    assert not failed.notice_only
    retry = SessionEventPresentation.build(event=AgentStreamEventDAO(kind="run_retrying"))
    assert retry.spinner_status == "Retrying…"
    assert retry.notice_only
    assert retry.notice is None
