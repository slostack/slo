"""Shared Herdr schema contracts; no external service or process."""

import pytest
from pydantic import ValidationError
from src.agents.slo_agent.sessions import dao as session_dao


def test_session_attention_contract() -> None:
    """Attention uses one fixed vocabulary and a strict blocked invariant."""
    state = session_dao.SessionReportingStateDAO
    for status in ("idle", "working"):
        assert state(state=status).block_reason is None
        with pytest.raises(ValueError):
            state(state=status, block_reason="Approval required")
    assert state(state="blocked", block_reason="Approval required").state == "blocked"
    with pytest.raises(ValueError):
        state(state="blocked")
    attention = session_dao.OperatorAttentionDAO.model_validate({"token": 1, "reason": "Approval required"})
    with pytest.raises(ValidationError):
        attention.token = 2
    with pytest.raises(ValueError) as caught:
        state.model_validate({"state": "secret-sentinel"})
    assert "secret-sentinel" not in str(caught.value)


def test_provenance_is_private() -> None:
    """Process provenance hides prompts and retains immutable tool membership."""
    provenance = session_dao.HerdrOrchestratorProvenanceDAO.model_validate(
        {"tools": [], "system_prompt": "private-sentinel", "append_system_prompt": None}
    )
    assert provenance.tools == ()
    assert "private-sentinel" not in repr(provenance)


def test_private_restore_is_recursive_and_closed() -> None:
    """Caller mutations cannot change captured private policy."""
    from src.agents.slo_agent.herdr import dao

    entry = dict(
        model_name="gpt-5.4",
        provider="openai",
        priority=0,
        cooldown_seconds=300,
        rate_limit_cooldown_seconds=60,
    )
    entries = [entry, dict(entry, priority=1)]
    pool = dao.HerdrRestorePoolDAO.model_validate({"entries": entries})
    config = dao.HerdrRestoreConfigDAO.model_validate(
        {
            "session_id": "s",
            "model_name": "secret-model",
            "model_pool_dao": pool,
            "reasoning_level": "off",
            "workdir": "/private",
        }
    )
    entry["model_name"] = "changed"
    entries.clear()
    assert pool.entries[0].model_name == "gpt-5.4"
    assert len(pool.entries) == 2
    assert "secret-model" not in repr(config)
    assert "/private" not in repr(config)
    with pytest.raises(ValueError):
        dao.HerdrRestorePoolDAO.model_validate({"entries": []})
    with pytest.raises(ValueError):
        pool.entries[0].priority = 3
    capture = dao.HerdrRestoreCaptureDAO.model_validate({"config": config})
    assert "secret-model" not in repr(capture)


def test_publication_and_reference() -> None:
    """Strict generations and exact capture identity guard the handoff."""
    from src.agents.slo_agent.herdr import dao

    snapshot = dao.HerdrReportSnapshotDAO.model_validate({"session_id": "s", "state": "idle", "tokens": ()})
    for invalid in (True, -1, "1"):
        with pytest.raises(ValueError):
            dao.HerdrPublicationDAO.model_validate(
                {"configuration_generation": invalid, "snapshot": snapshot}
            )
    assert (
        dao.HerdrPublicationDAO.model_validate(
            {"configuration_generation": 0, "snapshot": snapshot}
        ).restore_capture
        is None
    )
    config = dao.HerdrRestoreConfigDAO.model_validate(
        {"session_id": "other", "model_name": "gpt-5.4", "reasoning_level": "off", "workdir": "/tmp"}
    )
    with pytest.raises(ValueError):
        dao.HerdrPublicationDAO(
            configuration_generation=0,
            snapshot=snapshot,
            restore_capture=dao.HerdrRestoreCaptureDAO.model_validate({"config": config}),
        )
    reference = "r1-" + "a" * 32
    assert (
        dao.HerdrRestoreReferenceDAO.model_validate({"restore_reference": reference}).restore_reference
        == reference
    )
    for invalid in (reference.upper(), reference + "\n", "../secret"):
        with pytest.raises(ValueError):
            dao.HerdrRestoreReferenceDAO.model_validate({"restore_reference": invalid})
    record = dao.HerdrRestoreRecordDAO.model_validate(
        {"schema_version": 1, "restore_reference": reference, "config": config}
    )
    assert "gpt-5.4" not in repr(record)


@pytest.mark.parametrize(
    "status", ["ok", "unavailable", "timeout", "rejected", "malformed", "cancelled", "suppressed"]
)
def test_transport_results(status: str) -> None:
    """Raw bytes survive only successful private results."""
    from src.agents.slo_agent.herdr import dao

    outcome = dao.HerdrCommandOutcomeDAO.model_validate({"status": status})
    assert dao.HerdrCommandResultDAO.model_validate({"outcome": outcome}).json_bytes is None
    if status == "ok":
        result = dao.HerdrCommandResultDAO.model_validate({"outcome": outcome, "json_bytes": b"secret"})
        assert "secret" not in repr(result)
    else:
        with pytest.raises(ValueError):
            dao.HerdrCommandResultDAO.model_validate({"outcome": outcome, "json_bytes": b"secret"})
    for admitted in (True, False):
        if status == "unavailable" and admitted:
            assert dao.HerdrCommandResultDAO.model_validate(
                {"outcome": outcome, "admitted": True, "spawn_failed": True}
            ).spawn_failed
        else:
            with pytest.raises(ValueError):
                dao.HerdrCommandResultDAO.model_validate(
                    {"outcome": outcome, "admitted": admitted, "spawn_failed": True}
                )


def test_close_resources_are_independent() -> None:
    """Retained local resources always prohibit safe replacement."""
    from src.agents.slo_agent.herdr import dao

    for replacement in ("safe", "uncertain"):
        assert (
            dao.HerdrReporterCloseOutcomeDAO.model_validate({"replacement": replacement}).resources
            == "drained"
        )
    assert dao.HerdrReporterCloseOutcomeDAO.model_validate(
        {"replacement": "uncertain", "resources": "retained"}
    )
    with pytest.raises(ValueError):
        dao.HerdrReporterCloseOutcomeDAO.model_validate({"replacement": "safe", "resources": "retained"})


@pytest.mark.parametrize(
    "operation",
    [
        "claim",
        "lifecycle",
        "restore",
        "clear",
        "set",
        "replace_release",
        "shutdown_release",
        "shutdown_clear",
        "activation_release",
    ],
)
def test_final_ticket_contract(operation: str) -> None:
    """Every operation has one immutable authority shape."""
    from src.agents.slo_agent.herdr import dao

    publication = dao.HerdrPublicationDAO(
        configuration_generation=0,
        snapshot=dao.HerdrReportSnapshotDAO.model_validate(
            {"session_id": "s", "state": "idle", "tokens": ()}
        ),
    )
    ordinary = operation not in ("shutdown_release", "shutdown_clear", "activation_release")
    args = dict(configuration_generation=0, report_revision=1, operation=operation, sequence=1)
    ticket = dao.HerdrReportTicketDAO.model_validate(
        {**args, "publication": publication if ordinary else None}
    )
    assert ticket.operation == operation
    with pytest.raises(ValueError):
        dao.HerdrReportTicketDAO.model_validate({**args, "publication": None if ordinary else publication})
    if operation not in ("clear", "set"):
        with pytest.raises(ValueError):
            dao.HerdrReportTicketDAO.model_validate(
                {**args, "publication": ticket.publication, "display_final": True}
            )
    else:
        assert dao.HerdrReportTicketDAO.model_validate(
            {**args, "publication": publication, "display_final": True}
        ).display_final


def test_lifecycle_acknowledgement() -> None:
    """Acknowledgement shares the session state/reason invariant."""
    from src.agents.slo_agent.herdr import dao

    assert dao.HerdrLifecycleAcknowledgementDAO.model_validate(
        {"configuration_generation": 0, "session_id": "s", "state": "idle"}
    )
    with pytest.raises(ValueError):
        dao.HerdrLifecycleAcknowledgementDAO.model_validate(
            {"configuration_generation": 0, "session_id": "s", "state": "blocked"}
        )


def test_viewer_schemas() -> None:
    """Known panes require identity; uncertain attempts retain only admission ledger."""
    from src.agents.slo_agent.herdr import dao

    assert (
        dao.HerdrVisualizerRequestDAO.model_validate(
            {"parent_session_id": "s", "history_root": "/tmp"}
        ).history_root.name
        == "tmp"
    )
    for status in ("opened", "submitted", "reused", "skipped", "failed"):
        assert dao.VisualizerLaunchOutcomeDAO.model_validate({"status": status}).pane_id is None
    for state in ("split_attempted", "uncertain", "pane_known"):
        pane = "p1" if state == "pane_known" else None
        attempt = dao.HerdrVisualizerAttemptDAO.model_validate(
            {"state": state, "pane_id": pane, "admitted_operations": ["split"]}
        )
        assert attempt.admitted_operations == frozenset({"split"})
        with pytest.raises(ValueError):
            dao.HerdrVisualizerAttemptDAO.model_validate({"state": state, "pane_id": None if pane else "p1"})


def test_config_sequence_and_command() -> None:
    """Construction is inert; filesystem eligibility belongs to activation."""
    from src.agents.slo_agent.herdr import dao

    config = dao.HerdrReporterConfigDAO.model_validate(
        {
            "pane_id": "p1",
            "binary_path": "/not-probed/herdr",
            "state_root": "/private",
            "metadata_profile": "compact",
        }
    )
    assert config.command_timeout_seconds == 1.0
    with pytest.raises(ValueError):
        dao.HerdrReporterConfigDAO.model_validate(
            {
                "pane_id": "",
                "binary_path": "relative",
                "state_root": "/private",
                "metadata_profile": "compact",
            }
        )
    for invalid in (True, -1, "1"):
        with pytest.raises(ValueError):
            dao.HerdrSequenceStateDAO.model_validate(
                {"schema_version": 1, "lifecycle_sequence": invalid, "display_sequence": 0}
            )
    assert dao.HerdrSequenceStateDAO.model_validate(
        {"schema_version": 1, "lifecycle_sequence": 0, "display_sequence": 0}
    )
    assert dao.HerdrCliCommandDAO.model_validate({"argv": ["pane", "run", "p1", "secret"]}).argv[0] == "pane"
    assert "secret" not in repr(dao.HerdrCliCommandDAO.model_validate({"argv": ["pane", "run", "secret"]}))
    for argv in ([], ["/bin/sh"], ["pane", "unknown"], ["pane", "run", "\x00"]):
        with pytest.raises(ValueError):
            dao.HerdrCliCommandDAO.model_validate({"argv": argv})


def test_protocols_and_fixed_restore_error() -> None:
    """Consumers share narrow interfaces and a single fixed error owner."""
    from src.agents.slo_agent.herdr import dao

    assert hasattr(dao.HerdrRestoreStoreProtocol, "save")
    assert not hasattr(dao.HerdrRestoreStoreProtocol, "load")
    assert hasattr(dao.HerdrCommandAdmission, "try_admit")
    assert hasattr(dao.HerdrCommandAdmission, "complete")
    for name in (
        "start",
        "publish",
        "close",
        "close_transport",
        "build_visualizer",
        "destination",
        "allows_viewer_admission",
        "retains_external_resources",
        "drain_retained_external_resources",
    ):
        assert hasattr(dao.HerdrReporterProtocol, name)
    assert str(dao.HerdrRestoreUnavailableError()) == dao.RESTORE_UNAVAILABLE_MESSAGE


def test_private_validation_never_exposes_input() -> None:
    """Even structured errors and formatted tracebacks omit private sentinels."""
    import traceback
    from src.agents.slo_agent.herdr import dao

    for model, payload in (
        (dao.HerdrRestoreConfigDAO, dict(secret="private-sentinel")),
        (dao.HerdrRestorePoolDAO, dict(entries=["private-sentinel"])),
        (dao.HerdrRestoreRecordDAO, dict(config="private-sentinel")),
        (dao.HerdrCliCommandDAO, dict(argv=["private-sentinel"])),
    ):
        with pytest.raises(Exception) as caught:
            model.model_validate(payload)
        error = caught.value
        rendered = str(error) + repr(error) + "".join(traceback.format_exception(error))
        if isinstance(error, ValidationError):
            rendered += str(error.errors())
        assert "private-sentinel" not in rendered


def test_version_and_provenance_input_privacy() -> None:
    """Version literals reject bool and provenance errors contain no prompts."""
    from src.agents.slo_agent.herdr import dao

    with pytest.raises(ValueError):
        dao.HerdrSequenceStateDAO.model_validate(
            {"schema_version": True, "lifecycle_sequence": 0, "display_sequence": 0}
        )
    with pytest.raises(ValueError) as caught:
        session_dao.HerdrOrchestratorProvenanceDAO.model_validate(
            {"tools": ["private-sentinel"], "system_prompt": None, "append_system_prompt": None}
        )
    if isinstance(caught.value, ValidationError):
        assert "private-sentinel" not in str(caught.value.errors())


def test_all_schema_fields_documented_and_nested_private_carriers() -> None:
    """Shared carriers remain frozen, closed, documented and privately represented."""
    from src.agents.slo_agent.herdr import dao
    from pydantic import BaseModel

    for name, model in vars(dao).items():
        if not name.endswith("DAO") or not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        assert model.model_config["frozen"]
        assert model.model_config["extra"] == "forbid"
        assert all(field.description for field in model.model_fields.values())
    config = dao.HerdrRestoreConfigDAO.model_validate(
        {
            "session_id": "s",
            "model_name": "private-sentinel",
            "reasoning_level": "off",
            "workdir": "/private-sentinel",
        }
    )
    capture = dao.HerdrRestoreCaptureDAO.model_validate({"config": config})
    reference = dao.HerdrRestoreReferenceDAO.model_validate({"restore_reference": "r1-" + "a" * 32})
    saved = dao.HerdrSavedRestoreDAO.model_validate(
        {"configuration_generation": 0, "capture": capture, "reference": reference}
    )
    binding = dao.HerdrRemoteBindingDAO.model_validate(
        {
            "configuration_generation": 0,
            "session_id": "s",
            "capture": capture,
            "reference": reference,
            "certainty": "possible",
        }
    )
    for carrier in (saved, binding):
        assert "private-sentinel" not in repr(carrier)
        with pytest.raises(ValueError):
            carrier.configuration_generation = 2
    with pytest.raises(ValueError):
        dao.HerdrCommandResultDAO(
            outcome=dao.HerdrCommandOutcomeDAO.model_validate({"status": "ok"}), json_bytes=b"x" * 16385
        )


def test_release_command_is_in_final_inventory() -> None:
    """Activation/replacement/shutdown release uses the same transport schema."""
    from src.agents.slo_agent.herdr import dao

    command = dao.HerdrCliCommandDAO(
        argv=("pane", "release-agent", "p1", "--source", "custom:slo", "--agent", "slo", "--seq", "1")
    )
    assert command.argv[1] == "release-agent"
