"""Applied transcript delivery through the real application and temporary history."""

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Static
from textual.await_remove import AwaitRemove

from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent, TranscriptScrollComponent
from src.tui.components.chat_transcript.commands import (
    EchoUserDAO,
    TranscriptCommand,
    PresentAgentEventDAO,
    HydrateTranscriptDAO,
    BindHistoryDAO,
    ClearTranscriptDAO,
    ScrollCommand,
    SetScrollPositionDAO,
    TranscriptNoticeDAO,
)
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.components.protocols import ComponentProtocol, AdapterProtocol
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.tui.test_chat_transcript_app_integration import RecordingSessionFactory, session_config
from tests.tui.test_chat_transcript import TranscriptTestApp
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO


class HeldUserTranscript(ChatTranscriptComponent):
    """Hold an admitted mount to order lifecycle callers deterministically."""

    def __init__(self) -> None:
        """Use an empty borrowed history and explicit mount barriers."""
        super().__init__(history_reader=empty_history)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def mount_user_message_block(self, *, text: str, before: int | None = None) -> UserMessageBlock:
        """Delay only the first user mount, preserving the real Textual host."""
        if text == "held":
            self.entered.set()
            await self.release.wait()
        return await super().mount_user_message_block(text=text, before=before)


async def empty_history() -> list[TranscriptEntryDAO]:
    """Supply a borrowed empty replay source."""
    return []


async def test_queued_delivery_rejects_after_close_at_serialized_boundary() -> None:
    """A caller admitted before close must not silently succeed behind retirement."""
    transcript = HeldUserTranscript()
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            held = asyncio.create_task(transcript.handle(command=EchoUserDAO(text="held")))
            await transcript.entered.wait()
            closing = asyncio.create_task(transcript.close())
            await asyncio.sleep(0)
            queued = asyncio.create_task(transcript.handle(command=EchoUserDAO(text="late")))
            await asyncio.sleep(0)
            transcript.release.set()
            await held
            await closing
            with pytest.raises(RuntimeError, match="closed|retired"):
                await queued
            assert not transcript.query(UserMessageBlock)


async def test_queued_reset_rejects_after_close_without_reopening_presentation() -> None:
    """A reset already waiting for the lifecycle lock cannot silently succeed after close."""
    transcript = HeldUserTranscript()
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            held = asyncio.create_task(transcript.handle(command=EchoUserDAO(text="held")))
            await transcript.entered.wait()
            closing = asyncio.create_task(transcript.close())
            await asyncio.sleep(0)
            binding = asyncio.create_task(transcript.bind_history(history_reader=empty_history))
            await asyncio.sleep(0)
            transcript.release.set()
            await held
            await closing
            with pytest.raises(RuntimeError, match="closed"):
                await binding


async def test_reset_cancels_hydration_without_waiting_for_reader_release() -> None:
    """Reset joins a cancelled read and permits the retained reader to be reused."""
    entered, cancelled = asyncio.Event(), asyncio.Event()
    calls = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Block the first read until cancellation, then serve the successor."""
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return []

    transcript = ChatTranscriptComponent(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            hydration = asyncio.create_task(transcript.handle(command=HydrateTranscriptDAO()))
            await entered.wait()
            await transcript.reset()
            assert cancelled.is_set()
            with pytest.raises(asyncio.CancelledError):
                await hydration
            await transcript.handle(command=HydrateTranscriptDAO())
            assert calls == 2


class HeldNoticeTarget:
    """Borrowed destination with deterministic completion and a usable lifetime."""

    def __init__(self) -> None:
        """Retain barriers and observable deliveries without a framework harness."""
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.contents: list[str] = []

    async def handle(self, *, command: TranscriptNoticeDAO) -> None:
        """Keep delivery in flight until the test releases the target."""
        self.entered.set()
        await self.release.wait()
        self.contents.append(command.content)

    async def mount_transcript_notice(self, *, notice: TranscriptNoticeDAO) -> None:
        """Implement the specialized display leaf with the same barrier."""
        await self.handle(command=notice)


@pytest.mark.parametrize("display", [False, True])
@pytest.mark.parametrize("close", [False, True])
async def test_notice_retirement_joins_delivery_and_preserves_borrowed_target(
    display: bool, close: bool
) -> None:
    """Retirement cannot return early or let queued old delivery enter a successor."""
    from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
    from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter

    target = HeldNoticeTarget()
    adapter = (
        TranscriptNoticeDisplayAdapter.register(tui=target)
        if display
        else WorkflowNoticeAdapter.register(tui=target)
    )
    async with asyncio.timeout(5):
        delivery = asyncio.create_task(adapter.handle(event=TranscriptNoticeDAO(content="held")))
        await target.entered.wait()
        retirement = asyncio.create_task(adapter.close() if close else adapter.reset())
        await asyncio.sleep(0)
        queued = asyncio.create_task(adapter.handle(event=TranscriptNoticeDAO(content="stale")))
        await asyncio.sleep(0)
        try:
            assert not retirement.done()
        finally:
            target.release.set()
            await delivery
            await retirement
        with pytest.raises(RuntimeError, match="closed|retired"):
            await queued
        assert target.contents == ["held"]
        if isinstance(adapter, TranscriptNoticeDisplayAdapter):
            assert adapter.lines == []
        await target.handle(command=TranscriptNoticeDAO(content="borrowed survives"))
        if not close:
            await adapter.handle(event=TranscriptNoticeDAO(content="successor"))
        await adapter.close()
        await adapter.close()
        assert "borrowed survives" in target.contents


class FailingRemovalStatic(Static):
    """Fail one cleanup attempt so close must remain retryable."""

    fail_removal = True

    def remove(self) -> AwaitRemove:
        """Expose a deterministic native removal failure before delegation."""
        if self.fail_removal:
            self.fail_removal = False
            raise RuntimeError("removal failed")
        return super().remove()


async def test_failed_binding_keeps_old_history_until_successful_retry() -> None:
    """Cleanup failure propagates without adopting the candidate history reader."""
    from src.tui.components.chat_transcript.commands import MountTreeOutputDAO

    async def old_history() -> list[TranscriptEntryDAO]:
        """Return a distinct old binding value."""
        return [TranscriptEntryDAO(kind="user", content="old")]

    async def new_history() -> list[TranscriptEntryDAO]:
        """Return a distinct candidate binding value."""
        return [TranscriptEntryDAO(kind="user", content="new")]

    transcript = ChatTranscriptComponent(history_reader=old_history)
    async with TranscriptTestApp(transcript=transcript).run_test():
        await transcript.handle(command=MountTreeOutputDAO(widget=FailingRemovalStatic("failure")))
        with pytest.raises(RuntimeError, match="removal failed"):
            await transcript.handle(command=BindHistoryDAO(history_reader=new_history))
        await transcript.handle(command=HydrateTranscriptDAO())
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == ["old"]
        await transcript.handle(command=BindHistoryDAO(history_reader=new_history))
        await transcript.handle(command=HydrateTranscriptDAO())
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == ["new"]


async def test_close_retries_failed_cleanup_and_reset_clears_exceptional_siblings() -> None:
    """Tree output is transient, and a failed close must not report false completion."""
    from src.tui.components.chat_transcript.commands import MountTreeOutputDAO, ToggleTranscriptDetailsDAO
    from textual.widgets import Static

    transcript = ChatTranscriptComponent(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test():
        tree = Static("tree", id="transient-tree")
        await transcript.handle(command=MountTreeOutputDAO(widget=tree))
        await transcript.handle(command=ToggleTranscriptDetailsDAO())
        await transcript.reset()
        assert not transcript.query("#transient-tree")
        assert transcript._global_expand_all is None
        failed = FailingRemovalStatic("retry", id="failed-removal")
        await transcript.handle(command=MountTreeOutputDAO(widget=failed))
        with pytest.raises(RuntimeError, match="removal failed"):
            await transcript.close()
        with pytest.raises(RuntimeError, match="closed"):
            await transcript.handle(command=EchoUserDAO(text="late"))
        await transcript.close()
        assert not transcript.query("#failed-removal")
        await transcript.close()


async def test_component_reset_joins_workflow_notices_waiting_behind_projection() -> None:
    """Queued adapter notices cannot reappear after component reset has returned."""
    transcript = HeldUserTranscript()
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            held = asyncio.create_task(transcript.handle(command=EchoUserDAO(text="held")))
            await transcript.entered.wait()
            first = asyncio.create_task(
                transcript.workflow_notice.handle(event=TranscriptNoticeDAO(content="first"))
            )
            await asyncio.sleep(0)
            second = asyncio.create_task(
                transcript.workflow_notice.handle(event=TranscriptNoticeDAO(content="second"))
            )
            resetting = asyncio.create_task(transcript.reset())
            await asyncio.sleep(0)
            transcript.release.set()
            await held
            await resetting
            await asyncio.gather(first, second, return_exceptions=True)
            assert transcript.logical_copy_text() == ""
            assert not transcript.query_one("#transcript-content").children
            await transcript.workflow_notice.handle(event=TranscriptNoticeDAO(content="new lifetime"))
            assert transcript.logical_copy_text() == "new lifetime"


@pytest.mark.parametrize("display", [False, True])
async def test_notice_cancelled_retirement_joins_before_propagating(display: bool) -> None:
    """Repeated caller cancellation cannot orphan a borrowed-target delivery."""
    from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
    from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter

    target = HeldNoticeTarget()
    adapter = (
        TranscriptNoticeDisplayAdapter.register(tui=target)
        if display
        else WorkflowNoticeAdapter.register(tui=target)
    )
    async with asyncio.timeout(5):
        delivery = asyncio.create_task(adapter.handle(event=TranscriptNoticeDAO(content="held")))
        await target.entered.wait()
        closing = asyncio.create_task(adapter.close())
        await asyncio.sleep(0)
        for _ in range(2):
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
        target.release.set()
        await delivery
        with pytest.raises(asyncio.CancelledError):
            await closing
        await adapter.close()
        await target.handle(command=TranscriptNoticeDAO(content="survives"))
        assert target.contents == ["held", "survives"]


async def test_projection_cleanup_failure_is_retryable_without_closing_host() -> None:
    """Terminal rejection and cleanup completion are distinct after a failed retirement."""

    class FailingProjection(TranscriptProjectionAdapter):
        """Fail once at the existing identity-retirement seam."""

        failures = 0

        def _reset_for_new_run(self) -> None:
            """Fail first, then execute the real identity cleanup."""
            self.failures += 1
            if self.failures == 1:
                raise ValueError("identity cleanup failed")
            super()._reset_for_new_run()

    transcript = ChatTranscriptComponent(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test():
        adapter = FailingProjection(host=transcript)
        with pytest.raises(ValueError, match="cleanup failed"):
            await adapter.close()
        await adapter.close()
        assert adapter.failures == 2
        with pytest.raises(RuntimeError, match="closed"):
            await adapter.handle(event=AgentStreamEventDAO(kind="compaction_started"))
        await transcript.handle(command=EchoUserDAO(text="borrowed"))


async def test_projection_union_applies_replay_user_and_joins_cancelled_close() -> None:
    """All projector inputs use the admitted seam and cancelled close still joins."""
    from src.tui.components.chat_transcript.commands import (
        ProjectUserTurnDAO,
        ProjectReplayEntryDAO,
        ProjectionInput,
    )

    transcript = HeldUserTranscript()
    async with TranscriptTestApp(transcript=transcript).run_test():
        projector: AdapterProtocol[ProjectionInput] = TranscriptProjectionAdapter.register(host=transcript)
        await projector.handle(
            event=ProjectReplayEntryDAO(entry=TranscriptEntryDAO(kind="user", content="replay"))
        )
        async with asyncio.timeout(5):
            delivery = asyncio.create_task(projector.handle(event=ProjectUserTurnDAO(text="held")))
            await transcript.entered.wait()
            closing = asyncio.create_task(projector.close())
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
            transcript.release.set()
            await delivery
            with pytest.raises(asyncio.CancelledError):
                await closing
        with pytest.raises(RuntimeError, match="closed"):
            await projector.handle(event=ProjectUserTurnDAO(text="late"))
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == [
            "replay",
            "held",
        ]
        await transcript.handle(command=EchoUserDAO(text="borrowed host survives"))


async def test_rebinding_joins_stale_read_and_rejects_queued_old_hydration() -> None:
    """A cancelled old read cannot repaint or consume a successor history binding."""
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    successor_reads = 0

    async def old_reader() -> list[TranscriptEntryDAO]:
        """Return stale data even after cancellation to challenge generation admission."""
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return [TranscriptEntryDAO(kind="user", content="stale")]

    async def successor() -> list[TranscriptEntryDAO]:
        """Count reads made against the replacement binding."""
        nonlocal successor_reads
        successor_reads += 1
        return [TranscriptEntryDAO(kind="user", content="successor")]

    transcript = ChatTranscriptComponent(history_reader=old_reader)
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            old = asyncio.create_task(transcript.handle(command=HydrateTranscriptDAO()))
            await entered.wait()
            queued = asyncio.create_task(transcript.handle(command=HydrateTranscriptDAO()))
            await asyncio.sleep(0)
            binding = asyncio.create_task(transcript.handle(command=BindHistoryDAO(history_reader=successor)))
            await cancelled.wait()
            assert not binding.done()
            release.set()
            await asyncio.gather(old, binding)
            with pytest.raises(RuntimeError, match="retired"):
                await queued
        assert successor_reads == 0
        assert not transcript.query(UserMessageBlock)
        await transcript.handle(command=HydrateTranscriptDAO())
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == ["successor"]


async def test_delivery_rejects_foreign_loop_and_propagates_mount_failure() -> None:
    """Native UI work stays on its loop and projection failures reach the caller."""

    class FailingMountTranscript(ChatTranscriptComponent):
        """Fail at the public host boundary, not a patched private implementation."""

        async def mount_transcript_notice(self, *, notice: TranscriptNoticeDAO) -> None:
            """Expose a deterministic translation/mount error."""
            raise ValueError("mount rejected")

    transcript = FailingMountTranscript(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test():
        scroll = transcript.query_one(TranscriptScrollComponent)
        with pytest.raises(RuntimeError, match="UI loop"):
            await asyncio.to_thread(
                lambda: asyncio.run(transcript.handle(command=EchoUserDAO(text="foreign")))
            )
        with pytest.raises(RuntimeError, match="UI loop"):
            await asyncio.to_thread(lambda: asyncio.run(scroll.handle(command=SetScrollPositionDAO(y=0))))
        with pytest.raises(ValueError, match="mount rejected"):
            await transcript.workflow_notice.handle(event=TranscriptNoticeDAO(content="not recorded"))
        assert transcript.logical_copy_text() == ""
        await transcript.handle(command=EchoUserDAO(text="still usable"))


async def test_queued_visibility_and_notice_cannot_mutate_during_retirement() -> None:
    """Non-stream commands obey the same serialized admission as mounted content."""
    from src.tui.components.chat_transcript.commands import SetTranscriptVisibilityDAO

    transcript = HeldUserTranscript()
    async with TranscriptTestApp(transcript=transcript).run_test():
        async with asyncio.timeout(5):
            held = asyncio.create_task(transcript.handle(command=EchoUserDAO(text="held")))
            await transcript.entered.wait()
            visibility = asyncio.create_task(
                transcript.handle(command=SetTranscriptVisibilityDAO(visible=False))
            )
            await asyncio.sleep(0)
            try:
                assert not visibility.done()
            finally:
                transcript.release.set()
                await held
                await visibility
            assert not transcript.display


def test_static_contract_rejects_wrong_inputs_async_shape_and_variance(tmp_path: Path) -> None:
    """Run the existing mypy gate against invalid consumers, not runtime type ignores."""
    import subprocess
    import sys

    contract = (tmp_path / "negative_contract.py").resolve()
    assert contract.is_relative_to(tmp_path.resolve())
    contract.write_text(
        """from src.tui.components.protocols import ComponentProtocol, AdapterProtocol
from src.tui.components.chat_transcript.commands import EchoUserDAO, TranscriptNoticeDAO, TranscriptCommand, ProjectionInput
from src.tui.components.chat_transcript.component import ChatTranscriptComponent, TranscriptScrollComponent
from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter

async def invalid(t: ChatTranscriptComponent, s: TranscriptScrollComponent, d: TranscriptNoticeDisplayAdapter, w: WorkflowNoticeAdapter, p: TranscriptProjectionAdapter, narrow: ComponentProtocol[EchoUserDAO]) -> None:
    await t.handle(command=object())
    await s.handle(command=EchoUserDAO(text="wrong"))
    await d.handle(event=EchoUserDAO(text="wrong"))
    await w.handle(event=EchoUserDAO(text="wrong"))
    await p.handle(event=TranscriptNoticeDAO(content="wrong"))
    broad: ComponentProtocol[TranscriptCommand] = narrow
    await t.handle(EchoUserDAO(text="positional"))

class Synchronous:
    def handle(self, *, command: EchoUserDAO) -> None: pass
    async def reset(self) -> None: pass
    async def close(self) -> None: pass

bad: ComponentProtocol[EchoUserDAO] = Synchronous()
""",
        encoding="utf-8",
    )
    result = subprocess.run(
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
        timeout=90,
        check=False,
    )
    diagnostics = [line for line in result.stdout.splitlines() if ": error:" in line]
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(diagnostics) == 8, result.stdout
    assert all(str(contract) in line for line in diagnostics), result.stdout
    assert sum("[arg-type]" in line for line in diagnostics) == 5
    assert sum("[assignment]" in line for line in diagnostics) == 2
    assert sum("[misc]" in line for line in diagnostics) == 1


@pytest.mark.parametrize("adapter_name", ["display", "workflow", "projection"])
@pytest.mark.parametrize("operation", ["handle", "reset"])
async def test_transcript_adapters_reject_foreign_loop(adapter_name: str, operation: str) -> None:
    """A bound adapter cannot mutate mounted presentation from another event loop."""
    from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
    from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter

    transcript = ChatTranscriptComponent(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test():
        adapter = (
            TranscriptNoticeDisplayAdapter.register(tui=transcript)
            if adapter_name == "display"
            else WorkflowNoticeAdapter.register(tui=transcript)
        )
        projection = TranscriptProjectionAdapter.register(host=transcript)

        async def deliver() -> None:
            """Enter the concrete typed delivery boundary with a valid event."""
            if adapter_name == "projection":
                await projection.handle(event=AgentStreamEventDAO(kind="text_start"))
            else:
                await adapter.handle(event=TranscriptNoticeDAO(content="notice"))

        async def invoke() -> None:
            """Exercise delivery or reusable retirement on the foreign loop."""
            if operation == "handle":
                await deliver()
            elif adapter_name == "projection":
                await projection.reset()
            else:
                await adapter.reset()

        await deliver()
        with pytest.raises(RuntimeError, match="UI loop"):
            await asyncio.to_thread(lambda: asyncio.run(invoke()))
        await adapter.close()
        await projection.close()


async def test_lifecycle_notice_completes_real_application_delivery(tmp_path: Path) -> None:
    """Lifecycle feedback is mounted and recorded before its caller continues."""
    factory = RecordingSessionFactory()
    session = factory(config=session_config(tmp_path=tmp_path), allow_pending_preparation=True)
    app = SloTUI(session=session)
    async with app.run_test():
        await app._write_lifecycle_notice(content="lifecycle applied", classes="tool-result")
        transcript = app.query_one(ChatTranscriptComponent)
        assert "lifecycle applied" in transcript.logical_copy_text()
        assert any("lifecycle applied" in str(widget.render()) for widget in transcript.query(".tool-result"))


async def test_transcript_delivery_is_applied_and_reset_is_reusable(tmp_path: Path) -> None:
    """Await delivery before paint; reset preserves borrowed history and terminal rejection."""
    factory = RecordingSessionFactory()
    session = factory(config=session_config(tmp_path=tmp_path), allow_pending_preparation=True)
    app = SloTUI(session=session)
    async with app.run_test():
        transcript = app.query_one(ChatTranscriptComponent)
        component: ComponentProtocol[TranscriptCommand] = transcript
        scroll: ComponentProtocol[ScrollCommand] = transcript.query_one(TranscriptScrollComponent)
        await scroll.handle(command=SetScrollPositionDAO(y=0.0))
        await scroll.reset()
        with pytest.raises(TypeError, match="Unsupported"):
            await scroll.handle(command=object())  # type: ignore[arg-type]
        from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter

        display: AdapterProtocol[TranscriptNoticeDAO] = TranscriptNoticeDisplayAdapter.register(
            tui=transcript
        )
        await display.handle(event=TranscriptNoticeDAO(content="display conformance"))
        await display.reset()
        await display.close()
        notice: AdapterProtocol[TranscriptNoticeDAO] = transcript.workflow_notice
        await notice.handle(event=TranscriptNoticeDAO(content="notice", classes="tool-result"))
        assert "notice" in transcript.logical_copy_text()
        await component.handle(
            command=PresentAgentEventDAO(event=AgentStreamEventDAO(kind="compaction_started"))
        )
        assert "(compacting session history)" in transcript.logical_copy_text()
        assert any(
            "compacting session history" in str(widget.render())
            for widget in transcript.query(".assistant-aborted")
        )
        await notice.reset()
        projection: AdapterProtocol[AgentStreamEventDAO] = TranscriptProjectionAdapter.register(
            host=transcript
        )
        await projection.handle(event=AgentStreamEventDAO(kind="compaction_started"))
        await projection.reset()
        await projection.close()
        await projection.close()
        with pytest.raises(RuntimeError, match="closed"):
            await projection.handle(event=AgentStreamEventDAO(kind="compaction_started"))
        await component.handle(command=EchoUserDAO(text="first"))
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == ["first"]
        await component.handle(
            command=PresentAgentEventDAO(
                event=AgentStreamEventDAO(kind="run_completed", content="answer", iteration=1)
            )
        )
        assert "answer" in transcript.logical_copy_text()
        await component.handle(command=ClearTranscriptDAO())
        await component.handle(command=BindHistoryDAO(history_reader=session.hydrate_transcript_entries))
        await component.handle(command=HydrateTranscriptDAO())
        await component.reset()
        await component.reset()
        await component.handle(command=EchoUserDAO(text="second"))
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == ["second"]
        with pytest.raises(TypeError, match="Unsupported"):
            await component.handle(command=object())  # type: ignore[arg-type]
        await component.close()
        await component.close()
        with pytest.raises(RuntimeError, match="closed"):
            await component.handle(command=EchoUserDAO(text="late"))
        with pytest.raises(RuntimeError, match="closed"):
            await component.reset()
        with pytest.raises(RuntimeError, match="closed"):
            await notice.handle(event=TranscriptNoticeDAO(content="late"))
        await scroll.close()
        await scroll.close()
        with pytest.raises(RuntimeError, match="closed"):
            await scroll.handle(command=SetScrollPositionDAO(y=0.0))
        assert await session.hydrate_transcript_entries() == []
