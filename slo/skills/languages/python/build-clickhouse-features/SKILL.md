---
name: build-clickhouse-features
description: 'Python: Anything touching ClickHouse — clients, migrations, DAOs, S3, queries.'
when_to_use: For Python projects only. Use when adding ClickHouse-backed analytics or storage features.
group: languages
kind: skill
source_prompt: build-clickhouse-features.md
---

# Building ClickHouse Features

## Skill summary

- **Name:** `build-clickhouse-features`
- **Description:** Anything touching ClickHouse — clients, migrations, DAOs, S3, queries.
- **When to use:** Use when adding ClickHouse-backed analytics or storage features.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-clickhouse-features.md`

## Examples

- The user asks: "Add or revise the clickhouse features for this feature."
- You want the canonical build pattern before touching clickhouse features.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

This guide documents the patterns for working with ClickHouse in this codebase — including connection management, migrations, query execution, DAOs, S3 integration, and testing.

## Client Architecture

The project uses the `asynch` library with a dual-client pattern defined in `connectors/async_clickhouse.py`.

### Dual Clients

Two client classes exist for separation of concerns:

- **`CHClient`**: Read-write operations (DDL, DML, mutations). Uses `CLICKHOUSE_URL`.
- **`CHReadOnlyClient`**: Read-only queries (SELECT). Uses `CLICKHOUSE_READONLY_URL`.

Both inherit from `_CHClientBase` which provides connection pooling and retry logic.

```python
from connectors.async_clickhouse import CHClient, CHReadOnlyClient

# For mutations (INSERT, CREATE, ALTER)
await CHClient.execute(query=insert_statement)

# For reads (SELECT)
results: List[Dict[str, Any]] = await CHReadOnlyClient.fetchall_dict(query=select_query)
```

### Available Methods

| Method | Returns | Use When |
|--------|---------|----------|
| `execute(query, params)` | `None` | INSERT, CREATE TABLE, ALTER, DROP |
| `fetchall(query, params)` | `List[Tuple]` | SELECT returning multiple rows as tuples |
| `fetchone(query, params)` | `Tuple` | SELECT returning a single row as tuple |
| `fetchall_dict(query, params)` | `List[Dict]` | SELECT returning multiple rows as dicts |
| `fetchone_dict(query, params)` | `Dict` | SELECT returning a single row as dict |
| `clickhouse_connection()` | context manager | Raw connection access for advanced operations |

### Retry Behavior

All methods are decorated with `@clickhouse_retry` which provides automatic exponential backoff on transient errors (`AsynchPoolError`, `UnexpectedPacketFromServerError`, `ConnectionError`, `OSError`). Wait time: `min(2**attempt, 5)` seconds, max retries controlled by `CLICKHOUSE_MAX_RETRIES` (default 3).

---

## Migrations

ClickHouse does **not** use Alembic. Migrations are service-based, defined per-domain and coordinated by a `ClickHouseMigrator`.

### Migration Coordinator

File: `src/apps/decision_strategy/clickhouse_migrate.py`

```python
class ClickHouseMigrator:
    def __init__(self):
        self.migration_services: List[Type[BaseService]] = [
            DecisionTableService,
            AICallListService,
            HumanCallListService,
        ]

    async def run_all_migrations(self) -> None:
        for service in self.migration_services:
            await self.run_migration(service)
```

### Adding a New Table

Each domain service that owns a ClickHouse table must implement `BaseService`:

```python
from src.apps.decision_strategy.domains.base_service import BaseService

class MyNewTableService(BaseService):
    TABLE_NAME: str = "my_new_table"

    @staticmethod
    def get_database_name() -> str:
        return cfg("DECISION_STRATEGY_DATABASE")

    @staticmethod
    def get_full_table_name(table_name: str) -> str:
        db_name: str = cfg("DECISION_STRATEGY_DATABASE")
        return f"{db_name}.{table_name}"

    @staticmethod
    async def migrate(CHClient: Type[CHClient]) -> None:
        cluster_name: str = cfg("CLICKHOUSE_CLUSTER_NAME")
        full_table_name: str = MyNewTableService.get_full_table_name(
            MyNewTableService.TABLE_NAME
        )

        create_statement: str = f"""
            CREATE TABLE IF NOT EXISTS {full_table_name}
            ON CLUSTER {cluster_name}
            (
                decision_date Date32,
                account_id String,
                amount Nullable(Float64),
                inserted_at_utc DateTime64(3) DEFAULT now64(3)
            )
            ENGINE = ReplicatedMergeTree
            PARTITION BY toYYYYMMDD(decision_date)
            ORDER BY (decision_date, account_id)
            SETTINGS index_granularity = 8192
        """
        await CHClient.execute(query=create_statement)
```

Then register it in the migrator:

```python
self.migration_services: List[Type[BaseService]] = [
    DecisionTableService,
    AICallListService,
    HumanCallListService,
    MyNewTableService,  # <-- add here
]
```

### Table Design Conventions

1. **Always create `ON CLUSTER`** using `cfg("CLICKHOUSE_CLUSTER_NAME")` for replication
2. **Engine**: Use `ReplicatedMergeTree` for primary tables, `ReplicatedReplacingMergeTree(inserted_at_utc)` for tables that need deduplication
3. **Partition by date**: `PARTITION BY toYYYYMMDD(decision_date)` — choose the most common filter column
4. **ORDER BY**: Start with the partition key, then the most selective columns
5. **Include `inserted_at_utc`**: `DateTime64(3) DEFAULT now64(3)` on every table for versioning
6. **Nullable fields**: Wrap optional columns with `Nullable(Type)` — e.g. `Nullable(String)`, `Nullable(DateTime64(3))`

### Common Type Mappings

| Data Type | ClickHouse Type |
|-----------|----------------|
| String / Text | `String` |
| Integer | `Int32` or `Int64` |
| Boolean | `Bool` (or `UInt8` for PG sync) |
| Decimal / Money | `Decimal(18, 2)` or `Float64` |
| Date | `Date32` |
| Datetime (ms) | `DateTime64(3)` |
| UUID | `UUID` |
| JSON / JSONB | `String` (no native JSON storage) |
| Array | `Array(String)` |

### PostgreSQL → ClickHouse Sync (PeerDB)

When syncing from Postgres, use the type map in `tests/utils/clickhouse_client_utils.py`:

```python
PG_TO_CLICKHOUSE_TYPE_MAP: Dict[str, str] = {
    "INTEGER": "Int32",
    "BIGINT": "Int64",
    "BOOLEAN": "UInt8",
    "VARCHAR": "String",
    "TEXT": "String",
    "TIMESTAMP WITHOUT TIME ZONE": "DateTime",
    "DOUBLE PRECISION": "Float64",
    "JSON": "String",
    "JSONB": "String",
    "ARRAY": "Array(String)",
}
```

PeerDB-synced tables use `ReplacingMergeTree` engine and include a `_peerdb_is_deleted UInt8` column for soft deletes.

---

## Materialized Views

Materialized views automatically filter and transform data from a parent table into a target table.

```python
@staticmethod
async def create_materialized_view(CHClient: Type[CHClient]) -> None:
    cluster_name: str = cfg("CLICKHOUSE_CLUSTER_NAME")
    db_name: str = cfg("DECISION_STRATEGY_DATABASE")
    decision_table: str = f"{db_name}.decision_table"
    table_name: str = f"{db_name}.ai_call_list"

    create_mv_statement: str = f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS {db_name}.mv_ai_call_list
        ON CLUSTER {cluster_name}
        TO {table_name} AS
        WITH
            toStartOfInterval(toDateTime(dt.phone_call_time_utc), INTERVAL 15 minute) AS utc_call_bucket
        SELECT
            dt.*,
            utc_call_bucket
        FROM {decision_table} dt
        WHERE
            dt.phone_flag = true
            AND dt.phone_number IS NOT NULL
            AND dt.phone_strategy = 'AI_VET'
    """
    await CHClient.execute(query=create_mv_statement)
```

### Conventions

1. Target tables are created first (usually `CREATE TABLE AS parent_table` pattern)
2. Target engine is typically `ReplicatedReplacingMergeTree(inserted_at_utc)` — replacing by the version column
3. MV names are prefixed with `mv_`
4. Always create `ON CLUSTER`
5. Call `create_materialized_view` in the service's `migrate()` method after the target table creation

---

## Query Patterns

### Parameter Substitution

Use named parameters passed as a dict:

```python
query: str = """
    SELECT *
    FROM decision_table
    WHERE decision_date = toDate32({decision_date:String})
"""
results = await CHReadOnlyClient.fetchall_dict(
    query=query,
    params={"decision_date": "2026-03-15"}
)
```

### Template Substitution (Data Manager)

The data manager service supports three levels of template substitution (in order) via `QueryTemplateSubstitutionService`:

1. **Domain variables**: `{{domain.variable_name}}` — resolved from domain config
2. **Workflow results**: `{{workflow.workflow_name.attribute}}` — resolved from prior workflow runs
3. **Runtime values**: `:variable_name` — resolved from runtime parameters

### Deduplication with LIMIT BY

```sql
SELECT *
FROM table_name
WHERE decision_date = toDate32({decision_date})
ORDER BY inserted_at_utc DESC
LIMIT 1 BY decision_date, account_id
```

### Window Functions

```sql
SELECT
    r.*,
    dense_rank() OVER (PARTITION BY r.decision_date ORDER BY r.local_call_bucket ASC) AS rn_local,
    dense_rank() OVER (PARTITION BY r.decision_date ORDER BY r.utc_call_bucket ASC) AS rn_utc
FROM ranked_ai_call_list AS r
```

### Time Interval Bucketing

```sql
toStartOfInterval(toDateTime(phone_call_time_utc), INTERVAL 15 minute) AS utc_call_bucket
```

---

## S3 Integration

ClickHouse natively reads from and writes to S3. No intermediate staging is needed.

### Import (CSV from S3)

```python
query: str = f"""
    INSERT INTO {full_table}
    (column1, column2, column3)
    SELECT column1, column2, column3
    FROM s3(
        '{s3_clickhouse_path}',
        'CSVWithNames'
    )
"""
await CHClient.execute(query=query)
```

### Export (Results to S3)

```python
query: str = f"""
    INSERT INTO FUNCTION s3(
        '{s3_clickhouse_path}',
        'CSVWithNames'
    )
    SELECT * FROM {table_name}
    WHERE decision_date = toDate32({{decision_date}})
"""
await CHClient.execute(query=query, params={"decision_date": decision_date})
```

### S3 Path Encoding

S3 paths must be URL-encoded segment by segment:

```python
from urllib.parse import quote

encoded_file_path: str = "/".join(
    quote(segment, safe="") for segment in s3_file_path.split("/")
)
s3_clickhouse_path: str = f"{s3_endpoint_url}/{encoded_file_path}"
```

---

## DAOs (Data Access Objects)

ClickHouse DAOs follow the same Pydantic pattern as Postgres DAOs but without a SQLAlchemy model (no ORM for ClickHouse).

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import date, datetime


class DecisionTableDAO(BaseModel):
    model_config = ConfigDict(
        title="clickhouse_decision_table",
        from_attributes=True,
        json_encoders={
            datetime: lambda v: v.isoformat(timespec="milliseconds") if v else None,
        },
    )

    decision_date: date = Field(..., description="Date this decision applies to")
    account_id: str = Field(..., min_length=1)
    created_at_utc: datetime
    email_flag: Optional[bool] = Field(default=None)
    phone_flag: Optional[bool] = Field(default=None)
    amount: Optional[float] = Field(default=None)
```

### Key Differences from Postgres DAOs

1. No corresponding `model.py` — ClickHouse has no ORM layer
2. Table schema is defined in the service's `migrate()` method, not a model class
3. DAO `title` is prefixed with `clickhouse_` to distinguish from Postgres DAOs
4. Use `isoformat(timespec="milliseconds")` for datetime encoding (matches `DateTime64(3)`)

---

## Error Handling

### Service-Level Pattern

```python
try:
    await CHClient.execute(query)
except Exception as exc:
    logger.error(
        message="ClickHouse CSV import failed",
        metadata={
            "s3_file_path": s3_file_path,
            "decision_date": decision_date,
            "error": str(exc),
        },
        exc_info=exc,
    )
    raise
```

Always log structured metadata (file paths, dates, identifiers) before re-raising. The `@clickhouse_retry` decorator handles transient errors at the client level — service-level error handling is for business logic failures.

---

## Configuration

All ClickHouse config is sourced from environment variables via `config/cfg.py`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `CLICKHOUSE_URL` | Read-write DSN | — |
| `CLICKHOUSE_READONLY_URL` | Read-only DSN | — |
| `CLICKHOUSE_CLUSTER_NAME` | Cluster name for `ON CLUSTER` | `"cluster"` |
| `CLICKHOUSE_MINSIZE` | Min pool connections | `1` |
| `CLICKHOUSE_MAXSIZE` | Max pool connections | `5` |
| `CLICKHOUSE_CONNECT_TIMEOUT` | Connection timeout (seconds) | `10` |
| `CLICKHOUSE_SEND_RECEIVE_TIMEOUT` | Send/receive timeout (seconds) | `300` |
| `CLICKHOUSE_MAX_RETRIES` | Max retry attempts | `3` |
| `CLICKHOUSE_AWS_S3_ENDPOINT_URL` | S3 endpoint for ClickHouse S3 functions | — |
| `CLICKHOUSE_AWS_S3_BUCKET_NAME` | S3 bucket name | — |
| `DECISION_STRATEGY_DATABASE` | Database name for decision strategy tables | — |

---

## Testing

### Integration Tests

Integration tests are in `tests/clickhouse/test_integration.py`. Use the `async_clickhouse_client` fixture.

```python
class TestClickHouseIntegration:
    @pytest.mark.asyncio
    async def test_connection(self, async_clickhouse_client):
        """Test connection with retry for startup."""
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                result = await async_clickhouse_client.fetchone("SELECT version()")
                assert result is not None
                return
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                await asyncio.sleep(2)
```

### Table Operations in Tests

Use the `Memory` engine for test tables (no replication needed):

```python
await async_clickhouse_client.execute("""
    CREATE TABLE IF NOT EXISTS test_table (
        id Int32,
        name String
    ) ENGINE = Memory
""")
```

### Schema Sync for Tests

Use `ClickHouseClientUtils` in `tests/utils/clickhouse_client_utils.py` to sync Postgres schemas to ClickHouse for integration tests:

```python
sync_utils = ClickHouseClientUtils(pg_session, ch_client)
await sync_utils.sync_specific_tables(["inbound_calls", "inbound_call_reports"])
```

---

## Checklist: Adding a New ClickHouse Feature

1. **Define the table** in a domain service's `migrate()` method with `ON CLUSTER`, proper engine, and partitioning
2. **Register the service** in `ClickHouseMigrator.migration_services`
3. **Create a DAO** (Pydantic model with `clickhouse_` prefix in title) if the table has structured reads
4. **Use `CHClient`** for writes, **`CHReadOnlyClient`** for reads
5. **Use named parameters** for query substitution — never interpolate user input directly
6. **Log structured metadata** on errors before re-raising
7. **Write integration tests** using the `async_clickhouse_client` fixture with `Engine = Memory` for test tables
8. **Add config variables** to `config/cfg.py` and the appropriate `.env` files
