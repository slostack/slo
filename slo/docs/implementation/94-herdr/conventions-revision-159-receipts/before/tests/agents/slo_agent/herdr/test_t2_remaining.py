"""Explicit remaining T2 branch evidence; no runtime assembly."""

import asyncio
from pathlib import Path
from typing import Optional

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrSavedRestoreDAO,
    HerdrReportOperation,
    HerdrRestoreConfigDAO,
    HerdrRestoreReferenceDAO,
    HerdrRestoreCaptureDAO,
)
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


async def test_save_success_does_not_recover_failed_install(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Saving private policy cannot establish PATH or remote install recovery."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._log_failure(category="restore_unavailable")
    await owner._ensure_saved_restore(publication=facts)
    assert owner._saved is not None
    assert [record.message for record in caplog.records] == ["herdr_restore_unavailable"]


@pytest.mark.parametrize("case", ["absent", "success", "store_error", "cancel"])
async def test_save_join_remaining(tmp_path: Path, case: str) -> None:
    """Each terminal path clears the slot and retrieves owned exceptions."""
    owner = reporter(root=tmp_path)
    release = asyncio.Event()

    async def save() -> HerdrSavedRestoreDAO:
        """Keep the save owned while a single caller cancellation arrives."""
        await release.wait()
        if case == "store_error":
            raise OSError("private-save-sentinel")
        return await owner._save_capture(publication=publication(eligible=True))

    owned = None if case == "absent" else asyncio.create_task(coro=save())
    owner._save_task = owned
    waiter = asyncio.create_task(coro=owner._join_save())
    await asyncio.sleep(0)
    if case == "cancel":
        waiter.cancel()
        await asyncio.sleep(0)
        assert not waiter.done() and owned is not None and not owned.cancelled()
    release.set()
    if case == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await waiter
    else:
        result = await waiter
        assert (result is not None) == (case == "success")
    assert owner._save_task is None
    assert owned is None or (owned.done() and not owned._log_traceback)


@pytest.mark.parametrize(
    "case", ["current", "usage_changed", "config_changed", "ineligible", "closed", "disabled"]
)
async def test_save_adoption_remaining(tmp_path: Path, case: str) -> None:
    """Exact capture adoption never grants stale or revoked policy permission."""
    from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO

    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    saved = await owner._save_capture(publication=facts)
    if case == "usage_changed":
        owner.publish(
            publication=facts.model_copy(
                update={
                    "snapshot": facts.snapshot.model_copy(
                        update={"tokens": (HerdrDisplayTokenDAO(key="turn", value="42"),)}
                    )
                }
            )
        )
    elif case in ("config_changed", "ineligible"):
        owner.publish(publication=publication(generation=1, eligible=case != "ineligible"))
    elif case == "closed":
        await owner.close()
    elif case == "disabled":
        owner._disabled = True
    owner._take_pending()
    owner._adopt_save(saved=saved)
    accepted = case in ("current", "usage_changed")
    assert (owner._saved == saved) == accepted
    assert (owner._pending is owner._latest) == accepted
    assert owner._wake.is_set() == accepted


async def test_session_mismatch_publication_has_fixed_failure(tmp_path: Path) -> None:
    """Same-generation identity change is memory-only refusal without private repr."""
    owner = reporter(root=tmp_path)
    first = publication()
    owner.publish(publication=first)
    changed = first.model_copy(
        update={
            "snapshot": first.snapshot.model_copy(
                update={"session_id": "00000000-0000-4000-8000-000000000002"}
            )
        }
    )
    with pytest.raises(ValueError) as caught:
        owner.publish(publication=changed)
    assert str(caught.value) == "publication_invalid"
    assert owner._revision == 1 and owner._pending is first
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "case",
    [
        "capture_replaced",
        "executable_replaced",
        "missing",
        "directory",
        "symlink",
        "parent_link",
        "traversal",
        "outside",
        "unregistered",
        "nonexecutable",
        "hardlink",
    ],
)
async def test_actual_spawn_substitution_refused(fake_herdr, tmp_path: Path, case: str) -> None:
    """The installed spawn guard refuses substitutions before real process creation."""
    import os
    from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO

    owner = reporter(root=tmp_path)
    target = fake_herdr.capture if case == "capture_replaced" else fake_herdr.executable
    assert target.resolve().parent == tmp_path.resolve() and not target.is_symlink()
    candidate = fake_herdr.executable
    if case in ("capture_replaced", "executable_replaced", "outside", "unregistered", "symlink"):
        replacement = tmp_path / "replacement"
        assert replacement.resolve().parent == tmp_path.resolve() and not replacement.exists()
        replacement.write_text("#!/bin/sh\nexit 99\n")
        replacement.chmod(0o700)
        if case in ("capture_replaced", "executable_replaced"):
            replacement.replace(target)
        elif case == "symlink":
            target.unlink()
            target.symlink_to(replacement)
        else:
            candidate = replacement if case == "unregistered" else tmp_path.parent / "never-execute"
    elif case in ("missing", "directory"):
        target.unlink()
        if case == "directory":
            target.mkdir()
    elif case == "nonexecutable":
        target.chmod(0o600)
    elif case == "hardlink":
        os.link(src=target, dst=tmp_path / "alias")
    elif case == "parent_link":
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        candidate = link / target.name
    else:
        candidate = tmp_path / ".." / tmp_path.name / target.name
    owner._transport._config = owner._config.model_copy(update={"binary_path": candidate})
    with pytest.raises((AssertionError, FileNotFoundError)):
        await owner._transport._spawn(command=HerdrCliCommandDAO(argv=("pane", "split")))
    assert owner._transport.resources_drained
    if case != "capture_replaced":
        assert fake_herdr.capture.read_text() == ""


@pytest.mark.parametrize("operation", ["claim", "lifecycle", "restore", "clear", "set", "replace_release"])
@pytest.mark.parametrize(
    "cutoff",
    ["current", "revision_changed", "generation_changed", "closing", "disabled", "no_latest", "revoked"],
)
async def test_ordinary_operation_currentness(
    fake_herdr, tmp_path: Path, operation: HerdrReportOperation, cutoff: str
) -> None:
    """Every ordinary ticket crosses real lock admission; stale work never spawns."""
    from src.agents.slo_agent.herdr.dao import HerdrRemoteBindingDAO

    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    owner._saved = await owner._save_capture(publication=facts)
    owner._resume_available = True
    owner._binding = HerdrRemoteBindingDAO(
        configuration_generation=0,
        session_id=facts.snapshot.session_id,
        capture=facts.restore_capture,
        reference=None,
        certainty="confirmed",
    )
    owner._withdrawal_pending = operation == "replace_release"
    ticket = await owner._reserve_ticket(
        operation=operation, publication=facts, revision=1, saved=owner._saved, binding=owner._binding
    )
    assert ticket is not None
    from src.agents.slo_agent.herdr.reporter import HerdrReporterAdmission
    from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO

    command = owner._command_for_ticket(
        ticket=ticket,
        keys=("turn",) if operation == "clear" else (),
        tokens=(HerdrDisplayTokenDAO(key="turn", value="1"),) if operation == "set" else (),
    )
    if cutoff == "revision_changed":
        owner._revision += 1
    elif cutoff == "generation_changed":
        owner._latest = publication(generation=1, eligible=True)
    elif cutoff == "no_latest":
        owner._latest = None
    elif cutoff == "revoked":
        owner.revoke_viewer_admission()
    elif cutoff in ("closing", "disabled"):
        setattr(owner, "_" + cutoff, True)
    try:
        result = await owner._transport.invoke(
            command=command, admission=HerdrReporterAdmission(reporter=owner, ticket=ticket)
        )
        assert result.admitted == (cutoff == "current")
        assert result.outcome.status == ("ok" if cutoff == "current" else "suppressed")
        assert bool(fake_herdr.capture.read_text()) == (cutoff == "current")
        assert owner._admitted_ticket is None
    finally:
        await owner.close_transport()


async def test_close_reports_retained_lease_before_transport_drain(tmp_path: Path) -> None:
    """Reporter withdrawal alone cannot claim local resources have been drained."""
    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    try:
        outcome = await owner.close()
        assert outcome.resources == "retained"
        assert owner.retains_external_resources
        assert (await owner.close_transport()).resources == "drained"
    finally:
        owner._sequence_store.close()


@pytest.mark.parametrize(
    "case", ["pool", "eligibility", "session", "generation", "name", "closed", "disabled"]
)
async def test_changed_capture_save_barrier(
    fake_herdr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """An owned off-loop save cannot publish old policy after a boundary change."""
    import threading
    from src.agents.slo_agent.herdr.dao import HerdrRestorePoolDAO, HerdrRestorePoolEntryDAO
    from src.auth.credential_dao import ProviderName
    from tests.agents.slo_agent.herdr.test_reporter import Store

    entered, release = threading.Event(), threading.Event()

    class BarrierStore(Store):
        def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
            """Hold the finite write until the replacement has been published."""
            entered.set()
            assert release.wait(timeout=5)
            return super().save(config=config)

    owner = reporter(root=tmp_path)
    store = BarrierStore()
    owner._restore_store = store
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    monkeypatch.setattr(owner, "_plain_slo_available", lambda: False)
    first = publication(eligible=True)
    owner.publish(publication=first)
    task = asyncio.create_task(coro=owner._consume_publication(publication=first))
    try:
        assert await asyncio.to_thread(entered.wait, timeout=5)
        assert first.restore_capture is not None
        capture: Optional[HerdrRestoreCaptureDAO] = first.restore_capture
        snapshot = first.snapshot
        if case == "pool":
            assert capture is not None
            pool = HerdrRestorePoolDAO(
                entries=tuple(
                    HerdrRestorePoolEntryDAO(
                        model_name=name,
                        provider=ProviderName.OPENAI,
                        priority=index,
                        cooldown_seconds=300,
                        rate_limit_cooldown_seconds=60,
                    )
                    for index, name in enumerate(("gpt-5.4", "gpt-5"))
                )
            )
            capture = capture.model_copy(
                update={"config": capture.config.model_copy(update={"model_pool_dao": pool})}
            )
        elif case == "session":
            assert capture is not None
            identity = "00000000-0000-4000-8000-000000000002"
            capture = capture.model_copy(
                update={"config": capture.config.model_copy(update={"session_id": identity})}
            )
            snapshot = snapshot.model_copy(update={"session_id": identity})
        elif case == "eligibility":
            capture = None
        if case in ("closed", "disabled"):
            setattr(owner, "_closing" if case == "closed" else "_disabled", True)
        else:
            owner.publish(
                publication=first.model_copy(
                    update={
                        "configuration_generation": 0 if case == "name" else 1,
                        "restore_capture": capture,
                        "snapshot": snapshot,
                    }
                )
            )
        release.set()
        await task
        assert len(store.calls) == 1 and owner._save_task is None
        assert (owner._saved is not None) == (case == "name")
        assert fake_herdr.capture.read_text() == ""
        assert owner._restore_ack is None
    finally:
        release.set()
        await task
        await owner.close_transport()
