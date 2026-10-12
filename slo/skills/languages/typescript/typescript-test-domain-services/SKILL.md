---
name: typescript-test-domain-services
description: TypeScript domain service test conventions — test the service layer in isolation using mocked
  repositories, with factory helpers and canonical fixture names.
when_to_use: Use when writing tests for domain service classes or functions that contain business logic
  and depend on a repository or DAO layer.
group: languages
kind: skill
---

# TypeScript Test Domain Services

## Skill summary

- **Name:** `typescript-test-domain-services`
- **Description:** TypeScript domain service test conventions — test the service layer in isolation using mocked repositories, with factory helpers and canonical fixture names.
- **When to use:** Use when writing tests for domain service classes or functions that contain business logic and depend on a repository or DAO layer.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write unit tests for the UserService"
- "Add tests for the domain service methods"
- "Test the create and update methods in isolation"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Core rule

Domain service tests do NOT hit the database. The repository/DAO layer is fully mocked. The goal is to test the business logic of the service in complete isolation — every assertion is about what the service *decided* to do, not about what the database returned.

### Structure

- One `describe` block per service method
- Tests nested inside `describe` blocks for sub-cases
- Factory helpers at the top of the test file (not inline)
- `beforeEach` resets mocks and re-instantiates the service
- Test file next to the source: `src/domains/user/user.service.test.ts`

### What to test per method

- **Success path** — the main flow with valid input
- **Not-found path** — when a repository lookup returns null
- **Validation error path** — when the service enforces a business rule and throws
- **Constraint error path** — when a uniqueness or integrity check fails
- **Guard clause path** — every early return

### Factory helpers: use canonical production names

Factory parameters must use the same names as production code. No shorthands.

```typescript
// Bad — shorthand names that don't match production fields
const buildUser = (id = '1', name = 'Alice') => ({ id, name })

// Good — canonical names that match the domain model exactly
const buildUser = (overrides: Partial<UserDAO> = {}): UserDAO => ({
  id: 'user-1',
  name: 'Alice',
  email: 'alice@example.com',
  role: 'member',
  createdAt: new Date('2024-01-01'),
  ...overrides,
})
```

### Mocking a repository

```typescript
import { vi } from 'vitest'
import type { UserRepository } from '../repositories/user.repository'

const makeUserRepo = (): UserRepository => ({
  findById: vi.fn(),
  findByEmail: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
})
```

### Complete example

```typescript
// src/domains/user/user.service.ts
import type { UserRepository } from '../repositories/user.repository'
import { NotFoundError, ConflictError, ValidationError } from '../../errors'

export class UserService {
  constructor(private readonly repo: UserRepository) {}

  async getById(userId: string): Promise<UserDAO> {
    const user = await this.repo.findById(userId)
    if (!user) {
      throw new NotFoundError(`User ${userId} not found`)
    }
    return user
  }

  async create(input: CreateUserInput): Promise<UserDAO> {
    if (!input.email.includes('@')) {
      throw new ValidationError('email must be a valid email address')
    }

    const existing = await this.repo.findByEmail(input.email)
    if (existing) {
      throw new ConflictError(`A user with email ${input.email} already exists`)
    }

    return this.repo.create(input)
  }

  async updateRole(userId: string, role: UserRole): Promise<UserDAO> {
    const user = await this.repo.findById(userId)
    if (!user) {
      throw new NotFoundError(`User ${userId} not found`)
    }
    return this.repo.update(userId, { role })
  }
}
```

```typescript
// src/domains/user/user.service.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { UserService } from './user.service'
import { NotFoundError, ConflictError, ValidationError } from '../../errors'
import type { UserRepository } from '../repositories/user.repository'

// Factory helpers — canonical names matching production UserDAO
const buildUser = (overrides: Partial<UserDAO> = {}): UserDAO => ({
  id: 'user-1',
  name: 'Alice',
  email: 'alice@example.com',
  role: 'member',
  createdAt: new Date('2024-01-01'),
  ...overrides,
})

const buildCreateInput = (overrides: Partial<CreateUserInput> = {}): CreateUserInput => ({
  name: 'Alice',
  email: 'alice@example.com',
  role: 'member',
  ...overrides,
})

// Repository mock factory
const makeRepo = (): UserRepository => ({
  findById: vi.fn(),
  findByEmail: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
})

describe('UserService', () => {
  let repo: UserRepository
  let service: UserService

  beforeEach(() => {
    repo = makeRepo()
    service = new UserService(repo)
  })

  describe('getById', () => {
    it('returns the user when found', async () => {
      const user = buildUser({ id: 'user-42' })
      vi.mocked(repo.findById).mockResolvedValue(user)

      const result = await service.getById('user-42')

      expect(result).toEqual(user)
      expect(repo.findById).toHaveBeenCalledWith('user-42')
    })

    it('throws NotFoundError when user does not exist', async () => {
      vi.mocked(repo.findById).mockResolvedValue(null)

      await expect(service.getById('missing')).rejects.toThrow(NotFoundError)
      await expect(service.getById('missing')).rejects.toThrow('User missing not found')
    })
  })

  describe('create', () => {
    it('creates and returns the user when input is valid', async () => {
      const input = buildCreateInput()
      const created = buildUser()
      vi.mocked(repo.findByEmail).mockResolvedValue(null)
      vi.mocked(repo.create).mockResolvedValue(created)

      const result = await service.create(input)

      expect(result).toEqual(created)
      expect(repo.findByEmail).toHaveBeenCalledWith('alice@example.com')
      expect(repo.create).toHaveBeenCalledWith(input)
    })

    it('throws ValidationError when email is invalid', async () => {
      const input = buildCreateInput({ email: 'not-an-email' })

      await expect(service.create(input)).rejects.toThrow(ValidationError)
      await expect(service.create(input)).rejects.toThrow('email must be a valid email address')

      // Guard: repo should never be called when validation fails
      expect(repo.findByEmail).not.toHaveBeenCalled()
      expect(repo.create).not.toHaveBeenCalled()
    })

    it('throws ConflictError when a user with that email already exists', async () => {
      const input = buildCreateInput()
      vi.mocked(repo.findByEmail).mockResolvedValue(buildUser())

      await expect(service.create(input)).rejects.toThrow(ConflictError)
      await expect(service.create(input)).rejects.toThrow('already exists')

      expect(repo.create).not.toHaveBeenCalled()
    })
  })

  describe('updateRole', () => {
    it('updates and returns the user when found', async () => {
      const existing = buildUser({ role: 'member' })
      const updated = buildUser({ role: 'admin' })
      vi.mocked(repo.findById).mockResolvedValue(existing)
      vi.mocked(repo.update).mockResolvedValue(updated)

      const result = await service.updateRole('user-1', 'admin')

      expect(result.role).toBe('admin')
      expect(repo.update).toHaveBeenCalledWith('user-1', { role: 'admin' })
    })

    it('throws NotFoundError when the user does not exist', async () => {
      vi.mocked(repo.findById).mockResolvedValue(null)

      await expect(service.updateRole('missing', 'admin')).rejects.toThrow(NotFoundError)
      expect(repo.update).not.toHaveBeenCalled()
    })
  })
})
```

### Testing async error propagation

```typescript
it('propagates unexpected repository errors', async () => {
  vi.mocked(repo.create).mockRejectedValue(new Error('DB timeout'))

  await expect(
    service.create(buildCreateInput())
  ).rejects.toThrow('DB timeout')
})
```

### Rules checklist before finishing domain service tests

- [ ] No real database or external I/O in any test
- [ ] Repository is fully mocked via `vi.fn()` factory — never via partial mocks
- [ ] Factory helpers use canonical production field names (no shorthands)
- [ ] One `describe` per method
- [ ] Success, not-found, validation-error, and constraint-error paths each have a test
- [ ] Guard clause paths verify that the repository is NOT called
- [ ] Test names follow `it('<expected outcome> when <condition>', ...)`
- [ ] `beforeEach` resets mocks with `vi.clearAllMocks()` or re-instantiates the repo
