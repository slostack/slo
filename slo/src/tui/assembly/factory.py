"""Production adapters and fail-closed assembly for Slo's current Textual TUI."""

from __future__ import annotations

from config.ai_model_config import resolve_model_name_with_fallback
from config.cfg import cfg
from config.logger import log_info
from config.model_pool_config import parse_model_pool_config
from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.preferences.dao import (
    UserPreferencesDAO,
    UserPreferencesStoreCorruptError,
)
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.assembly.dao import SloTuiAssemblyConfigDAO
from src.tui.assembly.ports import (
    SloAgentSessionFactory,
    SloClipboardPort,
    SloDetachedVisualizerLauncher,
    SloDetachedWorkflowRendererFactory,
    SloOsc52ClipboardPort,
    SloTuiApplication,
    SloTuiApplicationFactory,
    SloTuiRunner,
    SloTuiSessionFactory,
)
from src.tui.visualizer_launcher import VisualizerLauncher
from src.tui.workflows.renderer import (
    DetachedWorkflowNoticeSink,
    DetachedWorkflowRenderer,
)

__all__ = [
    "DefaultSloAgentSessionFactory",
    "DefaultSloClipboardPort",
    "DefaultSloDetachedVisualizerLauncher",
    "DefaultSloDetachedWorkflowRendererFactory",
    "DefaultSloTuiApplicationFactory",
    "DefaultSloTuiAssemblyFactory",
    "DefaultSloTuiRunner",
    "DefaultSloTuiSessionFactory",
    "SloTuiAssemblyConfigurationError",
]


class SloTuiAssemblyConfigurationError(ValueError):
    """Report a local interactive assembly contract violation before runner startup."""


class DefaultSloTuiSessionFactory:
    """Build existing session configuration from immutable interactive inputs."""

    def build_config(self, *, config: SloTuiAssemblyConfigDAO) -> SessionConfigDAO:
        """Resolve existing preference-backed session configuration without provider activity.

        WHAT: Preserves the current preference/default model resolution used by the TUI path.
        WHO: DefaultSloTuiAssemblyFactory calls this after local configuration validation.
        WHEN: Before lazy session construction, credentials, providers, or the application runner.

        Args:
            config (SloTuiAssemblyConfigDAO): Validated resolved interactive facts.

        Returns:
            SessionConfigDAO: Existing lazy-session configuration with propagated CLI facts.
        """
        preferences: UserPreferencesDAO = self._load_preferences()
        model_name: str = preferences.default_model_name or cfg("DEFAULT_MODEL_NAME") or "gpt-5.4"
        resolved_model_name: str
        fallback_notice: str | None
        resolved_model_name, fallback_notice = resolve_model_name_with_fallback(model_name=model_name)
        return SessionConfigDAO(
            workdir=config.workdir,
            workspace_file=config.workspace_file,
            model_name=resolved_model_name,
            model_pool_dao=parse_model_pool_config(preference_value=preferences.default_model_pool),
            reasoning_level=preferences.default_reasoning_level,
            session_id=config.resume_session_id,
            fallback_notice=fallback_notice,
            plugin_paths=list(config.plugin_paths),
        )

    @staticmethod
    def _load_preferences() -> UserPreferencesDAO:
        """Load stored preferences while preserving the existing corrupt-file fallback.

        WHAT: Reads user preferences and treats a corrupt stored file as absent.
        WHO: build_config calls this as its only preference resolution step.
        WHEN: Before session construction and without credential or network work.

        Returns:
            UserPreferencesDAO: Persisted preferences or default values after a corrupt-file fallback.
        """
        try:
            return UserPreferencesStore.load()
        except UserPreferencesStoreCorruptError:
            log_info(msg="preferences_file_corrupt_falling_back_to_defaults")
            return UserPreferencesDAO()


class DefaultSloAgentSessionFactory:
    """Adapt Slo's existing lazy agent-session builder."""

    def build_session(self, *, config: SessionConfigDAO) -> SloAgentSession:
        """Build one lazy Slo session without invoking its provider path.

        WHAT: Delegates exactly once to the existing session constructor.
        WHO: DefaultSloTuiAssemblyFactory calls this before orchestrator promotion.
        WHEN: After session configuration resolves and before application construction.

        Args:
            config (SessionConfigDAO): Existing validated lazy-session configuration.

        Returns:
            SloAgentSession: Built session that has not been invoked.
        """
        return SloAgentSession.build(config=config)


class DefaultSloClipboardPort:
    """Preserve Slo's local clipboard followed by terminal OSC-52 delivery."""

    def __init__(
        self,
        *,
        local_clipboard: SloClipboardPort | None = None,
        osc52_clipboard: SloOsc52ClipboardPort | None = None,
    ) -> None:
        """Store explicit transport endpoints without attempting a clipboard write.

        WHAT: Retains optional transport collaborators for a later copy action.
        WHO: Production assembly builds this once; focused tests may inject both endpoints.
        WHEN: During local object-graph construction before the application runner starts.

        Args:
            local_clipboard (SloClipboardPort | None): Optional local clipboard endpoint.
            osc52_clipboard (SloClipboardPort | None): Optional terminal OSC-52 endpoint.
        """
        self._local_clipboard: SloClipboardPort | None = local_clipboard
        self._osc52_clipboard: SloOsc52ClipboardPort | None = osc52_clipboard

    def copy(self, *, text: str) -> None:
        """Copy selected text locally first and then send it through OSC-52.

        WHAT: Preserves the existing non-fatal local-copy behavior before terminal delivery.
        WHO: SloTUI invokes this after its current selection policy chooses non-empty text.
        WHEN: Only on an operator copy action after the application has started.

        Args:
            text (str): Selected text to deliver unchanged.
        """
        self._copy_locally(text=text)
        self._copy_via_osc52(text=text)

    def _copy_locally(self, *, text: str) -> None:
        """Attempt local clipboard delivery without blocking terminal fallback.

        WHAT: Sends text to an injected local endpoint or pyperclip and suppresses local failure.
        WHO: copy calls this as the first half of Slo's clipboard funnel.
        WHEN: Immediately before OSC-52 terminal delivery for a copy action.

        Args:
            text (str): Selected text to copy locally.
        """
        if self._local_clipboard is not None:
            self._copy_with_local_endpoint(text=text)
            return
        self._copy_with_current_local_helper(text=text)

    def _copy_with_local_endpoint(self, *, text: str) -> None:
        """Attempt an injected local clipboard endpoint without blocking OSC-52.

        WHAT: Preserves best-effort local delivery for test or production endpoint adapters.
        WHO: ``_copy_locally`` delegates here when the assembly supplied an endpoint.
        WHEN: Immediately before the mandatory terminal clipboard fallback.

        Args:
            text (str): Selected text to deliver locally.
        """
        local_clipboard: SloClipboardPort | None = self._local_clipboard
        if local_clipboard is None:
            return
        try:
            local_clipboard.copy(text=text)
        except Exception:  # noqa: BLE001 - local clipboard failure must not block OSC-52
            return

    @staticmethod
    def _copy_with_current_local_helper(*, text: str) -> None:
        """Attempt Slo's compatibility local clipboard helper without blocking OSC-52.

        WHAT: Retains legacy direct-app copy behavior when no local endpoint was injected.
        WHO: ``_copy_locally`` delegates here for standard production assembly.
        WHEN: Immediately before the mandatory terminal clipboard fallback.

        Args:
            text (str): Selected text to deliver through the current local helper.
        """
        try:
            from src.tui.app import SloTUI

            SloTUI._copy_via_local_clipboard(text=text)
        except Exception:  # noqa: BLE001 - local clipboard failure must not block OSC-52
            return

    def _copy_via_osc52(self, *, text: str) -> None:
        """Deliver text through the injected terminal OSC-52 endpoint when available.

        WHAT: Delegates the terminal write to the current app-owned endpoint.
        WHO: copy calls this after its non-fatal local delivery attempt.
        WHEN: On every selected-text copy action, including local clipboard failure.

        Args:
            text (str): Selected text to deliver through OSC-52.
        """
        if self._osc52_clipboard is None:
            return
        self._osc52_clipboard.copy_to_clipboard(text)


class DefaultSloDetachedVisualizerLauncher:
    """Delegate visualizer spawning to Slo's concrete best-effort owner."""

    def launch(self, *, parent_session_id: str) -> bool:
        """Launch Slo's existing visualizer without reimplementing platform policy.

        WHAT: Calls VisualizerLauncher with the supplied parent session identifier.
        WHO: Slo TUI and detached workflow renderer collaboration paths call this port.
        WHEN: Only after existing Slo policy requests a visualizer window.

        Args:
            parent_session_id (str): Detached orchestrator session to visualize.

        Returns:
            bool: Existing best-effort launcher outcome.
        """
        return VisualizerLauncher.launch(parent_session_id=parent_session_id)


class DefaultSloDetachedWorkflowRendererFactory:
    """Construct Slo's current workflow renderer with an injected launcher port."""

    def build_renderer(
        self,
        *,
        notice_sink: DetachedWorkflowNoticeSink,
        visualizer_launcher: SloDetachedVisualizerLauncher,
    ) -> DetachedWorkflowRenderer:
        """Create the current renderer without taking workflow-state ownership.

        WHAT: Adapts the launcher port to the renderer's existing callable seam.
        WHO: SloTUI calls this after compose makes its transcript notice sink available.
        WHEN: Lazily when the first workflow UI effect requires a renderer.

        Args:
            notice_sink (DetachedWorkflowNoticeSink): Current transcript notice writer.
            visualizer_launcher (SloDetachedVisualizerLauncher): Best-effort launch owner.

        Returns:
            DetachedWorkflowRenderer: Existing renderer retaining de-duplication state.
        """
        return DetachedWorkflowRenderer(
            notice_sink=notice_sink,
            launcher=visualizer_launcher.launch,
        )


class DefaultSloTuiApplicationFactory:
    """Build current SloTUI with its explicit Slo-owned collaborators."""

    def build_application(
        self,
        *,
        session: SloAgentSession,
        clipboard: SloClipboardPort,
        detached_workflow_renderer_factory: SloDetachedWorkflowRendererFactory,
        visualizer_launcher: SloDetachedVisualizerLauncher,
        session_factory: SloAgentSessionFactory,
    ) -> SloTuiApplication:
        """Construct current SloTUI without starting the terminal loop.

        WHAT: Injects all public assembly collaborators into the existing Textual owner.
        WHO: DefaultSloTuiAssemblyFactory calls this after session promotion.
        WHEN: Immediately before its final synchronous runner call.

        Args:
            session (SloAgentSession): Promoted lazy interactive session.
            clipboard (SloClipboardPort): Slo copy-delivery port.
            detached_workflow_renderer_factory (SloDetachedWorkflowRendererFactory): Renderer builder.
            visualizer_launcher (SloDetachedVisualizerLauncher): Best-effort visualizer port.
            session_factory (SloAgentSessionFactory): Lazy replacement-session builder for `/new`.

        Returns:
            SloTuiApplication: Current SloTUI prior to event-loop startup.
        """
        from src.tui.app import SloTUI

        return SloTUI(
            session=session,
            clipboard=clipboard,
            detached_workflow_renderer_factory=detached_workflow_renderer_factory,
            visualizer_launcher=visualizer_launcher,
            session_factory=session_factory,
        )


class DefaultSloTuiRunner:
    """Call the current application's synchronous Textual runner."""

    def run(self, *, application: SloTuiApplication, mouse: bool) -> None:
        """Enter the current terminal app once.

        WHAT: Delegates to the application run surface exactly once.
        WHO: DefaultSloTuiAssemblyFactory calls this as its last successful action.
        WHEN: After all local construction has completed without provider activity.

        Args:
            application (SloTuiApplication): Fully assembled current application.
            mouse (bool): Existing current TUI mouse setting.
        """
        application.run(mouse=mouse)


class DefaultSloTuiAssemblyFactory:
    """Build and run Slo's one permitted current Textual interactive object graph."""

    def __init__(
        self,
        *,
        session_config_factory: SloTuiSessionFactory,
        session_factory: SloAgentSessionFactory,
        application_factory: SloTuiApplicationFactory,
        clipboard: SloClipboardPort,
        visualizer_launcher: SloDetachedVisualizerLauncher,
        detached_workflow_renderer_factory: SloDetachedWorkflowRendererFactory,
        runner: SloTuiRunner,
    ) -> None:
        """Store only Slo-owned construction collaborators without starting runtime work.

        WHAT: Captures testable assembly dependencies without sessions, credentials, or terminal output.
        WHO: A future CLI caller constructs this factory once for an interactive command.
        WHEN: Before run validates the closed scenario and begins local composition.

        Args:
            session_config_factory (SloTuiSessionFactory): Existing config builder.
            session_factory (SloAgentSessionFactory): Existing lazy session builder.
            application_factory (SloTuiApplicationFactory): Current application constructor.
            clipboard (SloClipboardPort): Current Slo clipboard transport.
            visualizer_launcher (SloDetachedVisualizerLauncher): Current visualizer launch owner.
            detached_workflow_renderer_factory (SloDetachedWorkflowRendererFactory): Existing renderer builder.
            runner (SloTuiRunner): Synchronous application runner.
        """
        self._session_config_factory: SloTuiSessionFactory = session_config_factory
        self._session_factory: SloAgentSessionFactory = session_factory
        self._application_factory: SloTuiApplicationFactory = application_factory
        self._clipboard: SloClipboardPort = clipboard
        self._visualizer_launcher: SloDetachedVisualizerLauncher = visualizer_launcher
        self._detached_workflow_renderer_factory: SloDetachedWorkflowRendererFactory = (
            detached_workflow_renderer_factory
        )
        self._runner: SloTuiRunner = runner

    @classmethod
    def build_default(cls) -> DefaultSloTuiAssemblyFactory:
        """Build production assembly adapters without creating a session or app.

        WHAT: Wires the current Slo-only collaborators for the closed textual scenario.
        WHO: A future interactive CLI caller will invoke this after resolving CLI facts.
        WHEN: Before run performs validation or local object-graph construction.

        Returns:
            DefaultSloTuiAssemblyFactory: Unstarted production assembly factory.
        """
        clipboard: DefaultSloClipboardPort = DefaultSloClipboardPort()
        visualizer_launcher: DefaultSloDetachedVisualizerLauncher = DefaultSloDetachedVisualizerLauncher()
        return cls(
            session_config_factory=DefaultSloTuiSessionFactory(),
            session_factory=DefaultSloAgentSessionFactory(),
            application_factory=DefaultSloTuiApplicationFactory(),
            clipboard=clipboard,
            visualizer_launcher=visualizer_launcher,
            detached_workflow_renderer_factory=DefaultSloDetachedWorkflowRendererFactory(),
            runner=DefaultSloTuiRunner(),
        )

    def run(self, *, config: SloTuiAssemblyConfigDAO) -> None:
        """Validate, assemble, and run the current application exactly once.

        WHAT: Builds config, lazy session, promotion, current app, then makes one runner call.
        WHO: A future interactive CLI caller will invoke this after resolving its command inputs.
        WHEN: Before the first user prompt; this method never invokes the session itself.

        Args:
            config (SloTuiAssemblyConfigDAO): Closed scenario plus resolved interactive facts.

        Raises:
            SloTuiAssemblyConfigurationError: If local scenario, paths, or factory output is invalid.
        """
        self._validate_config(config=config)
        session: SloAgentSession = self._build_promoted_session(config=config)
        application: SloTuiApplication = self._application_factory.build_application(
            session=session,
            clipboard=self._clipboard,
            detached_workflow_renderer_factory=self._detached_workflow_renderer_factory,
            visualizer_launcher=self._visualizer_launcher,
            session_factory=self._session_factory,
        )
        if application is None:
            raise SloTuiAssemblyConfigurationError("application factory returned no application")
        self._runner.run(application=application, mouse=True)

    @staticmethod
    def _validate_config(*, config: SloTuiAssemblyConfigDAO) -> None:
        """Reject unsupported or unresolved configuration before downstream construction.

        WHAT: Defensively rechecks the closed scenario and absolute path invariant.
        WHO: run calls this as its first operation.
        WHEN: Before preferences, session construction, application construction, or runner startup.

        Args:
            config (SloTuiAssemblyConfigDAO): Candidate immutable assembly input.

        Raises:
            SloTuiAssemblyConfigurationError: If local interactive facts violate this boundary.
        """
        if config.environment_scenario != "textual_current":
            raise SloTuiAssemblyConfigurationError("unsupported Slo TUI environment scenario")
        if not config.workdir.is_absolute():
            raise SloTuiAssemblyConfigurationError("interactive workdir must be resolved and absolute")
        if config.workspace_file is not None and not config.workspace_file.is_absolute():
            raise SloTuiAssemblyConfigurationError("interactive workspace file must be resolved and absolute")

    def _build_promoted_session(self, *, config: SloTuiAssemblyConfigDAO) -> SloAgentSession:
        """Build and promote one lazy interactive session without invocation.

        WHAT: Sequences existing config construction, lazy session creation, and Slo promotion policy.
        WHO: run calls this after local configuration validation.
        WHEN: Before current application construction and before provider credentials or network activity.

        Args:
            config (SloTuiAssemblyConfigDAO): Validated closed-scenario interactive facts.

        Returns:
            SloAgentSession: Promoted lazy session ready for current SloTUI.

        Raises:
            SloTuiAssemblyConfigurationError: If a required factory returns no session configuration or session.
        """
        session_config: SessionConfigDAO | None = self._session_config_factory.build_config(config=config)
        if session_config is None:
            raise SloTuiAssemblyConfigurationError("session config factory returned no config")
        session: SloAgentSession | None = self._session_factory.build_session(config=session_config)
        if session is None:
            raise SloTuiAssemblyConfigurationError("session factory returned no session")
        OrchestratorSessionBootstrap.attach(session=session)
        return session
