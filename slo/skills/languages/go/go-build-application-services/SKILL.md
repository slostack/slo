---
name: go-build-application-services
description: Go workflow services with typed construction/input/result DAOs, consumer-local interfaces,
  named steps, transaction ownership and no per-request state.
when_to_use: Go workflow services with typed construction/input/result DAOs, consumer-local interfaces,
  named steps, transaction ownership and no per-request state.
group: languages
kind: skill
---

# Go Build Application Services

## Skill summary

Go workflow services with typed construction/input/result DAOs, consumer-local interfaces, named steps, transaction ownership and no per-request state.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Ownership and placement

Read go-conventions first. A service owns one workflow; a separate unrelated workflow gets another service. `internal/app/<concern>/service.go` is a useful layout, not a requirement to rename a working project. Keep input/result DAOs and errors beside their owner. Domain services own state transitions; adapters own mechanics. `Execute(ctx, in)` is the public workflow gateway; lifecycle façades may use exact Start/Stop/Wait verbs. Pure support services may expose cohesive domain verbs.

## Complete minimal orchestration example

This dependency-free example is a compilable package. It demonstrates typed construction, a consumer-owned boundary, operation-wrapped sentinels and no request state. Real collaborators supply the implementation structurally.

```go
// Package activation orchestrates account activation and notification.
package activation

import (
    "context"
    "fmt"
)

// ActivateDAO carries one activation request.
type ActivateDAO struct { AccountID string }
// ResultDAO carries the resolved activation result.
type ResultDAO struct { AccountID string }
// NoticeDAO carries the notification boundary data.
type NoticeDAO struct { AccountID string }

type accountActivator interface {
    Activate(context.Context, ActivateDAO) (ResultDAO, error)
}
type notifier interface {
    Send(context.Context, NoticeDAO) error
}

// DependenciesDAO carries required collaborators, supplied before publication.
type DependenciesDAO struct {
    Accounts accountActivator
    Notices notifier
}
// Service owns the activation workflow, not per-request state.
type Service struct {
    accounts accountActivator
    notices notifier
}
// New constructs a reusable service from required collaborators.
// The composition root must supply initialized, non-nil collaborators.
func New(in DependenciesDAO) *Service {
    return &Service{accounts: in.Accounts, notices: in.Notices}
}
// Execute activates the account then sends its notification.
// Notification failure does not undo an already committed activation.
func (s *Service) Execute(ctx context.Context, in ActivateDAO) (ResultDAO, error) {
    result, err := s.activate(ctx, in)
    if err != nil { return ResultDAO{}, fmt.Errorf("activating: %w", err) }
    if err := s.notify(ctx, result); err != nil {
        return ResultDAO{}, fmt.Errorf("notifying: %w", err)
    }
    return result, nil
}
func (s *Service) activate(ctx context.Context, in ActivateDAO) (ResultDAO, error) {
    return s.accounts.Activate(ctx, in)
}
func (s *Service) notify(ctx context.Context, result ResultDAO) error {
    return s.notices.Send(ctx, NoticeDAO{AccountID: result.AccountID})
}
```

Construct with `New(DependenciesDAO{Accounts: accounts, Notices: notices})`, never five positional dependencies. Validate mandatory construction invariants before publishing the service/runtime; interface typed-nil pitfalls require attention at the composition root.

## Atomicity and side effects

For cross-domain writes, the application service owns the transaction/rollback boundary. A named `persist` step opens the transaction and passes its handle to all real domain collaborators; inner calls must not commit independently. Do not put transaction closures, SQL, policy branches or payload decoding directly in Execute.

With GORM, the persist step uses `db.WithContext(ctx).Transaction(func(tx *gorm.DB) error { return s.persistWithin(ctx, PersistDAO{Tx: tx, Input: in}) })`; the named DAO and helper are project types, not library APIs. `persistWithin` constructs transaction-scoped collaborators through typed factories, runs ordered steps and returns the first wrapped failure. Use the equivalent adapter contract for another store. Do not add GORM just to express this boundary.

Email/event/cache effects cannot be rolled back by SQL. Either run approved best-effort effects after commit with explicit failure semantics, or persist an outbox atomically and publish with retries/idempotency. The example's post-commit failure is deliberate; a production signup flow must decide replay and duplicate-notification behavior before coding. Never report success without durable required effects.

## Required tests and review

Use go-test-orchestration for deterministic recorder tests: happy order, exact arguments/result, each failure cutoff and absent later effects, cancellation propagation, repeated calls with no request-state leakage. Use go-test-application-services for real database atomicity, constraints and rollback. Assert errors.Is and exact rendered errors at compatibility boundaries. Reject provider-exported interfaces, service locators, public mutable collaborator bags, global test seams, one service for unrelated workflows, or helper extraction that leaves ownership unchanged.

