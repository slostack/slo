"""Focused tests for fail-closed current Textual TUI assembly."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.assembly.dao import SloTuiAssemblyConfigDAO
from src.tui.assembly.factory import (
    DefaultSloTuiAssemblyFactory,
    SloTuiAssemblyConfigurationError,
)
from src.tui.assembly.ports import (
    SloAgentSessionFactory,
    SloClipboardPort,
    SloDetachedVisualizerLauncher,
    SloDetachedWorkflowRendererFactory,
    SloTuiApplicationFactory,
    SloTuiSessionFactory,
)
from src.tui.workflows.renderer import (
    DetachedWorkflowNoticeSink,
    DetachedWorkflowRenderer,
)


class _CallLog:
    """Record public collaborator calls without reaching runtime owners."""

    def __init__(self) -> None:
        """Create an empty ordered call record."""
        self.entries: list[str] = []

    def add(self, *, entry: str) -> None:
        """Append one public collaborator event."""
        self.entries.append(entry)


class _RecordingSessionConfigFactory:
    """Return a fixed session config while recording the assembly step."""

    def __init__(self, *, call_log: _CallLog, session_config: SessionConfigDAO) -> None:
        """Store the configuration supplied to the lazy session factory."""
        self._call_log: _CallLog = call_log
        self._session_config: SessionConfigDAO = session_config

    def build_config(self, *, config: SloTuiAssemblyConfigDAO) -> SessionConfigDAO:
        """Record config construction without credentials or providers."""
        del config
        self._call_log.add(entry="config")
        return self._session_config


class _RecordingSessionFactory:
    """Return a fake lazy session while recording construction only."""

    def __init__(self, *, call_log: _CallLog, session: SloAgentSession | None) -> None:
        """Store the configured fake session result."""
        self._call_log: _CallLog = call_log
        self._session: SloAgentSession | None = session

    def build_session(self, *, config: SessionConfigDAO) -> SloAgentSession | None:
        """Record lazy-session construction and return the configured result."""
        del config
        self._call_log.add(entry="session")
        return self._session


class _RecordingApplicationFactory:
    """Record application construction without starting Textual."""

    def __init__(self, *, call_log: _CallLog, application: SloTUI | None) -> None:
        """Store the configured fake application result."""
        self._call_log: _CallLog = call_log
        self._application: SloTUI | None = application

    def build_application(
        self,
        *,
        session: SloAgentSession,
        clipboard: SloClipboardPort,
        detached_workflow_renderer_factory: SloDetachedWorkflowRendererFactory,
        visualizer_launcher: SloDetachedVisualizerLauncher,
        session_factory: SloAgentSessionFactory,
    ) -> SloTUI | None:
        """Record explicit collaborator propagation and return the fake app."""
        del clipboard, detached_workflow_renderer_factory, session, session_factory, visualizer_launcher
        self._call_log.add(entry="application")
        return self._application


class _RecordingRunner:
    """Record the one synchronous app-run call."""

    def __init__(self, *, call_log: _CallLog) -> None:
        """Store the shared call log."""
        self._call_log: _CallLog = call_log
        self.applications: list[SloTUI] = []
        self.mouse_values: list[bool] = []

    def run(self, *, application: SloTUI, mouse: bool) -> None:
        """Record runner invocation without entering a terminal event loop."""
        self._call_log.add(entry="runner")
        self.applications.append(application)
        self.mouse_values.append(mouse)


class _NoopClipboard:
    """Satisfy the explicit clipboard port without side effects."""

    def copy(self, *, text: str) -> None:
        """Accept a selected string without external clipboard access."""
        del text


class _NoopLauncher:
    """Satisfy visualizer-launch collaboration without spawning a terminal."""

    def launch(self, *, parent_session_id: str) -> bool:
        """Return a deterministic no-launch result."""
        del parent_session_id
        return False


class _NoopRendererFactory:
    """Satisfy renderer creation; factory tests never mount an application."""

    def build_renderer(
        self,
        *,
        notice_sink: DetachedWorkflowNoticeSink,
        visualizer_launcher: SloDetachedVisualizerLauncher,
    ) -> DetachedWorkflowRenderer:
        """Reject accidental renderer construction in the assembly-only tests."""
        del notice_sink, visualizer_launcher
        raise AssertionError("application factory must own renderer construction")


def _config(*, workdir: Path) -> SloTuiAssemblyConfigDAO:
    """Build a valid closed production assembly configuration."""
    return SloTuiAssemblyConfigDAO(environment_scenario="textual_current", workdir=workdir)


def _factory(
    *,
    call_log: _CallLog,
    session: SloAgentSession | None,
    application: SloTUI | None,
) -> tuple[DefaultSloTuiAssemblyFactory, _RecordingRunner]:
    """Build the tested factory with only explicit recording collaborators."""
    session_config: SessionConfigDAO = SessionConfigDAO(workdir=Path("/").resolve())
    runner: _RecordingRunner = _RecordingRunner(call_log=call_log)
    factory: DefaultSloTuiAssemblyFactory = DefaultSloTuiAssemblyFactory(
        session_config_factory=cast(
            SloTuiSessionFactory,
            _RecordingSessionConfigFactory(call_log=call_log, session_config=session_config),
        ),
        session_factory=cast(
            SloAgentSessionFactory, _RecordingSessionFactory(call_log=call_log, session=session)
        ),
        application_factory=cast(
            SloTuiApplicationFactory,
            _RecordingApplicationFactory(call_log=call_log, application=application),
        ),
        clipboard=_NoopClipboard(),
        visualizer_launcher=_NoopLauncher(),
        detached_workflow_renderer_factory=_NoopRendererFactory(),
        runner=runner,
    )
    return factory, runner


class TestDefaultSloTuiAssemblyFactory:
    """Verify current Textual composition stays local and fail-closed."""

    def test_rejects_forged_scenario_before_constructing_any_collaborator(self, tmp_path: Path) -> None:
        """An invalid unvalidated scenario fails before config/session/app/runner calls."""
        call_log: _CallLog = _CallLog()
        factory, runner = _factory(call_log=call_log, session=None, application=None)
        forged_config: SloTuiAssemblyConfigDAO = _config(workdir=tmp_path).model_copy(
            update={"environment_scenario": "forged"}
        )

        with pytest.raises(SloTuiAssemblyConfigurationError, match="unsupported"):
            factory.run(config=forged_config)

        assert call_log.entries == []
        assert runner.applications == []

    def test_dao_rejects_relative_path_before_any_factory_can_construct_collaborators(self) -> None:
        """A relative input cannot pass config validation into an assembly factory."""
        with pytest.raises(ValidationError, match="resolved and absolute"):
            SloTuiAssemblyConfigDAO(environment_scenario="textual_current", workdir=Path("relative"))

    def test_runs_current_application_after_config_session_promotion_and_application(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The current assembly order is config, lazy session, bootstrap, app, runner."""
        call_log: _CallLog = _CallLog()
        session: SloAgentSession = cast(SloAgentSession, object())
        application: SloTUI = cast(SloTUI, object())
        factory, runner = _factory(call_log=call_log, session=session, application=application)

        def _record_attach(*, session: SloAgentSession) -> None:
            """Record bootstrap promotion without inspecting session internals."""
            assert session is not None
            call_log.add(entry="bootstrap")

        monkeypatch.setattr(
            "src.tui.assembly.factory.OrchestratorSessionBootstrap.attach",
            _record_attach,
        )

        factory.run(config=_config(workdir=tmp_path))

        assert call_log.entries == ["config", "session", "bootstrap", "application", "runner"]
        assert runner.applications == [application]
        assert runner.mouse_values == [True]

    def test_rejects_missing_session_before_bootstrap_application_or_runner(self, tmp_path: Path) -> None:
        """A faulty lazy-session factory stops assembly before app or provider work."""
        call_log: _CallLog = _CallLog()
        factory, runner = _factory(call_log=call_log, session=None, application=None)

        with pytest.raises(SloTuiAssemblyConfigurationError, match="session factory returned no session"):
            factory.run(config=_config(workdir=tmp_path))

        assert call_log.entries == ["config", "session"]
        assert runner.applications == []

    def test_rejects_missing_application_before_runner(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A faulty app factory cannot enter the runner or invoke the lazy session."""
        call_log: _CallLog = _CallLog()
        session: SloAgentSession = cast(SloAgentSession, object())
        factory, runner = _factory(call_log=call_log, session=session, application=None)
        monkeypatch.setattr(
            "src.tui.assembly.factory.OrchestratorSessionBootstrap.attach",
            lambda *, session: call_log.add(entry="bootstrap"),
        )

        with pytest.raises(
            SloTuiAssemblyConfigurationError, match="application factory returned no application"
        ):
            factory.run(config=_config(workdir=tmp_path))

        assert call_log.entries == ["config", "session", "bootstrap", "application"]
        assert runner.applications == []
