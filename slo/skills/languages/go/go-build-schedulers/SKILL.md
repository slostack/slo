---
name: go-build-schedulers
description: "Go scoped recipe (asynq, Temporal): Go equivalent of scheduled/cron tasks \u2014 cron-style\
  \ periodic enqueuing with asynq's Scheduler and PeriodicTaskManager (github.com/hibiken/asynq). Covers\
  \ the scheduler process bootstrap, registering cron entries, dynamic periodic-task config, idempotency\
  \ for periodic runs, timezone handling, and enqueuing into the same Redis queues consumed by build-go-workers."
when_to_use: Only for the named project stack and component. Use when building a process that periodically
  enqueues background tasks on a cron schedule (nightly reports, hourly syncs, every-minute health probes),
  or when translating a DBOS/Celery-beat scheduled workflow into idiomatic Go.
group: languages
kind: skill
---

# Building Go Schedulers (Cron-Style Periodic Tasks)

## Skill summary

- **Name:** `go-build-schedulers`
- **Description:** Go equivalent of DBOS/Celery-beat scheduled workflows —
  cron-style periodic enqueuing with asynq's `Scheduler` and `PeriodicTaskManager`
  (`github.com/hibiken/asynq`). Covers the scheduler process bootstrap, registering
  cron entries (cron spec → task), dynamic periodic-task config, idempotency for
  periodic runs, timezone handling, and enqueuing into the same Redis queues
  consumed by `go-build-workers`.
- **When to use:** Use when a process must periodically enqueue background tasks on
  a cron schedule, or when porting a DBOS `@DBOS.scheduled(...)` / Celery-beat entry
  to Go.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add a nightly report job that runs at 2am and enqueues into the reports queue."
- "Set up an asynq scheduler process for our cron tasks."
- "Port this DBOS `@DBOS.scheduled('* * * * *')` workflow to Go."
- "Register a cron entry that fires every 15 minutes in America/New_York."
- "How do I make a periodic task idempotent so a double-fire doesn't double-run?"
- "Load our cron schedule dynamically from the database instead of hardcoding it."
- "Make the scheduler enqueue tasks the workers already consume."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

The DBOS/Celery-beat model is: a **scheduler process** owns a set of cron entries;
on each tick it **enqueues a task** into a queue; a **worker process** (a separate
deployable) consumes it. Go's idiomatic equivalent is asynq's scheduler side.

The scheduler is a **producer only** — it never executes business logic. It maps a
cron spec to a task payload and enqueues it. The `Handler` that actually runs lives
in the worker process. See `go-build-workers` for the consumer side, `TaskType`
constants, payload structs, and queue definitions — this skill reuses all of them.

> **Separation of concerns (the DBOS "queue isolation" analog).** DBOS forced each
> worker to define its queues inline to avoid cross-registration. In asynq the
> hazard is different but the discipline is the same: the **scheduler enqueues into
> queues that a worker is actually consuming**. A cron entry pointed at a queue no
> worker drains is a silent no-op — tasks pile up in Redis forever. Keep the queue
> name list in one shared package (`internal/tasks/queues.go`) imported by both the
> scheduler and the worker, so a typo can't split them.

Defer to `go-conventions` for naming, godoc, declarative function
structure, option structs, ubiquitous language, and error wrapping. This skill only
adds scheduler-specific rules.

---

## Section 1 — Two asynq scheduling primitives, and when to use each

asynq ships two ways to run cron-style work. Pick deliberately.

| Primitive | Use when | Config source |
|---|---|---|
| `asynq.Scheduler` | The schedule is **static** — known at compile time, changes only on redeploy. | Go code (`Register` calls). |
| `asynq.PeriodicTaskManager` | The schedule is **dynamic** — entries live in a DB/config file and change without redeploy. | A `PeriodicTaskConfigProvider` you implement. |

Both enqueue into the same Redis instance and the same queues the workers drain.
Both are cron-driven producers. Prefer `Scheduler` unless the requirement is
explicitly "operators change the schedule without a deploy" — then use
`PeriodicTaskManager`.

> A cron entry is **not** a durable single-run timer. If you need "run this exact
> workflow once, survive a crash, resume mid-step," that is a durable-workflow
> concern — use Temporal (`go.temporal.io/sdk`), not the scheduler. asynq cron is
> for *recurring enqueue*, matching Celery-beat / `@DBOS.scheduled`.

---

## Section 2 — Shared task + queue definitions (owned with the worker)

These live in a package imported by **both** the scheduler and the worker. This is
the single source of truth that keeps producer and consumer from drifting — the
direct translation of the DBOS "queue name must match the Queue in the worker" rule.

```go
// Package tasks defines task types, payloads, and queue names shared by the
// scheduler (producer) and the workers (consumer). See go-build-workers for the
// handler side that consumes these.
package tasks

// Task type names. The scheduler references these when building tasks; the worker
// registers handlers under the identical strings. One name, one concept — never
// let the scheduler and worker spell a task type differently.
const (
	TypeDailyReport   = "report:daily"
	TypeVendorSync    = "sync:vendor"
	TypeHealthProbe   = "health:probe"
)

// Queue names. Both the scheduler (via asynq.Queue(...)) and the worker
// (via asynq.Config.Queues) reference these constants — never string literals.
const (
	QueueCritical = "critical"
	QueueDefault  = "default"
	QueueLow      = "low"
)

// DailyReportPayload is the JSON body carried by a TypeDailyReport task.
// Field names match the worker's decode target and downstream domain fields.
type DailyReportPayload struct {
	ReportDate string `json:"report_date"` // YYYY-MM-DD, the logical run date
	VendorID   int64  `json:"vendor_id"`
}
```

Constructors that build a task belong here too, so the scheduler never hand-rolls a
payload:

```go
// NewDailyReportTask builds a TypeDailyReport task for the given logical date.
//
// The report_date is the logical run date, not time.Now — see Section 5 on
// idempotency. Returns an error if the payload cannot be marshalled.
func NewDailyReportTask(params DailyReportPayload) (*asynq.Task, error) {
	body, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("marshalling daily report payload: %w", err)
	}
	return asynq.NewTask(TypeDailyReport, body), nil
}
```

---

## Section 3 — Scheduler process bootstrap (static schedule)

`cmd/scheduler/main.go` is a **separate deployable** from the worker and the API.
Like every `main.go`, it only wires and starts — no logic (see
`go-conventions`).

```go
// Command scheduler runs the cron-style task scheduler. It is a producer-only
// process: on each cron tick it enqueues a task into a Redis queue that the
// worker process (see go-build-workers) consumes. It runs no business logic.
package main

import (
	"log/slog"
	"os"

	"github.com/hibiken/asynq"

	"example.com/svc/internal/config"
	"example.com/svc/internal/scheduler"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := config.Load()
	if err != nil {
		logger.Error("loading config", "err", err)
		os.Exit(1)
	}

	sched, err := scheduler.New(scheduler.Params{
		RedisAddr: cfg.RedisAddr,
		Location:  cfg.SchedulerTimezone, // e.g. "America/New_York"
		Logger:    logger,
	})
	if err != nil {
		logger.Error("building scheduler", "err", err)
		os.Exit(1)
	}

	// Run blocks until SIGTERM/SIGINT, then shuts down gracefully.
	if err := sched.Run(); err != nil {
		logger.Error("scheduler exited", "err", err)
		os.Exit(1)
	}
}
```

The scheduler itself lives in `internal/scheduler`. Registration is a **flat table
of contents** — one line per cron entry, each delegating to a task constructor. No
inline payload building, no branching.

```go
// Package scheduler registers cron entries and runs the asynq Scheduler process.
package scheduler

import (
	"fmt"
	"log/slog"
	"time"

	"github.com/hibiken/asynq"

	"example.com/svc/internal/tasks"
)

// Params configures a Scheduler. Grouped into a struct rather than positional
// args (go-conventions).
type Params struct {
	RedisAddr string
	Location  string // IANA tz name; empty means UTC
	Logger    *slog.Logger
}

// Scheduler owns the asynq scheduler and its registered cron entries.
type Scheduler struct {
	inner *asynq.Scheduler
	log   *slog.Logger
}

// New builds a Scheduler, resolves its timezone, and registers all cron entries.
//
// Returns an error if the timezone cannot be loaded or an entry fails to register.
func New(params Params) (*Scheduler, error) {
	loc, err := resolveLocation(params.Location)
	if err != nil {
		return nil, err
	}

	inner := asynq.NewScheduler(
		asynq.RedisClientOpt{Addr: params.RedisAddr},
		&asynq.SchedulerOpts{
			Location:            loc,
			EnqueueErrorHandler: enqueueErrorHandler(params.Logger),
		},
	)

	s := &Scheduler{inner: inner, log: params.Logger}
	if err := s.registerEntries(); err != nil {
		return nil, err
	}
	return s, nil
}

// registerEntries wires every cron entry. Reads as a table of contents — one line
// per schedule, each delegating to a helper. Add a new job = add one line here.
func (s *Scheduler) registerEntries() error {
	if err := s.registerDailyReport(); err != nil {
		return err
	}
	if err := s.registerVendorSync(); err != nil {
		return err
	}
	if err := s.registerHealthProbe(); err != nil {
		return err
	}
	return nil
}

// Run starts the scheduler and blocks until the process receives SIGTERM/SIGINT.
func (s *Scheduler) Run() error {
	s.log.Info("scheduler starting")
	return s.inner.Run()
}

// resolveLocation loads an IANA timezone; empty string resolves to UTC.
//
// Returns an error if the zone name is not found in the system tz database.
func resolveLocation(name string) (*time.Location, error) {
	if name == "" {
		return time.UTC, nil
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		return nil, fmt.Errorf("loading timezone %q: %w", name, err)
	}
	return loc, nil
}

// enqueueErrorHandler logs enqueue failures. A cron tick that fails to enqueue is
// never silently dropped — it is logged with the task type and the error.
func enqueueErrorHandler(log *slog.Logger) func(*asynq.Task, *asynq.SchedulerEnqueueEvent, error) {
	return func(task *asynq.Task, _ *asynq.SchedulerEnqueueEvent, err error) {
		log.Error("cron enqueue failed", "type", task.Type(), "err", err)
	}
}
```

---

## Section 4 — Registering cron entries (cron spec → task)

Each `register*` helper does exactly one thing: build the task and register the cron
spec. This mirrors DBOS's `@DBOS.scheduled('* * * * *')` decorator, but the mapping
is explicit and testable rather than a decorator side effect.

```go
// registerDailyReport enqueues a daily report at 02:00 in the scheduler's
// timezone, targeting the low-priority queue drained by the worker.
func (s *Scheduler) registerDailyReport() error {
	task, err := tasks.NewDailyReportTask(tasks.DailyReportPayload{
		VendorID: 0, // 0 = all vendors; resolved by the handler
		// ReportDate is left blank here; the handler stamps the logical date on
		// receipt (see Section 5). For per-run dating, use a dynamic provider.
	})
	if err != nil {
		return err
	}

	// Cron spec: minute hour dom month dow. "0 2 * * *" = 02:00 daily.
	entryID, err := s.inner.Register(
		"0 2 * * *",
		task,
		asynq.Queue(tasks.QueueLow),
		asynq.TaskID("daily-report"),        // idempotency — see Section 5
		asynq.Retention(24*time.Hour),
		asynq.MaxRetry(3),
	)
	if err != nil {
		return fmt.Errorf("registering daily report: %w", err)
	}
	s.log.Info("registered cron entry", "id", entryID, "spec", "0 2 * * *")
	return nil
}

// registerVendorSync enqueues a vendor sync every 15 minutes into the default
// queue. Uses the @every macro that asynq/robfig-cron supports as an alternative
// to raw cron specs.
func (s *Scheduler) registerVendorSync() error {
	task := asynq.NewTask(tasks.TypeVendorSync, nil)

	entryID, err := s.inner.Register(
		"@every 15m",
		task,
		asynq.Queue(tasks.QueueDefault),
		asynq.TaskID("vendor-sync"),
	)
	if err != nil {
		return fmt.Errorf("registering vendor sync: %w", err)
	}
	s.log.Info("registered cron entry", "id", entryID, "spec", "@every 15m")
	return nil
}

// registerHealthProbe enqueues a health probe every minute into the critical
// queue. The "* * * * *" spec is the direct analog of the DBOS
// @DBOS.scheduled('* * * * *') example.
func (s *Scheduler) registerHealthProbe() error {
	task := asynq.NewTask(tasks.TypeHealthProbe, nil)

	entryID, err := s.inner.Register(
		"* * * * *",
		task,
		asynq.Queue(tasks.QueueCritical),
		asynq.TaskID("health-probe"),
	)
	if err != nil {
		return fmt.Errorf("registering health probe: %w", err)
	}
	s.log.Info("registered cron entry", "id", entryID, "spec", "* * * * *")
	return nil
}
```

**Cron spec cheat-sheet** (asynq uses robfig/cron under the hood):

| Spec | Meaning |
|---|---|
| `* * * * *` | every minute |
| `0 2 * * *` | 02:00 daily |
| `0 */4 * * *` | every 4 hours on the hour |
| `0 9 * * 1-5` | 09:00 Mon–Fri |
| `@every 15m` | every 15 minutes |
| `@hourly`, `@daily`, `@weekly` | named macros |

---

## Section 5 — Idempotency for periodic runs

This is the sharpest hazard in scheduling and the one most easily missed. A cron
scheduler can double-fire: two scheduler replicas, a clock adjustment, a restart
straddling a tick. Without protection, "daily report" runs twice.

**Rule 1 — one scheduler replica, or a shared lock.** `asynq.Scheduler` is not
leader-elected. Run **exactly one** scheduler instance, or guard startup with a
Redis-based lock so only one replica registers entries. Do not scale the scheduler
horizontally the way you scale workers.

**Rule 2 — deterministic `TaskID` for uniqueness.** asynq deduplicates by task ID
within its uniqueness window. A cron entry with a **stable** `asynq.TaskID` collapses
a same-tick double-enqueue into one task. Combine with `asynq.Unique(ttl)` when you
want a time-boxed guarantee:

```go
// Good — a per-period unique key makes a double-fire a no-op. The date-stamped
// task ID means the 02:00 tick can fire twice but only one task ever enters Redis.
runDate := time.Now().In(s.location()).Format("2006-01-02")
task, _ := tasks.NewDailyReportTask(tasks.DailyReportPayload{ReportDate: runDate})

s.inner.Register(
	"0 2 * * *",
	task,
	asynq.Queue(tasks.QueueLow),
	asynq.TaskID("daily-report:"+runDate), // unique per logical day
	asynq.Unique(20*time.Hour),            // reject a duplicate within the window
)
```

> `asynq.TaskID` with a **static** string dedupes *concurrent identical* enqueues.
> A **date-stamped** ID dedupes *across the whole day*. Choose based on whether a
> second run in the same period is acceptable. For static-schedule `Scheduler`,
> per-period stamping needs a dynamic provider (Section 6) since the ID must change
> each period.

**Rule 3 — carry the logical run date, not `time.Now()`, in the payload.** The
handler must be able to tell *which period* it is processing so a retry or a delayed
run doesn't process "today" when it meant "yesterday". This is the same discipline
as passing `scheduled_time` into a DBOS scheduled workflow.

```go
// Bad — handler computes "now", so a retry at 00:05 processes the wrong day.
report := buildReport(time.Now())

// Good — the logical date travels in the payload; retries are deterministic.
report := buildReport(payload.ReportDate)
```

**Rule 4 — the handler stays idempotent.** Even with all the above, the worker
handler (in `go-build-workers`) must upsert / check-before-insert keyed on the
logical period, because at-least-once delivery means a task can be re-run after a
crash. The scheduler reduces duplicates; the handler must tolerate them.

---

## Section 6 — Dynamic periodic-task config (PeriodicTaskManager)

When operators change the schedule without a redeploy, drive it from a config
source via `asynq.PeriodicTaskManager`. You implement a
`PeriodicTaskConfigProvider`; the manager polls it and reconciles the live cron
entries with what the provider returns. This is the asynq analog of Celery-beat
reading its schedule from the database.

```go
// dbConfigProvider supplies periodic-task configs from the database, letting
// operators change the cron schedule without redeploying the scheduler.
type dbConfigProvider struct {
	repo scheduleRepository // consumer-defined interface (conventions §6)
}

// scheduleRepository is the minimal data-access contract the provider needs.
type scheduleRepository interface {
	ActiveSchedules(ctx context.Context) ([]ScheduleRow, error)
}

// ScheduleRow is one operator-managed cron entry loaded from the DB.
type ScheduleRow struct {
	Cronspec string // e.g. "0 2 * * *"
	TaskType string // must be one of the tasks.Type* constants
	Queue    string // must be one of the tasks.Queue* constants
	Payload  []byte // pre-marshalled task payload, may be nil
}

// GetConfigs returns the current desired set of periodic tasks. asynq calls this
// on each sync interval and reconciles the running entries against it.
//
// Returns an error if the schedules cannot be loaded; asynq keeps the previous
// config on error rather than clearing all entries.
func (p *dbConfigProvider) GetConfigs() ([]*asynq.PeriodicTaskConfig, error) {
	rows, err := p.repo.ActiveSchedules(context.Background())
	if err != nil {
		return nil, fmt.Errorf("loading active schedules: %w", err)
	}

	configs := make([]*asynq.PeriodicTaskConfig, 0, len(rows))
	for _, row := range rows {
		configs = append(configs, &asynq.PeriodicTaskConfig{
			Cronspec: row.Cronspec,
			Task:     asynq.NewTask(row.TaskType, row.Payload),
			Opts:     []asynq.Option{asynq.Queue(row.Queue)},
		})
	}
	return configs, nil
}

// NewManager builds a PeriodicTaskManager that syncs the DB schedule every minute.
//
// Returns an error if the manager cannot be constructed.
func NewManager(params ManagerParams) (*asynq.PeriodicTaskManager, error) {
	return asynq.NewPeriodicTaskManager(asynq.PeriodicTaskManagerOpts{
		RedisConnOpt:               asynq.RedisClientOpt{Addr: params.RedisAddr},
		PeriodicTaskConfigProvider: &dbConfigProvider{repo: params.Repo},
		SyncInterval:               time.Minute,
		SchedulerOpts: &asynq.SchedulerOpts{
			Location: params.Location,
		},
	})
}
```

Guardrails for a dynamic provider:

- **Validate `TaskType` and `Queue` against the shared constants** before returning
  a config. An operator typo that points at a nonexistent queue produces a silent
  no-op (Section 2). Reject unknown types loudly.
- **Return the last-known-good config on load error** — asynq already keeps the
  previous set if `GetConfigs` returns an error, so surface the error rather than
  returning an empty slice (empty slice = "delete all entries").
- The uniqueness / idempotency rules from Section 5 apply identically; encode a
  per-period `TaskID` into `Opts` if a second run per period is unacceptable.

---

## Section 7 — Timezone handling

Cron specs are evaluated in the scheduler's `Location`. Getting this wrong means
"2am" fires at the wrong hour or drifts across DST.

- **Set `Location` explicitly** on `SchedulerOpts` / `PeriodicTaskManagerOpts`.
  Never rely on the process's ambient `TZ`.
- **Load from config**, not a hardcoded literal, so staging and prod can differ:
  `time.LoadLocation(cfg.SchedulerTimezone)`.
- **UTC is the safe default** for machine-facing jobs (syncs, probes). Use a named
  zone only when the schedule is anchored to human/local time (business-hours jobs,
  end-of-day reports).
- **DST is a real risk** for daily jobs anchored to local time: `0 2 * * *` in a
  zone with DST can skip or repeat the 02:00 hour on transition days. If the job
  must run exactly once per day regardless, anchor it in UTC and convert, or make
  the handler idempotent per logical date (Section 5) so a repeat is harmless.

```go
// Bad — ambient TZ; behaviour differs between the dev laptop and the prod pod.
sched := asynq.NewScheduler(redisOpt, nil)

// Good — explicit, config-driven zone.
loc, err := time.LoadLocation(cfg.SchedulerTimezone) // "America/New_York"
if err != nil {
	return nil, fmt.Errorf("loading timezone %q: %w", cfg.SchedulerTimezone, err)
}
sched := asynq.NewScheduler(redisOpt, &asynq.SchedulerOpts{Location: loc})
```

---

## Section 8 — Relationship to go-build-workers

The scheduler and worker are two halves of one system. Keep them consistent:

| Concern | Scheduler (this skill) | Worker (`go-build-workers`) |
|---|---|---|
| Role | Producer — enqueues on cron ticks | Consumer — drains queues, runs handlers |
| Task types | References `tasks.Type*` constants | Registers handlers under the same constants |
| Queues | `asynq.Queue(tasks.Queue*)` on each entry | `asynq.Config.Queues` lists the same names |
| Payload | Marshals via shared task constructors | Unmarshals into the same payload structs |
| Business logic | **None** | All of it — via an application service |
| Deployable | `cmd/scheduler` | `cmd/worker` |

The single most common failure is a queue mismatch: the scheduler enqueues into a
queue the worker's `Config.Queues` does not list. Tasks accumulate in Redis and
never run. Enforce the shared-constants rule (Section 2) and, in CI, assert every
`tasks.Queue*` referenced by the scheduler appears in the worker config.

---

## Section 9 — Testing the scheduler

Test the mapping (cron spec → task, payload correctness, idempotency key), not
asynq's internal ticking. Table-driven, one decision per case (conventions §1.5).

```go
// TestNewDailyReportTask verifies the task type and payload are set correctly.
func TestNewDailyReportTask(t *testing.T) {
	tests := []struct {
		name       string
		params     tasks.DailyReportPayload
		wantType   string
		wantDate   string
	}{
		{
			name:     "carries the logical report date",
			params:   tasks.DailyReportPayload{ReportDate: "2026-07-06", VendorID: 1},
			wantType: tasks.TypeDailyReport,
			wantDate: "2026-07-06",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			task, err := tasks.NewDailyReportTask(tc.params)
			assert.NoError(t, err)
			assert.Equal(t, tc.wantType, task.Type())

			var got tasks.DailyReportPayload
			assert.NoError(t, json.Unmarshal(task.Payload(), &got))
			assert.Equal(t, tc.wantDate, got.ReportDate)
		})
	}
}
```

For the dynamic provider, test `GetConfigs` against a mock `scheduleRepository`:
assert unknown task types are rejected and that a repo error propagates (so asynq
keeps the last-known-good config) rather than returning an empty slice.

---

## Section 10 — Scheduler Checklist

Apply before every merge. Each unchecked item is a **blocker**.

### Structure & separation

- [ ] The scheduler is a **producer only** — zero business logic; all logic lives in
      the worker handler (`go-build-workers`).
- [ ] `cmd/scheduler/main.go` only wires and starts (<~30 lines).
- [ ] `registerEntries()` reads as a **table of contents** — one line per cron
      entry, each delegating to a `register*` helper.
- [ ] Task types, queue names, payload structs, and task constructors live in a
      **shared package** imported by both scheduler and worker — no string literals.

### Correctness

- [ ] Every cron entry enqueues into a queue the **worker actually drains**
      (`Config.Queues`). No orphaned queues.
- [ ] Cron specs are correct and use constants/macros where clearer.
- [ ] The right primitive is chosen: `Scheduler` for static, `PeriodicTaskManager`
      for operator-editable schedules.

### Idempotency

- [ ] **Exactly one** scheduler replica runs, or startup is guarded by a shared lock.
- [ ] Cron entries set a deterministic `asynq.TaskID` (per-period stamped when a
      second run per period is unacceptable), with `asynq.Unique` where appropriate.
- [ ] The **logical run date/period** travels in the payload — handlers never rely
      on `time.Now()` to decide which period they process.
- [ ] The worker handler is idempotent per logical period (at-least-once delivery).

### Timezone

- [ ] `Location` is set **explicitly** from config — never ambient `TZ`.
- [ ] UTC is used for machine jobs; a named zone only for human/local-time jobs.
- [ ] DST risk is considered for daily local-time jobs; handler idempotency covers a
      skipped/repeated hour.

### Dynamic provider (if used)

- [ ] `GetConfigs` validates `TaskType`/`Queue` against shared constants.
- [ ] On load error, the error is returned (last-known-good kept) — never an empty
      slice.

### Testing

- [ ] Task constructors and the config provider have table-driven tests.
- [ ] Tests assert the spec→task mapping and idempotency key, not asynq internals.

---

## Cross-references

- `go-build-workers` — the consumer side: handlers, `Config.Queues`, retries,
  monitoring. **Required reading** — this skill's tasks are meaningless without it.
- `go-conventions` — naming, godoc, declarative structure, option
  structs, error wrapping, DI. Non-negotiable on every file.
