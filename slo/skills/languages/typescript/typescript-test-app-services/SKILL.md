---
name: typescript-test-app-services
description: TypeScript application service test conventions — test orchestration classes that coordinate
  multiple domain services, verifying delegation order and guard clause exits.
when_to_use: Use when writing tests for application service classes that have an invoke() or execute()
  entry point and coordinate multiple domain services or external clients.
group: languages
kind: skill
---

# TypeScript Test App Services

## Skill summary

- **Name:** `typescript-test-app-services`
- **Description:** TypeScript application service test conventions — test orchestration classes that coordinate multiple domain services, verifying delegation order and guard clause exits.
- **When to use:** Use when writing tests for application service classes that have an `invoke()` or `execute()` entry point and coordinate multiple domain services or external clients.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the PaymentProcessingAppService"
- "Test the orchestration layer for the user onboarding flow"
- "Add tests for the invoke() method of the ReportGenerationService"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Core rule

Application service tests mock **all** domain services and external clients. The goal is to test the *orchestration logic* — that steps are called in the right order, that guard clauses short-circuit correctly, and that the return value is shaped correctly. You are not re-testing what the domain services do — only that the application service delegates to them correctly.

### What to test per `invoke()` call

- **The happy path** — all steps execute in sequence and the correct return value is produced
- **Each early exit / guard clause** — when a step fails, subsequent steps are NOT called
- **Return value shape** — not just that something is returned, but that the fields are correct
- **Step call order** — use `vi.spyOn()` with `.toHaveBeenCalledBefore()` or ordered assertions
- **Dependency call arguments** — verify the right data was passed to each downstream service

### Structure

- One `describe` block for the service class, one nested `describe` per code path
- All dependencies injected via constructor and mocked in `beforeEach`
- Factory functions for input DAOs and fixture responses
- `vi.spyOn()` preferred over `vi.mock()` when the class is instantiated directly

### Complete example

```typescript
// src/services/app/user-onboarding.app-service.ts
export class UserOnboardingAppService {
  constructor(
    private readonly userService: UserService,
    private readonly emailService: EmailService,
    private readonly auditService: AuditService,
  ) {}

  async invoke(input: OnboardUserInput): Promise<OnboardUserResult> {
    const existingUser = await this.userService.findByEmail(input.email)
    if (existingUser) {
      throw new ConflictError(`User with email ${input.email} already exists`)
    }

    const user = await this.userService.create({
      name: input.name,
      email: input.email,
      role: 'member',
    })

    await this.emailService.sendWelcome({ userId: user.id, email: user.email })

    await this.auditService.log({
      event: 'user.created',
      actorId: input.createdByAdminId,
      resourceId: user.id,
    })

    return { userId: user.id, email: user.email }
  }
}
```

```typescript
// src/services/app/user-onboarding.app-service.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { UserOnboardingAppService } from './user-onboarding.app-service'
import { ConflictError } from '../../errors'
import type { UserService } from '../../domains/user/user.service'
import type { EmailService } from '../../clients/email.client'
import type { AuditService } from '../../domains/audit/audit.service'

// Factory helpers — canonical names matching production types
const buildOnboardInput = (overrides: Partial<OnboardUserInput> = {}): OnboardUserInput => ({
  name: 'Alice',
  email: 'alice@example.com',
  createdByAdminId: 'admin-1',
  ...overrides,
})

const buildUserDAO = (overrides: Partial<UserDAO> = {}): UserDAO => ({
  id: 'user-1',
  name: 'Alice',
  email: 'alice@example.com',
  role: 'member',
  createdAt: new Date('2024-01-01'),
  ...overrides,
})

// Dependency mock factories
const makeUserService = (): UserService => ({
  findByEmail: vi.fn(),
  create: vi.fn(),
  getById: vi.fn(),
  updateRole: vi.fn(),
})

const makeEmailService = (): EmailService => ({
  sendWelcome: vi.fn(),
  sendPasswordReset: vi.fn(),
})

const makeAuditService = (): AuditService => ({
  log: vi.fn(),
})

describe('UserOnboardingAppService', () => {
  let userService: UserService
  let emailService: EmailService
  let auditService: AuditService
  let service: UserOnboardingAppService

  beforeEach(() => {
    userService = makeUserService()
    emailService = makeEmailService()
    auditService = makeAuditService()
    service = new UserOnboardingAppService(userService, emailService, auditService)
    vi.clearAllMocks()
  })

  describe('invoke — happy path', () => {
    it('creates the user, sends a welcome email, and logs the audit event', async () => {
      const createdUser = buildUserDAO()
      vi.mocked(userService.findByEmail).mockResolvedValue(null)
      vi.mocked(userService.create).mockResolvedValue(createdUser)
      vi.mocked(emailService.sendWelcome).mockResolvedValue(undefined)
      vi.mocked(auditService.log).mockResolvedValue(undefined)

      const input = buildOnboardInput()
      const result = await service.invoke(input)

      // Return value shape
      expect(result).toEqual({ userId: 'user-1', email: 'alice@example.com' })

      // Step 1: check for existing user
      expect(userService.findByEmail).toHaveBeenCalledWith('alice@example.com')

      // Step 2: create user with the correct payload
      expect(userService.create).toHaveBeenCalledWith({
        name: 'Alice',
        email: 'alice@example.com',
        role: 'member',
      })

      // Step 3: send welcome email
      expect(emailService.sendWelcome).toHaveBeenCalledWith({
        userId: 'user-1',
        email: 'alice@example.com',
      })

      // Step 4: log audit event
      expect(auditService.log).toHaveBeenCalledWith({
        event: 'user.created',
        actorId: 'admin-1',
        resourceId: 'user-1',
      })
    })
  })

  describe('invoke — guard clause: user already exists', () => {
    it('throws ConflictError and does not create a user or send email', async () => {
      vi.mocked(userService.findByEmail).mockResolvedValue(buildUserDAO())

      await expect(
        service.invoke(buildOnboardInput())
      ).rejects.toThrow(ConflictError)

      // Nothing after the guard clause should be called
      expect(userService.create).not.toHaveBeenCalled()
      expect(emailService.sendWelcome).not.toHaveBeenCalled()
      expect(auditService.log).not.toHaveBeenCalled()
    })
  })

  describe('invoke — downstream failure propagation', () => {
    it('does not send email or log audit when user creation fails', async () => {
      vi.mocked(userService.findByEmail).mockResolvedValue(null)
      vi.mocked(userService.create).mockRejectedValue(new Error('DB write failed'))

      await expect(
        service.invoke(buildOnboardInput())
      ).rejects.toThrow('DB write failed')

      expect(emailService.sendWelcome).not.toHaveBeenCalled()
      expect(auditService.log).not.toHaveBeenCalled()
    })

    it('does not log audit event when welcome email fails', async () => {
      vi.mocked(userService.findByEmail).mockResolvedValue(null)
      vi.mocked(userService.create).mockResolvedValue(buildUserDAO())
      vi.mocked(emailService.sendWelcome).mockRejectedValue(new Error('Email service down'))

      await expect(
        service.invoke(buildOnboardInput())
      ).rejects.toThrow('Email service down')

      expect(auditService.log).not.toHaveBeenCalled()
    })
  })
})
```

### Verifying step call order with `vi.spyOn()`

When the class exists in the same module and you need to spy on its own methods:

```typescript
it('calls enrichUser before calling persistUser', async () => {
  const enrichSpy = vi.spyOn(service as any, '_enrichUser').mockResolvedValue(enrichedData)
  const persistSpy = vi.spyOn(service as any, '_persistUser').mockResolvedValue(savedUser)

  await service.invoke(buildOnboardInput())

  const enrichOrder = enrichSpy.mock.invocationCallOrder[0]
  const persistOrder = persistSpy.mock.invocationCallOrder[0]
  expect(enrichOrder).toBeLessThan(persistOrder)
})
```

### Testing the return value shape

Never just assert `expect(result).toBeDefined()`. Assert the exact fields the caller depends on:

```typescript
// Bad
expect(result).toBeDefined()

// Good — asserts the exact contract the caller receives
expect(result).toEqual({
  userId: 'user-1',
  email: 'alice@example.com',
})
```

### Rules checklist before finishing app service tests

- [ ] All domain services and external clients are mocked — no real I/O
- [ ] Happy path test asserts: return value shape AND all steps were called with the right args
- [ ] Each guard clause has a test that verifies subsequent steps are NOT called
- [ ] Each failure propagation path has a test
- [ ] Factory helpers use canonical production field names
- [ ] `beforeEach` resets all mocks and re-instantiates the service
- [ ] `vi.clearAllMocks()` called in `beforeEach` to prevent cross-test pollution
- [ ] No re-testing of domain service internals — only that the app service delegates correctly
