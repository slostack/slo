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
group: design-and-analysis
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

## Pre-conditions

Before launching a headless workflow, confirm:

1. **A workflow name is identified.** The user has named a Slo workflow (e.g., `code-test-review`, `specification-development`) or has provided a task that maps to one. A detach-qualified phrase ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows") counts as an explicit request for this headless-orchestrator path. An unqualified "dynamic workflows" phrase (no detach qualifier) runs in-session via spawn_sub_agents — do not continue with this skill for an unqualified phrase. If the actual workflow name is still unspecified, load `skills/design-and-analysis/workflows/SKILL.md` to list options and ask.
2. **A project working directory is known.** The agent needs `--cwd` set to the repository root. Default to `$PWD` only if it is clearly a project root.
3. **Credentials are in place.** At least one of `ANTHROPIC_API_KEY`, `KIMI_FOR_CODING_API_KEY`, or `MOONSHOT_API_KEY` must be set.
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
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS="${SLO_BASH_DEFAULT_TIMEOUT_SECONDS:-1200}"

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
ORCHESTRATOR_MODEL="${ORCHESTRATOR_MODEL:-claude-sonnet-4-6}"
```

The orchestrator itself uses this model. Sub-agents inherit the pool default unless overridden per task.

### Multi-model configuration (optional)

Different phases often have different cost/quality trade-offs:

- **Spec writing / review / completion-check phases:** high reasoning — use `claude-opus-4-8` or `claude-sonnet-4-6`.
- **Code-test loop phases:** fast iteration — use `claude-sonnet-4-6` or `claude-haiku-4-5`.
- **Analysis / synthesis phases:** balanced — use `claude-sonnet-4-6`.

Pass the model in the `SubAgentTaskDAO` `model` field when constructing tasks for the `spawn_sub_agents` call. Example task JSON:

```json
[
  {
    "task_id": "phase-1-code",
    "prompt": "<self-contained phase prompt>",
    "cwd": "/path/to/project",
    "model": "claude-sonnet-4-6"
  },
  {
    "task_id": "phase-2-review",
    "prompt": "<self-contained review prompt>",
    "cwd": "/path/to/project",
    "model": "claude-opus-4-8"
  }
]
```

### Model pool fallback (recommended for long runs)

Export `SLO_MODEL_POOL` to automatically fall back to a secondary provider on rate limits or credit exhaustion:

```bash
export SLO_MODEL_POOL='[
  {"model_name":"claude-sonnet-4-6","provider":"anthropic","priority":1,"cooldown_seconds":300,"rate_limit_cooldown_seconds":30},
  {"model_name":"kimi-for-coding","provider":"kimi_for_coding","priority":2,"cooldown_seconds":600,"rate_limit_cooldown_seconds":60}
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
Workflow file: skills/design-and-analysis/workflows/<workflow-name>.md

When all phases are complete, output exactly:
WORKFLOW COMPLETE.
Phase summary: <what each phase produced>
EOF
)"
```

The prompt is purely context. The `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` injected by `--orchestrator` already instructs the orchestrator how to read the workflow file, build per-phase prompts, dispatch phases, handle verdicts, and synthesize results.

---

## Step 4 — Launch the orchestrator

### Standard launch (blocking, output captured to file)

```bash
SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 \
SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 \
SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200 \
SLO_SUBAGENT_MAX_CONCURRENCY=6 \
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd /path/to/project \
  --model "$ORCHESTRATOR_MODEL" \
  --json > "${WORKFLOW_SESSION}.jsonl" 2> "${WORKFLOW_SESSION}.err"

STATUS=$?
```

### Background launch (non-blocking, monitor separately)

```bash
SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 \
SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 \
SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200 \
SLO_SUBAGENT_MAX_CONCURRENCY=6 \
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd /path/to/project \
  --model "$ORCHESTRATOR_MODEL" \
  --json > "${WORKFLOW_SESSION}.jsonl" 2> "${WORKFLOW_SESSION}.err" &

ORCH_PID=$!
echo "Orchestrator PID: $ORCH_PID  Session: $WORKFLOW_SESSION"
echo "Monitor: python -m src.cli visualize --session $WORKFLOW_SESSION --follow"
```

**Note:** If running from inside an existing slo agent session, prefer the background form and use the monitor loop in Step 5 to poll for completion rather than blocking the current session.

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

### Programmatic monitoring (poll from script)

The orchestrator run is complete when its JSONL output contains a terminal event (`run_completed`, `run_failed`, or `run_aborted`). Poll the output file:

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

### Monitoring from inside a slo agent session (bash tool)

When the orchestrator is launched as a background process from within a slo agent turn, use the bash tool to poll:

```bash
# Check every 60 seconds for up to 2 hours
SESSION_FILE="${WORKFLOW_SESSION}.jsonl"
for i in $(seq 1 120); do
  if grep -q '"run_completed"\|"run_failed"\|"run_aborted"' "$SESSION_FILE" 2>/dev/null; then
    STATUS=$(grep -o '"kind":"run_[a-z_]*"' "$SESSION_FILE" | tail -1 | cut -d'"' -f4)
    echo "Terminal state reached: $STATUS"
    break
  fi
  echo "[$i/120] Still running... sleeping 60s"
  sleep 60
done
```

---

## Step 6 — Serial vs. parallel phase dispatch inside the orchestrator

The orchestrator (running as the `--orchestrator` headless process) uses `spawn_sub_agents` to dispatch phases. The dispatch strategy is determined by the workflow type:

### Serial phases (Pipeline workflow — most workflows)

Pipeline workflows dispatch **one phase at a time** using `mode="single"`. Each phase must complete and return a terminal verdict before the next phase is dispatched.

```json
// Correct: dispatch Phase 1 alone
{
  "mode": "single",
  "tasks_json": "[{\"task_id\": \"phase-1\", \"prompt\": \"<self-contained phase 1 prompt>\", \"cwd\": \"/path\", \"model\": \"claude-sonnet-4-6\"}]"
}

// After phase-1 returns READY: dispatch Phase 2 alone
{
  "mode": "single",
  "tasks_json": "[{\"task_id\": \"phase-2\", \"prompt\": \"<self-contained phase 2 prompt incorporating phase 1 outputs>\", \"cwd\": \"/path\", \"model\": \"claude-sonnet-4-6\"}]"
}
```

**Chain shorthand:** If Phase 2's prompt can be templated with the Phase 1 result, use `mode="chain"` with `{previous}`:

```json
{
  "mode": "chain",
  "tasks_json": "[
    {\"task_id\": \"phase-1\", \"prompt\": \"<phase 1 prompt>\"},
    {\"task_id\": \"phase-2\", \"prompt\": \"Using the prior result: {previous}\\n\\n<phase 2 instructions>\"}
  ]"
}
```

`mode="chain"` runs tasks sequentially and injects the previous task's answer into `{previous}` in the next prompt. A failed step stops the chain.

### Parallel phases (Parallel workflow)

Parallel workflows dispatch **all independent phases in one call** using `mode="parallel"`. A subsequent synthesis phase runs as a separate `mode="single"` call after all parallel phases complete.

```json
// Dispatch all independent phases at once
{
  "mode": "parallel",
  "tasks_json": "[
    {\"task_id\": \"phase-auth\",    \"prompt\": \"<auth module analysis prompt>\", \"model\": \"claude-sonnet-4-6\"},
    {\"task_id\": \"phase-db\",      \"prompt\": \"<db module analysis prompt>\",   \"model\": \"claude-sonnet-4-6\"},
    {\"task_id\": \"phase-api\",     \"prompt\": \"<api module analysis prompt>\",  \"model\": \"claude-sonnet-4-6\"}
  ]"
}

// After all complete: synthesis
{
  "mode": "single",
  "tasks_json": "[{\"task_id\": \"synthesis\", \"prompt\": \"Synthesize findings from auth, db, and api reviews: <insert phase results>\"}]"
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
| `0` | `run_completed` — success | Extract synthesis; workflow done. |
| `1` | `run_failed` | Read stderr: `tail -30 "${WORKFLOW_SESSION}.err"`. Check which phase failed in the JSONL. Retry with `--resume "$WORKFLOW_SESSION"` after fixing the root cause. |
| `2` | `run_aborted` | Aborted (SIGINT / timeout). Resume if partial work exists, or relaunch. |

---

## Step 8 — Environment variable summary

All variables relevant to a headless workflow launch:

| Variable | Recommended value | Default | Guards |
|---|---|---|---|
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | `10800` | Orchestrator's own LLM stream. Keep it at or above the shipped default. |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | `7200` | Each child sub-agent's stdout pipe. |
| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1200` | `600` | Bash tool per-command ceiling inside sub-agents. |
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `6` | `4` | Maximum simultaneous child processes. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | `8` | Maximum tasks per `spawn_sub_agents` call. |
| `SLO_MODEL_POOL` | JSON pool array | — | Multi-provider fallback on rate limits. |
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
ORCHESTRATOR_MODEL="claude-sonnet-4-6"
SLO_SRC="${SLO_SRC:-$HOME/Code/slo/slo}"   # path to slo source root

# ── Session id ────────────────────────────────────────────────────────────────
SESSION="${WORKFLOW_NAME}-$(date +%Y%m%d-%H%M%S)"

# ── Timeout and concurrency env vars ─────────────────────────────────────────
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200
export SLO_SUBAGENT_MAX_CONCURRENCY=6

# ── Task prompt (context only — orchestrator knows the workflow protocol) ─────
TASK_PROMPT="$(cat <<EOF
Use the ${WORKFLOW_NAME} workflow to implement the feature described in:
  ${SPEC_PATH}

Repository root: ${PROJECT_ROOT}
Current branch: ${BRANCH} (already checked out)
Git user email: ${GIT_EMAIL}
Workflow file: skills/design-and-analysis/workflows/${WORKFLOW_NAME}.md

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
        Export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200

Step 2: Choose orchestrator model (and optionally per-phase models)

Step 3: Set SESSION id and build task prompt (context only, not orchestrator instructions)

Step 4: Launch with --orchestrator --enable-history --session-id --cwd --model
        Immediately output session id + visualize command to user (mandatory)

Step 5: Monitor via visualizer or poll output JSONL for terminal event

Step 6: Serial phases → mode="single" per phase; chain → mode="chain"
        Parallel phases → mode="parallel", then mode="single" for synthesis

Step 7: Extract results, inspect child transcripts, handle failures / resume

Step 8: All env var reference in table above
```
