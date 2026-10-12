---
name: go-test-domain-services
description: "Go database-backed integration recipe (real domain collaborators; disposable PostgreSQL/GORM).\
  \ Not isolated orchestration: Go scoped recipe (GORM, testcontainers, asynq): How to write transactional\
  \ unit tests for Go domain services \u2014 the lowest persistence-aware layer \u2014 using stdlib testing\
  \ + testify + testcontainers-go against a real Postgres, table-driven cases, per-test transaction rollback\
  \ isolation, GORM fixtures/factories, and typed domain-error assertions via errors.Is."
when_to_use: Only for the named project stack and component. Use before writing or modifying a test for
  a Go domain service (the repository/service pair in internal/domain/<name>). These tests are the contract
  every layer above (application services, handlers, workers) depends on, so cover every decision path
  in the method under test.
group: languages
kind: skill
---

# Test Go Domain Services

## Skill summary

- **Name:** `go-test-domain-services`
- **Description:** Transactional unit tests for Go domain services — the lowest
  persistence-aware layer — using stdlib `testing` + `testify` +
  `testcontainers-go` against a real Postgres, table-driven cases, per-test
  transaction rollback isolation, GORM model fixtures/factories, and typed
  domain-error assertions via `errors.Is`.
- **When to use:** Before writing or modifying any domain-service test. Domain
  services are the contract everything above them depends on; cover every branch,
  guard, and returned error.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write a unit test for the coupon domain service's Create method."
- "How do I spin up Postgres for a domain-service test in Go?"
- "Add table-driven test cases for every branch of ActivateUser."
- "Test that CreateCoupon returns ErrDuplicateCode on a duplicate insert."
- "Set up per-test transaction rollback so my GORM tests don't leak rows."
- "Review this domain-service test — does it cover all the decision paths?"
- "Build a factory for a fully-wired account-with-coupon fixture."

---

## Guidance

**Test category:** database-backed integration. Keep real domain collaborators here; use go-test-orchestration recording fakes for isolated order/cutoff behavior. A skip because Docker is unavailable is unverified integration evidence, not a passing gate.

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill is the Go translation of the Python `test-domain-services` prompt.
The principles survive verbatim — one branch per test, real database not mocks,
assert on the persisted round-trip, typed error assertions — but the mechanics
are idiomatic Go: `testing` + `testify`, `testcontainers-go` for the real
Postgres, GORM for models, and `errors.Is` in place of `pytest.raises`.

Defer to **`go-conventions`** for naming, godoc, declarative structure,
and the domain-layer 3-file pattern. This skill only covers *testing* the domain
service. See **`go-build-domain-features`** for how the code under test is
structured, and **`go-recipe-setup-dependencies-and-tests`** for the shared container,
migrations, and `TestMain` bootstrap that these tests rely on.

---

## 1. What a domain-service test exercises

A domain-service test exercises a **single method** on the domain service against
the **real** PostgreSQL database (via testcontainers-go or a shared test DB). It:

1. Builds prerequisite rows (parent `Account`, `Campaign`, etc.) using sibling
   domain services or a factory.
2. Calls the method under test.
3. Asserts on the returned GORM model **and** the re-read row (round-trip).

It does **not** exercise:

- HTTP, middleware, or routing — that is a handler test (`go-test-handlers`).
- Multi-step orchestration across several services with shared state — that is an
  application-service test (`go-test-application-services`).
- External I/O (HTTP clients, Redis, NATS, asynq). Domain services must not depend
  on those; if they appear to, treat it as a bug in the code under test.

The Go analog of "the lowest persistence-aware layer" is the `Service` +
`Repository` pair in `internal/domain/<name>/`. The repository holds the
`*gorm.DB`; the service holds the business rules. Both are tested here.

---

## 2. File layout and naming

| Item | Convention |
|---|---|
| Test file location | `internal/domain/<domain>/service_test.go` (alongside the code it tests, same package or `<domain>_test`) |
| Top-level test func | `func TestCouponService_Create(t *testing.T)` — one top-level func per method under test |
| Sub-test names | `t.Run("succeeds with valid params", ...)` / `t.Run("returns ErrDuplicateCode on duplicate", ...)` — one sub-test per decision point |
| Granularity | One table case (or one `t.Run`) per branch, guard, and returned error — mirror `test-verification-policy` |

Use table-driven tests as the **default** for any method with more than one branch
(see `go-conventions`). Reserve a flat sequence of `t.Run` blocks
for cases whose *setup* differs so much a shared table row would be misleading.

---

## 3. Test harness — real Postgres, per-test rollback

There are two supported harnesses. Both give every test a **real** database and
**isolation**. Prefer the shared-container + tx-rollback harness for speed; use a
throwaway container per package when a test needs raw DDL or advisory locks.

### 3.1 Shared container + per-test transaction rollback (default)

`TestMain` starts one Postgres container for the whole package, runs goose
migrations once, and hands each test a `*gorm.DB` bound to a transaction that is
**always rolled back** when the test ends. Nothing leaks between tests. This is
the Go equivalent of the Python `async_db_session` savepoint fixture.

```go
// Package coupon domain-service tests. TestMain owns a single Postgres
// container for the whole package; each test runs inside a rolled-back tx.
package coupon_test

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"testing"
	"time"

	"github.com/pressly/goose/v3"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

// rootDB is the package-wide connection to the migrated test database.
// Individual tests never use it directly — they go through withTx.
var rootDB *gorm.DB

// TestMain starts one Postgres container, applies migrations, and shares the
// connection across every test in the package.
func TestMain(m *testing.M) {
	ctx := context.Background()

	container, err := tcpostgres.Run(ctx,
		"postgres:16-alpine",
		tcpostgres.WithDatabase("app_test"),
		tcpostgres.WithUsername("test"),
		tcpostgres.WithPassword("test"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").
				WithOccurrence(2).
				WithStartupTimeout(60*time.Second),
		),
	)
	if err != nil {
		log.Fatalf("starting postgres container: %v", err)
	}
	defer func() { _ = container.Terminate(ctx) }()

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		log.Fatalf("building dsn: %v", err)
	}

	if err := runMigrations(dsn); err != nil {
		log.Fatalf("running migrations: %v", err)
	}

	rootDB, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("opening gorm: %v", err)
	}

	os.Exit(m.Run())
}

// runMigrations applies the goose up migrations against the test database.
func runMigrations(dsn string) error {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return fmt.Errorf("opening sql db: %w", err)
	}
	defer db.Close()

	goose.SetBaseFS(nil)
	if err := goose.SetDialect("postgres"); err != nil {
		return fmt.Errorf("setting goose dialect: %w", err)
	}
	if err := goose.Up(db, "../../../db/migrations"); err != nil {
		return fmt.Errorf("goose up: %w", err)
	}
	return nil
}

// withTx runs fn inside a transaction that is ALWAYS rolled back, giving each
// test a clean, isolated database. Never commit inside fn — a commit escapes
// the rollback boundary and leaks rows into the shared container.
func withTx(t *testing.T, fn func(tx *gorm.DB)) {
	t.Helper()
	tx := rootDB.Begin()
	require.NoError(t, tx.Error, "begin tx")
	t.Cleanup(func() {
		// Rollback is unconditional; the tx is disposable test state.
		if err := tx.Rollback().Error; err != nil && err != sql.ErrTxDone {
			t.Errorf("rollback tx: %v", err)
		}
	})
	fn(tx)
}
```

> **Isolation rule (the Go analog of "never call `commit()`"):** inside a test,
> use `tx` for everything and never call `tx.Commit()`. GORM's `SavePoint` /
> `Rollback` on the shared tx is what keeps tests hermetic. A stray `Commit`
> releases the rollback boundary and leaks rows — the exact failure the Python
> prompt warns about, one-to-one.

### 3.2 Throwaway container per test (when you need real DDL / isolation of DDL)

When a test mutates schema, uses advisory locks, or must observe real commit
visibility across connections, give it its own container instead of a shared tx:

```go
// newIsolatedDB spins up a dedicated migrated Postgres for a single test.
// Slower than withTx; use only when transaction rollback isolation is
// insufficient (DDL, advisory locks, cross-connection visibility).
func newIsolatedDB(t *testing.T) *gorm.DB {
	t.Helper()
	ctx := context.Background()

	container, err := tcpostgres.Run(ctx, "postgres:16-alpine",
		tcpostgres.WithDatabase("app_test"),
		tcpostgres.WithUsername("test"),
		tcpostgres.WithPassword("test"),
		testcontainers.WithWaitStrategy(
			wait.ForListeningPort("5432/tcp").WithStartupTimeout(60*time.Second),
		),
	)
	require.NoError(t, err)
	t.Cleanup(func() { _ = container.Terminate(ctx) })

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	require.NoError(t, err)
	require.NoError(t, runMigrations(dsn))

	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	return db
}
```

Default to §3.1. Reach for §3.2 only when you can name why rollback isolation is
not enough.

---

## 4. Building prerequisite state — factories, not raw inserts

Domain entities have parents (a `Coupon` needs a `Campaign` → `Account` → `User`).
Build them **through sibling domain services** in FK order, so the test exercises
the same code path production uses. Never `tx.Create(&Coupon{...})` a parent
directly — that skips the service's defaults and validation.

```go
// buildUser, buildAccount, buildCampaign create prerequisite rows through the
// real domain services. Each returns the created entity or fails the test.
func buildCampaign(t *testing.T, tx *gorm.DB) *campaign.Campaign {
	t.Helper()

	usr, err := user.NewService(user.NewRepository(tx)).Create(context.Background(),
		user.CreateParams{
			FirstName: "siddharth",
			LastName:  "ravichandran",
			Email:     "sid@core27.co",
			Password:  "Abc123!!",
		})
	require.NoError(t, err)

	acct, err := account.NewService(account.NewRepository(tx)).Create(context.Background(),
		account.CreateParams{Name: "First_account", UserID: usr.ID})
	require.NoError(t, err)

	cmp, err := campaign.NewService(campaign.NewRepository(tx)).Create(context.Background(),
		campaign.CreateParams{
			Name:      "First Campaign",
			AccountID: acct.ID,
			StartDate: time.Now(),
			EndDate:   time.Now().Add(72 * time.Hour),
		})
	require.NoError(t, err)
	return cmp
}
```

For richly-wired state (account + campaign + coupon + keys), prefer a **factory**
that returns a bundle struct — the Go analog of `Factory.create_active_coupon`:

```go
// Fixture bundles a fully-wired active-coupon graph for tests that need the
// whole chain but don't care how it was built.
type Fixture struct {
	Account  *account.Account
	Campaign *campaign.Campaign
	Coupon   *coupon.Coupon
}

// createActiveCoupon builds an account → campaign → active coupon graph.
func createActiveCoupon(t *testing.T, tx *gorm.DB) Fixture {
	t.Helper()
	cmp := buildCampaign(t, tx)
	cpn, err := coupon.NewService(coupon.NewRepository(tx)).Create(context.Background(),
		coupon.CreateParams{
			Code:            "MYFIRST_COUPON",
			RedemptionType:  coupon.RedemptionTypeAbsoluteValue,
			RedemptionValue: decimal.NewFromInt(10),
			CampaignID:      cmp.ID,
			StartDate:       cmp.StartDate,
			EndDate:         cmp.EndDate,
		})
	require.NoError(t, err)
	return Fixture{Campaign: cmp, Coupon: cpn}
}
```

**Rule of thumb (unchanged from the source):** if a test needs more than two
parent rows, use the factory. If it tests a permutation the factory does not
produce (custom dates, custom redemption types), build inline through the
services.

---

## 5. Test structure — the canonical shape

Every domain-service test follows the same four blocks: **fixture → params →
action → assert**. Table-driven tests fold blocks 2–4 into the loop.

```go
// TestCouponService_Create covers each decision path in Service.Create:
// defaults application, JSON-column round-trip, and duplicate-code rejection.
func TestCouponService_Create(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(p *coupon.CreateParams) // tweak the base params per case
		wantErr error                        // sentinel expected via errors.Is; nil = success
		assert  func(t *testing.T, got *coupon.Coupon, tx *gorm.DB)
	}{
		{
			name:   "succeeds and applies defaults",
			mutate: func(p *coupon.CreateParams) {},
			assert: func(t *testing.T, got *coupon.Coupon, tx *gorm.DB) {
				// Block 4a: model identity + service-applied defaults
				require.NotZero(t, got.ID)
				require.Equal(t, "MYFIRST_COUPON", got.Code)
				require.True(t, got.IsActive)          // default applied by service
				require.Equal(t, 1, got.MaxUseCount)   // default applied by service
				require.Equal(t, 0, got.UsedCount)     // default applied by service
			},
		},
		{
			name: "persists constraints as a round-trippable JSON column",
			mutate: func(p *coupon.CreateParams) {
				p.MinimumOrderValue = decimal.RequireFromString("2200.00")
				p.MerchantID = "Zomato"
				p.CustomerIDs = []string{"customer_12345", "customer_22123"}
			},
			assert: func(t *testing.T, got *coupon.Coupon, tx *gorm.DB) {
				// Block 4b: re-READ the row so we prove it serialized AND
				// deserialized correctly — the Go analog of the DAO round-trip.
				var reread coupon.Coupon
				require.NoError(t, tx.First(&reread, "id = ?", got.ID).Error)

				require.Equal(t, decimal.RequireFromString("2200.00"),
					reread.Constraints.MinimumOrder.Value)
				require.Equal(t, "Zomato", reread.Constraints.Merchant.MerchantID)
				require.Equal(t, []string{"customer_12345", "customer_22123"},
					reread.Constraints.Customer.CustomerIDs)
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			withTx(t, func(tx *gorm.DB) {
				// ── Block 1: fixture (parents built via sibling services) ──
				cmp := buildCampaign(t, tx)

				// ── Block 2: params ──────────────────────────────────────
				params := coupon.CreateParams{
					Code:            "MYFIRST_COUPON",
					RedemptionType:  coupon.RedemptionTypeAbsoluteValue,
					RedemptionValue: decimal.NewFromInt(10),
					CampaignID:      cmp.ID,
					StartDate:       cmp.StartDate,
					EndDate:         cmp.EndDate,
				}
				tc.mutate(&params)

				// ── Block 3: the single call under test ──────────────────
				svc := coupon.NewService(coupon.NewRepository(tx))
				got, err := svc.Create(context.Background(), params)

				// ── Block 4: assert ──────────────────────────────────────
				if tc.wantErr != nil {
					require.ErrorIs(t, err, tc.wantErr)
					return
				}
				require.NoError(t, err)
				tc.assert(t, got, tx)
			})
		})
	}
}
```

### Block discipline

| Block | What goes in it | What MUST NOT go in it |
|---|---|---|
| 1. Fixture | Parent rows via sibling services / factory, time-window construction | The method under test |
| 2. Params | The `CreateParams` (or arguments) for the call | Any DB mutation |
| 3. Action | A **single** `svc.<Method>(ctx, ...)` call (the unit under test) | Any other domain mutation — that belongs in the fixture |
| 4. Assert | Model identity, defaults, re-read round-trip, `errors.Is` on the returned error | Additional inserts/updates once assertions begin |

---

## 6. Assertion patterns — three surfaces

Assert against three distinct surfaces of the result, exactly as the Python prompt
does (identity, defaults, round-trip):

### 6.1 Model identity and required fields

```go
require.NotZero(t, got.ID)
require.Equal(t, "MYFIRST_COUPON", got.Code)
require.Equal(t, cmp.ID, got.CampaignID)
```

### 6.2 Defaults — prove the service applied them

The service, not the caller, owns defaults. Assert the omitted fields came back
with the right values:

```go
require.True(t, got.IsActive)        // service default
require.Equal(t, 1, got.MaxUseCount) // service default
require.Equal(t, 0, got.UsedCount)   // service default
```

### 6.3 Re-read round-trip — the Go analog of the DAO round-trip

The Python prompt round-trips through a Pydantic DAO to prove the JSON column
serializes and re-parses. In Go, **re-read the row from the database** with a
fresh query and assert the deserialized structure. This catches the same failure
class: a service that stores the right shape but with a key GORM cannot scan back.

```go
var reread coupon.Coupon
require.NoError(t, tx.First(&reread, "id = ?", got.ID).Error)

require.Equal(t,
	[]decimal.Decimal{decimal.NewFromInt(100), decimal.NewFromInt(50), decimal.NewFromInt(30)},
	reread.Constraints.StaggeredRedemption.SplitInPercent,
)
```

For any GORM model field backed by a JSON/JSONB column or a custom
`Scanner`/`Valuer`, the re-read assertion is **mandatory**, not optional.

---

## 7. Testing error paths — typed errors and `errors.Is`

The Go equivalent of `pytest.raises(ExactClass)` is `require.ErrorIs` against a
package-level **sentinel error** (see `go-conventions`). Assert on
the sentinel the service documents, never on a substring of the message.

```go
{
	name: "returns ErrDuplicateCode on duplicate code in same campaign",
	// First insert happens in the fixture; the case re-inserts the same code.
	setup: func(t *testing.T, tx *gorm.DB, p coupon.CreateParams) {
		svc := coupon.NewService(coupon.NewRepository(tx))
		_, err := svc.Create(context.Background(), p)
		require.NoError(t, err)
	},
	wantErr: coupon.ErrDuplicateCode, // asserted via errors.Is in the loop
},
```

For a **typed** domain error that carries API-facing metadata (the Go analog of
`excinfo.value.code` / `http_error_code`), assert with `errors.As` and check the
fields the handler layer relies on:

```go
_, err := svc.IncrementUsedCount(ctx, cpn.ID)

var maxErr *coupon.ExceededMaxUsageCountError
require.ErrorAs(t, err, &maxErr)
require.Equal(t, "error_coupon_exceeded_max_usage_count", maxErr.Code)
require.Equal(t, http.StatusPreconditionFailed, maxErr.HTTPStatus) // 412
```

Where the failure originates in the driver (a real unique-constraint violation),
the repository should translate it to the domain sentinel before returning — and
the test asserts on the **domain** sentinel, never on `pgconn.PgError` codes. If
you find yourself matching `"23505"` in a service test, the translation belongs in
the repository, not the assertion.

---

## 8. Testing list / query methods

For `ListBy*`, `GetBy*`, and `CountBy*` methods, build **more than the minimum**
state so the filter has something to exclude. Write one case that proves a
matching row is **included** and a sibling case that proves a non-matching row is
**excluded** — one decision point each.

```go
func TestCouponService_ListByCampaignID(t *testing.T) {
	withTx(t, func(tx *gorm.DB) {
		fix := createActiveCoupon(t, tx)
		svc := coupon.NewService(coupon.NewRepository(tx))

		// Second coupon in the SAME campaign → must be included.
		_, err := svc.Create(context.Background(), coupon.CreateParams{
			Code:            "MYSECOND_COUPON",
			RedemptionType:  coupon.RedemptionTypeAbsoluteValue,
			RedemptionValue: decimal.NewFromInt(10),
			CampaignID:      fix.Campaign.ID,
			StartDate:       fix.Campaign.StartDate,
			EndDate:         fix.Campaign.EndDate,
		})
		require.NoError(t, err)

		// A coupon in a DIFFERENT campaign → must be excluded.
		other := buildCampaign(t, tx)
		_, err = svc.Create(context.Background(), coupon.CreateParams{
			Code:            "OTHER_COUPON",
			RedemptionType:  coupon.RedemptionTypeAbsoluteValue,
			RedemptionValue: decimal.NewFromInt(10),
			CampaignID:      other.ID,
			StartDate:       other.StartDate,
			EndDate:         other.EndDate,
		})
		require.NoError(t, err)

		got, err := svc.ListByCampaignID(context.Background(), fix.Campaign.ID)
		require.NoError(t, err)
		require.Len(t, got, 2) // the two in fix.Campaign, not the third
	})
}
```

When a query has multiple filters (state, customer ID, date window), write one
include/exclude pair per filter clause.

---

## 9. Commit visibility, flush, and refresh

The Python prompt uses `flush()` + `refresh()` and forbids `commit()`. The Go
equivalents on the rolled-back `tx`:

- **Re-read** with a fresh `tx.First(&reread, ...)` to see the persisted state
  through a clean identity — this is the round-trip assertion of §6.3 and the
  analog of `refresh()`.
- GORM writes are visible to subsequent reads on the **same** `tx` without any
  flush step, so no explicit flush is usually needed.
- **Never** call `tx.Commit()` in a test (§3.1). If a test genuinely needs
  cross-connection commit visibility, it needs an isolated container (§3.2), not a
  commit on the shared tx.

---

## 10. What every domain-service test must cover

For each public method on the domain service, write at minimum:

| Branch | Test case |
|---|---|
| Happy path | Valid args → assert persisted state and defaults |
| Each defaulted field | Omit it → prove the service applied the default |
| Each guard / returned error | One case per `return ..., Err*` path, asserted with `errors.Is` (or `errors.As` for typed errors, checking `Code`/`HTTPStatus`) |
| Each filter clause in a list/query | An include case and an exclude case |
| Each conditional branch (`if x == nil`, `if customerID != ""`) | One case per branch — see `test-verification-policy` |
| Any JSON/JSONB or custom-scanner column | Re-read round-trip asserting the parsed structure |

---

## 11. Running the tests

```bash
# testcontainers-go needs a reachable Docker daemon.
go test ./internal/domain/coupon/ -run TestCouponService_Create -v

# Run one sub-test:
go test ./internal/domain/coupon/ \
  -run 'TestCouponService_Create/persists_constraints' -v

# Whole domain package while iterating; race detector before a PR:
go test ./internal/domain/coupon/... -race
```

Container startup dominates the first run; the shared-container harness (§3.1)
amortizes it across the whole package.

---

## 12. Anti-patterns (do NOT do these)

- **Mocking the database.** Domain-service tests are integration tests against
  real Postgres. If you are mocking the `Repository` here, you are writing a test
  that proves nothing — mocks belong in application-service tests where an
  *external* dependency is replaced.
- **Calling `tx.Commit()` in a test** — releases the rollback boundary and leaks
  rows into the shared container. Re-read with a fresh query instead.
- **Building parent rows with raw `tx.Create(&Model{...})`** — bypasses the
  service's defaults and validation. Always go through the sibling
  `Service.Create(...)` or a factory.
- **Asserting only the returned struct and skipping the re-read** for JSON /
  custom-scanner columns — hides serialization bugs (§6.3).
- **Matching driver error codes (`"23505"`, `pgconn.PgError`) in the assertion** —
  the repository should translate to a domain sentinel; assert on the sentinel.
- **`require.ErrorContains(t, err, "duplicate")`** for a known failure — brittle;
  use `errors.Is` against the sentinel.
- **One test case covering three branches** — one branch, one case, one assertion
  cluster (see `test-verification-policy`).
- **A bare `require.NoError` + `require.NotNil`** with no behavioural assertion —
  proves the function ran, not that it is correct (see `go-conventions`
  §1.5).

---

## 13. Verification checklist

Before marking a domain-service test complete:

- [ ] File lives at `internal/domain/<domain>/service_test.go`.
- [ ] Top-level func is `func Test<Entity>Service_<Method>(t *testing.T)`.
- [ ] Multi-branch methods use a **table-driven** test; each row is one decision.
- [ ] Each test runs inside `withTx` (rolled back) or an isolated container.
- [ ] No `tx.Commit()` anywhere in the test.
- [ ] Parent rows are created via sibling `Service.Create(...)` or a factory —
      never raw `tx.Create` of a parent.
- [ ] Exactly **one** call to the method under test per case.
- [ ] Assertions cover model identity, service-applied defaults, and the re-read
      round-trip where a JSON/custom-scanner column is involved.
- [ ] Error paths use `require.ErrorIs` on a sentinel, or `require.ErrorAs` +
      `Code`/`HTTPStatus` checks for typed domain errors.
- [ ] List/query methods have an **include** case and an **exclude** case per
      filter clause.
- [ ] One case per decision point in the method under test.
- [ ] `go test ./... -race` passes.

---

### Cross-references

- `go-conventions` — naming, godoc, declarative structure, table-driven
  test discipline, sentinel errors. Non-negotiable baseline.
- `go-build-domain-features` — how the `model.go` / `dto.go` / `repository.go` /
  `service.go` under test is structured.
- `go-recipe-setup-dependencies-and-tests` — the shared testcontainers-go bootstrap,
  goose migration wiring, and `TestMain` conventions these tests depend on.
- `go-test-application-services` — the next layer up (orchestration across
  services; where selective mocking is permitted).
- `go-test-handlers` — full-stack handler tests with `httptest`.
