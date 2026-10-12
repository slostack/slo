---
name: go-test-application-services
description: 'Go database-backed integration recipe (real domain collaborators; disposable PostgreSQL/GORM).
  Not isolated orchestration: Go scoped recipe (GORM, testcontainers, asynq): How to write transactional
  unit tests for Go application services that orchestrate across domain services. Uses testify + testcontainers-go,
  a real Postgres via GORM with transaction-per-test isolation, mocks external clients at their interface
  boundary (testify/mock or hand-written fakes), and asserts the orchestration outcome plus side effects
  (rows written, jobs/events enqueued).'
when_to_use: Only for the named project stack and component. Use when testing an `Execute()`-style application
  service that wires multiple real domain services together and calls out to external systems. Pick this
  layer over a domain-service test (too low) or a handler test (too broad, goes through HTTP).
group: languages
kind: skill
---

# Test Go Application Services

## Skill summary

- **Name:** `go-test-application-services`
- **Description:** Transactional unit tests for Go application services — the
  orchestrators that sequence multiple real domain services and external clients.
  Real Postgres (testcontainers-go) with transaction-per-test isolation for the
  domain layer; interface-boundary mocks (testify/mock or hand-written fakes) for
  external clients; assertions on the orchestration outcome and its side effects.
- **When to use:** When testing an application service's `Execute()` (or a named
  entry method) end-to-end across its domain collaborators, without going through
  HTTP.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write a test for the `CreateReportService.Execute()` orchestrator."
- "Test the coupon-claim application service with a mocked payment client and a real DB."
- "How do I mock an external client but keep the DB real in a Go app-service test?"
- "Set up transaction-per-test isolation with testcontainers-go and GORM."
- "Assert that the app service enqueued an asynq job after persisting the row."
- "Add a guard-failure test for each `check*` step in this orchestrator."
- "The app-service test seeds rows by hand — is that right, or should it drive the real domain services?"

---

## Guidance

**Test category:** database-backed integration. Keep real domain collaborators here; use go-test-orchestration recording fakes for isolated order/cutoff behavior. A skip because Docker is unavailable is unverified integration evidence, not a passing gate.

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

An application service test sits **between** a domain-service test
([go-test-domain-services](../go-test-domain-services/SKILL.md)) and a handler test. It exercises one workflow on the
service — `svc.Execute(ctx, ...)` or a named entry method — against a **real
Postgres** through its **real domain-service collaborators**, while **mocking
external clients** (payment, telephony, S3, third-party APIs) at their interface
boundary. It asserts the orchestration *outcome* and its *side effects*.

Defer to [go-conventions](../go-conventions/SKILL.md) for naming, struct-field, godoc, and
declarative-structure rules. Defer to [go-build-application-services](../go-build-application-services/SKILL.md) for how the
`Execute()` orchestrator and its private step methods are structured, and to
[go-build-clients](../go-build-clients/SKILL.md) for how external clients expose the interface you mock here.

> Go has no pytest fixtures, no `@pytest.mark.asyncio`, no Pydantic form
> validation, and no SQLAlchemy savepoint fixture. The Python original leaned on
> all four. The Go equivalents are: `TestMain` + testcontainers-go for the
> container, a per-test GORM transaction rolled back in `t.Cleanup`, plain struct
> construction for params, and testify/mock (or a hand-written fake) at the client
> interface. The **principle survives**: real DB + real domain services + mocked
> externals, one workflow per test, assert the outcome and the side effects.

---

## 1. What an application-service test exercises

An application-service test:

1. Builds prerequisite domain state by calling the **real domain services**
   (not hand-written `INSERT`s) on a transaction-scoped `*gorm.DB`.
2. Constructs the application service with the **same dependencies the handler
   injects** — real domain services + mocked external clients.
3. Constructs the params struct with the **production param type** (never a `map`).
4. Calls the entry method: `svc.Execute(ctx, params)`.
5. Asserts on the **returned result**, the **persisted DB state**, and the
   **side effects on the mocked clients** (calls made, args passed), OR on the
   returned error.

It does **not** exercise:

- HTTP, Gin binding, middleware, auth, or the response envelope — that is a handler
  test.
- Domain-service implementation details (filter SQL, defaults, JSON tags) — those
  have their own tests ([go-test-domain-services](../go-test-domain-services/SKILL.md)). App-service tests treat
  domain services as trusted collaborators.

---

## 2. File layout and naming

| Item | Convention |
|---|---|
| Test file | `internal/app/<feature>/service_test.go`, alongside the service it tests |
| Package | `package <feature>` (white-box; the test needs the unexported step methods and struct wiring) |
| Test func | `TestService_Execute`, or `TestService_<EntryMethod>` — one per public entry method |
| Sub-tests | `t.Run("when campaign is not active", ...)` — one per guard / branch, plus a happy path |
| Shared infra | `TestMain` in the same package (or a shared `internal/testinfra` helper) spins up the container once |

Table-driven is the default for the *pure* branches; the happy path and side-effect
assertions usually justify their own explicit sub-test because they set up mock
expectations. Mixing both in one function is fine — see [§6](#6-a-full-app-service-test).

---

## 3. Test infrastructure — testcontainers-go + one transaction per test

Spin the container up **once per package** in `TestMain`, run migrations against it
once, then give **each test its own transaction** that is rolled back in
`t.Cleanup`. Rollback is the Go equivalent of the Python savepoint fixture: it
isolates tests without truncating tables between them.

```go
package createcoupon

import (
    "context"
    "database/sql"
    "fmt"
    "os"
    "testing"

    "github.com/pressly/goose/v3"
    "github.com/testcontainers/testcontainers-go"
    "github.com/testcontainers/testcontainers-go/modules/postgres"
    "github.com/testcontainers/testcontainers-go/wait"
    "gorm.io/driver/postgres" // gorm postgres driver, aliased below
    "gorm.io/gorm"
)

// testDB is the package-wide connection pool, opened once in TestMain.
var testDB *gorm.DB

// TestMain starts a throwaway Postgres container, runs migrations, and opens a
// pool shared by every test in this package. Each test takes its own
// transaction (see newTx) so tests never see each other's writes.
func TestMain(m *testing.M) {
    code, err := runWithContainer(m)
    if err != nil {
        fmt.Fprintf(os.Stderr, "test infra: %v\n", err)
        os.Exit(1)
    }
    os.Exit(code)
}

func runWithContainer(m *testing.M) (int, error) {
    ctx := context.Background()

    container, err := postgres.Run(ctx,
        "postgres:16-alpine",
        postgres.WithDatabase("app_test"),
        postgres.WithUsername("test"),
        postgres.WithPassword("test"),
        testcontainers.WithWaitStrategy(wait.ForListeningPort("5432/tcp")),
    )
    if err != nil {
        return 1, fmt.Errorf("starting postgres container: %w", err)
    }
    defer func() { _ = container.Terminate(ctx) }()

    dsn, err := container.ConnectionString(ctx, "sslmode=disable")
    if err != nil {
        return 1, fmt.Errorf("resolving dsn: %w", err)
    }

    if err := migrate(dsn); err != nil {
        return 1, fmt.Errorf("running migrations: %w", err)
    }

    testDB, err = gorm.Open(gormpg.Open(dsn), &gorm.Config{})
    if err != nil {
        return 1, fmt.Errorf("opening gorm pool: %w", err)
    }

    return m.Run(), nil
}

// migrate applies the versioned goose migrations to the freshly started DB.
func migrate(dsn string) error {
    db, err := sql.Open("pgx", dsn)
    if err != nil {
        return fmt.Errorf("opening migration conn: %w", err)
    }
    defer db.Close()

    goose.SetBaseFS(nil) // migrations read from the on-disk dir below
    if err := goose.SetDialect("postgres"); err != nil {
        return fmt.Errorf("setting goose dialect: %w", err)
    }
    return goose.Up(db, "../../../db/migrations")
}

// newTx returns a transaction-scoped *gorm.DB and registers a rollback so the
// test's writes never leak into another test. This is the isolation boundary.
func newTx(t *testing.T) *gorm.DB {
    t.Helper()
    tx := testDB.Begin()
    if tx.Error != nil {
        t.Fatalf("beginning tx: %v", tx.Error)
    }
    t.Cleanup(func() { tx.Rollback() })
    return tx
}
```

Rules:

- **One container per package**, opened in `TestMain` — not per test. Container
  startup is seconds; a per-test container is a blocker for suite speed.
- **One transaction per test**, via `newTx(t)`, rolled back in `t.Cleanup`. Pass
  that `tx` everywhere the production code would pass the request-scoped `*gorm.DB`.
- **Never truncate tables** to isolate tests. Rollback does it for free and in
  parallel-safe fashion (see [§11](#11-parallel-tests-and-shared-container)).
- Run migrations **once**, in `TestMain`, before `m.Run()`.

---

## 4. Mocking external clients at the interface boundary

Domain services are **real** (that is the point — the test proves the orchestration
uses them correctly). External clients are **mocked at the interface the app
service depends on**. Follow the consumer-defines-the-interface rule from
[[go-conventions]]: the app-service package declares the *minimal*
interface it needs, and the test supplies a fake.

Two sanctioned techniques — pick one and be consistent within a package.

### 4a. testify/mock — when you assert call args and sequencing

```go
import "github.com/stretchr/testify/mock"

// paymentClient is the consumer-side interface the app service depends on.
// (Declared in the app-service package, not the client package.)
type paymentClient interface {
    Charge(ctx context.Context, params ChargeParams) (*Charge, error)
}

// mockPaymentClient is a testify mock implementing paymentClient.
type mockPaymentClient struct{ mock.Mock }

// Charge records the call and returns the programmed result.
func (m *mockPaymentClient) Charge(ctx context.Context, params ChargeParams) (*Charge, error) {
    args := m.Called(ctx, params)
    charge, _ := args.Get(0).(*Charge)
    return charge, args.Error(1)
}
```

### 4b. Hand-written fake — when you only need canned behaviour

Prefer a fake when the mock's call-arg matchers would be noisier than the behaviour
they verify. A fake that records what it was called with is often clearer:

```go
// fakePaymentClient is a hand-written test double. It records the last Charge
// call so the test can assert the side effect without testify matchers.
type fakePaymentClient struct {
    charged   []ChargeParams
    returnErr error
}

// Charge records the params and returns the configured result.
func (f *fakePaymentClient) Charge(ctx context.Context, params ChargeParams) (*Charge, error) {
    f.charged = append(f.charged, params)
    if f.returnErr != nil {
        return nil, f.returnErr
    }
    return &Charge{ID: "chg_test", Amount: params.Amount}, nil
}
```

**Never** mock a sibling domain service. Mocking domain services hides drift between
the app service and its collaborators and defeats the reason this test exists
(anti-pattern — see [§12](#12-anti-patterns)).

---

## 5. Building prerequisite state — call the real domain services

Build state by invoking the **real domain services** on the test transaction, the
same way the production code path would. This proves the orchestration reads state
the domain services actually wrote — hand-rolled `INSERT`s would let the test pass
while production breaks.

```go
// seedActiveCampaign builds a verified user, an account, and an active campaign
// through the real domain services, returning the wired-up fixtures.
func seedActiveCampaign(t *testing.T, tx *gorm.DB) fixtures {
    t.Helper()
    ctx := context.Background()

    userSvc := user.NewService(user.NewRepository(tx))
    u, err := userSvc.Create(ctx, user.CreateParams{
        Email:     "owner@core27.co",
        FirstName: "John",
        LastName:  "Doe",
    })
    require.NoError(t, err)

    campaignSvc := campaign.NewService(campaign.NewRepository(tx))
    c, err := campaignSvc.Create(ctx, campaign.CreateParams{
        AccountID: u.AccountID,
        Name:      "Summer Sale",
        IsActive:  true,
    })
    require.NoError(t, err)

    return fixtures{user: u, campaign: c}
}
```

---

## 6. A full app-service test

The service under test: `CreateCouponService` orchestrates the coupon-creation
workflow — guard checks, then persist the coupon, then charge the merchant's plan
via the external payment client, then enqueue a notification job. Real domain
services, real DB, **mocked payment client and mocked asynq queue**.

```go
package createcoupon

import (
    "context"
    "testing"

    "github.com/hibiken/asynq"
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/mock"
    "github.com/stretchr/testify/require"
)

// mockEnqueuer records enqueued asynq tasks so the test can assert the job
// side effect without a live Redis.
type mockEnqueuer struct{ mock.Mock }

func (m *mockEnqueuer) Enqueue(task *asynq.Task, opts ...asynq.Option) (*asynq.TaskInfo, error) {
    args := m.Called(task, opts)
    info, _ := args.Get(0).(*asynq.TaskInfo)
    return info, args.Error(1)
}

func TestService_Execute(t *testing.T) {
    t.Run("creates coupon, charges plan, and enqueues notification on the happy path", func(t *testing.T) {
        // ── Arrange: real DB tx + real domain state ──────────────────────
        tx := newTx(t)
        ctx := context.Background()
        fx := seedActiveCampaign(t, tx)

        // ── Arrange: mocked external clients at the interface boundary ────
        payment := &mockPaymentClient{}
        payment.On("Charge", mock.Anything, mock.MatchedBy(func(p ChargeParams) bool {
            return p.AccountID == fx.user.AccountID && p.Amount == 150
        })).Return(&Charge{ID: "chg_1", Amount: 150}, nil).Once()

        queue := &mockEnqueuer{}
        queue.On("Enqueue", mock.Anything, mock.Anything).
            Return(&asynq.TaskInfo{ID: "task_1"}, nil).Once()

        // ── Arrange: construct the service exactly as the handler would ───
        svc := NewService(
            couponRepo(tx),
            campaign.NewService(campaign.NewRepository(tx)),
            payment,
            queue,
        )

        // ── Act: one entry-method call — the unit under test ─────────────
        result, err := svc.Execute(ctx, CreateCouponParams{
            CampaignID:      fx.campaign.ID,
            AccountID:       fx.user.AccountID,
            Code:            "SUMMER_OFF_20",
            Description:     "Summer 20% off",
            RedemptionValue: 150,
            MaxUseCount:     20,
            IsActive:        true,
        })

        // ── Assert: returned outcome ─────────────────────────────────────
        require.NoError(t, err)
        require.NotNil(t, result)
        assert.NotEmpty(t, result.ID)
        assert.Equal(t, "SUMMER_OFF_20", result.Code)
        assert.Equal(t, 20, result.MaxUseCount)
        assert.True(t, result.IsActive)

        // ── Assert: persisted DB state (read back through the real repo) ──
        persisted, err := couponRepo(tx).FindByID(ctx, result.ID)
        require.NoError(t, err)
        assert.Equal(t, "SUMMER_OFF_20", persisted.Code)

        // ── Assert: side effects on the mocked clients ───────────────────
        payment.AssertExpectations(t) // charged once, with the matched args
        queue.AssertExpectations(t)   // notification enqueued exactly once
    })
}
```

### Block discipline

| Block | What goes in it | What MUST NOT go in it |
|---|---|---|
| Arrange — infra | `newTx(t)`, `ctx`, seed via real domain services | Hand-written `INSERT`s |
| Arrange — mocks | Build + program external-client mocks/fakes | Mocking a sibling *domain* service |
| Arrange — construct | One `NewService(...)` with production-shaped deps | Business logic; re-seeding |
| Act | One `svc.Execute(ctx, params)` call | Additional writes after the action begins |
| Assert | Returned result + DB read-back + mock `AssertExpectations` | Constructing fresh state mid-assert |

The sub-test name is the Go equivalent of the Python `WHEN/AND WHEN/It should`
docstring: it must state the preconditions and the expected outcome in plain
English. Keep it accurate when the test changes.

---

## 7. Asserting orchestration outcomes and side effects

Assert on **three surfaces**, because an app service's job is coordination:

1. **The returned value / error.** Go services return the result; assert it
   directly. (No Python-style "mutate `self` and return `self`" — that idiom does
   not exist here.)
2. **Persisted DB state**, read back through the **real repository**, not a raw
   query — this confirms the write landed and is readable the way production reads it.
3. **External side effects** — that the mocked client was called, once, with the
   right args (`AssertExpectations`, or inspect the fake's recorded calls).

For a paginated entry method, assert on the returned page struct:

```go
page, err := svc.ListCoupons(ctx, ListParams{Page: 0, Size: 30})
require.NoError(t, err)
assert.Len(t, page.Items, 2)
assert.Equal(t, 2, page.Total)
```

For multi-step flows (claim → redeem → refresh), assert each transition inline and
re-read persisted state between steps:

```go
redemption, err := svc.Claim(ctx, claimParams)
require.NoError(t, err)

redeemed, err := svc.Redeem(ctx, redemption.ID)
require.NoError(t, err)
assert.Equal(t, StateRedeemed, redeemed.State)

coupon, err := couponRepo(tx).FindByID(ctx, claimParams.CouponID)
require.NoError(t, err)
assert.Equal(t, 1, coupon.UsedCount)
```

---

## 8. One test per guard / `check*` step

An `Execute()` orchestrator built per [go-build-application-services](../go-build-application-services/SKILL.md) is a flat
sequence of private steps, any of which can return an error:

```go
// Execute orchestrates coupon creation across guards, persistence, and side effects.
func (s *Service) Execute(ctx context.Context, params CreateCouponParams) (*coupon.Coupon, error) {
    if err := s.checkCampaign(ctx, params); err != nil {
        return nil, err
    }
    if err := s.checkCampaignOwnership(ctx, params); err != nil {
        return nil, err
    }
    if err := s.checkCampaignActive(ctx, params); err != nil {
        return nil, err
    }
    if err := s.checkCouponLimit(ctx, params); err != nil {
        return nil, err
    }
    created, err := s.createCoupon(ctx, params)
    if err != nil {
        return nil, err
    }
    if err := s.chargePlan(ctx, params); err != nil {
        return nil, err
    }
    return created, s.enqueueNotification(ctx, created)
}
```

**Every `return nil, err` is a decision point and needs a dedicated sub-test.**
Assert the exact sentinel error with `errors.Is`, or the typed error with
`errors.As`:

| Branch | Sub-test | Expected error |
|---|---|---|
| happy path | `"creates coupon ... on the happy path"` | `nil` |
| `checkCampaignActive` fails | `"returns error when campaign is not active"` | `campaign.ErrNotActive` |
| `checkCampaignOwnership` fails | `"returns error when campaign is not owned by account"` | `campaign.ErrNotOwned` |
| `checkCouponLimit` fails | `"returns error when subscription coupon limit reached"` | `ErrCouponLimitReached` |
| `createCoupon` duplicate | `"returns error when coupon code is duplicate"` | `coupon.ErrDuplicateCode` |
| `chargePlan` client error | `"returns error and does not enqueue when charge fails"` | wrapped payment error |

```go
t.Run("returns error when campaign is not active", func(t *testing.T) {
    tx := newTx(t)
    fx := seedInactiveCampaign(t, tx)
    svc := NewService(couponRepo(tx), campaign.NewService(campaign.NewRepository(tx)),
        &mockPaymentClient{}, &mockEnqueuer{})

    _, err := svc.Execute(context.Background(), validParamsFor(fx))

    require.Error(t, err)
    assert.ErrorIs(t, err, campaign.ErrNotActive)
})
```

For typed errors that drive the HTTP response, use `errors.As` and assert the fields
the handler reads (the Go analog of the Python `code` / `http_error_code` asserts):

```go
var limitErr *CouponLimitError
require.ErrorAs(t, err, &limitErr)
assert.Equal(t, "error_coupon_limit_reached", limitErr.Code)
assert.Equal(t, http.StatusPreconditionFailed, limitErr.HTTPStatus)
```

---

## 9. Asserting the "no side effect on failure" contract

When a guard fails *before* the external call, prove the external client was
**never** invoked — a real orchestration bug is charging a card after a validation
failure. With testify, program nothing and call `AssertNotCalled`; with a fake,
assert its recorder is empty:

```go
payment := &mockPaymentClient{} // no .On(...) — any call fails the test

_, err := svc.Execute(ctx, validParamsFor(fx))

require.ErrorIs(t, err, campaign.ErrNotActive)
payment.AssertNotCalled(t, "Charge", mock.Anything, mock.Anything)
```

Symmetrically, when a *later* step fails (e.g. `chargePlan` errors), assert that the
notification job was **not** enqueued and — if the service is transactional — that
the coupon row did not persist:

```go
payment.On("Charge", mock.Anything, mock.Anything).
    Return(nil, errors.New("card declined")).Once()

_, err := svc.Execute(ctx, validParamsFor(fx))

require.Error(t, err)
queue.AssertNotCalled(t, "Enqueue", mock.Anything, mock.Anything)
```

---

## 10. Inducing failure conditions

Drive the system into the guard through the **same domain services**, not by
patching. To trigger the campaign-inactive guard, seed an inactive campaign (or
flip it via the real domain service) — the write lives inside the test transaction
and rolls back at the end:

```go
// Flip the campaign inactive through the real domain service, then re-run.
err := campaign.NewService(campaign.NewRepository(tx)).
    Deactivate(ctx, fx.campaign.ID)
require.NoError(t, err)
```

For ownership failures, build a **second** account and construct the service against
it while keeping the original campaign:

```go
other := seedAccount(t, tx, "Company2")
svc := NewService(couponRepo(tx),
    campaign.NewService(campaign.NewRepository(tx)),
    &mockPaymentClient{}, &mockEnqueuer{})

_, err := svc.Execute(ctx, CreateCouponParams{
    CampaignID: fx.campaign.ID, // belongs to the original account
    AccountID:  other.ID,       // different account → ownership guard fires
    Code:       "X", RedemptionValue: 1, MaxUseCount: 1,
})
require.ErrorIs(t, err, campaign.ErrNotOwned)
```

For limit failures, drive the system into the boundary through **repeated real
calls** to the service rather than seeding rows by hand — this proves both the limit
check and the loop-stable accounting:

```go
for i := 0; i < 14; i++ {
    _, err := svc.Execute(ctx, couponParams(fx, fmt.Sprintf("CODE_%d", i)))
    require.NoError(t, err)
}
_, err := svc.Execute(ctx, couponParams(fx, "OVER_LIMIT"))
require.ErrorIs(t, err, ErrCouponLimitReached)
```

---

## 11. Parallel tests and the shared container

Because isolation comes from a per-test transaction (not truncation), tests in the
package can run in parallel safely — each has its own tx on the shared pool:

- Call `t.Parallel()` in each sub-test that does not depend on ordering.
- **Do not** call `t.Parallel()` in a test that mutates shared, committed state
  outside its own transaction. If a test must commit (rare — see below), it cannot
  be parallel and must clean up after itself.
- Keep `TestMain`'s container alive for the whole package; never terminate it
  mid-suite.

The Go analog of the Python `flush()` vs `commit()` rule: prefer keeping every write
**inside the test transaction** so rollback cleans up. Only reach for a real commit
when reproducing a condition that genuinely depends on a committed parent row
(e.g. a `SELECT ... FOR UPDATE` in another connection); in that case the test is not
parallel and must delete what it committed in `t.Cleanup`.

---

## 12. Anti-patterns (do NOT do these)

- **Mocking sibling domain services.** App-service tests are integration tests
  against a real DB; the whole point is to verify the orchestration uses the *real*
  domain services correctly. Mocking them hides drift.
- **Hand-written `INSERT`s to seed state.** Seed through the real domain services
  so the test reflects what production writes and reads.
- **Going through Gin / HTTP.** Asserting binding, middleware, auth, or the response
  envelope is a handler test. This layer calls `Execute()` directly.
- **A container per test.** Start it once in `TestMain`.
- **Truncating tables to isolate.** Use a per-test transaction with rollback.
- **A single mock shared and reprogrammed across sub-tests.** Build a fresh mock per
  sub-test; stale `.On(...)` expectations cause false passes.
- **Asserting only the return value when the real work is a side effect.** Also
  assert DB read-back and `AssertExpectations` on external clients — and
  `AssertNotCalled` on the "no side effect on failure" paths.
- **Passing a `map[string]any` where the params struct belongs.** Construct the
  production param type so field names and validation match production.
- **Skipping the plain-English sub-test name.** It is the only place the full set of
  preconditions for a test is stated.

---

## 13. What every app-service test must cover

For each public entry method on the application service, write at minimum:

| Branch | Test |
|---|---|
| Happy path | Constructs valid params; asserts returned result **+** DB read-back **+** external side effects |
| Each `check*` / guard `return err` in the orchestrator | One sub-test per guard, asserting the exact error via `errors.Is` / `errors.As` (and typed-error fields the handler reads) |
| Each conditional branch inside the orchestrator | One sub-test per branch |
| "No side effect on failure" | For each pre-external guard, assert the external client is `AssertNotCalled`; for a failing later step, assert no downstream job/row |
| External client error | Assert the wrapped error propagates and no downstream side effect fires |
| Multi-step flows (claim → redeem → void) | One sub-test per terminal state |
| Limit / pagination methods | Drive state above and below the boundary; assert both sides |

---

## 14. Running the tests

```bash
# Single package (starts one container, runs all its tests):
go test ./internal/app/createcoupon/ -run TestService_Execute -v

# Whole app layer while iterating:
go test ./internal/app/... -v

# Full suite before opening a PR:
go test ./... -race
```

Run with `-race` before opening a PR — the shared container pool plus `t.Parallel()`
sub-tests make the race detector worth its cost.

---

## 15. Verification checklist

Before marking a Go application-service test complete:

- [ ] Test file is `internal/app/<feature>/service_test.go`, `package <feature>`
- [ ] Container starts **once** in `TestMain`; migrations run once, before `m.Run()`
- [ ] Each test uses `newTx(t)` with a `t.Cleanup` rollback — no truncation
- [ ] Prerequisite state is built through the **real domain services**, not raw SQL
- [ ] Sibling domain services are **real**; only **external clients** are mocked/faked
- [ ] External clients are mocked at the **consumer-defined interface** boundary
- [ ] A **fresh** mock/fake is built per sub-test
- [ ] Params use the **production param struct** with named fields — never a `map`
- [ ] The service is constructed exactly as the handler constructs it
- [ ] Action is a single `Execute()` (or one call per logical step in a flow)
- [ ] Assertions cover **returned result + DB read-back + external side effects**
- [ ] Guard failures assert the exact error via `errors.Is` / `errors.As`, plus
      typed-error fields the handler reads
- [ ] "No side effect on failure" paths assert `AssertNotCalled` on the client
- [ ] One sub-test per guard / `check*` step and per conditional branch
- [ ] Each sub-test name states its preconditions and expected outcome in prose
- [ ] Suite passes under `go test ./... -race`

---

## Cross-references

- [go-build-application-services](../go-build-application-services/SKILL.md) — the `Execute()` orchestrator + private step
  methods this skill tests.
- [go-build-clients](../go-build-clients/SKILL.md) — how external clients expose the interface mocked here.
- [go-test-domain-services](../go-test-domain-services/SKILL.md) — the layer below; real-DB tests for one domain
  service in isolation. App-service tests treat those as trusted collaborators.
- [go-conventions](../go-conventions/SKILL.md) — naming, godoc, declarative structure,
  consumer-defined interfaces, table-driven tests.
