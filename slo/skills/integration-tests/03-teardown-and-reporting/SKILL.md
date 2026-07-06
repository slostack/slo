---
name: 03-teardown-and-reporting
description: 'Integration tests: cleanup, dependency-ordered DB reset, and reporting.'
when_to_use: Use when wiring teardown for a test suite or formatting its results.
group: integration-tests
kind: skill
source_prompt: integration-tests/03-teardown-and-reporting.md
---

# Integration Test Teardown & Reporting

## Skill summary

- **Name:** `03-teardown-and-reporting`
- **Description:** Integration tests: cleanup, dependency-ordered DB reset, and reporting.
- **When to use:** Use when wiring teardown for a test suite or formatting its results.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/03-teardown-and-reporting.md`

## Examples

- The user asks for help with: Integration tests: cleanup, dependency-ordered DB reset, and reporting.
- Use when wiring teardown for a test suite or formatting its results.

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

Clean up test state after execution, generate structured test reports, and maintain a record of what was tested, what passed, and what gaps remain. This prompt covers database cleanup, Docker lifecycle, report generation, and gap analysis.

---

## Prerequisites

Tests have been written and executed following `01-test-setup.md` and `02-test-execution.md`.

---

## Step 1: Teardown Strategy

### Principle

Every record created during a test must be removed. Teardown runs even if the test fails. Use pytest fixture finalizers or `yield` patterns to guarantee cleanup.

### Teardown Order

Delete records in **reverse dependency order** to avoid foreign key violations:

```
1. MappedOrder               (references Order + MappedSystem)
2. CsvImportRowProcessingResult  (references CsvImport)
3. StagedImportRow           (references CsvImport)
4. EmailAddress              (references Customer)
5. PhoneNumber               (references Customer)
6. Identifier                (references Customer)
7. LineItem                  (references Order)
8. Order                     (references Customer + Tenant)
9. Customer                  (references Tenant)
10. CsvImport                (references Tenant + Configuration)
11. AttributeMapping         (references Tenant)
12. MappedSystem             (references Tenant)
13. Configuration            (references Tenant)
14. SystemConfiguration      (standalone)
15. Tenant                   (standalone)
```

### Implementation Pattern

Use pytest fixtures with `yield` to pair setup and teardown:

```python
@pytest_asyncio.fixture(scope="module")
async def seed_tenant_and_config(app_db):
    """Seed tenant, configuration, and related records. Clean up after all tests in module."""
    # --- SETUP ---
    tenant = await create_tenant(app_db, name="tenant-acme")
    config = await create_configuration(app_db, tenant_id=tenant.id)
    sys_config = await create_system_configuration(app_db)
    mapped_system = await create_mapped_system(app_db, tenant_id=tenant.id)
    attr_mapping = await create_attribute_mapping(app_db, tenant_id=tenant.id)
    
    yield {
        "tenant": tenant,
        "config": config,
        "sys_config": sys_config,
        "mapped_system": mapped_system,
        "attr_mapping": attr_mapping,
    }
    
    # --- TEARDOWN (reverse order) ---
    await delete_records(app_db, "mapped_orders", "tenant_id", tenant.id)
    await delete_records(app_db, "csv_import_row_processing_results", "tenant_id", tenant.id)
    await delete_records(app_db, "staged_import_rows", "tenant_id", tenant.id)
    await delete_records(app_db, "email_addresses", "customer_id IN (SELECT id FROM customers WHERE tenant_id = :tid)", tenant.id)
    await delete_records(app_db, "phone_numbers", "customer_id IN (SELECT id FROM customers WHERE tenant_id = :tid)", tenant.id)
    await delete_records(app_db, "identifiers", "customer_id IN (SELECT id FROM customers WHERE tenant_id = :tid)", tenant.id)
    await delete_records(app_db, "line_items", "order_id IN (SELECT id FROM orders WHERE tenant_id = :tid)", tenant.id)
    await delete_records(app_db, "orders", "tenant_id", tenant.id)
    await delete_records(app_db, "customers", "tenant_id", tenant.id)
    await delete_records(app_db, "csv_imports", "tenant_id", tenant.id)
    await delete_by_id(app_db, "attribute_mappings", attr_mapping.id)
    await delete_by_id(app_db, "mapped_systems", mapped_system.id)
    await delete_by_id(app_db, "configurations", config.id)
    await delete_by_id(app_db, "system_configurations", sys_config.id)
    await delete_by_id(app_db, "tenants", tenant.id)
    await app_db.commit()
```

### Reusable Teardown Helpers

```python
# tests/fixtures/teardown_helpers.py

async def delete_records(db_session, table, where_clause, value):
    """Delete records from a table matching a condition."""
    if "IN" in where_clause or "=" not in where_clause:
        await db_session.execute(text(f"DELETE FROM {table} WHERE {where_clause}"), {"tid": value})
    else:
        await db_session.execute(text(f"DELETE FROM {table} WHERE {where_clause} = :val"), {"val": value})


async def delete_by_id(db_session, table, record_id):
    """Delete a single record by ID."""
    await db_session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": record_id})
```

### External State Cleanup

Beyond the database, clean up:

1. **Cloud storage files:** Delete uploaded CSV files from MinIO/S3
   ```python
   await minio_client.remove_object(bucket_name, object_key)
   ```

2. **Redis keys:** Clear any cached state (especially Notifications Service records) and flush the Celery broker to avoid ghost task pickups in the next test
   ```python
   await redis_client.flushdb()
   ```

3. **Mock server state:** Clear captured requests between scenarios via the mock's control endpoint
   ```python
   httpx.post(f"{MOCK_PARTNER_URL}/mock/reset")
   ```

> **Never purge or subscribe to NATS from test code.** `js.purge_stream(...)` and any wrapper around it are banned: purging yanks the backlog from the application's in-flight durable consumers and produces non-deterministic dispatch. Events are observed only through the `system_event_histories` audit table (see `02-test-execution` and the hard ban in `10-cardinal-rules-and-anti-patterns`). No stream cleanup is needed from the test side — configure JetStream retention on the app/infra side instead.

---

## Step 2: Docker Lifecycle Management

### After Test Suite Completes

Stop containers only if no other test scenarios will run. If running scenarios sequentially, keep shared infrastructure alive between runs.

```bash
# Stop a specific service stack
docker compose -f docker/docker-compose.orders_service.yml down

# Stop all integration test containers
docker compose -f docker/docker-compose.orders_service.yml down
docker compose -f docker/docker-compose.notifications_service.yml down
docker compose -f docker/docker-compose.admin_ui.yml down
docker compose -f docker/docker-compose.payments_service.yml down

# Remove volumes (full reset for next run)
docker compose -f docker/docker-compose.orders_service.yml down -v
```

### Fixture-Based Docker Lifecycle (Optional)

For fully automated test runs, manage Docker via pytest fixtures:

```python
@pytest.fixture(scope="session", autouse=True)
def docker_services():
    """Start Docker services before the test session, stop after."""
    subprocess.run(
        ["docker", "compose", "-f", "docker/docker-compose.orders_service.yml", "up", "-d"],
        cwd="<workspace>/integration_tests",
        check=True,
    )
    # Wait for health
    _wait_for_service("http://localhost:18080/o/api/v1/health", timeout=120)
    
    yield
    
    subprocess.run(
        ["docker", "compose", "-f", "docker/docker-compose.orders_service.yml", "down"],
        cwd="<workspace>/integration_tests",
    )
```

---

## Step 3: Test Reporting

### pytest Report Output

Run tests with verbose BDD output and JUnit XML for CI:

```bash
loadenv environments/local.env && poetry run pytest -s \
    --gherkin-terminal-reporter \
    --junitxml=reports/test_results.xml \
    -v tests/
```

### Structured Scenario Report

After tests complete, generate a markdown report summarizing results per scenario. Store reports at `integration_tests/reports/`.

```markdown
# Integration Test Report — Scenario 01: CSV Import

**Date:** 2026-04-06
**Status:** PASSED (14/14 assertions)
**Duration:** 45.2s

## Services Tested
- orders_service (Docker: localhost:18080)
- partner mock (localhost:18090)

## Test Results

| Test | Status | Duration | Notes |
| --- | --- | --- | --- |
| CSV import creates records | PASSED | 3.1s | |
| PlacementMapping transforms CSV columns | PASSED | 1.2s | |
| DomainMapping creates domain objects | PASSED | 2.4s | |
| Order creation event recorded in audit table | PASSED | 5.7s | Polled for 4s |
| Partner handler processes event | PASSED | 8.3s | Includes worker processing time |
| SOR mapping transforms to partner format | PASSED | 1.1s | V2 path taken |
| Partner API call succeeds | PASSED | 2.0s | Mock received 2 POST requests |
| MappedOrder created | PASSED | 0.8s | |
| V1 fallback path | PASSED | 6.2s | Removed SOR mappings, verified fallback |
| CSV import marked complete | PASSED | 1.5s | |
| Order update (not duplicate) | PASSED | 4.8s | |
| Duplicate CSV import rejected | PASSED | 0.9s | |
| SOR disabled — no sync | PASSED | 3.1s | |
| Partner retry on 500 | PASSED | 7.2s | First call 500, retry 200 |

## Unit Test Coverage Skipped
- PlacementMappingTransformer field mapping (covered in orders_service/tests/)
- DomainMappingTransformer categorical v2 (covered in orders_service/tests/)
- PartnerCreateOrderDAO construction (covered in orders_service/tests/)

## Gaps / Follow-Up
- Composite reference generation not tested (no AttributeMapping with is_composite_ref_enabled=true in seed data)
- DomainValueMapping transformations not tested (categorical v2 value transforms)
```

---

## Step 4: Gap Analysis

### After Each Scenario

Compare the scenario specification's assertion checklist against what was actually tested. Identify:

1. **Covered**: Assertions that have passing tests
2. **Skipped (unit-tested)**: Assertions covered by unit tests in source repos — document which unit test file covers them
3. **Not Covered**: Assertions that need additional test work — create follow-up tasks

### Gap Report Template

```markdown
## Coverage Matrix — Scenario 01

| Assertion | Integration Test | Unit Test | Status |
| --- | --- | --- | --- |
| CsvImport created with status=pending | test_successful_import | — | Covered |
| PlacementMapping CSV→internal fields | — | tests/services/mapping_transformers/test_placement_mapping.py | Unit-tested |
| DomainMapping categorical v2 | — | tests/services/mapping_transformers/test_domain_mapping.py | Unit-tested |
| Composite reference generation | — | — | GAP |
| Event recorded in system_event_histories with correct payload | test_events_recorded | — | Covered |
| Partner handler checks is_processable | test_partner_sync | — | Covered |
| SOR V2 mapping with bracket notation | test_sor_mapping | — | Covered |
| SOR V1 fallback | test_v1_fallback | — | Covered |
| Partner API retry on 500 | test_retry | — | Covered |
```

---

## Step 5: Maintaining the Test Suite

### When Source Code Changes

If a service's API contract changes (new fields, renamed endpoints, modified event payloads):

1. Re-read the service's AGENTS.md and RESEARCH.md for updated contracts
2. Update the scenario specification in `<feature-requests-root>/`
3. Update affected step definitions and assertions
4. Run the full scenario to verify

### When New Scenarios Are Added

1. Create a new scenario specification following the feature-request format in `06-generate-feature-requests.md`
2. Follow `01-test-setup.md` for environment setup
3. Follow `02-test-execution.md` for test authoring
4. Follow this document for teardown and reporting
5. Update `RESEARCH.md` in the integration test repo with the new scenario

### Keeping Workers in Sync

The launch script (`docker/scripts/launch_all_orders_service.sh`) has most workers commented out. When adding a new scenario that requires a specific worker:

1. Uncomment the worker in the launch script
2. Document which scenarios require which workers in a comment
3. Rebuild the Docker image or restart the container

---

## Summary Checklist

- [ ] Teardown deletes all records in reverse dependency order
- [ ] Cloud storage files and Redis keys are cleaned up (no NATS purges — events are observed via `system_event_histories`)
- [ ] Mock server state is cleared between scenarios via `POST /mock/reset`
- [ ] Docker containers stopped (or kept alive for next scenario)
- [ ] Test report generated in `reports/` with pass/fail per assertion
- [ ] Gap analysis completed — gaps documented with follow-up tasks
- [ ] Unit test coverage noted — no duplication between integration and unit tests
