---
name: typescript-code-test-loop
description: TypeScript behavioral increments with focused verification and project-scoped final gates.
when_to_use: Use when implementing TypeScript features or fixes in verified behavioral increments.
group: languages
kind: skill
---

# TypeScript Code-Test Loop

## Skill summary

- **Name:** `typescript-code-test-loop`
- **Description:** TypeScript behavioral increments with focused verification and project-scoped final gates.
- **When to use:** Implement TypeScript features or fixes in verified behavioral increments.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Implement the OrderService with tests"
- "Add the refund logic and make sure it's covered"
- "Walk through the code-test loop for this feature"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test (levels, doubles, journeys). This skill covers TypeScript cadence only.

### The loop in six steps

```
1. Select one observable behavior and its existing/missing evidence
2. Implement and test the increment in project/user-approved order
3. Cover meaningful decisions and relevant failure paths
4. Run focused tests using the project routing commands
5. Diagnose failures against the contract; verify the correction
6. Run affected suites at milestones and required full gates before acceptance
```

Never leave a failing test behind. Never move to the next unit of work until the current one is green.

### Step 1: Write the production code

Implement a small cohesive behavior, potentially across a few files. Preserve TypeScript declarative-method conventions; method boundaries need not define test increments. Implementation-first is permitted by the default cadence, but never overrides user/project test-first requirements. Follow `skills/coding/code-test-loop/SKILL.md`.

### Step 2: Identify every decision point

After writing, scan the code for every branch:

```typescript
// Example service method with 4 decision points:
async processOrder({ orderId, userId }: { orderId: string; userId: string }): Promise<OrderDAO> {
  const order: OrderDAO | null = await this.options.orderRepo.findById({ id: orderId }) // ① may be null
  if (!order) throw new NotFoundError(`Order ${orderId} not found`)

  if (order.status !== 'pending') {                                                      // ② status check
    throw new ConflictError(`Order is already ${order.status}`)
  }

  const user: UserDAO | null = await this.options.userRepo.findById({ id: userId })      // ③ may be null
  if (!user) throw new NotFoundError(`User ${userId} not found`)

  const charged: ChargeDAO = await this.options.paymentClient.charge({                   // ④ may throw (third-party)
    userId,
    amount: order.totalAmount,
  })

  return this.options.orderRepo.update({ id: orderId, changes: { status: 'completed', chargeId: charged.id } })
}
```

Decision points found:
1. `order` is null → NotFoundError
2. `order.status !== 'pending'` → ConflictError
3. `user` is null → NotFoundError
4. `paymentClient.charge` throws → propagate

These are the outcomes to prove: four failure outcomes plus the happy path.

### Step 3: Write one test per path

Add missing behavioral evidence and run focused tests promptly. Existing tests may already cover paths; one test can traverse multiple branches. The example illustrates meaningful outcomes, not a mandatory branch-to-test formula.

- Repositories are real and run against the test database; `resetTestDatabase()` runs in `beforeEach`.
- Only `paymentClient` (a third-party API) is faked, through an injected class that implements `PaymentClient`. `msw` against the real client is an equally valid choice.
- Assert outcomes: returned value, persisted order read back, recorded charges.

```typescript
// tests/services/order.service.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { db } from '@/connectors/db'
import type { ChargeDAO, ChargeInput, PaymentClient } from '@/clients/payment.client'
import { OrderRepository } from '@/domains/order/order.repository'
import { UserRepository } from '@/domains/user/user.repository'
import { ConflictError, NotFoundError } from '@/errors'
import { OrderService } from '@/services/order.service'
import { buildCreateOrderInput, buildCreateUserInput } from '../helpers/factories'
import { resetTestDatabase } from '../helpers/db'

/** Third-party fake: records charges and returns a fixed charge id. */
class RecordingPaymentClient implements PaymentClient {
  readonly charges: ChargeInput[] = []

  async charge(input: ChargeInput): Promise<ChargeDAO> {
    this.charges.push(input)
    return { id: 'charge-99' }
  }
}

/** Third-party fake: every charge is declined. */
class DecliningPaymentClient implements PaymentClient {
  async charge(_input: ChargeInput): Promise<ChargeDAO> {
    throw new Error('Card declined')
  }
}

describe('OrderService.processOrder', (): void => {
  let orderRepo: OrderRepository
  let userRepo: UserRepository
  let paymentClient: RecordingPaymentClient
  let user: UserDAO

  const buildService = ({ paymentClient }: { paymentClient: PaymentClient }): OrderService =>
    new OrderService({ orderRepo, userRepo, paymentClient })

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    orderRepo = new OrderRepository({ db })
    userRepo = new UserRepository({ db })
    paymentClient = new RecordingPaymentClient()
    user = await userRepo.create({ input: buildCreateUserInput() })
  })

  // Happy path
  it('charges the user and persists the completed order when the order is pending', async (): Promise<void> => {
    const order: OrderDAO = await orderRepo.create({ input: buildCreateOrderInput({ totalAmount: 100 }) })

    const result: OrderDAO = await buildService({ paymentClient }).processOrder({ orderId: order.id, userId: user.id })

    expect(result).toMatchObject({ status: 'completed', chargeId: 'charge-99' })
    expect(await orderRepo.findById({ id: order.id })).toMatchObject({ status: 'completed', chargeId: 'charge-99' })
    expect(paymentClient.charges).toEqual([{ userId: user.id, amount: 100 }])
  })

  // ① order not found
  it('throws NotFoundError and charges nothing when the order does not exist', async (): Promise<void> => {
    await expect(
      buildService({ paymentClient }).processOrder({ orderId: 'missing', userId: user.id }),
    ).rejects.toThrow(NotFoundError)
    expect(paymentClient.charges).toEqual([])
  })

  // ② order already processed
  it('throws ConflictError and charges nothing when the order status is not pending', async (): Promise<void> => {
    const order: OrderDAO = await orderRepo.create({ input: buildCreateOrderInput({ status: 'completed' }) })

    await expect(
      buildService({ paymentClient }).processOrder({ orderId: order.id, userId: user.id }),
    ).rejects.toThrow(ConflictError)
    expect(paymentClient.charges).toEqual([])
  })

  // ③ user not found
  it('throws NotFoundError and leaves the order pending when the user does not exist', async (): Promise<void> => {
    const order: OrderDAO = await orderRepo.create({ input: buildCreateOrderInput() })

    await expect(
      buildService({ paymentClient }).processOrder({ orderId: order.id, userId: 'missing' }),
    ).rejects.toThrow(NotFoundError)
    expect(paymentClient.charges).toEqual([])
    expect(await orderRepo.findById({ id: order.id })).toMatchObject({ status: 'pending' })
  })

  // ④ payment client throws
  it('propagates the payment error and leaves the order pending when the charge is declined', async (): Promise<void> => {
    const order: OrderDAO = await orderRepo.create({ input: buildCreateOrderInput() })

    await expect(
      buildService({ paymentClient: new DecliningPaymentClient() }).processOrder({ orderId: order.id, userId: user.id }),
    ).rejects.toThrow('Card declined')
    expect(await orderRepo.findById({ id: order.id })).toMatchObject({ status: 'pending', chargeId: null })
  })
})
```

### Step 4: Run only the changed file

```bash
pnpm vitest run tests/services/order.service.test.ts
# or
npx vitest run tests/services/order.service.test.ts
```

This is fast. Run it immediately after writing the tests. You will often see failures.

### Step 5: Fix failures

Common failure categories and their fixes:

**Incorrect test oracle (establish from the contract, not from current output):**
```bash
AssertionError: expected "charge-98" to equal "charge-99"
# → the payment fake returned the wrong fixture value; fix the fake
```

**Code is wrong:**
```bash
TypeError: Cannot read properties of null (reading 'status')
# → forgot to guard against null before accessing .status
```

**Fake is incomplete:**
```bash
TypeError: this.options.paymentClient.refund is not a function
# → the third-party fake does not implement the full PaymentClient interface; add the method
```

**Test data is missing:**
```bash
NotFoundError: User user-1 not found
# → the test did not seed the row; create it through the real repository in the test

Never silently skip a failing test. Either fix the code or fix the test — but understand which one is wrong before changing anything.

### Step 6: Run the full suite

At coherent milestones run affected suites; before final acceptance run all required project gates. For a Vitest project, for example:

```bash
pnpm vitest run
```

Introduced regressions block acceptance. Required gates must pass; baseline exclusions require explicit approval, and blocked checks remain unverified.

### Vitest CLI reference

```bash
# Run a single test file
pnpm vitest run tests/services/order.service.test.ts

# Run all tests matching a pattern
pnpm vitest run --reporter=verbose order

# Watch mode — re-runs on file save
pnpm vitest

# Run with coverage
pnpm vitest run --coverage

# Run a specific test by name (partial match)
pnpm vitest run -t "throws NotFoundError"

# Verbose output (shows all test names)
pnpm vitest run --reporter=verbose
```

### Anti-patterns to avoid

| Anti-pattern | Why it breaks the loop |
|---|---|
| Writing all code before any tests | You lose track of which decision points need coverage |
| Running tests after every line | Verify a coherent behavior rather than following a line-count ritual |
| Skipping the full suite run | A local green does not mean no regressions |
| Using `.skip` to silence a failure | The failure is still there — you just can't see it |
| Writing "it ran" tests | `expect(result).toBeDefined()` doesn't test any decision |
| Testing the mock, not the code | `expect(repo.create).toHaveBeenCalled()` instead of reading the persisted row back |
| Mocking repositories or internal services | A mocked repository proves nothing about queries, constraints or transactions |

### Checklist before marking a unit of work complete

- [ ] Meaningful changed decisions, required outcomes and critical failure paths have passing evidence
- [ ] The targeted test file runs green: `pnpm vitest run <file>`
- [ ] Affected suites pass at milestones; required full gates pass before final acceptance
- [ ] No `.skip` or `.todo` left without an explanatory comment
- [ ] Test names describe the specific path, not just the method
- [ ] Repositories run against the test database; only third-party clients are faked
- [ ] Guard clause tests assert no later effect: no recorded third-party call and no changed row
