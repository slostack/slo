---
name: go-test-lifecycle
description: Go lifecycle tests proving cancellation, wait, startup rollback, readiness and cleanup deterministically;
  isolated from Gin/PostgreSQL.
when_to_use: Go lifecycle tests proving cancellation, wait, startup rollback, readiness and cleanup deterministically;
  isolated from Gin/PostgreSQL.
group: languages
kind: skill
---

# Go Test Lifecycle

## Skill summary

Go lifecycle tests proving cancellation, wait, startup rollback, readiness and cleanup deterministically; isolated from Gin/PostgreSQL.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Deterministic harness

Use go-build-lifecycle's background package. The fake signals readiness through a channel; synchronization—not time.Sleep—establishes order. A timer bounds a broken test rather than supplying the intended ordering.

```go
package background

import (
    "context"
    "errors"
    "testing"
    "time"
)

type blockingOperation struct { started chan struct{} }
func (o blockingOperation) Run(ctx context.Context) error {
    close(o.started)
    <-ctx.Done()
    return ctx.Err()
}
func TestStopWait(t *testing.T) {
    started := make(chan struct{})
    runtime := Start(context.Background(), InputDAO{
        Operation: blockingOperation{started: started},
    })
    t.Cleanup(runtime.Stop)
    select {
    case <-started:
    case <-time.After(time.Second): t.Fatal("operation never started")
    }
    runtime.Stop()
    runtime.Stop()
    result := make(chan error, 1)
    go func() { result <- runtime.Wait() }()
    select {
    case err := <-result:
        if !errors.Is(err, context.Canceled) { t.Fatalf("wait: %v", err) }
    case <-time.After(time.Second): t.Fatal("operation did not stop")
    }
}
```

For bootstrap, inject recording acquisition/close interfaces. Table rows: first acquisition fails → no cleanup; second fails → first closed once; third fails → second then first closed; all succeed → publication only after final invariant; shutdown → cancellation then dependent stops then wait then stores close. Add cleanup-error rows preserving both primary and cleanup errors. A failure must return no published runtime and leave no listener or loop alive. Assert the full ordered event list, not just close counts.

Use net.Listen on 127.0.0.1:0 for a real listener adapter test with cleanup; don't reserve a fixed port. Assert readiness before exercising it, close then prove wait completed. Check connection-owned work stops with its connection but daemon-owned work survives that cancellation until daemon shutdown. Inject clock/timer interfaces for retry timing where appropriate.

Run targeted tests, `go test -race -count=1` on changed packages, full suite, build/vet and applicable build tags. No database/Gin fixture unless that lifecycle actually owns one. Avoid shared globals, process-wide signals and environment mutation in parallel tests. Record unsupported race platforms or unavailable dependencies as limitations, not green.

