---
name: 04-scenario-conventions
description: 'Integration tests: file organization, fixture layering, step-definition
  patterns, assertion structure.'
when_to_use: Use when revising how scenarios are organized across the suite.
group: integration-tests
kind: skill
source_prompt: integration-tests/04-scenario-conventions.md
---

# Integration Test Scenario Conventions

## Skill summary

- **Name:** `04-scenario-conventions`
- **Description:** Integration tests: file organization, fixture layering, step-definition patterns, assertion structure.
- **When to use:** Use when revising how scenarios are organized across the suite.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/04-scenario-conventions.md`

## Examples

- The user asks for help with: Integration tests: file organization, fixture layering, step-definition patterns, assertion structure.
- Use when revising how scenarios are organized across the suite.

## Slo defaults for request and specification artifacts

Unless the user explicitly overrides these paths, use:

```text
<feature-requests-root> = ${SLO_FEATURE_REQUESTS_DIR:-~/.slo/projects/<project_name>/feature-requests}
<feature-specifications-root> = ${SLO_FEATURE_SPECIFICATIONS_DIR:-~/.slo/projects/<project_name>/feature-specifications}
```

Use one folder per feature:

```text
<feature-requests-root>/
└── 01-example-feature/
    └── request.md

<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md
    ├── 01.a-sub-step.md
    └── plan.md
```

## Guidance

## Purpose

Codify the file organization, fixture layering, step definition patterns, mock server design, and assertion structure that every integration test scenario must follow. These conventions were established by the CSV import implementation and ensure consistency as new scenarios are added.

---

## Convention 1: File Organization

Each integration test scenario adds files to a flat structure. Feature files, step definitions, fixtures, and helpers each live in their own top-level directory under `tests/`. There are no per-scenario subdirectories — files are named by scenario instead.

```
tests/
  features/
    test_{scenario_name}.feature              # Gherkin BDD scenarios
  step_defs/
    test_{scenario_name}_steps.py             # pytest-bdd step implementations
  fixtures/
    {domain}_fixtures.py                      # Test data generators (CSVs, mappings)
  helpers/
    env_manager.py                            # ScenarioEnvironment context manager (shared)
    api_client.py                             # httpx wrapper for service APIs (shared)
    db_client.py                              # asyncpg direct Postgres client (shared)
    db_seed.py                                # SQL INSERT helpers for test setup (shared)
    db_assertions.py                          # SQL SELECT helpers for assertions (shared)
    event_history.py                          # Reads the system_event_histories audit table (shared)
    minio_client.py                           # boto3 S3/MinIO client (shared)
    polling.py                                # Async poll-until utilities (shared)
  mock_servers/
    {service_name}_mock.py                    # FastAPI mock for external services
  conftest.py                                 # Registers conftest plugins, session event loop
  conftest_{scenario_name}.py                 # Scenario-specific fixtures
  reports/                                    # Generated test reports (gitignored)
```

### Naming Rules

| Element | Pattern | Example |
| --- | --- | --- |
| Feature file | `test_{scenario}.feature` | `test_csv_import_partner.feature` |
| Step definitions | `test_{scenario}_steps.py` | `test_csv_import_partner_steps.py` |
| Conftest plugin | `conftest_{scenario}.py` | `conftest_csv_import.py` |
| Fixture module | `{domain}.py` under `fixtures/` | `attribute_mappings.py`, `csv_imports.py` |
| Helper module | `{responsibility}.py` under `helpers/` | `db_seed.py`, `polling.py` |
| Mock server | `{service}_mock.py` under `mock_servers/` | `partner_mock.py` |

### Adding a New Scenario

1. Create `tests/features/test_{scenario}.feature`
2. Create `tests/step_defs/test_{scenario}_steps.py`
3. Create `tests/conftest_{scenario}.py` with scenario-specific fixtures
4. Register the conftest in `tests/conftest.py` via `pytest_plugins`
5. Add fixture modules under `tests/fixtures/` if the scenario needs new test data generators
6. Add a mock server under `tests/mock_servers/` if the scenario introduces a new external service
7. Reuse existing helpers — do not duplicate `db_client.py`, `polling.py`, etc.

---

## Convention 2: Conftest Plugin Registration

Each scenario gets its own conftest module. The root `conftest.py` registers them via `pytest_plugins`:

```python
# tests/conftest.py

pytest_plugins = ["tests.conftest_csv_import"]
```

When adding a new scenario, append its conftest to this list:

```python
pytest_plugins = [
    "tests.conftest_csv_import",
    "tests.conftest_payment_processing",   # new scenario
]
```

The root `conftest.py` also provides the session-scoped event loop and any truly global infrastructure (SQLite engine for unit-style tests). Scenario-specific infrastructure goes in the scenario conftest.

---

## Convention 3: Fixture Layering

Three fixture scopes, each with a distinct purpose. Never mix responsibilities across scopes.

| Scope | What lives here | Examples | Why this scope |
| --- | --- | --- | --- |
| **Session** | Expensive infrastructure that starts once | Mock server subprocess, DB connection pool, event loop | Avoids per-test startup cost |
| **Function** | Lightweight wrappers and per-test state | `db_client` (alias), `api_client`, `context` dict, `minio`, `event_history` reader | Fresh state per scenario |
| **Function autouse** | Cross-cutting cleanup | Mock state reset, tenant data teardown | Runs automatically without explicit request |

### Session Fixtures (conftest_{scenario}.py)

```python
@pytest.fixture(scope="session")
def mock_partner_server() -> Generator[subprocess.Popen, None, None]:
    """Start mock server as subprocess. Kill after session."""
    proc = subprocess.Popen([...])
    # Wait for health check
    yield proc
    proc.terminate()

@pytest.fixture(scope="session")
def db_client_session(event_loop) -> Generator[AppDBClient, None, None]:
    """Session-scoped Postgres pool."""
    client = AppDBClient()
    event_loop.run_until_complete(client.create_pool())
    yield client
    event_loop.run_until_complete(client.close())
```

### Function Fixtures (conftest_{scenario}.py)

```python
@pytest.fixture()
def context() -> dict[str, Any]:
    """Per-scenario mutable state shared across Given/When/Then steps."""
    return {}

@pytest.fixture()
def db_client(db_client_session: AppDBClient) -> AppDBClient:
    """Per-test alias for session-scoped DB client."""
    return db_client_session

@pytest.fixture()
def api_client(run_async: Callable) -> Generator[AppAPIClient, None, None]:
    """Per-test httpx client."""
    client = AppAPIClient()
    yield client
    run_async(client.close())
```

### Autouse Fixtures (conftest_{scenario}.py)

```python
@pytest.fixture(autouse=True)
def _reset_mock_partner(mock_partner_server) -> None:
    """Reset mock state before each scenario."""
    httpx.post(f"{MOCK_PARTNER_URL}/mock/reset")

@pytest.fixture(autouse=True)
def _teardown_tenant(context, db_client, run_async) -> Generator[None, None, None]:
    """Delete all seeded tenant data after each scenario."""
    yield
    tenant_id = context.get("tenant_id")
    mapped_system_id = context.get("mapped_system_id")
    if tenant_id is not None:
        run_async(teardown_all(db=db_client, tenant_id=tenant_id, mapped_system_id=mapped_system_id))
```

### Key Rules

- Autouse teardown fixtures use `yield` — setup is empty, cleanup runs after the test
- Teardown checks `context.get("tenant_id")` before running — safe when no tenant was seeded
- The `run_async` fixture bridges sync pytest-bdd steps to async code via `event_loop.run_until_complete`

---

## Convention 4: Step Definition Pattern

Step definition files follow a strict four-section layout.

### Section Layout

```python
"""Step definitions for test_{scenario}.feature.

pytest-bdd does not support async step functions natively. All steps are
synchronous and use the ``run_async`` fixture from conftest to execute
coroutines against the async database and API clients.
"""

from pytest_bdd import scenario, given, when, then, parsers

FEATURE_FILE = "../features/test_{scenario}.feature"

# ---------------------------------------------------------------------------
# Section 1: Scenario declarations
# ---------------------------------------------------------------------------

@scenario(FEATURE_FILE, "Scenario name matches Gherkin exactly")
def test_scenario_name() -> None:
    """One-line description."""

# ---------------------------------------------------------------------------
# Section 2: Background Given steps
# ---------------------------------------------------------------------------

@given("a tenant exists with an active configuration")
def given_tenant(context: dict, db_client: AppDBClient, run_async: Callable) -> None:
    tenant_id = run_async(seed_tenant(db=db_client, ...))
    context["tenant_id"] = tenant_id

# ---------------------------------------------------------------------------
# Section 3: When steps
# ---------------------------------------------------------------------------

@when("I upload an order CSV with 2 rows for the tenant")
def when_upload(context: dict, api_client: AppAPIClient, run_async: Callable) -> None:
    response = run_async(api_client.upload_csv(...))
    context["import_response"] = response

# ---------------------------------------------------------------------------
# Section 4: Then steps
# ---------------------------------------------------------------------------

@then(parsers.parse('a csv import record should exist with status "{status}"'))
def then_csv_import_exists(context: dict, db_client: AppDBClient, run_async: Callable) -> None:
    record = run_async(get_csv_import(db=db_client, ...))
    assert record is not None, "Expected csv import record to exist"
    assert record["status"] == status, f"Expected status '{status}', got '{record['status']}'"
```

### Step Definition Rules

| Rule | Rationale |
| --- | --- |
| All step functions are synchronous | pytest-bdd does not support async steps |
| Use `run_async(coro)` to execute async code | Bridges sync steps to async DB/API clients |
| State flows through `context` dict | Steps share state without return values or globals |
| Use `parsers.parse()` for parameterized steps | Extracts values from Gherkin like `"{status}"` |
| Assertion messages are explicit | `assert x == y, f"Expected {y}, got {x}"` |
| `FEATURE_FILE` is a module-level constant | Relative path from step file to feature file |
| Scenario function name matches Gherkin | `test_` prefix + snake_case of the scenario name |
| Scenario function body is `pass` | pytest-bdd wires steps via decorators, not the function body |

### State Flow Through Context

The `context` dict is the only mechanism for passing state between steps. Each Given step seeds data and stores IDs. When steps perform actions and store results. Then steps read from context to make assertions.

```python
# Given step stores tenant_id
context["tenant_id"] = tenant_id
context["mapped_system_id"] = mapped_system_id

# When step stores response
context["import_response"] = response
context["csv_import_id"] = response["data"]["id"]

# Then step reads from context
tenant_id = context["tenant_id"]
record = run_async(get_order_by_unique_number(db=db_client, tenant_id=tenant_id, ...))
```

---

## Convention 5: Environment Management

Tests never modify `.env` files. Runtime overrides use the `ScenarioEnvironment` context manager.

### ScenarioEnvironment Usage

```python
from tests.helpers.env_manager import ScenarioEnvironment

@given("SOR is enabled with the fulfillment partner as the system of record")
def given_sor_enabled(context: dict) -> None:
    env = ScenarioEnvironment(
        SOR_ENABLED="true",
        SOR_NAME="partner",
        PARTNER_BASE_URL="http://host.docker.internal:18090",
    )
    context["_env_ctx"] = env
    env.__enter__()
```

### When Docker Services Need Different Config

Service-specific environment overrides live in `environments/local.env.{service}` and are loaded via docker-compose `--env-file`. These are static and committed. Per-test overrides happen in code via `ScenarioEnvironment`.

| Layer | Mechanism | Mutated at runtime? |
| --- | --- | --- |
| Docker service defaults | `.env` files in `environments/` | No |
| Per-test overrides | `ScenarioEnvironment` in step code | Yes (restored on exit) |

---

## Convention 6: Mock Server Design

External services get a FastAPI mock that implements both real API routes and test control endpoints.

### Required Endpoints

Every mock server must implement:

| Endpoint | Purpose |
| --- | --- |
| Real API routes | Same paths, methods, request/response schemas as the actual service |
| `GET /mock/health` | Returns 200 when mock is ready |
| `GET /mock/requests` | Returns all captured requests for assertion |
| `POST /mock/config` | Configure response behavior (success, failure, delays) |
| `POST /mock/reset` | Clear captured requests and reset config to defaults |

### Implementation Pattern

```python
# tests/mock_servers/{service}_mock.py

app = FastAPI(title="{Service} Mock")

# Thread-safe state
_lock = threading.Lock()
_requests: list[dict] = []
_config: dict = {"fail_next": False, "status_code": 200}

# --- Real API routes ---

@app.post("/api/order")
async def create_order(request: Request, authorization: str = Header(None)):
    body = await request.json()
    with _lock:
        _requests.append({"method": "POST", "path": "/api/order", "body": body, "headers": dict(request.headers)})
        if _config.get("fail_next"):
            _config["fail_next"] = False
            return JSONResponse(status_code=500, content={"error": "Injected failure"})
    return JSONResponse(content={"orderId": 1000 + len(_requests), "referenceNumber": body.get("referenceNumber")})

# --- Control endpoints ---

@app.get("/mock/health")
def health():
    return {"status": "ok"}

@app.get("/mock/requests")
def get_requests():
    with _lock:
        return _requests.copy()

@app.post("/mock/config")
async def set_config(request: Request):
    body = await request.json()
    with _lock:
        _config.update(body)
    return {"status": "updated"}

@app.post("/mock/reset")
def reset():
    with _lock:
        _requests.clear()
        _config.clear()
        _config.update({"fail_next": False, "status_code": 200})
    return {"status": "reset"}
```

### Mock Server Lifecycle

Mock servers run as subprocesses managed by session-scoped fixtures:

1. **Start**: `subprocess.Popen` launches uvicorn
2. **Health check**: Poll `GET /mock/health` until 200 (max 15 seconds)
3. **Reset**: Autouse fixture calls `POST /mock/reset` before each test
4. **Stop**: `proc.terminate()` in fixture teardown

### Failure Injection

Configure the mock to return errors for retry testing:

```python
# In a When step — make the next partner call fail
httpx.post(f"{MOCK_PARTNER_URL}/mock/config", json={"fail_next": True})
```

---

## Convention 7: Database Seeding and Teardown

### Seeding: Raw SQL via asyncpg

All database seeding uses direct SQL through the `AppDBClient` (asyncpg pool). No ORM. This makes seed data explicit and avoids hidden defaults.

```python
# tests/helpers/db_seed.py

async def seed_tenant(db: AppDBClient, name: str, access_key: str, ...) -> int:
    """INSERT a tenant and return its ID."""
    row = await db.fetchrow(
        """INSERT INTO tenants (name, access_key, country_code, ...)
           VALUES ($1, $2, $3, ...) RETURNING id""",
        name, access_key, country_code, ...
    )
    return row["id"]
```

### Teardown: Reverse Dependency Order

Teardown deletes records in reverse FK dependency order, keyed by `tenant_id`. This is an autouse fixture that runs after every scenario.

```python
async def teardown_all(db: AppDBClient, tenant_id: int, mapped_system_id: int | None = None) -> None:
    """Delete all test records in reverse dependency order."""
    await db.execute("DELETE FROM mapped_orders WHERE tenant_id = $1", tenant_id)
    await db.execute("DELETE FROM csv_import_row_processing_results WHERE ...")
    # ... continue in reverse order through all dependent tables ...
    await db.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
```

### Rules

| Rule | Rationale |
| --- | --- |
| Seed with raw SQL, not ORM | Explicit about what is created; no hidden model defaults |
| Teardown is autouse | Runs even when tests fail |
| Teardown checks `context.get("tenant_id")` | Safe no-op when no data was seeded |
| Delete in reverse FK order | Avoids foreign key constraint violations |
| All seed functions return IDs | Callers store them in `context` for later assertion |

---

## Convention 8: Polling for Async Results

Celery workers and event handlers process asynchronously. Use `poll_until` to wait for results instead of `time.sleep`.

### Generic poll_until

```python
async def poll_until(
    check: Callable[[], Awaitable[T | None]],
    timeout: float = 30.0,
    interval: float = 0.5,
    description: str = "condition",
) -> T:
    """Poll until check() returns truthy, or raise TimeoutError."""
```

### Domain-Specific Wrappers

Build convenience wrappers for common wait conditions. Each wrapper encapsulates the SQL query and passes a descriptive name to `poll_until`:

```python
async def wait_for_csv_import_processed(db, csv_import_id, timeout=30.0) -> dict:
    """Wait until the CSV import reaches a terminal state (completed/failed/processed)."""

async def wait_for_mapped_order(db, order_id, timeout=30.0) -> dict:
    """Wait until a mapped_order record exists for the given order."""

async def wait_for_orders_created(db, tenant_id, expected_count, timeout=30.0) -> list[dict]:
    """Wait until the expected number of orders exist for a tenant."""
```

### Default Timeouts

Aligned with the timeout table in `07-debugging-failing-tests`.

| Condition | Timeout | Interval | Rationale |
| --- | --- | --- | --- |
| CSV import processing | 30s | 0.5s | Worker picks up task, processes all rows |
| Mapped order creation | 30s | 0.5s | Event handler processes the order creation event |
| Order creation (count) | 30s | 0.5s | Multiple rows processed sequentially |
| Event recorded in `system_event_histories` | 30s | 0.5s | Audit row appears shortly after worker completes |

---

## Convention 9: Assertion Categories

Each scenario should assert outcomes at multiple levels. Not every scenario needs all categories, but every test file should cover at least database state and one additional category.

### Categories

| Category | What to check | Helper location |
| --- | --- | --- |
| **Database state** | Records created/updated with correct field values | `tests/helpers/db_assertions.py` |
| **File storage** | Files exist in MinIO/S3 with correct content and path | `tests/helpers/minio_client.py` |
| **Event history** | Correct events recorded in the `system_event_histories` audit table with correct payloads (never a NATS subscription) | `tests/helpers/event_history.py` |
| **External service calls** | Mock received correct HTTP requests with correct bodies/headers | Mock control endpoint `GET /mock/requests` |
| **Error handling** | Retries work, failures produce correct error records, no cascading failures | Combine mock failure injection with DB assertions |

### Assertion Helpers

Database assertion helpers live in `db_assertions.py`. Each returns a dict (record found) or None (not found). The caller asserts on the result:

```python
# tests/helpers/db_assertions.py

async def get_order_by_unique_number(db, tenant_id, unique_order_number) -> dict | None:
    row = await db.fetchrow(
        "SELECT * FROM orders WHERE tenant_id = $1 AND unique_order_number = $2",
        tenant_id, unique_order_number,
    )
    return dict(row) if row else None

# In step definitions:
order = run_async(get_order_by_unique_number(db=db_client, tenant_id=tenant_id, unique_order_number="ORD-IT-001"))
assert order is not None, "Expected order ORD-IT-001 to exist"
assert Decimal(str(order["total_amount_due"])) == Decimal("5600.00"), \
    f"Expected total_amount_due 5600.00, got {order['total_amount_due']}"
```

---

## Convention 10: Fixture Data Generators

Test data (CSV content, JSONB payloads, mapping configurations) lives in `tests/fixtures/` as pure functions that return data. No side effects, no database access.

### Pattern

```python
# tests/fixtures/csv_imports.py

def order_csv_two_rows() -> str:
    """Return CSV content with 2 valid order rows."""
    return (
        "Order_Number,First_Name,Last_Name,...\n"
        "ORD-IT-001,Ada,Lovelace,...\n"
        "ORD-IT-002,Grace,Hopper,...\n"
    )

# tests/fixtures/attribute_mappings.py

PLACEMENT_MAPPINGS = {
    "Order_Number": {"internal_field": "unique_order_number", ...},
    "First_Name": {"internal_field": "first_name", ...},
    ...
}

def build_attribute_mapping_payload(tenant_id: int, config_id: int) -> dict:
    """Build a complete attribute_mapping INSERT payload."""
    return {
        "tenant_id": tenant_id,
        "configuration_id": config_id,
        "placement_mappings": PLACEMENT_MAPPINGS,
        "domain_mappings": DOMAIN_MAPPINGS,
        "system_of_record_mappings": SYSTEM_OF_RECORD_MAPPINGS,
    }
```

### Rules

- Fixture functions are pure — they return data, they do not insert it
- CSV generators return strings, not file handles
- Mapping constants are module-level dicts for easy import and modification
- Variants (e.g., `build_attribute_mapping_payload_v1`) handle alternate configurations

---

## Quick Reference: Adding a New Scenario

Follow these steps in order:

1. **Write the feature file** at `tests/features/test_{scenario}.feature` with Background and Scenarios
2. **Create step definitions** at `tests/step_defs/test_{scenario}_steps.py` following the four-section layout
3. **Create scenario conftest** at `tests/conftest_{scenario}.py` with session infrastructure and autouse cleanup
4. **Register the conftest** in `tests/conftest.py` via `pytest_plugins`
5. **Add fixture generators** under `tests/fixtures/` if new test data shapes are needed
6. **Add a mock server** under `tests/mock_servers/` if a new external service is involved
7. **Add polling wrappers** to `tests/helpers/polling.py` for new async wait conditions
8. **Add assertion helpers** to `tests/helpers/db_assertions.py` for new table queries
9. **Run**: `loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_{scenario}_steps.py -v`
