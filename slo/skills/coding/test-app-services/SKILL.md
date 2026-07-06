---
name: test-app-services
description: Patterns for testing application services with mocked dependencies and
  assert-on-invoke.
when_to_use: Use when writing or revising tests under tests/services/.
group: coding
kind: skill
source_prompt: test-app-services.md
---

# Test Application Services

## Skill summary

- **Name:** `test-app-services`
- **Description:** Patterns for testing application services with mocked dependencies and assert-on-invoke.
- **When to use:** Use when writing or revising tests under tests/services/.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `test-app-services.md`

## Examples

- The user asks: "Write or revise the tests covered by test app services."
- You finished coding and need the matching test convention before calling the work done.

## Guidance

How to write transactional unit tests for **application services** in the
standard service layer style. Application services live in
`src/services/<area>/service.py` (and
`src/services/api/<area>/...`) and orchestrate a workflow end-to-end
across multiple domain services. Their tests cover that orchestration
without going through HTTP.

> Application service tests sit between domain service tests and
> controller tests. Read this file in full before writing one — picking
> the wrong layer to test causes either silent gaps in coverage or
> over-broad tests that re-prove what other layers already prove.

---

## 1. What an application service test exercises

An application service test exercises a single workflow on the service
class — typically `await svc.invoke()` or one of its named entry methods
(`create`, `toggle`, `list_coupons`, `update_constraints`) — against the
real PostgreSQL database. It:

1. Builds prerequisite domain state (factory + `build_and_create`).
2. Constructs the application service with the same dependencies the
   controller would inject (account, user, campaign, db_session, optional
   sub-services).
3. Optionally constructs the form / params DAO with the same DAO type the
   controller passes.
4. Calls the entry method.
5. Asserts on the service's mutated public attributes (`svc.coupon`,
   `svc.campaign`) and the persisted DB state, OR on the raised exception.

It does **not** exercise:
- HTTP, middleware, auth, response envelope — that is for a controller
  test (`skills/coding/test-controllers/SKILL.md`).
- The lower-level domain service implementation details (filter SQL,
  default values, JSON serialization) — those have their own tests
  (`skills/coding/test-domain-services/SKILL.md`). Application service tests treat domain
  services as trusted collaborators.

---

## 2. File layout and naming

| Item | Convention |
|---|---|
| Test file location | `tests/services/<area>/test_<workflow>_app_service.py` mirroring `src/services/<area>/service.py` |
| API-side service tests | `tests/services/api/<area>/test_<workflow>_api_service.py` mirroring `src/services/api/<area>/service.py` |
| Test class | `class Test<Workflow>AppService:` (one class per service file) |
| Test method names | `test_<entry_method>_when_<condition>` — `test_create`, `test_create_when_campaign_is_not_active`, `test_create_when_campaign_is_not_owned_by_user`, `test_toggle`, `test_list_coupons` |
| Granularity | One test per `_check_*` / guard call inside the orchestrator, plus a happy-path test for each entry method |

---

## 3. Required fixtures and imports

Module-level imports stay minimal:

```python
import pytest

from tests.async_db import async_db_session
from tests.redis import async_redis_session, Redis
from sqlalchemy.orm.session import Session

# Optional — preload pure DAO modules used purely for type hints
from src.domains.verifications.service import SignupVerificationDAO
```

Every other import (the application service itself, sibling domain
services, factories, models, forms, exceptions) goes **inside** each
test function — same reason as for controller / domain service tests
(see `§7`).

The `async_redis_session` fixture is required only when the service
under test reaches Redis (cache, rate limit, queue). Pass it as a
parameter and the fixture flushes the test DB before yielding the
client.

---

## 4. Building the application service in a test

Application services take their collaborators as constructor arguments
so tests can substitute fakes. In practice — for the standard service layer — the
collaborators are *real* sibling domain services and the *real*
`async_db_session`. **Pass the constructor exactly what the controller
passes** so the test reflects production wiring:

```python
fact: FactoryInstance = await Factory.create_active_coupon(
    db_session=async_db_session,
)
user: User = fact.user
account: Account = fact.account
campaign: Campaign = fact.campaign
subscription: Subscription = fact.subscription

coupon_service: CouponAppService = CouponAppService(
    campaign=campaign,
    account=account,
    user=user,
    db_session=async_db_session,
)
```

If the application service has optional sub-service overrides
(`campaign_service`, `coupon_service`, `redemptions_service`,
`subscription_service`), leave them at default in tests. They exist for
production substitution, not test mocking.

---

## 5. Constructing form/params DAOs

For services that accept a WTForms-style `<Verb><Resource>Form`, build it
through the form's `from_formdata` classmethod with a `Request` shim so
validation runs identically to production:

```python
from fastapi import Request
from src.services.coupons.service import NewCouponForm
from src.domains.coupons.dao import COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE

new_coupon_form: NewCouponForm = await NewCouponForm.from_formdata(
    request=Request(
        scope={"type": "http", "method": "POST", "headers": {}},
    ),
    campaign_id=str(campaign.id),
    code="SUMMER_OFF_20",
    description="SUmmer 20% OFF",
    redemption_type=COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
    redemption_value=150,
    max_redemption_value=150,
    max_use_count=20,
    is_active="true",
)
await new_coupon_form.validate()
```

For services that accept a plain Pydantic params DAO
(`CouponClaimAPIParamsDAO`, `OrderParamsDAO`, etc.), construct the DAO
directly with the production type — never a dict:

```python
from src.services.api.coupons.service import CouponClaimAPIParamsDAO
from src.services.api.coupons.dao import OrderParamsDAO, CustomerParamsDAO

claim_params: CouponClaimAPIParamsDAO = CouponClaimAPIParamsDAO(
    coupon_code=coupon.code,
    order=OrderParamsDAO(
        order_id="merchant_order_12345",
        order_amount=Decimal(1200.00),
    ),
    customer=CustomerParamsDAO(customer_id=customer.customer_id),
)
```

---

## 6. Test structure — the canonical shape

Every application service test follows the same five blocks. Stick to
them; do not interleave.

```python
class TestCouponAppService:
    @pytest.mark.asyncio
    async def test_create(
        self, async_db_session: Session, async_redis_session: Redis,
    ):
        """
        WHEN a verified user exists.
        And WHEN the user campaign exists
        AND WHEN the campaign is active
        AND WHEN the user owns the campaign
        AND WHEN all the parameters for a new coupon have been passed
            It should create a new coupon
        """
        # ── Block 1: function-local imports (see §7) ──────────────────
        from tests.factories.factory import Factory, FactoryInstance
        from src.models.models import User, Account, Campaign, Subscription
        from src.services.coupons.service import (
            CouponAppService, NewCouponForm,
        )
        from src.domains.coupons.dao import COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE
        from fastapi import Request

        # ── Block 2: domain state via Factory + domain build_and_create ─
        fact: FactoryInstance = await Factory.create_active_coupon(
            db_session=async_db_session,
        )
        user: User = fact.user
        account: Account = fact.account
        campaign: Campaign = fact.campaign
        subscription: Subscription = fact.subscription

        # ── Block 3: instantiate the application service ──────────────
        coupon_service: CouponAppService = CouponAppService(
            campaign=campaign,
            account=account,
            user=user,
            db_session=async_db_session,
        )

        # ── Block 4: build params + invoke ────────────────────────────
        new_coupon_form: NewCouponForm = await NewCouponForm.from_formdata(
            request=Request(scope={"type": "http", "method": "POST", "headers": {}}),
            campaign_id=str(campaign.id),
            code="SUMMER_OFF_20",
            description="SUmmer 20% OFF",
            redemption_type=COUPON_REDEMPTION_TYPE_ABSOLUTE_VALUE,
            redemption_value=150,
            max_redemption_value=150,
            max_use_count=20,
            is_active="true",
        )
        await new_coupon_form.validate()

        await coupon_service.create(
            new_coupon_form=new_coupon_form, subscription=subscription,
        )

        # ── Block 5: assert mutated state on the service ──────────────
        assert coupon_service.coupon.id is not None
        assert coupon_service.coupon.code == "SUMMER_OFF_20"
        assert coupon_service.coupon.max_use_count == 20
        assert coupon_service.coupon.is_active is True
        assert coupon_service.coupon.description == "SUmmer 20% OFF"
```

### Block discipline

| Block | What goes in it | What MUST NOT go in it |
|---|---|---|
| 1. Imports | All function-local imports for symbols used in this test | HTTP clients (`httpx.AsyncClient`); `get_test_app` |
| 2. Setup | Factory + domain `build_and_create` calls | The application service constructor |
| 3. Construct | One `<Service>(...)` instantiation with production-shaped args | Patching sibling services with mocks (use real ones) |
| 4. Action | One `await svc.<entry_method>(...)` call (the unit under test) | Additional inserts/updates after the action begins |
| 5. Assert | Field assertions on `svc.<attr>`; DB-state assertions; raised-exception assertions | Constructing fresh state mid-assert |

### The `WHEN/AND WHEN` docstring

Each application service test must lead with a multi-line `WHEN/AND
WHEN/It should` docstring that names every precondition and the expected
outcome. This is the test's plain-English contract — keep it accurate
when you change the test.

---

## 7. Why imports live inside the test function

Same rationale as controller and domain service tests: module-level
imports of `src.services` and the FastAPI app trigger SQLAlchemy
model registration and Pydantic side effects at pytest collection time,
before the event loop and DB connection are wired up. Keep module-level
imports to `pytest`, fixture imports, type hints, and pure DAO modules.

---

## 8. Asserting orchestration outcomes

Application services typically expose their result on `self.<attr>`
(e.g. `coupon_service.coupon`, `coupon_service.campaign`). Assert
against those — not against the return value of the call — because the
service convention is to mutate `self` and return `self` for chaining:

```python
await coupon_service.create(
    new_coupon_form=new_coupon_form, subscription=subscription,
)
assert coupon_service.coupon.id is not None
assert coupon_service.coupon.code == "SUMMER_OFF_20"
```

For services that return a paginated DAO, assert on the returned object
directly:

```python
coupons: list[Coupon] = await coupon_service.list_coupons(page=1, limit=30)
assert len(coupons) == 2
```

For multi-step flows (claim → redeem → refresh), assert on each
transition's outcome inline:

```python
redemption_dao: RedemptionDAO = await coupon_api_service.claim(claim_params=claim_params)
redemption_dao = await coupon_api_service.redeem(redemption_id=redemption_dao.id)

await async_db_session.refresh(coupon)
assert redemption_dao.state == REDEMPTION_STATE_REDEEMED
assert coupon.used_count == 1
```

---

## 9. Testing each guard / `_check_*` step

Application services in the standard service layer are written in the declarative
style: `invoke()` (or each entry method) calls a sequence of
`_check_*` / `_load_*` / `_persist_*` private methods, and any of them
can `raise`. Every `raise` in the orchestrator is its own decision point
and must have a dedicated test.

For `CouponAppService.create()` the orchestrator is:

```python
async def create(self, new_coupon_form, subscription):
    self.new_coupon_form = new_coupon_form
    await self._check_campaign()
    await self._check_campaign_ownership()
    await self._check_campaign_active()
    await self._check_campaign_complete()
    await self._check_coupon_limit(subscription=subscription)
    await self._create_coupon_from_campaign()
    return self
```

Required tests, mapping one-to-one onto the guards:

| Branch | Test | Expected exception |
|---|---|---|
| Happy path | `test_create` | none |
| `_check_campaign_active` fails | `test_create_when_campaign_is_not_active` | `CampaignNotActiveError` |
| `_check_campaign_ownership` fails | `test_create_when_campaign_is_not_owned_by_user` | `CampaignAccountOwnershipError` |
| `_check_campaign_complete` fails | `test_create_when_campaign_end_date_has_passed` | `CampaignAlreadyCompletedError` |
| `_check_coupon_limit` fails | `test_create_when_campaign_has_reached_subscription_coupon_limits` | `SubscriptionCouponCountForCampaignReached` |
| `_create_coupon_from_campaign` IntegrityError | `test_create_when_coupon_code_is_duplicate` | `CouponDuplicateCodeException` |

```python
with pytest.raises(CampaignNotActiveError):
    await coupon_service.create(
        new_coupon_form=new_coupon_form, subscription=subscription,
    )
```

For domain-defined exceptions, also assert on `excinfo.value.code` and
`http_error_code` when those drive the API response:

```python
with pytest.raises(SubscriptionCouponCountForCampaignReached) as excinfo:
    await coupon_service.create(...)
assert excinfo.value.code == "error_coupon_limit_reached"
assert excinfo.value.http_error_code == 412
```

---

## 10. Inducing failure conditions

To trigger a guard, mutate the prerequisite state through the same
`db_session` and commit the mutation so the application service sees it
on the subsequent read:

```python
# Force the campaign inactive
campaign.is_active = False
async_db_session.add(campaign)
await async_db_session.commit()

with pytest.raises(CampaignNotActiveError):
    await coupon_service.create(
        new_coupon_form=new_coupon_form, subscription=subscription,
    )
```

For ownership failures, build a *second* user/account and pass them to
the service while keeping the original campaign:

```python
user1: User = await Factory.create_user(
    first_name="Grace",
    last_name="Hopper",
    email="grace.hopper@example.com",
    password="abcabcabc",
    db_session=async_db_session,
)
account1: Account = await Factory.create_account(
    user_id=user1.id, db_session=async_db_session, name="Company2",
)

# Service is constructed with user1/account1 but campaign belongs to fact.user/fact.account
coupon_service: CouponAppService = CouponAppService(
    campaign=campaign,      # belongs to original account
    account=account1,       # different account
    user=user1,
    db_session=async_db_session,
)

with pytest.raises(CampaignAccountOwnershipError):
    await coupon_service.create(
        new_coupon_form=new_coupon_form, subscription=subscription,
    )
```

For limit failures, drive the system into the limit through repeated
real calls to the service rather than seeding the DB by hand — this
proves both the limit check and the loop-stable accounting:

```python
for i in range(14):
    new_coupon_form = await NewCouponForm.from_formdata(
        request=Request(scope={"type": "http", "method": "POST", "headers": {}}),
        campaign_id=str(campaign.id),
        code=f"SUMMER_OFF_20{i}",
        ...
    )
    await new_coupon_form.validate()
    await coupon_service.create(
        new_coupon_form=new_coupon_form, subscription=subscription,
    )
    await async_db_session.flush()

with pytest.raises(SubscriptionCouponCountForCampaignReached):
    new_coupon_form = await NewCouponForm.from_formdata(...)
    await new_coupon_form.validate()
    await coupon_service.create(
        new_coupon_form=new_coupon_form, subscription=subscription,
    )
```

---

## 11. Reusing or rebuilding the service across actions

When a single test exercises multiple entry methods on the same service
(e.g. create, then toggle), **rebuild the service instance** between
calls. Application services hold per-call state on `self` and are not
designed to be reused for a second workflow:

```python
# 1. Create
coupon_service: CouponAppService = CouponAppService(
    campaign=campaign, account=account, user=user, db_session=async_db_session,
)
await coupon_service.create(new_coupon_form=new_coupon_form, subscription=subscription)
coupon: Coupon = coupon_service.coupon

# 2. Toggle — fresh instance
coupon_service: CouponAppService = CouponAppService(
    campaign=campaign, account=account, user=user, db_session=async_db_session,
)
await coupon_service.toggle(coupon_id=coupon.id, subscription=subscription)
assert coupon_service.coupon.is_active is False
```

---

## 12. The `autocommit` and `flush()` rules

Same as for domain service tests:

- Setup rows usually pass `autocommit=True`.
- Inside the test, prefer `await async_db_session.flush()` over
  `commit()` when you need the application service to see prior writes.
- Never call `await async_db_session.commit()` to "finalize" a test —
  the fixture wraps everything in a savepoint that gets rolled back.

The only sanctioned exception is when reproducing a guard condition that
*depends on a committed parent row* (see the `campaign.is_active = False`
example in §10). In that case the `commit()` is part of the
arrangement — the savepoint still rolls back the row at test end.

---

## 13. What every application service test must cover

For each entry method on the application service, write at minimum:

| Branch | Test |
|---|---|
| Happy path | One test that constructs valid params and asserts on the persisted result |
| Each `_check_*` / guard `raise` in the orchestrator | One test per guard, asserting the exact exception class (and `code` / `http_error_code` for `*Exception` types) |
| Each conditional inside the orchestrator (e.g. `if not is_active`) | One test per branch — see `skills/coding/test-verification-policy/SKILL.md` |
| Each public attribute the service mutates on `self` | Asserted in at least one happy-path test |
| Multi-step flows (claim → redeem) | One test per terminal state (claimed, redeemed, voided) |
| Limit / pagination methods | Build state above and below the boundary; assert both sides |

---

## 14. Running the tests

```bash
loadenv environments/test.env
loadenv environments/local.env

PYTHONPATH=${PWD} poetry run pytest -sv \
  tests/services/coupons/test_coupon_app_service.py::TestCouponAppService::test_create
```

Run the entire service test directory while iterating, then the full
suite before opening a PR — see `skills/coding/test-verification-policy/SKILL.md`.

---

## 15. Anti-patterns (do NOT do these)

- **Module-level imports of `src.services` / models / factories**
  — see §7.
- **Mocking sibling domain services** — application service tests are
  integration tests against the real DB. The whole point is to verify
  the orchestration uses the real domain services correctly. Patching
  hides drift between the app service and its collaborators.
- **Going through HTTP** — that is a controller test, not an app service
  test. If you need to assert response wrappers or middleware, write the
  controller test instead.
- **Skipping the `WHEN/AND WHEN` docstring** — it is the only place the
  full set of preconditions for a test is stated in plain language.
- **Reusing one application service instance across multiple actions**
  — see §11.
- **Asserting against `await svc.<entry_method>(...)`'s return value
  when the service mutates `self`** — assert on `svc.<attr>` instead.
  Many `*AppService` entry methods return `self` for chaining; relying
  on the return value masks state that did not actually settle on the
  service.
- **Constructing a form by passing a dict to `Form(**dict)`** — go
  through `await Form.from_formdata(request=...)` then
  `await form.validate()` so validators run.

---

## 16. Verification checklist

Before marking an application service test complete:

- [ ] File lives at `tests/services/<area>/test_<workflow>_app_service.py`
      mirroring the production location
- [ ] Class is named `Test<Workflow>AppService`
- [ ] Each test is `@pytest.mark.asyncio` and takes
      `async_db_session: Session` (and `async_redis_session: Redis` if the
      service touches Redis)
- [ ] Each test has a `WHEN/AND WHEN/It should` docstring stating the
      preconditions and expected outcome
- [ ] Module-level imports are limited to `pytest`, fixture imports,
      type hints, and pure DAO modules
- [ ] State is built via `Factory.create_*` and sibling
      `<DomainService>.build_and_create(...)` calls
- [ ] The application service is instantiated exactly once per test (or
      rebuilt between actions per §11) with the same constructor shape
      the controller uses
- [ ] Forms are built via `Form.from_formdata(request=...)` then
      `await form.validate()`; params DAOs are constructed with the
      production DAO type
- [ ] Action is a single `await svc.<entry_method>(...)` call (or one
      per logical step in a multi-step flow)
- [ ] Assertions cover service-mutated `self.<attr>` fields and DB state;
      exception paths use `pytest.raises(<ExactClass>)` with `code` /
      `http_error_code` checks for domain exceptions
- [ ] No `commit()` calls except where reproducing a parent-row
      precondition for a guard (per §12)
- [ ] One test per guard / `_check_*` step in the orchestrator and per
      conditional branch in the entry method
