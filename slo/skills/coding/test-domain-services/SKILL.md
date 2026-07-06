---
name: test-domain-services
description: Patterns for testing domain services (Pydantic DAOs, service methods,
  persistence).
when_to_use: Use when writing or revising tests under tests/domains/.
group: coding
kind: skill
source_prompt: test-domain-services.md
---

# Test Domain Services

## Skill summary

- **Name:** `test-domain-services`
- **Description:** Patterns for testing domain services (Pydantic DAOs, service methods, persistence).
- **When to use:** Use when writing or revising tests under tests/domains/.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `test-domain-services.md`

## Examples

- The user asks: "Write or revise the tests covered by test domain services."
- You finished coding and need the matching test convention before calling the work done.

## Guidance

How to write transactional unit tests for **domain services** in the
standard service layer style — the per-domain `<DomainService>` class that lives in
`src/domains/<domain>/service.py` and exposes static `build`,
`create`, `build_and_create`, `get`, `update`, `delete`, list/query
helpers, and any domain-specific transitions (e.g. `toggle`, `increment_*`).

> Read this **before** writing or modifying a domain service test. Domain
> services are the lowest persistence-aware layer in the codebase; their
> tests are the contract that everything above them (application
> services, controllers, workers) depends on.

---

## 1. What a domain service test exercises

A domain service test exercises a single static method on the domain
service against the **real** PostgreSQL database. It:

1. Builds prerequisite rows (parent `Account`, `Campaign`, etc.) using
   sibling domain services.
2. Calls the method under test.
3. Asserts on the returned SQLAlchemy model and (when relevant) the
   round-tripped DAO.

It does **not** exercise:
- HTTP, middleware, or routing — that is for a controller test
  (`skills/coding/test-controllers/SKILL.md`).
- Multi-step orchestration spanning several services with shared state
  — that is for an application service test (`skills/coding/test-app-services/SKILL.md`).
- External I/O (HTTP clients, Redis, mailers, workers). Domain services
  must not depend on those; if they appear to, treat that as a bug.

---

## 2. File layout and naming

| Item | Convention |
|---|---|
| Test file location | `tests/domains/<domain>/test_<entity>_service.py` mirroring `src/domains/<domain>/service.py` |
| Test class | `class Test<Entity>Service:` (one class per service file) |
| Test method names | `test_<method>_when_<condition>` — `test_build_and_create`, `test_build_and_create_with_constraints`, `test_duplicate_coupon_for_same_campaign`, `test_update_constraints` |
| Granularity | One test per decision point in the service method (each branch, each guard, each raised exception) — see `skills/coding/test-verification-policy/SKILL.md` |

---

## 3. Required fixtures and imports

Module-level imports stay minimal — only `pytest`, the rollback fixture,
and SQLAlchemy type hints. Everything else is imported **inside** each
test (see `§7`).

```python
import pydantic
import pytest
import sqlalchemy
from tests.async_db import async_db_session
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import models   # forces full model registration
```

The `from src.models import models` import at the top is
deliberate — it ensures every SQLAlchemy model is registered on the
metadata before the first query runs. Do not remove it.

---

## 4. Building prerequisite state

Domain entities almost always have parents (a `Coupon` needs a `Campaign`
which needs an `Account` which needs a `User`). Build them with the
same `build_and_create` pattern, **inline in the test**, in the order
the foreign keys require:

```python
user: User = await UserService.build_and_create(
    first_name="ada",
    last_name="lovelace",
    email="ada.lovelace@example.com",
    password="Abc123!!",
    db_session=async_db_session,
)

account: Account = await AccountService.build_and_create(
    name="First_account",
    user_id=user.id,
    db_session=async_db_session,
)

campaign: Campaign = await CampaignService.build_and_create(
    name="First Campaign",
    account_id=account.id,
    start_date=tz_now(),
    end_date=days_after(dt=tz_now(), days=3),
    db_session=async_db_session,
    autocommit=True,
)
```

For tests that need a fully wired account-with-coupon (and the access
keys, subscription, etc.), prefer `Factory.create_active_coupon`:

```python
fact: FactoryInstance = await Factory.create_active_coupon(
    db_session=async_db_session,
)
account: Account = fact.account
campaign: Campaign = fact.campaign
coupon: Coupon = fact.coupon
```

**Rule of thumb:** if your test needs *more than two* parent rows, use
the factory. If it tests a permutation the factory does not produce
(custom dates, custom redemption types), inline the `build_and_create`
calls.

---

## 5. Test structure — the canonical shape

Every domain service test follows the same four blocks:

```python
class TestCouponService:
    @pytest.mark.asyncio
    async def test_build_and_create_with_constraints(
        self, async_db_session: AsyncSession,
    ):
        # ── Block 1: function-local imports (see §7) ──────────────────
        from decimal import Decimal
        from src.domains.user.service import UserService, User
        from src.domains.account.service import AccountService, Account
        from src.domains.campaigns.service import CampaignService, Campaign
        from src.domains.coupons.service import (
            CouponService, Coupon, CouponDAO,
        )
        from src.domains.coupons.dao import (
            CouponDAO, COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
        )
        from utils.datetime_support import tz_now, days_after, datetime

        # ── Block 2: prerequisites (parents, factory state) ───────────
        user: User = await UserService.build_and_create(
            first_name="ada",
            last_name="lovelace",
            email="ada.lovelace@example.com",
            password="Abc123!!",
            db_session=async_db_session,
        )
        account: Account = await AccountService.build_and_create(
            name="First_account",
            user_id=user.id,
            db_session=async_db_session,
        )
        campaign: Campaign = await CampaignService.build_and_create(
            name="First Campaign",
            account_id=account.id,
            start_date=tz_now(),
            end_date=days_after(dt=tz_now(), days=3),
            db_session=async_db_session,
            autocommit=True,
        )

        # ── Block 3: invoke the method under test ─────────────────────
        coupon: Coupon = await CouponService.build_and_create(
            code="MYFIRST_COUPON",
            redemption_type=COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
            redemption_value=Decimal(10.00),
            max_redemption_value=Decimal(12.00),
            campaign_id=campaign.id,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            db_session=async_db_session,
            autocommit=True,
            minimum_order_value=Decimal("2200.00"),
            merchant_id="tenant-acme",
            customer_ids=["customer_12345", "customer_22123"],
            redemption_split_in_percent=[Decimal(100), Decimal(50), Decimal(30)],
        )

        # ── Block 4: assertions on model and DAO round-trip ───────────
        assert coupon.id is not None
        assert coupon.code == "MYFIRST_COUPON"
        assert coupon.campaign_id == campaign.id
        assert coupon.is_active is True
        assert coupon.used_count == 0

        coupon_dao: CouponDAO = CouponDAO.from_orm(coupon)
        assert (
            coupon_dao.constraints.minimum_order_constraint.minimum_order_value
            == Decimal("2200.00")
        )
        assert coupon_dao.constraints.merchant_constraint.merchant_id == "tenant-acme"
        assert coupon_dao.constraints.customer_constraint.customer_ids == [
            "customer_12345",
            "customer_22123",
        ]
```

### Block discipline

| Block | What goes in it | What MUST NOT go in it |
|---|---|---|
| 1. Imports | All function-local imports for symbols this test uses | Unused imports; HTTP clients; `get_test_app` |
| 2. Setup | Parent rows, factory calls, time-window construction | The method under test |
| 3. Action | A single `await <DomainService>.<method>(...)` call (the unit under test) | Any other domain mutations — those belong in setup |
| 4. Assert | Model field assertions; DAO round-trip assertions; raised-exception assertions | Additional inserts/updates after the assertion phase begins |

---

## 6. Assertion patterns

Assert against three distinct surfaces of the returned object:

### 6.1 Model identity and required fields

```python
assert coupon.id is not None
assert coupon.code == "MYFIRST_COUPON"
assert coupon.campaign_id == campaign.id
```

### 6.2 Model defaults — prove the service applied them

```python
assert coupon.is_active is True
assert coupon.max_use_count == 1
assert coupon.used_count == 0
assert coupon.constraints == {
    "minimum_order_constraint": None,
    "merchant_constraint": None,
    "customer_constraint": None,
    "staggered_redemption_constraint": None,
    "first_order_constraint": None,
}
```

### 6.3 DAO round-trip — prove the model serializes correctly

For any service method that touches a JSON column (e.g. `Coupon.constraints`)
or a Pydantic-encoded value, validate by round-tripping through the DAO:

```python
coupon_dao: CouponDAO = CouponDAO.from_orm(coupon)
assert (
    coupon_dao.constraints.staggered_redemption_constraint.redemption_split_in_percent
    == [Decimal(100), Decimal(50), Decimal(30)]
)
```

This catches a real failure class: a service that stores the right shape
in the column but with a key the DAO cannot parse.

---

## 7. Why imports live inside the test function

Module-level imports of `src` services and DAOs trigger:

1. SQLAlchemy model registration on the shared `Base.metadata`
2. Pydantic model construction (which has side effects on shared
   validators and registries)
3. Indirect imports of FastAPI app code that touches env-var defaults

If you import these at module load time, pytest collection runs *before*
the test event loop and DB connection are wired up — leading to
"models registered twice" / "session bound to a different connection"
failures that are hard to diagnose.

**Rule:** at module level, only `pytest`, `pytest_asyncio`, the fixture
imports (`async_db_session`), `AsyncSession` for type hints, and the
single `from src.models import models` registration import. Every
other import lives inside the test function body.

---

## 8. Testing exception paths

For methods that raise on invalid state (constraint violations,
deactivating an already-deactivated row, exceeding max use count), use
`pytest.raises` with the *exact* exception class the service raises:

```python
from sqlalchemy.exc import IntegrityError

# First insert succeeds
coupon: Coupon = await CouponService.build_and_create(
    code="MYFIRST_COUPON",
    campaign_id=campaign.id,
    ...
    db_session=async_db_session,
    autocommit=True,
)

# Duplicate insert raises
with pytest.raises(IntegrityError):
    await CouponService.build_and_create(
        code="MYFIRST_COUPON",   # same code, same campaign
        campaign_id=campaign.id,
        ...
        db_session=async_db_session,
        autocommit=True,
    )
```

For domain-defined exceptions (e.g. `CouponExceededMaxUsageCountError`),
import them from the same `service.py` and assert on attributes that
matter to the API layer:

```python
with pytest.raises(CouponExceededMaxUsageCountError) as excinfo:
    await CouponService.increment_used_count(
        coupon=coupon, db_session=async_db_session,
    )
assert excinfo.value.code == "error_coupon_exceeded_max_usage_count"
assert excinfo.value.http_error_code == 412
```

---

## 9. Testing list/query methods

For `list_*`, `get_by_*`, and `count_*` methods, build *more than the
minimum* state so you can prove filters work:

```python
fac: FactoryInstance = await Factory.create_active_coupon(
    db_session=async_db_session,
)
# Add a second coupon to the same campaign
coupon2: Coupon = await CouponService.build_and_create(
    code="MYSECOND_COUPON",
    campaign_id=fac.campaign.id,
    redemption_type=COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
    redemption_value=Decimal(10.00),
    max_redemption_value=Decimal(12.00),
    start_date=fac.campaign.start_date,
    end_date=fac.campaign.end_date,
    db_session=async_db_session,
    autocommit=True,
)

coupons: list[Coupon] = await CouponService.list_by_campaign_id(
    campaign_id=fac.campaign.id, db_session=async_db_session,
)
assert len(coupons) == 2
```

When the query has filters (state, customer_id, date window), write one
test per filter that proves a row is included AND a sibling test that
proves a non-matching row is excluded.

---

## 10. The `autocommit` flag

Domain services accept `autocommit: bool = True`. In tests, prefer
`autocommit=True` for setup rows — it gives a stable, queryable state
for the action under test. For the action under test itself, follow the
production caller's convention (most app services pass `autocommit=False`
and let the middleware commit at request boundary; most factories pass
`autocommit=True`).

If you need the persisted row to be visible to a subsequent SQL query
through a different ORM identity map state, call:

```python
await async_db_session.flush()
await async_db_session.refresh(coupon)
```

Never call `await async_db_session.commit()` in a test — the
`async_db_session` fixture wraps everything in a savepoint and rolls it
back after the test. A `commit()` can release the outer rollback
boundary and leak rows into the database.

---

## 11. What every domain service test must cover

For each public method on the domain service, write at minimum:

| Branch | Test |
|---|---|
| Happy path | One test that passes valid arguments and asserts the persisted state |
| Each defaulted argument | Tests that prove the default is applied when omitted |
| Each validation guard / raise | One test per `raise` statement in the method, asserting the exception class and (for `*Exception` types) `code` and `http_error_code` |
| Each filter clause in a list/query | One test that proves the filter includes a matching row, plus one that proves it excludes a non-matching one |
| Each conditional branch (`if x is None`, `if customer_id`, etc.) | One test per branch — see `skills/coding/test-verification-policy/SKILL.md` |
| DAO round-trip for any JSON-column field | `<Entity>DAO.from_orm(model)` and assert the parsed structure |

---

## 12. Running the tests

```bash
loadenv environments/test.env
loadenv environments/local.env

PYTHONPATH=${PWD} poetry run pytest -sv \
  tests/domains/coupons/test_coupon_service.py::TestCouponService::test_build_and_create_with_constraints
```

Run the full domain test directory while iterating, then the full suite
before opening a PR.

---

## 13. Anti-patterns (do NOT do these)

- **Module-level imports of services / DAOs / factories** — see §7.
- **Calling `await async_db_session.commit()`** — releases the outer
  rollback. Use `flush()` and `refresh()`.
- **Building parent rows with raw `db_session.add(Model(...))`** — always
  go through `<DomainService>.build_and_create(...)` so you exercise the
  same code path production uses.
- **Mocking the database** — domain service tests are integration tests
  against PostgreSQL. If you find yourself mocking `AsyncSession`, you're
  writing a test that proves nothing. Mocks belong in narrowly-scoped
  application service tests where an external dependency is being
  replaced (and even there, prefer real services).
- **Asserting the SQLAlchemy model and skipping the DAO round-trip** for
  fields stored as JSON / encoded structures — that hides a class of
  serialization bugs.
- **Reusing one test to cover three branches** — see
  `skills/coding/test-verification-policy/SKILL.md`. One branch, one test, one assertion
  cluster.

---

## 14. Verification checklist

Before marking a domain service test complete:

- [ ] File lives at `tests/domains/<domain>/test_<entity>_service.py`
- [ ] Class is named `Test<Entity>Service`
- [ ] Each test is `@pytest.mark.asyncio` and takes
      `async_db_session: AsyncSession`
- [ ] Module-level imports are limited to `pytest`, fixture imports,
      `AsyncSession`, and `from src.models import models`
- [ ] Parent rows are created via sibling
      `<DomainService>.build_and_create(...)` calls (or `Factory.*`)
- [ ] Exactly one call to the method under test per test
- [ ] Assertions cover model identity, model defaults, and DAO
      round-trip where applicable
- [ ] Exception paths use `pytest.raises(<ExactClass>)` and assert on
      `code` / `http_error_code` for domain exceptions
- [ ] No `commit()` calls; only `flush()` and `refresh()`
- [ ] One test per decision point in the method under test
