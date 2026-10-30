---
name: typescript-test-app-services
description: TypeScript application service test conventions — test invoke() orchestration with real domain services and repositories on the test database, faking only third-party clients, and asserting persisted rows, recorded calls and guard clause exits.
when_to_use: Use when writing tests for application service classes that have an invoke() or execute()
  entry point and coordinate multiple domain services or external clients.
group: languages
kind: skill
---

# TypeScript Test App Services

## Skill summary

- **Name:** `typescript-test-app-services`
- **Description:** TypeScript application service test conventions — test invoke() orchestration with real domain services and repositories on the test database, faking only third-party clients, and asserting persisted rows, recorded calls and guard clause exits.
- **When to use:** Use when writing tests for application service classes that have an `invoke()` or `execute()` entry point and coordinate multiple domain services or external clients.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the PaymentProcessingAppService"
- "Test the orchestration layer for the user onboarding flow"
- "Add tests for the invoke() method of the ReportGenerationService"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. This recipe covers TypeScript mechanics only.

### Core rule

- App-service tests are policy level 2 (application-service workflow).
- Use the **real domain services and real repositories** against the test database. `resetTestDatabase()` runs in `beforeEach`.
- Mock **only third-party APIs** at their client boundary: `msw` for vendor HTTP, or an injected recording fake that implements the client interface.
- Internal collaborators (audit, clock, ID generator) are real, or hand-written stubs passed in through the options object. Never `vi.mock` or `vi.fn()` them.
- Assert outcomes: the return value, persisted rows read back, and recorded third-party calls.

### What to test per `invoke()` call

- **Happy path:** every step runs; assert the return value, the persisted rows and the recorded third-party call.
- **Each guard clause:** the early exit fires; assert later steps left no rows and made no third-party calls.
- **Failure cutoffs:** a step fails; assert later steps did not run, through missing rows and missing calls.
- **Return value shape:** the exact fields the caller depends on.
- **Arguments to the third-party client:** read them from the recording fake or the captured `msw` request.

### Structure

- One `describe` block for the service class, one nested `describe` per code path.
- Construct the service with an options object holding real domain services and the injected third-party fake.
- Factory helpers for input DAOs live in `tests/helpers/factories.ts`.
- Test file location: `tests/services/app/<name>.app-service.test.ts`.

### Complete example

```typescript
// src/services/app/user-onboarding.app-service.ts
export interface UserOnboardingAppServiceOptions {
  userService: UserService
  emailClient: EmailClient // third-party provider client
  auditService: AuditService
}

export class UserOnboardingAppService {
  constructor(private readonly options: UserOnboardingAppServiceOptions) {}

  async invoke({ input }: { input: OnboardUserInput }): Promise<OnboardUserResult> {
    const existingUser: UserDAO | null = await this.options.userService.findByEmail({ email: input.email })
    if (existingUser) {
      throw new ConflictError(`User with email ${input.email} already exists`)
    }

    const user: UserDAO = await this.options.userService.create({
      input: { name: input.name, email: input.email, role: 'member' },
    })

    await this.options.emailClient.sendWelcome({ userId: user.id, email: user.email })

    await this.options.auditService.log({
      event: 'user.created',
      actorId: input.createdByAdminId,
      resourceId: user.id,
    })

    return { userId: user.id, email: user.email }
  }
}
```

```typescript
// tests/services/app/user-onboarding.app-service.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { db } from '@/connectors/db'
import type { EmailClient, SendWelcomeInput } from '@/clients/email.client'
import { AuditRepository } from '@/domains/audit/audit.repository'
import { AuditService } from '@/domains/audit/audit.service'
import { UserRepository } from '@/domains/user/user.repository'
import { UserService } from '@/domains/user/user.service'
import { ConflictError } from '@/errors'
import { UserOnboardingAppService } from '@/services/app/user-onboarding.app-service'
import { buildOnboardUserInput } from '../../helpers/factories'
import { resetTestDatabase } from '../../helpers/db'

/** Third-party fake: records every welcome email instead of calling the provider. */
class RecordingEmailClient implements EmailClient {
  readonly sent: SendWelcomeInput[] = []

  async sendWelcome(input: SendWelcomeInput): Promise<void> {
    this.sent.push(input)
  }
}

/** Third-party fake: the provider is down. */
class UnavailableEmailClient implements EmailClient {
  async sendWelcome(_input: SendWelcomeInput): Promise<void> {
    throw new Error('Email provider down')
  }
}

describe('UserOnboardingAppService', (): void => {
  let users: UserRepository
  let audits: AuditRepository
  let emailClient: RecordingEmailClient

  const buildService = ({ emailClient }: { emailClient: EmailClient }): UserOnboardingAppService =>
    new UserOnboardingAppService({
      userService: new UserService({ repo: users }),
      emailClient,
      auditService: new AuditService({ repo: audits }),
    })

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    users = new UserRepository({ db })
    audits = new AuditRepository({ db })
    emailClient = new RecordingEmailClient()
  })

  describe('invoke — happy path', (): void => {
    it('persists the user, sends one welcome email and records the audit row when the email is new', async (): Promise<void> => {
      const input: OnboardUserInput = buildOnboardUserInput()

      const result: OnboardUserResult = await buildService({ emailClient }).invoke({ input })

      const stored: UserDAO | null = await users.findByEmail({ email: input.email })
      expect(result).toEqual({ userId: stored?.id, email: input.email })
      expect(stored).toMatchObject({ name: input.name, role: 'member' })
      expect(emailClient.sent).toEqual([{ userId: stored?.id, email: input.email }])
      expect(await audits.listByResource({ resourceId: result.userId })).toMatchObject([
        { event: 'user.created', actorId: input.createdByAdminId },
      ])
    })
  })

  describe('invoke — guard clause: user already exists', (): void => {
    it('throws ConflictError and sends no email when the email is taken', async (): Promise<void> => {
      const input: OnboardUserInput = buildOnboardUserInput()
      await new UserService({ repo: users }).create({ input: { name: input.name, email: input.email, role: 'member' } })

      await expect(buildService({ emailClient }).invoke({ input })).rejects.toThrow(ConflictError)

      expect(await db.user.count({ where: { email: input.email } })).toBe(1)
      expect(emailClient.sent).toEqual([])
      expect(await db.auditEvent.count()).toBe(0)
    })
  })

  describe('invoke — failure cutoff', (): void => {
    it('records no audit row when the welcome email fails', async (): Promise<void> => {
      const input: OnboardUserInput = buildOnboardUserInput()

      await expect(
        buildService({ emailClient: new UnavailableEmailClient() }).invoke({ input }),
      ).rejects.toThrow('Email provider down')

      expect(await db.auditEvent.count()).toBe(0)
    })
  })
})
```

- If the email client is a real HTTP client, you may keep it real and intercept the provider with `msw` instead of the fake (see `typescript-setup-dependencies-and-tests`, step 7).
- A failure inside an internal step (for example the user insert) is forced with real data, such as a row that violates a constraint, or with a stub that implements the repository interface passed through the options object.

### Verifying step order through observable outcomes

- Do not spy on or patch private methods (`vi.spyOn(service as any, '_enrichUser')`). That couples tests to private structure.
- Prove order through what each step leaves behind:
  - **Persisted rows:** a later step's row exists only if the earlier step succeeded.
  - **Recorded third-party calls:** the fake records arguments that only an earlier step could produce, such as the persisted user's `id`.
  - **Failure cutoffs:** make step N fail and assert that step N+1 left no row and made no call.

```typescript
it('sends the welcome email with the persisted user id when onboarding succeeds', async (): Promise<void> => {
  const input: OnboardUserInput = buildOnboardUserInput()

  await buildService({ emailClient }).invoke({ input })

  const stored: UserDAO | null = await users.findByEmail({ email: input.email })
  expect(emailClient.sent.map((call: SendWelcomeInput): string => call.userId)).toEqual([stored?.id])
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

- [ ] Real domain services and real repositories run against the test database; `resetTestDatabase()` runs in `beforeEach`.
- [ ] Only third-party clients are faked (`msw` or an injected fake implementing the client interface).
- [ ] No `vi.mock`, `vi.fn()` or `vi.spyOn` on domain services, repositories, internal services or private methods.
- [ ] Happy path asserts the return value shape, the persisted rows and the recorded third-party call.
- [ ] Each guard clause and failure cutoff asserts that later steps left no rows and made no calls.
- [ ] The service is built through its options object in each test.
- [ ] Factory helpers use canonical production field names.
- [ ] Test names follow `it('<expected outcome> when <condition>', ...)`.
- [ ] Coverage and doubles pass the checklist in `skills/coding/test-verification-policy/SKILL.md`.
