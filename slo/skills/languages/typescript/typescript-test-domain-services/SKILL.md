---
name: typescript-test-domain-services
description: TypeScript domain service test conventions — test business rules against the real test database through the real repository, with factory helpers and canonical fixture names.
when_to_use: Use when writing tests for domain service classes or functions that contain business logic
  and depend on a repository or DAO layer.
group: languages
kind: skill
---

# TypeScript Test Domain Services

## Skill summary

- **Name:** `typescript-test-domain-services`
- **Description:** TypeScript domain service test conventions — test business rules against the real test database through the real repository, with factory helpers and canonical fixture names.
- **When to use:** Use when writing tests for domain service classes or functions that contain business logic and depend on a repository or DAO layer.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the UserService"
- "Add tests for the domain service methods"
- "Test the create and update rules against the database"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. This recipe covers TypeScript mechanics only.

- This recipe is level 3 (domain service) in the policy's test levels.
- Prefer journey tests (`typescript-test-controllers`) and application-service tests (`typescript-test-app-services`) for most coverage. Use this level for dense business rules.
- Coverage follows the policy's "What Must Be Tested".

### Core rule

- Domain service tests **use the real repository against the real test database**.
- Never `vi.mock` the repository, the database client (`@/connectors/db`) or the ORM.
- Assert on what the service decided **and** on what was persisted, read back through the repository.
- The only doubles allowed here are third-party API clients, intercepted with `msw` or passed in as fakes, and internal collaborators such as a clock, passed in through the constructor.

### Structure

- One `describe` block per service method, with `it` blocks for each distinct outcome.
- Factory helpers live in `tests/helpers/factories.ts`, not inline.
- `beforeEach` calls `resetTestDatabase()` (from `typescript-setup-dependencies-and-tests`) and builds a fresh service.
- Test file location: `tests/domains/<domain>/<entity>.service.test.ts`.

### What to test per method

- **Success:** valid input; assert the returned value and the persisted row.
- **Not found:** the row does not exist.
- **Validation error:** a business rule rejects the input; assert nothing was written.
- **Constraint error:** a uniqueness or integrity rule fails, using a real row that causes the conflict.
- **Guard clauses:** each early return.

### Factory helpers: use canonical production names

- Factory parameters use the same names as production code. No shorthands.

```typescript
// Bad — shorthand names that don't match production fields
const buildUser = (id = '1', name = 'Alice') => ({ id, name })

// Good — canonical names that match the domain model exactly
export const buildCreateUserInput = (overrides: Partial<CreateUserInput> = {}): CreateUserInput => ({
  name: 'Alice',
  email: `alice-${randomUUID()}@example.com`,
  role: 'member',
  ...overrides,
})
```

### Complete example

```typescript
// src/domains/user/user.service.ts
import type { UserRepository } from './user.repository'
import { NotFoundError, ConflictError, ValidationError } from '../../errors'

export class UserService {
  constructor(private readonly options: { repo: UserRepository }) {}

  async getById({ userId }: { userId: string }): Promise<UserDAO> {
    const user: UserDAO | null = await this.options.repo.findById({ id: userId })
    if (!user) {
      throw new NotFoundError(`User ${userId} not found`)
    }
    return user
  }

  async create({ input }: { input: CreateUserInput }): Promise<UserDAO> {
    if (!input.email.includes('@')) {
      throw new ValidationError('email must be a valid email address')
    }
    const existing: UserDAO | null = await this.options.repo.findByEmail({ email: input.email })
    if (existing) {
      throw new ConflictError(`A user with email ${input.email} already exists`)
    }
    return this.options.repo.create({ input })
  }
}
```

```typescript
// tests/domains/user/user.service.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { db } from '@/connectors/db'
import { UserRepository } from '@/domains/user/user.repository'
import { UserService } from '@/domains/user/user.service'
import { ConflictError, NotFoundError, ValidationError } from '@/errors'
import { buildCreateUserInput } from '../../helpers/factories'
import { resetTestDatabase } from '../../helpers/db'

describe('UserService', (): void => {
  let repo: UserRepository
  let service: UserService

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    repo = new UserRepository({ db })
    service = new UserService({ repo })
  })

  describe('create', (): void => {
    it('persists the user when input is valid', async (): Promise<void> => {
      const input: CreateUserInput = buildCreateUserInput()

      const created: UserDAO = await service.create({ input })

      expect(await repo.findById({ id: created.id })).toMatchObject({ email: input.email, role: 'member' })
    })

    it('rejects an invalid email and writes nothing when email has no @', async (): Promise<void> => {
      const input: CreateUserInput = buildCreateUserInput({ email: 'not-an-email' })

      await expect(service.create({ input })).rejects.toThrow(ValidationError)

      expect(await db.user.count()).toBe(0)
    })

    it('rejects a duplicate when a user with that email already exists', async (): Promise<void> => {
      const input: CreateUserInput = buildCreateUserInput()
      await service.create({ input })

      await expect(service.create({ input })).rejects.toThrow(ConflictError)

      expect(await db.user.count({ where: { email: input.email } })).toBe(1)
    })
  })

  describe('getById', (): void => {
    it('throws NotFoundError when the user does not exist', async (): Promise<void> => {
      await expect(service.getById({ userId: 'missing' })).rejects.toThrow(NotFoundError)
    })
  })
})
```

### Testing infrastructure failures

- Do not mock the repository to simulate "DB timeout".
- If a failure must be proven, inject a stub that implements the repository interface and throws. Use it only in that one test, and pass it through the constructor:

```typescript
it('propagates a repository failure when the store is unavailable', async (): Promise<void> => {
  const unavailableRepo: UserRepository = new UnavailableUserRepository() // implements UserRepository; every call throws
  const failingService: UserService = new UserService({ repo: unavailableRepo })

  await expect(failingService.create({ input: buildCreateUserInput() })).rejects.toThrow('store unavailable')
})
```

### Rules checklist before finishing domain service tests

- [ ] The real repository runs against the test database; `resetTestDatabase()` runs in `beforeEach`.
- [ ] No `vi.mock` of the repository, database client or ORM.
- [ ] Success paths assert the persisted row, read back through the repository.
- [ ] Rejection paths assert that nothing was written.
- [ ] Factory helpers use canonical production field names.
- [ ] Test names follow `it('<expected outcome> when <condition>', ...)`.
- [ ] Coverage and doubles pass the checklist in `skills/coding/test-verification-policy/SKILL.md`.
