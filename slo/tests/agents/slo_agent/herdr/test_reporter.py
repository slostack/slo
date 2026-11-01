"""Reporter ownership and deterministic publication regressions."""

from pathlib import Path

import pytest

from tests.state_isolation import FakeHerdrFixture

from src.agents.slo_agent.herdr.dao import (
    HerdrReportOperation,
    HerdrCliCommandDAO,
    HerdrCommandAdmission,
    HerdrCommandResultDAO,
    HerdrReporterCloseOutcomeDAO,
    HerdrPublicationDAO,
    HerdrReportSnapshotDAO,
    HerdrReporterConfigDAO,
    HerdrRestoreConfigDAO,
    HerdrRestoreCaptureDAO,
    HerdrRestoreReferenceDAO,
)
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore

SESSION = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def plain_slo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a regular contained PATH candidate, never a real launcher."""
    import os

    path = tmp_path / "slo"
    assert path.resolve().parent == tmp_path.resolve() and not path.is_symlink()
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    return path


@pytest.mark.parametrize("path_state", ["missing", "nonexecutable", "directory", "probe_error"])
async def test_missing_plain_slo_withdraws_installed_reference(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plain_slo: Path,
    path_state: str,
) -> None:
    """PATH loss releases an installed reference before identity-only replacement."""
    import json

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    try:
        await owner._consume_publication(publication=facts)
        assert owner._binding is not None and owner._binding.reference is not None
        count = len(fake_herdr.capture.read_text().splitlines())
        if path_state == "missing":
            monkeypatch.setenv("PATH", "")
        elif path_state == "nonexecutable":
            monkeypatch.setenv("PATH", str(tmp_path))
            plain_slo.chmod(0o600)
        elif path_state == "directory":
            monkeypatch.setenv("PATH", str(tmp_path))
            plain_slo.unlink()
            plain_slo.mkdir()
        else:

            def fail_probe(*args: object, **kwargs: object) -> None:
                """Inject a private filesystem failure without logging it."""
                raise OSError("private-probe-sentinel")

            monkeypatch.setattr("src.agents.slo_agent.herdr.reporter.shutil.which", fail_probe)
        await owner._consume_publication(publication=facts)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][count:]
        assert commands[0][1] == "release-agent"
        assert all("--herdr-restore" not in command for command in commands)
        assert owner._binding is not None and owner._binding.reference is None
    finally:
        await owner.close()
        await owner.close_transport()


class Store:
    """Capture immutable inputs without filesystem side effects."""

    def __init__(self) -> None:
        self.calls: list[HerdrRestoreConfigDAO] = []

    def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
        """Return an opaque synthetic reference for each input."""
        self.calls.append(config)
        return HerdrRestoreReferenceDAO(restore_reference="r1-" + "0" * 32)


def publication(*, generation: int = 0, eligible: bool = False) -> HerdrPublicationDAO:
    """Build minimal immutable session facts."""
    capture = (
        HerdrRestoreCaptureDAO(
            config=HerdrRestoreConfigDAO(
                session_id=SESSION,
                model_name="gpt-5.4",
                reasoning_level="off",
                workdir=Path("/tmp"),
            )
        )
        if eligible
        else None
    )
    return HerdrPublicationDAO(
        configuration_generation=generation,
        snapshot=HerdrReportSnapshotDAO(session_id=SESSION, state="idle", tokens=()),
        restore_capture=capture,
    )


def reporter(*, root: Path) -> HerdrReporter:
    """Construct inert collaborators under the caller's temporary root."""
    config = HerdrReporterConfigDAO(
        pane_id="p", binary_path=root / "fake", state_root=root, metadata_profile="compact"
    )
    return HerdrReporter(
        config=config,
        transport=HerdrCliTransport(config=config, environment={}),
        sequence_store=HerdrSequenceStore(state_root=root, socket_namespace="default", pane_id="p"),
        restore_store=Store(),
    )


async def test_background_failure_is_retrieved_immediately(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A completed worker defect is retrieved before eventual close, with fixed text."""
    import asyncio

    owner = reporter(root=tmp_path)

    async def failed() -> None:
        """Raise synthetic private data at the background boundary."""
        raise ValueError("private-worker-sentinel")

    task = asyncio.create_task(coro=failed())
    await asyncio.sleep(delay=0)
    owner._on_background_done(task)
    assert not task._log_traceback
    assert owner._disabled
    assert "herdr_cleanup_unavailable" in caplog.text
    assert "private-worker-sentinel" not in caplog.text


def test_diagnostic_recovery_is_once_per_failure_episode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Repeated success is silent; a failure episode gets exactly one recovery."""
    owner = reporter(root=tmp_path)
    owner._log_failure(category="restore_unavailable")
    owner._log_failure(category="restore_unavailable")
    owner._record_recovery(category="restore_unavailable")
    owner._record_recovery(category="restore_unavailable")
    assert [record.message for record in caplog.records] == [
        "herdr_restore_unavailable",
        "herdr_restore_unavailable_recovered",
    ]


async def test_unsafe_counter_close_emits_fixed_release_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Unsafe durable state forbids even cleanup release and reports that refusal."""
    from src.agents.slo_agent.herdr.dao import HerdrRemoteBindingDAO

    owner = reporter(root=tmp_path)
    owner._sequence_safe = False
    owner._binding = HerdrRemoteBindingDAO(
        configuration_generation=0,
        session_id=SESSION,
        capture=None,
        reference=None,
        certainty="possible",
    )
    assert (await owner.close()).replacement == "uncertain"
    assert "herdr_release_unavailable" in caplog.text
    assert owner._reservation_task is None
    assert list(tmp_path.iterdir()) == []


def test_initial_slots(tmp_path: Path) -> None:
    """Construction allocates no tasks, leases or remote authority."""
    owner = reporter(root=tmp_path)
    assert owner._pending is None and owner._latest is None
    assert owner._save_task is None and owner._reservation_task is None
    assert owner._binding is None and owner._revision == 0
    assert not owner._lease_held
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "case", ["initial", "equal", "new", "lower", "capture", "closing", "disabled", "revoked"]
)
def test_publication_admission(tmp_path: Path, case: str) -> None:
    """Only coherent generations replace the single memory slot."""
    owner = reporter(root=tmp_path)
    first = publication(generation=1)
    owner.publish(publication=first)
    if case in ("closing", "disabled"):
        setattr(owner, "_" + case, True)
    if case == "revoked":
        owner.revoke_viewer_admission()
    candidate = publication(
        generation=2 if case == "new" else 0 if case == "lower" else 1, eligible=case == "capture"
    )
    if case in ("lower", "capture"):
        with pytest.raises(ValueError, match="publication_invalid"):
            owner.publish(publication=candidate)
    else:
        owner.publish(publication=candidate)
    assert owner._revision == (2 if case == "new" else 1)
    assert owner._latest == (candidate if case == "new" else first)
    assert not owner.allows_viewer_admission()
    assert list(tmp_path.iterdir()) == []


async def test_save_exact_association(tmp_path: Path) -> None:
    """Off-loop save retains exact input and adopts only its current generation."""
    owner = reporter(root=tmp_path)
    first = publication(eligible=True)
    owner.publish(publication=first)
    saved = await owner._save_capture(publication=first)
    owner._adopt_save(saved=saved)
    assert owner._saved == saved and saved.capture == first.restore_capture
    owner.publish(publication=publication(generation=1))
    owner._saved = None
    owner._adopt_save(saved=saved)
    assert owner._saved is None
    with pytest.raises(Exception, match="Saved Herdr restore"):
        await owner._save_capture(publication=publication())


@pytest.mark.parametrize("eligible", [True, False])
async def test_save_selection(tmp_path: Path, eligible: bool) -> None:
    """Eligible saves are reused, while ineligible facts never touch storage."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=eligible)
    owner.publish(publication=facts)
    await owner._ensure_saved_restore(publication=facts)
    await owner._ensure_saved_restore(publication=facts)
    assert isinstance(owner._restore_store, Store)
    assert len(owner._restore_store.calls) == int(eligible)
    assert owner._save_task is None
    assert (owner._saved is not None) is eligible


async def test_failed_save_does_not_requeue(tmp_path: Path) -> None:
    """A storage failure is bounded by the next external wake."""
    owner = reporter(root=tmp_path)

    class FailedStore(Store):
        def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
            """Refuse without returning private text to the scheduler."""
            raise ValueError("private")

    owner._restore_store = FailedStore()
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._pending = None
    await owner._ensure_saved_restore(publication=facts)
    assert owner._saved is None and owner._pending is None


async def test_reservation_uses_durable_sources(tmp_path: Path) -> None:
    """Each ticket reserves its source independently before becoming admissible."""
    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    try:
        claim = await owner._reserve_ticket(operation="claim", publication=publication())
        clear = await owner._reserve_ticket(operation="clear", publication=publication())
        assert claim is not None and clear is not None
        assert claim.sequence == clear.sequence == 1
        assert owner._reserved_ticket is clear
        owner._sequence_store.close()
        assert await owner._reserve_ticket(operation="claim", publication=publication()) is None
        assert owner._disabled and not owner._sequence_safe
    finally:
        owner._sequence_store.close()


@pytest.mark.parametrize("case", ["none", "same", "generation", "withdrawal", "closing", "revision"])
def test_binding_policy(tmp_path: Path, case: str) -> None:
    """Currentness and exact binding independently gate ordinary work."""
    from src.agents.slo_agent.herdr.dao import HerdrRemoteBindingDAO, HerdrReportTicketDAO

    owner = reporter(root=tmp_path)
    facts = publication()
    owner.publish(publication=facts)
    if case != "none":
        owner._binding = HerdrRemoteBindingDAO(
            configuration_generation=int(case == "generation"),
            session_id=SESSION,
            capture=None,
            reference=None,
            certainty="confirmed",
        )
    owner._withdrawal_pending = case == "withdrawal"
    owner._closing = case == "closing"
    ticket = HerdrReportTicketDAO(
        configuration_generation=0, report_revision=1, operation="clear", sequence=1, publication=facts
    )
    assert owner._binding_allows(ticket=ticket) is (case in ("same", "closing", "revision"))
    assert owner._is_current(configuration_generation=0, revision=2 if case == "revision" else 1) is (
        case not in ("closing", "revision")
    )


@pytest.mark.parametrize("operation", ["claim", "restore", "activation_release", "shutdown_release"])
def test_possible_binding(tmp_path: Path, operation: HerdrReportOperation) -> None:
    """Commit captures possible effects from the ticket rather than latest facts."""
    from src.agents.slo_agent.herdr.dao import (
        HerdrReportTicketDAO,
        HerdrRemoteBindingDAO,
        HerdrSavedRestoreDAO,
    )

    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    assert facts.restore_capture is not None
    saved = HerdrSavedRestoreDAO(
        configuration_generation=0,
        capture=facts.restore_capture,
        reference=HerdrRestoreReferenceDAO(restore_reference="r1-" + "1" * 32),
    )
    if operation == "restore":
        owner._binding = HerdrRemoteBindingDAO(
            configuration_generation=0,
            session_id=SESSION,
            capture=facts.restore_capture,
            reference=None,
            certainty="confirmed",
        )
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        operation=operation,
        sequence=1,
        publication=None if "release" in operation else facts,
        saved=saved,
    )
    owner._mark_admitted(ticket=ticket)
    if operation == "activation_release":
        assert owner._activation_admitted
    elif operation == "shutdown_release":
        assert owner._shutdown_admitted
    else:
        assert owner._binding is not None
        assert owner._binding.capture == facts.restore_capture
        assert owner._binding.certainty == ("confirmed" if operation == "restore" else "possible")
        assert owner._binding.reference == (saved.reference if operation == "restore" else None)


@pytest.mark.parametrize("case", ["valid", "wrong", "lease", "unsafe", "stale", "closing", "activation"])
def test_lock_admission(tmp_path: Path, case: str) -> None:
    """Only the exact safe current reservation commits possible ownership once."""
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO

    owner = reporter(root=tmp_path)
    facts = publication()
    owner.publish(publication=facts)
    owner._lease_held = case != "lease"
    owner._sequence_safe = case != "unsafe"
    owner._closing = case == "closing"
    owner._starting = case == "activation"
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=0 if case == "stale" else 1,
        operation="activation_release" if case == "activation" else "claim",
        sequence=1,
        publication=None if case == "activation" else facts,
    )
    owner._reserved_ticket = None if case == "wrong" else ticket
    assert owner._admit_command(ticket=ticket) is (case in ("valid", "activation"))
    assert not owner._admit_command(ticket=ticket)


@pytest.mark.parametrize("case", ["current", "stale", "partial", "final", "failed"])
def test_acknowledgement(tmp_path: Path, case: str) -> None:
    """Only current semantic success or the final display patch acknowledges facts."""
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO

    owner = reporter(root=tmp_path)
    facts = publication()
    owner.publish(publication=facts)
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation="clear" if case in ("partial", "final") else "lifecycle",
        publication=facts,
        display_final=case == "final",
    )
    if case == "stale":
        owner.publish(publication=publication(generation=1))
    if case == "failed":
        owner._invalidate_semantic_acknowledgements(ticket=ticket)
    else:
        owner._acknowledge_current(ticket=ticket)
    assert (owner._lifecycle_ack is not None) is (case == "current")
    assert owner._display_ack_revision == (1 if case == "final" else None)


@pytest.mark.parametrize("case", ["ok", "stale", "rejected", "spawn_failed", "duplicate"])
def test_terminal_accounting(tmp_path: Path, case: str) -> None:
    """Admitted effects survive supersession; definitive spawn refusal rolls back."""
    from src.agents.slo_agent.herdr.dao import (
        HerdrReportTicketDAO,
        HerdrCommandResultDAO,
        HerdrCommandOutcomeDAO,
    )

    owner = reporter(root=tmp_path)
    facts = publication()
    owner.publish(publication=facts)
    owner._lease_held = True
    ticket = HerdrReportTicketDAO(
        configuration_generation=0, report_revision=1, sequence=1, operation="claim", publication=facts
    )
    owner._reserved_ticket = ticket
    assert owner._admit_command(ticket=ticket)
    if case == "stale":
        owner.publish(publication=publication(generation=1))
    result = HerdrCommandResultDAO(
        admitted=True,
        spawn_failed=case == "spawn_failed",
        outcome=HerdrCommandOutcomeDAO(
            status="unavailable" if case == "spawn_failed" else "rejected" if case == "rejected" else "ok"
        ),
    )
    owner._record_command_result(ticket=ticket, result=result)
    assert (owner._binding is None) is (case == "spawn_failed")
    assert (owner._lifecycle_ack is not None) is (case in ("ok", "duplicate"))
    if case == "duplicate":
        owner._binding = None
        owner._record_command_result(ticket=ticket, result=result)
        assert owner._binding is None
    assert owner._admitted_ticket is None


@pytest.mark.parametrize(
    "operation", ["claim", "lifecycle", "restore", "replace_release", "activation_release"]
)
def test_lifecycle_commands(tmp_path: Path, operation: HerdrReportOperation) -> None:
    """Wire commands contain fixed identity and opaque reference only."""
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO, HerdrSavedRestoreDAO

    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    assert facts.restore_capture is not None
    saved = HerdrSavedRestoreDAO(
        configuration_generation=0,
        capture=facts.restore_capture,
        reference=HerdrRestoreReferenceDAO(restore_reference="r1-" + "2" * 32),
    )
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=3,
        operation=operation,
        publication=None if operation == "activation_release" else facts,
        saved=saved,
    )
    owner.publish(publication=facts)
    owner._saved = saved
    owner._resume_available = True
    argv = owner._command_for_ticket(ticket=ticket).argv
    if operation.endswith("release"):
        assert argv == (
            "pane",
            "release-agent",
            "p",
            "--source",
            "custom:slo",
            "--agent",
            "slo",
            "--seq",
            "3",
        )
    else:
        assert argv[:3] == ("pane", "report-agent", "p")
        assert argv[7:13] == ("--state", "idle", "--seq", "3", "--agent-session-id", SESSION)
        assert argv[13:] == (
            ("--", "slo", "--resume", SESSION, "--herdr-restore", saved.reference.restore_reference)
            if operation == "restore"
            else ()
        )


@pytest.mark.parametrize("case", ["clear", "set", "empty", "too_many", "both"])
def test_metadata_payload(tmp_path: Path, case: str) -> None:
    """Builders refuse patches outside the owned sixteen-key wire budget."""
    from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO

    owner = reporter(root=tmp_path)
    keys = ("model",) if case in ("clear", "both") else ("model",) * 17 if case == "too_many" else ()
    tokens = (HerdrDisplayTokenDAO(key="turn", value="1"),) if case in ("set", "both") else ()
    if case in ("empty", "too_many", "both"):
        with pytest.raises(ValueError):
            owner._metadata_command(sequence=2, keys=keys, tokens=tokens)
        return
    argv = owner._metadata_command(sequence=2, keys=keys, tokens=tokens).argv
    assert argv[-4:] == ("--ttl-ms", "5000", "--seq", "2")
    assert argv[11:-4] == (("--clear-token", "model") if case == "clear" else ("--token", "turn=1"))


async def test_admission_bridge_refuses_reuse(tmp_path: Path) -> None:
    """The transport delegate cannot repeat even a refused admission."""
    from src.agents.slo_agent.herdr.reporter import HerdrReporterAdmission
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO

    owner = reporter(root=tmp_path)
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation="claim",
        publication=publication(),
    )
    bridge = HerdrReporterAdmission(reporter=owner, ticket=ticket)
    assert not bridge.try_admit()
    owner.publish(publication=publication())
    owner._lease_held = True
    owner._reserved_ticket = ticket
    assert not bridge.try_admit()


async def test_real_send_claim(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Real registered execution crosses durable reserve, admission and accounting."""
    import json

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    try:
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert owner._binding is not None
        assert owner._binding.certainty == "confirmed"
        assert json.loads(fake_herdr.capture.read_text())[1] == "report-agent"
    finally:
        await owner._transport.close()
        owner._sequence_store.close()


async def test_report_steps(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Claim, semantic deduplication and two empty-display patches compose for real."""
    import json

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    try:
        assert await owner._prepare_binding(publication=facts, revision=1)
        assert await owner._report_lifecycle(publication=facts, revision=1)
        await owner._report_resume(publication=facts, revision=1)
        await owner._report_metadata(publication=facts, revision=1)
        commands = [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()]
        assert commands == ["report-agent", "report-metadata", "report-metadata"]
        assert owner._display_ack_revision == 1
    finally:
        await owner._transport.close()
        owner._sequence_store.close()


async def test_bootstrap_batch(fake_herdr: FakeHerdrFixture, tmp_path: Path, plain_slo: Path) -> None:
    """Bootstrap installs restore before display and never retries it in the same pass."""
    import json

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    try:
        await owner._consume_publication(publication=facts)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert [command[1] for command in commands] == [
            "report-agent",
            "report-agent",
            "report-metadata",
            "report-metadata",
        ]
        assert "--" not in commands[0] and "--herdr-restore" in commands[1]
        assert owner._pending is None and not owner._wake.is_set()
    finally:
        await owner._transport.close()
        owner._sequence_store.close()


async def test_shutdown_release(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Successful shutdown release permits exactly two reserved inventory clears."""
    import asyncio
    import json

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    owner.publish(publication=publication())
    await owner._prepare_binding(publication=publication(), revision=1)
    owner._closing = True
    owner._close_token = 1
    owner._close_deadline = asyncio.get_running_loop().time() + 2
    try:
        await owner._shutdown_release()
        assert owner._binding is None and owner._shutdown_released
        commands = [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()]
        assert commands == ["report-agent", "release-agent", "report-metadata", "report-metadata"]
    finally:
        await owner._transport.close()
        owner._sequence_store.close()


async def test_close_unstarted(tmp_path: Path) -> None:
    """Unstarted close is cached and seals publication before returning safe evidence."""
    owner = reporter(root=tmp_path)
    result = await owner.close()
    assert result.replacement == "safe"
    assert await owner.close() is result
    owner.publish(publication=publication())
    assert owner._latest is None
    assert not owner.allows_viewer_admission()


async def test_local_drain_before_lease_release(tmp_path: Path) -> None:
    """Remote close retains the lease; sealed drained transport permits unlock."""
    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    await owner.close()
    assert owner.retains_external_resources
    outcome = await owner.close_transport()
    assert outcome.resources == "drained" and not owner.retains_external_resources
    assert owner._transport.closed
    final = await owner.drain_retained_external_resources()
    assert final.replacement == "uncertain" and final.resources == "drained"
    assert await owner.drain_retained_external_resources() is final


async def test_activation(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Activation withdraws retained claims exactly once before granting authority."""
    import json

    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    tmp_path.chmod(0o700)
    await owner.start()
    await owner.start()
    try:
        assert owner.allows_viewer_admission()
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == [
            "release-agent"
        ]
    finally:
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources


async def test_usage_update_during_identical_config_save_reuses_reference(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, plain_slo: Path
) -> None:
    """G1 blocks the real off-loop store and sends newest display with its exact save."""
    import asyncio
    import threading
    import json
    from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO

    entered, release = threading.Event(), threading.Event()

    class BarrierStore(Store):
        def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
            """Wait for explicit publication supersession before completing storage."""
            entered.set()
            assert release.wait(timeout=5)
            return super().save(config=config)

    owner = reporter(root=tmp_path)
    owner._restore_store = BarrierStore()
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    first = publication(eligible=True)
    owner.publish(publication=first)
    task = asyncio.create_task(coro=owner._consume_publication(publication=first))
    try:
        assert await asyncio.to_thread(entered.wait, timeout=5)
        latest = first.model_copy(
            update={
                "snapshot": first.snapshot.model_copy(
                    update={"tokens": (HerdrDisplayTokenDAO(key="turn", value="42"),)}
                )
            }
        )
        owner.publish(publication=latest)
        release.set()
        await task
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert len(owner._restore_store.calls) == 1
        assert "turn=42" in commands[-1]
        assert owner._restore_ack is not None
        assert owner._restore_ack.capture == first.restore_capture
        assert owner._display_ack_revision == 2
    finally:
        release.set()
        await task
        await owner._transport.close()
        owner._sequence_store.close()


@pytest.mark.parametrize("changed_generation", [False, True])
@pytest.mark.parametrize("cutoff", ["superseded", "close", "cancel", "timeout"])
async def test_viewer_lock_waiter_superseded_report_never_spawns(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    changed_generation: bool,
    monkeypatch: pytest.MonkeyPatch,
    cutoff: str,
) -> None:
    """G2 uses an actual viewer child, transport lock, durable A gap and newer B."""
    import asyncio
    import json
    from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrDisplayTokenDAO
    from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission

    # All mutations are contained regular fixture files; preserve registered inode.
    assert fake_herdr.executable.resolve().parent == tmp_path.resolve()
    assert not fake_herdr.executable.is_symlink()
    script = fake_herdr.executable.read_text()
    script += (
        f"\nif sys.argv[2] == 'split':\n import select\n"
        f" barrier = Path({str(fake_herdr.barrier)!r})\n"
        " while not barrier.read_text(): select.select([], [], [], 0.001)\n"
    )
    fake_herdr.executable.write_text(script)
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    viewer = asyncio.create_task(
        coro=owner._transport.invoke(
            command=HerdrCliCommandDAO(argv=("pane", "split")), admission=RecordingAdmission()
        )
    )
    # Observe actual executable entry, not merely an invoke mock.
    async with asyncio.timeout(0.5):
        while not fake_herdr.capture.read_text():
            await asyncio.sleep(0)
    first = publication()
    owner.publish(publication=first)
    queued = asyncio.Event()
    original = owner._transport.invoke

    async def observed(
        *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Signal after durable reservation, immediately before actual lock wait."""
        queued.set()
        return await original(command=command, admission=admission)

    monkeypatch.setattr(owner._transport, "invoke", observed)
    old = asyncio.create_task(
        coro=owner._send_report_operation(operation="claim", publication=first, revision=1)
    )
    await queued.wait()
    assert owner._reserved_ticket is not None
    reserved = owner._reserved_ticket.sequence
    newer = first.model_copy(
        update={
            "configuration_generation": int(changed_generation),
            "snapshot": first.snapshot.model_copy(
                update={"tokens": (HerdrDisplayTokenDAO(key="turn", value="9"),)}
            ),
        }
    )
    owner.publish(publication=newer)
    if cutoff == "close":
        await owner.close()
    elif cutoff == "cancel":
        old.cancel()
        with pytest.raises(asyncio.CancelledError):
            await old
    elif cutoff == "timeout":
        assert not await old
    assert fake_herdr.barrier.resolve().parent == tmp_path.resolve() and not fake_herdr.barrier.is_symlink()
    fake_herdr.barrier.write_text("release")
    try:
        viewer_result = await viewer
        assert viewer_result.outcome.status in ("ok", "timeout")
        if cutoff != "cancel":
            assert not await old
        if cutoff == "superseded":
            assert await owner._send_report_operation(operation="claim", publication=newer, revision=2)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        expected = ["split", "report-agent"] if cutoff == "superseded" else ["split"]
        assert [item[1] for item in commands] == expected
        if cutoff == "superseded":
            assert int(commands[-1][commands[-1].index("--seq") + 1]) > reserved
        else:
            assert owner._binding is None
            assert owner._lifecycle_ack is None
    finally:
        await owner._transport.close()
        owner._sequence_store.close()


async def test_close_transport_cancel_still_unlocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation of final-close caller cannot strand a drained lease."""
    import asyncio

    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    entered, release = asyncio.Event(), asyncio.Event()
    original = owner._transport.close

    async def delayed() -> HerdrReporterCloseOutcomeDAO:
        """Pause the transport seal for deterministic caller cancellation."""
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(owner._transport, "close", delayed)
    task = asyncio.create_task(coro=owner.close_transport())
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not owner.retains_external_resources


def test_build_disabled_is_inert(tmp_path: Path) -> None:
    """Public builder preserves disabled zero-I/O classification."""
    owner = HerdrReporter.build(environment={"SLO_HERDR_DISABLED": "1"}, state_root=tmp_path)
    assert owner.destination == "platform"
    assert list(tmp_path.iterdir()) == []


async def test_failed_activation_is_unavailable(tmp_path: Path) -> None:
    """Invalid executable cannot acquire active authority or claim safe replacement."""
    owner = reporter(root=tmp_path)
    await owner.start()
    assert owner.destination == "unavailable"
    assert (await owner.close()).replacement == "uncertain"
    assert not owner.retains_external_resources


def test_public_service_export_and_fixed_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Service exposes the sole reporter and isolates fixed diagnostic sink failures."""
    import logging
    from src.agents.slo_agent.herdr.service import HerdrReporter as Exported

    assert Exported is HerdrReporter
    owner = reporter(root=tmp_path)
    owner.record_publication_failure()
    owner.record_publication_failure()
    assert sum(record.message == "herdr_publication_failed" for record in caplog.records) == 1

    def broken(*args: object, **kwargs: object) -> None:
        """Simulate an unavailable diagnostic sink."""
        raise RuntimeError("private")

    monkeypatch.setattr(logging.getLogger("src.agents.slo_agent.herdr.reporter"), "warning", broken)
    owner._log_failure(category="restore_unavailable")


def test_inactive_visualizer_refused(tmp_path: Path) -> None:
    """Inactive reporters never import or construct the later viewer adapter."""
    owner = reporter(root=tmp_path)
    with pytest.raises(Exception, match="Saved Herdr restore"):
        owner.build_visualizer()


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "wrong_token",
        "not_closing",
        "no_deadline",
        "expired",
        "used",
        "wrong_binding",
        "clear_before",
        "clear_after",
    ],
)
async def test_shutdown_admission(tmp_path: Path, case: str) -> None:
    """Cleanup permission requires exact close identity, budget and release evidence."""
    import asyncio
    from src.agents.slo_agent.herdr.dao import HerdrReportTicketDAO, HerdrRemoteBindingDAO

    owner = reporter(root=tmp_path)
    owner._closing = case != "not_closing"
    owner._close_token = 1
    owner._close_deadline = (
        None
        if case == "no_deadline"
        else asyncio.get_running_loop().time() + (-1 if case == "expired" else 2)
    )
    owner._shutdown_admitted = case == "used"
    owner._shutdown_released = case == "clear_after"
    owner._binding = HerdrRemoteBindingDAO(
        configuration_generation=0, session_id=SESSION, capture=None, reference=None, certainty="possible"
    )
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=0,
        sequence=1,
        operation="shutdown_clear" if case.startswith("clear") else "shutdown_release",
        close_token=2 if case == "wrong_token" else 1,
        binding=None if case == "wrong_binding" else owner._binding,
    )
    assert owner._shutdown_allows(ticket=ticket) is (case in ("valid", "clear_after"))


@pytest.mark.parametrize("case", ["retained", "late_drain", "unlock_error"])
async def test_lease_close_order(tmp_path: Path, case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed local drain retains lease; final drain cannot erase uncertainty."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    drained = case == "unlock_error"
    monkeypatch.setattr(HerdrCliTransport, "resources_drained", property(lambda self: drained))

    async def seal() -> HerdrReporterCloseOutcomeDAO:
        """Model transport quarantine while recording actual seal state."""
        owner._transport._closed = True
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain", resources="drained" if drained else "retained"
        )

    monkeypatch.setattr(owner._transport, "close", seal)
    original_close = owner._sequence_store.close
    if case == "unlock_error":

        def fail_close() -> None:
            """Fail before releasing the actual held descriptor."""
            raise OSError("private")

        monkeypatch.setattr(owner._sequence_store, "close", fail_close)
    result = await owner.close_transport()
    assert result.resources == "retained" and owner._lease_held
    if case == "late_drain":
        drained = True
        result = await owner.drain_retained_external_resources()
        assert result.resources == "drained" and result.replacement == "uncertain"
    original_close()
