"""Tests for ``SubAgentProcess`` (sub-spec 01-sub-agents 01.d)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.process import (
    PER_TASK_OUTPUT_CAP,
    SubAgentProcess,
)
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_process(
    task_id: str = "t1",
    prompt: str = "Do something.",
    session_id: str = "s1",
    relayed: list[AgentStreamEventDAO] | None = None,
    parent_session_id: str | None = None,
    slo_home=None,
) -> tuple[SubAgentProcess, list[AgentStreamEventDAO]]:
    """Build a ``SubAgentProcess`` with a collector relay.

    Args:
        task_id (str): Task identifier.
        prompt (str): Task prompt.
        session_id (str): Child session id.
        relayed (list | None): External collector; a new list is used when ``None``.
        parent_session_id (str | None): Orchestrator session id for capture files.
        slo_home: Slo home directory for capture files.

    Returns:
        tuple[SubAgentProcess, list[AgentStreamEventDAO]]: Process and collector.
    """
    collected: list[AgentStreamEventDAO] = relayed if relayed is not None else []

    async def _relay(event: AgentStreamEventDAO) -> None:
        collected.append(event)

    registry: ProcessRegistry = ProcessRegistry()
    registry.register(
        task_id=task_id,
        session_id=session_id,
        task=SubAgentTaskDAO(task_id=task_id, prompt=prompt),
    )
    process: SubAgentProcess = SubAgentProcess(
        task=SubAgentTaskDAO(task_id=task_id, prompt=prompt),
        session_id=session_id,
        model=None,
        relay=_relay,
        registry=registry,
        parent_session_id=parent_session_id,
        slo_home=slo_home,
    )
    return process, collected


def _make_stream_reader(
    events: list[AgentStreamEventDAO],
) -> AsyncMock:
    """Build an ``asyncio.StreamReader``-like mock that returns serialised events.

    Args:
        events (list[AgentStreamEventDAO]): Events to emit as JSONL lines.

    Returns:
        AsyncMock: Reader whose ``readline`` side-effect yields one line per event
            and then an empty bytes sentinel.
    """
    lines: list[bytes] = [
        event.model_dump_json().encode() + b"\n" for event in events
    ] + [b""]
    reader: AsyncMock = AsyncMock()
    reader.readline = AsyncMock(side_effect=lines)
    return reader


# ── tests ─────────────────────────────────────────────────────────────────────


class TestSubAgentProcessArgvBuilding:
    """``_build_argv`` constructs the correct child command line."""

    def test_argv_includes_module_and_run_flags(self) -> None:
        """Argv always uses ``sys.executable -m src.cli run --json -p <prompt>``."""
        import sys

        process, _ = _make_process(prompt="Analyse files.")
        argv: list[str] = process._build_argv()

        assert argv[0] == sys.executable
        assert argv[1:4] == ["-m", "src.cli", "run"]
        assert "--json" in argv
        assert "-p" in argv
        assert "Analyse files." in argv

    def test_argv_includes_model_when_set(self) -> None:
        """``--model`` is appended when a model override is provided."""
        process, _ = _make_process()
        process._model = "claude-opus-4-5"

        argv: list[str] = process._build_argv()

        assert "--model" in argv
        assert "claude-opus-4-5" in argv

    def test_argv_includes_cwd_when_task_has_cwd(self) -> None:
        """``--cwd`` is appended when the task carries a working directory."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(task_id="t1", prompt="x", cwd="/tmp/work")

        argv: list[str] = process._build_argv()

        assert "--cwd" in argv
        assert "/tmp/work" in argv

    def test_argv_includes_reasoning_when_set(self) -> None:
        """``--reasoning`` is appended when the task carries a reasoning level."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(task_id="t1", prompt="x", reasoning_level="high")

        argv: list[str] = process._build_argv()

        assert "--reasoning" in argv
        assert "high" in argv

    def test_argv_omits_reasoning_when_absent(self) -> None:
        """``--reasoning`` is not present when ``reasoning_level`` is ``None``."""
        process, _ = _make_process()
        argv: list[str] = process._build_argv()

        assert "--reasoning" not in argv

    def test_argv_includes_resume_when_set(self) -> None:
        """``--resume`` is appended when the task carries a session reference."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(
            task_id="t1", prompt="x", resume_session_reference="ref-abc"
        )

        argv: list[str] = process._build_argv()

        assert "--resume" in argv
        assert "ref-abc" in argv

    def test_argv_omits_resume_when_absent(self) -> None:
        """``--resume`` is not present when ``resume_session_reference`` is ``None``."""
        process, _ = _make_process()
        argv: list[str] = process._build_argv()

        assert "--resume" not in argv

    def test_argv_includes_session_id_when_set(self) -> None:
        """``--session-id`` is appended when the task carries an explicit session id."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(task_id="t1", prompt="x", session_id="child-sess-01")

        argv: list[str] = process._build_argv()

        assert "--session-id" in argv
        assert "child-sess-01" in argv

    def test_argv_omits_session_id_when_absent(self) -> None:
        """``--session-id`` is not present when ``session_id`` is ``None``."""
        process, _ = _make_process()
        argv: list[str] = process._build_argv()

        assert "--session-id" not in argv

    def test_argv_includes_enable_history_when_true(self) -> None:
        """``--enable-history`` is appended when ``enable_history=True``."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(task_id="t1", prompt="x", enable_history=True)

        argv: list[str] = process._build_argv()

        assert "--enable-history" in argv

    def test_argv_omits_enable_history_when_false(self) -> None:
        """``--enable-history`` is absent when ``enable_history=False``."""
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(task_id="t1", prompt="x", enable_history=False)

        argv: list[str] = process._build_argv()

        assert "--enable-history" not in argv

    def test_argv_omits_enable_history_when_none(self) -> None:
        """``--enable-history`` is absent when ``enable_history=None``."""
        process, _ = _make_process()
        argv: list[str] = process._build_argv()

        assert "--enable-history" not in argv

    def test_argv_includes_system_prompt_b64_when_task_has_system_prompt(self) -> None:
        """``--system-prompt-b64`` is appended with the base64-encoded system prompt."""
        import base64

        prompt_text: str = "You are a focused test-writing agent."
        process, _ = _make_process()
        process._task = SubAgentTaskDAO(
            task_id="t1",
            prompt="x",
            system_prompt=prompt_text,
        )

        argv: list[str] = process._build_argv()

        assert "--system-prompt-b64" in argv
        b64_index: int = argv.index("--system-prompt-b64")
        encoded_arg: str = argv[b64_index + 1]
        decoded: str = base64.b64decode(encoded_arg.encode()).decode()
        assert decoded == prompt_text

    def test_argv_omits_system_prompt_b64_when_system_prompt_is_none(self) -> None:
        """``--system-prompt-b64`` is absent when ``system_prompt`` is ``None``."""
        process, _ = _make_process()
        argv: list[str] = process._build_argv()

        assert "--system-prompt-b64" not in argv


class TestSubAgentProcessInactivityTimeout:
    """A child that goes silent past the inactivity bound is declared hung."""

    async def test_pump_stdout_times_out_and_tears_down_a_silent_child(self) -> None:
        """A reader that never yields a line raises a ``TimeoutError`` and cancels the child."""
        import asyncio

        process, _ = _make_process()

        async def _never_returns() -> bytes:
            await asyncio.Event().wait()  # blocks forever — the classic hang
            return b""  # pragma: no cover

        reader: AsyncMock = AsyncMock()
        reader.readline = AsyncMock(side_effect=_never_returns)

        with (
            patch(
                "src.agents.slo_agent.orchestrator.process.CHILD_INACTIVITY_TIMEOUT_SECONDS",
                0.05,
            ),
            patch.object(process, "cancel", new=AsyncMock()) as mock_cancel,
        ):
            with pytest.raises(TimeoutError, match="no output"):
                await process._pump_stdout(stream=reader)

        mock_cancel.assert_awaited_once()


class TestSubAgentProcessHandleLine:
    """``_handle_line`` re-hydrates, tags, and relays events correctly."""

    async def test_rehydrates_and_tags_with_identity_fields(self) -> None:
        """Each relayed event carries ``sub_agent_id`` and ``task_id``."""
        process, collected = _make_process(task_id="t1", session_id="s1")
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="hello",
        )

        await process._handle_line(raw=event.model_dump_json().encode() + b"\n")

        assert len(collected) == 1
        assert collected[0].sub_agent_id == "s1"
        assert collected[0].task_id == "t1"

    async def test_non_json_lines_are_silently_ignored(self) -> None:
        """Non-JSON stdout lines (child diagnostics) do not raise and produce no event."""
        process, collected = _make_process()

        await process._handle_line(raw=b"this is not json\n")

        assert len(collected) == 0

    async def test_output_cap_drops_non_terminal_events(self) -> None:
        """Non-terminal events are dropped once ``_forwarded_bytes >= PER_TASK_OUTPUT_CAP``."""
        process, collected = _make_process()
        process._forwarded_bytes = PER_TASK_OUTPUT_CAP + 1

        delta_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="x",
        )
        await process._handle_line(
            raw=delta_event.model_dump_json().encode() + b"\n"
        )

        assert len(collected) == 0

    async def test_terminal_event_always_relayed_past_cap(self) -> None:
        """Terminal events are always forwarded regardless of the output cap."""
        process, collected = _make_process()
        process._forwarded_bytes = PER_TASK_OUTPUT_CAP + 1

        terminal_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="run_completed",
            content="done",
        )
        await process._handle_line(
            raw=terminal_event.model_dump_json().encode() + b"\n"
        )

        assert len(collected) == 1
        assert collected[0].kind == "run_completed"

    async def test_text_delta_updates_registry_last_text(self) -> None:
        """``text_delta`` events with a non-empty ``delta`` update the registry."""
        process, _ = _make_process(session_id="s1")
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="progress text",
        )

        await process._handle_line(raw=event.model_dump_json().encode() + b"\n")

        entry = process._registry.get(session_id="s1")
        assert entry is not None
        assert entry.last_text == "progress text"

    async def test_terminal_event_sets_answer(self) -> None:
        """A terminal event's ``content`` is captured in ``_answer``."""
        process, _ = _make_process()
        terminal_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="run_completed",
            content="final answer",
        )

        await process._handle_line(
            raw=terminal_event.model_dump_json().encode() + b"\n"
        )

        assert process._answer == "final answer"


class TestSubAgentProcessTerminalResult:
    """``_terminal_result`` maps exit codes to ``SubAgentResultDAO``."""

    def test_exit_zero_maps_to_completed(self) -> None:
        """Exit code 0 produces ``status='completed'``."""
        process, _ = _make_process()
        process._answer = "done"

        result = process._terminal_result(exit_code=0)

        assert result.status == "completed"
        assert result.answer == "done"
        assert result.exit_code == 0

    def test_exit_two_maps_to_aborted(self) -> None:
        """Exit code 2 produces ``status='aborted'``."""
        process, _ = _make_process()

        result = process._terminal_result(exit_code=2)

        assert result.status == "aborted"

    def test_non_zero_non_two_maps_to_failed(self) -> None:
        """Any exit code other than 0 or 2 produces ``status='failed'``."""
        process, _ = _make_process()

        result = process._terminal_result(exit_code=1)

        assert result.status == "failed"


class TestSubAgentProcessRunFailureIsolation:
    """``run()`` never raises — failures become ``failed`` results."""

    async def test_spawn_failure_returns_failed_result(self) -> None:
        """An ``OSError`` during subprocess spawn yields a ``failed`` result."""
        process, _ = _make_process()

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("spawn failed"),
        ):
            result = await process.run()

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "OSError" in result.answer


class TestWriteSpawnContext:
    """``_write_spawn_context`` persistence behaviour."""

    def test_write_spawn_context_creates_file(self, tmp_path: Path) -> None:
        """Creating spawn_context.json persists task and system prompt details."""
        from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO

        slo_home: Path = tmp_path / "slo_home"
        process, _ = _make_process(
            task_id="task-x",
            prompt="Do something useful.",
            session_id="child-1",
            parent_session_id="parent-1",
            slo_home=slo_home,
        )
        process._system_prompt = "test-sys-prompt"

        process._write_spawn_context()

        spawn_path: Path = (
            slo_home
            / "sessions"
            / "history"
            / "parent-1"
            / "children"
            / "child-1"
            / "spawn_context.json"
        )
        assert spawn_path.exists()
        ctx = SpawnContextDAO.model_validate_json(spawn_path.read_bytes())
        assert ctx.task_id == "task-x"
        assert ctx.prompt == "Do something useful."
        assert ctx.system_prompt == "test-sys-prompt"

    def test_write_spawn_context_is_idempotent(self, tmp_path: Path) -> None:
        """Second call leaves the existing spawn_context.json unchanged."""
        slo_home: Path = tmp_path / "slo_home"
        process, _ = _make_process(
            task_id="task-y",
            prompt="Compute results.",
            session_id="child-2",
            parent_session_id="parent-2",
            slo_home=slo_home,
        )
        process._system_prompt = "prompt-one"

        process._write_spawn_context()
        spawn_path: Path = (
            slo_home
            / "sessions"
            / "history"
            / "parent-2"
            / "children"
            / "child-2"
            / "spawn_context.json"
        )
        first_bytes: bytes = spawn_path.read_bytes()

        process._write_spawn_context()
        second_bytes: bytes = spawn_path.read_bytes()

        assert first_bytes == second_bytes

    def test_write_spawn_context_handles_oserror(self, tmp_path: Path) -> None:
        """OSError while creating directories logs a warning and does not raise."""
        slo_home: Path = tmp_path / "slo_home"
        process, _ = _make_process(
            task_id="task-z",
            prompt="Investigate failure.",
            session_id="child-3",
            parent_session_id="parent-3",
            slo_home=slo_home,
        )
        process._system_prompt = "sys"

        with (
            patch("pathlib.Path.mkdir", side_effect=OSError("disk full")),
            patch("src.agents.slo_agent.orchestrator.process.log_warning") as mock_warning,
        ):
            process._write_spawn_context()

        mock_warning.assert_called_once()

    def test_output_cap_increased(self) -> None:
        """PER_TASK_OUTPUT_CAP matches the 512 KiB specification."""
        assert PER_TASK_OUTPUT_CAP == 512 * 1024


class TestSubAgentProcessPumpStdout:
    """``_pump_stdout`` reads lines until EOF."""

    async def test_processes_all_lines_until_eof(self) -> None:
        """Every JSONL line is handled; EOF sentinel (empty bytes) stops the loop."""
        events: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(kind="text_delta", delta="a"),
            AgentStreamEventDAO(kind="run_completed", content="ok"),
        ]
        process, collected = _make_process()
        reader: AsyncMock = _make_stream_reader(events=events)

        await process._pump_stdout(stream=reader)

        assert len(collected) == 2

    async def test_none_stream_is_a_noop(self) -> None:
        """``_pump_stdout(stream=None)`` returns immediately without raising."""
        process, collected = _make_process()

        await process._pump_stdout(stream=None)

        assert len(collected) == 0


class TestSubAgentProcessCancel:
    """``cancel()`` sends SIGTERM and escalates to SIGKILL after grace period."""

    async def test_cancel_calls_terminate_on_running_process(self) -> None:
        """``cancel()`` calls ``terminate()`` when the child is running."""
        process, _ = _make_process()
        mock_proc: MagicMock = MagicMock()
        mock_proc.returncode = None
        mock_proc.wait = AsyncMock(return_value=0)
        process._proc = mock_proc

        await process.cancel()

        mock_proc.terminate.assert_called_once()

    async def test_cancel_is_noop_when_no_process(self) -> None:
        """``cancel()`` does nothing and does not raise when ``_proc`` is ``None``."""
        process, _ = _make_process()

        await process.cancel()  # no exception expected

    async def test_cancel_is_noop_when_process_already_exited(self) -> None:
        """``cancel()`` is a no-op when ``returncode`` is already set."""
        process, _ = _make_process()
        mock_proc: MagicMock = MagicMock()
        mock_proc.returncode = 0
        process._proc = mock_proc

        await process.cancel()

        mock_proc.terminate.assert_not_called()


class TestSubAgentProcessStreamLimit:
    """``_STDOUT_STREAM_LIMIT`` prevents ``ValueError`` on large JSON lines.

    Regression for the ``ValueError: Separator is found, but chunk is longer
    than limit`` failure that occurred when a child wrote a ``run_completed``
    event whose JSON exceeded the default ``asyncio.StreamReader`` limit of
    64 KB (e.g., a finished spec document with thousands of tokens).
    """

    def test_stdout_stream_limit_exceeds_default_asyncio_limit(self) -> None:
        """``_STDOUT_STREAM_LIMIT`` must be larger than asyncio's 64 KB default."""
        from src.agents.slo_agent.orchestrator.process import _STDOUT_STREAM_LIMIT

        default_asyncio_limit: int = 65536  # asyncio.StreamReader default
        assert _STDOUT_STREAM_LIMIT > default_asyncio_limit

    def test_stdout_stream_limit_is_at_least_1mb(self) -> None:
        """``_STDOUT_STREAM_LIMIT`` is at least 1 MB to accommodate large answers."""
        from src.agents.slo_agent.orchestrator.process import _STDOUT_STREAM_LIMIT

        assert _STDOUT_STREAM_LIMIT >= 1 * 1024 * 1024

    async def test_handle_line_processes_large_terminal_event(self) -> None:
        """A terminal event whose JSON exceeds 64 KB is handled without raising."""
        process, collected = _make_process()

        # Build a run_completed event with a large answer (> 64 KB)
        large_answer: str = "A" * 100_000  # 100 KB of content
        large_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="run_completed",
            content=large_answer,
        )
        raw: bytes = large_event.model_dump_json().encode() + b"\n"

        # Must not raise — the fix ensures the stream reader limit is 16 MB
        await process._handle_line(raw=raw)

        assert len(collected) == 1
        assert collected[0].kind == "run_completed"
        assert collected[0].content == large_answer

    async def test_handle_line_processes_large_text_delta_within_cap(self) -> None:
        """A large ``text_delta`` line within the stream limit is relayed correctly."""
        process, collected = _make_process()

        # Build a text_delta just under the forwarding cap
        delta_text: str = "B" * 1000
        delta_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta=delta_text,
        )
        raw: bytes = delta_event.model_dump_json().encode() + b"\n"

        await process._handle_line(raw=raw)

        assert len(collected) == 1
        assert collected[0].delta == delta_text

    def test_create_subprocess_exec_called_with_limit(self) -> None:
        """``run()`` passes ``limit=_STDOUT_STREAM_LIMIT`` to ``create_subprocess_exec``.

        Verifies the subprocess is created with the expanded buffer, not the
        64 KB default that caused the ``ValueError`` in production.
        """
        import asyncio
        import inspect

        from src.agents.slo_agent.orchestrator.process import (
            SubAgentProcess,
            _STDOUT_STREAM_LIMIT,
        )

        # Inspect the source to confirm `limit=` is passed in the call.
        # This is a static check since actually spawning a subprocess in a
        # unit test is fragile — the integration path is covered by test_process.py's
        # spawn_failure test.
        src = inspect.getsource(SubAgentProcess.run)
        assert "limit=_STDOUT_STREAM_LIMIT" in src, (
            "SubAgentProcess.run() must pass limit=_STDOUT_STREAM_LIMIT to "
            "create_subprocess_exec to prevent ValueError on large JSON lines"
        )


class TestSubAgentProcessPumpStderr:
    """``_pump_stderr`` drains stderr concurrently with stdout."""

    async def test_reads_all_stderr_lines_until_eof(self) -> None:
        """``_pump_stderr`` reads every line until the EOF sentinel."""
        process, _ = _make_process()
        lines: list[bytes] = [b"line one\n", b"line two\n", b""]
        reader: AsyncMock = AsyncMock()
        reader.readline = AsyncMock(side_effect=lines)

        with patch("config.logger.log_info"):
            await process._pump_stderr(stream=reader)

        assert reader.readline.call_count == 3  # two lines + EOF

    async def test_none_stream_is_a_noop(self) -> None:
        """``_pump_stderr(stream=None)`` returns immediately without raising."""
        process, _ = _make_process()

        await process._pump_stderr(stream=None)  # no exception expected

    async def test_logs_each_stderr_line(self) -> None:
        """Each stderr line is passed to ``log_info`` truncated to 500 chars."""
        process, _ = _make_process()
        reader: AsyncMock = AsyncMock()
        reader.readline = AsyncMock(side_effect=[b"child diagnostic\n", b""])

        with patch("src.agents.slo_agent.orchestrator.process.log_info") as mock_log:
            await process._pump_stderr(stream=reader)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["line"] == "child diagnostic"

    async def test_writes_lines_to_capture_file_when_configured(
        self, tmp_path: pytest.MonkeyPatch
    ) -> None:
        """Stderr lines are written to ``stderr.jsonl`` in the capture directory."""
        from pathlib import Path

        slo_home: Path = tmp_path / "slo_home"  # type: ignore[assignment]
        process, _ = _make_process(
            session_id="child-sess",
            parent_session_id="parent-sess",
            slo_home=slo_home,
        )
        reader: AsyncMock = AsyncMock()
        reader.readline = AsyncMock(side_effect=[b"error: boom\n", b""])

        with patch("src.agents.slo_agent.orchestrator.process.log_info"):
            await process._pump_stderr(stream=reader)

        capture_file = (
            slo_home / "sessions" / "history" / "parent-sess" / "children" / "child-sess" / "stderr.jsonl"
        )
        assert capture_file.exists()
        assert capture_file.read_bytes() == b"error: boom\n"


class TestSubAgentProcessCaptureFiles:
    """``_capture_dir`` and ``_open_capture_file`` resolve paths correctly."""

    def test_capture_dir_returns_none_when_parent_session_id_absent(self) -> None:
        """No capture directory when ``parent_session_id`` is not configured."""
        process, _ = _make_process()

        assert process._capture_dir() is None

    def test_capture_dir_returns_none_when_slo_home_absent(self) -> None:
        """No capture directory when ``slo_home`` is not configured."""
        process, _ = _make_process(parent_session_id="p1")

        assert process._capture_dir() is None

    def test_capture_dir_returns_expected_path(self, tmp_path) -> None:
        """Capture directory follows ``<slo_home>/sessions/history/<parent>/<child>``."""
        from pathlib import Path

        slo_home: Path = tmp_path / "slo_home"
        process, _ = _make_process(
            session_id="child-abc",
            parent_session_id="parent-xyz",
            slo_home=slo_home,
        )

        capture_dir = process._capture_dir()

        assert capture_dir == (
            slo_home / "sessions" / "history" / "parent-xyz" / "children" / "child-abc"
        )

    def test_open_capture_file_creates_directory_and_file(self, tmp_path) -> None:
        """``_open_capture_file`` creates the directory tree and returns a writable handle."""
        from pathlib import Path

        slo_home: Path = tmp_path / "slo_home"
        process, _ = _make_process(
            session_id="child-abc",
            parent_session_id="parent-xyz",
            slo_home=slo_home,
        )

        handle = process._open_capture_file(name="stdout.jsonl")
        assert handle is not None
        handle.write(b"test\n")
        handle.close()

        expected = (
            slo_home / "sessions" / "history" / "parent-xyz" / "children" / "child-abc" / "stdout.jsonl"
        )
        assert expected.exists()
        assert expected.read_bytes() == b"test\n"

    def test_open_capture_file_returns_none_when_not_configured(self) -> None:
        """``_open_capture_file`` returns ``None`` when capture is not configured."""
        process, _ = _make_process()

        assert process._open_capture_file(name="stdout.jsonl") is None


class TestSubAgentProcessEnvConfigurableTimeouts:
    """``TERMINATE_GRACE_SECONDS`` and ``CHILD_INACTIVITY_TIMEOUT_SECONDS`` read from env."""

    def test_terminate_grace_seconds_uses_primary_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SLO_SUBAGENT_TERMINATE_GRACE_SECONDS`` overrides the default."""
        monkeypatch.setenv("SLO_SUBAGENT_TERMINATE_GRACE_SECONDS", "15.0")

        import importlib
        import src.agents.slo_agent.orchestrator.process as proc_mod
        importlib.reload(proc_mod)

        assert proc_mod.TERMINATE_GRACE_SECONDS == 15.0

        # Restore original module-level value for other tests
        importlib.reload(proc_mod)

    def test_child_inactivity_timeout_reads_primary_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`` overrides the default."""
        monkeypatch.setenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", "600.0")
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT", raising=False)

        import importlib
        import src.agents.slo_agent.orchestrator.process as proc_mod
        importlib.reload(proc_mod)

        assert proc_mod.CHILD_INACTIVITY_TIMEOUT_SECONDS == 600.0

        importlib.reload(proc_mod)

    def test_child_inactivity_timeout_reads_alias_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SLO_SUBAGENT_INACTIVITY_TIMEOUT`` (legacy alias) is honoured when primary is absent."""
        monkeypatch.delenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT", "900.0")

        import importlib
        import src.agents.slo_agent.orchestrator.process as proc_mod
        importlib.reload(proc_mod)

        assert proc_mod.CHILD_INACTIVITY_TIMEOUT_SECONDS == 900.0

        importlib.reload(proc_mod)


class TestSubAgentProcessRunConcurrentPumping:
    """``run()`` pumps stdout and stderr concurrently."""

    def test_run_uses_asyncio_gather_for_concurrent_pump(self) -> None:
        """``run()`` must call ``asyncio.gather`` to pump stdout and stderr together.

        A static source-inspection confirms the concurrent pattern rather than
        the sequential ``await pump_stdout(); stderr.read()`` that caused
        pipe deadlock.
        """
        import inspect
        from src.agents.slo_agent.orchestrator.process import SubAgentProcess

        src = inspect.getsource(SubAgentProcess.run)
        assert "asyncio.gather" in src, (
            "SubAgentProcess.run() must use asyncio.gather to pump stdout and "
            "stderr concurrently and prevent pipe deadlock"
        )
        assert "_pump_stderr" in src, (
            "SubAgentProcess.run() must call _pump_stderr for concurrent stderr draining"
        )
