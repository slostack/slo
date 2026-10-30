---
name: go-test-handlers
description: 'Go database-backed integration recipe (real domain collaborators; disposable PostgreSQL/GORM;
  Gin HTTP boundary). Not isolated orchestration: Go scoped recipe (GORM, testcontainers, Gin): End-to-end
  Go handler/controller tests that boot the full Gin router (middleware + handler + service + DAO) against
  a real Postgres via testcontainers-go, drive it with net/http/httptest, and assert status codes, the
  uniform response envelope, DB state, and auth-required routes.'
when_to_use: Only for the named project stack and component. Use when writing or reviewing end-to-end
  tests for a Gin HTTP handler that must exercise the whole request stack (real DB + real middleware +
  auth) rather than a single service method in isolation.
group: languages
kind: skill
---

# Test Go Handlers (Controllers / Gin Routes)

## Skill summary

- **Name:** `go-test-handlers`
- **Description:** End-to-end Go handler tests that boot the full Gin router
  (middleware + handler + service + DAO) against a real Postgres via
  testcontainers-go, drive it over `net/http/httptest`, and assert status codes,
  the uniform response envelope, DB state, and auth on protected routes.
- **When to use:** Use when a test must exercise the whole request stack for a
  route — binding/validation, middleware, auth, the service, the DAO, and the real
  DB — not a single service method in isolation.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write an end-to-end test for the create-user Gin handler."
- "Add a controller test that hits the real DB and asserts the response envelope."
- "Test that this route returns 401 when the auth token is missing."
- "Cover the validation-error branch of the coupons handler with an httptest test."
- "Set up testcontainers-go Postgres for our handler tests."
- "Assert the DB row was actually written after the POST handler runs."
- "How do I test a Gin route with middleware and auth end to end?"

---

## Guidance

**Test category:** database-backed integration. Keep real domain collaborators here; use go-test-orchestration recording fakes for isolated order/cutoff behavior. A skip because Docker is unavailable is unverified integration evidence, not a passing gate.

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. This recipe covers Go mechanics only.

- This recipe is level 1 (journey: HTTP → handler → application service → domain service → database) in the policy's test levels.
- Doubles: real database or store; mocks (testify/mock or `httptest`) only for third-party API clients; hand-written stubs for internal collaborators, passed in through constructors or struct fields.
- Coverage: follow the policy's "What Must Be Tested". Do not restate it here.

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This is the Go equivalent of the Python `test-controllers` prompt (FastAPI router
tests over `httpx.AsyncClient` with a rollback-isolated session). The principles
survive verbatim; only the mechanics change:

| Python / FastAPI | Go / Gin |
|---|---|
| `httpx.AsyncClient(app=api)` (in-process ASGI) | `httptest.NewRecorder()` + `router.ServeHTTP` (in-process, no port) |
| savepoint-rolled-back `AsyncSession` | testcontainers-go Postgres, per-test transaction rollback **or** table truncation |
| `get_test_app()` middleware swap | build the **real** router via a shared `newTestRouter(...)` helper |
| `X-ACCESS-KEY-ID` factory header | `Authorization: Bearer <token>` set by your auth middleware |
| Pydantic request DAO | Gin `ShouldBindJSON` + `go-playground/validator` struct tags |
| `success_response()` / `failure_response()` envelope | `SuccessResponse[T]` / `FailureResponse` envelope |

Defer to `go-conventions` for naming, godoc, declarative structure, and
the envelope type definitions. Cross-reference `go-build-http-handlers` (handler
shape + route registration), `go-build-middleware` (auth/request-context
middleware), and `go-recipe-api-response-conventions` (the `SuccessResponse`/
`FailureResponse` envelope). This skill is the *test* counterpart to all three.

> Read this file in full **before** writing a handler test. The setup
> (container boot, real router build, per-test isolation, auth token minting) has
> several steps; skipping one silently breaks isolation or lets a leaked row make
> an assertion pass for the wrong reason.

---

### 1. What a handler test exercises

A handler test drives the **full request stack** for one route:

1. The Gin engine and its route table (path + method + prefix, e.g. `/ac/api/v1/users`).
2. Every middleware in the chain — request context, auth, recovery, logging.
   Nothing is swapped out; the test runs the production middleware.
3. The handler (bind + validate), the application service it calls, and the DAO.
4. The **real** database — every `INSERT`, `UPDATE`, query, and constraint runs
   against a Postgres started by testcontainers-go.

It does **not** exercise:

- A real network socket. `httptest.NewRecorder()` + `router.ServeHTTP(rec, req)`
  runs the whole stack in-process; no port is opened, so tests are fast and
  parallel-safe within a package.
- Mocked services. If you find yourself stubbing the service layer, you want a
  **service test** (see `go-test-domain-services` or `go-test-application-services`), not a handler test.

If your test only checks handler → service plumbing and doesn't care about auth,
middleware, or the JSON envelope, write a service-level test instead.

---

### 2. File layout and naming

| Item | Convention |
|---|---|
| Test file | `internal/handler/<group>/handler_test.go`, alongside the handler |
| Test function | `TestUserHandler_CreateUser` — `Test<Type>_<Method>` |
| Sub-tests | `t.Run("returns 401 when token is missing", ...)` — one decision point per sub-test, phrased as behaviour |
| Shared setup | `internal/handler/<group>/main_test.go` (or a `testsupport` package) for `TestMain`, the container, and `newTestRouter` |
| Package | Prefer the **external** test package `package <group>_test` so tests consume the exported surface exactly as a caller would |

Defer to `go-conventions` for table-driven structure and the
"one decision per test" rule.

---

### 3. Booting the real database once with testcontainers-go

Start **one** Postgres container per test binary in `TestMain`, run migrations
against it, and share the `*gorm.DB` handle. Booting a container per test is far
too slow.

```go
// internal/handler/users/main_test.go
package users_test

import (
	"context"
	"fmt"
	"log"
	"os"
	"testing"
	"time"

	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
	"gorm.io/driver/postgres" // gorm postgres driver
	gormpg "gorm.io/driver/postgres"
	"gorm.io/gorm"
)

// testDB is the shared GORM handle backed by the testcontainers Postgres.
// It is initialised once in TestMain and reused across every test in the package.
var testDB *gorm.DB

// TestMain boots a Postgres container, applies goose migrations, and exposes a
// shared *gorm.DB for the package's handler tests.
func TestMain(m *testing.M) {
	ctx := context.Background()

	container, err := postgres.Run(ctx,
		"postgres:16-alpine",
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
		log.Fatalf("starting postgres container: %v", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		log.Fatalf("building dsn: %v", err)
	}

	testDB, err = gorm.Open(gormpg.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("opening gorm: %v", err)
	}

	if err := runMigrations(dsn); err != nil {
		log.Fatalf("running migrations: %v", err)
	}

	code := m.Run()

	// Best-effort teardown; the test process is exiting anyway.
	_ = container.Terminate(ctx)
	os.Exit(code)
}

// runMigrations applies the versioned goose migrations to the test database.
func runMigrations(dsn string) error {
	db, err := goose.OpenDBWithDriver("pgx", dsn)
	if err != nil {
		return fmt.Errorf("opening db for goose: %w", err)
	}
	defer db.Close()
	return goose.Up(db, "../../../db/migrations")
}
```

**Rule:** migrations run against the container — never `AutoMigrate` in tests. The
schema under test must be the schema goose ships to production (mirrors the Python
prompt's "the real database — every constraint actually runs").

---

### 4. Per-test isolation

Two acceptable strategies. Pick one per package and stick to it.

**Preferred — truncate between tests** (simple, works with Gin's own connection
handling, no session-swap gymnastics):

```go
// resetTables truncates all mutable tables so each test starts from a clean slate.
// RESTART IDENTITY resets sequences; CASCADE handles FK-linked rows.
func resetTables(t *testing.T) {
	t.Helper()
	err := testDB.Exec(
		`TRUNCATE TABLE users, access_tokens RESTART IDENTITY CASCADE`,
	).Error
	require.NoError(t, err)
}
```

Call `resetTables(t)` at the top of each test (or via `t.Cleanup`). Because
truncation mutates shared state, tests in a package that truncate **must not** run
in parallel with each other — do not call `t.Parallel()` in truncating tests.

**Alternative — transaction rollback** (closer to the Python savepoint fixture):
open a `tx := testDB.Begin()`, inject it as the request-scoped DB, and
`tx.Rollback()` in cleanup. This is the direct analog of the FastAPI middleware
swap, but requires your app to read its `*gorm.DB` from the request context so the
test can substitute the transaction. Only reach for it if your middleware already
supports a per-request DB handle.

> **Do NOT** `Commit()` merely to "make the handler see the data" — the handler
> runs in-process against the *same* `testDB`, so a plain write is already visible.
> A stray commit defeats a rollback-based isolation strategy.

---

### 5. Building the real router

Build the router through the **same** constructor production uses. Never assemble a
bare `gin.New()` with only the handler under test — you would skip the middleware
the test exists to exercise. Set `gin.TestMode` to silence debug logging.

```go
// newTestRouter wires the full production router against the shared test DB and
// a token minter, returning the engine plus a helper to mint valid auth tokens.
func newTestRouter(t *testing.T) (*gin.Engine, *auth.TokenMinter) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	minter := auth.NewTokenMinter(auth.Config{Secret: "test-secret"})

	// Real dependency graph — same wiring as cmd/server/main.go.
	userRepo := user.NewGormRepository(testDB)
	deps := server.Deps{
		DB:        testDB,
		UserRepo:  userRepo,
		Auth:      auth.NewMiddleware(minter),
	}

	router := server.NewRouter(deps) // the production router builder
	return router, minter
}
```

**Rule:** if `NewRouter` doesn't yet accept its dependencies as parameters,
refactor it so it does (see `go-build-http-handlers` on constructor injection).
A router you cannot build with a test DB is a router you cannot test end to end.

---

### 6. Driving the request with httptest

Use `httptest.NewRequest` + `httptest.NewRecorder` and hand both to
`router.ServeHTTP`. Call the **full** path including the service namespace prefix
(e.g. `/ac/api/v1/...`, per `go-conventions`).

```go
func doJSON(t *testing.T, router *gin.Engine, method, path, token string, body any) *httptest.ResponseRecorder {
	t.Helper()

	var reader io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		require.NoError(t, err)
		reader = bytes.NewReader(buf)
	}

	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}
```

#### Authentication

Protected routes require a real, middleware-verifiable credential. Mint it with
the same minter the router was built with — never a hand-crafted string:

```go
token, err := minter.Mint(auth.Claims{AccountID: account.ID})
require.NoError(t, err)
```

To assert an auth failure, omit the header or pass a bogus token and expect `401`
with `errors.code == "ERROR_UNAUTHORIZED"` (see §8). This is the direct analog of
the Python prompt's bogus `X-ACCESS-KEY-ID` case.

#### Request bodies

Bind against the **exact** request DTO the handler declares so you test the
handler's validator, not a hand-rolled map that happens to match:

```go
body := user.CreateUserRequest{
	Email:         "alice@example.com",
	QuestionLimit: 50,
}
rec := doJSON(t, router, http.MethodPost, "/ac/api/v1/users", token, body)
```

---

### 7. Seeding domain state

Build prerequisite rows through the **repository/service**, not raw SQL or GORM
`.Create` on ad-hoc structs — the same "use factories, not `.add()`" rule from the
Python prompt. This keeps the test speaking the domain's ubiquitous language and
exercises the same write path production uses.

```go
account, err := userRepo.Create(ctx, user.CreateUserParams{
	Email:         "seed@example.com",
	QuestionLimit: 10,
})
require.NoError(t, err)
```

---

### 8. Asserting the response envelope

Every response follows the envelope from `go-recipe-api-response-conventions`:

```json
{
  "data":  { ... },
  "api_version": "v1.0",
  "errors": { "msg": [], "code": null }
}
```

Assert in this order — status first (the client contract), then `errors.code` on
failures (the machine-readable code, not the human message), then the specific
`data` fields that prove behaviour. Never assert the whole body against a giant
literal — generated IDs, timestamps, and ordering will make it brittle.

```go
// Decode into the generic envelope so field access is typed.
func decodeSuccess[T any](t *testing.T, rec *httptest.ResponseRecorder) response.SuccessResponse[T] {
	t.Helper()
	var env response.SuccessResponse[T]
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &env))
	return env
}

// Success path
require.Equal(t, http.StatusCreated, rec.Code)
env := decodeSuccess[user.UserResponse](t, rec)
assert.Equal(t, "alice@example.com", env.Data.Email)
assert.Equal(t, 50, env.Data.QuestionLimit)
assert.Nil(t, env.Errors.Code)

// Failure path
require.Equal(t, http.StatusBadRequest, rec.Code)
var fail response.FailureResponse
require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &fail))
require.NotNil(t, fail.Errors.Code)
assert.Equal(t, "ERROR_VALIDATION", *fail.Errors.Code)
```

> **Skipping the `errors.code` assertion on failure paths is a red flag.**
> `errors.code` is the API contract; the human-readable `msg` is not.

---

### 9. Asserting database state after a mutating route

For any POST/PUT/DELETE, prove the write actually landed by re-reading the row
through the repository (or a direct query on `testDB`) *after* the request. The
handler and the test share `testDB`, so the write is immediately visible.

```go
rec := doJSON(t, router, http.MethodPost, "/ac/api/v1/users", token, body)
require.Equal(t, http.StatusCreated, rec.Code)

var persisted user.User
err := testDB.Where("email = ?", "alice@example.com").First(&persisted).Error
require.NoError(t, err)
assert.Equal(t, 50, persisted.QuestionLimit)
assert.Equal(t, user.StatusActive, persisted.Status)

// Prove no duplicate was created.
var count int64
testDB.Model(&user.User{}).Where("email = ?", "alice@example.com").Count(&count)
assert.EqualValues(t, 1, count)
```

---

### 10. A full worked example

One test function, three cases: success, validation error, unauthorized — the
minimum coverage the Python prompt's §10 table requires for a mutating route.

```go
package users_test

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/app/internal/domain/user"
	"example.com/app/internal/response"
)

// TestUserHandler_CreateUser exercises the create-user route end to end against a
// real Postgres: the happy path, the validation-error branch, and the auth guard.
func TestUserHandler_CreateUser(t *testing.T) {
	router, minter := newTestRouter(t)

	t.Run("creates the user and returns 201 with the envelope", func(t *testing.T) {
		resetTables(t)
		token := mintToken(t, minter)

		body := user.CreateUserRequest{
			Email:         "alice@example.com",
			QuestionLimit: 50,
		}
		rec := doJSON(t, router, http.MethodPost, "/ac/api/v1/users", token, body)

		require.Equal(t, http.StatusCreated, rec.Code)
		env := decodeSuccess[user.UserResponse](t, rec)
		assert.Equal(t, "alice@example.com", env.Data.Email)
		assert.Equal(t, 50, env.Data.QuestionLimit)
		assert.Nil(t, env.Errors.Code)

		// DB state — prove the row persisted with the derived defaults.
		var persisted user.User
		require.NoError(t,
			testDB.Where("email = ?", "alice@example.com").First(&persisted).Error,
		)
		assert.Equal(t, user.StatusActive, persisted.Status)
	})

	t.Run("returns 400 and ERROR_VALIDATION when email is invalid", func(t *testing.T) {
		resetTables(t)
		token := mintToken(t, minter)

		body := user.CreateUserRequest{
			Email:         "not-an-email",
			QuestionLimit: 50,
		}
		rec := doJSON(t, router, http.MethodPost, "/ac/api/v1/users", token, body)

		require.Equal(t, http.StatusBadRequest, rec.Code)
		var fail response.FailureResponse
		require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &fail))
		require.NotNil(t, fail.Errors.Code)
		assert.Equal(t, "ERROR_VALIDATION", *fail.Errors.Code)

		// No row should have been written on the failure path.
		var count int64
		testDB.Model(&user.User{}).Count(&count)
		assert.EqualValues(t, 0, count)
	})

	t.Run("returns 401 and ERROR_UNAUTHORIZED when the token is missing", func(t *testing.T) {
		resetTables(t)

		body := user.CreateUserRequest{Email: "alice@example.com", QuestionLimit: 50}
		rec := doJSON(t, router, http.MethodPost, "/ac/api/v1/users", "", body) // no token

		require.Equal(t, http.StatusUnauthorized, rec.Code)
		var fail response.FailureResponse
		require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &fail))
		require.NotNil(t, fail.Errors.Code)
		assert.Equal(t, "ERROR_UNAUTHORIZED", *fail.Errors.Code)
	})
}

// mintToken produces a valid bearer token for an authenticated request.
func mintToken(t *testing.T, minter *auth.TokenMinter) string {
	t.Helper()
	token, err := minter.Mint(auth.Claims{AccountID: "acct-test"})
	require.NoError(t, err)
	return token
}
```

For table-driven variants (many query-param permutations, several validation
failures), use the `[]struct{ name; body; wantStatus; wantCode }` form from
`go-conventions` with one row per decision point.

---

### 11. What every handler test must cover

One sub-test per decision point in the route (mirrors the Python prompt's §10):

| Branch | Test |
|---|---|
| Auth — missing/invalid token | expect `401` and `errors.code == "ERROR_UNAUTHORIZED"` |
| Happy path — required fields only | expect `2xx` and assert each top-level `data` field |
| Validation error — each failing `validate` tag | expect `400` and `errors.code == "ERROR_VALIDATION"` |
| Each conditional query param / filter | one sub-test per param that changes behaviour |
| Each documented error code the handler can emit | one sub-test that triggers it, asserting `status` **and** `errors.code` |
| Each explicit branch in the handler/service body | e.g. `if page < 1`, both forks of a conditional |

For any state-mutating route additionally: assert the response payload reflects the
new state, re-read the affected row and assert persisted columns, and count rows
that should / should not exist.

---

### 12. Running the tests

```bash
# Whole package (boots one container, runs all handler tests):
go test ./internal/handler/users/...

# A single test while iterating, verbose:
go test -run 'TestUserHandler_CreateUser' -v ./internal/handler/users/

# One sub-test:
go test -run 'TestUserHandler_CreateUser/returns_401' -v ./internal/handler/users/
```

testcontainers-go requires a running Docker (or compatible) daemon. Run the
package suite while iterating, then the full module (`go test ./...`) before a PR.

---

### 13. Anti-patterns (do NOT do these)

- **Booting a container per test.** One container per binary in `TestMain`; isolate
  with truncation/rollback.
- **`gin.New()` with only the handler under test.** Build the real router via the
  shared constructor so middleware and auth actually run. A test that skips the
  middleware isn't a handler test.
- **`AutoMigrate` instead of goose.** The schema under test must be the shipped
  schema, constraints and all.
- **Mocking the service or DAO.** Handler tests are end-to-end against a real DB.
  If you're stubbing the service, write a service test instead.
- **Asserting the entire body with one equality check.** Generated IDs, timestamps,
  and ordering make it brittle — assert the fields that prove behaviour.
- **Skipping `errors.code` on failure paths.** It is the machine-readable contract;
  the `msg` string is not.
- **Hand-crafting a "valid-looking" auth token.** Mint it with the same minter the
  router uses, or the middleware will (rightly) reject it and you'll test the wrong
  branch.
- **`t.Parallel()` in truncating tests.** Shared-DB truncation races. Parallelise
  only under per-test transaction isolation with distinct connections.
- **Seeding via raw SQL / ad-hoc GORM structs.** Seed through the repository/service
  so the test speaks the domain language and uses the real write path.

---

### 14. Verification checklist

Before marking a handler test complete:

- [ ] Test lives in `internal/handler/<group>/handler_test.go` in an external
      `<group>_test` package; function is `Test<Type>_<Method>`.
- [ ] `TestMain` boots **one** testcontainers-go Postgres and applies **goose**
      migrations against it.
- [ ] Each test starts from a clean slate via `resetTables` (or a rolled-back tx);
      truncating tests are **not** `t.Parallel()`.
- [ ] The router is built through the production `NewRouter(...)` constructor with
      the test DB injected — middleware and auth run unmodified.
- [ ] Requests go through `httptest.NewRequest` + `router.ServeHTTP` on the full
      namespaced path (e.g. `/ac/api/v1/...`).
- [ ] Auth headers use a token minted by the router's own minter; the `401` case
      omits or corrupts it.
- [ ] Request bodies bind against the handler's exact request DTO.
- [ ] Assertions cover `status`, then `errors.code` (failure) or specific `data`
      fields (success) — never a whole-body equality.
- [ ] For mutating routes, post-call DB state is re-read and asserted, plus a
      row-count check.
- [ ] One sub-test per decision point: auth, happy path, each validation failure,
      each documented error code, each explicit branch.
- [ ] Defers to `go-conventions` for structure; cross-refs
      `go-build-http-handlers`, `go-build-middleware`, `go-recipe-api-response-conventions`.
```