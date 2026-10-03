---
name: go-recipe-bootstrap-project-scaffolding
description: "Go scoped recipe (GORM, Gin): Scaffold a brand-new Go service \u2014 go mod init, the cmd/internal/pkg\
  \ directory tree, a minimal main.go wiring (viper config, slog logger, GORM DB, Gin router, graceful\
  \ shutdown), Makefile, Dockerfile + docker-compose, .golangci.yml, goose migrations, and a first health\
  \ endpoint. Copy-paste-ready commands and stubs."
when_to_use: "Only for the named project stack and component. Use when creating a brand-new Go service\
  \ or project from scratch and you need the full directory layout plus wired-up scaffolding files. Not\
  \ for adding a feature to an existing service \u2014 use the build-go-* skills for that."
group: languages
kind: skill
---

# Go — Bootstrap Project Scaffolding

## Skill summary

- **Name:** `go-recipe-bootstrap-project-scaffolding`
- **Description:** Scaffold a brand-new Go service — `go mod init`, the
  `cmd/`/`internal/`/`pkg/` directory tree, a minimal wired `main.go` (viper →
  slog → GORM → Gin → graceful shutdown), Makefile, Dockerfile + docker-compose
  (postgres/redis), `.golangci.yml`, goose migrations, and a first health
  endpoint. Copy-paste-ready commands and file stubs.
- **When to use:** Creating a brand-new Go service/project. For extending an
  existing service, use the `build-go-*` skills instead.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Scaffold a new Go microservice called `atlasd`."
- "Bootstrap a fresh Go API project with GORM, Gin, and goose migrations."
- "Set up the standard Go directory layout for a new service."
- "Give me a minimal main.go that wires viper config, slog, a DB, and a Gin router
  with graceful shutdown."
- "Create the Makefile, Dockerfile, and docker-compose for a new Go service."
- "Add a first health endpoint and a goose migrations dir to a new Go project."
- "Initialize a new Go module with the linter config and CI-ready targets."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill is the Go equivalent of the Python `bootstrap-project-scaffolding`
prompt. The Python original scaffolds a FastAPI + SQLAlchemy + Alembic + Poetry
service; this translates each part to the idiomatic Go stack. Where a Python idiom
(Poetry, `pyproject.toml`, `__init__.py`, `conftest.py`, `PYTHONPATH`) has no Go
equivalent, the Go idiom wins and the translation is called out explicitly.

**Defer to [`go-conventions`](../go-conventions/SKILL.md)**
for all naming, structure, godoc, error-wrapping, and API-envelope rules — this
skill only lays down the skeleton; the conventions govern what goes inside it.
The directory layout here mirrors Section 2.1 of that skill and the
`go-recipe-cli-configuration` skill (for configuration layout) and `go-conventions` (for the standard package layout); cross-reference those before deviating.

Substitute two placeholders throughout:

- `<module>` — the full module path, e.g. `github.com/acme/atlasd`.
- `<service>` — the short service name, e.g. `atlasd`.

---

## 1. Module initialization

Unlike Python (Poetry / `pyproject.toml` / virtualenvs), Go dependency management
is built into the toolchain. Start with the module and a pinned toolchain.

```bash
mkdir <service> && cd <service>
go mod init <module>
go mod edit -go=1.23

# Core stack — the same libraries the sibling build-go-* skills assume.
go get github.com/gin-gonic/gin
go get github.com/go-playground/validator/v10
go get gorm.io/gorm
go get gorm.io/driver/postgres
go get github.com/spf13/viper
go get github.com/pressly/goose/v3

# Dev / test tooling
go get github.com/stretchr/testify

# Lint + migrate + swag CLIs (installed as binaries, not module deps)
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
go install github.com/pressly/goose/v3/cmd/goose@latest
go install github.com/swaggo/swag/cmd/swag@latest
```

`slog` and `net/http` are stdlib — no dependency needed (the Go equivalent of the
Python `logger.py` module and uvicorn).

---

## 2. Directory tree

Create the exact layout below. `internal/` is compiler-enforced private (no other
module can import it) — the closest Go has to the Python `src/` package boundary.
`pkg/` holds code intended for reuse by other services.

```bash
mkdir -p \
  cmd/<service> \
  internal/config \
  internal/server \
  internal/handler/health \
  internal/domain \
  internal/app \
  pkg \
  configs \
  migrations \
  deployments \
  api
```

Resulting tree:

```
<service>/
├── go.mod
├── go.sum
├── Makefile
├── .golangci.yml
├── .dockerignore
├── README.md
│
├── cmd/
│   └── <service>/
│       └── main.go            # entry point only — wires deps, starts server
│
├── internal/                  # private to this module (compiler-enforced)
│   ├── config/
│   │   └── config.go          # Config → ConfigDAO → ConfigSvc; flags > env > file > defaults
│   ├── server/
│   │   ├── server.go          # Gin router + http.Server + graceful shutdown
│   │   └── logger.go          # slog setup (json prod / text dev)
│   ├── handler/
│   │   └── health/
│   │       └── handler.go     # first endpoint: GET /<service>/api/v1/health
│   ├── domain/                # model/DAO/service and focused repository adapters
│   └── app/                   # application services — Execute() orchestrators
│
├── pkg/                       # exported, reusable packages (no internal deps)
│
├── configs/
│   └── config.toml            # default config, overridden by env/flags
│
├── migrations/                # goose versioned SQL (Alembic equivalent)
│   └── 00001_create_extensions.sql
│
├── deployments/
│   ├── Dockerfile
│   ├── docker-compose.yml     # postgres + redis for local dev
│   └── .env.example
│
└── api/
    └── openapi/               # swag-generated docs land here
```

> **Translation note.** No `__init__.py` files — Go packages are directory-based.
> No `conftest.py` — Go tests live in `_test.go` files beside the code. No
> `PYTHONPATH` — the module path resolves imports. The Python `config/` +
> `connectors/` + `src/models/base.py` collapse into `internal/config` and
> `internal/server` plus GORM's built-in base model.

---

## 3. Configuration and composition (canonical owners)

Read go-recipe-cli-configuration in full. Per binary, Config is the resolved noun,
ConfigDAO is source-shaped transient data and ConfigSvc owns parsing/resolution in
one config.go. One pflag registry and config-only viper resolution own flags > env
> file > defaults; explicit false/zero are not missing values. No parsing in main,
no package-global config singleton, no duplicate meta-flag scan.

## 4. Logger and dependencies

The composition service constructs slog from a named LoggerDAO (output, level,
format), then injects the resulting logger. Do not set a mutable global default.
Invalid levels/formats return a wrapped construction error. Required collaborators
arrive in named construction DAOs, optional behavior in functional options.

## 5. Bootstrap and graceful shutdown

Read go-build-lifecycle for typed runtime assembly and the compilable supervision
example. Construct storage, migrations and transport in ordered named steps, register
rollback immediately, and publish the resolved runtime only after invariants hold.
HTTP/GORM are optional choices in this scaffold, not mandatory Go dependencies.
The lifecycle owner launches listeners/loops, cancels on termination, stops ingress,
drains owned work, waits and closes stores in dependency order. Return shutdown
errors; never discard them or hide a timed-out drain.

## 6. Entry point

cmd/main delegates to Cli using injected output/error writers. Cli handles
help/version/display and exit mapping; ConfigSvc parses all arguments, and a thin
lifecycle façade delegates start/wait/shutdown. Help/version tests prove no resources
were acquired. Exact error-line and sentinel tests mirror atlasd's useful style,
without copying its global getters or mutable daemon fields. Use named construction
DAOs at all assembly boundaries.

## 7. First health endpoint (`internal/handler/health/handler.go`)

A thin handler — bind nothing, check the DB ping, wrap the response. This is the
Go equivalent of a FastAPI `@app.get("/health")` route. Keep it thin per
`go-conventions`; richer handlers belong in `go-build-http-handlers`.

```go
// Package health exposes the service liveness/readiness endpoint.
package health

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// Register mounts the health routes on the given router group.
func Register(rg *gin.RouterGroup, db *gorm.DB) {
	h := &Handler{db: db}
	rg.GET("/health", h.Check)
}

// Handler serves health checks backed by a database connection.
type Handler struct {
	db *gorm.DB
}

// statusResponse is the health payload. Uniform shape, JSON tags match wire names.
type statusResponse struct {
	Status   string `json:"status"`
	Database string `json:"database"`
}

// Check reports service health, including database connectivity.
//
// Returns 200 with status "ok" when the database responds to a ping; 503 with
// status "degraded" otherwise.
func (h *Handler) Check(c *gin.Context) {
	dbStatus := "up"
	code := http.StatusOK
	status := "ok"

	sqlDB, err := h.db.DB()
	if err != nil || sqlDB.PingContext(c.Request.Context()) != nil {
		dbStatus = "down"
		code = http.StatusServiceUnavailable
		status = "degraded"
	}

	c.JSON(code, statusResponse{Status: status, Database: dbStatus})
}
```

> The full uniform `SuccessResponse[T]` / `FailureResponse` envelope from
> `go-conventions` applies to real business endpoints. The health
> check is a deliberate, documented exception — probes expect a bare status body.

---

## 8. Migrations — goose (`migrations/`)

goose is the Go equivalent of Alembic: versioned, timestamp/sequence-ordered SQL
with explicit up/down. Mirror the Python scaffold's rule — the **first migration
always enables extensions**.

Initialize and create migrations:

```bash
# First migration: create extensions (mirrors the Alembic create_extensions rev)
goose -dir migrations create create_extensions sql

# Apply / roll back against the DSN
goose -dir migrations postgres "$<SERVICE>_DB_DSN" up
goose -dir migrations postgres "$<SERVICE>_DB_DSN" down
goose -dir migrations postgres "$<SERVICE>_DB_DSN" status
```

`migrations/00001_create_extensions.sql`:

```sql
-- +goose Up
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- +goose Down
DROP EXTENSION IF EXISTS "vector";
DROP EXTENSION IF EXISTS "uuid-ossp";
```

> **Translation note.** Alembic's `env.py` autogenerates migrations from
> SQLAlchemy metadata. goose is plain SQL by default — you write the DDL. This is
> intentional in the Go stack: migrations are reviewed as SQL, and GORM
> `AutoMigrate` is reserved for local dev only, never production.

---

## 9. `.golangci.yml`

The Go analog of black + autoflake + flake8 in one config. Keep it strict from
day one so the codebase never accrues lint debt.

```yaml
run:
  timeout: 5m
  tests: true

linters:
  enable:
    - errcheck      # unchecked errors — the conventions' "no swallowed error" rule
    - govet
    - staticcheck
    - gosimple
    - ineffassign
    - unused
    - misspell
    - revive        # style: exported-symbol docs, naming
    - gofmt
    - goimports

linters-settings:
  revive:
    rules:
      - name: exported
        arguments: ["checkPrivateReceivers"]
  goimports:
    local-prefixes: <module>

issues:
  exclude-rules:
    - path: _test\.go
      linters:
        - errcheck
```

---

## 10. Dockerfile + docker-compose (`deployments/`)

`deployments/Dockerfile` — multi-stage, distroless-style final image:

```dockerfile
# ---- build stage ----
FROM golang:1.23 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/<service> ./cmd/<service>

# ---- runtime stage ----
FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/<service> /app/<service>
COPY --from=build /src/configs /app/configs
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/app/<service>"]
```

`deployments/docker-compose.yml` — postgres (pgvector) + redis for local dev
(the Go equivalent of the Python `docker-compose.dev.yml`):

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: <service>
      POSTGRES_PASSWORD: <service>
      POSTGRES_DB: <service>
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U <service>"]
      interval: 2s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7.4
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

`deployments/.env.example` — the Go analog of `local.env`. No `PYTHONPATH`; env
vars carry the `<SERVICE>_` prefix that viper reads:

```env
<SERVICE>_ENV=development
<SERVICE>_HTTP_PORT=8080
<SERVICE>_DB_DSN=postgres://<service>:<service>@localhost:5432/<service>?sslmode=disable
<SERVICE>_LOG_FORMAT=text
<SERVICE>_LOG_LEVEL=debug
REDIS_URL=redis://localhost:6379/0
```

`.dockerignore`:

```
.git
*_test.go
/api/openapi
/deployments/.env
```

---

## 11. Makefile

The Go analog of the Python `Makefile` + `launch_dev.sh`. Every independently
runnable action gets a `.PHONY` target.

```makefile
.PHONY: run test lint fmt migrate-up migrate-down migrate-status swag up down tidy build

MODULE   := <module>
SERVICE  := <service>
DB_DSN   ?= postgres://$(SERVICE):$(SERVICE)@localhost:5432/$(SERVICE)?sslmode=disable

run:                       ## Run the service locally
	go run ./cmd/$(SERVICE)

build:                     ## Build the binary
	CGO_ENABLED=0 go build -o bin/$(SERVICE) ./cmd/$(SERVICE)

test:                      ## Run all tests
	go test ./... -race -count=1

lint:                      ## Run golangci-lint
	golangci-lint run ./...

fmt:                       ## Format + fix imports
	gofmt -w .
	goimports -local $(MODULE) -w .

tidy:                      ## Tidy module deps
	go mod tidy

migrate-up:                ## Apply all pending migrations
	goose -dir migrations postgres "$(DB_DSN)" up

migrate-down:              ## Roll back the last migration
	goose -dir migrations postgres "$(DB_DSN)" down

migrate-status:            ## Show migration status
	goose -dir migrations postgres "$(DB_DSN)" status

swag:                      ## Regenerate OpenAPI docs from swag annotations
	swag init -g cmd/$(SERVICE)/main.go -o api/openapi

up:                        ## Start local infra (postgres + redis)
	docker compose -f deployments/docker-compose.yml up -d

down:                      ## Stop local infra
	docker compose -f deployments/docker-compose.yml down
```

---

## 12. Verify the scaffold compiles

Before declaring the scaffold done, prove it builds and the module graph resolves:

```bash
go mod tidy
go build ./...
go vet ./...
golangci-lint run ./...   # if the binary is installed
```

Then smoke-test the health endpoint:

```bash
make up            # start postgres + redis
make migrate-up    # enable extensions
make run &         # start the service
curl -s localhost:8080/<service>/api/v1/health
# => data contains the health payload inside the canonical API envelope
```

---

## Cross-references

- [`go-conventions`](../go-conventions/SKILL.md) — naming,
  godoc, declarative structure, envelope, error-wrapping. Governs everything you
  write into this skeleton.
- `go-recipe-cli-configuration` — the canonical configuration structure, and app
  architecture this tree conforms to.
- `go-build-http-handlers` — for real handlers beyond the health stub.
- `go-build-application-services` — the `Execute()` orchestrator pattern for
  `internal/app`.
- `go-build-domain-features` — the model/DAO/service and repository ownership pattern for `internal/domain`.
- `go-recipe-database-migrations` — deeper goose migration conventions.

---

## Checklist

Verify before declaring scaffolding complete:

- [ ] `go mod init <module>` done; toolchain pinned via `go mod edit -go=1.23`.
- [ ] Directory tree matches §2 — `cmd/`, `internal/`, `pkg/`, `configs/`,
      `migrations/`, `deployments/`, `api/`.
- [ ] `internal/config/config.go` returns a **typed** `Config` (no stringly-typed
      `cfg("KEY")` lookups) via ConfigSvc with flags > env > file > defaults precedence.
- [ ] Logger uses stdlib `slog` — JSON in prod, text in dev.
- [ ] `main.go` is wiring only (< ~30 lines of body); no business logic.
- [ ] `server.go` owns the `http.Server` and shuts down gracefully on
      SIGINT/SIGTERM with a bounded drain window.
- [ ] Routes are mounted under the **service namespace** (`/<service>/api/v1`),
      never a bare `/api/v1`.
- [ ] First migration `00001_create_extensions.sql` enables `uuid-ossp` +
      `vector`, with a `-- +goose Down`.
- [ ] `.golangci.yml` present with `errcheck`, `staticcheck`, `revive` enabled.
- [ ] `deployments/` has Dockerfile (multi-stage), docker-compose (postgres +
      redis), and `.env.example` with `<SERVICE>_`-prefixed vars.
- [ ] Makefile has `run`, `build`, `test`, `lint`, `fmt`, `migrate-*`, `swag`,
      `up`, `down`, `tidy` — all in `.PHONY`.
- [ ] `go build ./...`, `go vet ./...`, and `golangci-lint run ./...` all pass.
- [ ] `curl /<service>/api/v1/health` returns the canonical envelope with typed health data.
