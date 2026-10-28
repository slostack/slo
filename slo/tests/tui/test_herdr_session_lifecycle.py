"""Mounted candidate preparation preserves the selected session until commit."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@pytest.mark.parametrize("failure", ["build", "attach", "name", "cancel", "cancel_before_name", "notice"])
async def test_new_prepare_retains_mounted_owner(tmp_path: Path, failure: str) -> None:
    """Fail real candidate preparation without losing old UI, delivery or pool."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="still usable")]),
            supports_explicit_caching=False,
        ),
    ):
        old = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=old)
        built: list[SloAgentSession] = []
        original_build = SloAgentSession.build
        original_attach = app._attach_pool_to_session
        entered = asyncio.Event()
        release = asyncio.Event()

        def build(*, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
            """Record actual construction, or refuse before publishing a candidate."""
            if failure == "build":
                raise ValueError("private failure sentinel")
            candidate = original_build(config=config, allow_pending_preparation=allow_pending_preparation)
            built.append(candidate)
            return candidate

        def attach(*, session: SloAgentSession) -> None:
            """Fail after actual attachment to prove candidate pool cleanup."""
            original_attach(session=session)
            if failure == "cancel_before_name":
                raise asyncio.CancelledError
            if failure in ("attach", "notice"):
                raise ValueError("private failure sentinel")

        async def rename(self: SloAgentSession, *, session_name: str) -> None:
            """Hold the real candidate rename boundary before failure or cancellation."""
            entered.set()
            await release.wait()
            raise ValueError("private failure sentinel")

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._chat_transcript.echo_user(text="old transcript")
            await app._queue_prompt(text="held prompt")
            await pilot.pause()
            assert app._chat_transcript._transcript_content is not None
            children = tuple(app._chat_transcript._transcript_content.children)
            queue = app._queued_prompt_block
            history = app._prompt_history
            pool = old.sub_agent_pool
            assert pool is not None
            subscribers = tuple(old._subscribers)
            assert app._lease_store is not None
            lease = await app._lease_store.read(session_id=old.session_id)

            async def hold_preparation() -> None:
                """Keep the prior preparation owner pending until normal unmount."""
                await asyncio.Event().wait()

            preparation = asyncio.create_task(coro=hold_preparation())
            app._preparation_task = preparation
            original_notice = app._chat_transcript.write_transcript_line

            def notice(*, content: str, classes: str) -> None:
                """A failing diagnostic sink cannot invalidate preserved ownership."""
                if failure == "notice":
                    raise RuntimeError("private notice sentinel")
                original_notice(content=content, classes=classes)

            with (
                patch.object(app._chat_transcript, "write_transcript_line", side_effect=notice),
                patch.object(SloAgentSession, "build", side_effect=build),
                patch.object(app, "_attach_pool_to_session", side_effect=attach),
                patch.object(SloAgentSession, "rename_session", new=rename),
            ):
                task = asyncio.create_task(coro=app._start_new_session(requested_name="candidate"))
                if failure in ("name", "cancel"):
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    if failure == "cancel":
                        task.cancel()
                    else:
                        release.set()
                if failure in ("cancel", "cancel_before_name"):
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    await task
            assert app._session is old
            assert tuple(old._subscribers) == subscribers
            assert not preparation.done()
            assert app._queued_prompt_block is queue
            assert app._queued_prompt_text == "held prompt"
            assert app._prompt_history is history
            assert tuple(app._chat_transcript._transcript_content.children)[: len(children)] == children
            assert await app._lease_store.read(session_id=old.session_id) == lease
            assert old.sub_agent_pool is pool and not pool._sealed
            assert not old._herdr_closing
            for candidate in built:
                assert candidate.session_id != old.session_id
                assert candidate._herdr_closing
                assert candidate.sub_agent_pool is not pool
                assert candidate.sub_agent_pool is not None and candidate.sub_agent_pool._sealed
            async for _event in old.invoke(text="prove retained session"):
                pass
            await pilot.pause()
            assert app._chat_transcript._adapter is not None
            assert "private failure sentinel" not in str(app._chat_transcript._adapter.lines)


@pytest.mark.parametrize("pooled", [False, True])
@pytest.mark.parametrize("requested_name", [None, "fresh name"])
async def test_new_prepared_policy_is_independent(
    tmp_path: Path, pooled: bool, requested_name: str | None
) -> None:
    """Mounted success preserves ordinary new policy but never aliases pool values."""
    from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.credential_dao import ProviderName

    configured_pool = (
        ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=2),
                ModelPoolEntryDAO(model_name="gpt-5.4-mini", provider=ProviderName.OPENAI, priority=7),
            ]
        )
        if pooled
        else None
    )
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="ok")]), supports_explicit_caching=False
        ),
    ):
        old = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                history_root=tmp_path / "history",
                model_name="gpt-5.4",
                model_pool_dao=configured_pool,
                reasoning_level="high",
            )
        )
        app = SloTUI(session=old)
        original_attach = app._attach_pool_to_session
        candidates: list[SloAgentSession] = []

        def attach(*, session: SloAgentSession) -> None:
            """Inspect the actual new candidate before normal attachment/adoption."""
            candidates.append(session)
            assert session._config is not None
            assert session._config.workspace_file is None
            assert not session._config.plugin_paths
            assert session.history_root == old.history_root
            assert session.workdir == old.workdir
            assert session.active_reasoning_level == old.active_reasoning_level
            assert session.model_pool_dao == configured_pool
            if configured_pool is not None:
                assert session.model_pool_dao is not configured_pool
                assert session.model_pool_dao is not None
                assert session.model_pool_dao.entries is not configured_pool.entries
                assert session.model_pool_dao.entries[0] is not configured_pool.entries[0]
                session.model_pool_dao.entries[0].cooldown_seconds = 999
                session.model_pool_dao.entries.reverse()
                assert configured_pool.entries[0].cooldown_seconds == 300
                assert configured_pool.entries[0].priority == 2
            original_attach(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._queue_prompt(text="discard on success")
            with patch.object(app, "_attach_pool_to_session", side_effect=attach):
                await app._start_new_session(requested_name=requested_name)
            assert len(candidates) == 1
            assert app._session is candidates[0]
            assert app._session.session_id != old.session_id
            assert app._session.session_name == requested_name
            assert app._queued_prompt_text is None and app._queued_prompt_block is None
            assert app._render_event not in old._subscribers
            assert app._render_event in app._session._subscribers
            assert old.sub_agent_pool is not None and not old.sub_agent_pool._sealed


@pytest.mark.parametrize("pool_present", [False, True])
@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_candidate_cleanup_joins_repeated_cancellation(
    tmp_path: Path, pool_present: bool, cleanup_error: bool
) -> None:
    """Cancellation at disposal joins candidate owners, even with a throwing notice."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    app = SloTUI(session=old)
    original_attach = app._attach_pool_to_session
    entered = asyncio.Event()
    release = asyncio.Event()
    candidates: list[SloAgentSession] = []
    drains: list[str] = []

    async def drain() -> None:
        """Hold the actual pool drain caller and expose ordinary cleanup defects."""
        drains.append("pool")
        entered.set()
        await release.wait()
        if cleanup_error:
            raise RuntimeError("private cleanup sentinel")

    def attach(*, session: SloAgentSession) -> None:
        """Capture a partially prepared candidate and fail its attachment boundary."""
        candidates.append(session)
        if pool_present:
            original_attach(session=session)
        raise RuntimeError("private attachment sentinel")

    async with app.run_test() as pilot:
        await pilot.pause()
        old_pool = old.sub_agent_pool
        assert old_pool is not None
        from src.agents.slo_agent.orchestrator.pool import SubAgentPool
        from src.agents.slo_agent.herdr.service import NullHerdrReporter

        original_close = NullHerdrReporter.close

        async def close(self: NullHerdrReporter) -> HerdrReporterCloseOutcomeDAO:
            """Provide a barrier when the candidate has no pool."""
            if not pool_present:
                entered.set()
                await release.wait()
            return await original_close(self)

        with (
            patch.object(app, "_attach_pool_to_session", side_effect=attach),
            patch.object(SubAgentPool, "abort_and_drain", side_effect=drain),
            patch.object(NullHerdrReporter, "close", new=close),
            patch.object(
                app._chat_transcript, "write_transcript_line", side_effect=RuntimeError("notice defect")
            ),
        ):
            task = asyncio.create_task(coro=app._start_new_session(requested_name=None))
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert app._candidate_cleanup_task is not None
            assert not app._candidate_cleanup_task.done()
            assert app._session is old and app._render_event in old._subscribers
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await candidates[0].dispose_unmounted_session()
        assert drains == (["pool"] if pool_present else [])
        assert not old_pool._sealed and not old._herdr_closing
        assert app._candidate_cleanup_task is None


async def test_new_rejects_candidate_history_root_change(tmp_path: Path) -> None:
    """An injected different-root candidate cannot enter the destructive swap."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "old"))
    candidate = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "other")
    )
    app = SloTUI(session=old)
    async with app.run_test() as pilot:
        await pilot.pause()
        with patch.object(SloAgentSession, "build", return_value=candidate):
            await app._start_new_session(requested_name=None)
        assert app._session is old
        assert app._render_event in old._subscribers
        assert candidate._herdr_closing
