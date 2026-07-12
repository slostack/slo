---
name: tui-scheduled-workflows
description: Operate the scheduler from an interactive TUI session to supervise
  dynamic workflows, post recurring progress updates, recover stalled orchestrators,
  and clean up monitor schedules.
when_to_use: Use when a TUI-session user asks to monitor dynamic workflows in the
  background, schedule recurring checks into the live session, or run any scheduled
  operational loop that should wake up later and report back into a TUI conversation.
group: tui
kind: skill
---

# TUI Scheduled Workflows

## Skill summary

- **Name:** `tui-scheduled-workflows`
- **Description:** Operate the scheduler from an interactive TUI session to supervise dynamic workflows, post recurring progress updates, recover stalled orchestrators, and clean up monitor schedules.
- **When to use:** Use when a TUI-session user asks to monitor dynamic workflows in the background, schedule recurring checks into the live session, or run any scheduled operational loop that should wake up later and report back into a TUI conversation.
- **Group:** `tui`
- **Kind:** `skill`

## Examples

- The user asks: "Run dynamic workflows for this spec and keep monitoring the orchestrator from this TUI session."
- The user asks: "Set up a recurring scheduler that checks workflow progress every two minutes and posts updates here."
- The user asks: "Schedule follow-up work into this session until the release checklist is complete."

## Guidance

## Specialized-use rule

This skill is for **interactive TUI sessions** that need to use the scheduler as
an operational control loop.

Load it when:

- the user asks the TUI agent to launch `dynamic workflows` and keep monitoring
  the orchestrator and child agents in the background,
- the user asks the TUI agent to schedule recurring follow-up work into the
  current session or another named session,
- the user wants a scheduled operational loop that wakes up, posts progress
  updates, performs checks, and cleans itself up when the workflow ends.

Do **not** load this skill for a one-off background workflow launch that does not
need recurring supervision. Use
`skills/design-and-analysis/headless-orchestration/SKILL.md` for that.

---

## What this skill governs

The scheduler is the durable wake-up mechanism for TUI-driven workflow supervision.
It is how the TUI agent can:

1. create a recurring monitor,
2. have the OS wake Slo up later,
3. deliver that wake-up back into the active TUI session through the session inbox,
4. inspect orchestrator and child-agent state,
5. post a concise progress update,
6. recover a failed or stalled workflow when appropriate,
7. remove the schedule when the work is done.

Treat the scheduler as the **heartbeat** for long-running interactive workflow management.

---

## Hard constraints from the current implementation

1. **The scheduler is OS-backed, not in-process.**
   - macOS uses `launchd`.
   - Linux uses `cron`.
   - A scheduled fire wakes up by running:
     `slo schedule execute --name <schedule-id>`

2. **Continuous session-mode is required for TUI delivery.**
   - If the recurring work must post back into a TUI session, create the schedule
     with `--session-mode continuous`.
   - When the target TUI session holds an active lease, delivery becomes
     `session_inbox`.

3. **Use coalescing for monitor loops.**
   - Monitoring schedules should almost always use:
     `--coalescing-mode latest_by_key`
   - This prevents a burst of pending monitor turns from piling up while the
     session is busy.

4. **Current TUI delivery needs a stable session reference.**
   - Prefer a **unique session name** for the current TUI session.
   - If the current session is unnamed or ambiguous, have the user rename it
     before you create the schedule.
   - Do not guess a target session reference.

5. **The scheduler does not automatically add `--orchestrator`.**
   - Scheduled headless execution uses the scheduler runtime, which launches
     `slo run` or `slo run --resume`.
   - If a scheduled turn needs orchestrator-specific recovery behavior, the
     prompt delivered by the scheduler must explicitly tell the agent how to
     inspect and recover the orchestrator session.

6. **There is no public `slo schedule delete` CLI yet.**
   - Cleanup is a two-step operation:
     1. uninstall from the OS scheduler,
     2. delete the persisted schedule record from `ScheduleStore`.
   - Do not leave monitor schedules behind after completion, user abort, or a
     deliberate session shutdown.

---

## Pattern A — Supervise dynamic workflows from the current TUI session

This is the default pattern when a user says some form of:

- "launch dynamic workflows and keep an eye on them"
- "run this headlessly but monitor and recover it from here"
- "periodically check the orchestrator and sub-agents until the workflow finishes"

### Step 1 — Stabilize the identifiers first

Before creating the schedule, collect all three identifiers:

1. **TUI target session reference**
   - Prefer the current session's unique name.
   - If the session is not uniquely nameable, ask the user to rename it first.

2. **Orchestrator session reference**
   - The parent headless workflow session id or unique name.
   - Do not proceed without this.

3. **Repository root / working directory**
   - The scheduler prompt will often need to inspect history files or launch
     a recovery command from the repo root.

### Step 2 — Create a recurring monitor schedule

Use an interval-based continuous schedule that targets the live TUI session.
Recommended interval: **60 to 180 seconds**.

Template:

```bash
slo schedule add \
  --name "<workflow-name> monitor" \
  --prompt "$(cat <<'EOF'
Monitor the workflow orchestrator session <orchestrator-session-reference>.

Working directory: <repo-root>
Monitor purpose: keep the workflow moving to completion from the active TUI session.

On this scheduled turn:
1. Inspect the orchestrator history under ~/.slo/sessions/history/<orchestrator-session-reference>/.
2. Determine whether the orchestrator is:
   - still running and healthy,
   - terminal success,
   - terminal failure,
   - user-aborted,
   - stalled because a child failed or retries were exhausted.
3. Inspect child-agent captures when needed under:
   ~/.slo/sessions/history/<orchestrator-session-reference>/children/
4. Post a concise progress update into this TUI session:
   - overall state,
   - child status summary,
   - any recovery action taken,
   - next expected step.
5. If recovery is required, take exactly one recovery action for this turn.
   Prefer resuming the orchestrator session with explicit instructions rather than
   launching unrelated work.
6. If the workflow has completed successfully, has been aborted by the user, or is
   irrecoverably finished, run the cleanup procedure for schedule
   <workflow-name> monitor and state that cleanup was performed.

Recovery rules:
- Do not treat a merely long-running child as failed.
- Do not launch duplicate recoveries when the orchestrator is still making progress.
- If a child failed and the orchestrator is resumable, prefer:
  slo run --resume "<orchestrator-session-reference>" --enable-history --cwd "<repo-root>" -p "<precise recovery instruction>"
- Recovery instructions must describe the failed phase, the observed failure, and
  the minimum next step needed to unblock completion.
EOF
)" \
  --interval-seconds 120 \
  --session-mode continuous \
  --session-reference "<tui-session-reference>" \
  --coalescing-mode latest_by_key \
  --coalescing-key "workflow-monitor:<orchestrator-session-reference>" \
  --cwd "<repo-root>"
```

Use `--model <model-name>` only when the monitor loop needs a non-default model.

### Step 3 — Install the schedule into the OS scheduler

After `add`, install it:

```bash
slo schedule install --name "<workflow-name> monitor"
```

The monitor is not durable until `install` succeeds.

### Step 4 — Tell the user what is now running

After creation and installation, report:

- schedule name,
- interval,
- target TUI session reference,
- orchestrator session reference,
- cleanup trigger conditions,
- and the exact commands to inspect it:

```bash
slo schedule show --name "<workflow-name> monitor"
slo schedule reports --name "<workflow-name> monitor"
slo visualize --session "<orchestrator-session-reference>" --follow
```

### Step 5 — What each scheduled turn must do

Every delivered monitor turn must be disciplined and idempotent.

It must:

1. **Read status first.**
   - Inspect the orchestrator session history and child captures before deciding.
   - Prefer direct filesystem inspection for automation.
   - Use `slo visualize` for human-facing live inspection, not as the primary
     automation primitive inside a scheduled turn.

2. **Log one concise progress update.**
   The update should include:
   - orchestrator state,
   - child counts (`running`, `completed`, `failed`, `aborted` when determinable),
   - whether recovery was attempted,
   - what the agent expects next.

3. **Take at most one recovery action per turn.**
   This keeps the monitor loop understandable and avoids thrashing.

4. **Prefer orchestrator continuation over ad-hoc side work.**
   If the workflow is resumable, resume it with precise steering instructions.

5. **Stop monitoring when the workflow reaches a terminal state.**
   A completed or aborted workflow should not keep generating scheduled turns.

### Step 6 — Cleanup is mandatory

When the workflow is complete, aborted by the user, or the user is ending the
supervising TUI session, remove the schedule completely.

First uninstall it:

```bash
slo schedule uninstall --name "<workflow-name> monitor"
```

Then delete the persisted schedule record:

```bash
PYTHONPATH=$(pwd) poetry run python - <<'PY'
from src.scheduling.store import ScheduleStore

loaded = ScheduleStore.load(reference="<workflow-name> monitor")
deleted = ScheduleStore.delete(schedule_id=loaded.schedule_id)
print(f"deleted={deleted}")
PY
```

If the session is about to end, perform cleanup **before** the user exits the TUI.
Otherwise the lease disappears and future fires may resume headlessly instead of
staying attached to the interactive session.

---

## Pattern B — Schedule general recurring operations from the TUI

Use this pattern when the user wants scheduled work that does **not** specifically
supervise a dynamic workflow.

Choose the schedule shape by desired behavior:

- `--session-mode fresh`
  Use for standalone headless jobs such as reports, audits, summaries, and batch checks.

- `--session-mode continuous`
  Use when repeated turns should accumulate state in one conversation, or when the
  user wants recurring work delivered into a live named TUI session.

- `--run-at <iso8601>`
  Use for one delayed follow-up.

- `--interval-seconds <n>`
  Use for polling, monitoring, or short recurring loops.

- `--cron "<expr>"`
  Use for wall-clock schedules such as daily or weekday jobs.

### Fresh headless example

```bash
slo schedule add \
  --name "nightly dependency audit" \
  --prompt "Audit dependencies, summarize risks, and write a concise report." \
  --cron "0 2 * * *" \
  --cwd "<repo-root>" \
  --session-mode fresh

slo schedule install --name "nightly dependency audit"
```

### Continuous TUI-delivered example

```bash
slo schedule add \
  --name "release checklist follow-up" \
  --prompt "Review the release checklist, summarize what changed since the last turn, and post the next highest-priority action." \
  --interval-seconds 900 \
  --cwd "<repo-root>" \
  --session-mode continuous \
  --session-reference "<named-session>" \
  --coalescing-mode latest_by_key \
  --coalescing-key "release-checklist"

slo schedule install --name "release checklist follow-up"
```

---

## Reporting and operator visibility

For any schedule created from the TUI, the agent should keep the user oriented.

Always provide:

- the schedule name,
- whether it is `fresh` or `continuous`,
- the trigger form (`run-at`, `interval`, or `cron`),
- the target session when continuous,
- and the commands to inspect recent fires:

```bash
slo schedule show --name "<schedule-name>"
slo schedule reports --name "<schedule-name>"
slo schedule show-report --name "<schedule-name>" --run-id "<run-id>"
```

If the schedule is a monitor loop, also provide the visualizer command for the
orchestrator session.

---

## Anti-patterns

Avoid all of the following:

- Creating a monitor schedule in `fresh` mode when the requirement is to post
  updates back into the current TUI session.
- Omitting `latest_by_key` coalescing on a fast interval monitor and then allowing
  duplicate pending checks to accumulate.
- Using `slo visualize` as the only inspection mechanism inside a scheduled turn.
- Leaving installed monitor schedules behind after the workflow has already
  finished.
- Launching repeated recovery attempts on every fire without confirming whether the
  workflow is still making progress.
- Guessing the current TUI session reference instead of requiring a stable name.

---

## Output contract when you use this skill

When acting on this skill, report the operational plan in this order:

1. the schedule you will create,
2. the target session / orchestrator references it depends on,
3. the exact `slo schedule ...` commands being used,
4. the monitoring and recovery policy,
5. the cleanup trigger and cleanup commands.
