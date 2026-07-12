---
name: tui-scheduled-operations
description: Operate generic scheduled tasks from an interactive TUI session,
  including delayed jobs, recurring in-session updates, and stop-on-request schedules.
when_to_use: Use when a TUI-session user wants any non-workflow-specific scheduled
  operation such as recurring reminders, periodic checks, or repeated output like
  printing the time every 5 seconds until stopped.
group: tui
kind: skill
---

# TUI Scheduled Operations

## Skill summary

- **Name:** `tui-scheduled-operations`
- **Description:** Operate generic scheduled tasks from an interactive TUI session, including delayed jobs, recurring in-session updates, and stop-on-request schedules.
- **When to use:** Use when a TUI-session user wants any non-workflow-specific scheduled operation such as recurring reminders, periodic checks, or repeated output like printing the time every 5 seconds until stopped.
- **Group:** `tui`
- **Kind:** `skill`

## Examples

- The user asks: "Print the time on the screen every 5 seconds until I ask you to stop."
- The user asks: "Schedule a reminder in this session for 30 minutes from now."
- The user asks: "Run a repo drift check every 10 minutes and report back here."

## Guidance

## Specialized-use rule

This skill covers **generic scheduled operations** started from an interactive
TUI session.

Load it when:

- the user wants a recurring or delayed operation that should happen later,
- the user wants repeated output or checks posted back into the current TUI
  session,
- the user asks for a schedule that continues "until I stop it",
- the task is not specifically about supervising a dynamic workflow
  orchestrator.

If the task is specifically about monitoring and recovering a headless
orchestrator plus child agents, load
`skills/tui/tui-scheduled-workflows/SKILL.md` instead.

---

## What this skill governs

Use the scheduler as a durable timer and wake-up mechanism for any supported
recurring or delayed operation, including:

- repeated reminders,
- recurring summaries,
- periodic checks,
- one-shot delayed follow-up actions,
- continuous session loops that post updates back into the open TUI.

The scheduler is the correct tool whenever the user wants work to happen
**later** or **repeatedly**, rather than immediately inside the current turn.

---

## Capability model

The scheduler supports three operational shapes:

1. **One-shot delayed fire**
   - Use `--run-at <iso8601>`
   - Best for "remind me in 30 minutes", "check this later today", or one
     delayed follow-up.

2. **Fixed-interval recurrence**
   - Use `--interval-seconds <n>`
   - Best for "every 5 seconds", "every 2 minutes", or polling-style loops.

3. **Wall-clock recurrence**
   - Use `--cron "<expr>"`
   - Best for daily, hourly, weekday, or time-of-day schedules.

Each schedule can run in one of two session modes:

- `fresh`
  - Every fire becomes a new headless run.
  - Use when each execution should be stateless.

- `continuous`
  - Every fire targets one evolving conversation.
  - Use when scheduled work should accumulate context or be delivered into a
    live TUI session.

---

## Choosing the right mode

### Use `fresh` when:

- the user wants independent recurring jobs,
- every execution should stand on its own,
- output does not need to return into the live TUI transcript.

Example:

```bash
slo schedule add \
  --name "daily repo summary" \
  --prompt "Summarize repo changes from the last 24 hours." \
  --cron "0 18 * * *" \
  --cwd "<repo-root>" \
  --session-mode fresh
```

### Use `continuous` when:

- the user wants scheduled output to appear in the current session,
- repeated turns should preserve prior context,
- the schedule should keep working "until I ask you to stop".

Example:

```bash
slo schedule add \
  --name "clock printer" \
  --prompt "Print the current time in this session and nothing else." \
  --interval-seconds 5 \
  --session-mode continuous \
  --session-reference "<named-tui-session>" \
  --coalescing-mode latest_by_key \
  --coalescing-key "clock-printer"
```

---

## Current implementation constraints

1. **A continuous TUI-targeted schedule needs a stable session reference.**
   - Prefer a unique session name.
   - If the current TUI session has no stable name, rename it before scheduling.

2. **The scheduler is OS-driven.**
   - Installing the schedule is what makes it durable:
     `slo schedule install --name "<schedule-name>"`

3. **Fast recurring TUI schedules should use coalescing.**
   - For frequent intervals such as 5s, 10s, or 30s, use:
     - `--coalescing-mode latest_by_key`
     - `--coalescing-key <stable-key>`
   - This avoids unbounded buildup of pending inbox items.

4. **Stopping a schedule is a cleanup operation, not just "ignore it".**
   - When the user says stop, disable or remove the schedule explicitly.
   - Do not leave a live OS-installed schedule behind.

5. **There is no public delete command yet.**
   - Full removal is:
     1. `slo schedule uninstall --name "<schedule-name>"`
     2. delete the persisted schedule record through `ScheduleStore.delete(...)`

---

## Standard operating procedure

Whenever the user requests a scheduled operation, follow this exact sequence.

### Step 1 — Translate the request into a scheduler shape

Decide:

- one-shot vs interval vs cron,
- fresh vs continuous,
- whether the current TUI session is the target,
- whether coalescing is needed,
- what the stop condition is.

Examples:

- "print the time every 5 seconds until I ask you to stop"
  - interval
  - continuous
  - current TUI session target
  - coalescing enabled
  - manual stop by user

- "check this again at 5 PM"
  - one-shot
  - fresh or continuous depending on whether the result should come back here

- "summarize CI failures every 15 minutes"
  - interval
  - usually fresh for headless reports, continuous if the user wants it in-session

### Step 2 — Create the schedule

Use `slo schedule add ...` with explicit flags.

For the "print the time every 5 seconds until I ask you to stop" example:

```bash
slo schedule add \
  --name "clock printer" \
  --prompt "Print the current time in this session. Keep the message concise." \
  --interval-seconds 5 \
  --session-mode continuous \
  --session-reference "<named-tui-session>" \
  --coalescing-mode latest_by_key \
  --coalescing-key "clock-printer"
```

If the operation depends on repository context, also include:

```bash
--cwd "<repo-root>"
```

### Step 3 — Install the schedule

Always install it after creation:

```bash
slo schedule install --name "<schedule-name>"
```

### Step 4 — Report the live control surface

After setup, tell the user:

- the schedule name,
- the trigger,
- the mode,
- the target session if continuous,
- and the commands to inspect it:

```bash
slo schedule show --name "<schedule-name>"
slo schedule reports --name "<schedule-name>"
```

### Step 5 — Stop when the user asks

If the user says stop, pause, cancel, remove, or equivalent:

1. uninstall it:

```bash
slo schedule uninstall --name "<schedule-name>"
```

2. delete the persisted schedule:

```bash
PYTHONPATH=$(pwd) poetry run python - <<'PY'
from src.scheduling.store import ScheduleStore

loaded = ScheduleStore.load(reference="<schedule-name>")
deleted = ScheduleStore.delete(schedule_id=loaded.schedule_id)
print(f"deleted={deleted}")
PY
```

3. tell the user the schedule is no longer active.

---

## Patterns

### Pattern A — Repeated in-session output

Use `continuous` plus a session reference.

Good examples:

- print the time every 5 seconds,
- check a file every minute and report changes,
- post a lightweight heartbeat into the session.

Recommended flags:

- `--session-mode continuous`
- `--session-reference "<named-session>"`
- `--coalescing-mode latest_by_key`
- `--coalescing-key "<stable-key>"`

### Pattern B — Periodic repo or system checks

Use `fresh` if each run is independent.

Example:

```bash
slo schedule add \
  --name "repo drift check" \
  --prompt "Check git status and summarize drift from HEAD." \
  --interval-seconds 300 \
  --cwd "<repo-root>" \
  --session-mode fresh
```

### Pattern C — One delayed follow-up into the same session

Use `run-at` plus `continuous`.

Example:

```bash
slo schedule add \
  --name "follow-up reminder" \
  --prompt "Remind me to review the migration output." \
  --run-at "2026-07-12T16:30:00+07:00" \
  --session-mode continuous \
  --session-reference "<named-session>"
```

---

## Anti-patterns

Avoid these:

- using `fresh` when the user explicitly wants the scheduled output to appear
  in the current TUI conversation,
- omitting a stable session reference for a continuous schedule,
- creating a fast interval schedule without coalescing,
- treating "until I ask you to stop" as implicit cleanup instead of explicit
  stop handling,
- leaving installed schedules behind after the user no longer wants them.

---

## Output contract when you use this skill

When using this skill, report:

1. the schedule shape you chose,
2. the exact command(s) used to create and install it,
3. where output will appear,
4. how the user can inspect it,
5. how it will be stopped and cleaned up.
