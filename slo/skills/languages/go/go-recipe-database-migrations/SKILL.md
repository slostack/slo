---
name: go-recipe-database-migrations
description: 'Go scoped recipe (testcontainers): Versioned SQL database migrations in Go using goose (github.com/pressly/goose/v3).
  Directory layout, up/down SQL with -- +goose annotations, embedded migrations via embed.FS run at app
  startup, CLI + Makefile targets, versioning, and why migrations (not GORM AutoMigrate) are the source
  of truth in production.'
when_to_use: Only for the named project stack and component. Use when setting up database migrations for
  a Go service, adding a new migration, wiring migrations to run at startup, or deciding how goose migrations
  relate to GORM models. The Go equivalent of Alembic setup.
group: languages
kind: skill
---

# Go Database Migrations (goose)

## Skill summary

- **Name:** `go-recipe-database-migrations`
- **Description:** Versioned SQL database migrations in Go using goose
  (`github.com/pressly/goose/v3`). Directory layout, up/down SQL with `-- +goose`
  annotations, embedded migrations via `embed.FS` run at app startup, CLI + Makefile
  targets, versioning, and why migrations (not GORM `AutoMigrate`) are the source of
  truth in production.
- **When to use:** Setting up migrations for a Go service, adding a migration, wiring
  migrations to run at startup, or reconciling goose migrations with GORM models.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up goose migrations for this Go service."
- "Add a migration to create the users table."
- "How do I run migrations at app startup?"
- "Should I use GORM AutoMigrate in production?"
- "Embed the migrations in the binary with embed.FS."
- "Add Makefile targets for creating and running migrations."
- "How do goose migrations relate to my GORM models?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill is the Go equivalent of the Alembic setup guide. goose replaces Alembic:
both are lightweight, version-controlled schema migration tools. The key differences
you must internalise:

| Alembic (Python) | goose (Go) |
|---|---|
| `alembic revision -m "..."` (Python migration files) | `goose create name sql` (raw SQL files) |
| `upgrade()` / `downgrade()` functions | `-- +goose Up` / `-- +goose Down` sections |
| `--autogenerate` diffs models against DB | **No autogenerate** — you write the SQL by hand |
| `alembic.ini` + `env.py` | flags/env vars, or a small Go runner |
| `alembic_version` table | `goose_db_version` table |

The single biggest principle carried over: **migrations are the source of truth for
the schema, not the ORM.** In Alembic, models feed autogenerate but the migration
file is authoritative. In Go with GORM, `AutoMigrate` is a dev convenience only — in
production the goose migrations are authoritative and `AutoMigrate` is **not** run.
See [Section 6](#section-6--migrations-vs-gorm-automigrate).

Defer to `go-conventions` for naming, godoc, error-wrapping, and function
structure rules on any Go you write here. Cross-references:
- `go-recipe-bootstrap-project-scaffolding` — where the `migrations/` directory and the
  startup runner sit in the standard layout.
- `go-build-domain-features` — the GORM model structs whose schema these migrations
  create; ubiquitous language (column name = struct field = JSON tag) applies here too.

---

## Section 1 — Install goose

Two things get installed: the **CLI** (for creating/running migrations during
development) and the **library** (imported by the app to embed and run migrations at
startup).

```bash
# CLI — pin the version; do not install @latest into a shared repo unpinned
go install github.com/pressly/goose/v3/cmd/goose@v3.24.1

# Library dependency (added when you first import it in the runner)
go get github.com/pressly/goose/v3
```

Record the pinned CLI version in the `Makefile` (Section 5) so every developer and CI
runner uses the same one. Unpinned tool versions are the migration equivalent of a
floating dependency — a blocker.

---

## Section 2 — Directory Layout

Migrations live in a single flat directory of numbered `.sql` files. This is the
goose analog of `db/versions/`. In the standard layout from
`go-recipe-bootstrap-project-scaffolding`:

```
<service>/
├── cmd/
│   └── server/
│       └── main.go
├── internal/
│   ├── database/
│   │   ├── migrate.go          # embedded-migrations runner (Section 4)
│   │   └── migrations/         # the migration SQL files
│   │       ├── embed.go        # //go:embed directive
│   │       ├── 00001_create_extensions.sql
│   │       ├── 00002_create_users.sql
│   │       └── 00003_add_users_status_index.sql
│   └── domain/
│       └── user/
│           └── model.go        # GORM model — schema mirrors migration 00002
├── Makefile
└── go.mod
```

Rules:
- **One directory, flat.** Do not nest migrations by domain — goose orders the whole
  set by version number and cross-table changes (foreign keys) must be globally
  ordered.
- **Sequential numeric versions** (`00001`, `00002`, …) — see
  [Section 7](#section-7--versioning-sequential-vs-timestamp). Zero-pad to a fixed
  width so lexical and numeric ordering agree.
- The `migrations/` directory sits under `internal/database/` so it can be embedded
  by the runner in the same package tree.

---

## Section 3 — Creating a Migration & the SQL Format

### 3.1 Create the file

Always create migrations with the CLI so the version prefix is generated correctly.
Use the `sql` type (never `go` — keep migrations as plain SQL for reviewability):

```bash
# Sequential numbering (recommended — see Section 7)
goose -s -dir internal/database/migrations create create_users sql

# Produces: internal/database/migrations/00002_create_users.sql
```

The `-s` flag forces sequential (`00002`) numbering instead of the default
timestamp. Name the migration in `snake_case`, describing the change
(`create_users`, `add_users_status_index`, `drop_legacy_reports`).

### 3.2 The up/down annotation format

Every goose SQL file has an `Up` and a `Down` section marked with `-- +goose`
annotations. `Up` applies the change; `Down` reverses it — the exact analog of
Alembic's `upgrade()` / `downgrade()`.

```sql
-- 00002_create_users.sql

-- +goose Up
-- +goose StatementBegin
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email          TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL DEFAULT 'PENDING',
    question_limit INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE users;
-- +goose StatementEnd
```

Key rules for the SQL format:

- **`-- +goose Up` and `-- +goose Down` are mandatory** section markers. Everything
  between `Up` and `Down` runs on migrate-up; everything after `Down` runs on rollback.
- **Wrap each multi-statement or dollar-quoted body in `StatementBegin`/`StatementEnd`.**
  goose splits statements on `;` by default; a function body, a `DO $$ ... $$` block,
  or any statement containing semicolons will be split incorrectly unless bracketed.
  Simple single-line statements do not strictly need it, but bracketing is the safe
  default and keeps diffs uniform.
- **Column names are the ubiquitous-language authority.** `question_limit` here is the
  same name used by the GORM struct field tag and the JSON tag downstream — never
  introduce a synonym (see `go-conventions` and
  `go-build-domain-features`).
- **`Down` must actually reverse `Up`.** A `Down` that is empty or wrong makes
  rollback a lie. The one accepted exception is shared, externally-owned objects
  (extensions) — see the next example.

### 3.3 Extensions migration (mirrors the Alembic first-migration)

The Alembic guide's first migration enabled `uuid-ossp` and `vector`. The goose
equivalent:

```sql
-- 00001_create_extensions.sql

-- +goose Up
-- +goose StatementBegin
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
-- Intentionally empty: extensions may be shared with other schemas/apps,
-- so we never drop them on rollback.
SELECT 1;
-- +goose StatementEnd
```

Note (carried from the Alembic gotcha): the `vector` (pgvector) extension requires
**superuser** privileges. If the app's DB role is not a superuser, create extensions
during database provisioning (as the `postgres` role) rather than in an app-run
migration, and drop this migration to a no-op that only verifies presence.

### 3.4 Non-transactional migrations

Some Postgres statements cannot run inside a transaction (e.g.
`CREATE INDEX CONCURRENTLY`). goose runs each migration in a transaction by default;
disable it with `-- +goose NO TRANSACTION` at the top of the file:

```sql
-- 00003_add_users_status_index.sql

-- +goose NO TRANSACTION

-- +goose Up
CREATE INDEX CONCURRENTLY idx_users_status ON users (status);

-- +goose Down
DROP INDEX CONCURRENTLY idx_users_status;
```

---

## Section 4 — Embedded Migrations Runner (run at startup)

This is the most important Go-specific piece and has no direct Alembic parallel.
Instead of shipping a `db/versions/` directory alongside the deployed app, embed the
migration files into the binary with `embed.FS` and apply them on startup. A single
self-contained binary migrates its own database — no separate migration step, no
files to copy to production.

### 4.1 Embed the migration files

```go
// internal/database/migrations/embed.go

// Package migrations embeds the versioned SQL migration files so they can be
// applied from the compiled binary without shipping loose .sql files.
package migrations

import "embed"

// FS holds every .sql migration file, embedded at build time.
//
//go:embed *.sql
var FS embed.FS
```

### 4.2 The runner

```go
// internal/database/migrate.go

// Package database provides connection setup and migration execution.
package database

import (
	"database/sql"
	"fmt"

	"github.com/pressly/goose/v3"

	"github.com/example/service/internal/database/migrations"
)

// dialect is the goose SQL dialect for this service's database.
const dialect = "postgres"

// Migrate applies all pending migrations embedded in the binary.
//
// It runs against the supplied *sql.DB (a plain database/sql handle, obtained
// from the pgx stdlib driver or GORM's underlying DB). Returns an error if any
// migration fails; the database is left at the last successfully applied version.
func Migrate(db *sql.DB) error {
	goose.SetBaseFS(migrations.FS)

	if err := goose.SetDialect(dialect); err != nil {
		return fmt.Errorf("setting goose dialect %q: %w", dialect, err)
	}

	if err := goose.Up(db, "."); err != nil {
		return fmt.Errorf("applying migrations: %w", err)
	}

	return nil
}

// MigrateDown rolls back the most recently applied migration.
//
// Intended for local development and tests only. Production rollbacks should be
// deliberate and reviewed, not automatic.
func MigrateDown(db *sql.DB) error {
	goose.SetBaseFS(migrations.FS)
	if err := goose.SetDialect(dialect); err != nil {
		return fmt.Errorf("setting goose dialect %q: %w", dialect, err)
	}
	if err := goose.Down(db, "."); err != nil {
		return fmt.Errorf("rolling back migration: %w", err)
	}
	return nil
}
```

`goose.SetBaseFS(migrations.FS)` points goose at the embedded filesystem instead of
disk; `"."` is the directory *inside* that FS (the files are embedded at the FS root).

### 4.3 Getting a `*sql.DB` from GORM

The runner takes a stdlib `*sql.DB`. When the app uses GORM, extract the underlying
handle rather than opening a second connection:

```go
// GORM is opened for the app; goose needs the raw *sql.DB underneath it.
gormDB, err := gorm.Open(postgres.Open(cfg.DatabaseURL), &gorm.Config{})
if err != nil {
	return fmt.Errorf("opening gorm connection: %w", err)
}

sqlDB, err := gormDB.DB()
if err != nil {
	return fmt.Errorf("extracting sql.DB from gorm: %w", err)
}
```

### 4.4 Call it at startup

Keep `main.go` thin (per `go-conventions`) — it wires the DB and
calls `Migrate` before serving traffic:

```go
// cmd/server/main.go (excerpt)

func run(ctx context.Context, cfg *config.AppConfig) error {
	sqlDB, err := database.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("connecting to database: %w", err)
	}
	defer sqlDB.Close()

	if err := database.Migrate(sqlDB); err != nil {
		return fmt.Errorf("running migrations: %w", err) // fail fast — do not serve on a bad schema
	}

	slog.Info("migrations applied; starting server", "addr", cfg.Addr)
	return startServer(ctx, cfg, sqlDB)
}
```

**Fail fast:** if migrations error, the process must exit non-zero and never start
serving. A server running against a half-migrated schema is worse than a server that
refuses to boot.

> Concurrency note: goose takes an advisory lock per run, so multiple replicas
> starting simultaneously will not race each other applying the same migration. Still
> prefer a controlled rollout (or a dedicated migration Job in Kubernetes) for large,
> long-running migrations rather than relying on N replicas contending on startup.

---

## Section 5 — Makefile Targets & CLI Commands

The CLI is for development; the embedded runner is for production. Provide Make
targets that wrap the CLI with the right `-dir` and connection string so no one
memorises flags. Mirror the Alembic command table.

```makefile
# Makefile

GOOSE            := go run github.com/pressly/goose/v3/cmd/goose@v3.24.1
MIGRATIONS_DIR   := internal/database/migrations
GOOSE_DRIVER     := postgres
# DATABASE_URL is loaded from the environment (viper/.env); never hardcode creds.
GOOSE_DBSTRING   := $(DATABASE_URL)

export GOOSE_DRIVER
export GOOSE_DBSTRING

.PHONY: migrate-create migrate-up migrate-down migrate-status migrate-reset migrate-version

## Create a new sequential SQL migration:  make migrate-create name=create_users
migrate-create:
	$(GOOSE) -s -dir $(MIGRATIONS_DIR) create $(name) sql

## Apply all pending migrations
migrate-up:
	$(GOOSE) -dir $(MIGRATIONS_DIR) up

## Roll back the most recent migration
migrate-down:
	$(GOOSE) -dir $(MIGRATIONS_DIR) down

## Show applied/pending status of every migration
migrate-status:
	$(GOOSE) -dir $(MIGRATIONS_DIR) status

## Print the current DB schema version
migrate-version:
	$(GOOSE) -dir $(MIGRATIONS_DIR) version

## Roll back every migration (DEV ONLY — destroys schema)
migrate-reset:
	$(GOOSE) -dir $(MIGRATIONS_DIR) reset
```

Command mapping from the Alembic guide:

| Alembic | goose Make target | goose CLI |
|---|---|---|
| `alembic revision -m "x"` | `make migrate-create name=x` | `goose ... create x sql` |
| `alembic upgrade head` | `make migrate-up` | `goose ... up` |
| `alembic upgrade +1` | — | `goose ... up-by-one` |
| `alembic downgrade -1` | `make migrate-down` | `goose ... down` |
| `alembic downgrade base` | `make migrate-reset` | `goose ... reset` |
| `alembic current` | `make migrate-version` | `goose ... version` |
| `alembic history` | `make migrate-status` | `goose ... status` |
| `alembic revision --autogenerate` | *(no equivalent — write SQL by hand)* | — |

Environment-specific runs (dev vs test) are handled by loading the right env file
(viper / direnv) before invoking the target, so `DATABASE_URL` points at the correct
database — the same discipline as the Alembic `loadenv environments/*.env` step.

---

## Section 6 — Migrations vs GORM AutoMigrate

This is the central design rule and the direct translation of the Alembic principle
"the migration file is the source of truth."

**Rule: goose migrations are the source of truth for the production schema.
`gorm.AutoMigrate` is NOT used in production.**

Why `AutoMigrate` is a production anti-pattern:
- It only ever **adds** columns/indexes/tables — it never drops or renames, never
  changes a type, never backfills. Your schema silently drifts from your models.
- It is not versioned. There is no `goose_db_version` equivalent, no history, no
  reviewable diff, no deterministic rollback.
- It runs implicit DDL inferred from struct tags at runtime — invisible in code
  review and impossible to reason about across deploys.

```go
// Bad — AutoMigrate as the production schema mechanism
func main() {
	db, _ := gorm.Open(postgres.Open(url), &gorm.Config{})
	db.AutoMigrate(&user.User{}, &order.Order{}) // silent, unversioned, additive-only — blocker
	startServer(db)
}

// Good — versioned goose migrations are authoritative; models mirror them
func run(ctx context.Context, cfg *config.AppConfig) error {
	sqlDB, err := database.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("connecting: %w", err)
	}
	if err := database.Migrate(sqlDB); err != nil { // goose Up — the only DDL path
		return fmt.Errorf("migrating: %w", err)
	}
	return startServer(ctx, cfg, sqlDB)
}
```

How the two relate (the workflow — the Go analog of Alembic's model → autogenerate →
review loop, but **manual** because goose has no autogenerate):

1. Add or change the GORM model struct in `internal/domain/<name>/model.go` per
   `go-build-domain-features`.
2. **Hand-write** the matching migration SQL (`make migrate-create name=...`). The
   column names, types, nullability, and defaults must match the struct tags exactly.
3. Apply and verify (`make migrate-up`, then inspect the schema).
4. Column name in the migration = struct field name = `gorm` tag = `json` tag. One
   concept, one name (ubiquitous language, `go-conventions`).

Where `AutoMigrate` *is* acceptable: throwaway local scratch databases and unit-test
fixtures where you want a schema quickly and correctness across deploys is irrelevant.
Even there, prefer running the real goose migrations against a testcontainers
Postgres so tests exercise the same schema production uses.

Example model that mirrors migration `00002_create_users.sql`:

```go
// internal/domain/user/model.go

// User is the core domain entity. Column names, types, and defaults are the
// mechanical mirror of migration 00002_create_users.sql — the migration is
// authoritative; this struct follows it, never the reverse.
type User struct {
	ID            string    `gorm:"column:id;type:uuid;primaryKey;default:uuid_generate_v4()" json:"id"`
	Email         string    `gorm:"column:email;not null;uniqueIndex"                        json:"email"`
	Status        string    `gorm:"column:status;not null;default:PENDING"                   json:"status"`
	QuestionLimit int       `gorm:"column:question_limit;not null;default:0"                 json:"question_limit"`
	CreatedAt     time.Time `gorm:"column:created_at;not null;default:now()"                 json:"created_at"`
	UpdatedAt     time.Time `gorm:"column:updated_at;not null;default:now()"                 json:"updated_at"`
}

// TableName pins the table name so it matches the migration exactly, rather than
// relying on GORM's pluralisation inference.
func (User) TableName() string { return "users" }
```

---

## Section 7 — Versioning: Sequential vs Timestamp

goose supports two version schemes, chosen at create time:

- **Sequential** (`-s`): `00001_`, `00002_`, … Recommended for single-team,
  single-trunk repos. Ordering is obvious and the numbers read like a changelog. The
  cost is merge conflicts on the number when two branches both add a migration —
  which is a *feature*: it forces you to consciously re-order concurrent schema
  changes rather than letting timestamps silently interleave them.
- **Timestamp** (default): `20260706143012_`. Avoids number-collision merge conflicts,
  useful for large teams with many concurrent branches. The cost is that "which ran
  first" is less legible and two migrations authored close together can apply in a
  surprising order.

Pick one scheme per repo and never mix. This skill defaults to **sequential** to
match the reviewable, changelog-like ordering of Alembic revision chains.

goose tracks applied versions in a `goose_db_version` table (the analog of Alembic's
`alembic_version`). Never edit this table by hand; use `goose up`/`down`. To inspect:

```sql
SELECT version_id, is_applied, tstamp FROM goose_db_version ORDER BY id;
```

---

## Section 8 — Verifying a Migration

After applying, verify the schema landed as intended (the goose analog of the
Alembic `psql -c "SELECT extname FROM pg_extension"` verification step):

```bash
make migrate-status          # every migration shows "Applied"
make migrate-version         # prints the current version id

# Inspect the actual schema
psql "$DATABASE_URL" -c "\d+ users"
psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension;"
```

For automated confidence, add a test that spins up a throwaway Postgres via
`testcontainers-go`, runs `database.Migrate`, and asserts key tables/columns exist —
this also proves `Down` reverses `Up` if you migrate up then down then up again.

---

## Section 9 — Troubleshooting

Translated from the Alembic troubleshooting section:

| Symptom | Cause | Fix |
|---|---|---|
| `goose: no migrations to run` when you expect one | New file not saved with `.sql` extension, or wrong `-dir` | Confirm the file is in `MIGRATIONS_DIR` and re-run `make migrate-status`. |
| Migration change not picked up by the binary | `embed.FS` snapshot is stale — you rebuilt nothing | Rebuild the binary; `//go:embed` captures files at compile time, not runtime. |
| `permission denied to create extension "vector"` | App DB role is not superuser | Create the extension during DB provisioning as `postgres`; make the extension migration a no-op. (Same gotcha as Alembic.) |
| `pq: syntax error` inside a function/DO block | Missing `StatementBegin`/`StatementEnd` — goose split on an inner `;` | Wrap the body in the statement annotations. |
| `CREATE INDEX CONCURRENTLY cannot run inside a transaction block` | goose wraps migrations in a transaction | Add `-- +goose NO TRANSACTION` at the top of the file. |
| `dial tcp ... connection refused` | Postgres not running / wrong `DATABASE_URL` | Start the DB container and confirm the env var is loaded. |
| Replicas racing on startup migration | Multiple pods calling `Migrate()` at once | goose's advisory lock serialises them; for big migrations use a dedicated migration Job instead. |

---

## Checklist

Run through before merging any migration change. Each unchecked item is a blocker.

### Files & layout
- [ ] Migration created via `goose ... create` (correct version prefix), not by hand.
- [ ] File lives in the single flat `internal/database/migrations/` directory.
- [ ] Version scheme (sequential vs timestamp) matches the rest of the repo — no mixing.
- [ ] Filename is descriptive `snake_case` (`create_users`, `add_users_status_index`).

### SQL format
- [ ] Both `-- +goose Up` and `-- +goose Down` sections present.
- [ ] Multi-statement / dollar-quoted bodies wrapped in `StatementBegin`/`StatementEnd`.
- [ ] `Down` genuinely reverses `Up` (or is a documented, justified no-op).
- [ ] `-- +goose NO TRANSACTION` added for `CONCURRENTLY` / non-transactional DDL.

### Schema authority
- [ ] `gorm.AutoMigrate` is **not** used in the production startup path.
- [ ] Migration is the source of truth; the GORM model mirrors it, not the reverse.
- [ ] Column name = struct field = `gorm` tag = `json` tag (one concept, one name).

### Runner & wiring
- [ ] Migrations embedded via `//go:embed *.sql` and `goose.SetBaseFS`.
- [ ] `Migrate()` runs at startup and the process exits non-zero on failure.
- [ ] `main.go` stays thin — it calls `Migrate`, it doesn't contain migration logic.

### Tooling
- [ ] Make targets (`migrate-create/up/down/status/version`) present and use env-sourced
      `DATABASE_URL` — no hardcoded credentials.
- [ ] goose CLI version pinned (not `@latest`) in the Makefile.
- [ ] Applied result verified (`make migrate-status` + schema inspection).
