"""Class-side registration contracts, independently checked from delivery typing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_IMPORTS = """from typing import Self, assert_type
from src.tui.components.protocols import (TranscriptNoticeDisplayProtocol, WorkflowNoticeProtocol, TranscriptProjectionProtocol, WorkflowProgressUpdatesProtocol, MessageSubmissionProtocol)
from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter, TranscriptNoticeMountTarget
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter, TranscriptNoticeTarget
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter, TranscriptMountHost
from src.tui.components.workflow_progress.adapters.workflow_progress import WorkflowProgressUpdatesAdapter, SessionListPresenter
from src.tui.components.workflow_progress.host import WorkflowProgressHost
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO, ProjectionInput
from src.tui.components.workflow_progress.events import WorkflowProgressUpdate
from src.tui.components.prompt_input.adapters.message_submission import MessageSubmissionAdapter
from src.tui.components.prompt_input.submission import SubmissionOutcomeReceiver
from src.agents.slo_agent.messaging.client import SessionMessagingClient
from src.tui.workflows.progress_coordinator import WorkflowProgressSink
"""

_POSITIVE = _IMPORTS + """
display_class: type[TranscriptNoticeDisplayProtocol] = TranscriptNoticeDisplayAdapter
notice_class: type[WorkflowNoticeProtocol] = WorkflowNoticeAdapter
projection_class: type[TranscriptProjectionProtocol] = TranscriptProjectionAdapter
progress_class: type[WorkflowProgressUpdatesProtocol] = WorkflowProgressUpdatesAdapter
submission_class: type[MessageSubmissionProtocol] = MessageSubmissionAdapter

async def consume(mount: TranscriptNoticeMountTarget, notice: TranscriptNoticeTarget, host: TranscriptMountHost, progress_host: WorkflowProgressHost, presenter: SessionListPresenter, projection_event: ProjectionInput, progress_event: WorkflowProgressUpdate, client: SessionMessagingClient, receiver: SubmissionOutcomeReceiver) -> None:
    display = display_class.register(tui=mount)
    workflow = notice_class.register(tui=notice)
    projection = projection_class.register(host=host)
    progress = progress_class.register(host=progress_host, presenter=presenter)
    submission = submission_class.register(client=client, receiver=receiver)
    sink: WorkflowProgressSink = progress
    assert_type(TranscriptNoticeDisplayAdapter.register(tui=mount), TranscriptNoticeDisplayAdapter)
    assert_type(WorkflowNoticeAdapter.register(tui=notice), WorkflowNoticeAdapter)
    assert_type(TranscriptProjectionAdapter.register(host=host), TranscriptProjectionAdapter)
    assert_type(WorkflowProgressUpdatesAdapter.register(host=progress_host, presenter=presenter), WorkflowProgressUpdatesAdapter)
    assert_type(MessageSubmissionAdapter.register(client=client, receiver=receiver), MessageSubmissionAdapter)
    await submission.reset()
    await submission.close()
    await display.handle(event=TranscriptNoticeDAO(content="notice"))
    await workflow.handle(event=TranscriptNoticeDAO(content="workflow"))
    await projection.handle(event=projection_event)
    await progress.handle(event=progress_event)
    await display.reset()
    await workflow.reset()
    await projection.reset()
    await progress.reset()
    await display.close()
    await workflow.close()
    await projection.close()
    await progress.close()
"""

_NEGATIVE = _IMPORTS + """
class DeliveryOnly:
    async def handle(self, *, event: TranscriptNoticeDAO) -> None: pass
    async def reset(self) -> None: pass
    async def close(self) -> None: pass

class InstanceRegister(DeliveryOnly):
    def register(self, *, tui: TranscriptNoticeMountTarget) -> Self: return self

class AsyncRegister(DeliveryOnly):
    @classmethod
    async def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self: return cls()

class WrongReturn(DeliveryOnly):
    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> DeliveryOnly: return DeliveryOnly()

class RestrictedTarget(DeliveryOnly):
    @classmethod
    def register(cls, *, tui: TranscriptNoticeDisplayAdapter) -> Self: return cls()

class SyncHandle:
    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self: return cls()
    def handle(self, *, event: TranscriptNoticeDAO) -> None: pass
    async def reset(self) -> None: pass
    async def close(self) -> None: pass

class SyncReset:
    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self: return cls()
    async def handle(self, *, event: TranscriptNoticeDAO) -> None: pass
    def reset(self) -> None: pass
    async def close(self) -> None: pass

class SyncClose:
    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self: return cls()
    async def handle(self, *, event: TranscriptNoticeDAO) -> None: pass
    async def reset(self) -> None: pass
    def close(self) -> None: pass

missing: type[TranscriptNoticeDisplayProtocol] = DeliveryOnly  # error: assignment
instance: type[TranscriptNoticeDisplayProtocol] = InstanceRegister  # error: assignment
asynchronous: type[TranscriptNoticeDisplayProtocol] = AsyncRegister  # error: assignment
wrong_return: type[TranscriptNoticeDisplayProtocol] = WrongReturn  # error: assignment
restricted: type[TranscriptNoticeDisplayProtocol] = RestrictedTarget  # error: assignment
sync_handle: type[TranscriptNoticeDisplayProtocol] = SyncHandle  # error: assignment
sync_reset: type[TranscriptNoticeDisplayProtocol] = SyncReset  # error: assignment
sync_close: type[TranscriptNoticeDisplayProtocol] = SyncClose  # error: assignment

async def invalid(mount: TranscriptNoticeMountTarget, notice: TranscriptNoticeTarget, host: WorkflowProgressHost, display: TranscriptNoticeDisplayProtocol, receiver: SubmissionOutcomeReceiver, client_obj: SessionMessagingClient) -> None:
    TranscriptNoticeDisplayAdapter.register(tui=notice)  # error: arg-type
    WorkflowNoticeAdapter.register(tui=mount)  # error: arg-type
    TranscriptNoticeDisplayAdapter.register(host=mount)  # error: call-arg
    TranscriptNoticeDisplayAdapter.register(mount)  # error: misc
    WorkflowProgressUpdatesAdapter.register(host=host)  # error: call-arg
    MessageSubmissionAdapter.register(client=notice, receiver=receiver)  # error: arg-type
    MessageSubmissionAdapter.register(client=client_obj, receiver=host)  # error: arg-type
    MessageSubmissionAdapter.register(receiver=receiver)  # error: call-arg
    await display.handle(event=object())  # error: arg-type
"""


def _check_contract(*, tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Check only a test-owned source file; imported production modules remain real."""
    contract = (tmp_path / "registration_contract.py").resolve()
    assert contract.is_relative_to(tmp_path.resolve())
    contract.write_text(source, encoding="utf-8")
    return subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-m",
            "mypy",
            "--cache-dir=/dev/null",
            "--follow-imports=silent",
            str(contract),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_actual_adapter_classes_support_typed_registration_and_delivery(tmp_path: Path) -> None:
    """All-valid class references construct exact lifecycles without typing escapes."""
    result = _check_contract(tmp_path=tmp_path, source=_POSITIVE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_registration_rejects_invalid_class_shapes_dependencies_and_calls(tmp_path: Path) -> None:
    """Every invalid statement fails at its intended location and diagnostic category."""
    result = _check_contract(tmp_path=tmp_path, source=_NEGATIVE)
    expected = {
        (number, line.split("# error: ")[1])
        for number, line in enumerate(_NEGATIVE.splitlines(), start=1)
        if "# error: " in line
    }
    diagnostics = [line for line in result.stdout.splitlines() if ": error:" in line]
    actual = {
        (int(line.split(": error:")[0].rsplit(":", 1)[1]), line.rsplit("[", 1)[1].rstrip("]"))
        for line in diagnostics
    }
    assert result.returncode == 1, result.stdout + result.stderr
    contract = (tmp_path / "registration_contract.py").resolve()
    assert all(line.startswith(f"{contract}:") for line in diagnostics), result.stdout
    assert actual == expected, result.stdout
    assert len(diagnostics) == len(expected), result.stdout
