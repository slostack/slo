---
name: 05-step-definitions-with-domain-helpers
description: 'Integration tests: pytest-bdd step definitions that consume domain helpers
  from source repos.'
when_to_use: Use when writing or rewriting Given/When/Then steps that mirror domain
  logic.
group: integration-tests
kind: skill
source_prompt: integration-tests/05-step-definitions-with-domain-helpers.md
---

# Writing Step Definitions with Domain Helpers

## Skill summary

- **Name:** `05-step-definitions-with-domain-helpers`
- **Description:** Integration tests: pytest-bdd step definitions that consume domain helpers from source repos.
- **When to use:** Use when writing or rewriting Given/When/Then steps that mirror domain logic.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/05-step-definitions-with-domain-helpers.md`

## Examples

- The user asks for help with: Integration tests: pytest-bdd step definitions that consume domain helpers from source repos.
- Use when writing or rewriting Given/When/Then steps that mirror domain logic.

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

Guide the authoring of pytest-bdd step definition files (`*_steps.py`) that use domain helpers from `src/domains/` for all test state management. Domain helpers own all SQL directly — there is no intermediate `db_seed` layer.

---

## Core Principle: Steps Declare Intent, Helpers Execute

Step functions should read like **declarative instructions** — "create a tenant", "update the attribute mapping" — not procedural SQL recipes. Each domain module in `src/domains/` owns the SQL for its table(s). Steps call domain helpers. That's it — one hop.

```
@given step  →  domain helper (src/domains/)  →  SQL
```

---

## MANDATORY: Cross-Reference the Source Service

Before creating or modifying any domain helper, **look up the actual domain structure** in the source service repository. Each table is its own domain in orders_service — do not group multiple tables into one domain file.

**How to verify:**

```bash
# Check which domains exist in orders_service
ls <workspace>/orders_service/src/domains/
```

**The rule:** One table = one domain module. If `configurations` is a separate domain in orders_service (`src/domains/configuration/`), then it gets its own file in the integration tests (`src/domains/orders_service/configurations.py`). Never put configuration SQL in `tenants.py` just because tenants "have" configurations — that's a FK relationship, not a domain boundary.

The same applies to notifications_service, payments_service, and any other service. Always verify:

| What you're inserting into | Where to look | Integration test file |
| --- | --- | --- |
| `tenants` table | `orders_service/src/domains/tenant/` | `src/domains/orders_service/tenants.py` |
| `configurations` table | `orders_service/src/domains/configuration/` | `src/domains/orders_service/configurations.py` |
| `api_service_keys` table | `orders_service/src/domains/api_service_key/` | `src/domains/orders_service/api_service_keys.py` |
| `attribute_mappings` table | `orders_service/src/domains/attribute_mapping/` | `src/domains/orders_service/attribute_mappings.py` |
| `mapped_systems` table | `orders_service/src/domains/mapped_system/` | `src/domains/orders_service/mapped_systems.py` |
| `mapped_partners` table | `orders_service/src/domains/mapped_partner/` | `src/domains/orders_service/mapped_partners.py` |

---

## Domain Structure

Domain helpers mirror the service structure of the system under test. Each service gets a top-level directory; each table/domain within that service gets its own module file.

```
src/
  domains/
    orders_service/               # Maps to the orders_service service
      tenants.py                  # create_tenant, delete_tenant (tenants table only)
      configurations.py           # create_configuration, delete_* (configurations table)
      api_service_keys.py         # create_api_service_key, delete_* (api_service_keys table)
      attribute_mappings.py       # create_attribute_mapping, update_*, delete_*
      system_configurations.py    # create_system_configuration, update_*, delete_*
      mapped_systems.py           # create_mapped_system, delete_* (mapped_systems table only)
      mapped_partners.py          # create_mapped_partner, delete_* (mapped_partners table)
      orders.py                   # delete_order_children_by_tenant, delete_orders_by_tenant
      customers.py                # delete_customer_children_by_tenant, delete_customers_by_tenant
      csv_imports.py              # delete_csv_import_children_by_tenant, delete_*
      teardown.py                 # teardown_tenant — orchestrates all domain deletes
    partner/                      # Maps to the fulfillment partner external service
      mock_client.py              # PartnerMockClient (health, config, requests)
    notifications_service/        # Future: maps to notifications_service service
    payments_service/             # Future: maps to payments_service service
```

**Composed helpers** (like `create_tenant_with_configuration`) live in the primary domain module (`tenants.py`) but import from other domain modules for cross-domain inserts. The SQL for each table stays in its own module.

---

## Naming Convention

Every function follows a strict `verb_entity` naming pattern:

| Operation | Pattern | Example |
| --- | --- | --- |
| **Create** | `create_<entity>` | `create_tenant`, `create_attribute_mapping` |
| **Create (composed)** | `create_<entity>_with_<related>` | `create_tenant_with_configuration`, `create_mapped_system_with_partner` |
| **Create (from fixture)** | `create_<entity>_from_payload` | `create_attribute_mapping_from_payload` |
| **Update** | `update_<entity>_<what>` | `update_attribute_mapping_composite_ref`, `update_system_configuration_disable_sor` |
| **Delete** | `delete_<entity>_by_<scope>` | `delete_orders_by_tenant`, `delete_mapped_system` |
| **Build (pure)** | `build_<thing>` | `build_system_configuration_attributes` (returns dict, no DB) |

Never use `seed_`, `setup_`, `teardown_` as function prefixes. The verb is always `create`, `update`, `delete`, or `build`.

---

## Module Anatomy

Every domain helper module follows this structure:

```python
"""<Entity> domain helpers for integration test state management.

Owns all SQL for the <table_name> table. Each function follows
the create/update/delete naming convention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from tests.helpers.db_client import AppDBClient


# ---------------------------------------------------------------------------
# Data classes (if multi-value returns are needed)
# ---------------------------------------------------------------------------


@dataclass
class <Entity>SetupResult:
    """Result of a <entity> provisioning operation.

    Attributes:
        <field>: Description.
    """

    <field>: <type>


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_<entity>(
    db: AppDBClient,
    <param>: <type>,
) -> int:
    """Insert a <entity> record.

    Args:
        db (AppDBClient): The database client.
        <param> (<type>): Description.

    Returns:
        int: The created <entity>'s ID.
    """
    return await db.fetchval(
        """
        INSERT INTO <table> (<columns>)
        VALUES ($1, $2, ...)
        RETURNING id
        """,
        <param>,
        ...,
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_<entity>_<what>(
    db: AppDBClient,
    <entity>_id: int,
    <param>: <type>,
) -> None:
    """Update <what> on a <entity>.

    Args:
        db (AppDBClient): The database client.
        <entity>_id (int): The record to update.
        <param> (<type>): Description.
    """
    await db.execute(
        """
        UPDATE <table>
        SET <column> = $1, updated_at = NOW()
        WHERE id = $2
        """,
        <param>,
        <entity>_id,
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_<entity>s_by_tenant(
    db: AppDBClient,
    tenant_id: int,
) -> None:
    """Delete all <entity> records for a tenant.

    Args:
        db (AppDBClient): The database client.
        tenant_id (int): The tenant whose records to delete.
    """
    await db.execute(
        "DELETE FROM <table> WHERE tenant_id = $1",
        tenant_id,
    )
```

**Key rules:**
- Each module owns ALL SQL for its table(s) — INSERT, UPDATE, DELETE
- No delegation to another module for SQL (no `db_seed`, no intermediate layer)
- The `db: AppDBClient` parameter is always the first argument
- All functions are `async` and use named arguments at call sites

---

## Teardown

Teardown is orchestrated by `src/domains/orders_service/teardown.py`, which composes domain-level delete methods in reverse FK dependency order:

```python
from src.domains.orders_service.teardown import teardown_tenant

# In conftest autouse fixture:
run_async(
    teardown_tenant(
        db=db_client,
        tenant_id=tenant_id,
        mapped_system_id=mapped_system_id,
    )
)
```

The teardown function calls delete methods from each domain module in order:
1. Order children → orders
2. Customer children → customers
3. CSV import children → csv imports
4. Tenant config (mapped_partners, attribute_mappings, api_service_keys, system_configurations, configurations)
5. Mapped system (if provided)
6. Tenant

When adding a new domain that creates records during tests, add its delete method to `teardown.py`.

---

## Step Definition Pattern

### Import Domain Helpers Directly

```python
from src.domains.orders_service.tenants import (
    TenantSetupResult,
    create_tenant_with_configuration,
)
from src.domains.orders_service.attribute_mappings import (
    create_attribute_mapping_from_payload,
    update_attribute_mapping_composite_ref,
    update_attribute_mapping_clear_sor,
)
from src.domains.orders_service.system_configurations import (
    create_system_configuration_with_defaults,
    update_system_configuration_disable_sor,
)
from src.domains.partner.mock_client import PartnerMockClient
```

### @given Steps Call Domain Helpers

```python
@given("a tenant exists with an active configuration")
def given_tenant_with_configuration(
    context: dict[str, Any],
    db_client: AppDBClient,
    api_client: AppAPIClient,
    run_async: Callable,
) -> None:
    """Create a tenant and its default configuration."""
    result: TenantSetupResult = run_async(
        create_tenant_with_configuration(db=db_client)
    )
    context["tenant_id"] = result.tenant_id
    context["configuration_id"] = result.configuration_id
    context["api_access_key"] = result.api_access_key
    context["api_access_secret"] = result.api_access_secret
    api_client.configure_auth(
        api_access_key=result.api_access_key,
        api_access_secret=result.api_access_secret,
    )
```

### Mock Service Clients

External service mocks get a typed client class in `src/domains/<service>/mock_client.py`. Instantiate once at module level and reuse across steps.

```python
_mock_partner = PartnerMockClient()

@given("the mock fulfillment partner server is running and healthy")
def given_mock_partner_healthy() -> None:
    """Verify the mock fulfillment partner server responds to health checks."""
    _mock_partner.assert_healthy()
```

---

## Composability Rules

1. **Each helper does one thing.** `create_tenant_with_configuration()` creates a tenant with config and API key. It does NOT create attribute mappings or system configurations — those are separate helpers.

2. **Helpers return dataclasses, not tuples.** Multi-value returns use a `@dataclass` with named fields so callers are explicit about what they unpack.

3. **Helpers accept the minimum parameters needed.** Generate internal values (UUIDs, suffixes) inside the helper. Only expose parameters that the caller legitimately needs to vary.

4. **Step functions wire context, helpers do not.** Helpers never touch the `context` dict. They return values; the step function stores them in context.

5. **Each domain module owns its SQL completely.** No intermediate `db_seed` layer. The domain module IS the SQL layer. If a new INSERT is needed, add it to the appropriate domain module.

6. **Convenience wrappers compose primitives within the same module.** `create_tenant_with_configuration` calls `create_tenant` + `create_configuration` + `create_api_service_key` — all in the same file. `create_attribute_mapping_from_payload` calls `create_attribute_mapping` with fixture data.

7. **Delete methods are first-class.** Every domain module that creates records must also provide `delete_*_by_tenant` methods. These are composed by `teardown.py`.

---

## Coding Conventions Checklist

Before submitting any step file or domain helper, verify compliance:

- [ ] Every function call with 2+ arguments uses **named arguments**
- [ ] Every function and method has **parameter type hints** and a **return type**
- [ ] `Optional[T] = None` for nullable parameters — never bare `= None`
- [ ] Container types are specific (`list[str]`, not `list`)
- [ ] Return types are honest — every code path returns the declared type
- [ ] **Google-style docstrings** on every function (summary, Args, Returns, Raises)
- [ ] Each method makes **one type of decision** (declarative structure)
- [ ] Guard clauses at top, no more than 2 levels of nesting
- [ ] Assertion messages are explicit: `assert x == y, f"Expected {y}, got {x}"`
- [ ] Function names follow `create_/update_/delete_/build_` convention — never `seed_/setup_/teardown_`

---

## Quick Reference: Adding a New Domain

1. Identify which **service** the table belongs to (orders_service, notifications_service, etc.)
2. Create `src/domains/<service>/<domain_name>.py`
3. Add `create_<entity>` with the INSERT SQL
4. Add `update_<entity>_<what>` methods if steps need to modify records
5. Add `delete_<entity>s_by_tenant` for teardown
6. If the domain has FK children, add `delete_<entity>_children_by_tenant`
7. Register the delete method in `src/domains/orders_service/teardown.py`
8. Import and call the helper from the step file
9. Keep `db_assertions.py` helpers for `@then` steps — those are read-only query functions
