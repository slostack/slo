---
name: schedule-operations
description: Create operational Slo schedules and verify the shared worker is healthy; list, show, edit, trigger, start, stop, delete, report and check status through the slo schedule CLI.
when_to_use: When the user asks Slo to schedule, repeat, trigger, pause, resume, delete, report or check a scheduled prompt.
group: cli
kind: skill
---

# Schedule Operations

## Skill summary

- **Name:** `schedule-operations`
- **Description:** Create operational Slo schedules and verify the shared worker is healthy; list, show, edit, trigger, start, stop, delete, report and check status through the `slo schedule` CLI.
- **When to use:** When the user asks Slo to schedule, repeat, trigger, pause, resume, delete, report or check a scheduled prompt.
- **Group:** `cli`
- **Kind:** `skill`

## Examples

- The user asks: "Schedule a daily summary of the repo at 9am."
- The user asks: "Pause the nightly digest."
- The user asks: "Is my schedule actually running?"
- The user asks: "Show me the report for the weekly standup."

## Commands

| Verb | Required flags | `--json` | Exit codes |
|---|---|---|---|
| `add` | `--name`, `--prompt`, one of `--interval-seconds` / `--run-at` / `--cron` | yes | 0 · 1 · 2 |
| `edit` | `--schedule`, `--name`, `--prompt`, one trigger | yes | 0 · 1 · 2 |
| `show` | `--schedule` | yes | 0 · 1 |
| `list` | (none; `--disabled` optional) | yes | 0 |
| `status` | (none; `--schedule` optional) | yes | 0 · 1 |
| `trigger` | `--schedule` | no | 0 · 1 |
| `start` | `--schedule` | yes | 0 · 1 |
| `stop` | `--schedule` | yes | 0 · 1 |
| `delete` | `--schedule`, `--yes` | yes | 0 · 1 · 2 |
| `report` | `--schedule`, `--days` (1–90) | yes | 0 · 1 · 2 |

## How schedules become operational

One shared schedule worker per user fires every schedule. You never start
it by hand: `add` and `start` save the schedule, then start the worker (or
reuse the one already running) and wait until it answers a live health
check. The worker runs detached, so it keeps running after the terminal or
session that created the schedule closes, and every later command from any
session reuses the same worker.

A successful `add` or `start` exits 0 and its `--json` output has
`"operational": true`, `"worker": {"state": "healthy", ...}` and the
schedule's `next_due_at`.

## Create a schedule

Ask the user for the name, the prompt and the trigger. Run `slo schedule list --json` first to avoid a name clash.

```sh
slo schedule list --json
slo schedule add --name "Daily Summary" --prompt "Summarise the repo" \
  --interval-seconds 60 --session-mode continuous --session-reference 01234567-89ab-cdef-0123-456789abcdef --json
slo schedule status --schedule "Daily Summary" --json
```

Then tell the user the schedule is operational, with its next due time.
Never tell the user to run `slo schedule worker` to make a schedule work.

## Verify health

`status` is read-only: it never starts the worker. It exits 0 only when the
worker is healthy and reports `worker.state`:

- `healthy` — the worker answered, leads the scheduler and its ticks progress.
- `starting` — it is still starting; check again shortly.
- `retiring` — it is stopping; `slo schedule start --schedule <id>` waits for
  it and starts a new one.
- `stopped` — no worker runs; `slo schedule start --schedule <id>` starts it.
- `unresponsive` — a worker holds the schedules but does not answer, or
  answers while its engine no longer leads or finishes ticks. Report it to the
  user with its `pid` and `reason`; it is never replaced automatically.
- `blocked` — something needs the user (the `reason` says what), for example
  an unusable worker control file or an unconfirmed upgrade.

Healthy does not prove that a particular prompt ran. To confirm delivery,
read `slo schedule report --schedule <name> --days 1 --json`.

## When the schedule is saved but not operational

If the worker cannot be started or proved healthy, `add` or `start` still
keeps the saved schedule, exits 1 and prints
`schedule saved, but not operational: <cause>` with the saved id. With
`--json` the output has `"operational": false`, the schedule `id`, the
`worker` observation and an `error` text.

1. Do **not** run `add` again — the schedule already exists.
2. Tell the user the schedule is saved but will not fire yet, and quote the cause.
3. After the cause is fixed, retry activation on the same id with
   `slo schedule start --schedule <id>`; it is safe on an enabled schedule.

If the cause names an earlier version or an earlier development build of the
schedule worker, only the user can confirm that every earlier worker has
stopped. While an earlier worker visibly still runs, even the confirmation is
refused: it must be stopped first. Never
confirm it on their behalf and never pass `--earlier-workers-stopped`
yourself; explain the cause and let the user run the upgrade step.

## Session targets

What happens at each due time depends on the session settings:

- **Fresh mode** (`--session-mode fresh`): one headless `slo run` starts per due time with a new session id. The schedule stores only that session id; no provider-specific resume state is kept. Without `--cwd` it starts in the worker's working directory (the user's home directory), so pass `--cwd` when the prompt needs a project.
- **Continuous with a session reference**: the prompt is queued to that session's channel. If the session is closed, the row waits in its durable inbox and is delivered when the session opens — the scheduler never resumes a session headlessly. A healthy worker plus a closed session means the prompt is queued, not lost.
- **Continuous without a session reference**: treated as fresh — one new headless run per due time.

## Trigger, start, stop

- `trigger --schedule X` queues one invocation now; the worker picks it up at the next tick (within about 15 seconds).
- `stop --schedule X` prevents future invocations; pending invocations are skipped.
- `start --schedule X` restarts from now; it does not replay missed times. It also makes sure the worker is running and healthy.

## Workflow supervision

To supervise a long-running workflow from a session, create a recurring
monitor schedule and clean it up when the work ends:

- Use `--coalescing-mode latest_by_key` with a `--coalescing-key` so a busy session keeps only the newest pending monitor turn.
- Target a unique session name; ask the user to rename the session first if it is not uniquely nameable.
- Keep the monitor interval between 60 and 180 seconds.
- Each delivered monitor turn must be idempotent: read status first, post one concise progress update, take at most one recovery action, and stop monitoring once the workflow reaches a terminal state.
- Cleanup is mandatory: after confirmation, delete the monitor with `slo schedule delete --schedule <name> --yes`. Never leave a monitor schedule behind.

## Report

```sh
slo schedule report --schedule "Daily Summary" --days 30 --json
```

Read the counts and the last 20 invocations from the output.

## Delete

**Ask the user to confirm first.** Only after confirmation, run:

```sh
slo schedule delete --schedule "Daily Summary" --yes
```

Deleted is soft; the name is free again.

## Guidance

- Read `--json` output; parse exit codes from the runner.
- A schedule is done only when `add` or `start` reported it operational; otherwise follow the saved-but-not-operational steps.
- **Never** edit or inspect the schedule store or its files directly; the CLI is the only surface.
- Interval minimum: 15 seconds.
- One-shot: `--run-at` must be in the future.
- `slo schedule worker` runs the worker in the foreground for administration and debugging only; it is refused while the shared worker runs and is never needed for ordinary use.
- A closed session's prompt waits in the durable inbox; do not work around it with a headless run.

## Exit codes

- `0` success (for `add`/`start`: saved and operational; for `status`: healthy)
- `1` domain failure (not found, name taken, refused, saved but not operational, worker not healthy)
- `2` usage error
