---
name: 02-test-execution
description: 'Integration tests: authoring scenarios with pytest, pytest-bdd, and
  Playwright.'
when_to_use: Use when writing a new integration test scenario.
group: integration-tests
kind: skill
source_prompt: integration-tests/02-test-execution.md
---

# Integration Test Execution & Verification

## Skill summary

- **Name:** `02-test-execution`
- **Description:** Integration tests: authoring scenarios with pytest, pytest-bdd, and Playwright.
- **When to use:** Use when writing a new integration test scenario.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/02-test-execution.md`

## Examples

- The user asks for help with: Integration tests: authoring scenarios with pytest, pytest-bdd, and Playwright.
- Use when writing a new integration test scenario.

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

Write and run integration tests for a specific cross-service scenario. This prompt covers test authoring (pytest, pytest-bdd, playwright), assertion patterns, service state management, documentation standards, and verification workflows.

---

## Prerequisites

Before using this prompt:

1. **Setup is complete** — Docker services healthy, environment variables isolated, database seeded, mock servers running. Follow `01-test-setup.md` first.
2. A **scenario specification** exists at `<feature-requests-root>/` with workflow phases, assertions, and code references.

---

## Step 1: Choose the Right Test Framework

Each scenario may use one or more test frameworks. Choose based on what you are verifying:

| Framework | When to use | Location |
| --- | --- | --- |
| **pytest** (plain) | Direct API calls, database assertions, event verification | `tests/step_defs/` |
| **pytest-bdd** | End-to-end workflows with Given/When/Then semantics | `tests/features/` + `tests/step_defs/` |
| **playwright** | Browser-based UI interactions (Admin UI only) — **last resort** | `tests/playwright/` |

**Default choice:** pytest-bdd for all cross-service workflows. Use plain pytest for isolated API contract tests. Use playwright only when the scenario specification explicitly requires browser interaction (e.g., "Admin clicks the Send button").

---

## Step 2: Write BDD Feature Files

### Feature File Structure

Each scenario gets its own `.feature` file. Write clear, business-readable Gherkin:

```gherkin
# tests/features/test_csv_import_partner.feature

Feature: CSV Import creates Orders and syncs to the fulfillment partner
  As an operations administrator
  I want to upload an order CSV via the Admin UI
  So that orders are created in the Orders Service and synced to the System of Record (the fulfillment partner)

  Background:
    Given a tenant "tenant-acme" exists with an active configuration
    And an active AttributeMapping exists for the tenant with placement, domain, and SOR mappings
    And a MappedSystem "partner" exists and is active for the tenant
    And SOR integration is enabled
    And the partner mock server is running

  Scenario: Successful order CSV import creates orders
    When I upload an order CSV with 2 valid rows
    Then a CsvImport record is created with status "pending"
    And the CSV file is stored in cloud storage
    And the staged import row worker processes both rows
    And 2 Customer records are created with correct names
    And 2 Order records are created with correct amounts
    And 2 LineItem records are created with correct quantities
    And Identifier records are created for each order
    And PhoneNumber records are created for each order

  Scenario: Order creation events are recorded in the audit table
    When I upload an order CSV with 2 valid rows
    And the staged import row worker completes processing
    Then 2 "order_created_from_csv_import" events appear in system_event_histories for the tenant's orders
    And each event payload contains batch_run_id as null
    And each event payload contains the complete order, customer, and line_item DAOs

  Scenario: Partner handler syncs orders to SOR
    When I upload an order CSV with 2 valid rows
    And the stream event handler worker processes the order creation events
    Then the partner mock receives 2 POST requests to "/api/order"
    And each request contains Authorization Bearer header
    And each request body has referenceNumber matching the order's unique_order_number
    And each request body has demographics with correct customer names
    And 2 MappedOrder records are created linking Orders Service orders to partner orderIds
    And CsvImport status is "PROCESSED"
```

> **Note on event observation.** The second scenario asserts on the `system_event_histories` audit table, **not** on a NATS subscription. Test code must never subscribe to, consume from, or purge NATS streams — see `10-cardinal-rules-and-anti-patterns` for the hard ban and the rationale.

### Gherkin Writing Rules

- **Background** sets up shared state that every scenario in the file needs
- **Scenario** names describe the specific cross-service interaction being tested
- **Given** steps seed data or verify preconditions
- **When** steps trigger the cross-service action
- **Then** steps assert outcomes across multiple services
- Use concrete values ("2 valid rows", status "pending") not vague descriptions
- Each scenario should test one cross-service interaction path — not the entire workflow

---

## Step 3: Write Step Definitions

### Step Definition Structure

Step definitions live in `tests/step_defs/test_{scenario}_steps.py`. They are synchronous (pytest-bdd limitation) but can invoke async code via the `run_async` fixture.

```python
"""Step definitions for test_csv_import_partner.feature.

Tests the cross-service workflow:
  Admin UI -> POST /o/api/v1/csv-import-by-stream -> Celery worker processes rows
  -> Orders created -> events recorded in system_event_histories -> partner handler -> SOR API call

Services under test:
  - orders_service (API + Celery workers)
  - partner mock (verifies SOR API contract)

Unit test coverage note:
  - PlacementMappingTransformer field mapping is unit-tested in orders_service
  - DomainMappingTransformer categorical mapping is unit-tested
  - This integration test verifies the END-TO-END flow through Docker containers
"""

import pytest
from pytest_bdd import scenario, given, when, then, parsers

# -- Scenarios --

@scenario(
    "../features/test_csv_import_partner.feature",
    "Successful order CSV import creates orders",
)
def test_successful_import():
    """End-to-end: CSV import -> order creation."""
    pass


# -- Given steps --

@given('a tenant "tenant-acme" exists with an active configuration', target_fixture="tenant")
def seed_tenant(app_client, run_async):
    """Seed a tenant with access_key for API auth."""
    tenant = run_async(app_client.create_tenant(name="tenant-acme", country_code="US"))
    return tenant


# -- When steps --

@when("I upload an order CSV with 2 valid rows", target_fixture="import_result")
def upload_csv(app_client, tenant, test_csv_file, run_async):
    """POST the test CSV to the CSV import endpoint."""
    result = run_async(app_client.upload_csv(
        tenant_id=tenant["id"],
        tenant_access_key=tenant["access_key"],
        file_path=test_csv_file,
        import_type="ORDER",
        delimiter=",",
    ))
    return result


# -- Then steps --

@then(parsers.parse('a CsvImport record is created with status "{status}"'))
def verify_csv_import(import_result, status):
    """Verify the CsvImport record was created correctly."""
    assert import_result["status"] == status
    assert import_result["import_type"] == "ORDER"
    assert import_result["tenant_id"] is not None
```

### Step Definition Rules

1. **Each step function gets a docstring** explaining what cross-service interaction it validates
2. **Use `target_fixture`** to pass data between steps (Given → When → Then)
3. **Use `run_async`** fixture to execute async operations from synchronous step functions
4. **Import fixtures** from `tests/fixtures/` for shared seed data and clients
5. **Never hardcode URLs or ports** — use fixtures or environment variables

---

## Step 4: Service State Verification

### Verifying Database State (Orders Service Postgres)

Connect to the Docker Postgres to verify records created by the service:

```python
@pytest_asyncio.fixture(scope="module")
async def app_db():
    """Direct connection to Orders Service Postgres in Docker."""
    engine = create_async_engine(
        "postgresql+asyncpg://orders_app:localdev-password@localhost:15434/orders_development"
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def verify_orders_created(app_db, tenant_id, expected_count):
    """Verify Order records exist in the database."""
    result = await app_db.execute(
        text("SELECT COUNT(*) FROM orders WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    count = result.scalar()
    assert count == expected_count, f"Expected {expected_count} orders, found {count}"
```

### Verifying Events (the `system_event_histories` audit table)

**Never subscribe to, consume from, or purge NATS from test code.** Side-channel JetStream subscribers compete with the application's durable pull-consumers for interest-set routing and silently ack messages out from under the real handlers; per-test purges yank the backlog from in-flight durables. Both produce non-deterministic dispatch. This is a hard ban — see `10-cardinal-rules-and-anti-patterns`.

Instead, observe published events through the application's own `system_event_histories` audit table, joined to `orders.tenant_id`:

```python
async def get_events(app_db, tenant_id, expected_event_name):
    """Return audit rows for the given event name scoped to a tenant's orders.

    Reads the application's own event-history audit table — never a NATS
    side-channel subscription.
    """
    result = await app_db.execute(
        text(
            """
            SELECT h.id, h.event_name, h.partition_id, h.payload, h.event_timestamp
            FROM system_event_histories h
            JOIN orders o ON o.id = h.partition_id
            WHERE o.tenant_id = :tid AND h.event_name = :name
            ORDER BY h.id ASC
            """
        ),
        {"tid": tenant_id, "name": expected_event_name},
    )
    return [dict(row._mapping) for row in result.fetchall()]
```

Because events are recorded asynchronously, wrap this query in the polling helper from Step 5 rather than asserting immediately.

### Verifying Mock Server Received Requests

Mock servers are FastAPI subprocesses (see `01-test-setup` and `04-scenario-conventions` Convention 6). Query the captured requests via the mock's `GET /mock/requests` control endpoint — do not reach into an in-process object:

```python
import httpx

MOCK_PARTNER_URL = "http://localhost:18090"

def get_partner_requests(path_contains=None):
    """Return requests captured by the mock fulfillment partner server."""
    requests = httpx.get(f"{MOCK_PARTNER_URL}/mock/requests").json()
    if path_contains:
        return [r for r in requests if path_contains in r["path"]]
    return requests

def reset_partner_mock():
    """Clear captured requests and reset the mock's config to defaults."""
    httpx.post(f"{MOCK_PARTNER_URL}/mock/reset")
```

### Verifying Redis State (Notifications Service)

For scenarios involving notifications, verify Redis state:

```python
import redis.asyncio as aioredis

@pytest_asyncio.fixture(scope="module")
async def notifications_redis():
    """Connect to Notifications Service Redis in Docker."""
    client = aioredis.Redis(host="localhost", port=16382, db=3)
    yield client
    await client.close()
```

---

## Step 5: Waiting for Async Operations

Many cross-service interactions are asynchronous (Celery workers, event handlers). Use polling with timeouts rather than `time.sleep()`. Default to a 30s timeout at a 0.5s interval (align with the timeout table in `07-debugging-failing-tests`):

```python
import asyncio

async def wait_for_condition(check_fn, timeout=30, interval=0.5, description="condition"):
    """Poll until check_fn returns truthy or timeout expires.
    
    Args:
        check_fn: Async callable that returns truthy when condition is met.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        description: Human-readable description for error messages.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last_result = None
    while asyncio.get_event_loop().time() < deadline:
        last_result = await check_fn()
        if last_result:
            return last_result
        await asyncio.sleep(interval)
    raise TimeoutError(
        f"Timed out after {timeout}s waiting for: {description}. Last result: {last_result}"
    )


# Usage example: wait for the CSV import to be processed
async def check_csv_import_processed(app_db, csv_import_id):
    result = await app_db.execute(
        text("SELECT status FROM csv_imports WHERE id = :cid"),
        {"cid": csv_import_id},
    )
    row = result.fetchone()
    return row and row[0] == "PROCESSED"

await wait_for_condition(
    lambda: check_csv_import_processed(app_db, csv_import_id),
    timeout=30,
    description=f"CsvImport {csv_import_id} to reach PROCESSED status",
)
```

---

## Step 6: Documentation Standards

### Every Test File Must Include

1. **Module docstring** at the top:
   - What cross-service workflow is being tested
   - Which services are involved (with their Docker ports)
   - What unit tests already exist (and why integration tests are needed beyond them)
   - Reference to the scenario specification file

2. **Scenario function docstring**: One-line summary of the end-to-end path

3. **Step function docstrings**: Explain what cross-service interaction the step validates

4. **Inline comments** for non-obvious assertions (e.g., "batch_run_id is None because the payments flow does not use batch runs")

### Example Module Docstring

```python
"""Integration tests: CSV Import -> Order Creation -> Partner (SOR) Sync

Cross-Service Workflow:
  1. Admin UI uploads CSV via POST /o/api/v1/csv-import-by-stream
  2. Celery worker (create_staged_import_row_worker) processes rows
  3. UpsertCustomerAndOrderAppService creates Order, Customer, LineItem, Identifiers
  4. OrderCreatedFromCsvImportEvent published, recorded in system_event_histories
  5. OrderCreatedPartnerHandler consumes the event
  6. PartnerCreateOrderService calls POST /api/order on the fulfillment partner
  7. MappedOrder record links Orders Service order_id to the partner orderId

Services Under Test:
  - orders_service (Docker: localhost:18080, PG: localhost:15434)
  - partner mock (localhost:18090)

Unit Test Coverage (already exists — NOT duplicated here):
  - PlacementMappingTransformer field mapping: orders_service/tests/services/mapping_transformers/
  - DomainMappingTransformer: orders_service/tests/services/mapping_transformers/
  - PartnerCreateOrderDAO construction: orders_service/tests/integrations/sor/

What This Integration Test Adds:
  - Verifies the CSV import → worker → order creation → event → SOR sync pipeline end-to-end
  - Validates HTTP contracts between services through Docker containers
  - Confirms event payloads (observed via system_event_histories) drive the partner handler correctly
  - Verifies MappedOrder records are created with correct external_id from mock response

Scenario Specification: <feature-requests-root>/02-integration-test-scenarios/request.md
"""
```

---

## Step 7: Playwright Tests (Browser-Based — Last Resort)

Use playwright only when the scenario specification explicitly requires browser interaction. These tests are inherently slower and more flaky.

### Directory Structure

```
tests/playwright/
  conftest.py                  # Playwright fixtures
  test_support_action.py       # Browser test, named per scenario
```

### Playwright Test Pattern

```python
"""Browser test: Admin UI support action initiation.

This test uses playwright because it validates UI-specific behavior:
  - Send button visibility on the order detail page
  - SMS provider token generation via browser
  - Real-time status update in the UI

All non-UI assertions are in the pytest-bdd tests for this scenario.
"""

import pytest
from playwright.async_api import async_playwright


@pytest.fixture(scope="module")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def admin_page(browser, admin_session_cookie):
    context = await browser.new_context()
    await context.add_cookies([admin_session_cookie])
    page = await context.new_page()
    yield page
    await context.close()


async def test_send_button_visible_on_order_detail(admin_page, tenant, order):
    """Verify the Send button appears on the order detail page in Admin UI."""
    await admin_page.goto(
        f"http://localhost:18082/a/tenants/{tenant['id']}/orders/{order['id']}"
    )
    send_button = admin_page.locator("[data-testid='support-send-button']")
    await send_button.wait_for(state="visible", timeout=10000)
    assert await send_button.is_visible()
```

### Playwright Rules

- Always run headless (`headless=True`) in CI
- Use `data-testid` attributes for element selection — never CSS classes
- Set explicit timeouts on all waits
- Take screenshots on failure for debugging
- Keep playwright tests minimal — move all API assertions to pytest-bdd

---

## Step 8: Running Tests

### Command Patterns

```bash
# Run all integration tests for a specific scenario
cd <workspace>/integration_tests
loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_csv_import_partner_steps.py -v

# Run with BDD verbose output
loadenv environments/local.env && poetry run pytest -s --gherkin-terminal-reporter tests/features/test_csv_import_partner.feature

# Run a single test
loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_csv_import_partner_steps.py::test_successful_import -v

# Run playwright tests
loadenv environments/local.env && poetry run pytest -s tests/playwright/test_support_action.py -v
```

### Debugging Failures

When a test fails:
1. Check Docker container logs: `docker logs orders_it_api --tail 100`
2. Check Celery worker logs for task failures
3. Query the database directly to verify state
4. Check the mock server's captured requests via `GET /mock/requests`
5. Query `system_event_histories` to confirm events were recorded (never subscribe to NATS from test code)

---

## Summary Checklist

- [ ] Feature file written with clear Given/When/Then covering cross-service interactions
- [ ] Step definitions reference correct Docker service ports
- [ ] Unit test coverage checked — integration tests only cover what unit tests cannot
- [ ] Database state verified via direct Postgres connection
- [ ] Events verified via the `system_event_histories` audit table (never a NATS subscription)
- [ ] Mock server requests captured and asserted via `GET /mock/requests`
- [ ] Async operations use polling with timeouts (not sleep)
- [ ] Module docstring documents the cross-service workflow, services, and unit test coverage gaps
- [ ] Playwright tests (if any) live in `tests/playwright/`
- [ ] Tests pass: `loadenv environments/local.env && poetry run pytest -s tests/ -v`
