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


class _RecordingNotifier:
    """WorkflowNotifier stand-in recording every lifecycle call in order."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[str, dict]] = []

    async def started(self, *, brief_preview: str) -> None:
        """Record a started call.

        Args:
            brief_preview (str): Brief preview text.
        """
        self.calls.append(("started", {"brief_preview": brief_preview}))

    async def phase_update(self, *, phase_summary: str) -> None:
        """Record a phase_update call.

        Args:
            phase_summary (str): One-line phase digest.
        """
        self.calls.append(("phase_update", {"phase_summary": phase_summary}))

    async def completed(self, *, synthesis: str, result_json: str) -> None:
        """Record a completed call.

        Args:
            synthesis (str): Final answer text.
            result_json (str): Last spawn result JSON.
        """
        self.calls.append(("completed", {"synthesis": synthesis, "result_json": result_json}))

    async def failed(self, *, error: str) -> None:
        """Record a failed call.

        Args:
            error (str): Terminal error description.
        """
        self.calls.append(("failed", {"error": error}))


def _spawn_result_event(*, content: str) -> AgentStreamEventDAO:
    """Build one orchestrator-level ``spawn_sub_agents`` tool-result event.

    Args:
        content (str): Serialized ``OrchestratorResultDAO`` JSON.

    Returns:
        AgentStreamEventDAO: The tool-result event.
    """
    return AgentStreamEventDAO(
        kind="tool_result",
        tool_name="spawn_sub_agents",
        content=content,
    )


class TestHeadlessRunnerWorkflowNotifications:
    """The ``--notify-session`` event tap (spec 57.a.3)."""

    async def _run(
        self,
        *,
        tmp_path,
        events: list[AgentStreamEventDAO],
        notify_session_id: str | None,
        notifier: _RecordingNotifier | None,
        prompt: str = "run the workflow",
    ) -> int:
        """Drive one runner over scripted events with an injected notifier.

        Args:
            tmp_path: Pytest tmp path.
            events (list[AgentStreamEventDAO]): Scripted session events.
            notify_session_id (str | None): CLI flag value under test.
            notifier (_RecordingNotifier | None): Injected recorder.
            prompt (str, optional): Headless prompt text.

        Returns:
            int: Runner exit code.
        """
        runner: HeadlessRunner = HeadlessRunner(
            config=_make_config(tmp_path),
            notify_session_id=notify_session_id,
            notifier=notifier,  # type: ignore[arg-type]
        )
        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=events),
        ):
            return await runner.invoke(prompt=prompt)

    async def test_started_and_completed_bracket_the_run(self, tmp_path, capsys) -> None:
        """A notified run sends started first and completed last."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="text_delta", delta="working"),
            AgentStreamEventDAO(kind="run_completed", content="all done"),
        ]

        exit_code: int = await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        assert exit_code == 0
        assert [name for name, _ in notifier.calls] == ["started", "completed"]
        assert notifier.calls[0][1]["brief_preview"] == "run the workflow"
        assert notifier.calls[1][1]["synthesis"] == "all done"

    async def test_runner_taps_spawn_result_into_phase_update(self, tmp_path, capsys) -> None:
        """Each orchestrator-level spawn result produces exactly one phase update."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        spawn_json: str = json.dumps(
            {
                "mode": "single",
                "all_completed": True,
                "failed_task_ids": [],
                "results": [{"task_id": "phase-1"}],
            }
        )
        events: list[AgentStreamEventDAO] = [
            _spawn_result_event(content=spawn_json),
            AgentStreamEventDAO(kind="run_completed", content="synth"),
        ]

        await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        phase_calls: list[tuple[str, dict]] = [c for c in notifier.calls if c[0] == "phase_update"]
        assert len(phase_calls) == 1
        assert phase_calls[0][1]["phase_summary"] == "1 task(s), all_completed=True"
        completed_call: dict = notifier.calls[-1][1]
        assert completed_call["result_json"] == spawn_json

    async def test_phase_summary_lists_failed_task_ids(self, tmp_path, capsys) -> None:
        """Failed task ids surface in the phase digest."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        spawn_json: str = json.dumps(
            {
                "mode": "parallel",
                "all_completed": False,
                "failed_task_ids": ["phase-2"],
                "results": [{"task_id": "phase-1"}, {"task_id": "phase-2"}],
            }
        )
        events: list[AgentStreamEventDAO] = [
            _spawn_result_event(content=spawn_json),
            AgentStreamEventDAO(kind="run_completed", content="synth"),
        ]

        await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        phase_call: dict = next(kwargs for name, kwargs in notifier.calls if name == "phase_update")
        assert phase_call["phase_summary"] == "2 task(s), all_completed=False, failed=['phase-2']"

    async def test_sub_agent_events_never_trigger_phase_updates(self, tmp_path, capsys) -> None:
        """Relayed child events (sub_agent_id set) are not phase boundaries."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        child_tool_result: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="spawn_sub_agents",
            content="{}",
            sub_agent_id="child-1",
            task_id="t1",
        )
        events: list[AgentStreamEventDAO] = [
            child_tool_result,
            AgentStreamEventDAO(kind="run_completed", content="synth"),
        ]

        await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        assert [name for name, _ in notifier.calls] == ["started", "completed"]

    async def test_runner_run_failed_maps_to_failed(self, tmp_path, capsys) -> None:
        """A run_failed terminal event maps to ``notifier.failed``."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="run_failed", content="model exhausted"),
        ]

        exit_code: int = await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        assert exit_code == 1
        assert notifier.calls[-1][0] == "failed"
        assert "run_failed" in notifier.calls[-1][1]["error"]
        assert "model exhausted" in notifier.calls[-1][1]["error"]

    async def test_runner_run_aborted_maps_to_failed(self, tmp_path, capsys) -> None:
        """A run_aborted terminal event also maps to ``notifier.failed``."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="run_aborted"),
        ]

        exit_code: int = await self._run(
            tmp_path=tmp_path,
            events=events,
            notify_session_id="tui-1",
            notifier=notifier,
        )

        assert exit_code == 2
        assert notifier.calls[-1][0] == "failed"
        assert "run_aborted" in notifier.calls[-1][1]["error"]

    async def test_runner_without_flag_constructs_no_notifier(self, tmp_path, capsys) -> None:
        """Without ``--notify-session`` no notifier exists and nothing is recorded."""
        notifier: _RecordingNotifier = _RecordingNotifier()
        events: list[AgentStreamEventDAO] = [
            _spawn_result_event(content="{}"),
            AgentStreamEventDAO(kind="run_completed", content="done"),
        ]

        runner: HeadlessRunner = HeadlessRunner(
            config=_make_config(tmp_path),
            notify_session_id=None,
            notifier=notifier,  # type: ignore[arg-type]
        )
        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=events),
        ):
            exit_code: int = await runner.invoke(prompt="hi")

        assert exit_code == 0
        assert notifier.calls == []
        assert runner._notifier is None

    async def test_workflow_id_read_from_env_with_fallback(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        """The real notifier is built with SLO_WORKFLOW_ID, else 'wf-unknown'."""
        monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-3f2a")
        runner: HeadlessRunner = HeadlessRunner(
            config=_make_config(tmp_path),
            notify_session_id="tui-1",
        )

        built = runner._resolve_notifier(orchestrator_session_id="orch-1")
        assert built is not None
        assert built._workflow_id == "wf-3f2a"
        assert built._target_session_id == "tui-1"
        assert built._orchestrator_session_id == "orch-1"

        monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)
        fallback = runner._resolve_notifier(orchestrator_session_id="orch-1")
        assert fallback is not None
        assert fallback._workflow_id == "wf-unknown"


class TestHeadlessNotifyEndToEnd:
    """Integration: runner event tap → real WorkflowNotifier → real inbox store."""

    async def test_full_lifecycle_lands_in_target_inbox(self, tmp_path, capsys) -> None:
        """started + phase + completed messages land in the owner session's inbox."""
        from src.agents.slo_agent.history.inbox.store import SessionInboxStore
        from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier

        inbox_store: SessionInboxStore = SessionInboxStore(history_root=tmp_path / "history")
        notifier: WorkflowNotifier = WorkflowNotifier(
            target_session_id="tui-owner",
            orchestrator_session_id="orch-1",
            workflow_id="wf-3f2a",
            inbox_store=inbox_store,
        )
        spawn_json: str = json.dumps(
            {"mode": "single", "all_completed": True, "failed_task_ids": [], "results": [{}]}
        )
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="tool_result", tool_name="spawn_sub_agents", content=spawn_json),
            AgentStreamEventDAO(kind="run_completed", content="workflow synthesis"),
        ]
        runner: HeadlessRunner = HeadlessRunner(
            config=_make_config(tmp_path),
            notify_session_id="tui-owner",
            notifier=notifier,
        )

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=events),
        ):
            exit_code: int = await runner.invoke(prompt="run the workflow")

        pending = await inbox_store.list_pending(session_id="tui-owner")
        assert exit_code == 0
        assert [message.kind for message in pending] == [
            "workflow_started",
            "workflow_phase_update",
            "workflow_completed",
        ]
        assert [message.delivery_mode for message in pending] == [
            "context_note",
            "context_note",
            "chat_turn",
        ]
        assert all(message.payload["workflow_id"] == "wf-3f2a" for message in pending)
        assert "workflow synthesis" in pending[-1].text

    async def test_exploding_inbox_never_alters_exit_code_or_stdout(
        self, tmp_path, capsys
    ) -> None:
        """An inbox that raises on every call leaves the run's output untouched."""
        from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier

        class _ExplodingStore:
            async def enqueue(self, *, message):
                raise OSError("disk full")

        notifier: WorkflowNotifier = WorkflowNotifier(
            target_session_id="tui-owner",
            orchestrator_session_id="orch-1",
            workflow_id="wf-3f2a",
            inbox_store=_ExplodingStore(),  # type: ignore[arg-type]
        )
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="text_delta", delta="hello"),
            AgentStreamEventDAO(kind="run_completed", content="done"),
        ]
        runner: HeadlessRunner = HeadlessRunner(
            config=_make_config(tmp_path),
            notify_session_id="tui-owner",
            notifier=notifier,
        )

        with patch(
            "src.cli.headless.SloAgentSession.build",
            return_value=_make_session_mock(events=events),
        ):
            exit_code: int = await runner.invoke(prompt="hi")

        captured = capsys.readouterr()
        lines: list[str] = [line for line in captured.out.strip().split("\n") if line]
        assert exit_code == 0
        assert len(lines) == len(events)


class TestRunCommandNotifySessionFlag:
    """``slo run --notify-session`` parse surface (spec 57.a.3)."""

    def test_notify_session_flag_reaches_dispatch(self) -> None:
        """The parsed flag value is forwarded as ``notify_session_id``."""
        from typer.testing import CliRunner

        from src.cli.app import app

        runner: CliRunner = CliRunner()
        with patch(
            "src.cli.typer_dispatch.TyperDispatch.run_headless",
            return_value=0,
        ) as mock_run_headless:
            result = runner.invoke(
                app,
                ["run", "-p", "hello", "--notify-session", "tui-42"],
            )

        assert result.exit_code == 0
        assert mock_run_headless.call_args.kwargs["notify_session_id"] == "tui-42"

    def test_flag_absent_forwards_none(self) -> None:
        """Omitting the flag forwards ``notify_session_id=None`` (legacy behaviour)."""
        from typer.testing import CliRunner

        from src.cli.app import app

        runner: CliRunner = CliRunner()
        with patch(
            "src.cli.typer_dispatch.TyperDispatch.run_headless",
            return_value=0,
        ) as mock_run_headless:
            result = runner.invoke(app, ["run", "-p", "hello"])

        assert result.exit_code == 0
        assert mock_run_headless.call_args.kwargs["notify_session_id"] is None
