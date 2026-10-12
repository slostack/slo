---
name: go-build-workflow-orchestration
description: "Go scoped recipe (asynq, Temporal): The Go equivalent of DBOS durable multi-step workflows\
  \ \u2014 Temporal (go.temporal.io/sdk). Deterministic Workflow functions that orchestrate, side-effecting\
  \ Activities that do the IO (calling application services), a Worker that registers both, a client that\
  \ starts runs, and child workflows as the recursive-watcher analog. Covers signals, queries, timers,\
  \ retries, and heartbeats."
when_to_use: Only for the named project stack and component. Use when building durable, resumable, multi-step
  orchestration in Go where each step depends on the previous one (ETL pipelines, multi-stage report generation,
  sagas, human-in-the-loop flows) and progress must survive process crashes. For fire-and-forget background
  jobs, use build-go-workers (asynq) instead.
group: languages
kind: skill
---

# Building Durable Workflow Orchestration in Go (Temporal)

## Skill summary

- **Name:** `go-build-workflow-orchestration`
- **Description:** The Go equivalent of DBOS durable, multi-step workflows built on
  **Temporal** (`go.temporal.io/sdk`). Deterministic Workflow functions orchestrate;
  side-effecting Activities do all IO by calling application services; a Worker
  registers both; a client starts runs; child workflows are the recursive-watcher
  analog. Covers signals, queries, timers, retries, and heartbeats.
- **When to use:** Durable, resumable, multi-step orchestration where each step
  depends on the previous one and progress must survive crashes. For
  fire-and-forget jobs, use `go-build-workers`.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Build a durable 3-step report pipeline: generate records, generate control
  records, merge files."
- "Convert this DBOS watcher chain to Temporal."
- "How do I wait for a workflow step to complete before starting the next one in Go?"
- "Add a signal so an operator can approve a workflow mid-flight."
- "Set up a Temporal worker and register my workflows and activities."
- "My workflow is non-deterministic and won't replay — what did I do wrong?"
- "Model a fan-out/fan-in ETL where each child feeds the next stage."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

Defer to `go-conventions` for all naming, godoc, declarative-function,
ubiquitous-language, error-wrapping, and testing rules. This skill adds the
**Temporal-specific** conventions on top of those. A convention violation from
either skill is a blocker.

### Why Temporal is the DBOS analog

DBOS gives you durable workflows via Postgres-backed queues + recursive watchers:
a workflow runs, sets a completion event, and a watcher wakes up, decides what
runs next, and enqueues the next watcher. The durability guarantee is "each step
executes exactly once and survives a crash."

Temporal gives you the same guarantee with a cleaner primitive model. The mapping:

| DBOS concept | Temporal concept |
|---|---|
| Durable workflow function | **Workflow function** (deterministic orchestrator) |
| The actual side-effecting step (SQL, S3, HTTP) | **Activity function** (the durable step) |
| DBOS worker process / `launch_workers()` | **Worker** (`worker.New`, registers workflows + activities) |
| Enqueuer / `dbos_client.enqueue_async` | **Client** (`client.ExecuteWorkflow`) |
| `set_event` / `get_event` between workflows | **Signals** (`SignalWorkflow` / `workflow.GetSignalChannel`) |
| Reading live workflow state | **Queries** (`workflow.SetQueryHandler`) |
| Recursive watcher enqueuing the next watcher | **Child workflows** (`workflow.ExecuteChildWorkflow`) or a loop |
| `deduplication_id` / `SetWorkflowID` | **`WorkflowID`** + `WorkflowIDReusePolicy` |
| `queue_partition_key` (ordered processing) | **Task queue** name + `WorkflowID` (same ID serializes) |
| Retries / failure actions | Activity **`RetryPolicy`** + workflow-level compensation (saga) |

The single most important rule Temporal enforces that DBOS did informally: **all
IO happens in Activities; Workflow code is deterministic orchestration only.**
That is exactly the DBOS "never put business logic in the worker; delegate to
application services" rule, but Temporal will actively break replay if you violate
it. Internalize it.

---

### Section 1 — The determinism contract (read this first)

A Temporal Workflow function is **replayed** from its event history after any
crash or worker restart. For replay to produce the same decisions, Workflow code
must be **deterministic**. This is the hard boundary that does not exist in plain
Go job code.

**Inside a Workflow function you MUST NOT:**

- Call `time.Now()`, `time.Sleep()`, `rand`, or read the wall clock.
- Do network / DB / file / S3 IO directly.
- Read environment variables, global mutable state, or config that can change.
- Spawn raw goroutines (`go func`), use `sync` primitives, or channels directly.
- Iterate a native `map` in a way that depends on iteration order.
- Call `os.*`, `uuid.New()`, or any non-deterministic library.

**Instead, use the Temporal-safe replacements:**

| Forbidden | Use instead |
|---|---|
| `time.Now()` | `workflow.Now(ctx)` |
| `time.Sleep(d)` | `workflow.Sleep(ctx, d)` |
| `time.After(d)` | `workflow.NewTimer(ctx, d)` |
| `uuid.New()` / `rand` | `workflow.SideEffect(ctx, ...)` or generate it in an Activity |
| `go func(){}` | `workflow.Go(ctx, func(ctx workflow.Context){})` |
| channels | `workflow.NewChannel(ctx)` / signal channels |
| direct IO | an **Activity** (`workflow.ExecuteActivity`) |
| logging | `workflow.GetLogger(ctx)` (replay-aware; suppresses duplicate logs) |

```go
// Bad — non-deterministic Workflow: wall clock, direct IO, raw goroutine.
// This WILL fail to replay after a worker restart and corrupt the run.
func ProcessReportWorkflow(ctx workflow.Context, in ReportInput) error {
    started := time.Now()                       // ← wall clock: forbidden
    rows, err := db.Query("SELECT ...")         // ← direct IO: forbidden
    if err != nil {
        return err
    }
    go uploadInBackground(rows)                 // ← raw goroutine: forbidden
    time.Sleep(5 * time.Second)                 // ← real sleep: forbidden
    _ = started
    return nil
}

// Good — deterministic Workflow: clock, timer, and IO all go through Temporal.
func ProcessReportWorkflow(ctx workflow.Context, in ReportInput) error {
    started := workflow.Now(ctx)                // ← replay-safe clock
    logger := workflow.GetLogger(ctx)
    logger.Info("report workflow started", "workflowRunID", in.WorkflowRunID)

    var records RecordSet
    // IO is delegated to an Activity — the durable step.
    if err := workflow.ExecuteActivity(ctx, GenerateRecordsActivityName, in).
        Get(ctx, &records); err != nil {
        return fmt.Errorf("generating records: %w", err)
    }

    _ = workflow.Sleep(ctx, 5*time.Second)      // ← durable timer
    _ = started
    return nil
}
```

**Rule of thumb:** if a line in a Workflow function talks to the outside world or
depends on time/randomness, it belongs in an Activity. The Workflow only decides
*what runs, in what order, and what happens on failure*.

---

### Section 2 — File structure and naming

Mirror the domain/app split from `go-conventions`. Workflows and
activities are *orchestration wiring*; the real business logic stays in
application services (`internal/app/<feature>/service.go`).

```
internal/
├── workflow/
│   └── report/
│       ├── names.go          # task-queue, workflow, activity, signal name constants
│       ├── types.go          # workflow/activity input & output structs (typed boundaries)
│       ├── workflow.go       # deterministic Workflow functions (orchestration only)
│       └── activities.go     # Activity funcs — each calls ONE application service
├── app/
│   └── report/
│       └── service.go        # application service — Execute() does the real IO work
└── config/
    └── config.go
cmd/
├── worker/
│   └── main.go               # Worker: registers workflows + activities, polls task queue
└── starter/
    └── main.go               # (or a handler) starts workflows via the client
```

Rules:
- One task queue per workflow domain. All workflows + activities in that domain
  register on the same worker / task queue.
- Names live in `names.go` as `const` — never inline a workflow/activity/signal
  name string at a call site (the deduplication-ID and event-tracking discipline
  from DBOS).
- Activity structs receive their application-service dependencies via a constructor
  (`NewActivities(...)`), so IO is injected and mockable. Workflow functions take
  no dependencies — they are pure functions of their input + Temporal context.

---

### Section 3 — Names and typed boundaries

`names.go` — the single source of truth for every string identifier. This is the
Temporal analog of `DBOSQueues` / `DBOSWorkflows`:

```go
// Package report defines the durable report-generation workflow and its
// activities. All identifier strings live here so callers never inline them.
package report

// TaskQueue is the Temporal task queue this domain's worker polls.
// One queue per domain; the same WorkflowID always serializes onto it.
const TaskQueue = "report-task-queue"

// Workflow type names. Used by the client to start runs and by the worker to
// register handlers. Keep them stable — they are persisted in event history.
const (
    ProcessReportWorkflowName = "ProcessReportWorkflow"
    MergeFilesWorkflowName    = "MergeFilesWorkflow"
)

// Activity type names — one per durable, side-effecting step.
const (
    GenerateRecordsActivityName        = "GenerateRecordsActivity"
    GenerateControlRecordsActivityName = "GenerateControlRecordsActivity"
    MergeFilesActivityName             = "MergeFilesActivity"
    NotifyFailureActivityName          = "NotifyFailureActivity"
)

// Signal and query names for live interaction with a running workflow.
const (
    ApproveSignalName = "approve"
    ProgressQueryName = "progress"
)

// BuildWorkflowID builds the deterministic, unique WorkflowID for a run.
//
// A stable ID enables deduplication (WorkflowIDReusePolicy rejects a second
// start with the same ID) and lets callers signal/query the run later. This is
// the direct analog of the DBOS build_..._workflow_id helper.
func BuildWorkflowID(workflowRunID string) string {
    return fmt.Sprintf("%s-%s", ProcessReportWorkflowName, workflowRunID)
}
```

`types.go` — typed inputs/outputs for every workflow and activity. These are the
serialized boundary (Temporal marshals them to the event history), so they play
the role Pydantic DAOs played in DBOS. Follow the ubiquitous-language rule:
field names match DB columns and API fields exactly.

```go
// ReportInput is the input to ProcessReportWorkflow. Field names match the
// workflow_runs table columns; PartitionKey is carried through the whole chain.
type ReportInput struct {
    WorkflowRunID string            `json:"workflow_run_id"`
    PartitionKey  string            `json:"partition_key"`
    RunAttributes map[string]string `json:"run_attributes"` // user inputs, carried downstream
}

// RecordSet is the output of the record-generation activity: where the data
// landed, so the next step can consume it.
type RecordSet struct {
    S3Location string `json:"s3_location"`
    RowCount   int    `json:"row_count"`
}

// MergeInput is the input to the terminal merge step. It references the outputs
// of the prior steps so the chain stays data-driven, not implicit.
type MergeInput struct {
    WorkflowRunID string   `json:"workflow_run_id"`
    PartitionKey  string   `json:"partition_key"`
    SourceKeys    []string `json:"source_keys"`
}
```

---

### Section 4 — Activities: the durable, side-effecting steps

An Activity is where **all** IO happens. Each Activity is thin: it calls exactly
one application service (the DBOS "delegate to `...AppService.invoke()`" rule).
Activities can be retried automatically, so make them idempotent where possible.

```go
// Activities holds the dependencies every report activity needs. Injecting the
// application service (not raw DB/S3 clients) keeps IO behind the app layer and
// makes activities unit-testable with a fake service.
type Activities struct {
    reportService *appreport.Service
}

// NewActivities constructs the activity set with its application-service deps.
func NewActivities(reportService *appreport.Service) *Activities {
    return &Activities{reportService: reportService}
}

// GenerateRecordsActivity runs the record-generation step and returns where the
// data landed. It delegates all work to the application service.
//
// It is safe to retry: the underlying service writes to a deterministic S3 key
// derived from the WorkflowRunID, so a retry overwrites rather than duplicates.
func (a *Activities) GenerateRecordsActivity(
    ctx context.Context,
    in ReportInput,
) (RecordSet, error) {
    activity.GetLogger(ctx).Info("generating records", "workflowRunID", in.WorkflowRunID)

    location, rows, err := a.reportService.GenerateRecords(ctx, appreport.GenerateParams{
        WorkflowRunID: in.WorkflowRunID,
        PartitionKey:  in.PartitionKey,
        Attributes:    in.RunAttributes,
    })
    if err != nil {
        return RecordSet{}, fmt.Errorf("generating records for %s: %w", in.WorkflowRunID, err)
    }

    return RecordSet{S3Location: location, RowCount: rows}, nil
}
```

**Heartbeats for long activities.** An activity that runs longer than its
`StartToCloseTimeout` must heartbeat so Temporal knows it is alive and can
resume/cancel it. Heartbeat also carries progress for resumption:

```go
// MergeFilesActivity merges many source files into one. It heartbeats per file
// so a worker crash resumes from the last acknowledged index rather than 0.
func (a *Activities) MergeFilesActivity(ctx context.Context, in MergeInput) (string, error) {
    start := 0
    if activity.HasHeartbeatDetails(ctx) {
        _ = activity.GetHeartbeatDetails(ctx, &start) // resume from last checkpoint
    }

    for i := start; i < len(in.SourceKeys); i++ {
        if err := a.reportService.AppendToMerge(ctx, in.WorkflowRunID, in.SourceKeys[i]); err != nil {
            return "", fmt.Errorf("appending %s: %w", in.SourceKeys[i], err)
        }
        activity.RecordHeartbeat(ctx, i+1) // checkpoint progress
    }

    return a.reportService.FinalizeMerge(ctx, in.WorkflowRunID)
}
```

Rules:
- `context.Context` is the first parameter (it carries cancellation + heartbeat).
- Activities return `(T, error)` — the output is serialized into history and fed
  to the next workflow step. Wrap errors with `%w` and context.
- No business logic in the activity beyond marshalling to/from the app service.
- Make activities idempotent; retries are the norm, not the exception.

---

### Section 5 — The Workflow: deterministic orchestration

The Workflow function is the orchestrator — the `Execute()`-style table of
contents from `go-conventions`, but every "step" is an
`ExecuteActivity` call, and it reads deterministically for replay.

```go
// ProcessReportWorkflow orchestrates the 3-step report pipeline durably:
// generate records → generate control records → merge into the final file.
//
// It is deterministic: all IO is delegated to activities, all timing goes
// through the workflow context. On any activity failure the retry policy applies;
// if a step exhausts retries the workflow runs the compensation activity.
func ProcessReportWorkflow(ctx workflow.Context, in ReportInput) (string, error) {
    ctx = withDefaultActivityOptions(ctx)
    logger := workflow.GetLogger(ctx)
    logger.Info("report workflow started", "workflowRunID", in.WorkflowRunID)

    records, err := generateRecords(ctx, in)
    if err != nil {
        return "", compensate(ctx, in, err)
    }

    control, err := generateControlRecords(ctx, in, records)
    if err != nil {
        return "", compensate(ctx, in, err)
    }

    finalKey, err := mergeFiles(ctx, in, records, control)
    if err != nil {
        return "", compensate(ctx, in, err)
    }

    logger.Info("report workflow completed", "finalKey", finalKey)
    return finalKey, nil
}

// generateRecords runs the first durable step.
func generateRecords(ctx workflow.Context, in ReportInput) (RecordSet, error) {
    var out RecordSet
    err := workflow.ExecuteActivity(ctx, GenerateRecordsActivityName, in).Get(ctx, &out)
    return out, err
}

// generateControlRecords runs the second step, consuming the first step's output.
func generateControlRecords(ctx workflow.Context, in ReportInput, records RecordSet) (RecordSet, error) {
    var out RecordSet
    err := workflow.ExecuteActivity(ctx, GenerateControlRecordsActivityName, in, records).Get(ctx, &out)
    return out, err
}

// mergeFiles runs the terminal merge step over both prior outputs.
func mergeFiles(ctx workflow.Context, in ReportInput, records, control RecordSet) (string, error) {
    var finalKey string
    merge := MergeInput{
        WorkflowRunID: in.WorkflowRunID,
        PartitionKey:  in.PartitionKey,
        SourceKeys:    []string{records.S3Location, control.S3Location},
    }
    err := workflow.ExecuteActivity(ctx, MergeFilesActivityName, merge).Get(ctx, &finalKey)
    return finalKey, err
}

// compensate runs the failure action — the analog of DBOS failure_action_names.
func compensate(ctx workflow.Context, in ReportInput, cause error) error {
    // Use a disconnected context so compensation still runs even if the main
    // workflow context was cancelled.
    dctx, _ := workflow.NewDisconnectedContext(ctx)
    dctx = withDefaultActivityOptions(dctx)
    _ = workflow.ExecuteActivity(dctx, NotifyFailureActivityName, in, cause.Error()).Get(dctx, nil)
    return fmt.Errorf("report workflow failed for %s: %w", in.WorkflowRunID, cause)
}
```

**Activity options and retry policy** — the durability knobs. Set them once:

```go
// withDefaultActivityOptions attaches the standard timeouts + retry policy that
// every activity in this domain inherits. StartToClose caps a single attempt;
// the retry policy handles transient failures automatically.
func withDefaultActivityOptions(ctx workflow.Context) workflow.Context {
    return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
        StartToCloseTimeout:    10 * time.Minute,
        HeartbeatTimeout:       30 * time.Second, // required for long, heartbeating activities
        ScheduleToCloseTimeout: time.Hour,
        RetryPolicy: &temporal.RetryPolicy{
            InitialInterval:    time.Second,
            BackoffCoefficient: 2.0,
            MaximumInterval:    time.Minute,
            MaximumAttempts:    5,
            // Errors that should NOT be retried (e.g. bad input) go here.
            NonRetryableErrorTypes: []string{"InvalidInputError"},
        },
    })
}
```

---

### Section 6 — Child workflows: the recursive-watcher analog

The DBOS recursive watcher (watch run → decide next → enqueue next watcher) maps
to **child workflows** driven by a config-lookup loop. Each stage decides its
successor from the same `success_action_names` table, then either loops or spawns
a child, until a terminal node has no successor. This is durable and deterministic
because the "next step" decision is fetched via an Activity, then acted on in the
workflow.

```go
// PipelineWorkflow drives a data-driven chain of steps, mirroring the DBOS
// recursive watcher: run a step, ask the config which step(s) come next, and
// recurse via child workflows until a terminal step has no successor.
//
// The recursion is durable: each child is its own workflow with its own history,
// and ContinueAsNew keeps the parent history from growing unbounded on long chains.
func PipelineWorkflow(ctx workflow.Context, in StageInput) error {
    ctx = withDefaultActivityOptions(ctx)

    // 1. Run this stage's work (delegates to an activity → app service).
    if err := workflow.ExecuteActivity(ctx, RunStageActivityName, in).Get(ctx, nil); err != nil {
        return fmt.Errorf("running stage %s: %w", in.StageName, err)
    }

    // 2. Ask the configuration what runs next (the success_action_names lookup).
    var next []string
    if err := workflow.ExecuteActivity(ctx, NextStagesActivityName, in.StageName).Get(ctx, &next); err != nil {
        return fmt.Errorf("resolving successors of %s: %w", in.StageName, err)
    }

    // 3. Terminal node — no successors — the chain ends here (chain terminates).
    if len(next) == 0 {
        return nil
    }

    // 4. Spawn a child workflow per successor, in parallel, waiting for all.
    //    Each child recurses through the same PipelineWorkflow.
    futures := make([]workflow.ChildWorkflowFuture, 0, len(next))
    for _, stageName := range next {
        childInput := StageInput{
            WorkflowRunID: in.WorkflowRunID,
            PartitionKey:  in.PartitionKey, // SAME partition key through the whole chain
            StageName:     stageName,
            RunAttributes: in.RunAttributes,
        }
        childOpts := workflow.ChildWorkflowOptions{
            WorkflowID: fmt.Sprintf("%s-%s-%s", in.WorkflowRunID, stageName, in.PartitionKey),
        }
        cctx := workflow.WithChildOptions(ctx, childOpts)
        futures = append(futures, workflow.ExecuteChildWorkflow(cctx, PipelineWorkflow, childInput))
    }

    for _, f := range futures {
        if err := f.Get(ctx, nil); err != nil {
            return fmt.Errorf("child stage failed: %w", err)
        }
    }
    return nil
}
```

For a **linear** chain (the common case), prefer a loop with `ContinueAsNew` over
deep child nesting — it keeps event history bounded, which is the direct fix for
the DBOS "long-running worker / history bloat" pitfall:

```go
// LinearPipelineWorkflow walks a single-successor chain. ContinueAsNew restarts
// the workflow with fresh history at each hop, so a 500-step chain never grows an
// unbounded event history.
func LinearPipelineWorkflow(ctx workflow.Context, in StageInput) error {
    ctx = withDefaultActivityOptions(ctx)

    if err := workflow.ExecuteActivity(ctx, RunStageActivityName, in).Get(ctx, nil); err != nil {
        return fmt.Errorf("running stage %s: %w", in.StageName, err)
    }

    var next []string
    if err := workflow.ExecuteActivity(ctx, NextStagesActivityName, in.StageName).Get(ctx, &next); err != nil {
        return err
    }
    if len(next) == 0 {
        return nil // terminal
    }

    in.StageName = next[0]
    return workflow.NewContinueAsNewError(ctx, LinearPipelineWorkflow, in)
}
```

---

### Section 7 — Signals and queries (live interaction)

**Signals** are the DBOS "set an event another workflow waits on" primitive, but
externally addressable — an operator, an API handler, or a sibling workflow sends
one by `WorkflowID`. Use them for human-in-the-loop approval or late-arriving input.

```go
// ApprovalWorkflow runs work, then blocks until an operator signals approval or a
// timeout elapses. The signal is delivered durably: it survives worker restarts.
func ApprovalWorkflow(ctx workflow.Context, in ReportInput) error {
    ctx = withDefaultActivityOptions(ctx)

    if err := workflow.ExecuteActivity(ctx, GenerateRecordsActivityName, in).Get(ctx, nil); err != nil {
        return err
    }

    var approved bool
    signalCh := workflow.GetSignalChannel(ctx, ApproveSignalName)

    // Wait for either the approval signal or a 24h timeout — whichever first.
    selector := workflow.NewSelector(ctx)
    selector.AddReceive(signalCh, func(c workflow.ReceiveChannel, _ bool) {
        c.Receive(ctx, &approved)
    })
    timer := workflow.NewTimer(ctx, 24*time.Hour)
    selector.AddFuture(timer, func(workflow.Future) { approved = false })
    selector.Select(ctx)

    if !approved {
        return fmt.Errorf("approval not received for %s", in.WorkflowRunID)
    }
    return workflow.ExecuteActivity(ctx, MergeFilesActivityName, in).Get(ctx, nil)
}
```

Send the signal from a client (e.g. inside a Gin handler — see
`go-build-http-handlers`):

```go
err := temporalClient.SignalWorkflow(ctx, workflowID, "" /* runID: latest */,
    report.ApproveSignalName, true)
```

**Queries** expose live, read-only workflow state without a signal round-trip.
The handler must be deterministic and side-effect free (it may run during replay):

```go
// Inside the workflow, register a query handler that returns current progress.
progress := "pending"
_ = workflow.SetQueryHandler(ctx, ProgressQueryName, func() (string, error) {
    return progress, nil
})
// ... update `progress` as steps complete; queries read the latest value.
```

```go
// From a client / handler:
resp, err := temporalClient.QueryWorkflow(ctx, workflowID, "", report.ProgressQueryName)
var progress string
_ = resp.Get(&progress)
```

---

### Section 8 — The Worker (registers workflows + activities)

The Worker is the long-lived process that polls the task queue and executes both
workflow and activity tasks. This is the Temporal analog of the DBOS worker
launcher. `cmd/worker/main.go` is wiring only — no logic (the ~30-line rule).

```go
// Package main runs the report-domain Temporal worker: it registers every
// workflow and activity for the domain and polls the report task queue.
package main

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

    cfg, err := config.Load()
    if err != nil {
        logger.Error("loading config", "err", err)
        os.Exit(1)
    }

    temporalClient, err := client.Dial(client.Options{HostPort: cfg.TemporalHostPort})
    if err != nil {
        logger.Error("dialing temporal", "err", err)
        os.Exit(1)
    }
    defer temporalClient.Close()

    // Build the application service and inject it into the activities.
    reportService := appreport.NewService(cfg) // real DB/S3 clients live here
    activities := report.NewActivities(reportService)

    w := worker.New(temporalClient, report.TaskQueue, worker.Options{})

    // Register workflows by their stable type names.
    w.RegisterWorkflowWithOptions(report.ProcessReportWorkflow,
        workflow.RegisterOptions{Name: report.ProcessReportWorkflowName})
    w.RegisterWorkflowWithOptions(report.PipelineWorkflow,
        workflow.RegisterOptions{Name: "PipelineWorkflow"})

    // Register activities by their stable type names.
    w.RegisterActivityWithOptions(activities.GenerateRecordsActivity,
        activity.RegisterOptions{Name: report.GenerateRecordsActivityName})
    w.RegisterActivityWithOptions(activities.GenerateControlRecordsActivity,
        activity.RegisterOptions{Name: report.GenerateControlRecordsActivityName})
    w.RegisterActivityWithOptions(activities.MergeFilesActivity,
        activity.RegisterOptions{Name: report.MergeFilesActivityName})
    w.RegisterActivityWithOptions(activities.NotifyFailureActivity,
        activity.RegisterOptions{Name: report.NotifyFailureActivityName})

    if err := w.Run(worker.InterruptCh()); err != nil {
        logger.Error("worker stopped", "err", err)
        os.Exit(1)
    }
}
```

Rules:
- Register every workflow and activity by its `names.go` constant, not an inline
  string — the name is persisted in history and must never drift.
- One worker per task queue per domain. Scale by running more worker replicas;
  Temporal load-balances tasks across them.
- Activities get their app-service dependency injected at registration; workflows
  are registered as bare functions.

---

### Section 9 — Starting a workflow (the client)

Start a run from an API handler (thin — see `go-build-http-handlers`) or a CLI.
This replaces the DBOS enqueuer. The `WorkflowID` + reuse policy give you
deduplication for free.

```go
// StartReport starts a durable report workflow and returns its WorkflowID.
//
// The deterministic WorkflowID deduplicates: WorkflowIDReusePolicyRejectDuplicate
// causes a second start with the same run ID to fail rather than double-run.
func StartReport(ctx context.Context, c client.Client, in report.ReportInput) (string, error) {
    workflowID := report.BuildWorkflowID(in.WorkflowRunID)

    opts := client.StartWorkflowOptions{
        ID:                       workflowID,
        TaskQueue:                report.TaskQueue,
        WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
        WorkflowExecutionTimeout: 24 * time.Hour,
    }

    we, err := c.ExecuteWorkflow(ctx, opts, report.ProcessReportWorkflowName, in)
    if err != nil {
        return "", fmt.Errorf("starting report workflow %s: %w", in.WorkflowRunID, err)
    }
    return we.GetID(), nil
}
```

To wait for the result synchronously (rare — usually you fire-and-return the ID):

```go
var finalKey string
if err := we.Get(ctx, &finalKey); err != nil {
    return fmt.Errorf("awaiting report workflow: %w", err)
}
```

In a Gin handler, start the workflow and return the ID immediately in the standard
envelope; do **not** block the request on completion:

```go
// StartReport handles POST /rp/api/v1/reports — starts the durable pipeline.
func (h *ReportHandler) StartReport(c *gin.Context) {
    var req report.ReportInput
    if err := c.ShouldBindJSON(&req); err != nil {
        writeError(c, http.StatusBadRequest, err.Error(), "INVALID_REQUEST")
        return
    }
    id, err := StartReport(c.Request.Context(), h.temporal, req)
    if err != nil {
        writeError(c, http.StatusInternalServerError, err.Error(), "WORKFLOW_START_FAILED")
        return
    }
    writeSuccess(c, http.StatusAccepted, gin.H{"workflow_id": id})
}
```

---

### Section 10 — Complete worked flow (the 3-step report)

Putting the DBOS "TBI Acknowledgement Report" example into Temporal terms:

```
1. POST /rp/api/v1/reports  → handler binds ReportInput
   ↓
2. client.ExecuteWorkflow(ProcessReportWorkflowName, in)  with WorkflowID = report-<runID>
   ↓
3. Worker picks up the workflow task → ProcessReportWorkflow(ctx, in) begins
   ↓
4. ExecuteActivity(GenerateRecordsActivity)      → app service writes AACK CSV to S3
   |   (retried automatically on transient failure per RetryPolicy)
   ↓  returns RecordSet{S3Location: ".../aack.csv"}
5. ExecuteActivity(GenerateControlRecordsActivity, records) → writes ATRL CSV to S3
   ↓  returns RecordSet{S3Location: ".../atrl.csv"}
6. ExecuteActivity(MergeFilesActivity, {aack.csv, atrl.csv}) → merges, uploads final
   |   (heartbeats per file; a crash resumes mid-merge)
   ↓  returns finalKey
7. Workflow returns finalKey → run is COMPLETED in Temporal history (durable)

   On any step exhausting retries:
   → compensate() runs NotifyFailureActivity on a disconnected context,
     then the workflow fails with the wrapped cause (the failure_action analog).
```

Every box in that diagram survives a worker crash: Temporal replays the workflow
from history and skips already-completed activities. That is the same
exactly-once, resumable guarantee DBOS gave you — enforced by the platform.

---

### Section 11 — Testing

Temporal ships a test framework (`go.temporal.io/sdk/testsuite`) that runs a
workflow in-memory with mocked activities. Follow the table-driven,
one-decision-per-test rule from `go-conventions`.

**Test the workflow with mocked activities** (asserts orchestration/decisions):

```go
func TestProcessReportWorkflow(t *testing.T) {
    var ts testsuite.WorkflowTestSuite
    env := ts.NewTestWorkflowEnvironment()

    // Mock each activity by name; assert the workflow calls them in order.
    env.OnActivity(report.GenerateRecordsActivityName, mock.Anything, mock.Anything).
        Return(report.RecordSet{S3Location: "s3://aack.csv"}, nil)
    env.OnActivity(report.GenerateControlRecordsActivityName, mock.Anything, mock.Anything, mock.Anything).
        Return(report.RecordSet{S3Location: "s3://atrl.csv"}, nil)
    env.OnActivity(report.MergeFilesActivityName, mock.Anything, mock.Anything).
        Return("s3://final.csv", nil)

    env.ExecuteWorkflow(report.ProcessReportWorkflow, report.ReportInput{WorkflowRunID: "run-1"})

    require.True(t, env.IsWorkflowCompleted())
    require.NoError(t, env.GetWorkflowError())

    var finalKey string
    require.NoError(t, env.GetWorkflowResult(&finalKey))
    require.Equal(t, "s3://final.csv", finalKey)
}
```

**Test compensation fires on failure** (one decision point: the failure path):

```go
func TestProcessReportWorkflow_CompensatesOnFailure(t *testing.T) {
    var ts testsuite.WorkflowTestSuite
    env := ts.NewTestWorkflowEnvironment()

    env.OnActivity(report.GenerateRecordsActivityName, mock.Anything, mock.Anything).
        Return(report.RecordSet{}, errors.New("s3 unavailable"))
    // Assert the failure action runs.
    env.OnActivity(report.NotifyFailureActivityName, mock.Anything, mock.Anything, mock.Anything).
        Return(nil).Once()

    env.ExecuteWorkflow(report.ProcessReportWorkflow, report.ReportInput{WorkflowRunID: "run-1"})

    require.True(t, env.IsWorkflowCompleted())
    require.Error(t, env.GetWorkflowError())
    env.AssertExpectations(t)
}
```

**Test the activity independently** with a faked application service (the app
service itself is tested per `go-build-application-services`):

```go
func TestGenerateRecordsActivity(t *testing.T) {
    var ts testsuite.WorkflowTestSuite
    env := ts.NewTestActivityEnvironment()

    activities := report.NewActivities(fakeReportService{location: "s3://x.csv", rows: 42})
    env.RegisterActivity(activities.GenerateRecordsActivity)

    val, err := env.ExecuteActivity(activities.GenerateRecordsActivity,
        report.ReportInput{WorkflowRunID: "run-1"})
    require.NoError(t, err)

    var out report.RecordSet
    require.NoError(t, val.Get(&out))
    require.Equal(t, 42, out.RowCount)
}
```

---

### Section 12 — Common pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| **Non-determinism in workflow code** | `nondeterministic error` on replay after a deploy/restart. | Move all IO/clock/rand/goroutines out of the workflow (Section 1). |
| **Inline name strings** | Renaming a workflow breaks running executions; watchers can't find events. | All names in `names.go`; register + call by constant. |
| **Business logic in the workflow or activity** | Untestable, non-idempotent steps. | Delegate to the application service; activity is a thin adapter. |
| **Non-idempotent activity + retries** | Duplicate rows / duplicate S3 objects. | Derive keys deterministically from `WorkflowRunID`; make writes overwrite. |
| **Unbounded history on long chains** | Slow replays, worker OOM (the DBOS "long-running worker" pitfall). | Use `ContinueAsNew` for linear loops; scope child workflows. |
| **Missing heartbeat on long activity** | Activity killed at `StartToCloseTimeout` mid-work. | Set `HeartbeatTimeout` + `RecordHeartbeat`; resume from details. |
| **Compensation skipped because context cancelled** | Failure notifications never sent. | Run compensation on `workflow.NewDisconnectedContext`. |
| **Circular successors in the config chain** | Infinite child-workflow spawning. | Design terminal nodes; validate the successor graph is a DAG. |
| **Bad input retried forever** | Workflow stuck retrying a permanent error. | Add the error type to `NonRetryableErrorTypes`. |

---

### Section 13 — Contrast: workflows vs background jobs

Do not reach for Temporal when a fire-and-forget job will do. The distinction:

| | `go-build-workers` (asynq) | `go-build-workflow-orchestration` (Temporal) |
|---|---|---|
| Purpose | Independent, fire-and-forget tasks | Multi-step, stateful orchestration |
| State | Stateless per task | Durable workflow state across steps |
| Failure | Retry the single task | Retry a step; compensate the workflow |
| Ordering / dependencies | None (or crude cron) | First-class: each step feeds the next |
| Resumability | Task re-runs from scratch | Replays; completed steps are skipped |
| Cost / overhead | Low (Redis) | Higher (Temporal cluster) |
| Use when | Send an email, resize an image, nightly cron | ETL pipeline, saga, human-in-the-loop, report chain |

If a step depends on a prior step's output, needs exactly-once resumable
execution, or must wait on an external signal — use Temporal. Otherwise use asynq.

---

## Checklist

Run through this before merging a Temporal workflow. Each unchecked item is a
**blocker** (in addition to the `go-conventions` checklist).

### Determinism
- [ ] No `time.Now`, `time.Sleep`, `rand`, `uuid.New`, `os.*`, or env reads in
      workflow code — the Temporal-safe replacement is used instead.
- [ ] No direct DB/S3/HTTP/file IO in workflow code — all IO is in activities.
- [ ] No raw goroutines/channels/`sync` in workflow code — `workflow.Go` /
      `workflow.NewChannel` / selectors used instead.

### Structure & naming
- [ ] All task-queue, workflow, activity, signal, and query names live in
      `names.go` as constants; nothing is inlined at a call site.
- [ ] `WorkflowID` is deterministic (`BuildWorkflowID`) and a reuse policy is set
      for deduplication.
- [ ] Workflow functions are orchestration-only tables of contents; each step is a
      named private helper calling `ExecuteActivity`.
- [ ] Each activity is thin and delegates to exactly one application service.

### Durability
- [ ] Every activity has explicit timeouts and a `RetryPolicy`; permanent errors
      are in `NonRetryableErrorTypes`.
- [ ] Long activities set `HeartbeatTimeout` and call `RecordHeartbeat`, resuming
      from heartbeat details.
- [ ] Long/linear chains use `ContinueAsNew` (or scoped child workflows) to bound
      event-history size.
- [ ] The failure path runs a compensation activity on a disconnected context.

### Worker & client
- [ ] The worker registers every workflow and activity by its `names.go` constant.
- [ ] Activities receive their application-service dependency via `NewActivities`.
- [ ] The starter/handler returns the `WorkflowID` without blocking on completion.

### Testing
- [ ] The workflow is tested with `testsuite` and mocked activities (happy path +
      compensation path), one decision per test.
- [ ] Each activity is tested via `NewTestActivityEnvironment` with a faked app
      service.

---

## Cross-references

- `go-conventions` — naming, godoc, declarative structure, ubiquitous
  language, error wrapping, table-driven tests. Non-negotiable base layer.
- `go-build-application-services` — the `Execute()` orchestrator that every
  activity delegates to; where the real IO and business logic live.
- `go-build-workers` — asynq fire-and-forget background jobs. The contrast in
  Section 13; use it when there is no multi-step dependency or resumability need.
- `go-build-http-handlers` — thin Gin handlers that start/signal/query workflows.
