"""SubAgentProcess — manage one headless child ``slo run`` process.

One process wrapper is created per task by ``SubAgentPool._run_one``. It
spawns ``sys.executable -m src.cli run --json -p <prompt>`` via
``asyncio.create_subprocess_exec`` (venv-portable), reads its JSONL stdout
line by line, re-hydrates each line into an ``AgentStreamEventDAO``, tags it
with identity fields, updates the ``ProcessRegistry``, enforces the per-task
output cap, and supports graceful cancellation (SIGTERM → grace → SIGKILL).

Stderr is pumped concurrently with stdout to prevent pipe deadlock: a child
that writes to both stdout and stderr can stall indefinitely if the parent
only drains one pipe at a time and the other pipe's buffer fills up.

Sub-spec 01-sub-agents 01.d.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
from pathlib import Path
from typing import IO, Optional

_STDOUT_STREAM_LIMIT: int = 16 * 1024 * 1024  # 16 MB
"""Per-line read buffer limit for child process stdout.

The default ``asyncio.StreamReader`` limit is 64 KB. A child agent
writing a large ``run_completed`` event — for example, a finished spec
document with thousands of tokens — can easily exceed that in a single
JSON line, raising::

    ValueError: Separator is found, but chunk is longer than limit

Raising the limit to 16 MB accommodates the largest realistic single-turn
assistant output. The ``PER_TASK_OUTPUT_CAP`` (50 KB) separately bounds
the total forwarded bytes, so memory use is still bounded.
"""

from config.logger import log_error, log_info, log_warning
from config.timeout_resolver import positive_float_env
from src.agents.model_catalog.prompt_clause import append_kimi_for_coding_clause
from src.cli.headless_events import emit_lifecycle_event

from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = [
    "SubAgentProcess",
    "PER_TASK_OUTPUT_CAP",
    "TERMINATE_GRACE_SECONDS",
    "CHILD_INACTIVITY_TIMEOUT_SECONDS",
]


PER_TASK_OUTPUT_CAP: int = 512 * 1024
"""Maximum bytes forwarded from one child's stdout before non-terminal events are dropped.

Raised from 50 KB to 512 KB (sub-spec 54.a.2) so thinking streams and tool call
events are not truncated for agents doing significant intermediate work.
"""

TERMINATE_GRACE_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_TERMINATE_GRACE_SECONDS",
    default=5.0,
)
"""Seconds between SIGTERM and SIGKILL in ``cancel()``.

Overridable via ``SLO_SUBAGENT_TERMINATE_GRACE_SECONDS``.
"""

CHILD_INACTIVITY_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS",
    alias_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT",
    default=1800.0,
)
"""Maximum silence tolerated from a child between stdout lines before it is declared hung.

This is a *liveness* bound, not a total-runtime budget: the clock resets on
every line the child emits, so a healthy long-running child that streams
events continuously is never killed, while a child that produces no output
at all (the classic ``readline()`` hang — a blocked subprocess waiting on an
operation that itself hung) surfaces as a timeout instead of wedging the
parent forever. Owned by the orchestrator; never set by the model.

Default is 1800 s (30 minutes) to accommodate large-context LLM calls where
the time-to-first-token on a 100 KB+ prompt can exceed several minutes.

Overridable via ``SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS``
(alias ``SLO_SUBAGENT_INACTIVITY_TIMEOUT``).
"""


class SubAgentProcess:
    """Runs one ``slo run --json`` child process and relays its tagged event stream.

    ``SubAgentPool`` constructs one process per task. The process is single-use:
    ``run()`` spawns the child, streams stdout and stderr concurrently until the
    child exits, and returns the terminal ``SubAgentResultDAO``. Never raises into
    the pool — any failure is mapped to a ``failed`` result so a sibling process
    is never cancelled by this one.

    When ``parent_session_id`` and ``slo_home`` are supplied, raw stdout and
    stderr bytes are also written to capture files under:
    ``<slo_home>/sessions/history/<parent_session_id>/children/<session_id>/``

    Attributes:
        _task (SubAgentTaskDAO): The task this process executes.
        _session_id (str): Pre-assigned child session identifier used for tagging
            events and for the parent↔child history link.
        _model (Optional[str]): Effective model for the child; ``None`` lets
            the child resolve its own default.
        _relay (AgentEventSubscriber): Pool relay; every tagged child event is
            forwarded here.
        _registry (ProcessRegistry): Pool-owned registry; updated on each
            ``text_delta`` event and terminal state.
        _parent_session_id (Optional[str]): Orchestrator session id used to build
            the capture directory path. ``None`` disables capture file writing.
        _slo_home (Optional[Path]): Slo home directory root used with
            ``_parent_session_id`` to locate the capture directory.
        _system_prompt (str): Assembled system prompt for the child session; written
            to ``spawn_context.json`` so the visualizer can surface it.
        _proc (Optional[asyncio.subprocess.Process]): The spawned child process;
            set by ``run()`` after the subprocess is created.
        _forwarded_bytes (int): Running total of raw bytes relayed from stdout.
        _answer (str): Accumulated final answer from the child's terminal event.
    """

    def __init__(
        self,
        *,
        task: SubAgentTaskDAO,
        session_id: str,
        model: Optional[str],
        relay: AgentEventSubscriber,
        registry: ProcessRegistry,
        system_prompt: str = "",
        parent_session_id: Optional[str] = None,
        slo_home: Optional[Path] = None,
    ) -> None:
        """Bind the process wrapper to its task, identity, relay, and registry.

        Args:
            task (SubAgentTaskDAO): Task definition including prompt and optional cwd.
            session_id (str): Child session identifier pre-assigned by the pool.
            model (Optional[str]): Effective model name for the child process.
            relay (AgentEventSubscriber): Tagged-event relay from the pool.
            registry (ProcessRegistry): Pool-owned lifecycle registry.
            system_prompt (str): Assembled system prompt for the child session.
                Written to ``spawn_context.json`` for visualizer inspection.
                Defaults to empty string when not supplied (pre-54 compat).
            parent_session_id (Optional[str]): Orchestrator session id for capture
                file path construction. ``None`` disables capture writing.
            slo_home (Optional[Path]): Slo home directory. ``None`` disables
                capture writing.
        """
        self._task: SubAgentTaskDAO = task
        self._session_id: str = session_id
        self._model: Optional[str] = model
        self._relay: AgentEventSubscriber = relay
        self._registry: ProcessRegistry = registry
        self._system_prompt: str = system_prompt
        self._parent_session_id: Optional[str] = parent_session_id
        self._slo_home: Optional[Path] = slo_home
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._forwarded_bytes: int = 0
        self._answer: str = ""

    def _write_spawn_context(self) -> None:
        """Write spawn_context.json to the child capture directory.

        Uses an atomic temp-file + os.replace pattern so readers never see a
        partial file. Guarded by an existence check so a second call (e.g. in
        a retry scenario) does not overwrite the original record. Failures are
        caught and logged; they must not propagate into ``run()``.
        """
        from src.agents.slo_agent.orchestrator.context_dao import (  # noqa: PLC0415
            SpawnContextDAO,
            dump_json_bytes,
        )

        effective_prompt: str = append_kimi_for_coding_clause(
            prompt=self._task.prompt,
            model_name=self._model or "",
        )

        capture_dir: Optional[Path] = self._capture_dir()
        if capture_dir is None:
            return
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
            spawn_path: Path = capture_dir / "spawn_context.json"
            if spawn_path.exists():
                return
            context: SpawnContextDAO = SpawnContextDAO.build(
                task_id=self._task.task_id,
                prompt=effective_prompt,
                system_prompt=self._system_prompt,
                inactivity_timeout_seconds=CHILD_INACTIVITY_TIMEOUT_SECONDS,
                model=self._model,
                reasoning_level=self._task.reasoning_level,
                cwd=self._task.cwd,
            )
            data: bytes = dump_json_bytes(model=context)
            with tempfile.NamedTemporaryFile(dir=capture_dir, delete=False) as tmp:
                tmp.write(data)
                tmp_name: str = tmp.name
            os.replace(tmp_name, spawn_path)
        except OSError as exc:
            log_warning(
                msg="spawn_context_write_failed",
                task_id=self._task.task_id,
                session_id=self._session_id,
                error=str(exc),
            )

    def _build_argv(self) -> list[str]:
        """Build the headless child command line.

        Uses ``sys.executable -m src.cli`` rather than a bare ``slo`` on PATH
        so the child always runs under the same interpreter and virtualenv as
        the orchestrator in both dev and installed layouts.

        Returns:
            list[str]: Argv for ``create_subprocess_exec``.
        """
        effective_prompt: str = append_kimi_for_coding_clause(
            prompt=self._task.prompt,
            model_name=self._model or "",
        )
        argv: list[str] = [
            sys.executable,
            "-m",
            "src.cli",
            "run",
            "--json",
            "-p",
            effective_prompt,
        ]
        if self._model is not None:
            argv += ["--model", self._model]
        if self._task.cwd is not None:
            argv += ["--cwd", self._task.cwd]
        if self._task.reasoning_level is not None:
            argv += ["--reasoning", self._task.reasoning_level]
        if self._task.resume_session_reference is not None:
            argv += ["--resume", self._task.resume_session_reference]
        if self._task.session_id is not None:
            argv += ["--session-id", self._task.session_id]
        if self._task.enable_history is True:
            argv += ["--enable-history"]
        if self._task.system_prompt is not None:
            encoded: str = base64.b64encode(self._task.system_prompt.encode()).decode()
            argv += ["--system-prompt-b64", encoded]
        return argv

    def _capture_dir(self) -> Optional[Path]:
        """Return the capture directory for this child, or ``None`` when not configured.

        The directory is not created here; ``_open_capture_file`` creates it on
        first use.

        Returns:
            Optional[Path]: Absolute capture directory path, or ``None`` when
                either ``parent_session_id`` or ``slo_home`` is unset.
        """
        if self._parent_session_id is None or self._slo_home is None:
            return None
        return (
            self._slo_home / "sessions" / "history" / self._parent_session_id / "children" / self._session_id
        )

    def _open_capture_file(self, *, name: str) -> Optional[IO[bytes]]:
        """Open a capture file for appending, creating the directory tree as needed.

        Failures are suppressed — capture is best-effort and must never block
        the process from running.

        Args:
            name (str): File name within the capture directory (e.g. ``stdout.jsonl``).

        Returns:
            Optional[IO[bytes]]: Open binary file handle, or ``None`` on any
                failure or when capture is not configured.
        """
        capture_dir: Optional[Path] = self._capture_dir()
        if capture_dir is None:
            return None
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
            return (capture_dir / name).open("ab")
        except OSError:
            return None

    async def run(self) -> SubAgentResultDAO:
        """Spawn the child, stream its events, and return the terminal result.

        Stdout and stderr are pumped concurrently via ``asyncio.gather`` to
        prevent pipe deadlock: a child that writes to both pipes can stall
        indefinitely if the parent only drains one at a time and the other
        pipe buffer fills up. Never raises: a spawn or stream failure is caught
        here and mapped to a ``failed`` result so a sibling process is never
        cancelled by this one's exception.

        Returns:
            SubAgentResultDAO: Terminal result for this sub-agent task.
        """
        try:
            self._write_spawn_context()
            self._proc = await asyncio.create_subprocess_exec(
                *self._build_argv(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STDOUT_STREAM_LIMIT,
                cwd=self._task.cwd,
            )
            await asyncio.gather(
                self._pump_stdout(stream=self._proc.stdout),
                self._pump_stderr(stream=self._proc.stderr),
            )
            exit_code: int = await self._proc.wait()
            return self._terminal_result(exit_code=exit_code)
        except Exception as exc:
            log_error(
                msg="sub_agent_process_crashed",
                task_id=self._task.task_id,
                session_id=self._session_id,
                e=exc,
                stack_trace=True,
            )
            return SubAgentResultDAO(
                task_id=self._task.task_id,
                session_id=self._session_id,
                status="failed",
                answer=f"{type(exc).__name__}: {exc}",
                exit_code=1,
            )

    async def _pump_stdout(
        self,
        *,
        stream: Optional[asyncio.StreamReader],
    ) -> None:
        """Read JSONL lines from ``stream`` until EOF, handling each line.

        Opens a capture file for this child's stdout when the process is
        configured with ``parent_session_id`` and ``slo_home``. Lines are
        written to the capture file before being parsed and relayed.

        Args:
            stream (Optional[asyncio.StreamReader]): The child's stdout reader.
                ``None`` is handled defensively (should not occur in normal use).
        """
        if stream is None:
            return
        capture: Optional[IO[bytes]] = self._open_capture_file(name="stdout.jsonl")
        try:
            while True:
                try:
                    raw: bytes = await asyncio.wait_for(
                        stream.readline(),
                        timeout=CHILD_INACTIVITY_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError as exc:
                    # The child produced no output for the full inactivity window:
                    # treat it as hung, tear it down (SIGTERM → grace → SIGKILL),
                    # and surface the stall as a failure rather than blocking the
                    # parent on a wait that may never return.
                    await self.cancel()
                    raise TimeoutError(
                        f"sub-agent produced no output for "
                        f"{CHILD_INACTIVITY_TIMEOUT_SECONDS:.0f}s; treated as hung"
                    ) from exc
                if not raw:
                    return
                if capture is not None:
                    capture.write(raw)
                    capture.flush()
                await self._handle_line(raw=raw)
        finally:
            if capture is not None:
                capture.close()

    async def _pump_stderr(
        self,
        *,
        stream: Optional[asyncio.StreamReader],
    ) -> None:
        """Drain the child's stderr concurrently with stdout to prevent pipe deadlock.

        Reads stderr line-by-line until EOF. Each line is logged at INFO level
        and written to a capture file when configured. Unlike stdout, stderr
        lines are not relayed as ``AgentStreamEventDAO`` objects — they are
        diagnostic output only.

        Running this concurrently with ``_pump_stdout`` via ``asyncio.gather``
        prevents the deadlock that occurs when a child writes to both stdout and
        stderr and the parent only drains one pipe at a time.

        Args:
            stream (Optional[asyncio.StreamReader]): The child's stderr reader.
                ``None`` is handled defensively (should not occur in normal use).
        """
        if stream is None:
            return
        capture: Optional[IO[bytes]] = self._open_capture_file(name="stderr.jsonl")
        try:
            while True:
                raw: bytes = await stream.readline()
                if not raw:
                    return
                if capture is not None:
                    try:
                        capture.write(raw)
                        capture.flush()
                    except OSError:
                        capture = None  # stop writing after first IO failure
                line_text: str = raw.decode("utf-8", errors="replace").rstrip()
                log_info(
                    msg="sub_agent_stderr_line",
                    task_id=self._task.task_id,
                    session_id=self._session_id,
                    line=line_text[:500],
                )
                emit_lifecycle_event(
                    kind="headless_child_stderr",
                    session_id=self._session_id,
                    message=line_text[:500],
                    payload={"task_id": self._task.task_id},
                )
        finally:
            if capture is not None:
                capture.close()

    async def _handle_line(self, *, raw: bytes) -> None:
        """Parse one stdout line, accumulate state, and relay the tagged event.

        Malformed lines (non-JSON child diagnostics) are silently ignored.
        The per-task output cap bounds forwarded delta bytes; the terminal
        event is always forwarded regardless of the cap.

        Args:
            raw (bytes): One newline-terminated stdout line from the child.
        """
        try:
            event: AgentStreamEventDAO = AgentStreamEventDAO.model_validate_json(
                raw.decode("utf-8", errors="replace")
            )
        except Exception:
            return  # non-JSON child diagnostic line — ignore

        if event.is_terminal:
            self._answer = event.content or self._answer

        if self._forwarded_bytes >= PER_TASK_OUTPUT_CAP and not event.is_terminal:
            return  # cap reached; drop non-terminal events

        self._forwarded_bytes += len(raw)

        if event.kind == "text_delta" and event.delta:
            self._registry.update_last_text(
                session_id=self._session_id,
                text=event.delta,
            )

        tagged: AgentStreamEventDAO = event.model_copy(
            update={
                "sub_agent_id": self._session_id,
                "task_id": self._task.task_id,
            }
        )
        await self._relay(tagged)

    def _terminal_result(self, *, exit_code: int) -> SubAgentResultDAO:
        """Map the child exit code and accumulated answer to a result DAO.

        Exit code semantics mirror ``HeadlessRunner``:
        ``0`` → ``completed``, ``2`` → ``aborted``, anything else → ``failed``.

        Args:
            exit_code (int): Child process exit code.

        Returns:
            SubAgentResultDAO: Terminal result DAO.
        """
        if exit_code == 0:
            status = "completed"
        elif exit_code == 2:
            status = "aborted"
        else:
            status = "failed"
        return SubAgentResultDAO(
            task_id=self._task.task_id,
            session_id=self._session_id,
            status=status,  # type: ignore[arg-type]
            answer=self._answer,
            exit_code=exit_code,
        )

    async def cancel(self) -> None:
        """Terminate the child gracefully, escalating to SIGKILL after the grace period.

        Invoked by ``SubAgentPool.cancel_all()`` when the orchestrator aborts.
        Sends SIGTERM first, waits up to ``TERMINATE_GRACE_SECONDS``, then
        sends SIGKILL if the child is still running. No-op when no process
        is running or the process has already exited.
        """
        if self._proc is None or self._proc.returncode is not None:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(
                self._proc.wait(),
                timeout=TERMINATE_GRACE_SECONDS,
            )
        except asyncio.TimeoutError:
            self._proc.kill()
