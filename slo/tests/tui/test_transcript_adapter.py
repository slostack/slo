"""Adapter lifetime and fresh-interpreter import ownership after cutover.

Mounted record/before/separator/notice behavior is exercised in
``test_chat_transcript.test_local_adapters_record_without_rendering_and_before_is_visual_only``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.tui.app import SloTUI
from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter
from src.tui.components.chat_transcript.adapters.workflow_progress import WorkflowProgressUpdatesAdapter
from src.tui.components.chat_transcript.component import ChatTranscript
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from tests.tui.test_app import _build_session
from langchain_core.messages import AIMessage


async def empty_history() -> list[TranscriptEntryDAO]:
    """Provide a borrowed empty reader without storage ownership."""
    return []


def test_register_returns_fresh_instances_with_correct_owners() -> None:
    """Transcript adapters borrow the component; progress still borrows the application."""
    transcript = ChatTranscript(history_reader=empty_history)
    app = SloTUI(session=_build_session(responses=[AIMessage(content="unused")]))
    first = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    second = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    first.record(content="one", classes="tool-result")
    assert second.lines == []
    assert first is not second
    assert WorkflowNoticeAdapter.register(tui=transcript)._tui is transcript
    progress = WorkflowProgressUpdatesAdapter.register(tui=app)
    assert progress._tui is app
    assert WorkflowProgressUpdatesAdapter.register(tui=app) is not progress


@pytest.mark.parametrize("adapter_first", [True, False])
@pytest.mark.parametrize(
    "module, class_name",
    [
        ("transcript", "TranscriptNoticeDisplayAdapter"),
        ("workflow_notice", "WorkflowNoticeAdapter"),
        ("workflow_progress", "WorkflowProgressUpdatesAdapter"),
    ],
)
def test_imports_are_acyclic_in_a_fresh_interpreter(
    adapter_first: bool,
    module: str,
    class_name: str,
) -> None:
    """Both import orders work without eager owner imports or old forwarding modules."""
    adapter_import = f"from src.tui.components.chat_transcript.adapters.{module} import {class_name}\n"
    owner_import = "from src.tui.app import SloTUI\nfrom src.tui.components.chat_transcript.component import ChatTranscript\n"
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
