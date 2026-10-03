---
name: test-controllers
description: Python FastAPI router integration tests via httpx.AsyncClient, real application middleware
  and isolated database state.
when_to_use: For Python projects only. Use when writing or revising tests under tests/routers/.
group: languages
kind: skill
source_prompt: test-controllers.md
---

# Test Controllers (Routers / API Endpoints)

## Skill summary

- **Name:** `test-controllers`
- **Description:** Patterns for testing FastAPI routers/controllers via httpx.AsyncClient and a real test AsyncSession.
- **When to use:** Use when writing or revising tests under tests/routers/.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `test-controllers.md`

## Examples

- The user asks: "Write or revise the tests covered by test controllers."
- You finished coding and need the matching test convention before calling the work done.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

How to write transactional, end-to-end controller (FastAPI router) tests in
the standard service layer style. These tests boot the real FastAPI app, swap in the
test `AsyncSession`, hit the route over HTTP via `httpx.AsyncClient`, and
assert on both the HTTP envelope and the resulting database state.

> Read this file in full **before** writing any controller test. Controller
> tests have a non-trivial setup (custom middleware swap, factory wiring,
> savepoint-based rollback) — skipping a step silently breaks isolation or
> auth.

---

## 1. What a controller test exercises

A controller test exercises the **full request stack** for a single route:

1. The router function (`src/routers/api/<thing>_controller.py`)
2. All middleware that survives the test swap (auth, CORS, request ctx,
   activity logging) — only the production `db_session_middleware` /
   `DbMiddleware` is replaced
3. The application or domain services the router invokes
4. The real database — every `INSERT`, `UPDATE`, query and constraint
   actually runs against PostgreSQL

It does **not** exercise:
- The production DB middleware (replaced by a test middleware that injects
  the test session — see `§4`)
- An external HTTP server — `httpx.AsyncClient(app=api, ...)` rides ASGI
  in-process; no port is opened

If your test only verifies router → service plumbing without hitting
auth, response wrappers, or the response envelope, write an **application
service test** instead — see `skills/languages/python/test-app-services/SKILL.md`.

---

## 2. File layout and naming

| Item | Convention |
|---|---|
| Test file location | `tests/routers/<api\|app>/test_<resource>_controller.py` mirroring `src/routers/<api\|app>/<resource>_controller.py` |
| Test class | `class Test<Resource>APIController:` (one class per controller file) |
| Test method names | `test_<route>_when_<condition>` — e.g. `test_available_coupons_when_customer_id_is_passed_and_no_coupon_redeemed` |
| One assertion per concern | Each test exercises one decision point in the route — happy path, each error branch, each conditional sub-flow |

---

## 3. Required fixtures and imports

Every controller test module starts with the same imports:

```python
import pytest

from tests.async_db import async_db_session            # the rollback-isolated AsyncSession fixture
from tests.redis import async_redis_session, Redis     # only if the route uses Redis
from sqlalchemy.orm.session import Session             # type-hint convenience
```

> **Why module-level imports stop here:** every other import (factories,
> models, services, the FastAPI `api`, `get_test_app`, `httpx.AsyncClient`)
> happens **inside** each test function. This is intentional — see `§7`.

The `async_db_session` fixture is defined in [tests/async_db.py](../../../tests/async_db.py)
and yields a savepoint-scoped `AsyncSession` whose outer transaction is
rolled back after the test. **Always pass it as the first parameter after
`self`.**

```python
class TestCouponsAPIController:
    @pytest.mark.asyncio
    async def test_available_coupons(self, async_db_session):
        ...
```

---

## 4. The test app and the middleware swap

`tests/async_db.py` exposes `get_test_app(app, dbsession)` which is the
**only** sanctioned way to obtain a FastAPI app for HTTP testing. It does
two things:

1. Walks `app.user_middleware` and replaces the production
   `db_session_middleware` (and any class-based `DbMiddleware`) with a test
   middleware that sets `request.state.db = dbsession`.
2. Rebuilds `app.middleware_stack`.

This is critical — without it the route would commit through a *different*
session than the one the test rolled back, and your inserts would either
leak into the database or be invisible inside the test.

```python
from tests.async_db import get_test_app
from src.main import api      # the API FastAPI() instance
# from src.main import app    # only for /orders/app routes

app = await get_test_app(app=api, dbsession=async_db_session)
```

**Rule:** import `api` from `src.main` for `/api/v1/*` routes and
`app` for the mounted `/orders/app` admin routes. Never construct your
own `FastAPI()` for tests.

---

## 5. Building HTTP requests with httpx.AsyncClient

Use `httpx.AsyncClient(app=app, base_url="http://test")` inside an
`async with` block. The base URL is irrelevant — it just satisfies httpx
— but the path you call must be the **full** route (including
`/api/v1/...` prefix declared on the `APIRouter`).

```python
async with AsyncClient(app=app, base_url="http://test") as client:
    response = await client.get(
        f"/api/v1/coupons/available?order_amount=120.33",
        headers={
            "X-ACCESS-KEY-ID": access_keys.access_key_id,
            "Content-Type": "application/json",
        },
    )
```

### Authentication

Routes that depend on `current_account`/`current_subscription` require an
`X-ACCESS-KEY-ID` header. That header must be the
`access_token.access_key_id` produced by the factory. The `Factory`
helpers (`Factory.create_active_coupon`) return a `FactoryInstance` whose
`access_keys` attribute is the `AccessToken` to use:

```python
fact: FactoryInstance = await Factory.create_active_coupon(
    db_session=async_db_session
)
access_keys: AccessToken = fact.access_keys

headers={
    "X-ACCESS-KEY-ID": access_keys.access_key_id,
    "Content-Type": "application/json",
}
```

To assert auth failure, pass a bogus value:

```python
headers={"X-ACCESS-KEY-ID": "randomString", "Content-Type": "application/json"}
# expect response.status_code == 401
# expect errors["code"] == "error_unauthorized"
```

### POST / PUT bodies

Pass `json=...` and use the *exact* request DAO the controller declares so
you do not accidentally test FastAPI's validator instead of the route:

```python
from src.services.api.coupons.service import CouponClaimAPIParamsDAO

response = await client.post(
    "/api/v1/coupons/claim",
    json=CouponClaimAPIParamsDAO(...).dict(),
    headers=headers,
)
```

---

## 6. Test structure — the canonical shape

Every controller test follows the same five-block shape. Stick to it; do
not interleave.

```python
class TestCouponsAPIController:
    @pytest.mark.asyncio
    async def test_available_coupons_when_customer_id_is_passed_and_no_coupon_redeemed(
        self, async_db_session
    ):
        # ── Block 1: function-local imports (see §7) ──────────────────
        from httpx import AsyncClient
        from tests.async_db import get_test_app
        from src.main import api
        from decimal import Decimal
        from tests.factories.factory import Factory, FactoryInstance
        from src.models.models import Account, Coupon, Campaign, AccessToken
        from src.domains.coupons.dao import COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE
        from src.services.api.coupons.service import (
            CouponService,
            CustomerService,
            Customer,
        )
        from utils.datetime_support import (
            tz_now, days_ago, days_after, asia_kolkata, datetime,
        )

        # ── Block 2: build domain state via Factory + domain services ─
        now: datetime = tz_now().astimezone(asia_kolkata)
        start_date: datetime = days_ago(dt=now, days=3)
        end_date: datetime = days_after(dt=start_date, days=21)

        fact: FactoryInstance = await Factory.create_active_coupon(
            db_session=async_db_session,
        )
        account: Account = fact.account
        coupon1: Coupon = fact.coupon
        campaign: Campaign = fact.campaign
        access_keys: AccessToken = fact.access_keys

        customer: Customer = await CustomerService.build_and_create(
            account_id=account.id,
            customer_id="customer_12345",
            db_session=async_db_session,
        )

        coupon2: Coupon = await CouponService.build_and_create(
            code="MY_SECOND_COUPON",
            campaign_id=campaign.id,
            start_date=start_date,
            end_date=end_date,
            redemption_type=COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
            redemption_value=Decimal(20.00),
            max_redemption_value=Decimal(20.00),
            timezone="Asia/Kolkata",
            is_active=True,
            db_session=async_db_session,
        )

        # ── Block 3: build the test app with the middleware swap ──────
        app = await get_test_app(app=api, dbsession=async_db_session)

        # ── Block 4: make the HTTP call ───────────────────────────────
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/coupons/available"
                f"?order_amount=120.33&customer_id={customer.id}",
                headers={
                    "X-ACCESS-KEY-ID": access_keys.access_key_id,
                    "Content-Type": "application/json",
                },
            )

            # ── Block 5: assert HTTP status, envelope, and payload ────
            assert response.status_code == 200
            response_body: dict = response.json()
            data: dict = response_body.get("data")
            assert len(data["available_coupons"]) == 2
            for coupon in data["available_coupons"]:
                assert coupon["code"] in [coupon1.code, coupon2.code]
```

### Block-by-block discipline

| Block | What goes in it | What MUST NOT go in it |
|---|---|---|
| 1. Imports | All function-local imports needed by this test | `import` statements for symbols you don't actually use |
| 2. Setup | Factory calls, additional domain `build_and_create` calls, time-window construction | Mocks, patches, HTTP calls |
| 3. Test app | A single `await get_test_app(app=api, dbsession=async_db_session)` call | Constructing your own `FastAPI()` instance |
| 4. HTTP | One `async with AsyncClient(...)` block, one or more `client.<verb>(...)` calls | Direct service calls — those belong in setup |
| 5. Assert | Status code, envelope shape (`data` / `errors`), payload field assertions | New DB inserts (creates fresh state mid-assert is a red flag) |

---

## 7. Why imports live inside the test function

Module-level imports of `src.main`, services, models, and factories
trigger SQLAlchemy model registration and FastAPI app construction at
**collection time** — before the test event loop, the test DB connection,
or any environment overrides have settled. This is the cause of the
"models registered twice" / "session is bound to a different connection"
classes of failure.

**Rule:** imports that touch SQLAlchemy models, the FastAPI `api`/`app`
objects, factories, or domain services live **inside the test function**.
Only `pytest`, the fixture imports (`async_db_session`, `async_redis_session`),
and pure type imports (`Session` for hints) live at module level.

---

## 8. Asserting the response envelope

Every API response in the standard service layer follows the wrapper shape produced by
`success_response()` / `failure_response()` in `base_controller.py`:

```json
{
  "data":  { ... },
  "errors": { "msg": [], "code": null },
  "api_version": "1.0"
}
```

Always assert in this order:

1. `response.status_code` — the contract with the client
2. `response_body["errors"]["code"]` for failure paths — the *machine-readable* error code, not the message
3. Specific `data` fields — never `assert response_body == {...}` against a giant fixture; assert the fields that prove behavior

```python
# Failure path
assert response.status_code == 412
errors: dict = response.json()["errors"]
assert errors["code"] == "error_coupon_already_used_once"

# Success path
assert response.status_code == 200
data: dict = response.json()["data"]
assert data["eligible"] is True
assert data["coupon_code"] == coupon2.code
assert data["customer_id"] == customer.customer_id
```

---

## 9. Asserting database state after the call

When the controller mutates state, refresh the SQLAlchemy instance and
assert against it. Do this **before** the `async with AsyncClient` block
exits if you need to query through the same session — the test session
is shared between setup and the route via `request.state.db`.

```python
await async_db_session.refresh(coupon)
assert coupon.used_count == 1
```

If you build prerequisite redemptions through the application service
(e.g. to test "available coupons excludes already-redeemed ones"),
flush after each mutation so subsequent SQL sees the change:

```python
redemption_dao = await coupon_api_service.claim(claim_params=claim_params)
redemption_dao = await coupon_api_service.redeem(redemption_id=redemption_dao.id)
await async_db_session.flush()
```

---

## 10. What every controller test must cover

For each route, write at least the following tests. One test per branch.

| Branch | Test |
|---|---|
| Auth — missing/invalid `X-ACCESS-KEY-ID` | `test_<route>_invalid_authentication_header` → expect `401` and `errors.code == "error_unauthorized"` |
| Happy path — required params only | `test_<route>` → expect `200` and assert each top-level `data` field |
| Each optional/conditional query param | One test per param that changes the route's behavior (e.g. `customer_id` present vs absent, `merchant_id` filter) |
| Each documented error code in the controller docstring | One test that triggers it, asserting both `status_code` and `errors.code` |
| Each branch in the controller body | If the controller has an `if page < 1`, write a test for `page=0`. If it forks on `customer_id`, write both forks. |

For any state-mutating route (POST/PUT/DELETE), additionally:

- Assert the response payload matches the new state
- Reload the affected row and assert the persisted columns
- Where applicable, count rows that should/should not exist

---

## 11. Running the tests

```bash
loadenv environments/test.env          # PYTHONPATH + DB_URL_ASYNC for orders_test
loadenv environments/local.env         # local overrides if needed

PYTHONPATH=${PWD} poetry run pytest -sv \
  tests/routers/api/test_coupons_controller.py::TestCouponsAPIController::test_available_coupons
```

Run the whole class while iterating, then the full suite before opening a
PR — see `skills/coding/test-verification-policy/SKILL.md`.

---

## 12. Anti-patterns (do NOT do these)

- **Module-level imports of `src.main` / models / factories** — see §7.
- **Constructing your own `FastAPI()` or `TestClient`** — must use
  `get_test_app(app=api, dbsession=async_db_session)` so the DB middleware
  is swapped.
- **Calling `await async_db_session.commit()` to "make the route see the
  data"** — the test fixture uses savepoints; a flush is enough, and a
  commit can release the outer rollback boundary.
- **Asserting against the entire response body with one equality check**
  — the response envelope changes (timestamps, generated UUIDs, ordering).
  Assert the specific fields that prove behavior.
- **Using `requests` or `httpx.Client` (sync)** — the app is async; use
  `httpx.AsyncClient` with `app=...` for in-process ASGI.
- **Mocking domain services in a controller test** — controller tests are
  end-to-end against a real DB. If you find yourself patching the service
  layer, write an application service test instead.
- **Skipping the `errors.code` assertion on failure paths** — `errors.code`
  is the API contract; the human-readable `msg` is not.

---

## 13. Verification checklist

Before marking a controller test complete:

- [ ] Class is named `Test<Resource>APIController` and lives at
      `tests/routers/<api|app>/test_<resource>_controller.py`
- [ ] Each test method is `@pytest.mark.asyncio` and takes
      `async_db_session` (and `async_redis_session` if the route uses Redis)
- [ ] All non-fixture imports are inside the test function body
- [ ] State is built via `Factory.create_*` or domain
      `<Service>.build_and_create(...)`, never raw SQL/ORM `.add()`
- [ ] The test app is built with
      `await get_test_app(app=api, dbsession=async_db_session)` exactly once
- [ ] The HTTP call is wrapped in `async with AsyncClient(app=app, base_url="http://test")`
- [ ] Auth headers use `access_keys.access_key_id` from the factory
      (or a bogus value for the `401` test)
- [ ] Assertions cover `status_code`, `errors.code` (on failure) or
      specific `data` fields (on success)
- [ ] For mutating routes, post-call DB state is asserted via
      `async_db_session.refresh(...)` then field-level checks
- [ ] One test per decision point in the controller and per documented
      error code
