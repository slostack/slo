"""Captured delivery identity checks against real temporary lease storage."""

import asyncio
import threading
from copy import copy
from pathlib import Path

from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from unittest.mock import PropertyMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.inbox.dao import SessionOwnershipLeaseDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.workflows.service import DetachedWorkflowAppService


async def test_preparation_notice_failure_still_registers_task(tmp_path: Path) -> None:
    """Optional preparing diagnostics cannot prevent the tracked preparation owner."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()

    async def prepare() -> None:
        """Hold preparation until its registered task has been observed."""
        entered.set()
        await release.wait()

    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch.object(
                type(session), "preparation_status", new_callable=PropertyMock, return_value="pending"
            ),
            patch.object(session, "prepare_startup", side_effect=prepare),
            patch.object(app, "_write_adapter_line", side_effect=RuntimeError("notice failure")),
        ):
            try:
                app._start_session_preparation()
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert app._preparation_task is not None
                release.set()
                await app._preparation_task
            finally:
                release.set()
                await app._cancel_session_preparation()


async def test_direct_preparation_cancellation_preserves_delivery(tmp_path: Path) -> None:
    """A cancelled catalog worker propagates cancellation without repainting or losing delivery."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()

    async def prepare() -> None:
        """Hold the catalog boundary without contacting a provider."""
        entered.set()
        await release.wait()

    async with app.run_test() as pilot:
        await pilot.pause()
        timers = (app._lease_timer, app._inbox_timer)
        assert app._lease_store is not None
        lease = await app._lease_store.read(session_id=session.session_id)
        with (
            patch.object(session, "prepare_startup", side_effect=prepare),
            patch.object(app, "_write_adapter_line") as notice,
            patch.object(app, "_refresh_title_bar") as title,
            patch.object(app, "_refresh_usage_status_bar") as usage,
        ):
            task = asyncio.create_task(coro=app._prepare_mounted_session(session=session))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                task.cancel("direct preparation")
                with pytest.raises(asyncio.CancelledError, match="direct preparation"):
                    await task
                notice.assert_not_called()
                title.assert_not_called()
                usage.assert_not_called()
                assert (app._lease_timer, app._inbox_timer) == timers
                assert await app._lease_store.read(session_id=session.session_id) == lease
                assert not app._delivery_quiescing
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


async def test_rollback_preserves_successor_after_release(tmp_path: Path) -> None:
    """Release continuation must not clear service/renderer published by a successor."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    app._build_session_delivery(session=session)
    app._ensure_workflow_renderer()
    store = app._lease_store
    assert store is not None
    entered, resume = asyncio.Event(), asyncio.Event()
    release = store.release

    async def blocked_release(*, session_id: str, owner_id: str) -> bool:
        """Hold the completed real release before rollback clears collaborators."""
        result = await release(session_id=session_id, owner_id=owner_id)
        entered.set()
        await resume.wait()
        return result

    async def displace() -> None:
        """Install real successor collaborators at the post-release boundary."""
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert app._workflow_handle_store is not None
        assert app._workflow_renderer is not None
        app._workflow_app_service = DetachedWorkflowAppService(
            workflow_handle_store=app._workflow_handle_store, owner_session_id="successor"
        )
        app._workflow_renderer = copy(app._workflow_renderer)
        successor_service = app._workflow_app_service
        successor_renderer = app._workflow_renderer
        resume.set()
        assert app._mount_runtime_task is not None
        await asyncio.shield(app._mount_runtime_task)
        assert app._workflow_app_service is successor_service
        assert app._workflow_renderer is successor_renderer

    with (
        patch.object(store, "release", side_effect=blocked_release),
        patch.object(SessionInboxStore, "ensure_session_inbox", side_effect=RuntimeError("setup failure")),
    ):
        observer = asyncio.create_task(coro=displace())
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await observer
                assert await store.read(session_id=session.session_id) is None
                assert app._delivery_quiescing
        finally:
            resume.set()
            await asyncio.gather(observer, return_exceptions=True)


async def test_captured_absent_store_does_not_release_successor(tmp_path: Path) -> None:
    """An absent pre-await store is not permission to use a later store."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    app._build_session_delivery(session=session)
    service = app._workflow_app_service
    assert service is not None
    app._lease_store = None
    successor = SessionOwnershipLeaseStore(history_root=tmp_path / "successor")
    await successor.acquire(session_id=session.session_id, owner_id=app._session_owner_id, ttl_seconds=60)
    original = service.reconcile_snapshot

    async def reconcile() -> None:
        """Publish a successor after the initializer captured absent storage."""
        await original()
        app._lease_store = successor

    with (
        patch.object(app, "_build_session_delivery"),
        patch.object(service, "reconcile_snapshot", side_effect=reconcile),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._delivery_quiescing
            assert await successor.read(session_id=session.session_id) is not None


@pytest.mark.parametrize("failure", [False, True])
async def test_rollback_release_joins_thread_before_original_cancel(tmp_path: Path, failure: bool) -> None:
    """Repeated cancellation cannot abandon actual release or replace its first cancel."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered = asyncio.Event()
    release = threading.Event()
    terminal = threading.Event()
    loop = asyncio.get_running_loop()
    original = SessionOwnershipLeaseStore._release_sync

    def blocked(self: SessionOwnershipLeaseStore, *, session_id: str, owner_id: str | None) -> bool:
        """Hold the real temp-owned filesystem operation until explicitly released."""
        assert self._history_root.resolve().is_relative_to(tmp_path.resolve())
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=10)
        try:
            result = original(self, session_id=session_id, owner_id=owner_id)
            if failure:
                raise OSError("release defect")
            return result
        finally:
            terminal.set()

    async with app.run_test() as pilot:
        await pilot.pause()
        with patch.object(SessionOwnershipLeaseStore, "_release_sync", new=blocked):
            task = asyncio.create_task(
                coro=app._rollback_session_delivery(session=session, owner_id=app._session_owner_id)
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                for message in ("original", "second", "third"):
                    task.cancel(message)
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                    assert not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError) as caught:
                    await task
                assert caught.value.args == ("original",)
                assert terminal.is_set()
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=session.session_id) is None
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


async def test_repeated_unmount_cancel_joins_actual_acquire_thread(tmp_path: Path) -> None:
    """Public cancellation cannot orphan a lease written by a retained acquire thread."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = SessionOwnershipLeaseStore._acquire_sync

    def acquire(
        self: SessionOwnershipLeaseStore, *, session_id: str, owner_id: str, ttl_seconds: float
    ) -> SessionOwnershipLeaseDAO:
        """Hold the actual off-loop operation after its real write."""
        assert self._history_root.resolve().is_relative_to(tmp_path.resolve())
        lease = original(self, session_id=session_id, owner_id=owner_id, ttl_seconds=ttl_seconds)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=10)
        return lease

    async def cancel_shutdown() -> None:
        """Cancel only the public waiter while its retained shutdown joins mount."""
        await asyncio.wait_for(entered.wait(), timeout=5)
        shutdown = asyncio.create_task(coro=app.on_unmount())
        try:
            await asyncio.sleep(0)
            retained = app._mount_runtime_task
            assert retained is not None
            for _ in range(3):
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
                assert app._mount_runtime_task is retained and not retained.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(shutdown, timeout=5)
            assert retained.done() and not retained.cancelled()
        finally:
            release.set()
            await asyncio.gather(shutdown, return_exceptions=True)

    with patch.object(SessionOwnershipLeaseStore, "_acquire_sync", new=acquire):
        observer = asyncio.create_task(coro=cancel_shutdown())
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await observer
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=session.session_id) is None
                assert app._delivery_quiescing
                assert app._lease_timer is None and app._inbox_timer is None
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)


@pytest.mark.parametrize("phase", ["reconcile", "acquire", "inbox"])
@pytest.mark.parametrize(
    "mutation", ["owner", "session_id", "store", "inbox", "service", "renderer", "session"]
)
async def test_initialization_revalidates_captured_binding(tmp_path: Path, phase: str, mutation: str) -> None:
    """Every real awaited continuation refuses changed identity before further effects."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    app._build_session_delivery(session=session)
    app._ensure_workflow_renderer()
    store = app._lease_store
    assert store is not None
    inbox_store = app._inbox_store
    service = app._workflow_app_service
    session_id = session.session_id
    successor_store = SessionOwnershipLeaseStore(history_root=tmp_path / "successor")
    entered, resume = asyncio.Event(), asyncio.Event()
    target, name = {
        "reconcile": (service, "reconcile_snapshot"),
        "acquire": (store, "acquire"),
        "inbox": (inbox_store, "ensure_session_inbox"),
    }[phase]
    original = getattr(target, name)

    async def boundary(**kwargs):
        """Hold the actual operation's completed result at its continuation boundary."""
        result = await original(**kwargs)
        entered.set()
        await resume.wait()
        return result

    async def displace() -> None:
        """Change precisely one captured dimension while initialization is suspended."""
        await asyncio.wait_for(entered.wait(), timeout=5)
        if mutation == "owner":
            app._session_owner_id = "successor-owner"
        elif mutation == "session_id":
            session._session_id = "successor-session"
        elif mutation == "store":
            app._lease_store = successor_store
        elif mutation == "inbox":
            app._inbox_store = SessionInboxStore(history_root=tmp_path / "successor")
        elif mutation == "renderer":
            assert app._workflow_renderer is not None
            app._workflow_renderer = copy(app._workflow_renderer)
        elif mutation == "session":
            app._session = SloAgentSession.build(
                config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "successor")
            )
        else:
            assert app._workflow_handle_store is not None
            app._workflow_app_service = DetachedWorkflowAppService(
                workflow_handle_store=app._workflow_handle_store, owner_session_id="successor-session"
            )
        resume.set()

    with patch.object(target, name, side_effect=boundary):
        observer = asyncio.create_task(coro=displace())
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await observer
                assert app._lease_timer is None and app._inbox_timer is None
                assert app._delivery_quiescing
                assert await store.read(session_id=session_id) is None
                assert await successor_store.read(session_id=session_id) is None
        finally:
            resume.set()
            await asyncio.gather(observer, return_exceptions=True)


@pytest.mark.parametrize("fault", ["notice", "usage"])
async def test_mount_optional_fault_does_not_skip_runtime(tmp_path: Path, fault: str) -> None:
    """Optional display failures cannot prevent retained mount delivery initialization."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    target, name = (
        (app, "_maybe_render_startup_notice")
        if fault == "notice"
        else (session, "refresh_context_window_snapshot")
    )
    with patch.object(target, name, side_effect=RuntimeError("optional defect")):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._mount_runtime_task is not None and app._mount_runtime_task.done()
            assert app._lease_timer is not None and app._inbox_timer is not None
            assert not app._delivery_quiescing


async def test_replacement_phase_order(tmp_path: Path) -> None:
    """Old delivery is gone before close/adoption; candidate delivery follows UI reset."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        events: list[str] = []
        close = session.close_external_reporting
        release = app._release_replaced_session_lease
        initialize = app._initialize_session_delivery
        clear = app._clear_transcript_and_prompt_queue

        async def record_close():
            """Observe real reporter close after old delivery retirement."""
            events.append("close")
            return await close()

        async def record_release(**kwargs) -> None:
            """Observe actual captured lease release."""
            events.append("release")
            await release(**kwargs)

        async def record_initialize() -> None:
            """Observe real successor delivery initialization."""
            events.append("initialize")
            await initialize()

        async def record_clear() -> None:
            """Observe the existing UI reset boundary."""
            events.append("clear")
            await clear()

        with (
            patch.object(session, "close_external_reporting", side_effect=record_close),
            patch.object(app, "_release_replaced_session_lease", side_effect=record_release),
            patch.object(app, "_initialize_session_delivery", side_effect=record_initialize),
            patch.object(app, "_clear_transcript_and_prompt_queue", side_effect=record_clear),
        ):
            await app._start_new_session(requested_name=None)
        assert events == ["release", "close", "clear", "initialize"]


async def test_missing_lease_store_refuses_acquisition(tmp_path: Path) -> None:
    """The existing acquisition gateway rejects absent construction without I/O."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, enable_history=False))
    app = SloTUI(session=session)
    with pytest.raises(RuntimeError, match="Session lease unavailable"):
        await app._acquire_session_lease(session=session, owner_id=app._session_owner_id)


@pytest.mark.parametrize("failure", ["reconcile", "acquire", "build"])
async def test_initialization_fault_is_contained(tmp_path: Path, failure: str) -> None:
    """Construction and each pre-inbox failure leave local mount usable and no lease."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    target, method = {
        "reconcile": (DetachedWorkflowAppService, "reconcile_snapshot"),
        "acquire": (SessionOwnershipLeaseStore, "acquire"),
        "build": (app, "_build_session_delivery"),
    }[failure]
    with patch.object(target, method, side_effect=RuntimeError("private init defect")):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._lease_timer is None and app._inbox_timer is None
            assert app._delivery_quiescing and not app._replacement_delivery_safe
            assert app._workflow_app_service is None


async def test_duplicate_initialization_preserves_timer_identity(tmp_path: Path) -> None:
    """A second initializer cannot overwrite live timer handles."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    with patch(
        "src.agents.slo_agent.graph.service.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
            supports_explicit_caching=False,
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            timers = (app._lease_timer, app._inbox_timer)
            async with app._prompt_submission_lock:
                await app._initialize_session_delivery()
            assert (app._lease_timer, app._inbox_timer) == timers
            assert not app._delivery_quiescing


async def test_initialization_rollback_uses_acquired_store(tmp_path: Path) -> None:
    """Changing the app store during inbox setup cannot redirect lease rollback."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    original_store = SessionOwnershipLeaseStore(history_root=tmp_path / "history")
    successor_store = SessionOwnershipLeaseStore(history_root=tmp_path / "successor")
    app._lease_store = original_store
    owner = app._session_owner_id
    await successor_store.acquire(session_id=session.session_id, owner_id=owner, ttl_seconds=60)
    original = SessionInboxStore.ensure_session_inbox

    async def inbox(self: SessionInboxStore, *, session_id: str) -> None:
        """Swap stores only after the real inbox and original lease exist."""
        await original(self, session_id=session_id)
        app._lease_store = successor_store
        raise RuntimeError("injected setup failure")

    with (
        patch.object(SessionInboxStore, "ensure_session_inbox", new=inbox),
        patch(
            "src.agents.slo_agent.graph.service.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]),
                supports_explicit_caching=False,
            ),
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await original_store.read(session_id=session.session_id) is None
            assert await successor_store.read(session_id=session.session_id) is not None


@pytest.mark.parametrize("replace_record", [False, True])
async def test_rollback_releases_captured_owner(tmp_path: Path, replace_record: bool) -> None:
    """Mutation during inbox setup cannot leak our lease or delete another owner's."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    captured_owner = app._session_owner_id
    original = SessionInboxStore.ensure_session_inbox

    async def inbox(self: SessionInboxStore, *, session_id: str) -> None:
        """Fail after real inbox creation and a competing owner mutation."""
        await original(self, session_id=session_id)
        app._session_owner_id = "successor-owner"
        assert app._lease_store is not None
        if replace_record:
            await app._lease_store.acquire(session_id=session_id, owner_id="successor-owner", ttl_seconds=60)
        raise RuntimeError("injected setup failure")

    with (
        patch.object(SessionInboxStore, "ensure_session_inbox", new=inbox),
        patch(
            "src.agents.slo_agent.graph.service.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]),
                supports_explicit_caching=False,
            ),
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._lease_store is not None
            lease = await app._lease_store.read(session_id=session.session_id)
            if replace_record:
                assert lease is not None and lease.owner_id == "successor-owner"
            else:
                assert lease is None, f"orphaned captured owner {captured_owner}"


@pytest.mark.parametrize("mismatch", ["session_id", "owner_id"])
async def test_mount_rejects_mismatched_acquisition(tmp_path: Path, mismatch: str) -> None:
    """A foreign acquisition result must never authorize inbox timers or its deletion."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    original = SessionOwnershipLeaseStore.acquire
    foreign_id = "foreign-session"
    foreign_owner = "foreign-owner"

    async def acquire(
        self: SessionOwnershipLeaseStore, *, session_id: str, owner_id: str, ttl_seconds: float
    ) -> SessionOwnershipLeaseDAO:
        """Persist the mismatched result through the real store, not a loose mock."""
        return await original(
            self,
            session_id=foreign_id if mismatch == "session_id" else session_id,
            owner_id=foreign_owner if mismatch == "owner_id" else owner_id,
            ttl_seconds=ttl_seconds,
        )

    with (
        patch.object(SessionOwnershipLeaseStore, "acquire", new=acquire),
        patch(
            "src.agents.slo_agent.graph.service.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]),
                supports_explicit_caching=False,
            ),
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._delivery_quiescing
            assert not app._replacement_delivery_safe
            assert app._lease_timer is None and app._inbox_timer is None
            assert app._lease_store is not None
            lease = await app._lease_store.read(
                session_id=foreign_id if mismatch == "session_id" else session.session_id
            )
            assert lease is not None
            assert lease.owner_id == (foreign_owner if mismatch == "owner_id" else app._session_owner_id)
