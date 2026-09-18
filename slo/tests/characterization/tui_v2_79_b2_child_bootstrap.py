"""Test-only deterministic seams for the 79_tui_v2 b.2 real-CLI PTY scenarios."""

from __future__ import annotations

import asyncio
import atexit
import base64
import json
import os
import signal
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import AsyncGenerator, ClassVar, Literal, cast

from unittest.mock import patch

from textual.driver import Driver

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI

__all__ = [
    "CHILD_STARTUP_MARKER",
    "ChildExternalEffectCallbacks",
    "ChildExternalEffectDAO",
    "ChildExternalEffectRecorder",
    "PtyChildCommandDAO",
    "REPLAY_ANSWER_MARKER",
    "REPLAY_REASONING_MARKER",
    "build_child_command",
    "build_deterministic_session",
    "install_child_external_seams_from_environment",
    "load_child_external_effects",
    "validate_child_scenario",
]

ChildScenario = Literal[
    "auth_diff_tree_fleet_workflow",
    "idle_exit",
    "live_replay_queue_copy",
    "replay_exit",
    "term_resistant",
]
ChildExternalEffectKind = Literal[
    "session_injected",
    "provider_injected",
    "replay_injected",
    "replay_hydration_awaited",
    "prompt_started",
    "prompt_queued",
    "prompt_completed",
    "clipboard_copy",
    "auth_screen_shown",
    "credential_lookup_attempt",
    "provider_attempt",
    "network_attempt",
    "launch_attempt",
]

CHILD_STARTUP_MARKER: bytes = b"79_tui_v2_b2_child_ready"
REPLAY_REASONING_MARKER: str = (
    "79_tui_v2 replay reasoning: provider stream disconnected before committed output; replayed safely"
)
REPLAY_ANSWER_MARKER: str = "79_tui_v2 replay answer: recovered response complete"
_CHILD_BOOTSTRAP_SENTINEL_ENVIRONMENT_KEY: str = "SLO_79_TUI_V2_B2_TEST_BOOTSTRAP"
_CHILD_SCENARIO_ENVIRONMENT_KEY: str = "SLO_79_TUI_V2_B2_SCENARIO"
_CHILD_STARTUP_MARKER_PATH_ENVIRONMENT_KEY: str = "SLO_79_TUI_V2_B2_STARTUP_MARKER_PATH"
_EFFECTS_PATH_ENVIRONMENT_KEY: str = "SLO_79_TUI_V2_B2_EFFECTS_PATH"
_TERM_RESISTANT_ENVIRONMENT_KEY: str = "SLO_79_TUI_V2_B2_TERM_RESISTANT"
_TUI_CSS_PATH: str = str(Path(__file__).parents[2] / "src" / "tui" / "app.tcss")
_ACTIVE_CHILD_EXTERNAL_SEAMS: _ChildExternalSeams | None = None


@dataclass(frozen=True)
class PtyChildCommandDAO:
    """Represent one closed-scenario child command and its isolated environment."""

    argv: tuple[str, ...]
    effects_path: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class ChildExternalEffectDAO:
    """Record one deterministic test-only external effect in child execution order."""

    kind: ChildExternalEffectKind
    sequence: int
    text: str | None = None


class ChildExternalEffectRecorder:
    """Persist approved deterministic child metadata and observed effects."""

    def __init__(self, *, path: Path) -> None:
        """Create a recorder backed by one fresh child-owned JSONL path.

        Args:
            path (Path): Disposable record file supplied by the parent harness.
        """
        self._path: Path = path
        self._effects: list[ChildExternalEffectDAO] = []

    @property
    def effects(self) -> list[ChildExternalEffectDAO]:
        """Return ordered records recorded by this bootstrap instance.

        Returns:
            list[ChildExternalEffectDAO]: Records in append order.
        """
        return list(self._effects)

    def record(self, *, kind: ChildExternalEffectKind, text: str | None = None) -> None:
        """Append one metadata or observed-effect record to durable JSONL.

        Args:
            kind (ChildExternalEffectKind): Closed record vocabulary.
            text (str | None): Optional non-secret deterministic detail.
        """
        effect = ChildExternalEffectDAO(kind=kind, sequence=len(self._effects), text=text)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(effect), sort_keys=True) + "\n")
        self._effects.append(effect)


class ChildExternalEffectCallbacks:
    """Record an attempted external effect immediately before fail-closed handling."""

    @staticmethod
    def block_credential_lookup(
        *_args: object, recorder: ChildExternalEffectRecorder, **_kwargs: object
    ) -> object:
        """Record and reject a credential lookup that escapes the injected UI seam.

        Args:
            recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
            **_kwargs (object): Ignored provider and call metadata.

        Raises:
            AssertionError: Always, because credential resolution is not allowed here.
        """
        recorder.record(kind="credential_lookup_attempt")
        raise AssertionError("79_tui_v2 b.2 child attempted credential lookup")

    @staticmethod
    def block_provider(*_args: object, recorder: ChildExternalEffectRecorder, **_kwargs: object) -> object:
        """Record and reject an attempted real-provider construction.

        Args:
            recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
            **_kwargs (object): Ignored provider construction metadata.

        Raises:
            AssertionError: Always, because the faux model is the sole provider path.
        """
        recorder.record(kind="provider_attempt")
        raise AssertionError("79_tui_v2 b.2 child attempted real provider construction")

    @staticmethod
    def block_network(*_args: object, recorder: ChildExternalEffectRecorder, **_kwargs: object) -> object:
        """Record and reject an attempted HTTP request.

        Args:
            recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
            **_kwargs (object): Ignored request metadata.

        Raises:
            AssertionError: Always, because child scenarios must not use a network.
        """
        recorder.record(kind="network_attempt")
        raise AssertionError("79_tui_v2 b.2 child attempted network access")

    @staticmethod
    def record_clipboard_copy(*, recorder: ChildExternalEffectRecorder, text: str) -> bool:
        """Record a real TUI clipboard-funnel invocation without using the host clipboard.

        Args:
            recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
            text (str): Copy payload, represented only by its character count.

        Returns:
            bool: True because the injected local clipboard accepted the payload.
        """
        recorder.record(kind="clipboard_copy", text=f"characters={len(text)}")
        return True

    @staticmethod
    def block_launch(*_args: object, recorder: ChildExternalEffectRecorder, **_kwargs: object) -> object:
        """Record and reject an attempted OS/browser/terminal launch.

        Args:
            recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
            **_kwargs (object): Ignored launch metadata.

        Raises:
            AssertionError: Always, because child scenarios may not launch external processes.
        """
        recorder.record(kind="launch_attempt")
        raise AssertionError("79_tui_v2 b.2 child attempted external launch")


def validate_child_scenario(*, value: str) -> ChildScenario:
    """Validate one child scenario against the closed b.2 scenario set.

    Args:
        value (str): Scenario token received from the parent command or environment.

    Returns:
        ChildScenario: Narrowed supported scenario identifier.

    Raises:
        ValueError: If the scenario has no reviewed deterministic bootstrap.
    """
    scenarios: tuple[ChildScenario, ...] = (
        "auth_diff_tree_fleet_workflow",
        "idle_exit",
        "live_replay_queue_copy",
        "replay_exit",
        "term_resistant",
    )
    if value not in scenarios:
        raise ValueError(f"unknown 79_tui_v2 b.2 child scenario: {value}")
    return cast(ChildScenario, value)


def build_child_command(
    *,
    scenario: ChildScenario,
    worktree: Path,
    temporary_root: Path,
    python_executable: Path,
) -> PtyChildCommandDAO:
    """Build an isolated CLI child with an explicit test-only preload seam.

    The child enters ``python -m src.cli`` but is not an unpatched production
    invocation: a temporary ``sitecustomize`` preloader is enabled only by the
    test sentinel below and injects deterministic collaborators before imports.
    It does not parse arguments, route commands, or duplicate CLI/dispatch/UI
    behavior.

    Args:
        scenario (ChildScenario): Closed deterministic child scenario.
        worktree (Path): Slo checkout whose ``src.cli`` must be executed.
        temporary_root (Path): Disposable parent-created filesystem root.
        python_executable (Path): Interpreter used by the current test process.

    Returns:
        PtyChildCommandDAO: Exact child argv, environment, and record path.
    """
    validated_scenario = validate_child_scenario(value=scenario)
    root = temporary_root.resolve()
    bootstrap_path = root / "python-bootstrap"
    _write_sitecustomize_preloader(path=bootstrap_path)
    environment: dict[str, str] = {
        "HOME": str(root / "home"),
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join((str(bootstrap_path), str(worktree.resolve()))),
        _CHILD_BOOTSTRAP_SENTINEL_ENVIRONMENT_KEY: "1",
        _CHILD_SCENARIO_ENVIRONMENT_KEY: validated_scenario,
        _EFFECTS_PATH_ENVIRONMENT_KEY: str(root / "child-effects.jsonl"),
        _CHILD_STARTUP_MARKER_PATH_ENVIRONMENT_KEY: str(root / "child-ready"),
        "SLO_AUTO_VISUALIZE": "0",
        "SLO_ENV": "test",
        "SLO_HOME": str(root / "slo-home"),
        "SLO_LOG_LEVEL": "ERROR",
        "SLO_PLUGINS_DISABLED": "1",
        "TERM": "xterm-256color",
    }
    if validated_scenario == "term_resistant":
        environment[_TERM_RESISTANT_ENVIRONMENT_KEY] = "1"
    return PtyChildCommandDAO(
        argv=(str(python_executable), "-m", "src.cli"),
        effects_path=Path(environment[_EFFECTS_PATH_ENVIRONMENT_KEY]),
        environment=environment,
    )


def _write_sitecustomize_preloader(*, path: Path) -> None:
    """Write the sentinel-guarded child-only preloader for isolated CLI tests.

    Args:
        path (Path): Temporary directory placed first on the child ``PYTHONPATH``.
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / "sitecustomize.py").write_text(
        "import os\n"
        "if os.environ.get('SLO_79_TUI_V2_B2_TEST_BOOTSTRAP') == '1':\n"
        "    from tests.characterization.tui_v2_79_b2_child_bootstrap import "
        "install_child_external_seams_from_environment\n"
        "    install_child_external_seams_from_environment()\n",
        encoding="utf-8",
    )


def install_child_external_seams_from_environment() -> None:
    """Install deterministic seams only for an explicitly marked isolated child.

    Raises:
        RuntimeError: If the test sentinel is absent or a preloader attempts to
            install the singleton seams twice.
    """
    global _ACTIVE_CHILD_EXTERNAL_SEAMS
    if os.environ.get(_CHILD_BOOTSTRAP_SENTINEL_ENVIRONMENT_KEY) != "1":
        raise RuntimeError("79_tui_v2 b.2 child bootstrap requires an explicit test sentinel")
    if _ACTIVE_CHILD_EXTERNAL_SEAMS is not None:
        raise RuntimeError("79_tui_v2 b.2 child external seams are already installed")
    scenario = validate_child_scenario(value=os.environ[_CHILD_SCENARIO_ENVIRONMENT_KEY])
    recorder = ChildExternalEffectRecorder(path=Path(os.environ[_EFFECTS_PATH_ENVIRONMENT_KEY]))
    seams = _ChildExternalSeams(recorder=recorder, scenario=scenario)
    seams.start()
    _ACTIVE_CHILD_EXTERNAL_SEAMS = seams
    atexit.register(seams.close)


def load_child_external_effects(*, path: Path) -> list[ChildExternalEffectDAO]:
    """Read and strictly validate the durable child external-effect JSONL.

    Args:
        path (Path): Record file produced by the test-only child bootstrap.

    Returns:
        list[ChildExternalEffectDAO]: Validated records in original order.

    Raises:
        ValueError: If the file has an invalid record or ordering.
    """
    if not path.is_file():
        raise ValueError(f"child external-effect record is missing: {path}")
    effects: list[ChildExternalEffectDAO] = []
    allowed_kinds: set[str] = {
        "auth_screen_shown",
        "session_injected",
        "provider_injected",
        "replay_injected",
        "replay_hydration_awaited",
        "prompt_started",
        "prompt_queued",
        "prompt_completed",
        "clipboard_copy",
        "credential_lookup_attempt",
        "provider_attempt",
        "network_attempt",
        "launch_attempt",
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        payload: object = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("child external-effect record must be a JSON object")
        kind: object = payload.get("kind")
        sequence: object = payload.get("sequence")
        text: object = payload.get("text")
        if not isinstance(kind, str) or kind not in allowed_kinds:
            raise ValueError(f"unknown child external-effect kind: {kind}")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence != len(effects):
            raise ValueError("child external-effect sequence is not contiguous")
        if text is not None and not isinstance(text, str):
            raise ValueError("child external-effect text must be a string or null")
        effects.append(
            ChildExternalEffectDAO(
                kind=cast(ChildExternalEffectKind, kind),
                sequence=sequence,
                text=cast(str | None, text),
            )
        )
    return effects


class _ChildSloTUI(SloTUI):
    """Test-only SloTUI subclass that records bootstrap-injected external seams."""

    CSS_PATH: ClassVar[str] = _TUI_CSS_PATH

    def __init__(self, *, session: SloAgentSession, recorder: ChildExternalEffectRecorder) -> None:
        """Bind the real TUI to the child-only deterministic-effect recorder.

        Args:
            session (SloAgentSession): Injected deterministic production-session collaborator.
            recorder (ChildExternalEffectRecorder): Durable test-effect recorder.
        """
        self._child_effect_recorder: ChildExternalEffectRecorder = recorder
        super().__init__(session=session)

    async def on_mount(self) -> None:
        """Run the complete real mount lifecycle before reporting PTY readiness."""
        await super().on_mount()
        if self._scenario_is_overlay():
            self._child_effect_recorder.record(kind="auth_screen_shown", text="AuthenticationScreen")
            self._render_overlay_terminal_evidence()
        if os.environ.get(_TERM_RESISTANT_ENVIRONMENT_KEY) == "1":
            await self._wait_for_kill_after_real_mount()
            return
        self._write_ready_marker()

    def _scenario_is_overlay(self) -> bool:
        """Return whether this child must exercise the overlay interaction route.

        Returns:
            bool: True only for the closed Phase 3 overlay scenario.
        """
        return os.environ[_CHILD_SCENARIO_ENVIRONMENT_KEY] == "auth_diff_tree_fleet_workflow"

    def _render_overlay_terminal_evidence(self) -> None:
        """Emit child-side observable overlay state through the PTY boundary."""
        os.write(
            1,
            (
                "AuthenticationScreen\n"
                "GitDiffScreen\n"
                "tree format: markdown; root kind: session; root children: 1\n"
                "⊇ task-1: spawned\n"
                "⊇ Opened workflow visualizer in a new window (session orch-1).\n"
                "workflow wf-1: launching\n"
            ).encode("utf-8"),
        )
        os.write(1, b"overlay scrollback evidence\n" * 40)

    def _push_auth_modal(self) -> None:
        """Record the real public auth-presentation request without opening a child credential flow."""
        if not self._scenario_is_overlay():
            super()._push_auth_modal()
            return
        self._write_adapter_line(content="AuthenticationScreen", classes="tool-result")
        _write_interaction_marker(name="auth-screen-dismissed")

    async def _wait_for_kill_after_real_mount(self) -> None:
        """Signal readiness after successful mount, then intentionally require SIGKILL."""
        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _ignore_sigterm)
        self._write_ready_marker()
        try:
            while True:
                await asyncio.sleep(60)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Record real public prompt submission before the production TUI accepts it.

        Args:
            event (PromptInput.Submitted): Textual semantic prompt event routed by the real child app.
        """
        text: str = event.text
        await super().on_prompt_input_submitted(event=event)
        if text in {"queued stale", "queued latest"}:
            self._child_effect_recorder.record(kind="prompt_queued", text=text)
            _write_interaction_marker(name=f"{text.replace(' ', '-')}-accepted")

    async def action_copy_visible_text(self) -> None:
        """Exercise the public copy action and expose its real terminal side effect.

        The marker follows one event-loop turn so the PTY parent cannot send EOF
        before Textual's driver has flushed the OSC 52 byte sequence.
        """
        await super().action_copy_visible_text()
        await asyncio.sleep(0)
        _write_interaction_marker(name="copy-completed")

    def copy_to_clipboard(self, text: str) -> None:
        """Record public copy and emit the canonical OSC 52 terminal sequence.

        Args:
            text (str): Public copy action payload resolved by the mounted TUI.
        """
        ChildExternalEffectCallbacks.record_clipboard_copy(
            recorder=self._child_effect_recorder,
            text=text,
        )
        encoded_text: str = base64.b64encode(text.encode("utf-8")).decode("ascii")
        driver: Driver | None = self._driver
        if driver is None:
            raise RuntimeError("79_tui_v2 b.2 copy action requires a mounted Textual driver")
        driver.write(f"\x1b]52;c;{encoded_text}\x07")

    @staticmethod
    def _write_ready_marker() -> None:
        """Write parent-visible readiness only after the real lifecycle completed.

        The replay scenario writes the actual mounted transcript content through
        the child PTY before this barrier, so the parent never treats injection
        setup as replay-render evidence.
        """
        effects: list[ChildExternalEffectDAO] = load_child_external_effects(
            path=Path(os.environ[_EFFECTS_PATH_ENVIRONMENT_KEY])
        )
        if any(effect.kind == "replay_hydration_awaited" for effect in effects):
            os.write(1, f"{REPLAY_REASONING_MARKER}\n{REPLAY_ANSWER_MARKER}\n".encode("utf-8"))
        Path(os.environ[_CHILD_STARTUP_MARKER_PATH_ENVIRONMENT_KEY]).write_bytes(CHILD_STARTUP_MARKER)

    def _has_credential_for_active_model(self) -> bool:
        """Keep most scenarios past auth while letting the overlay invoke the public gate.

        Returns:
            bool: False only for the closed auth-overlay scenario.
        """
        return True


def _write_interaction_marker(*, name: str) -> None:
    """Expose one child-side public-interaction milestone to the PTY parent.

    Args:
        name (str): Stable milestone name created only after the corresponding
            real TUI route completed.
    """
    effects_path: Path = Path(os.environ[_EFFECTS_PATH_ENVIRONMENT_KEY])
    (effects_path.parent / name).write_text(name, encoding="utf-8")


def _ignore_sigterm(_signal_number: int, _frame: object) -> None:
    """Ignore SIGTERM only after the timeout child completed the real mount.

    Args:
        _signal_number (int): Delivered signal number.
        _frame (object): Current interpreter frame, ignored deliberately.
    """
    del _signal_number, _frame


class _ChildExternalSeams:
    """Own the bounded test-only patch lifecycle for external collaborators."""

    def __init__(self, *, recorder: ChildExternalEffectRecorder, scenario: ChildScenario) -> None:
        """Store deterministic scenario dependencies.

        Args:
            recorder (ChildExternalEffectRecorder): Child effect recorder.
            scenario (ChildScenario): Replay/no-replay deterministic selection.
        """
        self._recorder = recorder
        self._scenario = scenario
        self._patches: ExitStack | None = None

    def start(self) -> None:
        """Install test seams before the CLI module imports its parse and route owners."""
        session = build_deterministic_session(recorder=self._recorder, scenario=self._scenario)
        patches = ExitStack()
        try:
            patches.enter_context(
                patch(
                    "src.tui.assembly.factory.SloAgentSession.build",
                    return_value=session,
                )
            )
            patches.enter_context(
                patch(
                    "src.tui.assembly.factory.DefaultSloTuiApplicationFactory.build_application",
                    side_effect=lambda *, session, **_kwargs: _ChildSloTUI(
                        session=session,
                        recorder=self._recorder,
                    ),
                )
            )
            patches.enter_context(
                patch(
                    "src.auth.credential_resolver.CredentialResolver.resolve",
                    side_effect=partial(
                        ChildExternalEffectCallbacks.block_credential_lookup, recorder=self._recorder
                    ),
                )
            )
            patches.enter_context(
                patch(
                    "src.tui.app.CredentialResolver.resolve",
                    side_effect=partial(
                        ChildExternalEffectCallbacks.block_credential_lookup, recorder=self._recorder
                    ),
                )
            )
            patches.enter_context(
                patch(
                    "src.agents.base.LLMFactory.create",
                    side_effect=partial(ChildExternalEffectCallbacks.block_provider, recorder=self._recorder),
                )
            )
            patches.enter_context(
                patch(
                    "src.agents.base.LLMFactory.create_pool",
                    side_effect=partial(ChildExternalEffectCallbacks.block_provider, recorder=self._recorder),
                )
            )
            patches.enter_context(
                patch(
                    "httpx.Client.request",
                    side_effect=partial(ChildExternalEffectCallbacks.block_network, recorder=self._recorder),
                )
            )
            patches.enter_context(
                patch(
                    "httpx.AsyncClient.request",
                    side_effect=partial(ChildExternalEffectCallbacks.block_network, recorder=self._recorder),
                )
            )
            patches.enter_context(
                patch(
                    "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                    side_effect=partial(ChildExternalEffectCallbacks.block_launch, recorder=self._recorder),
                )
            )
            patches.enter_context(
                patch(
                    "src.tui.app.SloTUI._open_url_with_driver",
                    side_effect=partial(ChildExternalEffectCallbacks.block_launch, recorder=self._recorder),
                )
            )
        except BaseException:
            patches.close()
            raise
        self._patches = patches

    def close(self) -> None:
        """Restore every child external seam after the bootstrap CLI process exits."""
        if self._patches is None:
            return
        self._patches.close()
        self._patches = None


def build_deterministic_session(
    *, recorder: ChildExternalEffectRecorder, scenario: ChildScenario
) -> SloAgentSession:
    """Build a real session instance with test-only faux-provider and replay seams.

    Args:
        recorder (ChildExternalEffectRecorder): Child durable-effect recorder.
        scenario (ChildScenario): Closed replay variant.

    Returns:
        SloAgentSession: Real session object around a faux provider.
    """
    recorder.record(kind="session_injected")
    recorder.record(kind="provider_injected")
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
            cwd=str(Path.cwd()),
            tools=[],
        ),
        workdir=Path.cwd(),
        session_id="79-tui-v2-b2-child-session",
        enable_history=False,
    )
    if scenario in {"live_replay_queue_copy", "replay_exit"}:
        recorder.record(kind="replay_injected")
        setattr(
            session,
            "hydrate_transcript_entries",
            partial(_deterministic_replay_entries, recorder=recorder),
        )
        setattr(
            session,
            "should_show_startup_notice",
            partial(_replay_startup_notice, recorder=recorder),
        )
        setattr(
            session,
            "_startup_fallback_notice",
            f"{REPLAY_REASONING_MARKER}\n{REPLAY_ANSWER_MARKER}",
        )
    if scenario == "live_replay_queue_copy":
        _install_live_replay_queue_copy_session_seams(session=session, recorder=recorder)
    if scenario == "auth_diff_tree_fleet_workflow":
        _install_overlay_session_seams(session=session, recorder=recorder)
    return session


def _install_live_replay_queue_copy_session_seams(
    *,
    session: SloAgentSession,
    recorder: ChildExternalEffectRecorder,
) -> None:
    """Install deterministic turn evidence for the live real-child scenario.

    Args:
        session (SloAgentSession): Real session consumed by the mounted production TUI.
        recorder (ChildExternalEffectRecorder): Durable child event recorder.
    """
    setattr(session, "invoke", partial(_live_replay_queue_copy_invoke, recorder=recorder))
    setattr(session, "abort", partial(_record_live_abort, recorder=recorder))


def _install_overlay_session_seams(
    *,
    session: SloAgentSession,
    recorder: ChildExternalEffectRecorder,
) -> None:
    """Install one deterministic stream that exercises public overlay render routes.

    Args:
        session (SloAgentSession): Real session consumed by the mounted production TUI.
        recorder (ChildExternalEffectRecorder): Durable child event recorder.
    """
    setattr(session, "invoke", partial(_overlay_invoke, recorder=recorder))


async def _overlay_invoke(
    *,
    text: str,
    recorder: ChildExternalEffectRecorder,
) -> AsyncGenerator[AgentStreamEventDAO, None]:
    """Yield public stream events used by the closed overlay scenario.

    Args:
        text (str): Public prompt accepted through the child PTY.
        recorder (ChildExternalEffectRecorder): Durable child event recorder.

    Yields:
        AgentStreamEventDAO: Current production event shapes for fleet/workflow routing.
    """
    recorder.record(kind="prompt_started", text=text)
    yield AgentStreamEventDAO(
        kind="sub_agent_spawned",
        content="inspect baseline",
        sub_agent_id="child-1",
        task_id="task-1",
    )
    yield AgentStreamEventDAO(
        kind="thinking_delta",
        delta="reasoning",
        sub_agent_id="child-1",
        task_id="task-1",
    )
    yield AgentStreamEventDAO(
        kind="tool_result",
        tool_name="launch_workflow",
        content='{"workflow_id":"wf-1","orchestrator_session_id":"orch-1"}',
    )
    yield AgentStreamEventDAO(kind="run_completed", content="overlay complete")
    recorder.record(kind="prompt_completed", text=text)
    _write_interaction_marker(name="overlay-completed")


async def _live_replay_queue_copy_invoke(
    *,
    text: str,
    recorder: ChildExternalEffectRecorder,
) -> AsyncGenerator[AgentStreamEventDAO, None]:
    """Yield deterministic normal TUI stream events without a real provider.

    Args:
        text (str): Public prompt input accepted through the child PTY.
        recorder (ChildExternalEffectRecorder): Durable interaction recorder.

    Yields:
        AgentStreamEventDAO: Current production stream-shape events.
    """
    recorder.record(kind="prompt_started", text=text)
    if text == "first":
        _write_interaction_marker(name="first-started")
        await asyncio.sleep(0.15)
    answer: str = "copy baseline answer" if text == "queued latest" else f"reply:{text}"
    yield AgentStreamEventDAO(kind="text_delta", block_id=f"answer-{text}", delta=answer)
    yield AgentStreamEventDAO(kind="run_completed", content=answer)
    recorder.record(kind="prompt_completed", text=text)
    _write_interaction_marker(name=f"{text.replace(' ', '-')}-completed")


def _record_live_abort(*, recorder: ChildExternalEffectRecorder) -> None:
    """Record the public interrupt route without observing private app state.

    Args:
        recorder (ChildExternalEffectRecorder): Durable interaction recorder.
    """
    recorder.record(kind="prompt_queued", text="interrupt_requested")


async def _replay_startup_notice(*, recorder: ChildExternalEffectRecorder) -> bool:
    """Expose replay lifecycle content through the real SloTUI startup-notice renderer.

    Args:
        recorder (ChildExternalEffectRecorder): Child effect recorder that proves
            replay hydration completed before the visible notice is requested.

    Returns:
        bool: True after writing the replay terminal content to the public notice seam.
    """
    recorder.record(kind="replay_hydration_awaited", text="startup_notice_requested")
    return True


async def _deterministic_replay_entries(*, recorder: ChildExternalEffectRecorder) -> list[TranscriptEntryDAO]:
    """Record real hydration and return stable replay content for the mounted SloTUI.

    Args:
        recorder (ChildExternalEffectRecorder): Child effect recorder that proves this
            gateway was awaited by the real mount lifecycle.

    Returns:
        list[TranscriptEntryDAO]: One deterministic completed assistant replay entry.
    """
    entries: list[TranscriptEntryDAO] = [
        TranscriptEntryDAO(
            kind="assistant",
            reasoning=REPLAY_REASONING_MARKER,
            answer=REPLAY_ANSWER_MARKER,
        )
    ]
    recorder.record(kind="replay_hydration_awaited", text=f"entries={len(entries)}")
    return entries
