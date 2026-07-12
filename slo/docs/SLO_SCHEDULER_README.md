# Slo Scheduler Guide

Detailed reference for the scheduled-tasks system in `slo/`.

This document covers:

- the schedule CLI surface and every supported option,
- how scheduled fires interact with headless runs and already-running TUI sessions,
- the recurring-delivery model for fresh and continuous schedules,
- the OS wake-up path on macOS and Linux,
- the reporting and inbox/coalescing behavior,
- and a code-level control-flow walkthrough of the implementation.

---

## Table of Contents

1. [What the scheduler is](#what-the-scheduler-is)
2. [Core concepts](#core-concepts)
3. [Quick start](#quick-start)
4. [Command reference](#command-reference)
5. [Detailed command examples](#detailed-command-examples)
6. [Running a scheduled fire against an already-running TUI session](#running-a-scheduled-fire-against-an-already-running-tui-session)
7. [Recurring invocation behavior](#recurring-invocation-behavior)
8. [How the scheduler wakes up](#how-the-scheduler-wakes-up)
9. [Headless runs, orchestrator behavior, and TUI interaction](#headless-runs-orchestrator-behavior-and-tui-interaction)
10. [Run records and reporting](#run-records-and-reporting)
11. [Control flow walkthrough](#control-flow-walkthrough)
12. [Code walkthrough](#code-walkthrough)
13. [Support matrix and current limitations](#support-matrix-and-current-limitations)

---

## What the scheduler is

The scheduler lets Slo persist a prompt plus a trigger, then fire that prompt later without a human sitting in the TUI.

At runtime, a fire ends up in one of three delivery paths:

1. `fresh_headless`
   A new headless `slo run` process is started.
2. `resume_headless`
   An existing history-backed session is resumed headlessly with `slo run --resume`.
3. `session_inbox`
   Work is queued into an already-running TUI-owned session instead of starting a second writer.

The scheduler is not a long-lived daemon inside Slo. It is an OS-scheduler integration:

- macOS uses `launchd`
- Linux uses `cron`

Those platform schedulers wake up and invoke:

```bash
slo schedule execute --name <schedule-id>
```

That CLI command loads the persisted schedule and runs the scheduling runtime.

---

## Core concepts

### Schedule definition

A schedule definition is the stable, human-authored part of a schedule:

- `name`
- `trigger`
- `prompt`
- `cwd`
- `model`
- `session_mode`
- optional continuous-session policy

It is stored under:

```text
$SLO_HOME/schedules/<schedule_id>/schedule.md
```

### Mutable state

Each schedule also has mutable state in:

```text
$SLO_HOME/schedules/<schedule_id>/state.json
```

This tracks:

- last run time
- last status
- last session id
- last delivery path
- last delivery state
- run count

### Run records

Each fire appends an immutable run record under:

```text
$SLO_HOME/schedules/<schedule_id>/runs/<run_id>.json
```

This is the reporting trail for executed, queued, coalesced, and skipped fires.

### Session modes

The scheduler has two user-facing session modes.

#### `fresh`

Each fire runs as a new headless invocation.

Use this for:

- daily summaries
- batch checks
- one-off analyses
- jobs that should not accumulate conversation state

#### `continuous`

Each fire targets one evolving conversation over time.

Use this for:

- repo-watch monitoring
- recurring release-prep sessions
- operational reviews that should accumulate state
- long-lived agent threads that should preserve context

### Active vs inactive continuous targets

For continuous schedules, the runtime decides between:

- `session_inbox` when the target session is already open in the TUI and currently leased by that TUI process,
- `resume_headless` when the target session exists but is not actively owned by a TUI,
- `fresh_headless` with a seeded session id on the first fire of a schedule-owned continuous session.

### Coalescing

Continuous schedules can coalesce pending inbox items when a TUI session is already active.

Current modes:

- `none`
- `latest_by_key`

`latest_by_key` means:

- if a pending inbox item already exists with the same `coalescing_key`,
- the newer fire replaces the older pending item,
- and the fire is reported as `delivery_state="coalesced"`.

---

## Quick start

Create a fresh daily schedule:

```bash
slo schedule add \
  --name "Daily Summary" \
  --prompt "Summarize the repo changes from today." \
  --cron "0 18 * * *" \
  --session-mode fresh
```

Create a continuous repo-watch schedule that targets one session:

```bash
slo schedule add \
  --name "Repo Watch" \
  --prompt "Check the repo and summarize new failures." \
  --cron "*/15 * * * *" \
  --session-mode continuous \
  --session-reference release-prep \
  --coalescing-mode latest_by_key \
  --coalescing-key repo-watch
```

List schedules:

```bash
slo schedule list
```

Fire one schedule immediately:

```bash
slo schedule execute --name "Repo Watch"
```

Install a schedule into the OS scheduler:

```bash
slo schedule install --name "Repo Watch"
```

Inspect run records:

```bash
slo schedule reports --name "Repo Watch"
slo schedule show-report --name "Repo Watch" --run-id <run-id>
```

---

## Command reference

All scheduler commands live under:

```bash
slo schedule ...
```

### `slo schedule add`

Create one new persisted schedule definition.

#### Options

| Option | Required | Meaning |
|---|---|---|
| `--name` | yes | Human-facing schedule name |
| `--prompt` | yes | Prompt to run for each fire |
| `--cron` | exactly one trigger option | Five-field cron expression |
| `--interval-seconds` | exactly one trigger option | Interval trigger in seconds |
| `--run-at` | exactly one trigger option | ISO8601 timestamp for one-shot fire |
| `--tz` | no | Timezone for cron/calendar-style triggers; default `UTC` |
| `--cwd` | no | Working directory override passed to the headless run |
| `--model` | no | Model override passed to the headless run |
| `--session-mode` | no | `fresh` or `continuous`; default `fresh` |
| `--session-reference` | no | Target session id or unique session name for continuous schedules |
| `--coalescing-mode` | no | `none` or `latest_by_key`; default `none` |
| `--coalescing-key` | no | Pending-item coalescing key |

#### Validation rules

- exactly one of `--cron`, `--interval-seconds`, or `--run-at` must be provided
- `fresh` forbids:
  - `--session-reference`
  - non-default `--coalescing-mode`
  - `--coalescing-key`
- `continuous` allows:
  - explicit `--session-reference`
  - coalescing
- `--coalescing-key` requires `--coalescing-mode latest_by_key`

### `slo schedule edit`

Rewrite one existing schedule definition in place.

#### Options

The same options as `add`, plus:

| Option | Required | Meaning |
|---|---|---|
| `--name` | yes | Existing schedule id or normalized name |
| `--schedule-name` | yes | New human-facing schedule name |

`edit` preserves the schedule id and rewrites the definition.

### `slo schedule list`

List persisted schedules with operational metadata.

Current columns:

- `Name`
- `Mode`
- `Trigger`
- `Target Session`
- `Installed`
- `Last Delivery`

### `slo schedule show`

Show one schedule summary:

- name
- mode
- target session
- last delivery

### `slo schedule execute`

Execute one fire immediately for the named schedule.

This is the canonical scheduler entrypoint used by the OS integration.

### `slo schedule run`

Alias for `execute`.

### `slo schedule install`

Register the schedule with the local OS scheduler.

### `slo schedule uninstall`

Remove the schedule from the local OS scheduler.

### `slo schedule reports`

List immutable run records for one schedule.

Current output shape:

```text
<run_id> | <delivery_path> | <delivery_state>
```

### `slo schedule show-report`

Show one immutable run record in detail.

Current fields surfaced:

- `delivery_path`
- `delivery_state`
- `session_id`
- `target_session_id`
- `coalesced_fire_count`

### `slo schedule cleanup`

Prune old run records while keeping the newest `--keep` by recorded fire time.

#### Options

| Option | Required | Meaning |
|---|---|---|
| `--name` | yes | Schedule id or normalized name |
| `--keep` | no | Number of newest run records to retain; default `100` |

---

## Detailed command examples

### Example: a fresh daily summary

```bash
slo schedule add \
  --name "Daily Summary" \
  --prompt "Summarize the repo changes and failing tests from today." \
  --cron "0 18 * * *" \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --model claude-opus-4-8 \
  --session-mode fresh
```

What happens:

- the schedule is stored under `$SLO_HOME/schedules/<uuid>/`
- each fire starts a new `slo run`
- no prior conversation state is resumed
- the fire is reported as `fresh_headless` when executed

### Example: a one-shot fresh run

```bash
slo schedule add \
  --name "One Shot Release Audit" \
  --prompt "Audit the release branch and summarize deployment blockers." \
  --run-at "2026-07-20T09:00:00+07:00" \
  --session-mode fresh
```

Use this when you want one future fire and no recurring conversation.

### Example: a continuous schedule targeting a known session

```bash
slo schedule add \
  --name "Release Prep" \
  --prompt "Review release-readiness and append any new blockers." \
  --cron "0 */2 * * *" \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --session-mode continuous \
  --session-reference release-prep
```

What happens:

- if `release-prep` is currently open in a TUI, the fire queues into that session inbox
- if `release-prep` exists but is not active in a TUI, the fire resumes it headlessly
- if `release-prep` is a slug that does not yet exist, the runtime can seed that exact session id

### Example: continuous repo watch with coalescing

```bash
slo schedule add \
  --name "Repo Watch" \
  --prompt "Check the repo and summarize new failures, flaky tests, and regressions." \
  --interval-seconds 300 \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --session-mode continuous \
  --session-reference repo-watch \
  --coalescing-mode latest_by_key \
  --coalescing-key repo-watch
```

This is the right pattern for high-frequency monitoring:

- if the TUI session is active and idle, a fire queues immediately
- if another pending item already exists, the newer fire replaces it
- the run record shows `coalesced`

### Example: edit a schedule

```bash
slo schedule edit \
  --name "Repo Watch" \
  --schedule-name "Repo Watch" \
  --prompt "Check the repo and summarize only new failing tests since the last fire." \
  --interval-seconds 600 \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --session-mode continuous \
  --session-reference repo-watch \
  --coalescing-mode latest_by_key \
  --coalescing-key repo-watch
```

### Example: list and inspect schedules

```bash
slo schedule list
slo schedule show --name "Repo Watch"
```

Example list output:

```text
Name | Mode | Trigger | Target Session | Installed | Last Delivery
Repo Watch | continuous | interval:300s | repo-watch | installed | session_inbox:queued
Daily Summary | fresh | cron:0 18 * * * | - | not-installed | fresh_headless:executed
```

### Example: run a fire now

```bash
slo schedule execute --name "Repo Watch"
```

This is the fastest way to validate the runtime path without waiting for the OS scheduler.

### Example: install and uninstall

```bash
slo schedule install --name "Repo Watch"
slo schedule uninstall --name "Repo Watch"
```

### Example: inspect reports and prune them

```bash
slo schedule reports --name "Repo Watch"
slo schedule show-report --name "Repo Watch" --run-id 6d9a7e5b-b0af-4a8c-8f8f-0f0e9895e6b0
slo schedule cleanup --name "Repo Watch" --keep 25
```

---

## Running a scheduled fire against an already-running TUI session

This is the most important safety path in the design.

### Why this exists

An active TUI session is already the writer for that conversation:

- it owns the in-memory session state,
- it is streaming events live,
- and it can already be mid-turn.

Starting a second headless `--resume` process against the same active session would create a split-brain writer problem.

The scheduler avoids that by using a lease + inbox model.

### How to use it

1. Start or resume a history-backed session in the TUI.
2. Keep that session open.
3. Create a continuous schedule that targets that session.
4. Fire the schedule manually or let the OS scheduler fire it.

Practical example:

In terminal 1, open the TUI and resume a session:

```bash
slo --resume release-prep
```

In terminal 2, create and fire a continuous schedule:

```bash
slo schedule add \
  --name "Release Prep" \
  --prompt "Review release blockers and append only new findings." \
  --cron "*/30 * * * *" \
  --session-mode continuous \
  --session-reference release-prep \
  --coalescing-mode latest_by_key \
  --coalescing-key release-prep

slo schedule execute --name "Release Prep"
```

If the TUI session is actively leased:

- the runtime does **not** spawn a second `slo run`
- it enqueues a `SessionInboxMessageDAO`
- the TUI polls its inbox
- if idle, the TUI starts a new chat turn from that queued work

### What the TUI is doing under the hood

When a history-backed session mounts, the TUI:

- acquires a session lease,
- renews it on a heartbeat,
- polls the session inbox only when idle,
- claims the next pending inbox message,
- renders a note or notice,
- starts a normal prompt turn for `chat_turn` delivery,
- and acknowledges the inbox message when done.

This is how recurring scheduled work can safely feed into a live session without creating concurrent writers.

---

## Recurring invocation behavior

Recurring behavior depends on both session mode and whether a target session is active.

### Fresh schedules

Every fire is independent.

Control pattern:

```text
fire
  -> start headless process
  -> run prompt
  -> persist one run record
  -> exit
```

Use fresh schedules when you want:

- no accumulation of state,
- one report per fire,
- fully isolated runs.

### Continuous schedules with explicit target session

Control pattern:

```text
fire
  -> resolve target session
  -> if active in TUI: queue inbox work
  -> else: resume headlessly
```

This is the best pattern for long-running work threads.

### Continuous schedules without explicit session reference

The first fire seeds a stable schedule-owned session id:

```text
schedule-<schedule_id>
```

After that:

- later fires can reuse that session id,
- the mutable schedule state carries the last session id,
- and the runtime can keep continuing the same conversation over time.

### Coalescing and high-frequency schedules

High-frequency schedules should usually use:

```bash
--coalescing-mode latest_by_key
--coalescing-key <stable-key>
```

This matters only for the active-session inbox path.

It prevents:

- a backlog of stale queued prompts,
- repeated delivery of obsolete state snapshots,
- and a TUI session being flooded when the operator returns after being away.

---

## How the scheduler wakes up

Slo does not ship an internal polling loop that sleeps and checks schedules.

Instead:

1. You persist a schedule with `slo schedule add`.
2. You register it with the OS via `slo schedule install`.
3. The OS scheduler invokes `slo schedule execute --name <schedule-id>`.
4. The Slo runtime loads the schedule and handles one fire.

### macOS wake-up path

On macOS, `launchd` writes one plist per schedule under:

```text
~/Library/LaunchAgents/com.slo.schedule.<name_key>.plist
```

That plist launches:

```text
slo schedule execute --name <schedule_id>
```

Current support in the launchd installer:

- cron triggers
- interval triggers

Current non-support:

- one-shot triggers
- calendar triggers

### Linux wake-up path

On Linux, the cron installer rewrites the user crontab with a stable marker block:

```text
# slo-schedule:<schedule_id>
<cron-expression> <slo> schedule execute --name <schedule_id> >> <stdout-log> 2>> <stderr-log>
# /slo-schedule:<schedule_id>
```

Current support in the cron installer:

- cron triggers only

Current non-support:

- interval triggers
- one-shot triggers
- calendar triggers

### Logs for OS-triggered fires

The OS integration also provisions scheduler log files under:

```text
$SLO_HOME/schedules/logs/
```

Those logs capture the outer scheduler invocation, not the semantic run record. The authoritative delivery/result metadata is still the JSON run record under `runs/`.

---

## Headless runs, orchestrator behavior, and TUI interaction

### Headless path

When the runtime chooses headless execution, it launches:

```bash
slo run --prompt "<prompt>" --json [--cwd ...] [--model ...]
```

For resumed continuous runs it adds:

```bash
--resume <session-reference>
```

For schedule-owned first continuous fires it can add:

```bash
--enable-history --session-id <seeded-id>
```

### Important note about orchestrator mode

Current scheduler behavior does **not** add:

```bash
--orchestrator
```

That means scheduled headless fires currently use the standard headless run path, not the explicit sub-agent-orchestrator bootstrap path.

Practical consequence:

- a scheduled fire can still execute normal agent work,
- it can still resume a real conversation,
- but the scheduler itself does not currently opt the run into orchestrator mode.

If you need scheduled runs to bootstrap the sub-agent pool automatically, that would require a follow-up change in `ScheduleSubprocessRunner`.

### Interaction with an already-running TUI session

When the target session is active in the TUI:

- the scheduler does not start a headless resume process,
- it delivers work through `SessionInboxStore`,
- the TUI picks that up when idle,
- and the TUI performs the actual prompt submission inside the existing session process.

This is the one-writer guarantee.

---

## Run records and reporting

Every fire produces exactly one normalized outcome record.

Important fields:

| Field | Meaning |
|---|---|
| `run_id` | Fire identity |
| `started_at` / `finished_at` | Fire timestamps |
| `status` | Child-run terminal status when a child process actually ran |
| `delivery_path` | `fresh_headless`, `resume_headless`, `session_inbox`, or `none` |
| `delivery_state` | `executed`, `queued`, `coalesced`, `skipped_disabled`, `skipped_overlapping` |
| `session_id` | Session created or resumed by the fire |
| `target_session_id` | Intended target session |
| `exit_code` | Child-process exit code when a subprocess ran |
| `summary` | High-level text summary |
| `stdout_summary` / `stderr_summary` | Clipped process output |
| `skipped_reason` | Human-readable skip reason |
| `coalesced_fire_count` | Older pending fires replaced by this fire |

### Delivery reporting examples

Fresh success:

```text
delivery_path: fresh_headless
delivery_state: executed
status: completed
```

Inactive continuous target:

```text
delivery_path: resume_headless
delivery_state: executed
session_id: <resumed-session-id>
```

Active continuous target:

```text
delivery_path: session_inbox
delivery_state: queued
```

Coalesced active target:

```text
delivery_path: session_inbox
delivery_state: coalesced
coalesced_fire_count: 1
```

Skipped disabled schedule:

```text
delivery_path: none
delivery_state: skipped_disabled
```

Skipped overlap:

```text
delivery_path: none
delivery_state: skipped_overlapping
```

### Cleanup behavior

`slo schedule cleanup --keep N` now keeps the newest `N` run records by recorded `started_at`.

This matters because `run_id` is a UUID and should not be used as a chronological ordering key.

---

## Control flow walkthrough

This is the end-to-end control flow for a typical installed recurring schedule.

### Path A: OS fires a fresh schedule

```text
launchd/cron wake up
  -> run `slo schedule execute --name <schedule-id>`
  -> CLI builds ScheduleExecutor with real lease/inbox stores
  -> ScheduleStore.load(reference=...)
  -> overlap lock acquired
  -> session_mode == fresh
  -> ScheduleSubprocessRunner.run_fresh(...)
  -> `slo run --prompt ... --json ...`
  -> child exits
  -> ScheduleReportWriter.write(...)
  -> run record appended
  -> state.json updated
```

### Path B: OS fires a continuous schedule while the target TUI is active

```text
launchd/cron wake up
  -> run `slo schedule execute --name <schedule-id>`
  -> ScheduleExecutor.execute(...)
  -> resolve target session
  -> SessionOwnershipLeaseStore.is_active(session_id=...)
  -> active == true
  -> SessionInboxStore.enqueue(...)
  -> run record written as session_inbox + queued/coalesced
  -> TUI heartbeat/poll loop claims inbox item
  -> TUI starts a normal prompt turn in the existing session
```

### Path C: OS fires a continuous schedule while the target session is inactive

```text
launchd/cron wake up
  -> run `slo schedule execute --name <schedule-id>`
  -> resolve target session
  -> lease inactive
  -> ScheduleSubprocessRunner.run_resume(...)
  -> `slo run --prompt ... --json --resume <reference>`
  -> resumed headless run completes
  -> run record written as resume_headless + executed
```

---

## Code walkthrough

### CLI surface

Primary file:

- `src/cli/schedule/app.py`

Responsibilities:

- define the Typer subcommands,
- parse scheduler flags,
- build validated schedule definitions,
- invoke `ScheduleExecutor`,
- invoke `ScheduleOSIntegration`,
- render list/show/report output.

### Persistent model and store

Primary files:

- `src/scheduling/dao.py`
- `src/scheduling/store.py`

Responsibilities:

- define trigger variants and schedule DAOs,
- validate fresh vs continuous constraints,
- persist `schedule.md`,
- persist `state.json`,
- append immutable run records,
- resolve schedule id or normalized name references.

### Runtime executor

Primary files:

- `src/scheduling/runtime/executor.py`
- `src/scheduling/runtime/dao.py`
- `src/scheduling/runtime/reporting.py`
- `src/scheduling/runtime/cleanup.py`

Responsibilities:

- decide whether the fire is skipped, headless, resumed, or inbox-delivered,
- normalize every fire into one `ScheduleExecutionOutcomeDAO`,
- write reports and mutable schedule state,
- prune old records safely by fire time.

### Session targeting

Primary file:

- `src/scheduling/runtime/session_target_resolver.py`

Responsibilities:

- resolve explicit session references,
- reuse `last_session_id` when available,
- seed a schedule-owned session id when needed.

### Overlap protection

Primary file:

- `src/scheduling/runtime/fire_lock.py`

Responsibility:

- create one filesystem lock per schedule fire to prevent overlapping execution of the same schedule.

### Headless subprocess path

Primary file:

- `src/scheduling/runtime/subprocess_runner.py`

Responsibilities:

- construct the `slo run` argv,
- pass through `cwd`, `model`, `--resume`, `--enable-history`, and seeded `--session-id`,
- normalize child exit status and clipped output.

### OS integration

Primary files:

- `src/scheduling/os/integration.py`
- `src/scheduling/os/launchd.py`
- `src/scheduling/os/cron.py`
- `src/scheduling/os/executable_locator.py`
- `src/scheduling/os/logs.py`
- `src/scheduling/os/status.py`

Responsibilities:

- route install/uninstall/status by platform,
- locate the `slo` executable,
- render launchd plists or cron marker blocks,
- manage scheduler stdout/stderr log paths.

### TUI inbox and lease path

Primary files:

- `src/agents/slo_agent/history/inbox/dao.py`
- `src/agents/slo_agent/history/inbox/lease.py`
- `src/agents/slo_agent/history/inbox/store.py`
- `src/tui/app.py`

Responsibilities:

- represent inbox messages and lease records,
- maintain a maildir-like inbox layout,
- track active ownership of a history-backed session,
- poll and claim scheduled work from the TUI only when idle,
- turn inbox `chat_turn` messages into normal prompt submissions.

---

## Support matrix and current limitations

### Trigger creation from the CLI

Current `slo schedule add` / `edit` support:

- cron
- interval
- one-shot (`--run-at`)

Current CLI non-support:

- calendar trigger creation

`CalendarTriggerDAO` exists in the storage model and list formatting, but the current CLI does not expose a calendar-trigger builder.

### OS installation support

macOS `launchd`:

- supports cron triggers
- supports interval triggers
- does not support one-shot triggers
- does not support calendar triggers

Linux `cron`:

- supports cron triggers
- does not support interval triggers
- does not support one-shot triggers
- does not support calendar triggers

### Orchestrator-mode scheduling

Current limitation:

- scheduled headless fires do not automatically pass `--orchestrator`

So the scheduler currently interacts with the standard headless runner, not the explicit headless orchestrator bootstrap mode.

### Skip taxonomy

Current emitted skip states:

- `skipped_disabled`
- `skipped_overlapping`

There is no emitted `skipped_exception` state in the current implementation.

### One-writer safety

What is guaranteed:

- if a target session is actively owned by a TUI, scheduled work is delivered through the inbox instead of a second resume process

What is not guaranteed:

- if a schedule targets a session but the TUI is not currently holding the lease, the scheduler can legitimately resume that session headlessly

That is intended behavior.

---

## Practical recipes

### Recipe: recurring daily report with no state

```bash
slo schedule add \
  --name "Daily Failures" \
  --prompt "Summarize all failing tests in the repo." \
  --cron "0 9 * * *" \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --session-mode fresh

slo schedule install --name "Daily Failures"
```

### Recipe: one rolling operational session

```bash
slo schedule add \
  --name "Ops Review" \
  --prompt "Review incidents and append only new action items." \
  --cron "0 * * * *" \
  --cwd /Users/sidravic/Code/slo-harness/slo \
  --session-mode continuous \
  --session-reference ops-review \
  --coalescing-mode latest_by_key \
  --coalescing-key ops-review
```

Open that session in the TUI when you want live delivery:

```bash
slo --resume ops-review
```

### Recipe: validate the inbox path without waiting for cron

Keep the target session open in the TUI, then from another terminal:

```bash
slo schedule execute --name "Ops Review"
slo schedule reports --name "Ops Review"
```

You should see a queued or coalesced `session_inbox` run record, and the TUI should start handling the work when idle.

