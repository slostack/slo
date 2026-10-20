"""Offline CLI admission contracts for exact private Herdr revisions."""

import asyncio
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.agents.slo_agent.herdr.dao import (
    HerdrRestoreConfigDAO,
    HerdrRestorePoolDAO,
    HerdrRestorePoolEntryDAO,
    RESTORE_UNAVAILABLE_MESSAGE,
)
from src.auth.credential_dao import ProviderName
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.cli.app import app
from src.cli.typer_dispatch import TyperDispatch

import src.cli.typer_dispatch as dispatch_module

SESSION_ID = "12345678-1234-1234-1234-123456789abc"
REFERENCE = "r1-" + "a" * 32


@pytest.mark.parametrize(
    "resume",
    [
        None,
        "",
        "named-session",
        SESSION_ID.upper(),
        "{" + SESSION_ID + "}",
        SESSION_ID.replace("-", ""),
        " " + SESSION_ID,
    ],
)
def test_restore_requires_literal_uuid_before_lookup(resume: str | None) -> None:
    """Invalid identities never reach history resolution or session construction."""
    args = ["--herdr-restore", REFERENCE]
    if resume is not None:
        args += ["--resume", resume]
    with (
        patch.object(TyperDispatch, "_resolve_resume_reference") as resolve,
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
        patch("src.cli.typer_dispatch.SloTUI") as tui,
    ):
        result = CliRunner().invoke(app=app, args=args)
    assert result.exit_code == 2
    assert "requires a literal canonical UUID --resume" in result.output
    resolve.assert_not_called()
    build.assert_not_called()
    tui.assert_not_called()


@pytest.mark.parametrize("extra", [["."], ["--workspace", "PRIVATE-MISSING"], ["--plugin", "PRIVATE-PLUGIN"]])
def test_restore_conflicts_precede_lookup(extra: list[str]) -> None:
    """Explicit config overrides refuse safely even when their paths do not exist."""
    with (
        patch.object(TyperDispatch, "_resolve_resume_reference") as resolve,
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
    ):
        result = CliRunner().invoke(
            app=app, args=["--resume", SESSION_ID, "--herdr-restore", REFERENCE, *extra]
        )
    assert result.exit_code == 2
    assert "cannot be combined" in result.output
    assert "PRIVATE-" not in result.output
    resolve.assert_not_called()
    build.assert_not_called()


def save_revision(*, pool: HerdrRestorePoolDAO | None = None) -> tuple[HerdrRestoreConfigDAO, str]:
    """Persist exact synthetic policy and history only inside the fixture-owned home."""
    root = dispatch_module._CFG_SLO_HOME
    assert root.resolve() == root and not root.is_symlink()
    integrations = root / "integrations"
    integrations.mkdir(mode=0o700, exist_ok=True)
    config = HerdrRestoreConfigDAO(
        session_id=SESSION_ID,
        model_name="gpt-5.4",
        reasoning_level="high",
        workdir=root,
        model_pool_dao=pool,
    )
    asyncio.run(
        FilesystemSessionHistoryStore().ensure_session(
            session_id=SESSION_ID,
            workdir=root,
            model_name="gpt-5.4",
        )
    )
    reference = HerdrRestoreStore(state_root=integrations / "herdr").save(config=config)
    return config, reference.restore_reference


def test_exact_single_restore_bypasses_preferences() -> None:
    """The actual parser loads private policy without ambient config assembly."""
    saved, reference = save_revision()
    with (
        patch.object(TyperDispatch, "_build_session_config", side_effect=AssertionError("ambient")),
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
        patch("src.cli.typer_dispatch.SloTUI") as tui,
    ):
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    assert result.exit_code == 0, result.exception
    config = build.call_args.kwargs["config"]
    assert config.model_name == saved.model_name
    assert config.reasoning_level == saved.reasoning_level
    assert config.workdir == saved.workdir
    assert config.session_id == SESSION_ID
    assert config.enable_history and config.history_root is None
    assert config.system_prompt is None and config.append_system_prompt is None
    assert config.extra_tools is None and config.should_stop_after_turn_hook is None
    tui.return_value.run.assert_called_once_with(mouse=True)


@pytest.mark.parametrize(
    "fault", ["missing_record", "missing_history", "corrupt_history", "wrong_history_identity"]
)
def test_restore_unavailable_before_construction(fault: str) -> None:
    """History/ref failure is a fixed safe usage error, never a fallback build."""
    _, reference = save_revision()
    root = dispatch_module._CFG_SLO_HOME
    metadata = root / "sessions" / "history" / SESSION_ID / "session.json"
    assert metadata.resolve().is_relative_to(root)
    if fault == "missing_record":
        reference = REFERENCE
    elif fault == "missing_history":
        metadata.unlink()
    elif fault == "corrupt_history":
        metadata.write_text("PRIVATE-BROKEN", encoding="utf-8")
    else:
        text = metadata.read_text(encoding="utf-8").replace(SESSION_ID, "private-other")
        metadata.write_text(text, encoding="utf-8")
    with patch("src.cli.typer_dispatch.SloAgentSession.build") as build:
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    assert result.exit_code == 2
    assert RESTORE_UNAVAILABLE_MESSAGE in result.output
    assert "PRIVATE" not in result.output and "private-other" not in result.output
    build.assert_not_called()


@pytest.mark.parametrize("invalid_provider", [False, True])
def test_pool_reconstruction_validates_new_mutable_entries(invalid_provider: bool) -> None:
    """Every saved scalar and entry order survives; provider mismatch fails closed."""
    pool = HerdrRestorePoolDAO(
        entries=(
            HerdrRestorePoolEntryDAO(
                model_name="gpt-5.4",
                provider=ProviderName.ANTHROPIC if invalid_provider else ProviderName.OPENAI,
                priority=9,
                cooldown_seconds=77,
                rate_limit_cooldown_seconds=13,
            ),
            HerdrRestorePoolEntryDAO(
                model_name="claude-sonnet-4-6",
                provider=ProviderName.ANTHROPIC,
                priority=2,
                cooldown_seconds=91,
                rate_limit_cooldown_seconds=17,
            ),
        )
    )
    saved, reference = save_revision(pool=pool)
    with (
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
        patch("src.cli.typer_dispatch.SloTUI"),
        patch("src.cli.typer_dispatch.UserPreferencesStore.load", side_effect=AssertionError("preferences")),
    ):
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    if invalid_provider:
        assert result.exit_code == 2
        assert RESTORE_UNAVAILABLE_MESSAGE in result.output
        build.assert_not_called()
        return
    assert result.exit_code == 0, result.exception
    restored = build.call_args.kwargs["config"].model_pool_dao
    assert restored is not None
    assert [entry.model_dump() for entry in restored.entries] == [
        entry.model_dump() for entry in pool.entries
    ]
    restored.entries[0].priority = 100
    restored.entries.reverse()
    loaded = HerdrRestoreStore(state_root=dispatch_module._CFG_SLO_HOME / "integrations" / "herdr").load(
        restore_reference=reference,
        session_id=SESSION_ID,
    )
    assert loaded == saved


@pytest.mark.parametrize("reference", ["", "../PRIVATE", "r1-" + "A" * 32, "r1-short"])
def test_invalid_reference_is_safe(reference: str) -> None:
    """Malformed references never build a runtime or reveal the supplied value."""
    save_revision()
    with patch("src.cli.typer_dispatch.SloAgentSession.build") as build:
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    assert result.exit_code == 2
    assert RESTORE_UNAVAILABLE_MESSAGE in result.output
    assert "PRIVATE" not in result.output
    build.assert_not_called()


@pytest.mark.parametrize("fault", ["json", "schema", "reference", "session", "slug", "extra"])
def test_invalid_private_record_is_safe(fault: str) -> None:
    """Real invalid bytes are refused before construction, without raw private data."""
    import json

    _, reference = save_revision()
    root = dispatch_module._CFG_SLO_HOME
    path = root / "integrations" / "herdr" / "restore-v1" / f"{reference}.json"
    assert path.resolve().is_relative_to(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if fault == "schema":
        payload["schema_version"] = 2
    elif fault == "reference":
        payload["restore_reference"] = REFERENCE
    elif fault == "session":
        payload["config"]["session_id"] = "22345678-1234-1234-1234-123456789abc"
    elif fault == "slug":
        payload["config"]["session_id"] = "PRIVATE-SLUG"
    elif fault == "extra":
        payload["config"]["secret"] = "PRIVATE-SENTINEL"
    path.write_text("PRIVATE-JSON" if fault == "json" else json.dumps(payload), encoding="utf-8")
    with patch("src.cli.typer_dispatch.SloAgentSession.build") as build:
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    assert result.exit_code == 2
    assert RESTORE_UNAVAILABLE_MESSAGE in result.output
    assert "PRIVATE" not in result.output
    build.assert_not_called()


def test_workspace_plugins_exact_and_old_reference_retained() -> None:
    """Exact saved workspace/plugin order wins over a later revision and ambient settings."""
    saved, old_reference = save_revision()
    root = dispatch_module._CFG_SLO_HOME
    workspace = root / "saved.code-workspace"
    assert workspace.resolve().is_relative_to(root)
    workspace.write_text('{"folders": []}', encoding="utf-8")
    plugins = (root / "second.py", root / "first.py")
    store = HerdrRestoreStore(state_root=root / "integrations" / "herdr")
    changed = HerdrRestoreConfigDAO(
        session_id=SESSION_ID,
        model_name="gpt-5.4",
        reasoning_level="low",
        workdir=root,
        workspace_file=workspace,
        plugin_paths=plugins,
    )
    reference = store.save(config=changed).restore_reference
    with (
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
        patch("src.cli.typer_dispatch.SloTUI"),
        patch("src.cli.typer_dispatch.UserPreferencesStore.load", side_effect=AssertionError("ambient")),
    ):
        for token, expected in [(reference, changed), (old_reference, saved)]:
            TyperDispatch.tui(
                workdir=None, resume_session_reference=SESSION_ID, herdr_restore_reference=token
            )
            config = build.call_args.kwargs["config"]
            assert config.workspace_file == expected.workspace_file
            assert config.plugin_paths == list(expected.plugin_paths)
            assert config.reasoning_level == expected.reasoning_level
            assert config.fallback_notice is None


def test_ordinary_slug_resume_still_uses_history_and_preferences() -> None:
    """The stricter Herdr gate does not tighten ordinary named/slug resume."""
    root = dispatch_module._CFG_SLO_HOME
    asyncio.run(
        FilesystemSessionHistoryStore().ensure_session(
            session_id="ordinary-slug",
            workdir=root,
            model_name="gpt-5.4",
        )
    )
    with (
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
        patch("src.cli.typer_dispatch.SloTUI"),
    ):
        result = CliRunner().invoke(app=app, args=["--resume", "ordinary-slug"])
    assert result.exit_code == 0, result.exception
    assert build.call_args.kwargs["config"].session_id == "ordinary-slug"


def test_saved_missing_workspace_refuses_before_build() -> None:
    """Existing CLI workspace admission remains in force without printing private paths."""
    saved, _ = save_revision()
    changed = saved.model_copy(update={"workspace_file": saved.workdir / "PRIVATE-MISSING"})
    reference = HerdrRestoreStore(state_root=saved.workdir / "integrations" / "herdr").save(config=changed)
    with patch("src.cli.typer_dispatch.SloAgentSession.build") as build:
        result = CliRunner().invoke(
            app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference.restore_reference]
        )
    assert result.exit_code == 2
    assert RESTORE_UNAVAILABLE_MESSAGE in result.output
    assert "PRIVATE-MISSING" not in result.output
    build.assert_not_called()


def test_restore_option_cannot_be_ignored_by_subcommand() -> None:
    """A root restore flag cannot silently turn into a different operation."""
    with patch.object(TyperDispatch, "update") as update:
        result = CliRunner().invoke(app=app, args=["--herdr-restore=" + REFERENCE, "update"])
    assert result.exit_code == 2
    update.assert_not_called()


def test_reporter_argv_reaches_real_session_without_provider_or_replay(tmp_path: Path) -> None:
    """The production argv builder feeds real dispatch/build, with factories safe before entry."""
    from src.agents.base import LLMBuildResult, LLMFactory
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.herdr.dao import (
        HerdrPublicationDAO,
        HerdrReportSnapshotDAO,
        HerdrRestoreCaptureDAO,
        HerdrRestoreReferenceDAO,
        HerdrSavedRestoreDAO,
    )
    from tests.agents.slo_agent.herdr.test_reporter import reporter

    saved, reference = save_revision()
    capture = HerdrRestoreCaptureDAO(config=saved)
    publication = HerdrPublicationDAO(
        configuration_generation=0,
        snapshot=HerdrReportSnapshotDAO(session_id=SESSION_ID, state="idle", tokens=()),
        restore_capture=capture,
    )
    owner = reporter(root=tmp_path)
    owner.publish(publication=publication)
    owner._resume_available = True
    argv = owner._build_resume_argv(
        publication=publication,
        saved=HerdrSavedRestoreDAO(
            configuration_generation=0,
            capture=capture,
            reference=HerdrRestoreReferenceDAO(restore_reference=reference),
        ),
    )
    assert argv == ("slo", "--resume", SESSION_ID, "--herdr-restore", reference)
    faux = FauxChatModel(responses=[FauxChatModel.assistant_message(content="unused")])
    root = dispatch_module._CFG_SLO_HOME
    before = {path: path.read_bytes() for path in (root / "sessions").rglob("*") if path.is_file()}
    with (
        patch.object(
            LLMFactory, "create", return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False)
        ) as factory,
        patch.object(LLMFactory, "create_pool", side_effect=AssertionError("unexpected pool")),
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch("src.cli.typer_dispatch.SloTUI") as tui,
    ):
        result = CliRunner().invoke(app=app, args=list(argv[1:]))
    assert result.exit_code == 0, result.exception
    session = tui.call_args.kwargs["session"]
    # Earlier import-isolation tests reload service.py; dispatch retains its original class binding.
    assert isinstance(session, dispatch_module.SloAgentSession)
    assert session.session_id == SESSION_ID
    assert session.active_model_name == saved.model_name
    factory.assert_not_called()
    after = {path: path.read_bytes() for path in (root / "sessions").rglob("*") if path.is_file()}
    assert after == before


def test_canonical_history_resolution_mismatch_refuses() -> None:
    """History resolver identity must agree with the literal before any runtime exists."""
    _, reference = save_revision()
    with (
        patch.object(TyperDispatch, "_resolve_resume_reference", return_value="another-session") as resolve,
        patch("src.cli.typer_dispatch.SloAgentSession.build") as build,
    ):
        result = CliRunner().invoke(app=app, args=["--resume", SESSION_ID, "--herdr-restore", reference])
    assert result.exit_code == 2
    assert RESTORE_UNAVAILABLE_MESSAGE in result.output
    resolve.assert_called_once_with(resume_session_reference=SESSION_ID)
    build.assert_not_called()
