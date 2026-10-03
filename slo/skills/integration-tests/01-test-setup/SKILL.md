---
name: 01-test-setup
description: 'Integration tests: Docker orchestration + DB seeding setup.'
when_to_use: Use when starting integration-test work — wires up the test environment
  before scenarios.
group: integration-tests
kind: skill
source_prompt: integration-tests/01-test-setup.md
---

# Integration Test Setup

## Skill summary

- **Name:** `01-test-setup`
- **Description:** Integration tests: Docker orchestration + DB seeding setup.
- **When to use:** Use when starting integration-test work — wires up the test environment before scenarios.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/01-test-setup.md`

## Examples

- The user asks for help with: Integration tests: Docker orchestration + DB seeding setup.
- Use when starting integration-test work — wires up the test environment before scenarios.

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

Prepare the integration test environment for a specific cross-service test scenario. This prompt handles repository orientation, Docker service orchestration, database seeding, mock service configuration, and environment variable isolation — everything needed before a single test line executes.

---

## End-to-End Testing Philosophy

The ultimate goal of this integration test suite is to test **all services end-to-end with real instances** — including the fulfillment partner (SOR), the SMS provider, the payment gateway, and any future external service. We are building toward a world where every service in the request chain runs as a real container, and tests validate the actual production wiring.

However, not all services are available as Docker containers today. External services will be **gradually introduced** into the platform as their containerized versions or sandbox environments become available. The test suite must be designed with this progression in mind:

### Maturity Levels Per External Service

| Level | Strategy | When to use |
| --- | --- | --- |
| **Level 0: Mock** | FastAPI mock server running as a subprocess with `/mock/*` control endpoints | Service has no container or sandbox. This is the starting point for all external services. |
| **Level 1: Stub Container** | Dedicated Docker container that implements the service's API contract with canned responses | A stub image is available but the real service isn't accessible. |
| **Level 2: Sandbox** | Real service instance in a sandbox/staging environment | The provider offers a test environment (e.g., SMS provider test credentials, payment gateway sandbox). |
| **Level 3: Real Container** | Actual service running in Docker as part of the compose stack | Full Docker image available (e.g., `orders_service`, `notifications_service`). |

### Current Service Maturity

| Service | Current Level | Target Level | Notes |
| --- | --- | --- | --- |
| Orders Service | Level 3 (Real Container) | Level 3 | Docker image from registry |
| Notifications Service | Level 3 (Real Container) | Level 3 | Docker image from registry |
| Admin UI | Level 3 (Real Container) | Level 3 | Docker image from registry |
| Payments Service | Level 3 (Real Container) | Level 3 | Docker image from registry |
| Fulfillment Partner (SOR) | Level 0 (Mock) | Level 2+ | Mock today; upgrade when sandbox or container available |
| SMS Provider | Level 0 (Mock) | Level 2 | Mock today; upgrade to test credentials when available |
| Payment Gateway | Level 0 (Mock) | Level 2 | Mock today; upgrade to sandbox when available |

### Upgrading a Service from Mock to Real

When a new service becomes available as a container or sandbox, follow this process:

1. **Add the service to Docker Compose** — Create `docker/docker-compose.{service_name}.yml` or add it to an existing compose file. Assign ports following the non-collision convention (offset from standard ports).

2. **Replace mock fixtures with real connections** — The mock server (`tests/mock_servers/{service}_mock.py`) becomes unused. Create a new client in `tests/helpers/` that connects to the real instance.

3. **Upgrade test assertions** — Mocks return canned responses so assertions are limited to "did the request arrive correctly?" Real services enable richer assertions:
   - Verify the service actually persisted the data (query its database or API)
   - Verify side effects (e.g., the fulfillment partner created a real order record, the voice service allocated a real session)
   - Verify error handling with real error responses (not just mock 500s)

4. **Update the scenario specification** — Change the "Services" field to list the real service. Update the Setup section to remove mock references and add container health checks. Update assertions to cover the deeper verification that real services enable.

5. **Keep the mock as a fallback** — Do NOT delete mock implementations. Gate them behind an environment variable so tests can fall back to mocks when the real service is unavailable (e.g., CI without VPN access to a sandbox):
   ```python
   @pytest.fixture(scope="session")
   def partner_service(scenario_env):
       """Use the real fulfillment partner if available, fall back to the mock subprocess."""
       if scenario_env.get("PARTNER_USE_REAL") == "true":
           yield RealPartnerApiClient(base_url=scenario_env["PARTNER_BASE_URL"])
       else:
           proc = subprocess.Popen(
               ["uvicorn", "tests.mock_servers.partner_mock:app", "--port", "18090"]
           )
           # Poll GET /mock/health until 200
           yield proc
           proc.terminate()
   ```

6. **Update the maturity table above** — Move the service to the next level and update Notes.

This graduated approach means:
- Tests are **valuable immediately** even with all mocks
- Each mock-to-real upgrade **strictly increases** test coverage without rewriting existing tests
- The test suite **documents** which services are real and which are mocked at any point in time

---

## Prerequisites

Before running this prompt, ensure:

1. A **scenario specification** exists at `<feature-requests-root>/` describing the workflow, services involved, setup requirements, and assertions. This is your source of truth for what to build.
2. The `integration_tests` repository is cloned and Poetry dependencies are installed.

---

## Step 1: Orient Yourself in the Codebase

Read these files **in order** to build context about the platform and the integration test harness:

### Integration Test Repository

| File | Purpose |
| --- | --- |
| `<workspace>/integration_tests/AGENTS.md` | Project structure, services under test, Docker layout, test architecture |
| `<workspace>/integration_tests/RESEARCH.md` | Full codebase index — every API endpoint, service, worker, and spec link across all service repos |

### Service Repositories (Read AGENTS.md and RESEARCH.md in each)

Each service repository has its own AGENTS.md and RESEARCH.md that serve as comprehensive indexes. Use them to look up API contracts, domain models, service methods, and event handlers — do NOT guess endpoint shapes or field names.

| Service | Local Path | What to look for |
| --- | --- | --- |
| Orders Service | `<workspace>/orders_service` | Routers (`src/routers/`), domains (`src/domains/`), app services (`src/services/`), events (`src/events/`), workers (`src/tasks/`) |
| Notifications Service | `<workspace>/notifications_service` | Routers (`src/routers/`), domains (`src/domains/`), clients (`src/services/clients/`) |
| Admin UI | `<workspace>/admin_ui` | Controllers (`src/routers/`), domain services (`src/domains/*/service.py`), API client (`src/clients/`) |
| Payments Service | `<workspace>/payments_service` | Routers (`src/routers/`), payment services (`src/services/`), domains (`src/domains/`) |

### Feature Specifications

The specification store contains detailed feature documentation organized chronologically. The `RESEARCH.md` in `integration_tests` has the complete index with spec IDs and descriptions. Fetch spec content when you need deeper understanding of a specific feature.

### Coding Conventions

| File | Purpose |
| --- | --- |
| `skills/languages/python/setup-dependencies-and-tests/SKILL.md` | Test infrastructure, conftest patterns |
| `skills/coding/test-verification-policy/SKILL.md` | Test coverage requirements |
| `skills/languages/python/build-clients/SKILL.md` | HTTP client conventions |
| `skills/languages/python/declarative-method-structure/SKILL.md` | Code style — flat code, early returns |

---

## Step 2: Identify Existing Unit Test Coverage

**Critical rule: Do NOT write integration tests for scenarios that are already covered by unit tests in the source repositories.**

Before writing any test, search for existing unit test coverage in the relevant service repositories:

```bash
# Search for unit tests covering the feature area
# Example: CSV import tests in orders_service
find <workspace>/orders_service/tests -name "*.py" | xargs grep -l "csv_import\|CsvImportCreate\|StagedImportRow"

# Example: fulfillment partner handler tests
find <workspace>/orders_service/tests -name "*.py" | xargs grep -l "partner\|PartnerCreate\|MappedOrder"
```

Read the relevant unit test files. For each test scenario in the specification:
- If a unit test already validates the **internal logic** (e.g., field mapping, DAO construction, guard clauses), skip that assertion in the integration test.
- Integration tests should focus on what unit tests **cannot cover**: cross-service API calls, event propagation between services, end-to-end data flow through Docker containers, and correct service wiring.

**What integration tests should verify that unit tests cannot:**
- HTTP requests from Service A actually reach Service B and produce correct responses
- Events published by Service A are consumed by Service B's handler
- Database records created by one service are visible/queryable by another
- Authentication and authorization headers are correctly passed between services
- Celery workers pick up tasks and produce observable side effects
- End-to-end data integrity from CSV import through to the partner (SOR) API call

---

## Step 3: Launch Docker Services

### Docker Compose Files

Each service has its own compose file under `integration_tests/docker/`:

```
docker/
  docker-compose.orders_service.yml         # API + Celery workers + PG + Redis + NATS + CH + MinIO
  docker-compose.notifications_service.yml  # API + Redis + NATS
  docker-compose.admin_ui.yml               # API + Redis
  docker-compose.payments_service.yml       # Payment + Gateway + PG + Redis
  docker-compose.portainer.yml              # Optional monitoring
```

### Service Port Allocation (Non-Standard to Avoid Collision)

| Service | App Port | PostgreSQL | Redis | NATS | ClickHouse |
| --- | --- | --- | --- | --- | --- |
| Orders Service | 18080 | 15434 | 16381 | 14223 | 18123 |
| Notifications Service | 18081 | — | 16382 | 14242 | — |
| Admin UI | 18082 | — | 16383 | — | — |
| Payments Service | 18085/18086 | 15435 | 16384 | — | — |

### Launch Strategy

Only start the services required by the scenario specification. Read the "Services" field in the scenario doc.

```bash
# Example: Start only orders_service and its dependencies
cd <workspace>/integration_tests
docker compose -f docker/docker-compose.orders_service.yml up -d

# Wait for health checks
docker compose -f docker/docker-compose.orders_service.yml ps
```

### Worker Enablement

The launch script at `docker/scripts/launch_all_orders_service.sh` has most workers commented out by default. For a specific test scenario, you may need to uncomment the required workers. Read the scenario specification to determine which workers are needed.

For example, the CSV import scenario requires:
- `launch_create_staged_import_row_worker.sh` (processes import rows)
- The main API server (handles POST /o/api/v1/csv-import)
- The stream event handler worker (routes events to partner handlers)

---

## Step 4: Environment Variable Isolation

### Principle

Test environment variables must be **isolated per scenario** and never leak to other tests or to the host machine.

### Implementation Pattern

Create scenario-specific `.env` files under `environments/`:

```
environments/
  local.env                         # Shared infra (PG, Redis passwords)
  local.orders_service.env          # Service-level config
  scenario_01_csv_import.env        # Scenario-specific overrides
```

The scenario `.env` file overrides only what the test needs:

```bash
# environments/scenario_01_csv_import.env
SOR_ENABLED=true
SOR_NAME=partner
PARTNER_API_KEY=test_api_key_12345
PARTNER_BASE_URL=http://host.docker.internal:18090
PARTNER_CUSTOMER_ID=test_customer_001
PARTNER_API_MAX_ATTEMPTS=3
USE_NATS_PUBLISHER=true
```

### In Test Code

Use pytest fixtures to load scenario-specific environment variables, and restore originals in teardown:

```python
@pytest.fixture(scope="module")
def scenario_env():
    """Load scenario-specific environment variables. Restore originals on teardown."""
    overrides = {
        "SOR_ENABLED": "true",
        "SOR_NAME": "partner",
        "PARTNER_BASE_URL": "http://localhost:18090",
        # ... scenario-specific values
    }
    originals = {}
    for key, value in overrides.items():
        originals[key] = os.environ.get(key)
        os.environ[key] = value
    
    yield overrides
    
    for key, original in originals.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
```

---

## Step 5: External Service Integration (Mocks Today, Real Tomorrow)

External services (the fulfillment partner (SOR), the SMS provider, the payment gateway, the voice service) start at **Level 0 (Mock)** as described in the maturity table above. Each mock must faithfully implement the service's API contract so that upgrading to a real instance requires zero changes to test assertions — only the fixture that provides the service connection changes.

**Design mocks to be replaceable:**
- Mock servers must implement the **exact same HTTP endpoints, request validation, and response shapes** as the real service
- Capture all incoming requests so assertions can query them via the mock's `GET /mock/requests` control endpoint
- Return realistic response payloads (not empty 200s) so assertions written against mocks remain valid against real services
- Support configurable error responses (500, 429, timeout) for failure testing via `POST /mock/config`

When a real service becomes available, follow the "Upgrading a Service from Mock to Real" process in the philosophy section above.

### Mock Server Pattern

Each mock is a **FastAPI application run as a subprocess** (not an in-process handler). It exposes the real API routes **plus** the standard `/mock/*` control endpoints (`GET /mock/health`, `GET /mock/requests`, `POST /mock/config`, `POST /mock/reset`). See `04-scenario-conventions` Convention 6 for the full endpoint contract and implementation pattern.

```python
# tests/mock_servers/partner_mock.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Partner Mock")
_requests: list[dict] = []

@app.post("/api/order")
async def create_order(request: Request):
    """Mock fulfillment partner POST /api/order."""
    body = await request.json()
    _requests.append({"method": "POST", "path": "/api/order", "body": body})
    return JSONResponse(content={
        "orderId": 987654,
        "referenceNumber": body.get("referenceNumber"),
        "status": "ACTIVE",
    })

@app.get("/mock/health")
def health():
    return {"status": "ok"}

@app.get("/mock/requests")
def get_requests():
    return _requests.copy()
```

### Mock Fixture

Run the mock as a subprocess and poll its health endpoint before yielding:

```python
@pytest.fixture(scope="session")
def mock_partner_server():
    """Start the mock fulfillment partner server as a subprocess on port 18090."""
    proc = subprocess.Popen(
        ["uvicorn", "tests.mock_servers.partner_mock:app", "--port", "18090"]
    )
    # Poll GET http://localhost:18090/mock/health until 200 (max 15s)
    yield proc
    proc.terminate()
```

Point the service environment variable (`PARTNER_BASE_URL`) at the mock server's address (`http://host.docker.internal:18090` from containers, `http://localhost:18090` from the host).

---

## Step 6: Seed the Database

### Principle

Each scenario seeds only the data it needs. Seeds are created in the **Setup** phase and cleaned up in **Teardown**. Use the service's API endpoints or direct database connections (for Docker-hosted Postgres) to seed data.

### Two Seeding Approaches

**Approach A: API-Based Seeding (Preferred)**

Seed data by calling the service's own API endpoints. This validates that the setup APIs work correctly and produces data in the exact shape the service expects.

```python
@pytest.fixture(scope="session")
def seed_tenant(api_client):
    """Create a tenant via the Orders Service API."""
    response = api_client.post(
        "http://localhost:18080/o/api/v1/tenants",
        json={"name": "tenant-acme", "country_code": "US", ...},
        headers=signed_headers(),
    )
    tenant = response.json()["data"]
    yield tenant
    # Teardown: delete tenant
    api_client.delete(f"http://localhost:18080/o/api/v1/tenants/{tenant['id']}", headers=signed_headers())
```

**Approach B: Direct Database Seeding (When API is insufficient)**

Connect directly to the Docker PostgreSQL instance when the API doesn't expose a creation endpoint (e.g., AttributeMapping with specific JSONB payloads):

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

@pytest_asyncio.fixture(scope="module")
async def db_engine():
    """Connect to the Orders Service Postgres running in Docker."""
    engine = create_async_engine(
        "postgresql+asyncpg://orders_app:localdev-password@localhost:15434/orders_development"
    )
    yield engine
    await engine.dispose()
```

### Seed Data Checklist

For each scenario, the specification's **Setup** section lists required seed records. Create fixtures for each one in dependency order. The scenario doc for CSV import requires:

1. `Tenant` (with known `access_key`)
2. `Configuration` (linked to tenant)
3. `SystemConfiguration`
4. `MappedSystem` (type=partner, status=active)
5. `AttributeMapping` (with `placement_mappings`, `domain_mappings`, `system_of_record_mappings`)
6. Test CSV file (staged in a temp directory)

---

## Step 7: Folder Structure for Tests

### Directory Layout

Each scenario adds files to a **flat structure** — there are no per-scenario subdirectories. Feature files, step definitions, fixtures, helpers, and mock servers each live in their own top-level directory under `tests/`, and files are named by scenario. This mirrors `04-scenario-conventions` Convention 1 exactly.

```
tests/
  features/
    test_{scenario}.feature            # Gherkin .feature files, named per scenario
  step_defs/
    test_{scenario}_steps.py           # BDD step definitions, named per scenario
  fixtures/
    {domain}_fixtures.py               # Pure test-data generators (CSVs, mappings)
  helpers/
    env_manager.py                     # ScenarioEnvironment context manager (shared)
    api_client.py                      # httpx wrapper for service APIs (shared)
    db_client.py                       # asyncpg direct Postgres client (shared)
    db_seed.py                         # SQL INSERT helpers (shared)
    db_assertions.py                   # SQL SELECT helpers (shared)
    minio_client.py                    # boto3 S3/MinIO client (shared)
    polling.py                         # Async poll-until utilities (shared)
  mock_servers/
    partner_mock.py                    # FastAPI mock for the fulfillment partner
    sms_provider_mock.py               # FastAPI mock for the SMS provider
    payment_gateway_mock.py            # FastAPI mock for the payment gateway
  playwright/                          # Browser-based tests (last resort)
    test_support_action.py
    conftest.py
  conftest.py                          # Root conftest — registers plugins, session event loop
  conftest_{scenario}.py               # Scenario-specific fixtures
```

### Naming Conventions

- Feature files: `test_{scenario}.feature`
- Step definition files: `test_{scenario}_steps.py`
- Scenario conftest: `conftest_{scenario}.py`
- Helper modules: `{responsibility}.py` under `helpers/` (shared, never duplicated)
- Mock servers: `{service}_mock.py` under `mock_servers/`
- All test functions: `test_{method}_{expected_outcome}_{when_condition}`

---

## Summary Checklist

Before proceeding to test execution:

- [ ] Read AGENTS.md and RESEARCH.md in all relevant repos
- [ ] Read the scenario specification thoroughly
- [ ] Searched for existing unit tests — confirmed integration tests add value beyond unit coverage
- [ ] Docker services started and healthy for all required services
- [ ] Required Celery workers uncommented in launch script
- [ ] Environment variables isolated per scenario
- [ ] External services configured at the correct maturity level (mock, stub, sandbox, or real container)
- [ ] Mock servers are FastAPI subprocesses with `/mock/health|requests|config|reset` control endpoints and faithful real API routes
- [ ] Mock-to-real toggle fixture exists for each external service (gated by environment variable)
- [ ] Database seeded with required records (Tenant, Configuration, MappedSystem, AttributeMapping, etc.)
- [ ] Test folder structure created with the flat layout and correct naming
- [ ] HTTP client wrappers created for each service under test
- [ ] Service maturity table in this document is up to date
