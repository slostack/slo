"""T2 live viewer authority and deferred T4 construction boundary proofs."""

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import MethodType, ModuleType
from unittest.mock import Mock

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.state_isolation import FakeHerdrFixture
from tests.agents.slo_agent.herdr.test_reporter import reporter

AUTHORITY_CHANGES = (
    ("_viewer_revoked", True),
    ("_closing", True),
    ("_disabled", True),
    ("_activation_released", False),
    ("_lease_held", False),
    ("_sequence_safe", False),
    ("_closed", True),
)


def change_authority(*, owner: HerdrReporter, field: str, value: bool) -> None:
    """Isolate one event-loop-owned predicate without invoking coupled teardown."""
    target = owner._transport if field == "_closed" else owner
    setattr(target, field, value)


def active_reporter(*, root: Path) -> HerdrReporter:
    """Build inert collaborators and set only the two positive authority facts.

    No lease or activation I/O is claimed: these are independent policy inputs.
    """
    owner = reporter(root=root)
    owner._activation_released = owner._lease_held = True
    return owner


@pytest.mark.parametrize(argnames="field,value", argvalues=AUTHORITY_CHANGES)
def test_independent_live_authority(tmp_path: Path, field: str, value: bool) -> None:
    """Each single authority loss immediately changes both predicate and destination."""
    owner = active_reporter(root=tmp_path)
    authority = owner.allows_viewer_admission
    assert authority() is True
    assert owner.destination == "herdr"
    change_authority(owner=owner, field=field, value=value)
    assert authority() is False
    assert owner.destination == "unavailable"
    assert list(tmp_path.iterdir()) == []


class LiveAdmission(RecordingAdmission):
    """Observe the real lock while delegating policy to the captured bound method."""

    def __init__(self, *, owner: HerdrReporter) -> None:
        """Capture callable identity, not a Boolean snapshot or a second policy."""
        super().__init__()
        self.authority: Callable[[], bool] = owner.allows_viewer_admission
        self.lock = owner._transport._command_lock

    def try_admit(self) -> bool:
        """Record only synchronous lock-held evaluations."""
        assert self.lock.locked()
        self.attempts += 1
        return self.authority()


@pytest.mark.parametrize(argnames="field,value", argvalues=AUTHORITY_CHANGES + (("current", False),))
async def test_queued_live_authority(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, field: str, value: bool
) -> None:
    """A queued command must observe changed authority before actual executable entry."""
    owner = active_reporter(root=tmp_path)
    transport = owner._transport
    transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    admission = LiveAdmission(owner=owner)
    command = HerdrCliCommandDAO(argv=("pane", "split", "--pane", owner._config.pane_id))
    await transport._command_lock.acquire()
    invocation = asyncio.create_task(coro=transport.invoke(command=command, admission=admission))
    try:
        async with asyncio.timeout(delay=0.5):
            while not transport._command_lock._waiters:
                await asyncio.sleep(delay=0)
        assert not invocation.done() and admission.attempts == 0
        assert admission.authority() and fake_herdr.capture.read_text() == ""
        if field != "current":
            change_authority(owner=owner, field=field, value=value)
            assert not admission.authority() and owner.destination == "unavailable"
        transport._command_lock.release()
        result = await invocation
        if field == "current":
            assert result.outcome.status == "ok" and result.admitted
            assert admission.attempts == 1 and admission.results == [result]
            assert [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()] == [
                list(command.argv)
            ]
        else:
            assert result.outcome.status == "suppressed" and not result.admitted
            assert admission.attempts == (0 if field == "_closed" else 1)
            assert admission.results == [] and fake_herdr.capture.read_text() == ""
        assert transport.resources_drained and not transport._command_lock.locked()
    finally:
        if transport._command_lock.locked() and admission.attempts == 0:
            transport._command_lock.release()
        if not invocation.done():
            invocation.cancel()
        await asyncio.gather(invocation, return_exceptions=True)
        await transport.close()


@pytest.fixture
def viewer_constructor(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Substitute only the absent T4 import/constructor, never reporter assembly."""
    module = ModuleType("src.agents.slo_agent.herdr.visualizer")
    constructor = Mock(name="HerdrVisualizerLauncher")
    setattr(module, "HerdrVisualizerLauncher", constructor)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return constructor


def test_build_visualizer_identity(tmp_path: Path, viewer_constructor: Mock) -> None:
    """Assembly returns the constructed viewer with exact shared transport and live owner."""
    owner = active_reporter(root=tmp_path)
    viewer = owner.build_visualizer()
    assert viewer is viewer_constructor.return_value
    viewer_constructor.assert_called_once_with(
        transport=owner._transport,
        owner_pane_id=owner._config.pane_id,
        authority=owner.allows_viewer_admission,
    )
    arguments = viewer_constructor.call_args.kwargs
    assert arguments["transport"] is owner._transport
    authority = arguments["authority"]
    assert isinstance(authority, MethodType)
    assert authority.__self__ is owner
    assert authority.__func__ is HerdrReporter.allows_viewer_admission
    assert authority() is True
    owner.revoke_viewer_admission()
    assert authority() is False and owner.destination == "unavailable"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(argnames="field,value", argvalues=AUTHORITY_CHANGES)
def test_build_visualizer_refuses_lost_authority(
    tmp_path: Path, viewer_constructor: Mock, field: str, value: bool
) -> None:
    """Closed, unsafe and each other independent loss refuse before construction."""
    owner = active_reporter(root=tmp_path)
    change_authority(owner=owner, field=field, value=value)
    with pytest.raises(HerdrRestoreUnavailableError):
        owner.build_visualizer()
    viewer_constructor.assert_not_called()
    assert list(tmp_path.iterdir()) == []
