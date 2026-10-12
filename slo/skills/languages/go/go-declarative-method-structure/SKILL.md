---
name: go-declarative-method-structure
description: "Go-specific syntax, boundaries, errors, and lifecycle contracts for the shared declarative-method-structure owner."
when_to_use: Use for Go functions, application services, domain services, lifecycle code, and orchestration after reading the generic owner.
group: languages
kind: skill
---

# Go Declarative Method Structure

## Skill summary

This is the Go specialization of the shared owner at
`skills/coding/declarative-method-structure/SKILL.md`. Read that owner first
for coherent decomposition, one decision per method, Tell, Don't Ask, flat
control flow, meaningful examples, testing boundaries, and the generic review
checklist. This file does not restate those generic lessons.

This specialization owns Go idioms and obligations: typed input/result DAOs,
consumer-local interfaces, context-first blocking methods, `Execute(ctx, in)`
workflows, operation-wrapped errors, lifecycle/goroutine ownership, and the Go
guidance of approximately **15 lines of substantive logic or fewer**. The
threshold is a review signal, not an invitation to create shallow helpers. Go's
expected `if err != nil` guards are part of declarative boundary control.

## Examples

- Use this file for Go application-service and domain-service boundaries.
- Use it for typed DAOs, consumer-owned interfaces, `%w` error context, and lifecycle ownership.
- Use the generic owner for the full language-independent before/after teaching patterns.

## Guidance

**Scope:** Go. Read `skills/languages/go/go-conventions/SKILL.md` and select the
applicable build, lifecycle, adapter, framework, and test recipes. Atlas source
is evidence for these idioms, not a universal dependency or framework mandate.
Do not infer Gin, GORM, NATS, asynq, Temporal, or ClickHouse from this skill.

### Typed boundaries and consumer-owned interfaces

Use a named DAO when a boundary has multiple non-obvious values. Define minimal
interfaces at the consumer, keep required dependency fields named, and keep
request-specific mutable state out of long-lived services. Context comes first
for blocking operations. Keep `cmd/` focused on wiring, I/O routing, help,
and exit mapping.

```go
package activation

import "context"

type ActivateDAO struct{ AccountID string }
type ResultDAO struct{ AccountID string }

type accountActivator interface {
    Activate(context.Context, ActivateDAO) (ResultDAO, error)
}
type notifier interface { Send(context.Context, ResultDAO) error }

type Service struct {
    accounts accountActivator
    notices  notifier
}
```

This is a standalone illustrative declaration fragment: it is complete Go
syntax but intentionally omits constructor and implementation details. The
generic owner carries cross-language semantics; Go project conventions define
package, documentation, and dependency requirements.

### `Execute(ctx, in)` as a table of contents

The entry point should show ordering and error boundaries, not policy branching,
persistence mechanics, decoding, or goroutine bodies. Wrap errors at meaningful
operation boundaries with `%w` so callers can use `errors.Is`/`errors.As`:

```go
func (s *Service) Execute(ctx context.Context, in ActivateDAO) (ResultDAO, error) {
    result, err := s.activate(ctx, in)
    if err != nil {
        return ResultDAO{}, fmt.Errorf("activating: %w", err)
    }
    if err := s.notify(ctx, result); err != nil {
        return ResultDAO{}, fmt.Errorf("notifying: %w", err)
    }
    return result, nil
}

func (s *Service) activate(ctx context.Context, in ActivateDAO) (ResultDAO, error) {
    return s.accounts.Activate(ctx, in)
}

func (s *Service) notify(ctx context.Context, result ResultDAO) error {
    return s.notices.Send(ctx, result)
}
```

For cross-domain writes, the application service owns the transaction or
rollback boundary. Domain services own state transitions; adapters own
persistence, transport, filesystem, or protocol mechanics. Do not hide a
transaction closure or policy matrix inside `Execute`.

### Flat guards and the Go decomposition signal

Use early returns and at most one normal nesting level. Approximately **15
lines of substantive logic or fewer** is the Go refactoring signal. Count
substantive statements, not braces or expected error guards. Extract only when
a helper has a clean input, output, owner, and test contract; never split a
coherent thought merely to satisfy the number.

```go
func (s *DaemonRuntimeSvc) Execute(ctx context.Context, in RuntimeDAO) (RuntimeResultDAO, error) {
    config, err := s.resolveConfig(ctx, in)
    if err != nil {
        return RuntimeResultDAO{}, fmt.Errorf("resolving config: %w", err)
    }
    runtime, err := s.buildRuntime(ctx, config)
    if err != nil {
        return RuntimeResultDAO{}, fmt.Errorf("building runtime: %w", err)
    }
    return s.validateAndPublish(runtime)
}
```

### Tell, Don't Ask and lifecycle ownership

A caller tells the domain/support owner to perform behavior; it does not read
state and reproduce validation. Every background operation has one owner that
starts it, documents cancellation, stops it, waits for it, and tests completion.
Do not launch raw unsupervised goroutines:

```go
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
```

Bootstrap, launch, wait, and shutdown should be named lifecycle phases. A
failed start must not publish a partial runtime or leave a listener/goroutine
running; rollback and cleanup are part of the service contract.

### Dispatch, errors, and compatibility

Use registry/interface dispatch when handlers are independently extensible; a
small closed choice may remain a switch. Use package-owned sentinels or typed
errors, `%w`, `errors.Is`, and `errors.As`; never branch on error strings. Exact
CLI/RPC/wire error text is observable compatibility and needs explicit tests.

## Go refactor triggers

| Go signal | Action |
|---|---|
| More than one normal nesting level | Extract a named guard, policy, or workflow step. |
| Approximately 15 lines of substantive logic | Review for a clean independent step, not a quota. |
| `Execute` contains SQL, decoding, or goroutine bodies | Move mechanics to the owning adapter/step. |
| Caller inspects domain state and decides | Tell the state owner to act. |
| Provider exports an interface for one implementation | Define the minimal interface at the consumer. |
| Background operation lacks stop/wait ownership | Add an explicit lifecycle owner and deterministic test. |

## Go checklist

- [ ] Did I read the generic owner and `go-conventions` first?
- [ ] Does the service own one cohesive workflow with typed DAOs and no request state?
- [ ] Does `Execute(ctx, in)` read as named steps with operation-wrapped errors?
- [ ] Are contexts first for blocking work and interfaces owned by consumers?
- [ ] Are guards flat and is approximately 15 lines used as a signal, not a quota?
- [ ] Does every extracted helper satisfy meaningful decomposition?
- [ ] Does one owner start, cancel, stop, wait for, and test every goroutine?
- [ ] Are sentinel/error compatibility and transaction boundaries explicit?
- [ ] Do tests cover order, cutoffs, cleanup, persistence/protocol boundaries, and race/build gates as applicable?
