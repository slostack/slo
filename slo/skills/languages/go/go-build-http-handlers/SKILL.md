---
name: go-build-http-handlers
description: "Go/Gin equivalent of the FastAPI router conventions \u2014 thin HTTP handlers that bind\
  \ + validate (go-playground/validator) + call an application service + wrap the response. Covers route\
  \ groups, handler structs holding service deps wired in main, request/response DTOs with binding tags,\
  \ path/query/body binding, and error-to-HTTP-status mapping. Handlers contain NO business logic."
when_to_use: "Use whenever adding or modifying HTTP endpoints in a Gin service \u2014 registering routes,\
  \ writing handlers, defining request/response DTOs, or mapping service errors to HTTP status codes.\
  \ Read before touching anything under internal/handler."
group: languages
kind: skill
---

# Build Go HTTP Handlers (Gin)

## Skill summary

- **Name:** `go-build-http-handlers`
- **Description:** The Go/Gin translation of the FastAPI router conventions. Handlers
  are the gateway to workflows and nothing more: bind the request, validate it with
  `go-playground/validator`, call an application service, and wrap the result in the
  uniform response envelope. No business logic, no inline SQL, no multi-step
  orchestration inside a handler.
- **When to use:** Adding/modifying Gin endpoints, route registration, request and
  response DTOs, path/query/body binding, and error-to-status mapping.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add a Gin endpoint to create a user."
- "Register the routes for the accounts service."
- "How do I bind and validate a request body in Gin?"
- "Wire the handler struct's service dependencies in main."
- "Map a not-found service error to a 404 in the handler."
- "Write the CRUD handlers for the report resource."
- "Review this Gin handler — is it too fat?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill is the Gin counterpart of the Python `build-routers` prompt. The FastAPI
idioms translate to Go as follows, and the **Go idiom wins** over a literal port:

| FastAPI / Python | Gin / Go equivalent |
|---|---|
| `APIRouter(prefix=...)` + `include_router` | `gin.RouterGroup` + a `RegisterRoutes(rg)` method |
| Pydantic request model | request DTO struct with `json` + `binding` (validator) tags |
| `Depends()` dependency injection | handler struct holding service deps, constructed in `main` |
| `raise TypedException(...)` + central handler | return sentinel/typed errors from the service; map to status in the handler (or a shared error mapper) |
| `success_response()` / `failure_response()` | `writeSuccess` / `writeError` envelope helpers |

Defer to sibling skills:

- **`go-conventions`** — naming, struct-literal named fields, godoc,
  declarative structure, ubiquitous language. Non-negotiable; applies to every file
  here.
- **`go-build-application-services`** — the `Execute()` orchestrator the handler
  calls. All business logic lives there.
- **`go-recipe-api-response-conventions`** — the canonical `SuccessResponse[T]` /
  `FailureResponse` envelope, pagination shape, and the `writeSuccess` / `writeError`
  helpers. This skill *uses* those helpers; it does not redefine them.
- **`go-build-middleware`** — auth, request-id, DB-session, and CORS middleware
  attached to the router groups shown below.

---

## Section 1 — The Cardinal Rule: Handlers Are Thin

A handler has exactly four responsibilities, in order:

1. **Bind** the request (path + query + body) into a typed DTO.
2. **Validate** the DTO (via `binding` tags → `go-playground/validator`).
3. **Call** the application service's `Execute(...)`.
4. **Wrap** the result (or the error) in the response envelope.

Anything else — SQL, multi-step orchestration, data massaging, calling more than one
service, accumulating results across calls — belongs in an application service. See
`go-build-application-services`.

```go
// Bad — business logic, inline DB access, unwrapped response, no validation.
func (h *UserHandler) CreateUser(c *gin.Context) {
    var req CreateUserRequest
    c.ShouldBindJSON(&req)                 // error ignored
    row := h.db.QueryRow(c, "INSERT INTO users (email) VALUES ($1) RETURNING id", req.Email)
    var id string
    row.Scan(&id)                          // business logic in the handler
    c.JSON(201, gin.H{"id": id})           // raw, unwrapped response — blocker
}

// Good — bind, validate, call service, wrap. Nothing else.
func (h *UserHandler) CreateUser(c *gin.Context) {
    var req user.CreateUserRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        writeValidationError(c, err)
        return
    }

    created, err := h.createUser.Execute(c.Request.Context(), req)
    if err != nil {
        writeServiceError(c, err)
        return
    }

    writeSuccess(c, http.StatusCreated, user.FromUser(created))
}
```

The handler reads like a table of contents: bind, validate, delegate, wrap. Same
shape for every endpoint.

---

## Section 2 — Request / Response DTOs (the Pydantic analog)

DTOs live in the domain package's `dto.go` — **never** in the handler file. This
mirrors the Python "DAO placement" rule: handlers *import* DTOs, they do not *define*
them. Binding tags on the struct are the Go equivalent of Pydantic field
constraints; Gin runs `go-playground/validator` against the `binding` tag during
`ShouldBind*`.

```go
// internal/domain/user/dto.go

// CreateUserRequest is the inbound DTO for user creation.
// json tags match the DB column names; binding tags are the validation contract.
type CreateUserRequest struct {
    Email         string `json:"email"          binding:"required,email"`
    QuestionLimit int    `json:"question_limit" binding:"min=0,max=200"`
}

// UpdateUserRequest is the inbound DTO for partial user update.
// Pointer fields distinguish "absent" from "zero value".
type UpdateUserRequest struct {
    Status        *string `json:"status"         binding:"omitempty,oneof=ACTIVE INACTIVE PENDING"`
    QuestionLimit *int    `json:"question_limit" binding:"omitempty,min=0,max=200"`
}

// ListUsersQuery binds pagination query parameters. `form` is the query-string tag.
type ListUsersQuery struct {
    Page int    `form:"page" binding:"min=0"`
    Size int    `form:"size" binding:"min=1,max=100"`
    Q    string `form:"q"    binding:"omitempty"`
}

// UserResponse is the outbound DTO. Field names derive mechanically from the DB
// columns — no synonyms introduced (see go-conventions).
type UserResponse struct {
    ID            string    `json:"id"`
    Email         string    `json:"email"`
    Status        string    `json:"status"`
    QuestionLimit int       `json:"question_limit"`
    CreatedAt     time.Time `json:"created_at"`
}

// FromUser converts a User entity to its outbound DTO. Mapping is mechanical.
func FromUser(u *user.User) UserResponse {
    return UserResponse{
        ID:            u.ID,
        Email:         u.Email,
        Status:        u.Status,
        QuestionLimit: u.QuestionLimit,
        CreatedAt:     u.CreatedAt,
    }
}
```

Binding rules:

- **Body:** `c.ShouldBindJSON(&req)` — validates `binding` tags.
- **Query:** `c.ShouldBindQuery(&q)` — uses `form` tags.
- **Path:** `c.Param("id")` for single values; for multiple path params bind into a
  struct with `uri` tags via `c.ShouldBindUri(&p)`.
- Default pagination values (`Size = 25`) are applied in the handler *after* a
  successful bind, before calling the service — never let an unvalidated zero leak in.

---

## Section 3 — The Handler Struct: Dependency Wiring

Gin has no `Depends()`. The idiomatic equivalent is a **handler struct that holds the
application-service dependencies**, injected via a constructor and assembled once in
`main`. This is constructor injection (see `go-conventions`) — never
package-level globals, never reaching into `c.MustGet("db")`.

The handler depends on the **application services it calls**, expressed as
consumer-local interfaces so the handler is testable with mocks.

```go
// internal/handler/user/handler.go

// Package user wires HTTP endpoints for the User resource. It contains no business
// logic — every handler binds, validates, delegates to a service, and wraps.
package user

// createUserService is the consumer-local interface the handler needs.
// Defined here (at the consumer), not at the provider — accept interfaces.
type createUserService interface {
    Execute(ctx context.Context, req domuser.CreateUserRequest) (*domuser.User, error)
}

type getUserService interface {
    Execute(ctx context.Context, id string) (*domuser.User, error)
}

type listUsersService interface {
    Execute(ctx context.Context, params domuser.ListUsersParams) ([]*domuser.User, int, error)
}

type updateUserService interface {
    Execute(ctx context.Context, id string, req domuser.UpdateUserRequest) (*domuser.User, error)
}

type deleteUserService interface {
    Execute(ctx context.Context, id string) error
}

// Handler holds the application services backing the User endpoints.
type Handler struct {
    createUser createUserService
    getUser    getUserService
    listUsers  listUsersService
    updateUser updateUserService
    deleteUser deleteUserService
}

// DependenciesDAO carries the required application-service consumers.
type DependenciesDAO struct {
    CreateUser createUserService
    GetUser getUserService
    ListUsers listUsersService
    UpdateUser updateUserService
    DeleteUser deleteUserService
}
// NewHandler constructs a Handler with its application-service dependencies.
func NewHandler(in DependenciesDAO) *Handler {
    return &Handler{createUser: in.CreateUser, getUser: in.GetUser,
        listUsers: in.ListUsers, updateUser: in.UpdateUser, deleteUser: in.DeleteUser}
}
```

The composition service assembles repositories → domain/app services → handler
using `userhttp.NewHandler(userhttp.DependenciesDAO{CreateUser: createSvc,
GetUser: getSvc, ListUsers: listSvc, UpdateUser: updateSvc, DeleteUser: deleteSvc})`.
It registers `/ac/api/v1` (the approved service namespace), injects the resulting
router into the owned HTTP runtime and returns a typed assembly result. See
go-build-lifecycle for startup/shutdown and go-recipe-cli-configuration for the
thin cmd façade. Do not parse config, connect stores or block on ListenAndServe
inside an ad hoc main workflow.

---

## Section 4 — Route Registration & Service Namespace Prefix

Each handler exposes a `RegisterRoutes(rg *gin.RouterGroup)` method — the Gin analog
of FastAPI's `include_router`. Routes are registered under a **service-name-derived
URL namespace** with `/api/v1` preserved underneath. A bare `/api/v1` prefix is a
**blocker** (see `go-conventions`): multiple services behind one edge
proxy collide on `/api/` without a per-service namespace.

```
<service-namespace> + /api/v1 + <route>
```

The namespace is the leading letters of the service name (`accounts` → `/ac`,
`verifier` → `/v`). The group's base path is set once in `main` (`§3` above); the
handler registers routes *relative* to whatever group it's handed, so it never
hardcodes the prefix.

```go
// internal/handler/user/handler.go

// RegisterRoutes mounts the User endpoints onto the given router group.
// The caller supplies the namespaced group (e.g. /ac/api/v1); routes here are
// relative, so this handler never hardcodes the service prefix.
func (h *Handler) RegisterRoutes(rg *gin.RouterGroup) {
    users := rg.Group("/users")
    users.Use(middleware.RequireAuth())     // see go-build-middleware
    {
        users.POST("", h.CreateUser)
        users.GET("", h.ListUsers)
        users.GET("/:id", h.GetUser)
        users.PATCH("/:id", h.UpdateUser)
        users.DELETE("/:id", h.DeleteUser)
    }
}
```

```go
// Bad — bare /api/v1, no service namespace. Collides with sibling services.
api := r.Group("/api/v1")

// Good — service namespace prefix; router rules stay disjoint at the edge.
api := r.Group("/ac/api/v1")
```

---

## Section 5 — Full CRUD Handler Example

The complete handler methods for the resource. Every method is the same four-step
shape. Note: **no** SQL, **no** orchestration, **no** envelope construction inline.

```go
// internal/handler/user/handler.go (continued)

// CreateUser handles POST /users. Binds + validates the body, delegates to the
// create-user service, and returns the created resource wrapped in the envelope.
func (h *Handler) CreateUser(c *gin.Context) {
    var req domuser.CreateUserRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        writeValidationError(c, err)
        return
    }

    created, err := h.createUser.Execute(c.Request.Context(), req)
    if err != nil {
        writeServiceError(c, err)
        return
    }

    writeSuccess(c, http.StatusCreated, domuser.FromUser(created))
}

// GetUser handles GET /users/:id.
func (h *Handler) GetUser(c *gin.Context) {
    id := c.Param("id")

    found, err := h.getUser.Execute(c.Request.Context(), id)
    if err != nil {
        writeServiceError(c, err)
        return
    }

    writeSuccess(c, http.StatusOK, domuser.FromUser(found))
}

// ListUsers handles GET /users with pagination query params.
func (h *Handler) ListUsers(c *gin.Context) {
    var q domuser.ListUsersQuery
    if err := c.ShouldBindQuery(&q); err != nil {
        writeValidationError(c, err)
        return
    }
    if q.Size == 0 {
        q.Size = 25 // apply default after a valid bind, before the service call
    }

    users, total, err := h.listUsers.Execute(c.Request.Context(), domuser.ListUsersParams{
        Page: q.Page,
        Size: q.Size,
        Q:    q.Q,
    })
    if err != nil {
        writeServiceError(c, err)
        return
    }

    items := make([]domuser.UserResponse, len(users))
    for i, u := range users {
        items[i] = domuser.FromUser(u)
    }

    // Pagination metadata lives inside data — see go-recipe-api-response-conventions.
    writeSuccess(c, http.StatusOK, PageResponse[domuser.UserResponse]{
        Page:  q.Page,
        Size:  q.Size,
        Total: total,
        Items: items,
    })
}

// UpdateUser handles PATCH /users/:id.
func (h *Handler) UpdateUser(c *gin.Context) {
    id := c.Param("id")

    var req domuser.UpdateUserRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        writeValidationError(c, err)
        return
    }

    updated, err := h.updateUser.Execute(c.Request.Context(), id, req)
    if err != nil {
        writeServiceError(c, err)
        return
    }

    writeSuccess(c, http.StatusOK, domuser.FromUser(updated))
}

// DeleteUser handles DELETE /users/:id.
func (h *Handler) DeleteUser(c *gin.Context) {
    id := c.Param("id")

    if err := h.deleteUser.Execute(c.Request.Context(), id); err != nil {
        writeServiceError(c, err)
        return
    }

    c.Status(http.StatusNoContent)
}
```

---

## Section 6 — Error-to-HTTP-Status Mapping (routers map, they don't build)

FastAPI centralizes error handling: services `raise` typed exceptions and one
registered handler builds the failure envelope. The idiomatic Go equivalent:
**services return typed/sentinel errors; a single shared mapper translates them into
an HTTP status + failure envelope.** The handler calls that mapper — it never builds
error JSON inline and never `switch`es on error type in every method.

The service defines the sentinel errors (see `go-build-application-services` and
`go-conventions`):

```go
// internal/domain/user/errors.go
var (
    ErrNotFound     = errors.New("user not found")
    ErrEmailConflict = errors.New("email already registered")
    ErrInvalidState = errors.New("invalid state transition")
    ErrUnauthorized = errors.New("not authorized")
)
```

A single mapper turns any error into the right status + envelope. This is the Go
translation of `_initialize_exception_handlers` — defined once, used by every handler.
The envelope helpers (`writeSuccess`, `writeError`) come from
`go-recipe-api-response-conventions`.

```go
// internal/handler/errors.go

// statusFor maps a domain/service error to an HTTP status and a stable error code.
// This is the single place error → status translation happens (the Go analog of
// FastAPI's centrally-registered exception handlers). Add new mappings here, not
// in individual handlers.
func statusFor(err error) (int, string) {
    switch {
    case errors.Is(err, domuser.ErrNotFound):
        return http.StatusNotFound, "NOT_FOUND"
    case errors.Is(err, domuser.ErrEmailConflict):
        return http.StatusConflict, "CONFLICT"
    case errors.Is(err, domuser.ErrInvalidState):
        return http.StatusPreconditionFailed, "PRECONDITION_FAILED"
    case errors.Is(err, domuser.ErrUnauthorized):
        return http.StatusUnauthorized, "UNAUTHORIZED"
    default:
        return http.StatusInternalServerError, "INTERNAL_ERROR"
    }
}

// writeServiceError maps a service error to its status/envelope and writes it.
// A 5xx is logged with the underlying cause; the client sees a sanitized message.
func writeServiceError(c *gin.Context, err error) {
    status, code := statusFor(err)
    if status >= http.StatusInternalServerError {
        slog.Error("handler: internal error",
            "path", c.FullPath(), "request_id", c.GetString("request_id"), "err", err)
        writeError(c, status, "internal error", code)
        return
    }
    writeError(c, status, err.Error(), code)
}

// writeValidationError converts a go-playground/validator failure into a 422 in the
// standard failure envelope, mirroring FastAPI's RequestValidationError handler.
func writeValidationError(c *gin.Context, err error) {
    var ve validator.ValidationErrors
    if errors.As(err, &ve) {
        msgs := make([]string, len(ve))
        for i, fe := range ve {
            msgs[i] = fmt.Sprintf("%s: failed %q", fe.Field(), fe.Tag())
        }
        writeErrors(c, http.StatusUnprocessableEntity, msgs, "UNPROCESSABLE_ENTITY")
        return
    }
    // malformed JSON, wrong type, etc. → 400
    writeError(c, http.StatusBadRequest, "invalid request body", "BAD_REQUEST")
}
```

```go
// Bad — handler builds error JSON inline and re-implements the envelope every time.
func (h *Handler) GetUser(c *gin.Context) {
    found, err := h.getUser.Execute(c.Request.Context(), c.Param("id"))
    if errors.Is(err, domuser.ErrNotFound) {
        c.JSON(404, gin.H{"errors": gin.H{"msg": []string{"not found"}, "code": "NOT_FOUND"}})
        return
    }
    if err != nil {
        c.JSON(500, gin.H{"error": err.Error()}) // drifts from the envelope shape
        return
    }
    c.JSON(200, found) // unwrapped
}

// Good — handler delegates the mapping; the shape stays uniform across every route.
func (h *Handler) GetUser(c *gin.Context) {
    found, err := h.getUser.Execute(c.Request.Context(), c.Param("id"))
    if err != nil {
        writeServiceError(c, err)
        return
    }
    writeSuccess(c, http.StatusOK, domuser.FromUser(found))
}
```

Adding a new failure mode: define a sentinel in the service, add one `case` to
`statusFor`. Handlers are untouched. If a handler contains an `if errors.Is(...)`
that translates one error to a status inline, the mapping is in the wrong place —
move it into `statusFor`.

---

## Section 7 — What Handlers MUST and MUST NOT Do

**MUST:**

1. Bind path/query/body into a typed DTO imported from the domain package.
2. Validate via `binding` tags; on failure call `writeValidationError`.
3. Call exactly the service(s) needed, passing `c.Request.Context()` first.
4. Wrap success with `writeSuccess`; wrap errors via `writeServiceError`.

**MUST NOT:**

1. Define request/response DTO structs in the handler file — they live in the domain
   `dto.go`.
2. Contain SQL, GORM calls, or any repository access.
3. Orchestrate across multiple service calls or accumulate state between them — that
   is an application service's job (`go-build-application-services`).
4. Build response or error JSON inline — always go through the envelope helpers.
5. Hardcode the service-namespace prefix — mount relative to the group handed to
   `RegisterRoutes`.
6. Reach for globals or `c.MustGet(...)` for dependencies — inject via `NewHandler`.

---

## Section 8 — Checklist

Run through before merging any handler change. Each unchecked item is a **blocker**.

### Structure
- [ ] Handler does only bind → validate → call service → wrap. No business logic.
- [ ] No SQL / GORM / repository access anywhere in the handler package.
- [ ] Handler never calls more than the service(s) strictly needed; no cross-call
      orchestration.
- [ ] DTOs are defined in the domain `dto.go`, not in the handler file.

### Binding & Validation
- [ ] Request DTOs carry `json`/`form`/`uri` tags and a `binding` validation contract.
- [ ] Every `ShouldBind*` error is handled via `writeValidationError` (never ignored).
- [ ] Pagination defaults applied after a successful bind, before the service call.

### Dependency Wiring
- [ ] Service deps are held on the handler struct and injected via `NewHandler`.
- [ ] Dependencies are consumer-local interfaces (accept interfaces, return structs).
- [ ] No package-level globals or `c.MustGet` for dependencies.
- [ ] Assembly (repo → service → handler → group) happens in `cmd/server/main.go`.

### Routing
- [ ] Routes registered via a `RegisterRoutes(rg *gin.RouterGroup)` method.
- [ ] Group prefix includes the **service namespace** (`/ac/api/v1`); bare `/api/v1`
      is a blocker.
- [ ] Handler registers routes relative to the group — no hardcoded prefix.
- [ ] Auth/middleware attached at the group level (`go-build-middleware`).

### Errors & Responses
- [ ] Every response goes through `writeSuccess` / `writeError` — no raw `c.JSON`
      of an entity, no inline error JSON.
- [ ] Service errors are mapped in the single shared `statusFor` mapper, not inline
      per-handler.
- [ ] 5xx paths log the underlying cause and return a sanitized client message.
- [ ] Sentinel/typed errors are defined in the service/domain layer, not the handler.

### Cross-references
- [ ] Envelope shape defers to `go-recipe-api-response-conventions`.
- [ ] Orchestration defers to `go-build-application-services`.
- [ ] Middleware defers to `go-build-middleware`.
- [ ] Naming/structure defers to `go-conventions`.
