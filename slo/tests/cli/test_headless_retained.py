"""Actual headless outer-finally ownership with contained subprocesses and leases."""

import asyncio
import gc
import weakref
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.cli.headless import HeadlessRunner
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.state_isolation import FakeHerdrFixture

RetainedOwner = TypeVar("RetainedOwner")


def require_retained(reference: weakref.ReferenceType[RetainedOwner]) -> RetainedOwner:
    """Assert reachability without retaining the owner between observations.

    Args:
        reference: Weak reference to the cleanup owner under test.

    Returns:
        The live owner for this expression only.
    """
    owner = reference()
    assert owner is not None
    return owner


@pytest.mark.parametrize("persistent", [False, True])
async def test_runner_retains_child_and_lease_until_final_drain(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, monkeypatch: pytest.MonkeyPatch, persistent: bool
) -> None:
    """Repeated runner cancellation cannot abandon its real quarantined session."""
    # Extend the registered regular file in place, preserving the guard's inode.
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write("import time\nwhile True: time.sleep(0.05)\n")
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-retained-key"
    )
    monkeypatch.setattr(
        target=CredentialResolver, name="resolve", value=classmethod(lambda cls, **kwargs: credential)
    )
    entered, release = asyncio.Event(), asyncio.Event()
    original_reap = HerdrCliTransport._terminate_and_reap
    attempts: list[asyncio.subprocess.Process] = []

    async def reap(transport: HerdrCliTransport, *, process: asyncio.subprocess.Process) -> None:
        """Fail initial cleanup and close; hold the single final local attempt."""
        fake_herdr.guard.require_registered(path=transport._config.binary_path)
        attempts.append(process)
        if len(attempts) <= 2:
            raise OSError("synthetic reap fault")
        entered.set()
        await release.wait()
        if persistent:
            raise OSError("synthetic persistent reap fault")
        await original_reap(self=transport, process=process)

    monkeypatch.setattr(target=HerdrCliTransport, name="_terminate_and_reap", value=reap)
    runner = HeadlessRunner(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    runner_ref = weakref.ref(runner)
    task = asyncio.create_task(coro=runner.invoke(prompt="synthetic retained question"))
    contender = None
    try:
        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="synthetic retained answer")]),
                supports_explicit_caching=False,
            ),
        ) as factory:
            await asyncio.wait_for(fut=entered.wait(), timeout=10)
        factory.assert_called_once()
        session = runner._session
        assert session is not None and not session._agent_is_injected
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        transport = reporter._transport
        process = transport._active
        assert process is not None and process.returncode is None
        assert attempts == [process, process, process]
        assert runner._terminal_kind == "run_completed"
        assert session._herdr_close_task is not None
        assert session._herdr_close_task.result().resources == "retained"
        assert session._herdr_capture is None and not session._herdr_interactive
        assert session._herdr_closing and not reporter.allows_viewer_admission()
        assert transport.closed and reporter._lease_held
        lease = reporter._sequence_store
        contender = HerdrSequenceStore(
            state_root=reporter._config.state_root,
            socket_namespace=reporter._config.socket_path or "default",
            pane_id=reporter._config.pane_id,
        )
        session_ref, reporter_ref = weakref.ref(session), weakref.ref(reporter)
        del runner, session, reporter
        gc.collect()
        assert runner_ref() is not None
        assert session_ref() is require_retained(runner_ref)._session
        assert reporter_ref() is require_retained(session_ref)._herdr_reporter
        assert require_retained(reporter_ref)._sequence_store is lease
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        wire = fake_herdr.capture.read_text()
        assert len(wire.splitlines()) == 1 and "release-agent" in wire
        assert "--herdr-restore" not in wire
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert transport._active is process and require_retained(reporter_ref)._lease_held
        release.set()
        drain_task = require_retained(session_ref)._herdr_retired_drain_task
        assert drain_task is not None
        final = await asyncio.wait_for(fut=asyncio.shield(drain_task), timeout=3)
        del drain_task
        assert final.replacement == "uncertain"
        assert final.resources == ("retained" if persistent else "drained")
        if persistent:
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            gc.collect()
            assert require_retained(runner_ref)._session is session_ref()
            assert transport._active is process and process.returncode is None
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
        else:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(fut=asyncio.shield(task), timeout=3)
            assert transport.resources_drained and process.returncode is not None
            assert not require_retained(reporter_ref)._lease_held
            contender.acquire()
        assert await require_retained(session_ref).drain_retained_external_resources() is final
        refused = RecordingAdmission()
        result = await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=refused)
        assert result.outcome.status == "suppressed" and not result.admitted
        assert refused.results == []
        assert len(attempts) == 3
        assert fake_herdr.capture.read_text() == wire
    finally:
        # Persistent production teardown deliberately never returns. Only this test
        # restores its owned reap boundary, drains the child, unlocks, then cancels
        # the private pending sentinel. Public runner cancellation is not cleanup.
        release.set()
        monkeypatch.setattr(target=HerdrCliTransport, name="_terminate_and_reap", value=original_reap)
        retained_runner = runner_ref()
        current = retained_runner._session if retained_runner is not None else None
        if current is not None and isinstance(current._herdr_reporter, HerdrReporter):
            owner = current._herdr_reporter
            if not owner._transport.resources_drained:
                await owner._transport._drain_quarantined_resources()
            await owner._release_lease()
            pending = current._herdr_finish_cleanup_task
            if pending is not None and not pending.done():
                pending.cancel()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(fut=asyncio.gather(task, return_exceptions=True), timeout=5)
        if contender is not None:
            contender.close()
    assert current is not None
    assert isinstance(current._herdr_reporter, HerdrReporter)
    assert current._herdr_reporter._transport.resources_drained
    assert require_retained(runner_ref)._operation_credential is None
