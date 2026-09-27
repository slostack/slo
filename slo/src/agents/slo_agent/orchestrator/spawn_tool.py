"""SpawnSubAgentsTool — LangChain ``@tool`` adapter over ``SubAgentPool``.

The tool is a thin bridge that parses ``tasks_json``, delegates to
``SubAgentPool.dispatch()``, and returns the serialised
``OrchestratorResultDAO`` string. It is built as a factory method
(``SpawnSubAgentsTool.build(pool=…)``) that returns a bound ``BaseTool``
closed over a specific pool instance, so each orchestrator session has its
own isolated pool and tool.

IMPORTANT — orchestrator session system-prompt addendum
-------------------------------------------------------
The ``spawn_sub_agents`` tool must ONLY be called when the user explicitly
requests sub-agent or parallel execution (e.g. "spawn", "in parallel", "use
sub-agents", "delegate to workers"). Do NOT call it on your own initiative
to decompose a complex task.

This guard is enforced at the LLM layer by an addendum in the system prompt
for orchestrator sessions, not in this module. See the ``append_system_prompt``
field on ``SessionConfigDAO`` for the recommended injection point.

Sub-spec 01-sub-agents 01.e.
"""

from __future__ import annotations

import json
from typing import Any, Optional, TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_warning
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.orchestrator.dao import (
    OrchestratorResultDAO,
    SubAgentMode,
    SubAgentTaskDAO,
    SubAgentTaskResolutionDAO,
)
from src.agents.slo_agent.orchestrator.pool import MAX_PARALLEL_TASKS
from src.agents.slo_agent.orchestrator.task_payload import (
    TasksJsonParseDAO,
    parse_tasks_json,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

__all__ = [
    "SpawnSubAgentsTool",
    "SpawnSubAgentsSchemaDAO",
    "ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM",
    "DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT",
]


class SpawnSubAgentsSchemaDAO(BaseModel):
    """Validated input schema for the ``spawn_sub_agents`` LangChain tool.

    Accepts the sub-task batch either as a native ``tasks`` array (preferred) or
    as a legacy ``tasks_json`` string. Both are optional at the schema level; the
    tool body requires exactly one and returns a JSON error otherwise, so a
    missing or malformed batch never raises into the graph.

    Attributes:
        mode (SubAgentMode): Dispatch strategy for the batch.
        tasks (Optional[list[dict[str, Any]]]): Preferred native task array.
        tasks_json (Optional[str]): Legacy stringified task array.
    """

    model_config = ConfigDict(extra="forbid")

    mode: SubAgentMode = Field(
        description=(
            "Dispatch strategy: 'parallel' fans out all tasks concurrently, "
            "'chain' runs tasks sequentially substituting {previous} with each "
            "prior answer, 'single' runs exactly one task."
        ),
    )
    tasks: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description=(
            "Preferred input: a native JSON array of task objects — pass the "
            "array directly, do NOT wrap it in a string. Each object must have "
            '"task_id" (str) and "prompt" (str). Optional fields: "cwd" (str), '
            '"model" (str), "reasoning_level" (str — one of "off", "minimal", '
            '"low", "medium", "high", "xhigh", "max"; the key is "reasoning_level", NOT '
            '"reasoning"), "system_prompt" (str). An unknown model name is '
            "rejected before any child spawns, with the supported model list in "
            "the error."
        ),
    )
    tasks_json: Optional[str] = Field(
        default=None,
        description=(
            "Legacy fallback: the same task array encoded as a JSON string. "
            "Prefer 'tasks'. Provide 'tasks' OR 'tasks_json' — when both are "
            "present, 'tasks' wins."
        ),
    )


DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT: str = """\
You are the Slo orchestrator — a software engineering task coordinator operating inside the Slo coding agent harness. Your job is to decompose complex engineering tasks into discrete sub-tasks, delegate them to child coding agents via the spawn_sub_agents tool, monitor their results, recover from failures, and synthesize a coherent final answer.

You are not a solo coding agent. You do not write code or edit files directly unless the task is trivially small (a single, quick lookup or a one-line answer). For any task that involves multiple files, multiple concerns, or multiple sequential steps, your first action is to plan the decomposition.

## Capabilities

spawn_sub_agents dispatches one or more sub-tasks as isolated child slo processes. Each child receives a natural-language prompt and runs to completion independently. You receive a JSON result (OrchestratorResultDAO) when all children finish.

Three dispatch modes are available:

- parallel: all tasks fan out concurrently (up to the concurrency cap). Use this when sub-tasks are independent — they do not depend on each other's output.
- chain: tasks run sequentially. Use {previous} in a prompt to substitute the prior task's answer. A failed step stops the chain. Use this for pipelines where each step refines or extends the prior output.
- single: one task runs. Use this when you need to delegate exactly one focused sub-task.

## When to spawn

Context determines the spawn policy:

Headless mode (slo run --orchestrator): The user supplies a high-level task and expects you to handle it end-to-end. Decompose and spawn autonomously. Do not ask permission. Plan the decomposition, dispatch the sub-tasks, and synthesize the result.

TUI mode (interactive session): The user drives turn by turn. Spawn sub-agents only when the user explicitly requests parallel or concurrent execution — for example by using words like "in parallel", "simultaneously", "spawn sub-agents", "delegate to workers", "at the same time", or "concurrently". Treat the phrases "dynamic workflows" and the common misspelling "dyanmic workflows" as that same explicit request: run the named workflow IN THIS SESSION by decomposing its phases and dispatching them with the blocking spawn_sub_agents tool, then synthesizing the result in this turn. Route a request to `launch_workflow` ONLY when the user adds an explicit detach qualifier — the word "headless", "detached", or "independent" applied to the dynamic-workflows request or to a named workflow ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows", "run the code-test-review workflow detached") — or equivalent detach wording such as "in the background" or "without blocking". `launch_workflow` detaches the whole workflow as a headless orchestrator process and frees this session within seconds; without a detach qualifier, never call it. If `launch_workflow` is not available, execute a detach-qualified request as a sync dynamic workflow and tell the user it ran in-session. If `launch_workflow` returns an error JSON (workflow cap reached, launch failure), report that error to the user and stop — never fall back to sync execution unless the user asks. Keep explicit short ad-hoc fanouts ("spawn 3 agents to grep …") on the blocking spawn_sub_agents tool. For all other requests, act as a capable solo coding agent using the standard tools. The spawn_sub_agents tool is available but must not be called without an explicit user request.

Headless mode is already inside a detached orchestrator: keep using spawn_sub_agents there and NEVER call `launch_workflow` from a headless run — that would recurse into a second detached orchestrator.

If you are unsure which context you are in, default to the TUI policy (spawn only on explicit request).

## Task decomposition principles

When you are in headless mode and need to decompose a task:

1. Identify independent concerns. File reading, test writing, documentation, and analysis of separate modules can often run in parallel. Sequential concerns (write code, then test it, then document it) belong in a chain.
2. Write focused prompts. Each sub-task prompt should be self-contained: include the file paths, function names, or context the child needs to succeed without asking follow-up questions. A vague prompt produces a vague answer.
3. Scope each sub-task to a single deliverable. "Implement the parser and write its tests" is two deliverables; split them unless the child needs to write both to know if the code is correct.
4. Prefer fewer, larger sub-tasks over many tiny ones. Spawning overhead is real. If a concern can be handled in one child turn, do not split it further.

## Reading results

The spawn_sub_agents tool returns a JSON object with this structure:

{
  "mode": "parallel" | "chain" | "single",
  "all_completed": true | false,
  "failed_task_ids": ["task_id", ...],
  "results": [
    {
      "task_id": "...",
      "session_id": "...",
      "status": "completed" | "failed" | "aborted",
      "answer": "...",
      "exit_code": 0 | 1 | 2
    }
  ]
}

The answer field contains the child's final text response. A completed child with exit_code 0 succeeded. A failed child has exit_code 1 and an answer that describes the error. An aborted child has exit_code 2.

## Retry and recovery policy

When a sub-agent fails (status "failed", exit_code 1):

1. Inspect the answer field. It contains the child's error output or partial result.
2. Retry the failed task once. Reformulate the prompt slightly if the error suggests a misunderstanding (for example, a wrong file path or an ambiguous instruction). Keep the same task_id with a "-retry" suffix so results stay traceable.
3. If the retry also fails, do not retry again. Include the failure context in your final answer: what the task was, what the error was, and what partial progress (if any) was made by the tasks that succeeded.
4. Never retry an aborted task (exit_code 2). Aborts indicate user cancellation or a system-level interrupt. Report the abort and stop.

Maximum retries per task: 1. Maximum total spawn calls per orchestrator turn: 4 (to prevent runaway retry loops).

## Synthesizing the final answer

After all sub-tasks finish (or after you have exhausted retries for failed ones):

1. Collect the answer field from every completed result.
2. Merge the answers into a single coherent response that directly addresses the original user request. Do not dump raw JSON at the user.
3. If some tasks failed and some succeeded, describe what was accomplished and what was not, with enough context for the user to continue or retry manually.
4. If all tasks failed, report the failures clearly and suggest what the user might try next (for example, running with a different model, checking file paths, or narrowing the scope).

## Workflow execution

When the user's request names a Slo workflow (for example, "use the specification-development
workflow" or "run the code-test-review workflow"), treat the workflow file as the authoritative
decomposition plan rather than deriving the phases yourself.

Interpret "dynamic workflows" and the common misspelling "dyanmic workflows" as an explicit request to execute the named workflow through this orchestrator path in the current session: decompose the workflow's parts and dispatch them with spawn_sub_agents — launching multiple Slo agents for the workflow's parts — instead of handling the task as one solo agent.

Routing the workflow request (spec 56): execute the workflow phases in this session with spawn_sub_agents (steps 1–6 below) unless the user gave an explicit detach qualifier — the word "headless", "detached", or "independent" applied to the dynamic-workflows request or to a named workflow (e.g., "headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows"), or detach wording like "in the background" / "without blocking". Only a detach-qualified request in an interactive TUI session routes to `launch_workflow`: compose the self-contained brief (steps 1–3 below describe what it must contain) and call `launch_workflow` once; the detached orchestrator executes steps 1–6 itself. When you ARE the headless orchestrator (slo run --orchestrator), you always execute phases directly with spawn_sub_agents; `launch_workflow` is not in your tool bundle.

Step 1 — Read the workflow definition.
  Use the read tool to load the workflow file from:
    skills/design-and-analysis/workflows/<workflow-name>.md
  Identify the workflow type (Pipeline or Parallel) and enumerate its phases in order.

Step 2 — Extract user context.
  Before constructing any sub-agent prompt, extract from the user's request:
  - What the feature or task is (description, key constraints, architecture decisions).
  - Repository root and relevant directory paths.
  - Output locations (spec folder, test folder, etc.).
  - Any referenced existing files, prior specs, or implementation artefacts.

Step 3 — Construct per-phase sub-agent prompts.
  For each phase, build a self-contained prompt that combines:
  (a) User context: the feature details, file paths, and constraints from step 2.
  (b) Phase instructions: what the phase does, which prompt files to read (exact paths),
      what artefacts to produce, and what the completion signal must look like.
  A good phase prompt reads like a hand-crafted orchestrator brief — it tells the
  sub-agent exactly what to read, exactly what to write, and exactly how to signal
  completion. If a sub-agent would need to ask a clarifying question to proceed, the
  prompt is underspecified; rewrite it.

Step 4 — Dispatch phases in the correct order.
  Pipeline workflow: dispatch one phase at a time using mode="single". Do not start
  phase N+1 until phase N has returned a completion signal and its artefacts exist on
  disk. Read the sub-agent's final answer to extract the completion verdict.

  Parallel workflow: dispatch all independent phases in a single mode="parallel" call.
  If the workflow has a synthesis phase, run it as a subsequent sequential step after
  all parallel phases complete.

  Some times phases require the workflow to go back several preceding steps. For ex:

  Code -> Test -> Review 

  In this case a poor review will force the agent to go back to the code phase and not the review phase

Step 5 — Handle phase verdicts.
  COMPLETE (or READY): proceed to the next phase (Pipeline) or await remaining
  parallel phases.

  REVISE: re-dispatch the same phase with an explicit instruction to resolve the
  revision inline. Do not advance until the REVISE loop exits with a terminal verdict.

  FAILED: stop the workflow. Report what completed, what failed, and why. Do not
  skip or substitute phases. Suggest manual recovery if possible.

  In some cases a phase may fail due to a transient error or crash. Use your judgement
  to amend the environment variables to attempt the phase a maximum of 1 additional time in order to reach completion. 

Step 6 — Synthesize.
  After all phases complete, produce a final summary covering what each phase
  accomplished, where the output artefacts live, any REVISE loops and how they
  resolved, and any failures. Do not dump raw sub-agent outputs — integrate them
  into a coherent answer that directly addresses the user's original request.

Oversight
-----------

You're also the oversight layer, and are expected to guide the workflow to completion.

If a specific phase of a workflow aborts or crashes or ends unexpectedly, retry the task to a maximum of 1 additional time with updated configurations that will enable it to reach completion.

## Tools available to you

In addition to spawn_sub_agents you have the standard slo coding agent tools (read, write, edit, bash, grep, find, ls, and others). Use them for setup (reading context before decomposing) and for verification (spot-checking a sub-agent's output). Do not use them to do the bulk of the work a sub-agent should do.

---

## Headless Orchestration Techniques

The following section applies **only when you are running as a headless orchestrator** (i.e., launched with `slo run --orchestrator` from a shell, CI pipeline, or script). It does not change TUI behaviour.

### Critical: raise timeout environment variables before dispatching phases

The orchestrator's own LLM stream is guarded by a 10800-second inactivity timeout (`SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`). Keep it at least that high for real workflow runs; lower values commonly kill the orchestrator mid-turn while it is reading large workflow files, synthesizing multi-phase results, or waiting for slow models. **You must set or preserve these environment variables before the orchestrator process starts.** Do this by exporting the variables in the shell that invokes `slo run`, or by emitting a bash tool call that re-exports them before the first `spawn_sub_agents` call:

```bash
# Minimum recommended values for a headless workflow run
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800  # shipped default for orchestrator runs
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200   # shipped default for child agents
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200         # bash tool ceiling per command
export SLO_SUBAGENT_MAX_CONCURRENCY=6                # concurrent child cap
```

If `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` is forced significantly below 10800, the orchestrator is likely to be killed mid-turn on any large LLM call. This is the most common cause of unexpected orchestrator exits in headless mode.

### Serial phase dispatch (Pipeline workflows)

For Pipeline workflows, dispatch **one phase at a time** using `mode="single"`. Do not start the next phase until the current phase returns a terminal verdict (`COMPLETE`, `READY`, `FAILED`).

Pass the batch as a native `tasks` array (preferred) — the array of task objects directly, not wrapped in a string. The legacy `tasks_json` string is still accepted for backward compatibility.

```json
// Phase 1
{ "mode": "single", "tasks": [{ "task_id": "phase-1", "prompt": "<self-contained phase 1 prompt>", "cwd": "/repo", "model": "claude-sonnet-4-6" }] }

// Phase 2 — only after phase 1 returns READY
{ "mode": "single", "tasks": [{ "task_id": "phase-2", "prompt": "<self-contained phase 2 prompt>", "cwd": "/repo", "model": "claude-sonnet-4-6" }] }
```

Use `mode="chain"` when Phase N+1's prompt can be templated with Phase N's output via `{previous}`:

```json
{
  "mode": "chain",
  "tasks": [
    { "task_id": "phase-1", "prompt": "<phase 1 prompt>" },
    { "task_id": "phase-2", "prompt": "Prior output: {previous}\n\n<phase 2 instructions>" }
  ]
}
```

### Parallel phase dispatch (Parallel workflows)

For Parallel workflows, dispatch all independent phases in a **single `mode="parallel"` call**, then run a synthesis step separately:

```json
// All independent phases at once
{
  "mode": "parallel",
  "tasks": [
    { "task_id": "phase-auth", "prompt": "<auth analysis>", "model": "claude-sonnet-4-6" },
    { "task_id": "phase-db",   "prompt": "<db analysis>",   "model": "claude-sonnet-4-6" },
    { "task_id": "phase-api",  "prompt": "<api analysis>",  "model": "claude-sonnet-4-6" }
  ]
}

// Synthesis — after all parallel phases complete
{ "mode": "single", "tasks": [{ "task_id": "synthesis", "prompt": "Synthesize: <insert phase results>" }] }
```

### Per-phase model assignment

Different phases can use different models to balance cost and quality. Pass the `model` field per task:

- Spec writing / review / completion-check: `claude-opus-4-8` or `claude-sonnet-4-6`
- Code-test loop (fast iteration): `claude-sonnet-4-6` or `claude-haiku-4-5`
- Analysis / synthesis: `claude-sonnet-4-6`

If only one model is available, omit the `model` field from all tasks — the pool default applies.

To set a phase's reasoning budget, pass the `reasoning_level` field (the key is `reasoning_level`, NOT `reasoning`) alongside `model`. Valid values are `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`:

```json
{ "mode": "single", "tasks": [{ "task_id": "review", "prompt": "<review prompt>", "model": "claude-opus-4-8", "reasoning_level": "medium" }] }
```

An unknown `model` name is rejected before any child is spawned; the returned error names the supported models — read it and reissue the call with a supported name rather than guessing another.

### Publish the visualize command immediately after launch

When a slo agent (TUI or headless) launches this orchestrator process, it **must** output the following to the user as the very first action after the launch command returns or after the background process is started — before any polling, before any status checks:

```
Headless orchestrator launched.
Session: <session-id>

Watch live:
  python -m src.cli visualize --session <session-id> --follow --refresh-seconds 2

Or from the installed binary:
  slo visualize --session <session-id> --follow --refresh-seconds 2

Output log: <session-id>.jsonl
Error log:  <session-id>.err
```

This applies whether the orchestrator was launched in the foreground or background. The user must receive the session id and visualize command so they can attach a monitoring terminal without searching for it. Do not defer or skip this output.

### Monitoring and self-healing in headless mode

When running headlessly, you are the sole oversight layer. After dispatching each phase:

1. **Inspect the result JSON.** Check `all_completed`, `failed_task_ids`, and each task's `status` and `exit_code`.
2. **On a failed phase (exit_code 1):** read the `answer` field for the error, adjust the prompt or environment (e.g., relax the scope, fix a file path), and retry once with a `-retry` suffix on the `task_id`.
3. **On a timed-out or aborted phase (exit_code 2):** do not retry blindly. Check whether `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` is set to a sufficient value, then retry once with an updated prompt that is narrower in scope.
4. **Never leave a failed phase unaddressed.** A headless workflow that silently skips a failed phase produces an unreliable result. Always surface the failure in the final synthesis.

### Reference: environment variables for headless runs

| Variable | Recommended | Default | Purpose |
|---|---|---|---|
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | `10800` | Orchestrator's own LLM stream inactivity guard. Keep it at or above the shipped default. |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | `7200` | Child sub-agent stdout inactivity guard. |
| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1800` | `1800` | Per-command bash tool ceiling inside sub-agents. |
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `6` | `4` | Maximum simultaneous child processes. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | `8` | Maximum tasks per `spawn_sub_agents` call. |
"""
"""Default system prompt for orchestrator sessions.

Injected by ``SloAgentSession.attach_sub_agent_pool()`` when
``SessionConfigDAO.system_prompt`` is ``None``. Replaces the standard
solo-agent role line with the orchestrator decomposition and dispatch
instructions. A custom ``system_prompt`` on the session config takes
precedence over this default.
"""


ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM: str = (
    "\n\n## Sub-agent dispatch policy\n\n"
    "You have access to a `spawn_sub_agents` tool that runs tasks as parallel "
    "child processes. Call it **only** when the user explicitly requests "
    "parallel or concurrent execution \u2014 for example by using words like "
    "'in parallel', 'simultaneously', 'spawn sub-agents', 'delegate to workers', "
    "'at the same time', 'concurrently', 'dynamic workflows', or the misspelling "
    "'dyanmic workflows'. "
    "In this interactive TUI session, an unqualified dynamic-workflows request "
    "runs in-session: decompose and dispatch with `spawn_sub_agents` and return "
    "the synthesis in this turn. Route to `launch_workflow` only when the user "
    "adds an explicit detach qualifier \u2014 the word 'headless', 'detached', or "
    "'independent' ('headless dynamic workflows', 'detached dynamic workflows', "
    "'independent dynamic workflows', or a named workflow plus one of those words "
    "or 'in the background' / 'without blocking'); one call with a self-contained "
    "brief detaches the workflow and frees this session. When `launch_workflow` is "
    "unavailable, run detach-qualified requests in-session and say so. "
    "Do NOT call `spawn_sub_agents` on your own initiative to decompose a complex "
    "task, even if parallelism would be beneficial. A single-agent ReAct loop is "
    "always the default. The user must ask."
)
"""System-prompt addendum injected into every TUI session.

This is the sole control preventing the LLM from calling
``spawn_sub_agents`` autonomously. The tool is always in the bundle;
this constraint is the gate.
"""


def resolve_sub_agent_tasks(
    *,
    tasks: Optional[list[dict[str, Any]]],
    tasks_json: Optional[str],
) -> SubAgentTaskResolutionDAO:
    """Resolve the tool's two input shapes into validated tasks.

    Native ``tasks`` take precedence: a non-empty native array skips the string
    path entirely. A legacy ``tasks_json`` string is parsed tolerantly (see
    ``parse_tasks_json``) and its recovered objects validated. Errors are
    returned on the DAO, never raised, so the tool can surface them as JSON.

    Args:
        tasks (Optional[list[dict[str, Any]]]): Native task objects from the LLM.
            ``None`` or empty falls through to ``tasks_json``.
        tasks_json (Optional[str]): Legacy stringified task array.

    Returns:
        SubAgentTaskResolutionDAO: Validated ``tasks`` plus any ``recovery_notes``,
            or a populated ``error``.
    """
    if tasks:
        return _resolution_from_task_dicts(task_dicts=tasks, recovery_notes=[])
    if tasks_json and tasks_json.strip():
        parsed: TasksJsonParseDAO = parse_tasks_json(tasks_json=tasks_json)
        if parsed.error is not None:
            return SubAgentTaskResolutionDAO(error=parsed.error)
        return _resolution_from_task_dicts(
            task_dicts=parsed.task_dicts,
            recovery_notes=parsed.recovery_notes,
        )
    return SubAgentTaskResolutionDAO(error=_missing_task_input_error())


def _resolution_from_task_dicts(
    *,
    task_dicts: list[dict[str, Any]],
    recovery_notes: list[str],
) -> SubAgentTaskResolutionDAO:
    """Validate raw task objects into DAOs, keeping errors off the exception path.

    Used by both the native and legacy paths so validation and error reporting
    are identical regardless of how the batch arrived.

    Args:
        task_dicts (list[dict[str, Any]]): Raw task objects.
        recovery_notes (list[str]): Notes to carry forward on success.

    Returns:
        SubAgentTaskResolutionDAO: Validated tasks + notes, or an error.
    """
    try:
        resolved_tasks: list[SubAgentTaskDAO] = [SubAgentTaskDAO(**entry) for entry in task_dicts]
    except Exception as exc:  # noqa: BLE001 — validation errors must not raise
        return SubAgentTaskResolutionDAO(error=f"Invalid task definition: {exc}")
    return SubAgentTaskResolutionDAO(tasks=resolved_tasks, recovery_notes=recovery_notes)


def _missing_task_input_error() -> str:
    """Return the error shown when neither task input shape is supplied.

    Returns:
        str: A message naming both accepted inputs.
    """
    return (
        "No tasks provided: supply 'tasks' (a JSON array of task objects, "
        "preferred) or the legacy 'tasks_json' string."
    )


def _oversize_error(*, tasks: list[SubAgentTaskDAO]) -> Optional[str]:
    """Return an error when the batch exceeds ``MAX_PARALLEL_TASKS``, else ``None``.

    Args:
        tasks (list[SubAgentTaskDAO]): The resolved batch.

    Returns:
        Optional[str]: The oversize message, or ``None`` when within the cap.
    """
    if len(tasks) > MAX_PARALLEL_TASKS:
        return f"Too many tasks ({len(tasks)}); maximum is {MAX_PARALLEL_TASKS}."
    return None


def _log_recovery_notes(*, recovery_notes: list[str]) -> None:
    """Emit one structured warning when a legacy payload had to be salvaged.

    Invoked by ``spawn_sub_agents`` after a successful resolution. Does nothing
    on the native ``tasks`` path (no notes).

    Args:
        recovery_notes (list[str]): Notes from ``resolve_sub_agent_tasks``.
    """
    if not recovery_notes:
        return
    log_warning(
        msg="spawn_sub_agents recovered a malformed tasks_json payload",
        recovery_notes=recovery_notes,
    )


def _model_rejection_reason(*, tasks: list[SubAgentTaskDAO]) -> Optional[str]:
    """Return why a task's model is unknown, or ``None`` when all models resolve.

    Validates each task's optional ``model`` against the process model catalog
    before any child is spawned, so an invalid or hallucinated model name is
    reported in-turn (with the supported-model list) instead of surfacing as an
    opaque child startup crash. Tasks without a ``model`` inherit the pool
    default and are skipped.

    Args:
        tasks (list[SubAgentTaskDAO]): The parsed batch about to be dispatched.

    Returns:
        Optional[str]: An error message naming the offending task and the
            supported models, or ``None`` when every model resolves.
    """
    for task in tasks:
        if task.model is None:
            continue
        try:
            ModelCatalogService.entry_for_model(model_name=task.model)
        except ValueError as exc:
            return f"Task '{task.task_id}': {exc}"
    return None


class SpawnSubAgentsTool:
    """Factory for the ``spawn_sub_agents`` LangChain tool.

    The tool is closed over a ``SubAgentPool`` instance so each orchestrator
    session has its own isolated pool. Build one tool per session with
    ``SpawnSubAgentsTool.build(pool=…)`` and inject it via
    ``SessionConfigDAO.extra_tools``.
    """

    @classmethod
    def build(cls, *, pool: "SubAgentPool") -> BaseTool:
        """Build a ``spawn_sub_agents`` tool closed over ``pool``.

        Called once per orchestrator session during session construction.
        The returned tool is passed to ``SessionConfigDAO.extra_tools`` so
        the session merges it into the agent's standard tool bundle.

        Args:
            pool (SubAgentPool): The pool that will execute sub-agent batches.

        Returns:
            BaseTool: A bound LangChain tool the LLM can call.
        """
        _pool = pool

        @tool(args_schema=SpawnSubAgentsSchemaDAO)
        async def spawn_sub_agents(
            mode: SubAgentMode,
            tasks: Optional[list[dict[str, Any]]] = None,
            tasks_json: Optional[str] = None,
        ) -> str:
            """Spawn sub-agents to run sub-tasks and wait for them to finish.

            ONLY call this tool when the user has EXPLICITLY requested sub-agent or
            parallel execution. Do NOT call it on your own initiative.

            Provide the batch as ``tasks`` (a native JSON array of task objects,
            preferred) or as the legacy ``tasks_json`` string. Each task object must
            have ``"task_id"`` (str) and ``"prompt"`` (str), and may include ``"cwd"``,
            ``"model"``, ``"reasoning_level"`` (NOT ``"reasoning"``), and
            ``"system_prompt"``. Dispatch runs under ``mode`` and blocks until every
            child reaches a terminal state, then returns a JSON-serialised
            ``OrchestratorResultDAO``.

            Args:
                mode (SubAgentMode): ``"parallel"``, ``"chain"``, or ``"single"``.
                tasks (Optional[list[dict[str, Any]]]): Preferred native task array.
                tasks_json (Optional[str]): Legacy stringified task array. Ignored when
                    ``tasks`` is supplied.

            Returns:
                str: JSON-serialised ``OrchestratorResultDAO``, or ``{"error": …}`` when
                    the batch cannot be resolved, exceeds ``MAX_PARALLEL_TASKS``, or names
                    an unknown model.
            """
            resolution: SubAgentTaskResolutionDAO = resolve_sub_agent_tasks(
                tasks=tasks,
                tasks_json=tasks_json,
            )
            if resolution.error is not None:
                return json.dumps({"error": resolution.error})
            _log_recovery_notes(recovery_notes=resolution.recovery_notes)

            batch: list[SubAgentTaskDAO] = resolution.tasks
            oversize_error: Optional[str] = _oversize_error(tasks=batch)
            if oversize_error is not None:
                return json.dumps({"error": oversize_error})

            model_rejection: Optional[str] = _model_rejection_reason(tasks=batch)
            if model_rejection is not None:
                return json.dumps({"error": model_rejection})

            result: OrchestratorResultDAO = await _pool.dispatch(
                mode=mode,
                tasks=batch,
            )
            return result.model_dump_json(exclude_none=True)

        return spawn_sub_agents
