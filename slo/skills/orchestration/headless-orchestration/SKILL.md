---
name: headless-orchestration
description: Launch a named Slo workflow as a DETACHED headless orchestrator process
  — triggered only when the user adds an explicit detach qualifier ("headless" /
  "detached" / "independent" applied to a dynamic-workflows request or a named
  workflow, or detach wording "in the background" / "without blocking"). An
  unqualified "dynamic workflows" request runs in-session via spawn_sub_agents and
  does NOT trigger this skill. Sets the required timeout env vars, selects models
  per phase, dispatches phases serially or in parallel, and monitors child agents
  until the orchestrator reaches a terminal state. A detached orchestrator never
  calls launch_workflow.
when_to_use: Use when the user explicitly asks to run a workflow with a detach
  qualifier — "headless dynamic workflows", "detached dynamic workflows",
  "independent dynamic workflows", "run the code-test-review workflow detached",
  or detach wording like "in the background" / "without blocking" applied to a
  workflow request. Do NOT load this skill for an unqualified "dynamic workflows"
  or "dyanmic workflows" phrase (no detach qualifier) — that runs in-session via
  spawn_sub_agents. Also load this skill when the user explicitly asks to execute
  a workflow using the headless runner (slo run --orchestrator) from a shell or CI
  pipeline.
group: orchestration
kind: workflow
---

# Headless Orchestration

## Skill summary

- **Name:** `headless-orchestration`
- **Description:** Launch a named Slo workflow as a DETACHED headless orchestrator process — triggered only when the user adds an explicit detach qualifier ("headless" / "detached" / "independent" applied to a dynamic-workflows request or a named workflow, or detach wording "in the background" / "without blocking"). An unqualified "dynamic workflows" request runs in-session via spawn_sub_agents and does NOT trigger this skill. Sets the required timeout env vars, selects models per phase, dispatches phases serially or in parallel, and monitors child agents until the orchestrator reaches a terminal state. A detached orchestrator never calls launch_workflow.
- **When to use:** Use when the user explicitly asks to run a workflow with a detach qualifier — "headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows", "run the code-test-review workflow detached", or detach wording like "in the background" / "without blocking" applied to a workflow request. Do NOT load this skill for an unqualified "dynamic workflows" or "dyanmic workflows" phrase (no detach qualifier) — that runs in-session via spawn_sub_agents. Also load this skill when the user explicitly asks to execute a workflow using the headless runner (`slo run --orchestrator`) from a shell or CI pipeline.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`

## Examples

- The user asks: "Run the code-test-review workflow for this feature spec in headless mode." — load this skill (detach qualifier present).
- The user asks: "Launch the specification-development workflow in the background." — load this skill (detach wording present).
- The user asks: "Run this workflow headlessly — I'll monitor it from the visualizer." — load this skill (detach qualifier present).
- The user asks: "Use headless dynamic workflows for this task." — load this skill (detach qualifier "headless" present).
- The user asks: "Use dynamic workflows for this task." — do NOT load this skill; the unqualified phrase runs in-session via spawn_sub_agents (sync dynamic workflow).

## Guidance

**Workflow-turn accounting:** Follow
`skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`.
Count a full pass through the workflow, not individual phases or agent calls.
Report partial passes and separate harness limits explicitly; never skip review
or treat repeated authoring dispatches as completed workflow turns.
Explicit user instructions override the default workflow-turn and per-turn dispatch
budgets: raise, lower or remove either limit as requested. Record and pass on the
effective limits without resetting consumed counts; runtime caps and other
policies remain separate. See the shared rules above for defaults and scope.


## Pre-conditions

Before launching a headless workflow, confirm:

1. **A workflow name is identified.** The user has named a Slo workflow (e.g., `code-test-review`, `specification-development`) or has provided a task that maps to one. A detach-qualified phrase ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows") counts as an explicit request for this headless-orchestrator path. An unqualified "dynamic workflows" phrase (no detach qualifier) runs in-session via spawn_sub_agents — do not continue with this skill for an unqualified phrase. If the actual workflow name is still unspecified, load `skills/orchestration/workflows/SKILL.md` to list options and ask.
2. **A project working directory is known.** The agent needs `--cwd` set to the repository root. Default to `$PWD` only if it is clearly a project root.
3. **Credentials are in place.** These GPT examples use provider `openai`: resolve `SLO_OPENAI_API_KEY` or a stored OpenAI API-key/OAuth credential through the runtime resolver. Do not print credentials. Confirm model access for that lane; a seeded catalog entry is not a live availability check.
4. **A session id strategy is chosen.** Either generate a human-readable slug (`<workflow>-<date>`) or use `--session-id` with a user-provided value.

---

## Step 1 — Set timeout and concurrency environment variables

**Always export these before launching the orchestrator.** The shipped 10800-second stream inactivity timeout is the minimum safe default for workflow orchestration; lowering it commonly kills the orchestrator during large LLM calls (reading workflow files, synthesizing multi-phase results).

```bash
# Orchestrator's own LLM stream — how long it may be silent before the run is
# treated as hung. Default is 10800s and should generally stay there or higher.
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS="${SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS:-10800}"

# Each child sub-agent process — how long a child may produce no stdout before
# being killed. Default is 7200s; raise further for especially slow models.
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS="${SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS:-7200}"

# Bash tool ceiling per command inside a sub-agent.  0 disables.
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS="${SLO_BASH_DEFAULT_TIMEOUT_SECONDS:-1800}"

# Maximum number of child sub-agents running simultaneously.
export SLO_SUBAGENT_MAX_CONCURRENCY="${SLO_SUBAGENT_MAX_CONCURRENCY:-6}"

# Maximum tasks accepted per single spawn_sub_agents call.
export SLO_SUBAGENT_MAX_TASKS="${SLO_SUBAGENT_MAX_TASKS:-8}"
```

These values are conservative lower bounds for production workflows. Raise them further for workflows that involve large codebases or expensive LLM calls.

**Reference:** `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` guards the orchestrator's own API stream. `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` guards each child's stdout pipe. They are independent; both must be set.

---

## Step 2 — Choose models

If the user specifies a model per phase, prepare the model assignments. Otherwise use a single default model for all phases.

### Single-model configuration (default)

```bash
ORCHESTRATOR_MODEL="${ORCHESTRATOR_MODEL:-gpt-6-astra}"
ORCHESTRATOR_REASONING="${ORCHESTRATOR_REASONING:-high}"
```

The orchestrator itself uses this model. Set every child model and reasoning_level
explicitly. These are workflow example defaults, not changes to runtime defaults.
User choices replace the corresponding real fields; never encode them only in prose.

### Multi-model configuration (optional)

Different phases often have different cost/quality trade-offs:

- **Orchestrator / spec writing / review / completion:** `high` — use `gpt-6.1-sol` or `gpt-6-astra`.
- **Code+Test:** `medium` — use `gpt-6-astra` or `gpt-6.1-sol`.
- **Analysis / synthesis:** `high` — use `gpt-6-astra`.

For a user override, replace the literal `reasoning_level` in each task below;
for shell/CI set `ORCHESTRATOR_REASONING=high` (or the user's canonical value),
which is passed to the actual `--reasoning` flag in every run template.

Pass the model in the `SubAgentTaskDAO` `model` field when constructing tasks for the `spawn_sub_agents` call. Example task JSON:

```json
[
  {
    "task_id": "phase-1-code",
    "prompt": "<self-contained phase prompt>",
    "cwd": "/path/to/project",
    "model": "gpt-6-astra",
    "reasoning_level": "medium"
  },
  {
    "task_id": "phase-2-review",
    "prompt": "<self-contained review prompt>",
    "cwd": "/path/to/project",
    "model": "gpt-6.1-sol",
    "reasoning_level": "high"
  }
]
```

### Model pool fallback (recommended for long runs)

Optional same-provider model fallback (not provider-outage isolation): both catalog
identifiers use provider `openai`. Catalog presence does not prove account entitlement
or live availability; verify the configured API-key/OAuth lane before launch.
The pool has no per-entry reasoning field: the request level is resolved per member.
An explicit model selection can bypass the configured pool; verify actual routing.
Export `SLO_MODEL_POOL` only when intentionally using the runtime pool path:

```bash
export SLO_MODEL_POOL='[
  {"model_name":"gpt-6-astra","provider":"openai","priority":1,"cooldown_seconds":300,"rate_limit_cooldown_seconds":30},
  {"model_name":"gpt-6.1-sol","provider":"openai","priority":2,"cooldown_seconds":600,"rate_limit_cooldown_seconds":60}
]'
```

---

## Step 3 — Construct the session id and task prompt

```bash
# Human-readable session id — traceable by workflow name and date
WORKFLOW_SESSION="<workflow-name>-$(date +%Y%m%d-%H%M%S)"

# Task prompt — context only; the orchestrator already knows the workflow protocol
# from DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT.  Do not re-explain orchestrator mechanics.
TASK_PROMPT="$(cat <<'EOF'
Use the <workflow-name> workflow to <describe the task>.

Repository root: /path/to/project
Current branch: <branch-name> (already checked out)
Spec / input: /path/to/spec/overview.md
Git user email: you@example.com
Workflow file: skills/orchestration/workflows/<workflow-name>.md

When all phases are complete, output exactly:
WORKFLOW COMPLETE.
Phase summary: <what each phase produced>
EOF
)"
```

The prompt is purely context. The `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` injected by `--orchestrator` already instructs the orchestrator how to read the workflow file, build per-phase prompts, dispatch phases, handle verdicts, and synthesize results.

---

## Step 4 — Launch the orchestrator

### Managed launch from an existing agent session (required)

Call `launch_workflow` once with explicit fields; never substitute brief prose
for configuration. Example tool arguments (Orchestrator: high):

```json
{
  "brief": "Use code-test-review for the approved specification; Code+Test: medium; Review: high; Completion: high. Put each phase value in the child reasoning_level field.",
  "cwd": "/path/to/project",
  "model": "gpt-6-astra",
  "reasoning_level": "high"
}
```

Replace `reasoning_level` with the user's canonical orchestrator value when
specified; replace each child's `reasoning_level` with its requested phase value.
Shell launches use `--reasoning`, not `reasoning_level`; child task JSON uses
`reasoning_level`, not `--reasoning`. These are independent requests.

Inspect the running exposed schema before calling. If it lacks the field despite
current source supporting it, report an **exposed-schema mismatch** and stop for
operator resolution: do not silently inherit and do not bypass the managed launcher
with a shell process. A detached orchestrator never calls `launch_workflow`.

Source contract: `LaunchWorkflowSchemaDAO` accepts Optional[ReasoningLevel]; the
launcher forwards `--reasoning`. Omitted/null uses its bootstrap-time snapshot,
not live parent settings; a null snapshot omits the flag. This is not the skill's
high default. CLI values: off / minimal / low / medium / high / xhigh / max.
CLI forwards the raw string; use canonical lowercase values, not aliases. The
slash parser trims and lowercases; that is not a CLI normalization guarantee.
No extra-high alias is accepted. Tool JSON must use canonical literals.
Model aliases and reasoning normalization are distinct.
The model policy clamps unsupported levels to the nearest stronger supported level,
then weaker; record requested and effective levels separately. These two GPT seeds
support all seven levels, but off/minimal map to provider low where required.

Launch acknowledgement proves spawn only. Record schema/version, requested fields,
forwarded argv, admitted model and effective provider effort from safe runtime
telemetry when available. Neither a brief, session model name, missing argv flag,
nor a successful spawn proves effective high. If telemetry is unavailable, say
unverified; never dump raw requests or secrets. Source files on disk need not match
the tool schema already exposed to a running session.

Managed `/workflows resume <workflow-id>` uses `--resume` but the current relaunch
argv forwards neither model nor reasoning overrides. The handle does not preserve
those launch fields; resumed configuration follows runtime resume/preferences policy.
Do not claim original requested high is restored or add unsupported resume flags.
Verify effective configuration again; report a limitation if exact replay is required.

### Shell/CI-only standard launch (blocking, output captured to file)

```bash
SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 \
SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 \
SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1800 \
SLO_SUBAGENT_MAX_CONCURRENCY=6 \
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd /path/to/project \
  --model "$ORCHESTRATOR_MODEL" \
  --reasoning "$ORCHESTRATOR_REASONING" \
  --json > "${WORKFLOW_SESSION}.jsonl" 2> "${WORKFLOW_SESSION}.err"

STATUS=$?
```

### Background launch (non-blocking, monitor separately)

```bash
SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 \
SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 \
SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1800 \
SLO_SUBAGENT_MAX_CONCURRENCY=6 \
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd /path/to/project \
  --model "$ORCHESTRATOR_MODEL" \
  --reasoning "$ORCHESTRATOR_REASONING" \
  --json > "${WORKFLOW_SESSION}.jsonl" 2> "${WORKFLOW_SESSION}.err" &

ORCH_PID=$!
echo "Orchestrator PID: $ORCH_PID  Session: $WORKFLOW_SESSION"
echo "Monitor: python -m src.cli visualize --session $WORKFLOW_SESSION --follow"
```

**Note:** These shell forms are only for explicitly requested shell/CI execution.
Inside an existing Slo agent session use the managed launch above, not a background
shell workaround; monitor its returned workflow/session identity through managed tools.

### Required: publish the visualize command immediately after launch

**After launching the orchestrator (blocking or background), you MUST output the following to the user before doing anything else:**

```
Headless orchestrator launched.
Session: <WORKFLOW_SESSION>

Watch live:
  python -m src.cli visualize --session <WORKFLOW_SESSION> --follow --refresh-seconds 2

Or from the installed binary:
  slo visualize --session <WORKFLOW_SESSION> --follow --refresh-seconds 2

Output log: <WORKFLOW_SESSION>.jsonl
Error log:  <WORKFLOW_SESSION>.err
```

Do not skip this output even if the orchestrator is running in the foreground. The user needs the session id and visualize command to attach a second terminal without having to search for it.

---

## Step 5 — Monitor until completion

### Live visualizer (separate terminal)

```bash
python -m src.cli visualize \
  --session "$WORKFLOW_SESSION" \
  --follow \
  --refresh-seconds 2.0
```

Keyboard: `↑`/`↓` navigate sub-agents, `Enter` select transcript, `r` force refresh, `f` toggle follow, `q` quit.

### Shell/CI-only programmatic monitoring (poll from script)

A terminal event (`run_completed`, `run_failed`, or `run_aborted`) means execution
has stopped. `run_completed` indicates execution success, not workflow acceptance.
Inspect phase verdicts and required artifacts before reporting the workflow as
complete. A successful process can return REVISE or INCOMPLETE. Poll the output file:

```bash
# Wait for terminal event (checks every 30s, up to 2 hours)
TIMEOUT=7200
ELAPSED=0
INTERVAL=30

while [ $ELAPSED -lt $TIMEOUT ]; do
  if grep -q '"kind":"run_completed"\|"kind":"run_failed"\|"kind":"run_aborted"' "${WORKFLOW_SESSION}.jsonl" 2>/dev/null; then
    echo "Orchestrator reached terminal state."
    break
  fi
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
  echo "Monitoring timed out after ${TIMEOUT}s — orchestrator may still be running."
fi
```

### Monitoring from inside a Slo agent session (managed workflow)

Use the `workflow_id` and `orchestrator_session_id` returned by `launch_workflow`.
Inspect the exposed `workflow_status` schema and query that managed workflow's
status; use its returned session identity for the visualizer and session evidence.
Do not assume a managed launch created the shell/CI example's local JSONL file.
If the required managed tool or schema is unavailable, report the limitation and
stop for operator resolution; do not launch or poll a replacement shell process.
The shell/CI file-polling example above applies only to explicitly requested
shell/CI execution, not an existing agent session's managed workflow.

A terminal status proves execution stopped, not acceptance. Inspect phase verdicts
and required artifacts before advancing or reporting completion. A monitoring
timeout is not an abort or permission to relaunch; report the last observed state.

---

## Stopping a running workflow — `/workflows abort`, never `pkill`

**Mandatory.** Stop a detached workflow only through Slo's abort path. Never
stop it with `pkill`, `kill`, `killall`, or a hand-written process-tree kill
from the bash tool. This applies even when the operator asks you to "stop the
workflow and commit what we have": stop it through the abort path first, then
snapshot.

| Launched from | Correct way to stop it |
|---|---|
| A TUI session via `launch_workflow` | The operator runs `/workflows abort <workflow-id>` in the owning session. An agent that needs the workflow stopped asks the operator to run it and waits until `workflow_status` reports `aborted`. |
| A shell or CI via `slo run --orchestrator` (no TUI handle) | Send `SIGTERM` to the orchestrator pid only (`kill -TERM "$ORCH_PID"`). It routes to the runner's cooperative abort, which records `aborted` and stops its own children. Do not signal the children or the process group. |

**Why:** a TUI-launched workflow has two durable records: the owning session's
handle (`workflows/<workflow-id>.json`) and the orchestrator's own status file
(`orchestrator.json`). `/workflows abort` writes a durable abort request, stops
the orchestrator group, and marks the handle `aborted`, so both records agree.
A raw `pkill` bypasses the handle. The orchestrator records `aborted`, but the
handle can be left `failed`. The reconcile step has no legal correction from
`failed` to `aborted`, so every later `launch_workflow` in that session fails
with:

```text
no evidence-backed correction for <workflow-id>: failed -> aborted
```

That one stale handle then blocks all new launches in the session, not just
the one that was killed.

**Verify:** after stopping, `workflow_status <workflow-id>` must report
`aborted` before reporting the stop as done. Do not retry, resume or relaunch
an aborted task as recovery.

---

## Step 6 — Serial vs. parallel phase dispatch inside the orchestrator

The orchestrator (running as the `--orchestrator` headless process) uses `spawn_sub_agents` to dispatch phases. The dispatch strategy is determined by the workflow type:

### Child payload and reasoning contract

Prefer native arrays: mode/tasks at the envelope; model/reasoning_level per task.
The task key is `reasoning_level`, not `reasoning`. The orchestrator's own model
and reasoning request is separate; never assume it forwards reasoning to children.
Every example sets both task fields, including standalone task objects in Step 2.

`resolve_sub_agent_tasks` → `_resolution_from_task_dicts` → `SubAgentTaskDAO`
validates the batch before `SubAgentProcess._build_argv` forwards child flags:

- A non-empty native `tasks` wins even when invalid; there is no legacy rescue.
- `None` or `[]` falls through to a nonblank legacy `tasks_json` string. That
  compatibility path uses a tolerant parser, then the same DAO validation.
  Recovery notes describe salvaged syntax; they do not waive validation.
- Unknown task fields and invalid canonical literals return an error beginning
  `Invalid task definition:`; no validated batch is returned.
- If neither input supplies a payload, the exact error is:
  `No tasks provided: supply 'tasks' (a JSON array of task objects, preferred) or the legacy 'tasks_json' string.`
- Omitted/null task reasoning becomes DAO `None`, so no child `--reasoning` is
  emitted. The child's own runtime resolves its setting, not the parent's explicit reasoning.
  This differs from the managed launcher's bootstrap-time snapshot described above.
- Model fallback is separate: `SubAgentPool._run_one` passes
  `task.model or self._default_model`. If both are absent, no `--model` is emitted.
  This model fallback is not a reasoning-inheritance mechanism.

The canonical `ReasoningLevel` lives in `src/agents/model_catalog/dao.py` and is
re-exported by `src/agents/reasoning_capabilities.py`. The injected
`DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` lives in `src/agents/slo_agent/orchestrator/spawn_tool.py`;
this guide does not update that runtime prompt or the running tool schema.

Version boundary: reference commit `2eca91fcd7d7d1bfca9a0012292c31f882f290b5`
adds `sys.executable -I -m src.cli` managed-launch isolation without changing the
reasoning contract. The historical base `7625be3a251339a5c434c27aef721359d52da872`
used `sys.executable -m src.cli` (no `-I`); versions containing the isolation
change use the isolated managed-launch form above. Do not infer a backport or
installed version from these examples; verify the actual runtime version independently.
Do not remove `-I` to bootstrap a source checkout: isolated managed launches need
Slo importable in that exact interpreter independently of cwd and `PYTHONPATH`.
Shell/CI commands have their own explicit import environment; they are not a
substitute for the managed launch path inside an agent session.

### Serial phases (Pipeline workflow — most workflows)

Pipeline workflows dispatch **one phase at a time** using `mode="single"`. Advance only after READY/COMPLETE and verification of required artifacts. REVISE returns to the workflow's revision-loop starting step; FAILED invokes recovery or stops the workflow. A normal process exit alone does not permit advancement.

Dispatch Code+Test alone:

```json
{
  "mode": "single",
  "tasks": [{"task_id": "phase-1-code", "prompt": "Implement and test the approved scope; report evidence and READY or REVISE.", "cwd": "/path/to/project", "model": "gpt-6-astra", "reasoning_level": "medium"}]
}
```

Only after Code+Test returns READY and its artifacts are verified, dispatch Review:

```json
{
  "mode": "single",
  "tasks": [{"task_id": "phase-2-review", "prompt": "Independently review the scope and Code+Test artifacts: <insert verified paths>. Report READY or REVISE.", "cwd": "/path/to/project", "model": "gpt-6.1-sol", "reasoning_level": "high"}]
}
```

Only after Review returns READY and its artifacts are verified, dispatch Completion:

```json
{
  "mode": "single",
  "tasks": [{"task_id": "phase-3-completion", "prompt": "Assess completion against the original scope and verified review: <insert paths>. Report COMPLETE or REVISE with evidence.", "cwd": "/path/to/project", "model": "gpt-6.1-sol", "reasoning_level": "high"}]
}
```

**Chain shorthand:** Chain is not a review gate. Use it only for non-gating dependent
work, never Code+Test → Review → Completion. Those phases require `single` and
verified verdicts. For a non-gating dependency, `{previous}` can template the result:

```json
{
  "mode": "chain",
  "tasks": [
    {"task_id": "summarize", "prompt": "Summarize the supplied release notes in five bullets: <insert notes>. This is a text transformation, not an approval gate.", "model": "gpt-6.1-sol", "reasoning_level": "high"},
    {"task_id": "shorten", "prompt": "Shorten this summary to three bullets without changing its meaning: {previous}", "model": "gpt-6.1-sol", "reasoning_level": "high"}
  ]
}
```

`mode="chain"` runs sequentially and injects the previous answer into `{previous}`.
A non-completed step stops the chain: this checks execution status, not verdict acceptance.
A completed answer containing REVISE is not an accepted review; use gated single calls.

### Parallel phases (Parallel workflow)

Dispatch independent analyses together. Verify their results before the separate synthesis call.

```json
{
  "mode": "parallel",
  "tasks": [
    {"task_id": "phase-auth", "prompt": "<auth module analysis prompt>", "model": "gpt-6-astra", "reasoning_level": "high"},
    {"task_id": "phase-db", "prompt": "<db module analysis prompt>", "model": "gpt-6-astra", "reasoning_level": "high"},
    {"task_id": "phase-api", "prompt": "<api module analysis prompt>", "model": "gpt-6-astra", "reasoning_level": "high"}
  ]
}
```

After all independent results and required artifacts have been checked, synthesize:

```json
{
  "mode": "single",
  "tasks": [{"task_id": "synthesis", "prompt": "Synthesize findings from auth, db, and api analyses: <insert verified results>", "model": "gpt-6.1-sol", "reasoning_level": "high"}]
}
```

**Concurrency cap:** `SLO_SUBAGENT_MAX_CONCURRENCY` (default 6) limits simultaneous children. With 3 parallel phases this is not a bottleneck; with 8+ phases some will queue.

---

## Step 7 — Extract results and handle failures

```bash
# Extract synthesis
RESULT=$(jq -r 'select(.kind == "run_completed") | .content' "${WORKFLOW_SESSION}.jsonl")

# Check sub-agent outcomes
jq -r 'select(.kind == "sub_agent_completed" or .kind == "sub_agent_failed") |
  "\(.kind): task=\(.task_id // "?") agent=\(.sub_agent_id // "?")"' \
  "${WORKFLOW_SESSION}.jsonl"

# Inspect a specific child's transcript
CHILD_ID=$(ls ~/.slo/sessions/history/"$WORKFLOW_SESSION"/children/ | head -1)
jq -r 'select(.kind == "text_delta") | .delta' \
  ~/.slo/sessions/history/"$WORKFLOW_SESSION"/children/"$CHILD_ID"/stdout.jsonl

# Post-run visualizer
python -m src.cli visualize --session "$WORKFLOW_SESSION" --no-follow
```

### Failure handling

| Exit code | Meaning | Action |
|---|---|---|
| `0` | `run_completed` — execution finished normally | Read the synthesis and verify every required phase verdict and artifact. Report REVISE/INCOMPLETE if acceptance gates did not pass. |
| `1` | `run_failed` | Read stderr: `tail -30 "${WORKFLOW_SESSION}.err"`. Check which phase failed in the JSONL. For a recoverable failure, address the cause and retry up to three times after the initial attempt, within the current workflow turn's dispatch budget. Carry counts forward on resume; do not reset them. |
| `2` | `run_aborted` | Never retry an aborted task, including an abort caused by a timeout. Report the abort and stop; do not automatically resume or relaunch. Never cause this state with `pkill`; see "Stopping a running workflow". |

---

## Step 8 — Environment variable summary

All variables relevant to a headless workflow launch:

| Variable | Recommended value | Default | Guards |
|---|---|---|---|
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | `10800` | Orchestrator's own LLM stream. Keep it at or above the shipped default. |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | `7200` | Each child sub-agent's stdout pipe. |
| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1800` | `1800` | Bash tool per-command ceiling inside sub-agents. |
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `6` | `6` | Maximum simultaneous child processes. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | `8` | Maximum tasks per `spawn_sub_agents` call. |
| `SLO_MODEL_POOL` | JSON pool array | — | Model fallback; examples use the same OpenAI provider. |
| `SLO_SESSION_ID` | Slug or UUID | — | Alternative to `--session-id` for env-driven pipelines. |
| `SLO_HOME` | `~/.slo` | `~/.slo` | Storage root for history and captures. |

---

## Complete launch template

Copy, fill in the placeholders, and run:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
WORKFLOW_NAME="code-test-review"            # e.g. code-test-review, specification-development
PROJECT_ROOT="/path/to/project"
SPEC_PATH="/path/to/spec/overview.md"
BRANCH="feature/my-feature"
GIT_EMAIL="you@example.com"
ORCHESTRATOR_MODEL="${ORCHESTRATOR_MODEL:-gpt-6-astra}"
ORCHESTRATOR_REASONING="${ORCHESTRATOR_REASONING:-high}"
SLO_SRC="${SLO_SRC:-$HOME/Code/slo/slo}"   # path to slo source root

# ── Session id ────────────────────────────────────────────────────────────────
SESSION="${WORKFLOW_NAME}-$(date +%Y%m%d-%H%M%S)"

# ── Timeout and concurrency env vars ─────────────────────────────────────────
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1800
export SLO_SUBAGENT_MAX_CONCURRENCY=6

# ── Task prompt (context only — orchestrator knows the workflow protocol) ─────
TASK_PROMPT="$(cat <<EOF
Use the ${WORKFLOW_NAME} workflow to implement the feature described in:
  ${SPEC_PATH}

Repository root: ${PROJECT_ROOT}
Current branch: ${BRANCH} (already checked out)
Git user email: ${GIT_EMAIL}
Workflow file: skills/orchestration/workflows/${WORKFLOW_NAME}.md

When all phases are complete, output exactly:
WORKFLOW COMPLETE.
Branch: ${BRANCH}
Tests: all passing
EOF
)"

echo "Launching headless workflow: ${SESSION}"
echo ""

# ── Launch ────────────────────────────────────────────────────────────────────
cd "$SLO_SRC"
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$SESSION" \
  --cwd "$PROJECT_ROOT" \
  --model "$ORCHESTRATOR_MODEL" \
  --reasoning "$ORCHESTRATOR_REASONING" \
  --json > "${SESSION}.jsonl" 2> "${SESSION}.err"

STATUS=$?

# ── Publish visualize command (required — always output this) ─────────────────
echo ""
echo "Headless orchestrator launched."
echo "Session: ${SESSION}"
echo ""
echo "Watch live:"
echo "  python -m src.cli visualize --session ${SESSION} --follow --refresh-seconds 2"
echo ""
echo "Or from the installed binary:"
echo "  slo visualize --session ${SESSION} --follow --refresh-seconds 2"
echo ""
echo "Output log: ${SESSION}.jsonl"
echo "Error log:  ${SESSION}.err"
echo ""
echo "Workflow exited: $STATUS"

if [ "$STATUS" -eq 0 ]; then
  jq -r 'select(.kind == "run_completed") | .content' "${SESSION}.jsonl"
else
  echo "Failed. Stderr tail:"
  tail -20 "${SESSION}.err"
fi
```

---

## Quick reference

```
When to use: user wants a Slo workflow run headlessly / unattended

Pre-conditions: workflow name known, project cwd known, credentials set

Step 1: Export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 (critical)
        Export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200
        Export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1800

Step 2: Orchestrator gpt-6-astra/high; Code+Test gpt-6-astra/medium;
        Review and Completion gpt-6.1-sol/high. Forward user overrides in fields.

Step 3: Set SESSION id and build task prompt (context only, not orchestrator instructions)

Step 4: Managed launch_workflow: model=gpt-6-astra, reasoning_level=high
        Shell/CI: --orchestrator --enable-history --session-id --cwd --model --reasoning
        Immediately output session id + visualize command to user (mandatory)

Step 5: Monitor via visualizer or poll output JSONL for terminal event

Stop:   /workflows abort <workflow-id> (TUI) or SIGTERM to the orchestrator pid (shell).
        NEVER pkill/kill the process tree — it leaves a stale handle that blocks
        every later launch_workflow in the session.

Step 6: Serial phases → mode="single" per phase; chain → mode="chain"
        Parallel phases → mode="parallel", then mode="single" for synthesis

Step 7: Extract results, inspect child transcripts, handle failures / resume

Step 8: All env var reference in table above
```
