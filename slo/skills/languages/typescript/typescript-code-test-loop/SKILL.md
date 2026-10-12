---
name: typescript-code-test-loop
description: TypeScript code-test loop — the cycle of write code, identify decision points, write one
  test per path, run the suite, fix failures, repeat.
when_to_use: Use when implementing any TypeScript feature or fix to enforce the discipline of testing
  each decision point before moving to the next unit of work.
group: languages
kind: skill
---

# TypeScript Code-Test Loop

## Skill summary

- **Name:** `typescript-code-test-loop`
- **Description:** TypeScript code-test loop — the cycle of write code, identify decision points, write one test per path, run the suite, fix failures, repeat.
- **When to use:** Use when implementing any TypeScript feature or fix to enforce the discipline of testing each decision point before moving to the next unit of work.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Implement the OrderService with tests"
- "Add the refund logic and make sure it's covered"
- "Walk through the code-test loop for this feature"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### The loop in six steps

```
1. Write or modify the production code
2. Identify every decision point in what you just wrote
3. Write one test per path BEFORE running the suite
4. Run only the file you changed: pnpm vitest run path/to/file.test.ts
5. Fix any failures — code or test — until all pass
6. Run the full suite: pnpm vitest run
```

Never leave a failing test behind. Never move to the next unit of work until the current one is green.

### Step 1: Write the production code

Write the method or function. Keep it small and focused — one decision per method (see the declarative method structure convention). Resist the urge to run the tests first; write the code so you can identify what needs covering.

### Step 2: Identify every decision point

After writing, scan the code for every branch:

```typescript
// Example service method with 4 decision points:
async processOrder(orderId: string, userId: string): Promise<OrderResult> {
  const order = await this.orderRepo.findById(orderId)  // ① may be null
  if (!order) throw new NotFoundError(`Order ${orderId} not found`)

  if (order.status !== 'pending') {                      // ② status check
    throw new ConflictError(`Order is already ${order.status}`)
  }

  const user = await this.userRepo.findById(userId)      // ③ may be null
  if (!user) throw new NotFoundError(`User ${userId} not found`)

  const charged = await this.paymentClient.charge({      // ④ may throw
    userId,
    amount: order.totalAmount,
  })

  return this.orderRepo.update(orderId, { status: 'completed', chargeId: charged.id })
}
```

Decision points found:
1. `order` is null → NotFoundError
2. `order.status !== 'pending'` → ConflictError
3. `user` is null → NotFoundError
4. `paymentClient.charge` throws → propagate

That means **4 tests beyond the happy path**, plus **1 happy path test** = **5 tests total**.

### Step 3: Write one test per path

Write all tests before running any of them. This forces you to think about the design before verifying it.

```typescript
// tests/services/order.service.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { OrderService } from '../../src/services/order.service'
import { NotFoundError, ConflictError } from '../../src/errors'

const makeOrderRepo = () => ({ findById: vi.fn(), update: vi.fn() })
const makeUserRepo = () => ({ findById: vi.fn() })
const makePaymentClient = () => ({ charge: vi.fn() })

const buildOrder = (overrides = {}) => ({
  id: 'order-1',
  totalAmount: 100,
  status: 'pending',
  ...overrides,
})

const buildUser = (overrides = {}) => ({
  id: 'user-1',
  name: 'Alice',
  ...overrides,
})

describe('OrderService.processOrder', () => {
  let orderRepo: ReturnType<typeof makeOrderRepo>
  let userRepo: ReturnType<typeof makeUserRepo>
  let paymentClient: ReturnType<typeof makePaymentClient>
  let service: OrderService

  beforeEach(() => {
    orderRepo = makeOrderRepo()
    userRepo = makeUserRepo()
    paymentClient = makePaymentClient()
    service = new OrderService(orderRepo, userRepo, paymentClient)
    vi.clearAllMocks()
  })

  // Happy path
  it('charges the user and marks the order as completed when input is valid', async () => {
    const order = buildOrder()
    const user = buildUser()
    vi.mocked(orderRepo.findById).mockResolvedValue(order)
    vi.mocked(userRepo.findById).mockResolvedValue(user)
    vi.mocked(paymentClient.charge).mockResolvedValue({ id: 'charge-99' })
    vi.mocked(orderRepo.update).mockResolvedValue({ ...order, status: 'completed', chargeId: 'charge-99' })

    const result = await service.processOrder('order-1', 'user-1')

    expect(result.status).toBe('completed')
    expect(result.chargeId).toBe('charge-99')
    expect(paymentClient.charge).toHaveBeenCalledWith({ userId: 'user-1', amount: 100 })
    expect(orderRepo.update).toHaveBeenCalledWith('order-1', { status: 'completed', chargeId: 'charge-99' })
  })

  // ① order not found
  it('throws NotFoundError when the order does not exist', async () => {
    vi.mocked(orderRepo.findById).mockResolvedValue(null)

    await expect(service.processOrder('missing', 'user-1')).rejects.toThrow(NotFoundError)
    expect(userRepo.findById).not.toHaveBeenCalled()
    expect(paymentClient.charge).not.toHaveBeenCalled()
  })

  // ② order already processed
  it('throws ConflictError when the order status is not pending', async () => {
    vi.mocked(orderRepo.findById).mockResolvedValue(buildOrder({ status: 'completed' }))

    await expect(service.processOrder('order-1', 'user-1')).rejects.toThrow(ConflictError)
    expect(userRepo.findById).not.toHaveBeenCalled()
    expect(paymentClient.charge).not.toHaveBeenCalled()
  })

  // ③ user not found
  it('throws NotFoundError when the user does not exist', async () => {
    vi.mocked(orderRepo.findById).mockResolvedValue(buildOrder())
    vi.mocked(userRepo.findById).mockResolvedValue(null)

    await expect(service.processOrder('order-1', 'missing')).rejects.toThrow(NotFoundError)
    expect(paymentClient.charge).not.toHaveBeenCalled()
  })

  // ④ payment client throws
  it('propagates payment errors and does not update the order', async () => {
    vi.mocked(orderRepo.findById).mockResolvedValue(buildOrder())
    vi.mocked(userRepo.findById).mockResolvedValue(buildUser())
    vi.mocked(paymentClient.charge).mockRejectedValue(new Error('Card declined'))

    await expect(service.processOrder('order-1', 'user-1')).rejects.toThrow('Card declined')
    expect(orderRepo.update).not.toHaveBeenCalled()
  })
})
```

### Step 4: Run only the changed file

```bash
pnpm vitest run src/services/order.service.test.ts
# or
npx vitest run src/services/order.service.test.ts
```

This is fast. Run it immediately after writing the tests. You will often see failures.

### Step 5: Fix failures

Common failure categories and their fixes:

**Test is wrong (most common when code is fresh):**
```bash
AssertionError: expected "charge-98" to equal "charge-99"
# → the mock returned the wrong fixture value; fix the mock
```

**Code is wrong:**
```bash
TypeError: Cannot read properties of null (reading 'status')
# → forgot to guard against null before accessing .status
```

**Mock is incomplete:**
```bash
TypeError: userRepo.findById is not a function
# → factory function is missing a method; add it to makeUserRepo()
```

Never silently skip a failing test. Either fix the code or fix the test — but understand which one is wrong before changing anything.

### Step 6: Run the full suite

Before you declare the unit of work done:

```bash
pnpm vitest run
```

A change that fixes five tests but breaks two others is not done. The suite must be fully green.

### Vitest CLI reference

```bash
# Run a single test file
pnpm vitest run src/services/order.service.test.ts

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
| Running tests after every line | Context switching kills focus; write all tests for a method first |
| Skipping the full suite run | A local green does not mean no regressions |
| Using `.skip` to silence a failure | The failure is still there — you just can't see it |
| Writing "it ran" tests | `expect(result).toBeDefined()` doesn't test any decision |
| Testing the mock, not the code | `expect(repo.create).toHaveBeenCalled()` without asserting the outcome |

### Checklist before marking a unit of work complete

- [ ] Every decision point in the changed code has a test
- [ ] The targeted test file runs green: `pnpm vitest run <file>`
- [ ] The full suite runs green: `pnpm vitest run`
- [ ] No `.skip` or `.todo` left without an explanatory comment
- [ ] Test names describe the specific path, not just the method
- [ ] Guard clause tests verify downstream mocks were NOT called
