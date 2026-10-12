---
name: go-build-workers
description: 'Go scoped recipe (testcontainers, asynq): The Go equivalent of Celery background workers,
  built on asynq (github.com/hibiken/asynq). Covers typed task/payload definitions, task-type naming and
  ServeMux registration, enqueuing with options (queue, retries, timeout, unique, retention), worker Server
  bootstrap (concurrency, queue priorities), retry/backoff config, context propagation (request-id, slog),
  and delegating real work to application services.'
when_to_use: "Only for the named project stack and component. Use whenever adding, modifying, or reviewing\
  \ background jobs in a Go service \u2014 anything you would have made a Celery worker for. Also use\
  \ when wiring the asynq Server, defining task payloads, or enqueuing deferred/scheduled work."
group: languages
kind: skill
---

# Building Go Workers (asynq)

## Skill summary

- **Name:** `go-build-workers`
- **Description:** The Go equivalent of Celery background workers, built on
  **asynq** (`github.com/hibiken/asynq`) — a Redis-backed task queue with retries,
  timeouts, uniqueness, retention, and a monitoring dashboard. Covers typed
  task/payload structs, task-type naming and `ServeMux` registration, enqueuing
  with options, the worker `Server` bootstrap (concurrency + queue priorities),
  retry/backoff config, request-id/slog context propagation, and delegating the
  real work to application services.
- **When to use:** Whenever you would have written a Celery worker — deferred jobs,
  fan-out processing, retryable side effects, scheduled batch work.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add a background worker that preprocesses an uploaded placement file."
- "Enqueue an email-send task with 5 retries and a 30s timeout."
- "How do I set up the asynq server with queue priorities in this Go service?"
- "Make this task idempotent so we don't enqueue two of them for the same account."
- "Convert this Celery `apply_async` call to its Go equivalent."
- "Run a task 60 seconds from now / on a schedule."
- "Review this asynq handler — is it delegating to the app service correctly?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill translates the Celery worker conventions to idiomatic Go on **asynq**.
Defer to `go-conventions` for all naming, godoc, declarative-structure,
error-wrapping, and testing rules — this skill only adds worker-specific patterns.

**Celery → asynq mental map:**

| Celery concept | asynq equivalent |
|---|---|
| `@celery.task(name=...)` | a **task type** string constant + a registered handler |
| task function body | `func(ctx, *asynq.Task) error` handler |
| `worker.py` app + `include` list | `asynq.NewServeMux()` with `mux.HandleFunc(type, handler)` |
| `task_routes` → `{queue}` | `asynq.Queue(name)` enqueue option + `Server` queue map |
| `.apply_async(kwargs=..., ...)` | `client.Enqueue(task, opts...)` |
| `countdown=60` | `asynq.ProcessIn(60*time.Second)` |
| `max_retries` / `retry_backoff` | `asynq.MaxRetry(n)` + `RetryDelayFunc` on the `Server` |
| `bind=True` self.retry | return an error → asynq reschedules automatically |
| beat_schedule (cron) | `asynq.Scheduler` — see `go-build-schedulers` |
| the business logic itself | an **application service** — see `go-build-application-services` |

The cardinal rule is unchanged from Celery: **a worker handler contains no business
logic.** It decodes the payload, propagates context, calls an application service's
`Execute()`, and maps the result to retry-or-done.

---

## Section 1 — Conventions & File Layout

Workers live under `internal/worker/`. One file per task, named after the task.
The central bootstrap (server, mux registration, retry policy) lives in
`internal/worker/server.go`.

```
internal/
├── worker/
│   ├── tasks.go                        # task-type constants (the "names")
│   ├── server.go                       # Server + ServeMux bootstrap, retry policy
│   ├── enqueuer.go                     # thin Enqueuer wrapper over *asynq.Client
│   ├── placement_file_preprocessor.go  # one task = payload + New + Handle
│   └── send_reminder.go
├── app/
│   └── preprocessplacementfile/
│       └── service.go                  # the actual work (Execute() orchestrator)
└── config/
    └── config.go
cmd/
├── server/main.go                      # HTTP API entry point
└── worker/main.go                      # worker process entry point (runs Server)
```

Naming rules (the ubiquitous-language rule applied to tasks):

1. **The task type, the payload struct, the constructor, and the handler all share
   one name.** Task type `task:placement_file_preprocess` ↔ `PlacementFilePreprocessPayload`
   ↔ `NewPlacementFilePreprocessTask` ↔ `PlacementFilePreprocessHandler`.
2. Task-type strings use a `task:` prefix and snake_case, matching the file name.
3. Each task gets a **dedicated queue** named after the task (Celery's
   `{task}_queue` pattern). The queue priority is declared once, in `server.go`.

---

## Section 2 — Task Type Constants (the "names")

The Celery `name=` is just a routing key. In asynq it's a string constant. Keep them
all in one file so the mux registration and the enqueuer reference the same source.

```go
// Package worker defines background task types, payloads, handlers, and the
// asynq server that processes them.
package worker

// Task type identifiers. These are the routing keys asynq uses to dispatch a
// task to its handler; they double as the queue-selection key. One constant per
// task; the string matches the file name.
const (
	TypePlacementFilePreprocess = "task:placement_file_preprocess"
	TypeSendReminder            = "task:send_reminder"
)

// Queue names. Each task has a dedicated queue (Celery's {task}_queue pattern);
// priorities are wired in NewServer.
const (
	QueuePlacementFilePreprocess = "placement_file_preprocess"
	QueueSendReminder            = "send_reminder"
	QueueDefault                 = "default"
)
```

---

## Section 3 — Task Payload + Constructor + Handler

An asynq `*asynq.Task` carries a type string and an opaque `[]byte` payload. The
idiomatic pattern is a **typed payload struct** (the Pydantic analog) marshalled to
JSON — never build tasks from loose maps.

Each task file has three things: the **payload struct**, a **constructor** that
returns `(*asynq.Task, error)`, and a **handler struct** whose `Handle` method
decodes and delegates.

```go
// internal/worker/placement_file_preprocessor.go
package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/hibiken/asynq"

	"myservice/internal/app/preprocessplacementfile"
)

// PlacementFilePreprocessPayload is the typed payload for a placement-file
// preprocessing task. Field names are the canonical domain names; JSON tags are
// snake_case (ubiquitous language across enqueue and handle sites).
type PlacementFilePreprocessPayload struct {
	AccountID int64  `json:"account_id"`
	VendorID  int64  `json:"vendor_id"`
	FileKey   string `json:"file_key"`
	RequestID string `json:"request_id"` // carried for log correlation
}

// NewPlacementFilePreprocessTask builds a task ready to enqueue.
//
// Returns an error if the payload cannot be marshalled.
func NewPlacementFilePreprocessTask(payload PlacementFilePreprocessPayload) (*asynq.Task, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshalling placement-file payload: %w", err)
	}
	return asynq.NewTask(TypePlacementFilePreprocess, body), nil
}

// preprocessService is the consumer-local interface for the work this handler
// delegates to. Defined at the consumer per go-conventions.
type preprocessService interface {
	Execute(ctx context.Context) error
}

// PlacementFilePreprocessHandler processes placement-file preprocessing tasks.
// It holds only the dependencies needed to construct the application service.
type PlacementFilePreprocessHandler struct {
	newService func(p PlacementFilePreprocessPayload) preprocessService
	logger     *slog.Logger
}

// NewPlacementFilePreprocessHandler wires the handler's dependencies.
func NewPlacementFilePreprocessHandler(
	newService func(p PlacementFilePreprocessPayload) preprocessService,
	logger *slog.Logger,
) *PlacementFilePreprocessHandler {
	return &PlacementFilePreprocessHandler{newService: newService, logger: logger}
}

// Handle decodes the payload, propagates context, and delegates to the
// application service. It contains no business logic.
//
// Returning an error tells asynq to retry per the task's MaxRetry/RetryDelayFunc.
// A nil error marks the task done.
func (h *PlacementFilePreprocessHandler) Handle(ctx context.Context, task *asynq.Task) error {
	var payload PlacementFilePreprocessPayload
	if err := json.Unmarshal(task.Payload(), &payload); err != nil {
		// A malformed payload will never succeed — do not retry it.
		return fmt.Errorf("unmarshalling placement-file payload: %w: %w", err, asynq.SkipRetry)
	}

	ctx = withRequestID(ctx, payload.RequestID)
	log := h.logger.With("task", TypePlacementFilePreprocess, "request_id", payload.RequestID)

	if err := h.newService(payload).Execute(ctx); err != nil {
		log.ErrorContext(ctx, "placement-file preprocess failed", "error", err)
		return fmt.Errorf("preprocessing placement file: %w", err) // → asynq retries
	}

	log.InfoContext(ctx, "placement-file preprocess completed",
		"account_id", payload.AccountID, "vendor_id", payload.VendorID)
	return nil
}
```

The application service (`preprocessplacementfile.NewService(...).Execute()`) holds
the real logic. Its shape — one public `Execute()` orchestrator, private step
methods, no inline I/O — is governed by `go-build-application-services`.

**Bad — logic in the handler (the anti-pattern this skill exists to prevent):**

```go
// Bad — decodes AND does the work: SQL, S3, parsing all inline in the handler.
func (h *Handler) Handle(ctx context.Context, task *asynq.Task) error {
	var p PlacementFilePreprocessPayload
	json.Unmarshal(task.Payload(), &p) // error ignored
	rows, _ := h.db.Query(ctx, "SELECT ... WHERE account_id=$1", p.AccountID)
	obj, _ := h.s3.GetObject(ctx, ...)
	// ...200 lines of business logic that can never be unit-tested without Redis...
	return nil
}
```

---

## Section 4 — Server Bootstrap: concurrency, queue priorities, retry policy

`server.go` is the Celery `worker.py` analog. It builds one `asynq.Server` (global
concurrency + weighted queue priorities + the retry-delay policy) and one
`asynq.ServeMux` mapping each task type to its handler.

```go
// internal/worker/server.go
package worker

import (
	"log/slog"
	"math"
	"time"

	"github.com/hibiken/asynq"
)

// ServerDeps carries the constructed handlers the mux dispatches to.
type ServerDeps struct {
	PlacementFile *PlacementFilePreprocessHandler
	SendReminder  *SendReminderHandler
	Logger        *slog.Logger
}

// NewServer constructs the asynq processing server.
//
// Concurrency caps in-flight tasks across all queues. The Queues map assigns
// weighted priority: default drains most, dedicated queues get guaranteed share.
// ServerDAO carries required worker-server dependencies.
type ServerDAO struct {
    RedisAddr string
    Logger *slog.Logger
}

func NewServer(in ServerDAO) *asynq.Server {
    redisAddr, logger := in.RedisAddr, in.Logger
	return asynq.NewServer(
		asynq.RedisClientOpt{Addr: redisAddr},
		asynq.Config{
			Concurrency: 20,
			Queues: map[string]int{
				QueuePlacementFilePreprocess: 6,
				QueueSendReminder:            3,
				QueueDefault:                 1,
			},
			RetryDelayFunc: exponentialBackoff,
			Logger:         newSlogAdapter(logger),
		},
	)
}

// NewMux registers every task type against its handler. This is the asynq
// analog of Celery's include list + task_routes: adding a task = one line here.
func NewMux(deps ServerDeps) *asynq.ServeMux {
	mux := asynq.NewServeMux()
	mux.Use(loggingMiddleware(deps.Logger)) // cross-cutting: start/finish timing
	mux.HandleFunc(TypePlacementFilePreprocess, deps.PlacementFile.Handle)
	mux.HandleFunc(TypeSendReminder, deps.SendReminder.Handle)
	return mux
}

// exponentialBackoff replicates Celery retry_backoff + retry_jitter: the delay
// doubles each attempt, capped, with jitter added by asynq's default runner.
func exponentialBackoff(n int, _ error, _ *asynq.Task) time.Duration {
	const base, cap = 30 * time.Second, 10 * time.Minute
	delay := time.Duration(math.Pow(2, float64(n))) * base
	if delay > cap {
		return cap
	}
	return delay
}
```

The worker process is a thin `cmd/worker/main.go` (wiring only, per the
30-line rule in `go-conventions`):

```go
// cmd/worker/main.go
func main() {
	cfg := config.Load()
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	deps := buildWorkerDeps(cfg, logger) // constructs handlers + app services
	srv := worker.NewServer(worker.ServerDAO{RedisAddr: cfg.RedisAddr, Logger: logger})

	if err := srv.Run(worker.NewMux(deps)); err != nil {
		logger.Error("worker server exited", "error", err)
		os.Exit(1)
	}
}
```

`srv.Run` blocks and handles graceful shutdown (SIGTERM drains in-flight tasks).

---

## Section 5 — Enqueuing (the `apply_async` analog)

Wrap `*asynq.Client` in a small typed `Enqueuer` so callers enqueue by intent, not
by hand-rolling tasks and options. Application services and handlers call the
enqueuer — the same way Celery code called `worker.apply_async(...)`.

```go
// internal/worker/enqueuer.go
package worker

import (
	"context"
	"fmt"
	"time"

	"github.com/hibiken/asynq"
)

// Enqueuer submits background tasks to Redis. One typed method per task keeps
// call sites intent-revealing and the options in one place.
type Enqueuer struct {
	client *asynq.Client
}

// NewEnqueuer constructs an Enqueuer over the given Redis address.
func NewEnqueuer(redisAddr string) *Enqueuer {
	return &Enqueuer{client: asynq.NewClient(asynq.RedisClientOpt{Addr: redisAddr})}
}

// EnqueuePlacementFilePreprocess submits a placement-file preprocessing task.
//
// Options: dedicated queue, 5 retries, 10-minute per-attempt timeout, and a
// unique window so a duplicate for the same file within 1h is a no-op.
func (e *Enqueuer) EnqueuePlacementFilePreprocess(
	ctx context.Context,
	payload PlacementFilePreprocessPayload,
) (*asynq.TaskInfo, error) {
	task, err := NewPlacementFilePreprocessTask(payload)
	if err != nil {
		return nil, err
	}

	info, err := e.client.EnqueueContext(ctx, task,
		asynq.Queue(QueuePlacementFilePreprocess),
		asynq.MaxRetry(5),
		asynq.Timeout(10*time.Minute),
		asynq.Unique(time.Hour),
		asynq.Retention(24*time.Hour), // keep result/state visible in the dashboard
	)
	if err != nil {
		return nil, fmt.Errorf("enqueuing placement-file task: %w", err)
	}
	return info, nil
}
```

### Enqueue-option cheat sheet

| Need | Option | Celery analog |
|---|---|---|
| Target a queue | `asynq.Queue("name")` | `task_routes` / `queue=` |
| Retry budget | `asynq.MaxRetry(5)` | `max_retries` |
| Per-attempt timeout | `asynq.Timeout(10*time.Minute)` | `time_limit` |
| Absolute deadline | `asynq.Deadline(t)` | `expires` |
| Delay before running | `asynq.ProcessIn(60*time.Second)` | `countdown=60` |
| Run at a specific time | `asynq.ProcessAt(t)` | `eta` |
| Idempotency window | `asynq.Unique(time.Hour)` | (no direct equal — dedup) |
| Keep completed state | `asynq.Retention(24*time.Hour)` | `result_expires` |
| Explicit task id | `asynq.TaskID(id)` | `task_id=` |

### Delayed / scheduled enqueue

```go
// Run 60s from now — the countdown= analog.
info, err := e.client.EnqueueContext(ctx, task,
	asynq.Queue(QueueSendReminder),
	asynq.ProcessIn(60*time.Second),
)

// Run at an exact wall-clock time — the eta= analog.
info, err := e.client.EnqueueContext(ctx, task,
	asynq.Queue(QueueSendReminder),
	asynq.ProcessAt(dueAt),
)
```

For **recurring cron-style** work (the Celery `beat_schedule`), do **not** enqueue
in a loop — use `asynq.Scheduler` / periodic-task registration. That belongs to
`go-build-schedulers`; this skill covers one-shot and delayed enqueues.

### Calling the enqueuer from an application service

Enqueuing is a side effect an app service performs; it delegates to the enqueuer,
never to `asynq.Client` directly (accept the minimal interface, per §6 of
`go-conventions`).

```go
// internal/app/importplacement/service.go
type placementEnqueuer interface { // consumer-local interface
	EnqueuePlacementFilePreprocess(ctx context.Context, p worker.PlacementFilePreprocessPayload) (*asynq.TaskInfo, error)
}

// enqueuePreprocess schedules the async follow-up after the upload is persisted.
func (s *Service) enqueuePreprocess(ctx context.Context) error {
	_, err := s.enqueuer.EnqueuePlacementFilePreprocess(ctx, worker.PlacementFilePreprocessPayload{
		AccountID: s.accountID,
		VendorID:  s.vendorID,
		FileKey:   s.fileKey,
		RequestID: RequestIDFromContext(ctx),
	})
	if err != nil {
		return fmt.Errorf("scheduling placement-file preprocess: %w", err)
	}
	return nil
}
```

---

## Section 6 — Context Propagation (request-id + slog)

Celery passed a `trace_id` kwarg and set it into a context var. In Go the request-id
travels **in the JSON payload** (Redis doesn't carry the caller's `context.Context`),
then the handler re-hydrates it into `ctx` and a child `*slog.Logger`.

```go
type ctxKey string

const requestIDKey ctxKey = "request_id"

// withRequestID returns a context carrying the request id for log correlation.
func withRequestID(ctx context.Context, requestID string) context.Context {
	return context.WithValue(ctx, requestIDKey, requestID)
}

// RequestIDFromContext extracts the request id, or "" if absent. Enqueuers read
// it to stamp the payload so correlation survives the Redis boundary.
func RequestIDFromContext(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey).(string)
	return id
}
```

The mux-level logging middleware (the `@log_execution` analog) times every task and
logs start/finish with the request id, so individual handlers don't repeat it:

```go
// loggingMiddleware logs task start, outcome, and elapsed time. This is the
// asynq analog of the @log_execution decorator.
func loggingMiddleware(logger *slog.Logger) asynq.MiddlewareFunc {
	return func(next asynq.Handler) asynq.Handler {
		return asynq.HandlerFunc(func(ctx context.Context, task *asynq.Task) error {
			start := time.Now()
			log := logger.With("task", task.Type())
			log.InfoContext(ctx, "task started")

			err := next.ProcessTask(ctx, task)

			log.InfoContext(ctx, "task finished",
				"elapsed_ms", time.Since(start).Milliseconds(),
				"ok", err == nil, "error", err)
			return err
		})
	}
}
```

---

## Section 7 — Retry & failure semantics

- **Retry is return-driven.** Return an error → asynq reschedules using the task's
  `MaxRetry` and the server's `RetryDelayFunc`. Return `nil` → done. There is no
  `self.retry()`; you never re-enqueue by hand for a transient failure.
- **Poison messages skip retry.** Wrap with `asynq.SkipRetry` for errors that can
  never succeed (malformed payload, permanently missing record) so they go straight
  to the archive/dead queue instead of burning the retry budget.
- **Exhausted retries are observable.** After `MaxRetry`, asynq archives the task;
  surface it via the asynqmon dashboard or an `asynq.Inspector`. Do not swallow.
- **Timeouts cancel the context.** `asynq.Timeout`/`Deadline` cancel the handler's
  `ctx`; your app service must honor `ctx` for the timeout to actually stop work.
- **Idempotency is the caller's job.** `asynq.Unique` prevents duplicate *enqueues*
  within a window, but a retried task runs its handler again — the app service's
  `Execute()` must be safe to run more than once.

```go
// Distinguish retryable from terminal failures at the handler boundary.
if errors.Is(err, domain.ErrNotFound) {
	// The record is gone; retrying won't bring it back.
	return fmt.Errorf("account %d not found: %w: %w", payload.AccountID, err, asynq.SkipRetry)
}
if err != nil {
	// Transient (DB blip, upstream 503) — let asynq back off and retry.
	return fmt.Errorf("preprocessing: %w", err)
}
```

---

## Section 8 — Testing

Handlers are unit-testable **without Redis**: construct the handler with a fake
app service, build a task with a JSON payload, call `Handle(ctx, task)` directly,
and assert on the returned error (done vs retryable vs SkipRetry). Follow the
table-driven, one-decision-per-case rule from `go-conventions`.

```go
func TestPlacementFilePreprocessHandler_Handle(t *testing.T) {
	tests := []struct {
		name        string
		payload     any
		serviceErr  error
		wantErr     string
		wantNoRetry bool
	}{
		{
			name:        "skips retry on malformed payload",
			payload:     "not-an-object",
			wantErr:     "unmarshalling",
			wantNoRetry: true,
		},
		{
			name:       "retries on transient service error",
			payload:    worker.PlacementFilePreprocessPayload{AccountID: 1, FileKey: "k"},
			serviceErr: errors.New("db timeout"),
			wantErr:    "preprocessing placement file",
		},
		{
			name:    "succeeds on happy path",
			payload: worker.PlacementFilePreprocessPayload{AccountID: 1, FileKey: "k"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			body, _ := json.Marshal(tc.payload)
			task := asynq.NewTask(worker.TypePlacementFilePreprocess, body)

			h := worker.NewPlacementFilePreprocessHandler(
				func(worker.PlacementFilePreprocessPayload) worker.PreprocessService {
					return &fakeService{err: tc.serviceErr}
				},
				slog.Default(),
			)

			err := h.Handle(context.Background(), task)
			if tc.wantErr == "" {
				assert.NoError(t, err)
				return
			}
			assert.ErrorContains(t, err, tc.wantErr)
			assert.Equal(t, tc.wantNoRetry, errors.Is(err, asynq.SkipRetry))
		})
	}
}
```

For an integration test that a task actually round-trips through Redis, spin up
Redis with **testcontainers-go** and drive it with `asynqtest`/`asynq.Inspector`.

---

## Section 9 — Adding a new worker: checklist

1. Add the task-type and queue constants to `internal/worker/tasks.go`.
2. Create `internal/worker/<task>.go`: payload struct, `New<Task>Task` constructor,
   handler struct + `Handle`. Handler delegates to an app service — **no logic**.
3. Build the real work as an application service (`go-build-application-services`).
4. Register the handler in `NewMux` and give the queue a priority weight in
   `NewServer` (`server.go`).
5. Add a typed `Enqueue<Task>` method to `internal/worker/enqueuer.go` with the
   right options (queue, retries, timeout, unique, retention).
6. Call the enqueuer from the app service via a consumer-local interface.
7. If it must run on a schedule, register it with `asynq.Scheduler`
   (`go-build-schedulers`) — do not loop-enqueue.

---

## Checklist (reviewer)

- [ ] Payload is a **typed struct** with snake_case JSON tags — no loose maps.
- [ ] Task type, payload, constructor, and handler share **one name** (ubiquitous
      language); the string is `task:snake_case` matching the file.
- [ ] Handler `Handle` only decodes + propagates context + delegates to an app
      service. **No business logic, no inline SQL/S3/HTTP.**
- [ ] `request_id` is carried in the payload and re-hydrated into `ctx` + a child
      `slog.Logger` in the handler.
- [ ] Enqueue uses a typed `Enqueuer` method; options are explicit (queue, retries,
      timeout, unique/retention as appropriate).
- [ ] Retry is **return-driven**; permanent failures wrap `asynq.SkipRetry`.
- [ ] App service `Execute()` is **idempotent** (retries re-run the handler).
- [ ] Task registered in `NewMux`; queue has a priority weight in `NewServer`.
- [ ] `cmd/worker/main.go` is wiring only; `srv.Run` handles graceful shutdown.
- [ ] Handler has table-driven unit tests covering done / retry / SkipRetry — no
      Redis required.
- [ ] Recurring work uses `asynq.Scheduler` (`go-build-schedulers`), not a loop.
