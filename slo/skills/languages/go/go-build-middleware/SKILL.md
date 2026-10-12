---
name: go-build-middleware
description: "Go scoped recipe (GORM, Gin): Building Gin middleware for cross-cutting concerns in Go services\
  \ \u2014 request-ID/tracing, structured slog logging, DB transaction-in-context, auth, panic recovery,\
  \ CORS, and centralized error handling that emits the uniform response envelope. Covers ordering, storing\
  \ values in gin.Context, and reading them downstream."
when_to_use: "Only for the named project stack and component. Use when adding or reviewing any Gin middleware\
  \ \u2014 anything that must run before/after every handler (context setup, logging, DB session lifecycle,\
  \ auth, recovery, CORS, error normalization). Not for per-route business logic."
group: languages
kind: skill
---

# Build Go Middleware

## Skill summary

- **Name:** `go-build-middleware`
- **Description:** Building Gin middleware for cross-cutting concerns — request-ID
  and tracing, structured `slog` request logging, DB transaction-in-context, auth
  and authorization, panic recovery, CORS, and centralized error handling that
  produces the uniform response envelope. Covers registration ordering, storing
  values in `gin.Context`, and reading them from downstream handlers and services.
- **When to use:** Anything that must run before/after every request rather than
  inside a single handler.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add request-ID and tracing middleware to our Gin service."
- "Wire up structured slog request logging as middleware."
- "How do I put a DB transaction in the request context in Go?"
- "Write auth middleware that puts the current user in gin.Context."
- "We need panic recovery that returns our standard error envelope."
- "Set up CORS the right way for our Gin API."
- "Centralize error handling so handlers just call c.Error()."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

Middleware in our Gin services intercepts every request before it reaches the
handler and every response before it leaves. We use it for cross-cutting concerns
only: request context, structured logging, DB session/transaction lifecycle, auth,
panic recovery, CORS, and error normalization. Business logic never lives in
middleware.

This is the Go equivalent of the FastAPI `build-middleware` prompt. FastAPI's
`BaseHTTPMiddleware.dispatch` + `request.state` maps to Gin's `gin.HandlerFunc` +
`gin.Context` key/value store. Python `ContextVar` (async-task-local storage) maps
to values carried on `context.Context` and read back downstream. **The Go idiom —
`gin.HandlerFunc` closures and `c.Set`/`c.Get` — wins over any literal port of the
class-based `dispatch` pattern.** The principles survive: one concern per
middleware, guaranteed cleanup, typed context values, and no swallowed errors.

Defer to `go-conventions` for naming, godoc, declarative structure,
error wrapping, and the response-envelope types. This skill only covers the
middleware layer. Cross-references:

- `go-recipe-api-response-conventions` — the `SuccessResponse[T]` / `FailureResponse`
  envelope that the error-handling and recovery middleware emit.
- `go-build-http-handlers` — the thin handlers that read the values these
  middleware store (`RequestID`, `CurrentUser`, the DB handle).

Middleware files live under `internal/middleware/`, one concern per file:
`requestctx.go`, `logging.go`, `db.go`, `auth.go`, `recovery.go`, `cors.go`,
`errors.go`.

---

### Section 1 — The `gin.HandlerFunc` shape

A middleware is a function returning a `gin.HandlerFunc`. The returned closure does
pre-processing, calls `c.Next()` to run the rest of the chain, then does
post-processing. This is the direct analog of FastAPI's
`response = await call_next(request)` sandwich.

```go
// Package middleware holds Gin middleware for cross-cutting concerns.
package middleware

import "github.com/gin-gonic/gin"

// Custom returns a template middleware showing the standard shape.
//
// Pre-processing runs before the handler; c.Next() runs the remaining chain;
// post-processing runs after the handler returns.
func Custom() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Pre-processing: attach data for downstream handlers/middleware.
		c.Set("example_key", "example_value")

		c.Next() // hand off to the next middleware / handler

		// Post-processing: inspect c.Writer.Status(), set headers, record metrics.
	}
}
```

Key points:

1. The outer function is where configuration parameters go (the Python `__init__`
   analog). Middleware needing config takes typed parameters and returns the
   closure over them — see Section 6 (CORS) and Section 4 (auth).
2. `c.Next()` forwards to the rest of the chain. Everything after it is
   post-processing.
3. **`c.Abort()` (or `c.AbortWithStatus`) stops the chain** — downstream handlers
   do not run. Use it in auth/validation middleware that rejects a request. Calling
   `c.Next()` after writing a response is a bug; abort instead.
4. Use `c.Set(key, value)` to attach data. Downstream code reads it with `c.Get`.
   This is the `request.state` analog.

```go
// Bad — mutating the request without a clear key; no c.Next()/c.Abort() decision.
func Broken() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Writer.Header().Set("X-Thing", "1")
		// forgot c.Next(): the handler never runs, response hangs at 200 empty
	}
}

// Good — explicit key, explicit chain control.
func RequireHeader(name string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.GetHeader(name) == "" {
			c.AbortWithStatusJSON(http.StatusBadRequest, failure("missing "+name, "MISSING_HEADER"))
			return
		}
		c.Next()
	}
}
```

---

### Section 2 — Typed context keys and accessors

FastAPI stashes arbitrary attributes on `request.state`. Gin's `c.Set`/`c.Get`
store `any` under string keys. Untyped string keys and `any` values scattered
across the codebase are a synonym/typing hazard (see `go-conventions`
§1.1 and §1.4). **Centralize keys as constants and expose typed accessors** so no
downstream handler ever does an unchecked type assertion.

```go
// contextkeys.go
package middleware

// Context keys under which middleware stores per-request values.
// Every consumer reads via the typed accessors below — never c.Get directly.
const (
	ctxKeyRequestID   = "request_id"
	ctxKeyCurrentUser = "current_user"
	ctxKeyDB          = "db"
)

// RequestID returns the request ID set by RequestContext middleware.
//
// Returns "" if no request ID was set (e.g. middleware not registered).
func RequestID(c *gin.Context) string {
	v, ok := c.Get(ctxKeyRequestID)
	if !ok {
		return ""
	}
	id, _ := v.(string)
	return id
}

// CurrentUser returns the authenticated user set by Auth middleware.
//
// Returns nil and false if the request is unauthenticated.
func CurrentUser(c *gin.Context) (*user.User, bool) {
	v, ok := c.Get(ctxKeyCurrentUser)
	if !ok {
		return nil, false
	}
	u, ok := v.(*user.User)
	return u, ok
}

// DB returns the *gorm.DB (transaction) bound to this request.
//
// Panics only if DBTransaction middleware was not registered — a programmer error.
func DB(c *gin.Context) *gorm.DB {
	return c.MustGet(ctxKeyDB).(*gorm.DB)
}
```

Downstream handlers stay clean and never repeat the assertion:

```go
// go-build-http-handlers territory — handler reads typed values.
func (h *UserHandler) GetUser(c *gin.Context) {
	log := slog.With("request_id", middleware.RequestID(c))
	db := middleware.DB(c)

	u, err := user.NewService(user.NewRepository(db)).GetByID(c.Request.Context(), c.Param("id"))
	if err != nil {
		c.Error(err) // centralized error middleware turns this into the envelope
		return
	}
	c.JSON(http.StatusOK, apiresp.Success(user.FromUser(u)))
}
```

---

### Section 3 — Registration and ordering

Register global middleware in the engine setup (the `web_app.py`
`_initialize_middleware` analog), typically `internal/server/router.go`. **Unlike
FastAPI, Gin runs middleware in registration order** — the first `Use` is the
outermost (first to see the request, last to see the response). No reverse-order
gotcha, but ordering is still load-bearing.

```go
// NewRouter builds the configured Gin engine with the global middleware chain.
// RouterDAO carries required router dependencies.
type RouterDAO struct {
    Config config.AppConfig
    DB *gorm.DB
}

func NewRouter(in RouterDAO) *gin.Engine {
    cfg, db := in.Config, in.DB
	r := gin.New() // gin.New, NOT gin.Default — we supply our own logger/recovery

	// Order matters. Outermost first.
	r.Use(middleware.Recovery())        // 1. catch panics from everything below
	r.Use(middleware.RequestContext())  // 2. request ID must exist before logging
	r.Use(middleware.RequestLogging())  // 3. logs using the request ID from (2)
	r.Use(middleware.CORS(cfg.CORS))    // 4. CORS headers / preflight short-circuit
	r.Use(middleware.DBTransaction(db)) // 5. per-request tx, committed on success
	r.Use(middleware.ErrorHandler())    // 6. normalize c.Errors into the envelope

	registerRoutes(r, db)
	return r
}
```

Ordering rules:

- **Recovery outermost.** It must wrap every other middleware so a panic anywhere
  still produces a clean response.
- **RequestContext before RequestLogging.** Logging reads the request ID, so the
  ID must be set first (the FastAPI "RequestCtx runs before Db" invariant).
- **CORS before anything that can abort**, so preflight `OPTIONS` short-circuits
  without touching auth or the DB.
- **Auth is registered per route group**, not globally — public routes exist. See
  Section 4.

```go
func registerRoutes(r *gin.Engine, db *gorm.DB) {
	// Service namespace prefix — bare /api/v1 is a blocker (go-conventions).
	ac := r.Group("/ac/api/v1")

	ac.POST("/auth/login", authHandler.Login) // public

	authed := ac.Group("")
	authed.Use(middleware.RequireAuth(userRepo)) // group-scoped auth
	authed.GET("/users/:id", userHandler.GetUser)
}
```

---

### Section 4 — Request context (request ID + tracing)

Generates a unique request ID per request, honors an inbound
`X-Request-ID`/trace header if present, stores it on both `gin.Context` and the
`context.Context` (so services and DB queries can log it without touching Gin), and
echoes it back as a response header. This is the `RequestCtxMiddleware` analog;
`context.Context` replaces the Python `ContextVar`.

```go
// requestctx.go
package middleware

import (
	"context"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// requestIDCtxKey is an unexported type to avoid context key collisions.
type requestIDCtxKey struct{}

// RequestContext assigns a request ID to every request.
//
// It reuses an inbound X-Request-ID header when present, otherwise generates a
// UUID. The ID is stored on gin.Context, injected into the request's
// context.Context, and echoed on the X-Request-ID response header.
func RequestContext() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-ID")
		if rid == "" {
			rid = uuid.NewString()
		}

		c.Set(ctxKeyRequestID, rid)
		ctx := context.WithValue(c.Request.Context(), requestIDCtxKey{}, rid)
		c.Request = c.Request.WithContext(ctx)
		c.Writer.Header().Set("X-Request-ID", rid)

		c.Next()
	}
}

// RequestIDFromContext reads the request ID off a context.Context.
//
// This lets services and repositories log the request ID without depending on Gin.
// Returns "" if no request ID is present.
func RequestIDFromContext(ctx context.Context) string {
	id, _ := ctx.Value(requestIDCtxKey{}).(string)
	return id
}
```

Design notes (mirror the Python "key design decisions"):

1. **Dual storage** — on `gin.Context` for handlers, and on `context.Context` for
   deep call stacks and DB drivers, exactly as the Python version stores in both
   `request.state` and a `ContextVar`.
2. **Unexported struct key type** (`requestIDCtxKey{}`) prevents cross-package
   `context` key collisions — the idiomatic Go rule; never use a bare string as a
   `context.Value` key.
3. **Honor inbound trace headers** so IDs propagate across service hops.

---

### Section 5 — Structured request logging (slog)

Logs one structured line per request after it completes: method, path, status,
latency, client IP, and request ID. Uses stdlib `log/slog`. Gin's default logger is
unstructured; we register `gin.New()` and supply this instead.

```go
// logging.go
package middleware

import (
	"log/slog"
	"time"

	"github.com/gin-gonic/gin"
)

// RequestLogging emits one structured slog line per completed request.
//
// It must run after RequestContext so the request ID is available. The line is
// logged at Error level for 5xx, Warn for 4xx, and Info otherwise.
func RequestLogging() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		c.Next()

		attrs := []slog.Attr{
			slog.String("request_id", RequestID(c)),
			slog.String("method", c.Request.Method),
			slog.String("path", c.Request.URL.Path),
			slog.Int("status", c.Writer.Status()),
			slog.Duration("latency", time.Since(start)),
			slog.String("client_ip", c.ClientIP()),
		}
		slog.LogAttrs(c.Request.Context(), levelForStatus(c.Writer.Status()),
			"request completed", attrs...)
	}
}

// levelForStatus maps an HTTP status to the slog level the access log uses.
func levelForStatus(status int) slog.Level {
	switch {
	case status >= 500:
		return slog.LevelError
	case status >= 400:
		return slog.LevelWarn
	default:
		return slog.LevelInfo
	}
}
```

Rules:

- Log **after** `c.Next()` so the final status and latency are known.
- Never log request bodies or auth headers — PII/secret leak.
- Keep it to one line per request; per-step logging belongs in services.

---

### Section 6 — DB transaction in context

The core middleware, matching the FastAPI `DbMiddleware`. It opens a GORM
transaction per request, binds it to `gin.Context`, and **guarantees cleanup**: the
transaction is committed if the handler succeeded (2xx and no errors) and rolled
back otherwise — including on panic. The Go analog of Python's `try/finally` is
`defer` plus a recover-aware close.

```go
// db.go
package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// DBTransaction runs each request inside a single GORM transaction.
//
// The transaction is stored under ctxKeyDB and read via middleware.DB(c).
// It commits when the handler completes with a 2xx status and no c.Errors;
// otherwise (error status, recorded error, or panic) it rolls back. This owns
// the transaction lifecycle so services never open their own.
func DBTransaction(base *gorm.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		tx := base.WithContext(c.Request.Context()).Begin()
		if tx.Error != nil {
			c.AbortWithStatusJSON(http.StatusInternalServerError,
				failure("could not start transaction", "DB_UNAVAILABLE"))
			return
		}

		// Guaranteed cleanup, even on panic — the try/finally analog.
		defer func() {
			if r := recover(); r != nil {
				tx.Rollback()
				panic(r) // re-raise for the Recovery middleware to handle
			}
		}()

		c.Set(ctxKeyDB, tx)

		c.Next()

		if len(c.Errors) > 0 || c.Writer.Status() >= http.StatusBadRequest {
			tx.Rollback()
			return
		}
		if err := tx.Commit().Error; err != nil {
			_ = c.Error(err) // surface to ErrorHandler; response already partly shaped
		}
	}
}
```

How it works (mirrors the Python explanation):

1. **Session creation** — one transaction per request, derived from the shared
   `*gorm.DB` pool and bound to the request `context.Context` so query cancellation
   propagates.
2. **Injection via context** — stored under `ctxKeyDB`; handlers and services read
   it through `middleware.DB(c)` or by taking a `*gorm.DB` parameter.
3. **Guaranteed cleanup** — `defer` + `recover` ensures rollback on panic;
   commit/rollback on the normal path is decided by status and `c.Errors`. No
   leaked transactions.
4. **Services never open their own transaction** — the middleware owns the
   lifecycle, exactly as the FastAPI services always accept `db_session` and never
   create sessions.

```go
// Good — service accepts the tx-scoped handle; never begins its own transaction.
type Service struct{ repo Repository }

func (s *Service) ActivateUser(ctx context.Context, id string) (*User, error) {
	u, err := s.repo.FindByID(ctx, id)
	if err != nil {
		return nil, err
	}
	u.Status = StatusActive
	return s.repo.Update(ctx, u)
}

// Bad — service opens its own transaction, defeating request-scoped consistency.
func (s *Service) ActivateUserBad(id string) error {
	tx := globalDB.Begin() // ← ignores the request's transaction; a blocker
	defer tx.Commit()
	// ...
	return nil
}
```

For read-only endpoints that don't need a transaction, register a
`DBSession(base)` variant that binds `base.WithContext(...)` directly and skips the
begin/commit — but a per-request transaction is the safe default.

---

### Section 7 — Auth and authorization

Two concerns, two middleware. **Authentication** resolves the caller and stores the
user; **authorization** checks a role/permission. Both are registered per route
group, never globally (public routes exist). They `c.Abort()` on rejection.

```go
// auth.go
package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// tokenVerifier is the minimal interface RequireAuth needs.
// Defined at the consumer per go-conventions.
type tokenVerifier interface {
	VerifyToken(ctx context.Context, token string) (*user.User, error)
}

// RequireAuth authenticates the caller from the Bearer token and stores the user.
//
// Aborts with 401 if the header is missing/malformed or the token is invalid.
// Downstream handlers read the user via middleware.CurrentUser(c).
func RequireAuth(verifier tokenVerifier) gin.HandlerFunc {
	return func(c *gin.Context) {
		token, ok := bearerToken(c.GetHeader("Authorization"))
		if !ok {
			c.AbortWithStatusJSON(http.StatusUnauthorized,
				failure("missing or malformed Authorization header", "UNAUTHENTICATED"))
			return
		}

		u, err := verifier.VerifyToken(c.Request.Context(), token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized,
				failure("invalid token", "UNAUTHENTICATED"))
			return
		}

		c.Set(ctxKeyCurrentUser, u)
		c.Next()
	}
}

// RequireRole authorizes the already-authenticated user against a required role.
//
// Must be registered after RequireAuth. Aborts with 403 if the role is absent.
func RequireRole(role string) gin.HandlerFunc {
	return func(c *gin.Context) {
		u, ok := CurrentUser(c)
		if !ok {
			c.AbortWithStatusJSON(http.StatusUnauthorized,
				failure("authentication required", "UNAUTHENTICATED"))
			return
		}
		if !u.HasRole(role) {
			c.AbortWithStatusJSON(http.StatusForbidden,
				failure("insufficient permissions", "FORBIDDEN"))
			return
		}
		c.Next()
	}
}

// bearerToken extracts the token from an "Authorization: Bearer <token>" header.
func bearerToken(header string) (string, bool) {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return "", false
	}
	return strings.TrimPrefix(header, prefix), true
}
```

Registration composes them in order:

```go
admin := ac.Group("/admin")
admin.Use(middleware.RequireAuth(verifier)) // 401 boundary
admin.Use(middleware.RequireRole("admin"))  // 403 boundary — runs only if authed
admin.DELETE("/users/:id", userHandler.DeleteUser)
```

---

### Section 8 — Panic recovery

Catches any panic from the handler chain and converts it to a `500` in the standard
envelope, logging the stack. This replaces `gin.Default`'s recovery so the response
shape matches every other error. It is registered outermost (Section 3).

```go
// recovery.go
package middleware

import (
	"log/slog"
	"net/http"
	"runtime/debug"

	"github.com/gin-gonic/gin"
)

// Recovery converts any panic in the handler chain into a 500 error envelope.
//
// It logs the panic value and stack at Error level, keyed by request ID, then
// aborts with the uniform FailureResponse. Registered outermost so it wraps all
// other middleware.
func Recovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				slog.LogAttrs(c.Request.Context(), slog.LevelError, "panic recovered",
					slog.String("request_id", RequestID(c)),
					slog.Any("panic", r),
					slog.String("stack", string(debug.Stack())),
				)
				c.AbortWithStatusJSON(http.StatusInternalServerError,
					failure("internal server error", "INTERNAL_ERROR"))
			}
		}()
		c.Next()
	}
}
```

Note the interaction with Section 6: `DBTransaction`'s `defer` re-panics after
rolling back, and `Recovery` (registered outermost) catches it. Never leak the
panic value or stack into the HTTP response body — log it, return a generic message.

---

### Section 9 — CORS

Configuration-driven middleware (the `RateLimitMiddleware`-with-params analog). It
takes a typed config, sets the CORS headers, and short-circuits preflight `OPTIONS`
before auth/DB run. Prefer the community `gin-contrib/cors` for anything nontrivial;
the hand-rolled version below shows the shape and the preflight short-circuit.

```go
// cors.go
package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// CORSConfig configures the CORS middleware. Field names mirror the response
// headers they populate.
type CORSConfig struct {
	AllowedOrigins []string
	AllowedMethods []string
	AllowedHeaders []string
	AllowCredentials bool
}

// CORS applies CORS headers and short-circuits preflight OPTIONS requests.
//
// Preflight requests return 204 immediately, before auth or DB middleware run.
func CORS(cfg CORSConfig) gin.HandlerFunc {
	allowMethods := strings.Join(cfg.AllowedMethods, ", ")
	allowHeaders := strings.Join(cfg.AllowedHeaders, ", ")

	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if allowed(cfg.AllowedOrigins, origin) {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Methods", allowMethods)
			c.Header("Access-Control-Allow-Headers", allowHeaders)
			if cfg.AllowCredentials {
				c.Header("Access-Control-Allow-Credentials", "true")
			}
		}

		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent) // preflight — stop here
			return
		}
		c.Next()
	}
}

// allowed reports whether origin is in the allow list (or the list is a wildcard).
func allowed(origins []string, origin string) bool {
	for _, o := range origins {
		if o == "*" || o == origin {
			return true
		}
	}
	return false
}
```

Rule: avoid `Access-Control-Allow-Origin: *` together with
`Allow-Credentials: true` — browsers reject it and it is a security smell. Echo the
specific allowed origin instead.

---

### Section 10 — Centralized error handling

Gin collects errors handlers attach with `c.Error(err)` onto `c.Errors`. A single
error middleware inspects them after `c.Next()`, maps sentinel errors to status
codes, and writes the uniform `FailureResponse` envelope — so handlers never build
error responses themselves (they just `c.Error(err); return`). This is the Go
equivalent of FastAPI's exception handlers, and it is why other middleware use
`c.Error` / `c.Errors` rather than writing responses directly.

```go
// errors.go
package middleware

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"myservice/internal/domain/apperr"
)

// ErrorHandler translates c.Errors into the uniform FailureResponse envelope.
//
// It runs after the handler, maps known sentinel errors to HTTP statuses, and
// writes a single normalized error response. If the handler already wrote a
// response it does nothing.
func ErrorHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()

		if len(c.Errors) == 0 || c.Writer.Written() {
			return
		}

		err := c.Errors.Last().Err
		status, code := classify(err)
		c.JSON(status, failure(err.Error(), code))
	}
}

// classify maps a domain error to an HTTP status and machine-readable code.
func classify(err error) (int, string) {
	switch {
	case errors.Is(err, apperr.ErrNotFound):
		return http.StatusNotFound, "NOT_FOUND"
	case errors.Is(err, apperr.ErrConflict):
		return http.StatusConflict, "CONFLICT"
	case errors.Is(err, apperr.ErrValidation):
		return http.StatusUnprocessableEntity, "VALIDATION_ERROR"
	case errors.Is(err, apperr.ErrUnauthorized):
		return http.StatusUnauthorized, "UNAUTHENTICATED"
	default:
		return http.StatusInternalServerError, "INTERNAL_ERROR"
	}
}
```

`failure` and `Success` come from the response layer — see
`go-recipe-api-response-conventions`. Shown inline here for a self-contained example:

```go
// failure builds a FailureResponse envelope. In real code this lives in the
// apiresp package (go-recipe-api-response-conventions), not in middleware.
func failure(msg, code string) apiresp.FailureResponse {
	return apiresp.FailureResponse{
		Data:       nil,
		APIVersion: apiresp.APIVersion,
		Errors:     apiresp.ResponseErrors{Msg: []string{msg}, Code: &code},
	}
}
```

Handlers become trivial and never assemble error bodies:

```go
// Good — handler defers all error shaping to the middleware.
func (h *UserHandler) GetUser(c *gin.Context) {
	u, err := h.svc.GetByID(c.Request.Context(), c.Param("id"))
	if err != nil {
		c.Error(err) // classified + enveloped by ErrorHandler
		return
	}
	c.JSON(http.StatusOK, apiresp.Success(user.FromUser(u)))
}

// Bad — handler hand-rolls the error response; drifts from the envelope.
func (h *UserHandler) GetUserBad(c *gin.Context) {
	u, err := h.svc.GetByID(c.Request.Context(), c.Param("id"))
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()}) // wrong shape — blocker
		return
	}
	c.JSON(200, u) // unwrapped payload — blocker
}
```

---

### Guidelines

1. **One concern per middleware.** Never fold DB session handling and logging into
   one middleware. Separate files under `internal/middleware/`.
2. **Guaranteed cleanup with `defer`.** Any middleware that allocates a resource
   (transaction, connection, file) releases it in a `defer`, and handles the panic
   path with `recover`. This is the Go `try/finally`.
3. **Store via `c.Set`, read via typed accessors.** Never scatter raw `c.Get` +
   type assertions across handlers; centralize keys and expose `RequestID(c)`,
   `CurrentUser(c)`, `DB(c)`.
4. **Registration order is load-bearing** — Gin runs middleware in registration
   order (outermost first). Recovery outermost; RequestContext before logging; CORS
   before anything that aborts; auth per route group.
5. **Abort, don't fall through.** Rejecting middleware calls `c.Abort*` and
   `return`. Never write a response and then `c.Next()`.
6. **Don't swallow errors; funnel them.** Middleware and handlers attach errors
   with `c.Error(err)` and let `ErrorHandler` shape the envelope. The one place that
   catches-to-suppress is `Recovery`, and it logs the full stack first.
7. **Never log secrets or PII** — no auth headers, no request bodies in the access
   log.
8. **`context.Context` carries values across layers**, `gin.Context` carries them
   within the request handling. Use unexported struct types as `context` keys.
9. **Defer to `go-conventions`** for godoc, naming, declarative
   structure, sentinel errors, and `%w` wrapping.

---

### Checklist

Run through before merging any middleware change. Each unchecked item is a blocker.

- [ ] Middleware is a `func(...) gin.HandlerFunc` returning a closure; config
      params live on the outer function.
- [ ] Exactly **one cross-cutting concern** per middleware, its own file under
      `internal/middleware/`.
- [ ] Every stored value has a **centralized key constant** and a **typed
      accessor**; no raw `c.Get` + assertion in handlers.
- [ ] Registration order is correct: Recovery outermost → RequestContext →
      Logging → CORS → DB → ErrorHandler; auth is **per route group**.
- [ ] Rejecting middleware calls `c.Abort*` and `return` (never `c.Next()` after
      writing).
- [ ] Resource-owning middleware (DB tx) uses `defer` + `recover` for guaranteed
      cleanup; commits on 2xx/no-errors, rolls back otherwise.
- [ ] `RequestContext` honors inbound `X-Request-ID`, sets it on both `gin.Context`
      and `context.Context`, and echoes the response header.
- [ ] Logging runs after `c.Next()`, is one structured `slog` line, and logs no
      secrets/PII.
- [ ] `Recovery` logs the stack and returns the uniform envelope — never leaks the
      panic to the client.
- [ ] Error responses go through `ErrorHandler` + the `go-recipe-api-response-conventions`
      envelope; handlers only call `c.Error(err)`.
- [ ] `context.Context` keys use unexported struct types, not bare strings.
