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
from collections import deque
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
from config.timeout_resolver import positive_float_env, positive_int_env
from src.agents.model_catalog.prompt_clause import append_kimi_for_coding_clause
from src.cli.headless_events import HeadlessLifecycleEventDAO, emit_lifecycle_event

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

STDERR_TAIL_MAX_LINES: int = 50
"""Number of trailing stderr lines retained per child for failure diagnostics.

A child that dies before emitting any stdout terminal event (e.g. an invalid
model name or a provider rate-limit at startup) leaves an empty answer. The
retained stderr tail is surfaced as the failure answer so the orchestrator sees
the actual error instead of an empty string.
"""

STDERR_TAIL_MAX_CHARS: int = 4000
"""Upper bound on the stderr-tail text surfaced as a failure answer.

Bounds the size of the fallback answer so a verbose traceback cannot bloat the
``OrchestratorResultDAO`` JSON returned to the orchestrator LLM.
"""

STDERR_LINE_MAX_CHARS: int = 1000
"""Per-line clamp applied to each retained stderr line to bound memory."""

TERMINATE_GRACE_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_TERMINATE_GRACE_SECONDS",
    default=5.0,
)
"""Seconds between SIGTERM and SIGKILL in ``cancel()``.

Overridable via ``SLO_SUBAGENT_TERMINATE_GRACE_SECONDS``.
"""

HEADLESS_HEARTBEAT_STALE_MULTIPLIER: int = positive_int_env(
    primary_name="SLO_HEADLESS_HEARTBEAT_STALE_MULTIPLIER",
    default=3,
)
"""Recognized heartbeat intervals tolerated before a child is considered stale."""

CHILD_INACTIVITY_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS",
    alias_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT",
    default=7200.0,
)
"""Maximum silence tolerated from a child between stdout lines before it is declared hung.

This is a *liveness* bound, not a total-runtime budget: the clock resets on
every line the child emits, so a healthy long-running child that streams
events continuously is never killed, while a child that produces no output
at all (the classic ``readline()`` hang — a blocked subprocess waiting on an
operation that itself hung) surfaces as a timeout instead of wedging the
parent forever. Owned by the orchestrator; never set by the model.

Default is 7200 s (2 hours) to accommodate large-context LLM calls where
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
        _stderr_tail (deque[str]): Bounded ring buffer of the child's most recent
            stderr lines, surfaced as the failure answer when the child dies
            without emitting a terminal stdout event.
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
        self._stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_MAX_LINES)
        self._last_liveness_at: Optional[float] = None
        self._last_stdout_at: Optional[float] = None
        self._heartbeat_seconds: float = positive_float_env(
            primary_name="SLO_HEADLESS_HEARTBEAT_SECONDS",
            default=15.0,
        )
        self._failure_envelope: dict[str, object] = {}
        self._terminal_result_built: Optional[SubAgentResultDAO] = None

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
                        timeout=self._next_child_liveness_timeout_seconds(),
                    )
                except asyncio.TimeoutError as exc:
                    await self._cancel_stale_child_if_needed(
                        now_seconds=asyncio.get_running_loop().time(),
                    )
                    raise TimeoutError(self._liveness_timeout_message()) from exc
                if not raw:
                    return
                self._last_stdout_at = asyncio.get_running_loop().time()
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
                self._record_headless_heartbeat(raw=raw)
                line_text: str = raw.decode("utf-8", errors="replace").rstrip()
                if line_text:
                    self._stderr_tail.append(line_text[:STDERR_LINE_MAX_CHARS])
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
            self._capture_failure_envelope(event=event)

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

    def _record_headless_heartbeat(self, *, raw: bytes) -> bool:
        """Accept only a valid same-session status lifecycle record as liveness proof."""
        try:
            lifecycle: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO.model_validate_json(raw)
        except Exception:
            return False
        if lifecycle.kind != "headless_status" or lifecycle.session_id != self._session_id:
            return False
        self._last_liveness_at = asyncio.get_running_loop().time()
        return True

    def _heartbeat_is_stale(self, *, now_seconds: float) -> bool:
        """Return whether a previously healthy child missed the bounded heartbeat deadline."""
        if self._last_liveness_at is None:
            return False
        return now_seconds - self._last_liveness_at >= self._heartbeat_stale_seconds()

    def _heartbeat_stale_seconds(self) -> float:
        """Return the bounded heartbeat liveness interval for the active child."""
        return self._heartbeat_seconds * HEADLESS_HEARTBEAT_STALE_MULTIPLIER

    def _next_child_liveness_timeout_seconds(self) -> float:
        """Select the next stdout-read timeout from recognized heartbeat state."""
        if self._last_liveness_at is None:
            return CHILD_INACTIVITY_TIMEOUT_SECONDS
        elapsed: float = asyncio.get_running_loop().time() - self._last_liveness_at
        return max(0.001, min(CHILD_INACTIVITY_TIMEOUT_SECONDS, self._heartbeat_stale_seconds() - elapsed))

    def _liveness_timeout_message(self) -> str:
        """Return the safe timeout message for the current supervision deadline."""
        if self._heartbeat_is_stale(now_seconds=asyncio.get_running_loop().time()):
            return "sub-agent headless heartbeat became stale; treated as hung"
        return f"sub-agent produced no output for {CHILD_INACTIVITY_TIMEOUT_SECONDS:.0f}s; treated as hung"

    async def _cancel_stale_child_if_needed(self, *, now_seconds: float) -> None:
        """Cancel a child after a selected heartbeat or stdout liveness timeout.

        WHAT: Records a redacted stale-heartbeat envelope then performs cleanup.
        WHO: Called by the stdout supervisor after its selected read deadline.
        WHEN: Before the controlled timeout escapes to the process run owner.
        """
        if self._heartbeat_is_stale(now_seconds=now_seconds):
            self._failure_envelope = {
                "failure_code": "headless_heartbeat_stale",
                "partial_output_committed": None,
                "attempts": None,
                "safe_message": "Headless child heartbeat became stale; child was cancelled.",
            }
        await self.cancel()

    def _capture_failure_envelope(self, *, event: AgentStreamEventDAO) -> None:
        """Copy only valid typed stream-failure metadata from a terminal child event."""
        if event.kind != "run_failed":
            return
        metadata: dict[str, object] = event.metadata
        failure_code: object = metadata.get("failure_code")
        if failure_code not in {"provider_stream_disconnected", "provider_stream_interrupted"}:
            return
        self._failure_envelope = {
            "failure_code": failure_code,
            "partial_output_committed": metadata.get("partial_output_committed"),
            "attempts": metadata.get("attempts"),
            "safe_message": "Provider stream interrupted; inspect durable artifacts before continuing.",
        }

    def _terminal_result(self, *, exit_code: int) -> SubAgentResultDAO:
        """Map the child exit code and accumulated answer to a result DAO.

        Exit code semantics mirror ``HeadlessRunner``:
        ``0`` → ``completed``, ``2`` → ``aborted``, anything else → ``failed``.

        Args:
            exit_code (int): Child process exit code.

        Returns:
            SubAgentResultDAO: Terminal result DAO.
        """
        if self._terminal_result_built is not None:
            return self._terminal_result_built
        self._terminal_result_built = SubAgentResultDAO(
            task_id=self._task.task_id,
            session_id=self._session_id,
            status=self._status_for(exit_code=exit_code),  # type: ignore[arg-type]
            answer=self._resolve_answer(exit_code=exit_code),
            exit_code=exit_code,
            failure_code=self._failure_envelope.get("failure_code"),  # type: ignore[arg-type]
            partial_output_committed=self._failure_envelope.get("partial_output_committed"),  # type: ignore[arg-type]
            attempts=self._failure_envelope.get("attempts"),  # type: ignore[arg-type]
            safe_message=self._failure_envelope.get("safe_message"),  # type: ignore[arg-type]
        )
        return self._terminal_result_built

    def _status_for(self, *, exit_code: int) -> str:
        """Map a child exit code to its terminal status string.

        Args:
            exit_code (int): Child process exit code.

        Returns:
            str: ``"completed"`` for ``0``, ``"aborted"`` for ``2``, else
                ``"failed"``.
        """
        if exit_code == 0:
            return "completed"
        if exit_code == 2:
            return "aborted"
        return "failed"

    def _resolve_answer(self, *, exit_code: int) -> str:
        """Choose the result answer, falling back to the stderr tail on silent failures.

        A child that dies before emitting a terminal stdout event leaves
        ``_answer`` empty; without a fallback the orchestrator sees only an
        empty string and cannot diagnose the failure. When the child exited
        non-zero with no accumulated answer, surface its captured stderr tail
        (the actual error) instead.

        Args:
            exit_code (int): Child process exit code.

        Returns:
            str: The accumulated answer, or the stderr-tail fallback for a
                silent non-zero exit.
        """
        if self._answer:
            return self._answer
        if exit_code == 0:
            return self._answer
        return self._stderr_fallback_answer()

    def _stderr_fallback_answer(self) -> str:
        """Build a bounded failure answer from the retained stderr tail.

        Returns:
            str: A labelled, char-bounded stderr tail, or an empty string when
                no stderr was captured.
        """
        if not self._stderr_tail:
            return ""
        tail_text: str = "\n".join(self._stderr_tail)[-STDERR_TAIL_MAX_CHARS:]
        return f"child exited without an answer; stderr tail:\n{tail_text}"

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
        await self._await_termination_or_kill()

    async def _await_termination_or_kill(self) -> None:
        """Wait for SIGTERM, escalate once, and reap after SIGKILL.

        WHAT: Completes the cancellation protocol even when a child ignores SIGTERM.
        WHO: Called by ``cancel`` after it has sent the graceful signal.
        WHEN: Runs during parent abort and all timeout cleanup paths.
        """
        if self._proc is None:
            return
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=TERMINATE_GRACE_SECONDS)
            return
        except asyncio.TimeoutError:
            if self._proc.returncode is not None:
                return
        self._proc.kill()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=TERMINATE_GRACE_SECONDS)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("sub-agent did not exit after SIGKILL") from exc
