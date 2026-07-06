"""Tests for ``HeadlessRunner`` and the ``slo run`` CLI command (sub-spec 01-sub-agents 01.a)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.cli.headless import HeadlessRunner


def _make_config(tmp_path) -> SessionConfigDAO:
    """Build a minimal session config with history disabled.

    Args:
        tmp_path: Pytest temporary path fixture.

    Returns:
        SessionConfigDAO: Minimal config for headless tests.
    """
    return SessionConfigDAO(
        workdir=tmp_path,
        model_name="faux",
        enable_history=False,
    )


def _make_session_mock(events: list[AgentStreamEventDAO]) -> AsyncMock:
    """Build a mock ``SloAgentSession`` that dispatches ``events`` when invoked.

    Args:
        events (list[AgentStreamEventDAO]): Events to dispatch in order.

    Returns:
        AsyncMock: Configured mock session.
    """
    session_mock: AsyncMock = AsyncMock()
    session_mock.session_id = "test-session-id-mock"
    session_mock._subscribers: list = []
    session_mock.subscribe = lambda handler: session_mock._subscribers.append(handler)

    async def _fake_invoke(*, text: str):
        for ev in events:
            for subscriber in session_mock._subscribers:
                await subscriber(ev)
            yield ev

    session_mock.invoke = _fake_invoke
    return session_mock


class TestHeadlessRunnerEmitsJSONL:
    """``HeadlessRunner`` writes one valid JSON line per ``AgentStreamEventDAO``."""

    async def test_emits_one_json_line_per_event(
        self, tmp_path, capsys
    ) -> None:
        """Each event dispatched by the session appears as one JSON line on stdout."""
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="text_start"),
            AgentStreamEventDAO(kind="text_delta", delta="hello"),
            AgentStreamEventDAO(kind="text_end", content="hello"),
            AgentStreamEventDAO(kind="run_completed"),
        ]
        config: SessionConfigDAO = _make_config(tmp_path)
        runner: HeadlessRunner = HeadlessRunner(config=config)
        session_mock: AsyncMock = _make_session_mock(events=events)

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=session_mock,
        ):
            exit_code: int = await runner.invoke(prompt="hi")

        captured = capsys.readouterr()
        lines: list[str] = [
            line for line in captured.out.strip().split("\n") if line
        ]

        assert len(lines) == len(events)
        for line, event in zip(lines, events):
            parsed: dict = json.loads(line)
            assert parsed["kind"] == event.kind

        assert exit_code == 0

    async def test_each_line_is_independently_parseable(
        self, tmp_path, capsys
    ) -> None:
        """Every stdout line is a self-contained valid JSON object."""
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="run_completed", content="done"),
        ]
        runner: HeadlessRunner = HeadlessRunner(config=_make_config(tmp_path))

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=events),
        ):
            await runner.invoke(prompt="hi")

        captured = capsys.readouterr()
        for line in captured.out.strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "kind" in parsed


class TestHeadlessRunnerExitCodes:
    """Terminal event kind maps to the correct POSIX exit code."""

    @pytest.mark.parametrize(
        "terminal_kind,expected_exit",
        [
            ("run_completed", 0),
            ("run_aborted", 2),
            ("run_failed", 1),
        ],
    )
    async def test_exit_code_matches_terminal_kind(
        self,
        tmp_path,
        terminal_kind: str,
        expected_exit: int,
    ) -> None:
        """Exit code matches the documented mapping for each terminal event kind."""
        terminal_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind=terminal_kind,  # type: ignore[arg-type]
        )
        runner: HeadlessRunner = HeadlessRunner(config=_make_config(tmp_path))

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=[terminal_event]),
        ):
            exit_code: int = await runner.invoke(prompt="hi")

        assert exit_code == expected_exit

    async def test_default_exit_code_is_1_when_no_terminal_event(
        self, tmp_path
    ) -> None:
        """When no terminal event is dispatched the exit code defaults to 1 (failed)."""
        non_terminal_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="x",
        )
        runner: HeadlessRunner = HeadlessRunner(config=_make_config(tmp_path))

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=[non_terminal_event]),
        ):
            exit_code: int = await runner.invoke(prompt="hi")

        assert exit_code == 1


class TestHeadlessRunnerExitCodeHelper:
    """``HeadlessRunner._exit_code_for_terminal_kind`` unit tests."""

    def test_run_completed_maps_to_zero(self) -> None:
        """``run_completed`` returns exit code 0."""
        assert HeadlessRunner._exit_code_for_terminal_kind(kind="run_completed") == 0

    def test_run_aborted_maps_to_two(self) -> None:
        """``run_aborted`` returns exit code 2."""
        assert HeadlessRunner._exit_code_for_terminal_kind(kind="run_aborted") == 2

    def test_run_failed_maps_to_one(self) -> None:
        """``run_failed`` returns exit code 1."""
        assert HeadlessRunner._exit_code_for_terminal_kind(kind="run_failed") == 1

    def test_unknown_kind_maps_to_one(self) -> None:
        """Unrecognised terminal kind defaults to exit code 1."""
        assert HeadlessRunner._exit_code_for_terminal_kind(kind="unknown_kind") == 1


class TestSloRunCommand:
    """``slo run`` CLI command wires correctly to ``TyperDispatch.run_headless``."""

    def test_run_command_is_registered_in_app(self) -> None:
        """The ``run`` command is listed in the Typer app's command registry."""
        from src.cli.app import app

        command_names: set[str] = {cmd.name for cmd in app.registered_commands}

        assert "run" in command_names

    def test_run_command_delegates_to_run_headless(self, tmp_path) -> None:
        """Typer invokes ``TyperDispatch.run_headless`` with the parsed arguments."""
        from typer.testing import CliRunner

        from src.cli.app import app

        runner: CliRunner = CliRunner()

        with patch(
            "src.cli.typer_dispatch.TyperDispatch.run_headless",
            return_value=0,
        ) as mock_run_headless:
            result = runner.invoke(app, ["run", "-p", "hello world", "--json"])

        mock_run_headless.assert_called_once()
        call_kwargs: dict = mock_run_headless.call_args.kwargs
        assert call_kwargs["prompt"] == "hello world"
        assert call_kwargs["as_json"] is True
        assert result.exit_code == 0

    def test_run_command_propagates_non_zero_exit(self, tmp_path) -> None:
        """A non-zero exit code from ``run_headless`` is propagated via ``typer.Exit``."""
        from typer.testing import CliRunner

        from src.cli.app import app

        runner: CliRunner = CliRunner()

        with patch(
            "src.cli.typer_dispatch.TyperDispatch.run_headless",
            return_value=1,
        ):
            result = runner.invoke(app, ["run", "-p", "fail prompt"])

        assert result.exit_code == 1
