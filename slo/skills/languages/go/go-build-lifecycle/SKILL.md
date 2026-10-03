---
name: go-build-lifecycle
description: Go typed runtime assembly and supervised bootstrap/launch/wait/shutdown with rollback, context
  ownership and compatibility.
when_to_use: Go typed runtime assembly and supervised bootstrap/launch/wait/shutdown with rollback, context
  ownership and compatibility.
group: languages
kind: skill
---

# Go Build Lifecycle

## Skill summary

Go typed runtime assembly and supervised bootstrap/launch/wait/shutdown with rollback, context ownership and compatibility.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Ownership map before implementation

Name the runtime noun, construction/result DAO, bootstrap service, lifecycle façade, adapter owners and every resource. Write a table: resource → acquire step → owning context → stop action → wait evidence → failed-start rollback. Public façade methods delegate; consumers receive narrow interfaces, not the whole runtime.

Bootstrap may open files/listeners/connections but must not publish partial runtime. Each successful acquisition immediately registers its cleanup; on failure unwind reverse order and preserve both primary and cleanup errors (errors.Join where supported, with an approved rendering contract). Only convert the typed construction result to the unexported runtime after invariants pass.

Prefer completing all fallible bootstrap before launching loops. If a compatibility boundary requires earlier launch, that loop is owned and joined during rollback before Start returns. Launch uses the daemon context for daemon work, connection context for connection work; never context.Background to detach a request-owned task silently.

## Supervised loop example

```go
// Package background owns a cancellable background operation.
package background

import "context"

type operation interface { Run(context.Context) error }
// InputDAO contains the single loop capability.
type InputDAO struct { Operation operation }
// Runtime owns cancellation and the one result channel.
// The lifecycle owner calls Wait exactly once after Stop or natural termination.
type Runtime struct {
    cancel context.CancelFunc
    done chan error
}
// Start launches one supervised operation after its caller finishes bootstrap.
func Start(parent context.Context, in InputDAO) *Runtime {
    ctx, cancel := context.WithCancel(parent)
    runtime := &Runtime{cancel: cancel, done: make(chan error, 1)}
    go func() {
        defer cancel()
        runtime.done <- in.Operation.Run(ctx)
        close(runtime.done)
    }()
    return runtime
}
// Stop requests cancellation; it is safe to call repeatedly.
func (r *Runtime) Stop() { r.cancel() }
// Wait joins the operation and returns its error; only the lifecycle owner calls it.
func (r *Runtime) Wait() error { return <-r.done }
```

The goroutine is supervised by an explicit owner and completion signal; it is not fire-and-forget. For multiple loops use the project's supervisor/errgroup or WaitGroup plus explicit error collection. Do not suppress unexpected operation errors merely because shutdown also occurred. A multi-caller Wait API needs stored terminal error and broadcast completion rather than this single-consumer contract.

## CLI façade and failure handling

Mirror atlasd's readable routing and output contracts: Cli holds output/error writers and a narrow lifecycle/config collaborator; cmd owns help/version/output/exit mapping only. ConfigSvc owns all parsing and precedence. Do not copy atlasd's help pre-scan or global getter. Help/version must not acquire daemon resources. Render an error once, preserving sentinel identity; an output-writer failure has an explicit tested contract. Shutdown must stop owned integrations, join loops and close resources in dependency order.

## Verification

See go-test-lifecycle. Cover each acquire failure, launch failure, natural loop failure, cancellation and reverse cleanup, no publication on failure, readiness visibility, repeated Stop, bounded wait completion and no work after shutdown. Race test the real concurrency boundary and supported build variants. Never rely on sleeps, global mutable function seams or killing unrelated processes.

