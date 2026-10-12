---
name: go-build-domain-features
description: Go resolved model, transient DAO and cohesive domain service with typed validation, state
  transitions, repository boundaries and explicit transaction ownership.
when_to_use: Go resolved model, transient DAO and cohesive domain service with typed validation, state
  transitions, repository boundaries and explicit transaction ownership.
group: languages
kind: skill
---

# Go Build Domain Features

## Skill summary

Go resolved model, transient DAO and cohesive domain service with typed validation, state transitions, repository boundaries and explicit transaction ownership.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Scope and source reconciliation

Read go-conventions. A domain is a cohesive concept; in relational projects a table-backed domain remains a useful granularity. Do not require every in-memory lifecycle/support concept to have a database table. `dao.go` owns transient data, **not** a repository renamed DAO. Put persistence in repository.go / a focused adapter, service policy in service.go, model state in model.go, errors in errors.go. Additional focused files are justified by role boundaries rather than a ceremonial three-file quota.

## Model / DAO / service example

```go
// Package order owns order state transitions.
package order

import (
    "context"
    "errors"
    "fmt"
    "time"
)

// ErrInvalidTransition means the source state cannot be shipped.
var ErrInvalidTransition = errors.New("order: invalid transition")
// ErrNotFound means the order does not exist.
var ErrNotFound = errors.New("order: not found")
// Order contains resolved persisted state.
type Order struct {
    ID string
    Status string
    ShippedAt *time.Time
}
// ShipDAO carries the state-transition boundary.
type ShipDAO struct { OrderID string }
// Validate checks intrinsic input shape, not current-state policy.
func (in ShipDAO) Validate() error {
    if in.OrderID == "" { return ErrNotFound }
    return nil
}
type repository interface {
    Find(context.Context, string) (Order, error)
    Save(context.Context, Order) error
}
// DependenciesDAO carries collaborators required by Service.
type DependenciesDAO struct {
    Repository repository
    Now func() time.Time
}
// Service owns order state transitions.
type Service struct {
    repository repository
    now func() time.Time
}
// New creates a service; both collaborators must be initialized.
func New(in DependenciesDAO) *Service {
    return &Service{repository: in.Repository, now: in.Now}
}
// MarkAsShipped permits only paid orders and persists the shipment time.
func (s *Service) MarkAsShipped(ctx context.Context, in ShipDAO) (Order, error) {
    if err := in.Validate(); err != nil { return Order{}, err }
    item, err := s.loadShippable(ctx, in)
    if err != nil { return Order{}, fmt.Errorf("loading shippable order: %w", err) }
    return s.saveShipped(ctx, item)
}
func (s *Service) loadShippable(ctx context.Context, in ShipDAO) (Order, error) {
    item, err := s.repository.Find(ctx, in.OrderID)
    if err != nil { return Order{}, err }
    if item.Status != "paid" { return Order{}, ErrInvalidTransition }
    return item, nil
}
func (s *Service) saveShipped(ctx context.Context, item Order) (Order, error) {
    at := s.now().UTC()
    item.Status, item.ShippedAt = "shipped", &at
    if err := s.repository.Save(ctx, item); err != nil {
        return Order{}, fmt.Errorf("saving shipped order: %w", err)
    }
    return item, nil
}
```

For an existing domain use its named state constants, not new synonyms. For concurrent transitions the repository must enforce the expected source state atomically (conditional update/version or lock in the owning transaction); a read-then-save example alone does not prove concurrency safety. Add the stale-write/race scenario before implementing it.

## Persistence recipe (only when applicable)

For GORM: model tags mechanically match canonical columns; nullable columns use pointers, UTC timestamps use approved model hooks, and migrations—not production AutoMigrate—own schema. Table names are plural and package names singular in the established relational layout. Translate gorm.ErrRecordNotFound to the domain ErrNotFound at the adapter. Use WithContext on every query. A typed UpdateDAO with pointer fields distinguishes unchanged from explicitly zero; build any driver map privately inside the adapter, never pass it across a boundary. A nullable column that can be cleared needs explicit presence plus value, not a pointer that conflates absent and null.

DAO.Validate owns intrinsic field/shape rules; the service owns contextual policy (authorization, allowed state transition, current account state). Request/response DAOs stay with their boundary/domain owner, not as anonymous handler structs. Mapping is mechanical and must not silently rename wire fields.

Provide dedicated MarkAs<State> methods, not a generic caller-controlled status setter. Boolean toggle APIs preserve the established nil=flip / explicit=value behavior in a named ToggleDAO; concurrent flips require an atomic store operation. Test false/zero as real supplied values.

One owner opens/commits a transaction. A single-domain owner may coordinate its own atomic state/outbox write; cross-domain atomicity is the application service's job. Inner methods accept the transaction-scoped collaborator and never commit. Past-tense typed event DAOs carry version and occurrence time; persist required outbox events with the state change, then publish under supervised retry ownership. Do not publish to NATS inside an SQL transaction and claim atomicity.

## Test matrix

Write table rows first for valid transition, invalid source, missing row, validation failure, read/save errors, timestamp, no write on guard failure, explicit false/zero and stale concurrent update. Recorders prove policy/call cutoffs; real migrated Postgres proves constraints, atomic updates, committed visibility and rollback. Assert sentinel identity and persisted fields, never merely non-nil output. Use go-test-domain-services for the detailed real-store harness; keep isolated domain tests independent of Docker.

