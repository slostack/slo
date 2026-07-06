---
name: 07-debugging-failing-tests
description: 'Integration tests: systematic debugging across microservices when an
  integration test fails.'
when_to_use: Use when an integration test fails in a way that spans multiple services.
group: integration-tests
kind: skill
source_prompt: integration-tests/07-debugging-failing-tests.md
---

# Debugging Failing Integration Tests

## Skill summary

- **Name:** `07-debugging-failing-tests`
- **Description:** Integration tests: systematic debugging across microservices when an integration test fails.
- **When to use:** Use when an integration test fails in a way that spans multiple services.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/07-debugging-failing-tests.md`

## Examples

- The user asks for help with: Integration tests: systematic debugging across microservices when an integration test fails.
- Use when an integration test fails in a way that spans multiple services.

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

Systematic methodology for diagnosing and fixing integration test failures across the Orders platform's microservices. Integration tests fail for reasons that span multiple services, async workers, environment configuration, database state, and timing — rarely is the cause obvious from the error message alone. This prompt prevents the two most expensive debugging mistakes: guessing at fixes without understanding the cause, and changing test code when the infrastructure is misconfigured.

---

## The Iron Rule

**Diagnose before you fix. One failure at a time.**

Never batch-fix multiple failures at once. Each failure may have a different root cause. Fix one, re-run that specific test, confirm it passes, then move to the next. Running the full suite after every single-test fix wastes minutes; run the full suite only after all individual fixes are confirmed.

---

## Step 1: Triage — Classify Every Failure

Run the full suite once and collect the output. Classify each failure into one of these categories:

| Category | Symptom | Likely cause |
| --- | --- | --- |
| **Auth failure** | `401 Unauthorized`, "timestamp expired" | Clock skew between host and container, or API service key not seeded |
| **Timeout** | `TimeoutError: Timed out after Ns waiting for: X` | Worker not running, env var missing, or poll interval too aggressive |
| **Missing record** | `AssertionError: X not found`, `None` where dict expected | Upstream processing failed silently — check processing results |
| **Wrong value** | `AssertionError: Expected X, got Y` | Mapping misconfiguration, stale data, or code behaviour change |
| **FK violation** | `ForeignKeyViolationError` in teardown | Async worker created a record after first-pass teardown delete |
| **Stale events** | Event found but "none with suffix" | NATS JetStream retains events across test runs |
| **Teardown error** | `ERROR at teardown of test_X` | Missing table in child table cleanup lists |
| **Connection refused** | `ConnectError`, `ConnectionRefusedError` | Service container not running or port mapping wrong |

Group failures by category. Failures in the same category usually share a root cause and can be fixed together.

---

## Step 2: Verify Infrastructure Before Touching Test Code

**Most integration test failures are infrastructure problems, not test logic problems.** Check these in order before reading a single line of test code.

### 2a. Container health

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep orders_it_
```

Every container must show `Up` with `(healthy)` for infra services (Postgres, Redis, NATS, ClickHouse, MinIO). Application containers (API, workers) show `Up` without `(healthy)`. If any container is `Exited`, fix that first.

**Services under test and their ports:**

| Service | Container | Host Port | Health check |
| --- | --- | --- | --- |
| Orders Service API | `orders_it_api` | 18080 | `curl -sf http://localhost:18080/o/health` |
| Notifications Service | `notifications_it_api` | 18081 | `curl -sf http://localhost:18081/n/health` |
| Admin UI | `admin_ui_it_api` | 18082 | `curl -sf http://localhost:18082/a/health` |
| Payments Service | `payments_it_api` | 18085 | `curl -sf http://localhost:18085/p/health` |
| Mock Fulfillment Partner | (host process) | 18090 | `curl -sf http://localhost:18090/mock/health` |

### 2b. Environment variables inside containers

Each service container may require specific environment variables. Check them directly:

```bash
docker exec <container_name> sh -c 'echo "VAR1=$VAR1 VAR2=$VAR2"'
```

**Orders Service critical env vars:**

```bash
docker exec orders_it_api sh -c \
  'echo "SOR_ENABLED=$SOR_ENABLED SOR_NAME=$SOR_NAME PARTNER_BASE_URL=$PARTNER_BASE_URL USE_NATS_PUBLISHER=$USE_NATS_PUBLISHER USE_NATS_CONSUMER=$USE_NATS_CONSUMER"'
```

| Variable | Required value | What breaks without it |
| --- | --- | --- |
| `SOR_ENABLED` | `true` | Order creation blocked by strict client validation (`"Fields phone_number, full_name, ... must not be null"`) |
| `SOR_NAME` | `partner` | SOR handler doesn't activate |
| `PARTNER_BASE_URL` | `http://host.docker.internal:18090` | Partner sync calls fail or go nowhere |
| `USE_NATS_PUBLISHER` | `true` | No events published to NATS |
| `USE_NATS_CONSUMER` | `true` | NATS stream consumer doesn't start, event handlers never fire |

These are provided by environment overlay files (e.g., `environments/local.env.partner`) via Docker Compose overrides. **If any are empty or wrong, the container was started without the required compose override.**

The correct way to start the orders_service stack for integration tests:

```bash
docker compose \
  -f docker/docker-compose.orders_service.yml \
  -f docker/docker-compose.partner-mock.yml \
  up -d
```

### 2c. Clock synchronization

```bash
echo "Host: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Container: $(docker exec orders_it_api date -u '+%Y-%m-%d %H:%M:%S UTC')"
```

More than 2 seconds of drift causes HMAC auth timestamp validation to fail with `401 Unauthorized - timestamp is expired or invalid`. If clocks are skewed, restart the Docker runtime (OrbStack / Docker Desktop).

### 2d. Workers and background processes

Each service container may run multiple processes (API server, Celery workers, NATS consumers). Check the container logs for startup messages:

```bash
docker logs <container_name> 2>&1 | grep "started\|worker\|consumer\|ERROR" | head -30
```

For orders_service, the launch script is `docker/scripts/launch_all_orders_service.sh`. It documents every process and its role. The critical workers depend on which test scenario is running:

| Worker | Queue | Required for |
| --- | --- | --- |
| `celery_worker_general` | `create_staged_import_row_worker_queue`, `stream_event_handler_worker_queue` | CSV import → order creation, event handling |
| `celery_worker_batch_run` | `batch_run_execution_worker_queue` | Third-party batch run processing |
| `nats_stream_consumer` | N/A | Event dispatch to SOR handlers (partner sync) |

### 2e. Network connectivity between containers

All integration-test containers share `orders_it_network`. If a container can't reach another:

```bash
docker exec orders_it_api sh -c 'wget -qO- http://orders-pg-db:5432 2>&1 || echo "PG not reachable"'
```

Common issues:
- Container started before the network was created (restart it)
- Container on the wrong network (check `docker inspect <container> | grep NetworkMode`)
- DNS name mismatch (container hostname vs service name in compose file)

---

## Step 3: Read the Source Code for the Failing Feature

Before debugging the test, understand what the production code does. This requires reading code across multiple repositories:

### 3a. Identify the code path

Every test scenario exercises a specific chain of services. Read the feature request document and the feature specification to understand:

1. **Which API endpoint is called** — find the router in the service repo
2. **Which worker processes the request** — find the Celery task or NATS handler
3. **Which application service orchestrates the logic** — find the `invoke()` method
4. **Which domain models are written to** — find the model and service classes
5. **Which events are fired** — find the event triggers

### 3b. Cross-reference with the source repositories

| Repository | Local path | What to look for |
| --- | --- | --- |
| `orders_service` | `<workspace>/orders_service` | Routers, domain models, app services, Celery workers, event handlers |
| `notifications_service` | `<workspace>/notifications_service` | Notification domains, service clients |
| `admin_ui` | `<workspace>/admin_ui` | Controllers, API client service |
| `payments_service` | `<workspace>/payments_service` | Payment services, domain models |

### 3c. Look for gate conditions

Many features have conditions that must be true for the logic to activate. Common gates:

- **Environment variables**: `cfg("SOR_ENABLED")`, `cfg("COMMS_ENABLED")` — read via `config/cfg.py`
- **Database flags**: `tenant_details.is_bundled`, `system_configurations.attributes.PARTNER_SYNC_ENABLED`
- **Tenant type checks**: `tenant.service_type == "direct_sale"` changes the entire processing path
- **Feature toggles**: Some features are gated by configuration attributes or DBOS flags

If a gate condition is not met, the feature silently skips — no error, no log, just no output. This is the hardest category to debug without reading the source.

---

## Step 4: Trace the Data Flow in the Database

After infrastructure checks pass and you understand the code path, pick the simplest failing test and trace the data through the database.

### General pattern

Every integration test follows: **seed setup data → trigger action via API → poll for async results → assert database state**. When assertions fail, trace backwards from the expected record to find where the chain broke.

### CSV import flow (orders_service)

```sql
-- 1. Check if the CSV import was created and processed
SELECT id, status, staged_import_rows_created, orders_upserted
FROM csv_imports WHERE id = <csv_import_id>;

-- 2. Check if rows were processed and why they failed
SELECT row_number, order_created, order_error, mapped_order_created, mapped_order_error
FROM csv_import_row_processing_results WHERE csv_import_id = <csv_import_id>;

-- 3. Check the staged import row data
SELECT id, import_row_str FROM staged_import_rows
WHERE csv_import_id = <csv_import_id>;

-- 4. Check orders created
SELECT id, unique_order_number, tenant_id FROM orders WHERE tenant_id = <tenant_id>;

-- 5. Check line items
SELECT id, order_id, client_user_id, order_number FROM line_items
WHERE order_id = <order_id>;

-- 6. Check order bundles
SELECT ob.*, o.unique_order_number FROM order_bundles ob
JOIN orders o ON ob.order_id = o.id WHERE o.tenant_id = <tenant_id>;

-- 7. Check mapped orders (SOR sync)
SELECT id, order_id, entity_id FROM mapped_orders WHERE order_id = <order_id>;
```

### Common database diagnostic patterns

| What you're checking | Query | What to look for |
| --- | --- | --- |
| CSV import stuck | `WHERE status = 'uploaded'` and never changes | Worker didn't pick up the task |
| Order not created | `order_error` in row results | Error message tells you the exact cause |
| Line item field missing | `SELECT * FROM line_items WHERE order_id = X` | Check if the field is `NULL` when expected non-null |
| Bundle not created | `SELECT * FROM order_bundles WHERE order_id = X` | Check `tenant_details.is_bundled` and `line_item.client_user_id` |
| SOR sync failed | `SELECT * FROM mapped_system_errors WHERE order_id = X` | Error details from the partner handler |

---

## Step 5: Understand the Attribute Mapping Pipeline

The CSV import → domain object pipeline uses a two-stage mapping system. Misunderstanding this system is the most common source of "field is unexpectedly NULL" bugs.

### Stage 1: Placement mappings (CSV column → internal_key)

- Maps raw CSV column names to internal field names (internal_keys)
- The internal_key **MUST** be a field on `StagedImportRowInputDAO` (`src/domains/staged_import_row/dao.py`)
- Pydantic v2 `extra="ignore"` silently drops unknown keys — no error, no warning, no log
- To verify available fields: `grep "Field(" src/domains/staged_import_row/dao.py`

### Stage 2: Domain mappings (key → domain object field)

- Maps keys to target domain object fields (order, customer, line_item, phone_number, identifier, misc_order_attributes)
- Domain mapping keys can be **both** internal_keys (from placement output) **AND** raw CSV column names
- Raw CSV column names work because the staged-row `import_row_str` preserves the original CSV data alongside DAO-validated fields
- A single CSV column can serve dual purposes via both mechanisms

### Debugging mapping issues

1. Parse the staged-row `import_row_str` JSON — verify the expected internal_key is present
2. If an internal_key is missing from staged-row data — it doesn't exist on the DAO and was silently dropped
3. If a domain field is NULL in the target table — the domain mapping key doesn't match any key in the `full_import_row` dict
4. Check the attribute mapping record in the database — verify `placement_mappings` and `domain_mappings` JSON columns contain the expected entries

### Tenant-specific mapping configurations

Each tenant has its own attribute mapping. The test fixtures must use the **actual** production mapping structure for that tenant, not a generic one. Before writing mapping fixtures:

1. Obtain the real attribute mapping configuration for the tenant under test
2. Verify every internal_key exists on `StagedImportRowInputDAO`
3. Verify composite-reference configuration if the tenant requires unique orders per line item

---

## Step 6: Fix, Re-run One Test, Confirm

After identifying the root cause:

1. Make the minimal fix
2. Re-run **only the failing test**: `poetry run pytest -s tests/step_defs/test_X.py::test_specific_name -v`
3. Confirm it passes
4. Move to the next failure

Do NOT re-run the full suite until all individual tests pass.

---

## Step 7: Check for Timing Regressions

If you changed poll intervals or timeouts, re-run the full suite once to check for:

- **New timeouts**: You reduced a timeout below what the async processing chain needs
- **Race conditions in teardown**: Faster polling means tests finish sooner, but async workers may still be writing records when teardown starts. Symptoms: `ForeignKeyViolationError` in teardown
- **Stale event pollution**: NATS JetStream retains events across runs. A faster test may observe audit rows from a previous test's orders if the `system_event_histories` query is not scoped tightly to the current test's `tenant_id`/`order_id`

### Teardown race condition fix pattern

If a table causes FK violations during teardown, add it to `_RACEABLE_CHILD_TABLES` in `src/domains/orders_service/orders.py`. The second-pass deletion catches records created by async workers after the first pass. This applies to any table where async workers (Celery, NATS handlers) may write records after the order is created.

### Polling guidelines

| Condition | Recommended timeout | Interval | Why |
| --- | --- | --- | --- |
| CSV import processing | 30s | 0.5s | First-party processes in <5s; third-party in <15s |
| Order creation | 30s | 0.5s | Created in same worker or shortly after |
| SOR sync (mapped order) | 30s | 0.5s | Async via NATS → event handler → HTTP |
| Order bundle | 30s | 0.5s | Created in same worker as order |
| Mock server requests | 15s (polled) | 0.5s | Async handler may not have completed when DB write finishes |
| Event recorded in `system_event_histories` | 30s | 0.5s | Audit row appears shortly after worker completes |
| Teardown pre-wait | 10s | 0.5s | Wait for in-flight processing before deleting |

---

## Common Failure → Root Cause Map

Quick reference for the most frequent failures:

| Failure | Root cause | Fix |
| --- | --- | --- |
| All tests return `401 Unauthorized` | Clock skew between host and container | Restart Docker runtime (OrbStack / Docker Desktop) |
| All tests return `401` after container restart | API service keys not seeded (new database) | Check that the `@given` step creates the API service key correctly |
| CSV import tests timeout at `wait_for_orders_created` | `SOR_ENABLED` not set in container | Restart with the correct compose override |
| Field is `None` that should be populated | Placement mapping used an internal_key not on the DAO | Verify internal_key exists on `StagedImportRowInputDAO` |
| Domain field not populated despite correct mapping | Domain mapping key doesn't match any key in staged-row data | Check if key should be internal_key or raw CSV column name |
| `ForeignKeyViolationError` in teardown | Async worker wrote to table after first-pass delete | Add table to `_RACEABLE_CHILD_TABLES` for second-pass cleanup |
| Event audit row not found | Query not scoped to the current test's `tenant_id`/`order_id`, or checked too early | Scope the `system_event_histories` query tightly and wrap it in polling |
| Mock server received 0 requests | Async handler hasn't completed; assertion checked too early | Add polling to mock request assertion |
| N orders expected but fewer created | Same unique identifier without composite reference enabled | Enable composite reference in attribute mapping |
| `"No active system configuration found"` | Missing `system_configurations` record for tenant | Check that `@given` step seeds system configuration |
| Container healthy but API returns 500 | Database migration not applied | Check container logs for migration errors at startup |
| Test passes alone but fails in suite | Shared state pollution from a prior test | Check teardown completeness — missing table or missing tenant_id scope |

---

## Checklist Before Declaring "Tests Fixed"

- [ ] Every previously-passing test still passes (no regressions)
- [ ] Every fix was verified by running the specific test individually, not just in the full suite
- [ ] Infrastructure state is documented (which compose overrides, which env vars)
- [ ] No secrets were committed (check env file diffs for API keys, passwords)
- [ ] Teardown was updated if new tables are written to by the test flow
- [ ] Poll intervals and timeouts are reasonable (not so low they cause flakes, not so high they waste time)
- [ ] The root cause of each failure is understood and noted — not just the symptom fixed
