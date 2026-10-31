"""Adapter lifetime and fresh-interpreter import ownership after cutover.

Mounted record/before/separator/notice behavior is exercised in
``test_chat_transcript.test_local_adapters_record_without_rendering_and_before_is_visual_only``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO


async def empty_history() -> list[TranscriptEntryDAO]:
    """Provide a borrowed empty reader without storage ownership."""
    return []


def test_register_returns_fresh_instances_with_correct_owners() -> None:
    """Transcript adapters borrow the component; each registration returns a fresh owner."""
    transcript = ChatTranscriptComponent(history_reader=empty_history)
    first = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    second = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    first.record(content="one", classes="tool-result")
    assert first.is_prior_turn_content_present()
    assert not second.is_prior_turn_content_present()
    assert second.lines == []
    assert first is not second
    workflow_first = WorkflowNoticeAdapter.register(tui=transcript)
    workflow_second = WorkflowNoticeAdapter.register(tui=transcript)
    assert workflow_first is not workflow_second
    assert workflow_first._tui is transcript
    assert workflow_first._loop is second._loop is None
    assert not transcript.is_mounted
    assert list(transcript.children) == []


@pytest.mark.parametrize("adapter_first", [True, False])
@pytest.mark.parametrize(
    "module, class_name",
    [
        ("transcript", "TranscriptNoticeDisplayAdapter"),
        ("workflow_notice", "WorkflowNoticeAdapter"),
    ],
)
def test_imports_are_acyclic_in_a_fresh_interpreter(
    adapter_first: bool,
    module: str,
    class_name: str,
) -> None:
    """Both import orders work without eager owner imports or old forwarding modules."""
    adapter_import = f"from src.tui.components.chat_transcript.adapters.{module} import {class_name}\n"
    owner_import = "from src.tui.components.chat_transcript.component import ChatTranscriptComponent\n"
    script = (
        adapter_import + "assert 'src.tui.app' not in sys.modules\n" + owner_import
        if adapter_first
        else owner_import + adapter_import
    )
    result = subprocess.run(
        [sys.executable, "-c", "import sys\n" + script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_projection_registration_is_inert_without_a_running_loop() -> None:
    """Registration borrows the host without mounting or pinning a delivery loop."""
    from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
    from tests.tui.test_transcript_projector import FakeHost

    host = FakeHost()
    first = TranscriptProjectionAdapter.register(host=host)
    second = TranscriptProjectionAdapter.register(host=host)
    assert first is not second
    assert first._host is second._host is host
    assert first._loop is second._loop is None
    assert host.mount_order == host.recorded == host.lines == []


async def test_registered_projection_lifetimes_leave_borrowed_host_reusable() -> None:
    """Closing one registration rejects its work but cannot close a sibling's host."""
    from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from tests.tui.test_transcript_projector import FakeHost

    host = FakeHost()
    first = TranscriptProjectionAdapter.register(host=host)
    second = TranscriptProjectionAdapter.register(host=host)
    await first.close()
    with pytest.raises(RuntimeError, match="closed"):
        await first.handle(event=AgentStreamEventDAO(kind="text_delta", delta="rejected"))
    await second.handle(event=AgentStreamEventDAO(kind="text_delta", delta="accepted"))
    assert [block.answer for block in host.blocks] == ["accepted"]
    await second.reset()
    await second.handle(event=AgentStreamEventDAO(kind="text_delta", delta="reused"))
    assert [block.answer for block in host.blocks] == ["accepted", "reused"]
    await second.close()
