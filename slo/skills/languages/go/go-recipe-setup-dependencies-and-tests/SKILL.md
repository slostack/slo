---
name: go-recipe-setup-dependencies-and-tests
description: "Go scoped recipe (GORM, testcontainers, asynq): Go equivalent of the pytest conftest/fixtures\
  \ test-infra model \u2014 TestMain for suite setup/teardown, testcontainers-go for Postgres/Redis, goose\
  \ migrations against the test DB, a shared test-DB helper with per-test transaction rollback (the fixture-isolation\
  \ analog), and GORM data factories under internal/testutil."
when_to_use: "Only for the named project stack and component. Use when standing up test infrastructure\
  \ for a Go service \u2014 spinning up ephemeral Postgres/Redis, migrating the test schema, isolating\
  \ tests from each other, or building reusable test data factories. Read before writing the first _test.go\
  \ that touches a database."
group: languages
kind: skill
---

# Go: Setup Dependencies and Tests

## Skill summary

- **Name:** `go-recipe-setup-dependencies-and-tests`
- **Description:** Go equivalent of the pytest `conftest.py`/fixtures model —
  `TestMain` for suite-level setup/teardown, `testcontainers-go` to spin up
  Postgres/Redis, `goose` migrations against the test DB, a shared test-DB helper
  with per-test transaction rollback (the fixture-isolation analog), and test data
  factories/builders for GORM models under `internal/testutil`.
- **When to use:** Use when standing up test infrastructure for a Go service, or
  before writing the first database-touching `_test.go`.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up test infrastructure for this Go service."
- "How do I spin up a Postgres container for my Go tests?"
- "My Go tests are polluting each other's database state — how do I isolate them?"
- "Write a TestMain that runs goose migrations against a test DB."
- "I need a factory to build User rows in my GORM tests."
- "What's the Go equivalent of conftest.py and the db_session fixture?"
- "How do I share one container across a whole test package?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill translates the Python `setup-dependencies-and-tests` prompt into Go. The
Python original mixed local-dev provisioning (a hand-rolled Postgres Dockerfile,
`init.sh`, `docker-compose.dev.yml`, `.env` files) with test wiring (`conftest.py`,
the `db_session` transactional-rollback fixture, a manually created test database).

In Go we collapse most of that manual provisioning into code. **`testcontainers-go`
replaces the Dockerfile + compose + `setup_test_db.sql` + manual `psql` dance** — the
test binary itself starts an ephemeral, correctly-configured Postgres, runs
migrations against it, and tears it down. There is no `conftest.py`; the equivalents
are `TestMain`, package-level helpers, and per-test transaction rollback.

The mapping, at a glance:

| Python / pytest | Go idiom |
|---|---|
| `conftest.py` (shared fixtures) | `internal/testutil` package + `TestMain` |
| `docker-compose.dev.yml` + Dockerfile + `init.sh` | `testcontainers-go` bootstrap helper |
| session-scoped `event_loop` fixture | `TestMain(m *testing.M)` |
| `db_session` fixture (BEGIN + SAVEPOINT + rollback) | `WithRollback(t, ...)` tx helper |
| Alembic `upgrade head` | `goose.Up` against the test DB (see `go-recipe-database-migrations`) |
| function-scoped fixtures | `t.Cleanup` + helpers taking `t *testing.T` |
| Pydantic factory objects in tests | GORM struct factories/builders |

Defer to `go-conventions` for all naming, godoc, declarative-structure,
and error-handling rules. This skill only covers the test-infrastructure layer.

Sibling skills, referenced throughout:
- `go-recipe-database-migrations` — how goose migrations are authored and run.
- `go-test-domain-services` — unit tests for the repository/service layer.
- `go-test-application-services` — transactional tests across domain services.
- `go-test-handlers` — end-to-end handler tests running the full request stack.

---

## Section 1 — Layout: where test infra lives

There is no top-level `tests/` directory in Go. Tests live in `_test.go` files
alongside the code they exercise. Shared test infrastructure — the analog of
`conftest.py` — lives in a dedicated internal package:

```
<service>/
├── internal/
│   ├── domain/
│   │   └── user/
│   │       ├── model.go
│   │       ├── repository.go
│   │       ├── service.go
│   │       └── service_test.go        # unit tests next to the code
│   └── testutil/                      # the conftest.py analog
│       ├── container.go               # testcontainers bootstrap (Postgres/Redis)
│       ├── db.go                      # shared *gorm.DB + WithRollback helper
│       ├── migrate.go                 # goose.Up against the test DB
│       └── factory/
│           ├── user.go                # GORM data factories/builders
│           └── account.go
├── migrations/                        # goose .sql files (see go-recipe-database-migrations)
└── go.mod
```

Rules:
- `internal/testutil` is imported **only** by `_test.go` files. It must not leak into
  production build paths. (It compiles into test binaries only because nothing in
  `cmd/` or non-test code imports it.)
- One factory file per domain entity, mirroring the domain package layout.
- The container + migration wiring is invoked from `TestMain`, never from individual
  test functions.

---

## Section 2 — `TestMain`: the suite-level setup/teardown

`TestMain` is the Go equivalent of a session-scoped pytest fixture. Go calls it once
per test binary (i.e., once per package) instead of running the tests directly. Use
it to: start the container, run migrations, expose a shared `*gorm.DB`, run the
tests, then tear everything down.

Put `TestMain` in the package whose tests need the database. A common pattern is one
per integration-style package; unit tests that mock the repository need no container
at all.

```go
// internal/domain/user/main_test.go
package user_test

import (
	"context"
	"log"
	"os"
	"testing"

	"github.com/example/service/internal/testutil"
)

// testDB is the shared, migrated database handle for this package's tests.
// It is set up once in TestMain and reused by every test via a per-test
// transaction that is always rolled back (see testutil.WithRollback).
var testDB *testutil.TestDatabase

// TestMain provisions an ephemeral Postgres container, runs goose migrations,
// executes the package's tests, and tears the container down.
//
// This is the Go analog of a session-scoped pytest fixture: setup and teardown
// happen exactly once per package, not once per test.
func TestMain(m *testing.M) {
	ctx := context.Background()

	db, err := testutil.SetupTestDatabase(ctx)
	if err != nil {
		log.Fatalf("setting up test database: %v", err)
	}
	testDB = db

	code := m.Run()

	// Teardown must run before os.Exit; os.Exit does not honour defer.
	if err := db.Teardown(ctx); err != nil {
		log.Printf("tearing down test database: %v", err)
	}

	os.Exit(code)
}
```

**Gotcha (the Go equivalent of the `event_loop` fixture pitfall):** `os.Exit` does
**not** run deferred functions. Never `defer db.Teardown()` in `TestMain` — call it
explicitly, capture `m.Run()`'s exit code in a variable, tear down, then `os.Exit`.

---

## Section 3 — Container bootstrap helper (`container.go`)

This replaces the Python original's Dockerfile, `init.sh`, `docker-compose.dev.yml`,
and the manual `setup_test_db.sql`/`psql` steps. `testcontainers-go` starts a real
Postgres in a container, waits for it to be healthy, and hands back a DSN.

```go
// internal/testutil/container.go
package testutil

import (
	"context"
	"fmt"
	"time"

	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

// pgContainer bundles a running Postgres container with its connection DSN.
type pgContainer struct {
	container *postgres.PostgresContainer
	dsn       string
}

// startPostgres launches an ephemeral Postgres 16 container and blocks until it
// is ready to accept connections.
//
// The image, credentials, and database name are fixed for tests — they are
// throwaway and never touch a real environment. Returns an error if the
// container fails to start or become healthy within the wait strategy timeout.
func startPostgres(ctx context.Context) (*pgContainer, error) {
	container, err := postgres.Run(
		ctx,
		"pgvector/pgvector:pg16",
		postgres.WithDatabase("app_test"),
		postgres.WithUsername("test"),
		postgres.WithPassword("test"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").
				WithOccurrence(2).
				WithStartupTimeout(60*time.Second),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("starting postgres container: %w", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		return nil, fmt.Errorf("resolving postgres dsn: %w", err)
	}

	return &pgContainer{container: container, dsn: dsn}, nil
}
```

Notes:
- The Python original used the `pgvector/pgvector:pg16` image so the `vector` and
  `uuid-ossp` extensions were available. Keep the same base image; create extensions
  in your **first goose migration** (`CREATE EXTENSION IF NOT EXISTS "vector";`)
  rather than in an `init.sh`. See `go-recipe-database-migrations`.
- The Python `init.sh` created a separate app user with scoped grants. Tests don't
  need that — the container superuser is fine for a throwaway DB, and it removes the
  "permission denied to create extension" class of errors the original called out.
- A **Redis** container follows the same shape when a test needs asynq/cache:

```go
// startRedis launches an ephemeral Redis 7 container for tests that exercise
// asynq queues or caching. Returns the host:port address of the container.
func startRedis(ctx context.Context) (testcontainers.Container, string, error) {
	req := testcontainers.ContainerRequest{
		Image:        "redis:7-alpine",
		ExposedPorts: []string{"6379/tcp"},
		WaitingFor:   wait.ForLog("Ready to accept connections"),
	}
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: req,
		Started:          true,
	})
	if err != nil {
		return nil, "", fmt.Errorf("starting redis container: %w", err)
	}

	endpoint, err := container.Endpoint(ctx, "")
	if err != nil {
		return nil, "", fmt.Errorf("resolving redis endpoint: %w", err)
	}
	return container, endpoint, nil
}
```

---

## Section 4 — The `TestDatabase` handle + migrations (`db.go`, `migrate.go`)

`SetupTestDatabase` ties the pieces together: start the container, open GORM against
the DSN, run goose migrations. This is what `TestMain` calls.

```go
// internal/testutil/db.go
package testutil

import (
	"context"
	"fmt"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// TestDatabase is the migrated, ready-to-use test database handle shared across
// a package's tests. Hold one per test package (created in TestMain).
type TestDatabase struct {
	DB        *gorm.DB
	container *pgContainer
}

// SetupTestDatabase starts an ephemeral Postgres, opens a GORM connection, and
// runs all goose migrations against it.
//
// The returned handle must be torn down with Teardown once the package's tests
// have finished. Returns an error if the container, connection, or migrations
// fail.
func SetupTestDatabase(ctx context.Context) (*TestDatabase, error) {
	pg, err := startPostgres(ctx)
	if err != nil {
		return nil, err
	}

	db, err := gorm.Open(postgres.Open(pg.dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent), // quiet SQL in test output
	})
	if err != nil {
		return nil, fmt.Errorf("opening gorm connection: %w", err)
	}

	if err := runMigrations(ctx, pg.dsn); err != nil {
		return nil, err
	}

	return &TestDatabase{DB: db, container: pg}, nil
}

// Teardown terminates the underlying container. Safe to call once, from TestMain.
func (t *TestDatabase) Teardown(ctx context.Context) error {
	if err := t.container.container.Terminate(ctx); err != nil {
		return fmt.Errorf("terminating postgres container: %w", err)
	}
	return nil
}
```

Migrations use goose against the container DSN. Author the migrations themselves per
`go-recipe-database-migrations`; here we only *apply* them:

```go
// internal/testutil/migrate.go
package testutil

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/pressly/goose/v3"
	_ "github.com/jackc/pgx/v5/stdlib" // pgx stdlib driver for database/sql
)

// migrationsDir is resolved relative to the repository root. Prefer embedding
// the migrations with //go:embed in production; a path is shown here for clarity.
const migrationsDir = "../../../migrations"

// runMigrations applies every pending goose migration to the database at dsn.
//
// It opens a short-lived database/sql connection (goose operates on *sql.DB, not
// *gorm.DB), migrates to the latest version, and closes the connection. Returns
// an error if any migration fails.
func runMigrations(ctx context.Context, dsn string) error {
	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		return fmt.Errorf("opening sql connection for migrations: %w", err)
	}
	defer sqlDB.Close()

	if err := goose.SetDialect("postgres"); err != nil {
		return fmt.Errorf("setting goose dialect: %w", err)
	}

	if err := goose.UpContext(ctx, sqlDB, migrationsDir); err != nil {
		return fmt.Errorf("running goose migrations: %w", err)
	}
	return nil
}
```

> Prefer `//go:embed migrations/*.sql` + `goose.SetBaseFS(embedFS)` over a relative
> path so tests are insensitive to the working directory. The path form is shown
> above only to keep the example self-contained. See `go-recipe-database-migrations`.

---

## Section 5 — Per-test transaction rollback (the fixture-isolation analog)

This is the heart of the Python original's `db_session` fixture: **each test runs
inside a transaction that is always rolled back**, so tests never see each other's
writes and the schema is migrated only once. In Go there is no fixture-injection
mechanism, so we express it as a helper that takes `*testing.T` and a callback.

GORM's `db.Transaction` + a forced rollback gives us the exact behaviour: the test
gets a `*gorm.DB` scoped to a transaction; whatever it writes is discarded when the
callback returns.

```go
// internal/testutil/db.go (continued)

import "errors"

// errRollback is returned by the callback to force GORM to roll back the
// enclosing transaction. It is never surfaced to the caller.
var errRollback = errors.New("testutil: forced rollback")

// WithRollback runs fn inside a database transaction that is always rolled back,
// giving each test a clean, isolated view of the database.
//
// This is the Go equivalent of the pytest db_session fixture: the schema is
// migrated once (in TestMain), but every test sees only its own uncommitted
// writes, which are discarded when fn returns. Nested SAVEPOINTs are handled by
// GORM automatically, so service code may call its own transactions inside fn.
//
// Any assertion failure inside fn is reported against t as usual.
func WithRollback(t *testing.T, db *gorm.DB, fn func(tx *gorm.DB)) {
	t.Helper()

	err := db.Transaction(func(tx *gorm.DB) error {
		fn(tx)
		return errRollback // force rollback regardless of fn's outcome
	})

	if err != nil && !errors.Is(err, errRollback) {
		t.Fatalf("transaction wrapper failed: %v", err)
	}
}
```

Why this matches the Python `db_session` semantics:
- **BEGIN before the test, ROLLBACK after** → `db.Transaction(...)` + returning
  `errRollback`.
- **A nested transaction so app code can `commit`** → GORM issues a `SAVEPOINT` when
  code calls `tx.Transaction(...)` on the already-open `tx`; the outer rollback
  unwinds everything. This is the direct analog of the `begin_nested()` /
  `after_transaction_end` savepoint re-arming in the Python fixture.
- **Session closed at end of test** → the transaction closure completes and GORM
  releases the connection.

**Usage in a domain-service test** (see `go-test-domain-services`):

```go
// internal/domain/user/service_test.go
package user_test

import (
	"context"
	"testing"

	"github.com/example/service/internal/domain/user"
	"github.com/example/service/internal/testutil"
	"github.com/example/service/internal/testutil/factory"
	"github.com/stretchr/testify/require"
)

func TestService_ActivateUser(t *testing.T) {
	testutil.WithRollback(t, testDB.DB, func(tx *gorm.DB) {
		ctx := context.Background()

		// Arrange: seed a pending user via the factory.
		existing := factory.NewUser(t, tx, factory.WithStatus(user.StatusPending))

		repo := user.NewPostgresRepository(tx)
		svc := user.NewService(repo)

		// Act.
		activated, err := svc.ActivateUser(ctx, existing.ID)

		// Assert: one decision point — the status transition.
		require.NoError(t, err)
		require.Equal(t, user.StatusActive, activated.Status)
	})
	// Nothing persists past this point — the tx is rolled back.
}
```

The repository is constructed with the transaction handle `tx`, not the raw
`testDB.DB`. That is the whole trick: everything the test and the code-under-test do
flows through the same rolled-back transaction.

---

## Section 6 — Test data factories/builders (`internal/testutil/factory`)

The Python original hand-built entities inline (`UserService.build_and_create(...)`).
In Go we centralise this into factories so tests stay declarative and share sane
defaults. A factory: builds a valid GORM model with defaults, applies functional
options for the fields a test cares about, persists it through the passed `tx`, and
fails the test on error.

Use the **functional-options pattern** (per `go-conventions`) so
call sites read as "a user, but pending" rather than positional soup.

```go
// internal/testutil/factory/user.go
package factory

import (
	"testing"
	"time"

	"github.com/example/service/internal/domain/user"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

// UserOption overrides a field on the User being built.
type UserOption func(*user.User)

// WithStatus sets the user's status. Defaults to user.StatusActive.
func WithStatus(status string) UserOption {
	return func(u *user.User) { u.Status = status }
}

// WithEmail sets the user's email. Defaults to a unique generated address.
func WithEmail(email string) UserOption {
	return func(u *user.User) { u.Email = email }
}

// WithQuestionLimit sets the question_limit column. Defaults to 50.
func WithQuestionLimit(limit int) UserOption {
	return func(u *user.User) { u.QuestionLimit = limit }
}

// NewUser builds a valid User with sensible defaults, applies any overrides,
// persists it through tx, and returns the created entity.
//
// The test fails immediately (t.Fatalf) if persistence fails, so callers can
// treat the returned *user.User as guaranteed non-nil. Field names match the
// domain model and DB columns exactly — no synonyms.
func NewUser(t *testing.T, tx *gorm.DB, opts ...UserOption) *user.User {
	t.Helper()

	u := &user.User{
		ID:            uuid.NewString(),
		Email:         uuid.NewString() + "@example.test", // unique by default
		Status:        user.StatusActive,
		QuestionLimit: 50,
		CreatedAt:     time.Now().UTC(),
	}
	for _, opt := range opts {
		opt(u)
	}

	if err := tx.Create(u).Error; err != nil {
		t.Fatalf("factory: creating user: %v", err)
	}
	return u
}
```

Factory rules:
- **Take `*testing.T` and `*gorm.DB`** — the factory persists through the same
  transaction the test uses, so rows vanish on rollback.
- **`t.Helper()`** so failures point at the test, not the factory.
- **Unique defaults** for anything with a unique constraint (email here) — otherwise
  two factory calls in one test collide.
- **Functional options**, one per field a test might override. Never a positional
  builder.
- **Ubiquitous language:** factory option names match the domain field and DB column
  (`WithQuestionLimit` → `QuestionLimit` → `question_limit`). No synonyms.
- A `Build*` variant that returns the struct **without** persisting is fine when a
  test needs an unsaved entity — name it `BuildUser` to distinguish from `NewUser`.

---

## Section 7 — Guarding cost: skip container tests when Docker is absent

`testcontainers-go` needs a Docker daemon. Keep pure unit tests (mocked repos, per
`go-test-domain-services`) runnable without Docker, and gate container-backed tests
so `go test ./...` degrades gracefully on machines/CI without Docker.

```go
// In TestMain, before starting the container:
if os.Getenv("SKIP_DB_TESTS") != "" {
	log.Println("SKIP_DB_TESTS set; skipping database-backed tests")
	os.Exit(0)
}
```

Alternatively use `testing.Short()` and run fast tests with `go test -short ./...`.
Document whichever gate you choose in the package doc comment so contributors know
the knob exists.

---

## Section 8 — Checklist

Run through this before declaring test infrastructure "done". Each unchecked item is
a blocker.

### Provisioning
- [ ] Postgres (and Redis, if needed) is started via **`testcontainers-go`**, not a
      hand-rolled Dockerfile/compose file.
- [ ] The container image matches production needs (e.g. `pgvector` for the `vector`
      extension); extensions are created in the **first goose migration**, not an
      `init.sh`.
- [ ] A wait strategy blocks until the DB is actually accepting connections.

### Suite lifecycle
- [ ] `TestMain` starts the container, runs migrations, calls `m.Run()`, tears down,
      then `os.Exit`.
- [ ] Teardown is called **explicitly** — never `defer`red in `TestMain` (`os.Exit`
      skips defers).
- [ ] Migrations run via **goose** against the container DSN (see
      `go-recipe-database-migrations`); prefer `//go:embed` over a relative path.

### Isolation
- [ ] Every DB-touching test runs inside `WithRollback` (or equivalent) — schema
      migrated once, writes discarded per test.
- [ ] Code-under-test receives the **transaction handle** (`tx`), not the raw shared
      `*gorm.DB`.
- [ ] No test depends on ordering or on state left by another test.

### Factories
- [ ] One factory file per domain entity under `internal/testutil/factory`.
- [ ] Factories take `*testing.T` + `*gorm.DB`, call `t.Helper()`, and `t.Fatalf`
      on persistence error.
- [ ] Functional options are used for overrides; unique constraints have unique
      defaults.
- [ ] Factory option/field names match the domain model and DB columns — no
      synonyms (per `go-conventions`).

### Boundaries
- [ ] `internal/testutil` is imported only by `_test.go` files.
- [ ] Container-backed tests are gated so `go test ./...` degrades gracefully
      without Docker.
- [ ] Unit-level tests (mocked repos) need **no** container — see
      `go-test-domain-services`.
