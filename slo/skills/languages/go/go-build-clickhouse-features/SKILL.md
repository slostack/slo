---
name: go-build-clickhouse-features
description: "Go scoped recipe (testcontainers, ClickHouse): Go patterns for ClickHouse features using\
  \ the official github.com/ClickHouse/clickhouse-go/v2 driver \u2014 connection/pool bootstrap, typed\
  \ row structs and scanning, batch inserts (the high-throughput path), parameterized queries, async inserts,\
  \ ClickHouse migrations, S3 table functions, and an analytical DAO mirroring the GORM DAO discipline."
when_to_use: Only for the named project stack and component. Use whenever writing or reviewing Go code
  that connects to ClickHouse, inserts rows in bulk, runs analytical SELECTs, defines ClickHouse tables/migrations,
  or reads/writes S3 via ClickHouse table functions.
group: languages
kind: skill
---

# Building ClickHouse Features (Go)

## Skill summary

- **Name:** `go-build-clickhouse-features`
- **Description:** Go patterns for ClickHouse features on the official
  `github.com/ClickHouse/clickhouse-go/v2` driver — connection bootstrap, typed row
  structs + scanning, batch inserts, parameterized queries, async inserts, migrations,
  S3 table functions, and an analytical DAO mirroring the GORM DAO discipline.
- **When to use:** Any Go code touching ClickHouse — clients, bulk inserts,
  analytical queries, table/migration definitions, or S3 ingestion/export.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up a ClickHouse connection pool in Go."
- "Write a batch insert for millions of decision rows into ClickHouse."
- "Add a ClickHouse migration for a new ReplicatedMergeTree table."
- "Build a DAO to run an analytical query and scan into typed structs."
- "Ingest a CSV from S3 into ClickHouse with the s3() table function."
- "Use async inserts for our high-volume event stream."
- "Review this ClickHouse DAO for convention violations."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This is the Go translation of the Python `build-clickhouse-features` prompt. The
Python codebase used the async `asynch` driver with a dual-client pattern, Pydantic
DAOs, and service-based migrations. In Go we use the **official
`github.com/ClickHouse/clickhouse-go/v2` driver**, typed row structs, and
**goose**-managed migrations.

Defer to **`go-conventions`** for all naming, godoc, declarative
structure, error-wrapping, and ubiquitous-language rules — they apply verbatim here.
Cross-reference **`go-build-domain-features`** for the DAO/repository discipline this
skill mirrors, and **`go-recipe-database-migrations`** for goose mechanics (this skill
covers only the ClickHouse-specific dialect concerns).

Key idiom translations, stated up front:

| Python (source) | Go (this skill) |
|---|---|
| `asynch` async client, `await` | `clickhouse-go/v2` `driver.Conn`, `context.Context` |
| Dual `CHClient` / `CHReadOnlyClient` classes | Two `driver.Conn` values (RW + RO) held on a `Client` struct |
| `@clickhouse_retry` decorator | Driver-level `MaxOpenConns` + explicit retry wrapper |
| `fetchall_dict` → `List[Dict]` | Typed `[]RowStruct` via `conn.Select` / `rows.ScanStruct` |
| Pydantic DAO (`clickhouse_` title) | DAO struct wrapping `driver.Conn`, `ch:` struct tags |
| Service `migrate()` methods + `ClickHouseMigrator` | goose versioned SQL migrations |
| `params={"x": v}` named substitution | `clickhouse.Named("x", v)` bind parameters |

---

## Section 1 — Connection & Pool Bootstrap

### 1.1 Two connections, one Client

ClickHouse benefits from separating read-write (DDL/DML/mutations) from read-only
(SELECT) traffic — they often point at different endpoints (a writer vs a
load-balanced replica set). In Go, hold **two `driver.Conn` values on one `Client`
struct** rather than two classes. Config comes from `viper` (see the config
conventions), never from package globals.

```go
// Package clickhouse provides the analytical-store client and DAOs.
package clickhouse

import (
	"context"
	"crypto/tls"
	"fmt"
	"time"

	ch "github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

// Config holds all ClickHouse connection settings, loaded via viper.
// Field names are the ubiquitous names used across config files and env vars.
type Config struct {
	WriteAddrs      []string      // CLICKHOUSE_WRITE_ADDRS  (host:port list)
	ReadAddrs       []string      // CLICKHOUSE_READ_ADDRS
	Database        string        // CLICKHOUSE_DATABASE
	Username        string        // CLICKHOUSE_USERNAME
	Password        string        // CLICKHOUSE_PASSWORD
	ClusterName     string        // CLICKHOUSE_CLUSTER_NAME (for ON CLUSTER DDL)
	MaxOpenConns    int           // CLICKHOUSE_MAX_OPEN_CONNS (default 10)
	MaxIdleConns    int           // CLICKHOUSE_MAX_IDLE_CONNS (default 5)
	DialTimeout     time.Duration // CLICKHOUSE_DIAL_TIMEOUT   (default 10s)
	MaxRetries      int           // CLICKHOUSE_MAX_RETRIES    (default 3)
	UseTLS          bool          // CLICKHOUSE_USE_TLS
}

// Client owns the read-write and read-only ClickHouse connections plus config.
// Writes (DDL/DML/batch inserts) use writeConn; SELECTs use readConn.
type Client struct {
	writeConn driver.Conn
	readConn  driver.Conn
	cfg       Config
}

// NewClient opens both connections and verifies each with a ping.
//
// Returns an error if either connection cannot be established. The caller owns
// the returned Client and must call Close when done.
func NewClient(ctx context.Context, cfg Config) (*Client, error) {
	writeConn, err := open(ctx, cfg, cfg.WriteAddrs)
	if err != nil {
		return nil, fmt.Errorf("opening write connection: %w", err)
	}

	readConn, err := open(ctx, cfg, cfg.ReadAddrs)
	if err != nil {
		_ = writeConn.Close()
		return nil, fmt.Errorf("opening read connection: %w", err)
	}

	return &Client{writeConn: writeConn, readConn: readConn, cfg: cfg}, nil
}

// open dials ClickHouse and pings to fail fast on a bad endpoint.
func open(ctx context.Context, cfg Config, addrs []string) (driver.Conn, error) {
	opts := &ch.Options{
		Addr: addrs,
		Auth: ch.Auth{
			Database: cfg.Database,
			Username: cfg.Username,
			Password: cfg.Password,
		},
		DialTimeout:     orDefault(cfg.DialTimeout, 10*time.Second),
		MaxOpenConns:    orDefaultInt(cfg.MaxOpenConns, 10),
		MaxIdleConns:    orDefaultInt(cfg.MaxIdleConns, 5),
		ConnMaxLifetime: time.Hour,
		Compression:     &ch.Compression{Method: ch.CompressionLZ4},
	}
	if cfg.UseTLS {
		opts.TLS = &tls.Config{}
	}

	conn, err := ch.Open(opts)
	if err != nil {
		return nil, fmt.Errorf("dialing clickhouse: %w", err)
	}
	if err := conn.Ping(ctx); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("pinging clickhouse: %w", err)
	}
	return conn, nil
}

// Close closes both underlying connections, returning the first error seen.
func (c *Client) Close() error {
	werr := c.writeConn.Close()
	rerr := c.readConn.Close()
	if werr != nil {
		return werr
	}
	return rerr
}
```

Rules:

- **Prefer the native protocol** (`ch.Open` returning `driver.Conn`) over
  `database/sql` — it gives you `ScanStruct`, native batch API, and async inserts.
  Only use the `sql.DB` wrapper (`clickhouse.OpenDB`) when a library forces
  `database/sql`.
- **Enable LZ4 compression** — ClickHouse payloads are large; compression is a
  near-free throughput win.
- `MaxOpenConns` is your effective concurrency cap. There is no per-query pool to
  tune beyond this and `MaxIdleConns`.
- `Ping` on startup so a misconfigured endpoint fails at boot, not at first query.

### 1.2 Retry wrapper for transient errors

The Python `@clickhouse_retry` decorator became an explicit helper. Retry only
**transient** errors (network, pool exhaustion) — never retry a query syntax error
or a DDL conflict.

```go
// withRetry runs fn with exponential backoff on transient ClickHouse errors.
//
// It retries up to cfg.MaxRetries times with a min(2^attempt, 5)s backoff. It
// does not retry non-transient errors (bad SQL, type mismatches).
func (c *Client) withRetry(ctx context.Context, fn func() error) error {
	maxRetries := orDefaultInt(c.cfg.MaxRetries, 3)
	var err error
	for attempt := 0; attempt <= maxRetries; attempt++ {
		err = fn()
		if err == nil || !isTransient(err) {
			return err
		}
		backoff := time.Duration(min(1<<attempt, 5)) * time.Second
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
	}
	return fmt.Errorf("exhausted %d retries: %w", maxRetries, err)
}
```

Keep `isTransient` narrow — inspect for `*ch.Exception` codes that indicate
timeouts/network, plus `context.DeadlineExceeded` and `net.Error` with `Timeout()`.

---

## Section 2 — Typed Rows & Scanning

The Pydantic-DAO-returning-dicts approach maps to **typed row structs with `ch:`
struct tags**. Never scan into `map[string]any` in production code — that is the Go
equivalent of `fetchall_dict` and loses type safety (allowed only in ad-hoc tooling
with a comment explaining why).

```go
// DecisionRow is one row of the decision_table. Field names and ch tags match
// the ClickHouse column names exactly — no synonyms (ubiquitous language).
type DecisionRow struct {
	DecisionDate  time.Time  `ch:"decision_date"`
	AccountID     string     `ch:"account_id"`
	Amount        *float64   `ch:"amount"`         // Nullable(Float64) → pointer
	PhoneFlag     *bool      `ch:"phone_flag"`     // Nullable(Bool) → pointer
	InsertedAtUTC time.Time  `ch:"inserted_at_utc"`
}
```

Rules:

- **`Nullable(T)` columns map to Go pointers** (`*float64`, `*bool`, `*string`) or
  `sql.Null*`. A non-pointer scan target for a null value errors at runtime.
- `DateTime64(3)` scans into `time.Time`; `Date32` also `time.Time` (date part).
- `Array(String)` scans into `[]string`; `Map(K,V)` into `map[K]V`.
- Use `conn.Select(ctx, &dest, query, args...)` to scan a whole result set into a
  `[]RowStruct` in one call — it is the high-level, allocation-friendly path.
- Use `conn.QueryRow(...).ScanStruct(&dest)` for a single row.

---

## Section 3 — Batch Inserts (the high-throughput path)

**This is the most important pattern in this skill.** ClickHouse is optimized for
large, infrequent inserts, not row-at-a-time DML. Never issue one `INSERT` per row.
The native batch API buffers columns client-side and flushes in one block.

```go
// InsertDecisions bulk-inserts decision rows using the native batch API.
//
// Rows are appended column-wise and flushed in a single block via Send. Returns
// an error if preparation, any append, or the flush fails.
func (d *DecisionDAO) InsertDecisions(ctx context.Context, rows []DecisionRow) error {
	if len(rows) == 0 {
		return nil
	}

	return d.client.withRetry(ctx, func() error {
		batch, err := d.client.writeConn.PrepareBatch(
			ctx,
			"INSERT INTO "+d.fullTableName(),
		)
		if err != nil {
			return fmt.Errorf("preparing batch: %w", err)
		}

		for i := range rows {
			r := rows[i]
			if err := batch.Append(
				r.DecisionDate,
				r.AccountID,
				r.Amount,
				r.PhoneFlag,
				r.InsertedAtUTC,
			); err != nil {
				_ = batch.Abort()
				return fmt.Errorf("appending row %d: %w", i, err)
			}
		}

		if err := batch.Send(); err != nil {
			return fmt.Errorf("sending batch of %d rows: %w", len(rows), err)
		}
		return nil
	})
}
```

Rules:

- **Append order must match the column order** in the `INSERT` statement (or the
  table's physical order when columns are omitted). Prefer listing columns
  explicitly: `INSERT INTO db.tbl (col_a, col_b, ...)` so an out-of-order struct
  cannot silently corrupt data.
- Call `batch.Abort()` on any append error before returning — a half-built batch
  left un-aborted leaks the acquired connection.
- **Batch size:** aim for 10k–100k rows (or a few MB) per `Send`. For unbounded
  input, chunk it and `Send` per chunk; do not accumulate millions of rows in one
  batch (memory) nor one row per batch (throughput collapse).
- `batch.Column(i).Append(colSlice)` is the columnar variant — fastest when you
  already have data laid out column-wise; prefer it for very hot paths.

```go
// Bad — row-at-a-time Exec; a throughput and connection-churn disaster
for _, r := range rows {
	err := conn.Exec(ctx,
		"INSERT INTO db.decision_table VALUES (?, ?, ?)",
		r.DecisionDate, r.AccountID, r.Amount)
	if err != nil { return err }
}

// Good — one PrepareBatch, N Appends, one Send (see InsertDecisions above)
```

---

## Section 4 — Async Inserts

For high-frequency, small inserts (event streams, telemetry) where you can tolerate
a brief buffering window, enable **server-side async inserts** instead of batching
client-side. ClickHouse buffers on the server and flushes when a size/time threshold
is hit.

```go
// InsertEventAsync enqueues one event using ClickHouse async inserts.
//
// The insert returns once the server has buffered the row (wait_for_async_insert=1
// waits for the server flush; set to 0 for fire-and-forget with at-least-once
// buffering). Use for high-frequency small inserts, not bulk loads.
func (d *EventDAO) InsertEventAsync(ctx context.Context, ev EventRow) error {
	ctx = clickhouse.Context(ctx, clickhouse.WithSettings(clickhouse.Settings{
		"async_insert":          1,
		"wait_for_async_insert": 1, // 0 = fire-and-forget; 1 = wait for flush ack
	}))

	err := d.client.writeConn.Exec(ctx,
		"INSERT INTO "+d.fullTableName()+" (event_id, event_type, occurred_at_utc) VALUES (?, ?, ?)",
		ev.EventID, ev.EventType, ev.OccurredAtUTC,
	)
	if err != nil {
		return fmt.Errorf("async insert event %s: %w", ev.EventID, err)
	}
	return nil
}
```

Rules:

- **Async insert vs batch is a decision, not a default.** Batch = you control
  buffering, best for bulk ETL. Async = the server buffers, best for many
  concurrent small writers.
- `wait_for_async_insert=1` gives you a durability ack at some latency cost. Use
  `0` only when at-least-once with a small loss window on crash is acceptable.
- Do not combine async inserts with tiny transactions in a hot loop expecting batch
  throughput — measure.

---

## Section 5 — Parameterized Queries

Use the driver's **named bind parameters** (`clickhouse.Named`) — the Go equivalent
of the Python `params={...}` dict. **Never string-interpolate user input** into SQL;
that is an injection blocker. Interpolation is acceptable *only* for trusted
structural identifiers (database/table names from config), and even then prefer a
validated allowlist.

```go
// Bad — user value interpolated straight into SQL (injection)
q := fmt.Sprintf("SELECT * FROM decision_table WHERE account_id = '%s'", accountID)

// Good — named bind parameter, typed on the ClickHouse side
const q = `
	SELECT decision_date, account_id, amount, phone_flag, inserted_at_utc
	FROM %s
	WHERE decision_date = toDate32(@decision_date)
	  AND account_id     = @account_id
	ORDER BY inserted_at_utc DESC
	LIMIT 1 BY decision_date, account_id
`

rows, err := conn.Query(ctx, fmt.Sprintf(q, fullTableName),
	clickhouse.Named("decision_date", decisionDate),
	clickhouse.Named("account_id", accountID),
)
```

Analytical SQL patterns carry over unchanged from the source — they are ClickHouse
SQL, not language-specific:

- **Deduplication:** `... ORDER BY inserted_at_utc DESC LIMIT 1 BY decision_date, account_id`
- **Window functions:** `dense_rank() OVER (PARTITION BY decision_date ORDER BY utc_call_bucket ASC)`
- **Interval bucketing:** `toStartOfInterval(toDateTime(phone_call_time_utc), INTERVAL 15 minute)`

Keep these in `const` query strings next to the DAO method that runs them — never
build analytical SQL by concatenating fragments across call sites.

---

## Section 6 — The ClickHouse DAO Pattern

A ClickHouse DAO mirrors the GORM repository discipline from
`go-build-domain-features`, but wraps a `driver.Conn` instead of `*gorm.DB` (there
is no ORM for ClickHouse — SQL is written explicitly). The DAO is the **only** place
ClickHouse SQL lives; services call DAO methods, never the driver directly.

```go
// DecisionDAO provides analytical data-access operations for decision_table.
// It is the single owner of decision_table SQL — services depend on it, never
// on the raw driver.
type DecisionDAO struct {
	client   *Client
	database string // resolved from config; used to build fully-qualified names
	table    string
}

// NewDecisionDAO constructs a DecisionDAO bound to the decision_table.
func NewDecisionDAO(client *Client) *DecisionDAO {
	return &DecisionDAO{
		client:   client,
		database: client.cfg.Database,
		table:    "decision_table",
	}
}

// fullTableName returns the database-qualified table name, e.g. "ds.decision_table".
func (d *DecisionDAO) fullTableName() string {
	return fmt.Sprintf("%s.%s", d.database, d.table)
}

// FindByDate returns all decision rows for a given decision date, deduplicated
// to the latest version per (decision_date, account_id).
//
// Returns an empty slice (not an error) when no rows match.
func (d *DecisionDAO) FindByDate(ctx context.Context, decisionDate time.Time) ([]DecisionRow, error) {
	const q = `
		SELECT decision_date, account_id, amount, phone_flag, inserted_at_utc
		FROM %s
		WHERE decision_date = @decision_date
		ORDER BY inserted_at_utc DESC
		LIMIT 1 BY decision_date, account_id
	`

	var rows []DecisionRow
	err := d.client.withRetry(ctx, func() error {
		return d.client.readConn.Select(ctx, &rows,
			fmt.Sprintf(q, d.fullTableName()),
			clickhouse.Named("decision_date", decisionDate),
		)
	})
	if err != nil {
		return nil, fmt.Errorf("querying decisions for %s: %w",
			decisionDate.Format("2006-01-02"), err)
	}
	return rows, nil
}
```

Rules mirrored from the GORM DAO discipline:

- **One DAO per table** — it owns that table's SQL, its `fullTableName()`, and its
  row struct.
- **Reads use `readConn`, writes use `writeConn`** (the dual-connection intent from
  the Python `CHClient` / `CHReadOnlyClient` split).
- **DAO methods return typed rows and wrapped errors** — never leak `driver.Rows`
  or the raw driver error to the service layer.
- **Ubiquitous language:** the Go field, the `ch:` tag, and the ClickHouse column
  name are mechanically identical.
- A service (application-service `Execute()` pattern) orchestrates DAO calls; it
  never constructs SQL. See `go-build-application-services`.

---

## Section 7 — Migrations

ClickHouse migrations use **goose** with the ClickHouse dialect — see
`go-recipe-database-migrations` for goose setup, `up`/`down` structure, and running. This
section covers only ClickHouse-specific table design. There is no per-service
`migrate()` method registry (the Python pattern); versioned SQL files are the source
of truth.

```sql
-- migrations/clickhouse/00012_create_decision_table.sql
-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS ds.decision_table ON CLUSTER '{cluster}'
(
    decision_date   Date32,
    account_id      String,
    amount          Nullable(Float64),
    phone_flag      Nullable(Bool),
    inserted_at_utc DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplicatedMergeTree
PARTITION BY toYYYYMMDD(decision_date)
ORDER BY (decision_date, account_id)
SETTINGS index_granularity = 8192;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS ds.decision_table ON CLUSTER '{cluster}';
-- +goose StatementEnd
```

Configure goose for ClickHouse in the migrate command:

```go
// runClickHouseMigrations applies pending goose migrations to ClickHouse.
func runClickHouseMigrations(ctx context.Context, dsn, dir string) error {
	db, err := goose.OpenDBWithDriver("clickhouse", dsn)
	if err != nil {
		return fmt.Errorf("opening clickhouse for migrations: %w", err)
	}
	defer db.Close()

	goose.SetDialect("clickhouse")
	if err := goose.UpContext(ctx, db, dir); err != nil {
		return fmt.Errorf("running clickhouse migrations: %w", err)
	}
	return nil
}
```

### Table design conventions (carried from the source, unchanged)

1. **Always `ON CLUSTER '{cluster}'`** for replication (`{cluster}` resolves from
   the server macros; pass the cluster name from config where macros are absent).
2. **Engine:** `ReplicatedMergeTree` for primary tables;
   `ReplicatedReplacingMergeTree(inserted_at_utc)` when dedup-on-version is needed.
3. **Partition by date:** `PARTITION BY toYYYYMMDD(decision_date)` — pick the most
   common filter column.
4. **`ORDER BY`:** start with the partition key, then the most selective columns.
5. **`inserted_at_utc DateTime64(3) DEFAULT now64(3)`** on every table for versioning.
6. **Nullable fields** wrapped in `Nullable(T)` — and remember these map to Go
   pointers in the row struct (Section 2).

### Type mapping (ClickHouse column → Go field)

| ClickHouse type | Go field type |
|---|---|
| `String` | `string` |
| `Int32` / `Int64` | `int32` / `int64` |
| `Bool` | `bool` (or `uint8` for `UInt8` sync columns) |
| `Float64` / `Decimal(18,2)` | `float64` / `decimal.Decimal` |
| `Date32` | `time.Time` |
| `DateTime64(3)` | `time.Time` |
| `UUID` | `uuid.UUID` or `string` |
| `Array(String)` | `[]string` |
| `Nullable(T)` | `*T` (pointer) |

### Materialized views

MVs are DDL like any other migration — target table first, then the MV `TO` it.
Prefix names with `mv_`, always `ON CLUSTER`, target engine typically
`ReplicatedReplacingMergeTree(inserted_at_utc)`.

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS ds.mv_ai_call_list ON CLUSTER '{cluster}'
TO ds.ai_call_list AS
WITH toStartOfInterval(toDateTime(dt.phone_call_time_utc), INTERVAL 15 minute) AS utc_call_bucket
SELECT dt.*, utc_call_bucket
FROM ds.decision_table dt
WHERE dt.phone_flag = true AND dt.phone_number IS NOT NULL AND dt.phone_strategy = 'AI_VET';
```

---

## Section 8 — S3 Integration

ClickHouse reads from and writes to S3 natively via the `s3()` table function — no
intermediate staging in Go. The DAO issues the `INSERT`/`SELECT`; Go's job is to
build the (URL-encoded) S3 path and bind parameters.

### Import — CSV from S3 into a table

```go
// ImportFromS3 loads a CSV from S3 into the target table via the s3() function.
//
// s3Path must be a ClickHouse-reachable, URL-encoded S3 URL. Credentials are
// resolved server-side (IAM role) or passed via named params if required.
func (d *DecisionDAO) ImportFromS3(ctx context.Context, s3Path string) error {
	q := fmt.Sprintf(`
		INSERT INTO %s (decision_date, account_id, amount)
		SELECT decision_date, account_id, amount
		FROM s3(@s3_path, 'CSVWithNames')
	`, d.fullTableName())

	err := d.client.withRetry(ctx, func() error {
		return d.client.writeConn.Exec(ctx, q, clickhouse.Named("s3_path", s3Path))
	})
	if err != nil {
		return fmt.Errorf("importing from %s: %w", s3Path, err)
	}
	return nil
}
```

### Export — query results to S3

```go
// ExportToS3 writes the day's rows to S3 via INSERT INTO FUNCTION s3(...).
func (d *DecisionDAO) ExportToS3(ctx context.Context, s3Path string, decisionDate time.Time) error {
	q := fmt.Sprintf(`
		INSERT INTO FUNCTION s3(@s3_path, 'CSVWithNames')
		SELECT * FROM %s WHERE decision_date = @decision_date
	`, d.fullTableName())

	err := d.client.writeConn.Exec(ctx, q,
		clickhouse.Named("s3_path", s3Path),
		clickhouse.Named("decision_date", decisionDate),
	)
	if err != nil {
		return fmt.Errorf("exporting %s to %s: %w",
			decisionDate.Format("2006-01-02"), s3Path, err)
	}
	return nil
}
```

### S3 path encoding

ClickHouse needs each path segment URL-encoded (spaces, special chars in keys).
Build the path in Go with `url.PathEscape` per segment.

```go
// buildS3Path joins the endpoint with a segment-wise URL-encoded object key.
func buildS3Path(endpoint, objectKey string) string {
	segments := strings.Split(objectKey, "/")
	for i, seg := range segments {
		segments[i] = url.PathEscape(seg)
	}
	return endpoint + "/" + strings.Join(segments, "/")
}
```

---

## Section 9 — Error Handling & Logging

Follow the error-wrapping rules from `go-conventions`. Log **structured
metadata** with `slog` (file paths, dates, identifiers) at the boundary that owns
the operation, then return the wrapped error — do not log-and-swallow.

```go
// Good — structured slog before returning the wrapped error
if err := d.ImportFromS3(ctx, s3Path); err != nil {
	slog.ErrorContext(ctx, "clickhouse csv import failed",
		slog.String("s3_path", s3Path),
		slog.String("decision_date", decisionDate.Format("2006-01-02")),
		slog.Any("error", err),
	)
	return fmt.Errorf("import decisions: %w", err)
}
```

The `withRetry` wrapper (Section 1.2) handles **transient** infrastructure errors at
the client boundary. DAO/service error handling is for **business** failures (bad
input, empty results treated as errors, downstream contract violations). Do not
retry business errors.

---

## Section 10 — Testing

Follow the table-driven convention from `go-conventions`. Integration
tests use **testcontainers-go** to spin up a real ClickHouse — the driver's wire
behavior (batch, Nullable scanning, async) cannot be faithfully mocked.

```go
// startClickHouse launches an ephemeral ClickHouse container for integration tests.
func startClickHouse(t *testing.T) *Client {
	t.Helper()
	ctx := context.Background()

	container, err := clickhousetc.Run(ctx, "clickhouse/clickhouse-server:24-alpine")
	require.NoError(t, err)
	t.Cleanup(func() { _ = container.Terminate(ctx) })

	host, err := container.ConnectionHost(ctx)
	require.NoError(t, err)

	client, err := NewClient(ctx, Config{
		WriteAddrs: []string{host},
		ReadAddrs:  []string{host},
		Database:   "default",
	})
	require.NoError(t, err)
	t.Cleanup(func() { _ = client.Close() })
	return client
}
```

Rules:

- Use the **`Memory` engine** for test tables — no replication/`ON CLUSTER`
  needed: `CREATE TABLE test_decisions (...) ENGINE = Memory`.
- **Retry the initial connection** in CI — ClickHouse takes a few seconds to accept
  connections after the container starts (the `Ping` in `NewClient` plus a short
  retry loop covers this).
- Assert **one decision point per test case** (e.g. "Nullable float scans to nil
  pointer when column is NULL", "batch of N rows produces N rows in the table").
- Keep unit tests for path-building / param-assembly helpers (`buildS3Path`) fast
  and container-free.

---

## Checklist — Adding a New ClickHouse Feature (Go)

Apply before merge. Each unchecked item is a **blocker**.

- [ ] Table defined in a **goose migration** with `ON CLUSTER`, correct engine,
      partition key, `ORDER BY`, and `inserted_at_utc DEFAULT now64(3)`.
- [ ] Row struct has **`ch:` tags matching column names exactly**; `Nullable(T)`
      columns are **pointers**.
- [ ] Writes go through the **native batch API** (`PrepareBatch`/`Append`/`Send`),
      chunked — **no row-at-a-time inserts** in hot paths. `Abort()` on append error.
- [ ] Reads use **`readConn`**; writes/DDL use **`writeConn`**.
- [ ] All parameters use **`clickhouse.Named`** — no user input interpolated into SQL.
- [ ] Analytical SQL lives in `const` strings inside the **DAO** — one DAO per table;
      services never touch the driver.
- [ ] S3 paths are **segment-wise URL-encoded**; `s3()` path passed as a bound param.
- [ ] Transient errors handled by **`withRetry`**; business errors are **not** retried.
- [ ] Errors **wrapped with `%w`**; structured `slog` metadata logged at the boundary.
- [ ] **testcontainers** integration tests with `Memory`-engine tables; table-driven,
      one decision point per case.
- [ ] Config loaded via **viper** into the typed `Config` struct — no globals.
