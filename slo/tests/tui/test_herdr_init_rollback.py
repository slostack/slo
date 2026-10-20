"""Mounted delivery rollback with real temporary lease and inbox storage."""

from pathlib import Path
from collections.abc import Callable
from typing import Optional
from textual.timer import Timer, TimerCallback
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@pytest.mark.parametrize("new_stop_fails", [False, True])
async def test_init_subset_preserves_old_retained_timer(tmp_path: Path, new_stop_fails: bool) -> None:
    """Init cleanup neither retries nor forgets another initialization's failed handle."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        old = app.set_interval(interval=60, callback=lambda: None)
        new = app.set_interval(interval=60, callback=lambda: None)
        app._failed_delivery_timers = (old,)
        original = Timer.stop
        stopped: list[Timer] = []

        def stop(timer: Timer) -> None:
            """Record stop identity and optionally retain the new failed resource."""
            stopped.append(timer)
            if timer is new and new_stop_fails:
                raise RuntimeError("stop failure")
            original(timer)

        with patch.object(Timer, "stop", new=stop):
            app._stop_delivery_timers(timers=(new,))
        assert stopped == [new]
        assert app._failed_delivery_timers == ((old, new) if new_stop_fails else (old,))
        with patch.object(Timer, "stop", autospec=True, side_effect=original) as shutdown:
            app._stop_delivery_timers()
        assert old in [call.args[0] for call in shutdown.call_args_list]
        assert not app._failed_delivery_timers


@pytest.mark.parametrize("fails", [False, True])
async def test_displaced_failed_timer_remains_owned(tmp_path: Path, fails: bool) -> None:
    """A displaced handle survives a failed stop and is retried by later cleanup."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        old = app._lease_timer
        successor = app.set_interval(interval=60, callback=lambda: None)
        original = Timer.stop
        calls: list[Timer] = []

        def stop(timer: Timer) -> None:
            """Displace the old slot synchronously before its stop outcome is known."""
            calls.append(timer)
            if timer is old:
                app._lease_timer = successor
                if fails:
                    raise RuntimeError("stop failure")
            original(timer)

        with patch.object(Timer, "stop", new=stop):
            app._stop_delivery_timers()
        assert successor not in calls
        assert app._lease_timer is successor
        with patch.object(Timer, "stop", autospec=True, side_effect=original) as later:
            app._stop_delivery_timers()
        stopped = [call.args[0] for call in later.call_args_list]
        assert (old in stopped) is fails
        assert successor in stopped
        assert app._lease_timer is None


@pytest.mark.parametrize("phase", ["inbox", "timer1", "timer2"])
@pytest.mark.parametrize("change_owner", [False, True])
@pytest.mark.parametrize("stop_fails", [False, True])
async def test_init_rollback_never_stops_successor_timers(
    tmp_path: Path, phase: str, change_owner: bool, stop_fails: bool
) -> None:
    """Displacement preserves successor slots while stopping only this init's timers."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    original_interval = app.set_interval
    original_inbox = SessionInboxStore.ensure_session_inbox
    original_stop = Timer.stop
    created: list[Timer] = []
    successors: list[Timer] = []
    stopped: list[Timer] = []

    def displace() -> None:
        """Install distinct successor handles at the real continuation seam."""
        if change_owner:
            app._session_owner_id = "new-owner"
        successors.extend(original_interval(interval=60, callback=lambda: None) for _ in range(2))
        app._lease_timer, app._inbox_timer = successors

    def interval(
        interval: float,
        callback: Optional[TimerCallback] = None,
        *,
        name: Optional[str] = None,
        repeat: int = 0,
        pause: bool = False,
    ) -> Timer:
        """Capture each actually created delivery timer before displacing its slots."""
        timer = original_interval(interval=interval, callback=callback, name=name, repeat=repeat, pause=pause)
        if callback in (app._renew_session_lease, app._poll_session_inbox):
            created.append(timer)
            if phase == f"timer{len(created)}":
                displace()
        return timer

    async def inbox(self: SessionInboxStore, *, session_id: str) -> None:
        """Complete real storage before simulating a changed binding."""
        await original_inbox(self, session_id=session_id)
        if phase == "inbox":
            displace()

    def stop(timer: Timer) -> None:
        """Record exact handles, not merely stop invocation counts."""
        stopped.append(timer)
        if stop_fails and timer in created:
            raise RuntimeError("injected init stop failure")
        original_stop(timer)

    with (
        patch.object(app, "set_interval", side_effect=interval),
        patch.object(SessionInboxStore, "ensure_session_inbox", new=inbox),
        patch.object(Timer, "stop", new=stop),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert (app._lease_timer, app._inbox_timer) == tuple(successors)
            assert all(timer not in stopped for timer in successors)
            assert all(timer in stopped for timer in created)
            assert len(created) == {"inbox": int(not change_owner), "timer1": 1, "timer2": 2}[phase]
            assert app._delivery_quiescing and not app._replacement_delivery_safe
            assert app._lease_store is not None
            assert await app._lease_store.read(session_id=session.session_id) is None
            assert app._failed_delivery_timers == (tuple(created) if stop_fails else ())
            assert len(app._failed_delivery_timers) <= 2
            before = tuple(created)
            await app._initialize_session_delivery()
            assert tuple(created) == before
            assert (app._lease_timer, app._inbox_timer) == tuple(successors)
            # Retry after leaving the failing stop seam, while still mounted.
            with patch.object(Timer, "stop", autospec=True, side_effect=original_stop) as retry:
                app._stop_delivery_timers()
            assert {call.args[0] for call in retry.call_args_list} == set(
                (*successors, *(created if stop_fails else []))
            )
            assert app._failed_delivery_timers == ()
            assert app._lease_timer is None and app._inbox_timer is None


async def test_timer_stop_preserves_successor_slot(tmp_path: Path) -> None:
    """A stop callback replacing a slot cannot make cleanup clear its successor."""
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
            old_timer = app._lease_timer
            successor = app.set_interval(interval=60, callback=lambda: None)
            original_stop = Timer.stop

            def stop(timer: Timer) -> None:
                """Replace the slot synchronously at the actual stop seam."""
                original_stop(timer)
                if timer is old_timer:
                    app._lease_timer = successor

            try:
                with patch.object(Timer, "stop", new=stop):
                    app._stop_delivery_timers()
                assert app._lease_timer is successor
            finally:
                successor.stop()


@pytest.mark.parametrize("stop_failure", ["lease", "inbox", "both"])
@pytest.mark.parametrize("release_failure", ["none", "false", "error"])
async def test_failed_stops_retain_handles_until_later_cleanup(
    tmp_path: Path, stop_failure: str, release_failure: str
) -> None:
    """Both timers and the lease are attempted despite stop/release/notice faults."""
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
            lease_timer, inbox_timer = app._lease_timer, app._inbox_timer
            assert lease_timer is not None and inbox_timer is not None
            assert app._lease_store is not None
            original_stop = Timer.stop
            original_release = app._lease_store.release
            calls: list[str] = []

            def stop(timer: Timer) -> None:
                """Fail selected exact handles; leave unrelated framework timers alone."""
                kind = "lease" if timer is lease_timer else "inbox"
                if timer in (lease_timer, inbox_timer):
                    calls.append(kind)
                    if stop_failure in (kind, "both"):
                        raise RuntimeError("injected stop failure")
                original_stop(timer)

            async def release(*, session_id: str, owner_id: Optional[str] = None) -> bool:
                """Record the mandatory release attempt and inject the selected fault."""
                calls.append("release")
                if release_failure == "error":
                    raise RuntimeError("injected release failure")
                if release_failure == "false":
                    return False
                return await original_release(session_id=session_id, owner_id=owner_id)

            with (
                patch.object(Timer, "stop", new=stop),
                patch.object(app._lease_store, "release", side_effect=release),
                patch.object(app, "_write_adapter_line", side_effect=RuntimeError("notice failure")),
            ):
                await app._rollback_session_delivery(session=session, owner_id=app._session_owner_id)
            assert calls == ["lease", "inbox", "release"]
            assert app._lease_timer is (lease_timer if stop_failure in ("lease", "both") else None)
            assert app._inbox_timer is (inbox_timer if stop_failure in ("inbox", "both") else None)
            assert app._delivery_quiescing and not app._replacement_delivery_safe
            await app._close_selected_delivery()
            assert app._lease_timer is None and app._inbox_timer is None
            assert await app._lease_store.read(session_id=session.session_id) is None


@pytest.mark.parametrize("failure", ["inbox", "timer1", "timer2", "cutoff1", "cutoff2"])
async def test_mount_setup_failure_rolls_back(tmp_path: Path, failure: str) -> None:
    """Partial initialization is contained before mount returns, not only at unmount."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    original_timer = app.set_interval
    original_inbox = SessionInboxStore.ensure_session_inbox
    registered: list[Timer] = []

    def interval(
        interval: float,
        callback: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        repeat: int = 0,
        pause: bool = False,
    ) -> Timer:
        """Fail only delivery registration, leaving Textual's own timers intact."""
        if callback in (app._renew_session_lease, app._poll_session_inbox):
            if failure == f"timer{len(registered) + 1}":
                raise RuntimeError("injected timer failure")
            timer = original_timer(
                interval=interval, callback=callback, name=name, repeat=repeat, pause=pause
            )
            registered.append(timer)
            if failure == f"cutoff{len(registered)}":
                app._app_closing = True
            return timer
        return original_timer(interval=interval, callback=callback, name=name, repeat=repeat, pause=pause)

    async def inbox(self: SessionInboxStore, *, session_id: str) -> None:
        """Create the real inbox before injecting the initialization failure."""
        await original_inbox(self, session_id=session_id)
        if failure == "inbox":
            raise RuntimeError("injected inbox failure")

    with (
        patch.object(app, "set_interval", side_effect=interval),
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
            assert app._delivery_quiescing
            assert not app._replacement_delivery_safe
            assert app._lease_timer is None and app._inbox_timer is None
            assert app._workflow_app_service is None
            assert app._lease_store is not None
            assert await app._lease_store.read(session_id=session.session_id) is None
