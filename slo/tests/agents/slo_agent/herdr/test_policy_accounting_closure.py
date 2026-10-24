"""Finite B7.11 policy/accounting gaps; existing result/currentness matrices stay authoritative."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.herdr.dao import (
    HerdrRemoteBindingDAO,
    HerdrLifecycleAcknowledgementDAO,
    HerdrDisplayTokenDAO,
    HerdrCliCommandDAO,
    HerdrReportOperation,
    HerdrReportTicketDAO,
    HerdrSavedRestoreDAO,
    HerdrRestoreReferenceDAO,
)
from src.agents.slo_agent.herdr.reporter import HerdrReporterAdmission
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.state_isolation import FakeHerdrFixture
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


def saved_restore() -> HerdrSavedRestoreDAO:
    """Build exact synthetic policy for pure admission and accounting tests."""
    facts = publication(eligible=True)
    assert facts.restore_capture is not None
    return HerdrSavedRestoreDAO(
        configuration_generation=0,
        capture=facts.restore_capture,
        reference=HerdrRestoreReferenceDAO(restore_reference="r1-" + "0" * 32),
    )


def remote_binding() -> HerdrRemoteBindingDAO:
    """Build confirmed identity with a separately unacknowledged possible reference."""
    saved = saved_restore()
    return HerdrRemoteBindingDAO(
        configuration_generation=0,
        session_id=saved.capture.config.session_id,
        capture=saved.capture,
        reference=saved.reference,
        certainty="confirmed",
    )


@pytest.mark.parametrize("operation", ["claim", "lifecycle", "restore", "clear", "set", "replace_release"])
@pytest.mark.parametrize(
    "case", ["capture", "session", "generation", "withdrawal", "wrong_release", "missing_publication"]
)
def test_binding_conflict_policy(tmp_path: Path, operation: HerdrReportOperation, case: str) -> None:
    """Conflicting exact policy permits only matching withdrawal, never replacement display."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    binding = remote_binding()
    if case == "capture":
        assert binding.capture is not None
        binding = binding.model_copy(
            update={
                "capture": binding.capture.model_copy(
                    update={"config": binding.capture.config.model_copy(update={"reasoning_level": "high"})}
                )
            }
        )
    elif case == "session":
        binding = binding.model_copy(update={"session_id": "00000000-0000-4000-8000-000000000002"})
    elif case == "generation":
        binding = binding.model_copy(update={"configuration_generation": 1})
    owner._binding = binding
    owner._saved = saved_restore()
    owner._withdrawal_pending = case in ("withdrawal", "wrong_release")
    if case == "missing_publication":
        with pytest.raises(ValidationError, match="Invalid ticket publication"):
            HerdrReportTicketDAO(
                configuration_generation=0, report_revision=1, sequence=1, operation=operation
            )
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation=operation,
        publication=facts,
        saved=owner._saved,
        binding=binding.model_copy(update={"reference": None}) if case == "wrong_release" else binding,
    )
    if case == "missing_publication":
        # Defensive helper path is unreachable through validated ordinary tickets.
        ticket = ticket.model_copy(update={"publication": None})
    assert owner._needs_release(publication=facts) == (case != "missing_publication")
    assert owner._binding_allows(ticket=ticket) == (
        operation == "replace_release" and case not in ("wrong_release", "missing_publication")
    )
    assert owner._binding is binding and owner._admitted_ticket is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["lifecycle", "clear", "set", "restore"])
@pytest.mark.parametrize("certainty", ["absent", "possible", "confirmed"])
def test_confirmed_policy(tmp_path: Path, operation: HerdrReportOperation, certainty: str) -> None:
    """Lifecycle, display and restore require confirmed same-capture identity."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._saved = saved_restore()
    owner._binding = (
        None if certainty == "absent" else remote_binding().model_copy(update={"certainty": certainty})
    )
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation=operation,
        publication=facts,
        saved=owner._saved,
    )
    assert owner._binding_allows(ticket=ticket) == (certainty == "confirmed")


@pytest.mark.parametrize(
    "case",
    [
        "no_ticket_save",
        "no_owner_save",
        "reference",
        "capture",
        "generation",
        "matching_wrong_capture",
        "matching_wrong_generation",
    ],
)
def test_restore_association_policy(tmp_path: Path, case: str) -> None:
    """Matching session ID cannot substitute for exact generation, capture and reference."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._binding = remote_binding()
    saved = saved_restore()
    owner._saved = saved
    if case == "reference":
        saved = saved.model_copy(
            update={"reference": HerdrRestoreReferenceDAO(restore_reference="r1-" + "1" * 32)}
        )
    elif "capture" in case:
        saved = saved.model_copy(
            update={
                "capture": saved.capture.model_copy(
                    update={"config": saved.capture.config.model_copy(update={"reasoning_level": "high"})}
                )
            }
        )
    elif "generation" in case:
        saved = saved.model_copy(update={"configuration_generation": 1})
    if case.startswith("matching_wrong"):
        owner._saved = saved
    if case == "no_owner_save":
        owner._saved = None
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation="restore",
        publication=facts,
        saved=None if case == "no_ticket_save" else saved,
    )
    assert not owner._binding_allows(ticket=ticket)
    assert owner._restore_ack is None


@pytest.mark.parametrize("operation", ["replace_release", "shutdown_release"])
@pytest.mark.parametrize("case", ["nonmatching", "stale_revision", "stale_generation"])
def test_release_accounting(tmp_path: Path, operation: HerdrReportOperation, case: str) -> None:
    """Only the exact released binding clears seeded acknowledgements, even when stale."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    binding = remote_binding()
    owner._binding = binding
    owner._withdrawal_pending = True
    lifecycle = HerdrLifecycleAcknowledgementDAO(
        configuration_generation=0, session_id=facts.snapshot.session_id, state="idle"
    )
    saved = saved_restore()
    owner._lifecycle_ack, owner._restore_ack, owner._display_ack_revision = lifecycle, saved, 1
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation=operation,
        publication=facts if operation == "replace_release" else None,
        binding=binding,
        close_token=1 if operation == "shutdown_release" else None,
    )
    owner._admitted_ticket = ticket
    owner._mark_admitted(ticket=ticket)
    if case == "nonmatching":
        owner._binding = binding.model_copy(update={"reference": None})
    elif case == "stale_revision":
        owner._revision += 1
    else:
        owner.publish(publication=publication(generation=1, eligible=True))
    retained = owner._binding
    owner._record_command_result(ticket=ticket, result=HerdrCliTransport._failure(status="ok", admitted=True))
    matching = case != "nonmatching"
    assert owner._binding == (None if matching else retained)
    assert owner._withdrawal_pending == (not matching)
    assert owner._lifecycle_ack == (None if matching else lifecycle)
    assert owner._restore_ack == (None if matching else saved)
    assert owner._display_ack_revision == (None if matching else 1)
    assert owner._shutdown_released == (matching and operation == "shutdown_release")
    assert owner._admitted_ticket is None and owner._before_admission_binding is None


@pytest.mark.parametrize("operation", ["clear", "set"])
@pytest.mark.parametrize("final", [False, True], ids=["partial", "final"])
@pytest.mark.parametrize("cutoff", ["current", "revision", "generation", "closing"])
async def test_display_acknowledgement(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: HerdrReportOperation,
    final: bool,
    cutoff: str,
) -> None:
    """Real admitted patches credit only current final success, not obsolete completions."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve(strict=True) == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._binding = remote_binding()
    # Completion barrier follows real process creation and admission; no fabricated result.
    entered, release = asyncio.Event(), asyncio.Event()
    original_spawn = owner._transport._spawn

    async def held_spawn(*, command: HerdrCliCommandDAO) -> asyncio.subprocess.Process:
        """Return the guarded real child only after the publication cutoff."""
        process = await original_spawn(command=command)
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr(target=owner._transport, name="_spawn", value=held_spawn)
    task = asyncio.create_task(
        coro=owner._send_report_operation(
            operation=operation,
            publication=facts,
            revision=1,
            display_final=final,
            keys=("turn",) if operation == "clear" else (),
            tokens=(HerdrDisplayTokenDAO(key="turn", value="1"),) if operation == "set" else (),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert owner._admitted_ticket is not None
        if cutoff == "revision":
            owner._revision += 1
        elif cutoff == "generation":
            owner.publish(publication=publication(generation=1, eligible=True))
        elif cutoff == "closing":
            owner.revoke_viewer_admission()
            owner._closing = True
        release.set()
        assert await task == (cutoff == "current")
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert len(commands) == 1 and commands[0][1] == "report-metadata"
        assert commands[0][-4:] == ["--ttl-ms", "5000", "--seq", "1"]
        assert owner._display_ack_revision == (1 if final and cutoff == "current" else None)
        assert owner._binding == remote_binding()
        assert owner._lifecycle_ack is None and owner._restore_ack is None
        assert owner._admitted_ticket is None
    finally:
        release.set()
        await task
        await owner.close_transport()


@pytest.mark.parametrize("case", ["claim_without_prior", "claim_with_prior", "restore_with_prior"])
@pytest.mark.parametrize("stale", [False, True])
async def test_definitive_spawn_failure(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    stale: bool,
) -> None:
    """Actual transport spawn-task failure restores exact pre-admission knowledge."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve(strict=True) == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    prior = None if case == "claim_without_prior" else remote_binding()
    owner._binding = prior
    owner._saved = saved_restore()
    owner._resume_available = True
    operation: HerdrReportOperation = "restore" if case == "restore_with_prior" else "claim"
    ticket = await owner._reserve_ticket(
        operation=operation, publication=facts, revision=1, saved=owner._saved
    )
    assert ticket is not None
    original_reference = owner._saved.reference
    observed_bindings: list[HerdrRemoteBindingDAO] = []
    reached_refusal: list[bool] = []

    async def refuse_spawn(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        """Fail process creation after the fixture guard and reporter admission."""
        assert owner._admitted_ticket is ticket
        assert owner._binding is not None and owner._binding.reference == (
            original_reference if prior else None
        )
        observed_bindings.append(owner._binding)
        if stale:
            owner.publish(publication=publication(generation=1, eligible=True))
        reached_refusal.append(True)
        raise OSError("synthetic-spawn-failure")

    monkeypatch.setattr(target=asyncio, name="create_subprocess_exec", value=refuse_spawn)
    try:
        result = await owner._transport.invoke(
            command=owner._command_for_ticket(ticket=ticket),
            admission=HerdrReporterAdmission(reporter=owner, ticket=ticket),
        )
        assert reached_refusal == [True] and len(observed_bindings) == 1
        assert observed_bindings[0].certainty == ("confirmed" if operation == "restore" else "possible")
        assert result.admitted and result.spawn_failed and result.outcome.status == "unavailable"
        assert result.json_bytes is None
        assert owner._binding is prior
        assert owner._lifecycle_ack is None and owner._restore_ack is None
        assert owner._display_ack_revision is None
        assert owner._admitted_ticket is None and owner._before_admission_binding is None
        assert owner._transport.resources_drained and not owner._transport._command_lock.locked()
        assert fake_herdr.capture.read_text() == ""
    finally:
        await owner.close_transport()


async def test_claim_after_uncertain_install(tmp_path: Path, fake_herdr: FakeHerdrFixture) -> None:
    """A real rejected install then successful identity-only claim retains its possible reference."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    fake_herdr.executable.write_text(script + "\nif '--herdr-restore' in sys.argv: sys.exit(9)\n")
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve(strict=True) == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._saved = saved_restore()
    owner._resume_available = True
    try:
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert not await owner._send_report_operation(
            operation="restore", publication=facts, revision=1, saved=owner._saved
        )
        assert owner._binding == remote_binding()
        assert owner._restore_ack is None and owner._lifecycle_ack is None
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert owner._binding == remote_binding()
        assert owner._restore_ack is None and owner._lifecycle_ack is not None
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert [command[1] for command in commands] == ["report-agent"] * 3
        assert [command[command.index("--seq") + 1] for command in commands] == ["1", "2", "3"]
        assert ["--herdr-restore" in command for command in commands] == [False, True, False]
        assert commands[1][-6:] == [
            "--",
            "slo",
            "--resume",
            facts.snapshot.session_id,
            "--herdr-restore",
            owner._saved.reference.restore_reference,
        ]
        assert "--" not in commands[2]
        assert owner._admitted_ticket is None and owner._before_admission_binding is None
    finally:
        await owner.close_transport()


@pytest.mark.parametrize("present", [False, True], ids=["none", "same"])
@pytest.mark.parametrize("operation", ["claim", "replace_release"])
def test_nonconflicting_claim_release_policy(
    tmp_path: Path, present: bool, operation: HerdrReportOperation
) -> None:
    """Same policy permits identity confirmation but never unnecessary withdrawal."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._binding = remote_binding() if present else None
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation=operation,
        publication=facts,
        binding=owner._binding,
    )
    assert not owner._needs_release(publication=facts)
    assert owner._binding_allows(ticket=ticket) == (operation == "claim")


@pytest.mark.parametrize("case", ["suppressed", "not_admitted", "wrong_ticket"])
def test_unowned_result_cannot_account(tmp_path: Path, case: str) -> None:
    """Unowned completion cannot consume another ticket or change binding/acknowledgements."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._binding = remote_binding()
    ticket = HerdrReportTicketDAO(
        configuration_generation=0,
        report_revision=1,
        sequence=1,
        operation="claim",
        publication=facts,
    )
    owner._admitted_ticket = ticket
    owner._mark_admitted(ticket=ticket)
    binding, prior = owner._binding, owner._before_admission_binding
    owner._record_command_result(
        ticket=ticket.model_copy() if case == "wrong_ticket" else ticket,
        result=HerdrCliTransport._failure(
            status="suppressed" if case == "suppressed" else "ok",
            admitted=case == "wrong_ticket",
        ),
    )
    assert owner._admitted_ticket is ticket and owner._before_admission_binding is prior
    assert owner._binding is binding
    assert owner._lifecycle_ack is None and owner._restore_ack is None
    assert owner._display_ack_revision is None and owner._diagnostic_failures == set()
