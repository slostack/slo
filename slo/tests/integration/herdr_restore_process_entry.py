"""Test regular-entry shim: fresh process safety precedes every application import."""

import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.integration.herdr_restore_process_bootstrap import ProcessSafety

ROOT = Path(os.environ["T6_ROOT"]).resolve(strict=True)
HOME = Path(os.environ["SLO_HOME"]).resolve(strict=True)
assert HOME.is_relative_to(ROOT)
SAFETY = ProcessSafety(root=ROOT, stdio=(1, 2))
SAFETY.install()
# Subprocess DEVNULL redirection must not open even /dev/null for writing.
null_sink = ROOT / "null-sink"
null_sink.touch(exist_ok=True)
os.devnull = str(null_sink)
for key in tuple(os.environ):
    if key.upper().startswith("HERDR_"):
        del os.environ[key]
os.environ.update(
    SLO_ENV="test",
    SLO_ROOT_DIR=str(ROOT),
    SLO_APP_DIR=str(ROOT),
    SLO_APP_NAME="slo",
    SLO_LOG_FORMAT="text",
    SLO_DEFAULT_MODEL_NAME="gpt-5.4",
    SLO_AUTO_VISUALIZE="0",
    SLO_HERDR_DISABLED="1",
    SLO_OPENAI_API_KEY="synthetic-offline-key",
    SLO_AUTH_FILE=str(HOME / "global/authentication.json"),
)

if os.environ.get("T6_CAPABILITY") == "refused":
    os.environ.pop("SLO_OPENAI_API_KEY")

from langchain_core.messages import AIMessage
from src.agents.base import LLMBuildResult, LLMFactory
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.auth.credential_dao import ProviderName, AuthType, CredentialDAO
from src.auth.credential_resolver import CredentialResolver
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.dao import ModelCatalogEntryDAO, ModelCatalogSnapshotDAO
from contextlib import ExitStack
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.user_message_block import UserMessageBlock
from src.tui.visualizer_launcher import VisualizerLauncher
from tests.state_isolation import FakeHerdrSpawnGuard


def forbidden(*args: object, **kwargs: object) -> None:
    """Never let a missing offline seam open a terminal or build a pool."""
    raise AssertionError("forbidden external boundary")


def write_json(*, name: str, value: object) -> None:
    """Persist a parent-owned observation, not application restore input."""
    (ROOT / name).write_text(json.dumps(value), encoding="utf-8")


async def publish() -> None:
    """Run config-backed session and reporter with only a registered fake executable."""
    executable = ROOT / "fake-herdr"
    capture = ROOT / "commands.jsonl"
    capture.write_text("", encoding="utf-8")
    executable.write_text(SAFETY.capture_script(path=capture), encoding="utf-8")
    executable.chmod(0o700)
    shim = ROOT / "slo"
    guard = FakeHerdrSpawnGuard(root=ROOT)
    guard.register(executable=executable, files=(capture, shim))
    SAFETY.executable = executable
    metadata = executable.stat()
    SAFETY.identity = (metadata.st_dev, metadata.st_ino)
    original = HerdrCliTransport._spawn

    async def guarded_spawn(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO
    ) -> asyncio.subprocess.Process:
        """Recheck capability immediately before the real transport spawn."""
        guard.require_registered(path=transport._config.binary_path)
        return await original(transport, command=command)

    os.environ.update(
        HERDR_ENV="1", HERDR_PANE_ID="offline-pane", HERDR_BIN_PATH=str(executable), SLO_HERDR_DISABLED="0"
    )
    session = SloAgentSession.build(config=build_policy())
    with patch.object(HerdrCliTransport, "_spawn", guarded_spawn):
        await publish_session(session=session, capture=capture)


def build_policy() -> SessionConfigDAO:
    """Build exact path and deliberately unsorted pool policy from test-owned inputs."""
    workspace = HOME / "saved.code-workspace"
    workspace.write_text('{"folders": []}', encoding="utf-8")
    plugins = [HOME / "first.py", HOME / "second.py"]
    for plugin in plugins:
        plugin.write_text(
            f"from pathlib import Path\ndef register(slo):\n    Path({str(HOME / (plugin.stem + '-loaded'))!r}).touch()\n",
            encoding="utf-8",
        )
    project = HOME / ".slo" / "plugins"
    project.mkdir(parents=True)
    (project / "untrusted.py").write_text(
        f"from pathlib import Path\nPath({str(HOME / 'untrusted-executed')!r}).touch()\n"
        "def register(slo):\n    pass\n",
        encoding="utf-8",
    )
    pool = None
    if os.environ.get("T6_POLICY") == "pool":
        pool = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="gpt-5.4",
                    provider=ProviderName.OPENAI,
                    priority=9,
                    cooldown_seconds=77,
                    rate_limit_cooldown_seconds=13,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-5.5",
                    provider=ProviderName.OPENAI,
                    priority=2,
                    cooldown_seconds=91,
                    rate_limit_cooldown_seconds=17,
                ),
            ]
        )
    return SessionConfigDAO(
        workdir=HOME,
        model_name="gpt-5.4",
        reasoning_level="high",
        workspace_file=workspace,
        plugin_paths=plugins,
        model_pool_dao=pool,
    )


factory_credentials_checked = 0


def require_synthetic_credential() -> None:
    """Check real resolution at each replaced factory use, never admit ambient secrets."""
    from src.auth.credential_resolver import CredentialResolver

    global factory_credentials_checked
    credential = CredentialResolver.require(provider=ProviderName.OPENAI)
    assert credential.access_token == "synthetic-offline-key"
    assert credential.refresh_token is None
    factory_credentials_checked += 1


def faux_single(**kwargs: object) -> LLMBuildResult:
    """Replace provider construction only after the real synthetic credential gate."""
    require_synthetic_credential()
    return LLMBuildResult(llm=faux, supports_explicit_caching=False)


def faux_pool(*, pool_dao: ModelPoolDAO, **kwargs: object) -> ModelPool:
    """Keep real pool routing but replace every provider member before construction."""
    require_synthetic_credential()
    assert all(entry.provider == ProviderName.OPENAI for entry in pool_dao.entries)
    return ModelPool(pool_dao=pool_dao, models={entry.model_name: faux for entry in pool_dao.entries})


async def publish_session(*, session: SloAgentSession, capture: Path) -> None:
    """Keep actual mount/provenance and current history beyond the advertised revision."""
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        async for _ in session.invoke(text="first offline prompt"):
            pass
        async with asyncio.timeout(15):
            while "--herdr-restore" not in capture.read_text():
                await asyncio.sleep(0.01)
        row = next(json.loads(line) for line in capture.read_text().splitlines() if "--herdr-restore" in line)
        index = row.index("--resume") - 1
        argv = row[index : index + 5]
        write_json(name="advertised.json", value=argv)
        async for _ in session.invoke(text="current history after advertisement"):
            pass
        assert session._herdr_capture is not None
        assert session._history_store is not None
        events = await session._history_store.load_events(session_id=session.session_id)
        assert session._config is not None
        original_policy = session._herdr_capture.config.model_dump(mode="json")
        session._config.plugin_paths.reverse()
        if session._config.model_pool_dao is not None:
            session._config.model_pool_dao.entries[0].cooldown_seconds = 333
            session._config.model_pool_dao.entries.reverse()
        assert session._herdr_capture.config.model_dump(mode="json") == original_policy
        write_json(
            name="published.json",
            value={
                "pid": os.getpid(),
                "policy": session._herdr_capture.config.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in events],
                "tool_results": sum(event.kind == "tool_result" for event in events),
                "factory_credentials_checked": factory_credentials_checked,
                "mutable_policy_changed": session._config.plugin_paths[0].name == "second.py",
                "record_bytes": (HOME / "integrations/herdr/restore-v1" / (argv[4] + ".json")).read_text(),
            },
        )
        (HOME / "first-loaded").unlink()
        (HOME / "second-loaded").unlink()
        UserPreferencesStore.upsert(model_name="gpt-5.5", reasoning_level="low", model_pool="gpt-5.5,gpt-5.4")


async def observe_restore(app: SloTUI) -> None:
    """Mount the actual dispatch-created app without submitting any prompt."""
    session = app._session
    assert (HOME / "first-loaded").exists() and (HOME / "second-loaded").exists()
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert session._config is not None
        assert session._history_store is not None
        from src.agents.slo_agent.herdr.dao import HerdrRestoreConfigDAO

        config = session._config
        assert config.model_name is not None
        policy = HerdrRestoreConfigDAO(
            session_id=session.session_id,
            model_name=config.model_name,
            reasoning_level=session._active_reasoning_level,
            workdir=config.workdir,
            workspace_file=config.workspace_file,
            plugin_paths=tuple(config.plugin_paths),
            model_pool_dao=session._capture_herdr_pool(pool=config.model_pool_dao),
        )
        capability = os.environ.get("T6_CAPABILITY", "available")
        public_admission = "not_attempted"
        painted_error = ""
        if capability == "model_changed":
            from src.tui.app import PromptInput

            app.query_one(PromptInput).text = "explicit capability refusal probe"
            await pilot.press("enter")
            async with asyncio.timeout(10):
                while session._operator_attention is None or app._in_flight_task is not None:
                    await pilot.pause()
            await pilot.pause()
            from textual.widgets import Static
            from tests.tui.authentication._painted_output import painted_widget_strips

            errors = [
                widget
                for widget in app.query(Static)
                if "This model requires an OpenAI Platform API key" in str(widget.render())
            ]
            assert len(errors) == 1
            painted_error = "\n".join(
                strip.text for strip in painted_widget_strips(app=app, widget=errors[0])
            )
            public_admission = "model_refused"
            assert session._agent is None
        if capability == "refused":
            # A distinct explicit user attempt, never a replay of either saved prompt.
            try:
                async for _ in session.invoke(text="explicit credential refusal probe"):
                    raise AssertionError("refused submission emitted execution output")
            except ValueError as error:
                assert "credential" in str(error).lower() or "api key" in str(error).lower()
                public_admission = "credential_refused"
            else:
                raise AssertionError("missing credential admitted")
            assert session._agent is None
            assert config.model_pool_dao is None or len(config.model_pool_dao.entries) == 2
        events = await session._history_store.load_events(session_id=session.session_id)
        write_json(
            name="restored.json",
            value={
                "pid": os.getpid(),
                "argv": ["slo", *sys.argv[1:]],
                "policy": policy.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in events],
                "model_calls": factory.call_count + pool_factory.call_count,
                "visible_prompts": [block.text for block in app.query(UserMessageBlock)],
                "record_bytes": (
                    HOME / "integrations/herdr/restore-v1" / (sys.argv[4] + ".json")
                ).read_text(),
                "project_plugin_refused": not (HOME / "untrusted-executed").exists(),
                "capability": capability,
                "public_admission": public_admission,
                "painted_error": painted_error,
                "reporting_state": session._reporting_state().model_dump(mode="json"),
            },
        )


def current_entry(
    *, model_name: str, snapshot: ModelCatalogSnapshotDAO | None = None
) -> ModelCatalogEntryDAO:
    """Change only the child-local catalog capability, retaining normal eligibility."""
    entry = original_entry(model_name=model_name, snapshot=snapshot)
    if entry.provider is ProviderName.OPENAI:
        return entry.model_copy(
            update={"supports_chatgpt_codex": os.environ["T6_CAPABILITY"] == "model_supported"}
        )
    return entry


async def no_refresh(**kwargs: object) -> None:
    """Synthetic OAuth never refreshes or reaches a provider."""


def headless_run(app: SloTUI, *, mouse: bool) -> None:
    """Replace only Textual's terminal driver; retain real mount and teardown."""
    asyncio.run(observe_restore(app))


if __name__ == "__main__":
    faux = FauxChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "now", "args": {}, "id": "offline-tool"}]),
            AIMessage(content="first answer"),
            AIMessage(content="second answer"),
        ]
    )
    with (
        ExitStack() as fixtures,
        patch.object(VisualizerLauncher, "_default_spawn", forbidden),
        patch.object(LLMFactory, "create", side_effect=faux_single) as factory,
        patch.object(LLMFactory, "create_pool", side_effect=faux_pool) as pool_factory,
    ):
        if os.environ.get("T6_CAPABILITY", "").startswith("model_"):
            credential = CredentialDAO(
                provider=ProviderName.OPENAI, auth_type=AuthType.OAUTH, access_token="synthetic-offline-key"
            )
            fixtures.enter_context(patch.object(CredentialResolver, "resolve", return_value=credential))
            original_entry = ModelCatalogService.entry_for_model
            fixtures.enter_context(
                patch.object(ModelCatalogService, "entry_for_model", side_effect=current_entry)
            )
            fixtures.enter_context(
                patch("src.agents.slo_agent.sessions.service.refresh_if_stale", side_effect=no_refresh)
            )
        if sys.argv[1:] == ["publish"]:
            asyncio.run(publish())
        else:
            from src.cli.app import main

            with patch.object(SloTUI, "run", headless_run):
                raise SystemExit(main())
