---
name: typescript-test-controllers
description: TypeScript route/controller journey test conventions — drive the real app through real middleware, services and the test database with supertest or framework-native test clients, asserting the response envelope and persisted state.
when_to_use: Use when writing tests for Express, Hono, Fastify, or Nitro route handlers to ensure the
  HTTP layer, middleware, and response envelope are all exercised.
group: languages
kind: skill
---

# TypeScript Test Controllers

## Skill summary

- **Name:** `typescript-test-controllers`
- **Description:** TypeScript route/controller journey test conventions — drive the real app through real middleware, services and the test database with supertest or framework-native test clients, asserting the response envelope and persisted state.
- **When to use:** Use when writing tests for Express, Hono, Fastify, or Nitro route handlers to ensure the HTTP layer, middleware, and response envelope are all exercised.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the POST /users route"
- "Test the auth middleware rejection case"
- "Add controller tests for the documents API"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. This recipe covers TypeScript mechanics only.

### Core rule

- Controller tests are policy level 1 (journey): HTTP request → real middleware → router → application service → domain service → test database, read back.
- Drive the **real app** (`createApp()`) with supertest or the framework's test client.
- Never `vi.mock` services, repositories, the database client or middleware (including auth).
- Authenticate with a **real test session or token** created by a helper, so the real auth middleware runs.
- Mock only third-party APIs, with `msw` or a fake passed into `createApp()` options.
- Assert the response status, the response envelope **and** the persisted state read back from the database.

### What each controller test must cover

- The **2xx happy path** for each route, with a DB read-back.
- At least one **error path** (400/401/403/404/409) per route.
- **Middleware behavior** (auth rejection, validation errors) as separate cases, asserting nothing was written.
- **Response envelope shape**, not just the status code.
- **Status code** asserted on every test.

### Structure rules

- `beforeEach` calls `resetTestDatabase()` (from `typescript-setup-dependencies-and-tests`).
- Build the app once per file with `createApp()`; pass third-party fakes through its options if needed.
- One test file per router/controller file: `tests/routers/<name>.router.test.ts`.
- Seed preconditions through the real domain service or repository, not inline SQL in every test.

### Test authentication helper

- The helper creates a real session row (or signs a real token with the test secret) so `requireAuth` validates it.

```typescript
// tests/helpers/auth.ts
import { db } from '@/connectors/db'
import { SessionService } from '@/domains/session/session.service'
import { SessionRepository } from '@/domains/session/session.repository'

export interface TestSession {
  userId: string
  authorizationHeader: string
}

/** Create a real user and session in the test database and return the bearer header. */
export async function createTestSession({ role = 'member' }: { role?: UserRole } = {}): Promise<TestSession> {
  const user: { id: string } = await db.user.create({
    data: { name: 'Test Admin', email: `admin-${crypto.randomUUID()}@example.com`, role },
  })
  const sessions: SessionService = new SessionService({ repo: new SessionRepository({ db }) })
  const token: string = await sessions.issue({ userId: user.id })
  return { userId: user.id, authorizationHeader: `Bearer ${token}` }
}
```

### Example: Express + Supertest + Vitest

```typescript
// src/controllers/user.controller.ts
import { Router, type Request, type Response } from 'express'
import { requireAuth } from '../middleware/auth'
import type { UserService } from '../domains/user/user.service'

export function buildUserRouter({ userService }: { userService: UserService }): Router {
  const router: Router = Router()

  router.get('/:id', requireAuth, async (req: Request, res: Response): Promise<Response> => {
    const user: UserDAO | null = await userService.findById({ id: req.params.id })
    if (!user) {
      return res.status(404).json({ data: null, errors: [{ code: 'NOT_FOUND', message: 'User not found' }] })
    }
    return res.status(200).json({ data: user, errors: [] })
  })

  router.post('/', requireAuth, async (req: Request, res: Response): Promise<Response> => {
    const { name, email } = req.body
    if (!name || !email) {
      return res.status(400).json({ data: null, errors: [{ code: 'VALIDATION', message: 'name and email are required' }] })
    }
    const user: UserDAO = await userService.create({ input: { name, email, role: 'member' } })
    return res.status(201).json({ data: user, errors: [] })
  })

  return router
}
```

```typescript
// tests/routers/user.router.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import request, { type Response } from 'supertest'
import type { Express } from 'express'
import { createApp } from '@/app'
import { db } from '@/connectors/db'
import { UserRepository } from '@/domains/user/user.repository'
import { createTestSession, type TestSession } from '../helpers/auth'
import { resetTestDatabase } from '../helpers/db'

const app: Express = createApp()

describe('GET /users/:id', (): void => {
  let session: TestSession

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    session = await createTestSession()
  })

  it('returns 200 and the user envelope when the user exists', async (): Promise<void> => {
    const users: UserRepository = new UserRepository({ db })
    const stored: UserDAO = await users.create({ input: { name: 'Alice', email: 'alice@example.com', role: 'member' } })

    const res: Response = await request(app).get(`/users/${stored.id}`).set('Authorization', session.authorizationHeader)

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({ data: { id: stored.id, email: 'alice@example.com' }, errors: [] })
  })

  it('returns 404 when the user does not exist', async (): Promise<void> => {
    const res: Response = await request(app).get('/users/missing').set('Authorization', session.authorizationHeader)

    expect(res.status).toBe(404)
    expect(res.body).toEqual({ data: null, errors: [{ code: 'NOT_FOUND', message: 'User not found' }] })
  })

  it('returns 401 when the request has no session', async (): Promise<void> => {
    const res: Response = await request(app).get(`/users/${session.userId}`)

    expect(res.status).toBe(401)
    expect(res.body.data).toBeNull()
  })
})

describe('POST /users', (): void => {
  let session: TestSession

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    session = await createTestSession()
  })

  it('returns 201 and persists the user when input is valid', async (): Promise<void> => {
    const res: Response = await request(app)
      .post('/users')
      .set('Authorization', session.authorizationHeader)
      .send({ name: 'Bob', email: 'bob@example.com' })

    expect(res.status).toBe(201)
    expect(res.body).toMatchObject({ data: { name: 'Bob', email: 'bob@example.com' }, errors: [] })
    const stored: UserDAO | null = await new UserRepository({ db }).findByEmail({ email: 'bob@example.com' })
    expect(stored).toMatchObject({ id: res.body.data.id, role: 'member' })
  })

  it('returns 400 and writes nothing when name is missing', async (): Promise<void> => {
    const res: Response = await request(app)
      .post('/users')
      .set('Authorization', session.authorizationHeader)
      .send({ email: 'bob@example.com' })

    expect(res.status).toBe(400)
    expect(res.body).toEqual({ data: null, errors: [{ code: 'VALIDATION', message: 'name and email are required' }] })
    expect(await db.user.count({ where: { email: 'bob@example.com' } })).toBe(0)
  })

  it('returns 401 and writes nothing when the session is missing', async (): Promise<void> => {
    const res: Response = await request(app).post('/users').send({ name: 'Bob', email: 'bob@example.com' })

    expect(res.status).toBe(401)
    expect(await db.user.count({ where: { email: 'bob@example.com' } })).toBe(0)
  })

  it('returns 409 and keeps one row when the email already exists', async (): Promise<void> => {
    await new UserRepository({ db }).create({ input: { name: 'Bob', email: 'bob@example.com', role: 'member' } })

    const res: Response = await request(app)
      .post('/users')
      .set('Authorization', session.authorizationHeader)
      .send({ name: 'Bob Again', email: 'bob@example.com' })

    expect(res.status).toBe(409)
    expect(await db.user.count({ where: { email: 'bob@example.com' } })).toBe(1)
  })
})
```

- `createApp()` registers the real error handler, so a domain `ConflictError` maps to 409 through production code.
- To prove a 5xx path, pass a stub implementing the repository interface into `createApp()` options for that one test. Do not mock the module.

### Example: Hono with `app.request()`

- Hono has a built-in test helper; no supertest needed. The same rules apply: the real app, real middleware, test database.

```typescript
// tests/routes/documents.route.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import type { Hono } from 'hono'
import { createApp } from '@/app'
import { db } from '@/connectors/db'
import { DocumentRepository } from '@/domains/document/document.repository'
import { createTestSession, type TestSession } from '../helpers/auth'
import { resetTestDatabase } from '../helpers/db'

describe('GET /documents/:id', (): void => {
  const app: Hono = createApp()
  let session: TestSession

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase()
    session = await createTestSession()
  })

  it('returns 200 with the document envelope when the document exists', async (): Promise<void> => {
    const stored: DocumentDAO = await new DocumentRepository({ db }).create({ input: { title: 'Spec' } })

    const res: Response = await app.request(`/documents/${stored.id}`, {
      headers: { Authorization: session.authorizationHeader },
    })

    expect(res.status).toBe(200)
    expect(await res.json()).toMatchObject({ data: { id: stored.id, title: 'Spec' }, errors: [] })
  })

  it('returns 404 when the document does not exist', async (): Promise<void> => {
    const res: Response = await app.request('/documents/missing', {
      headers: { Authorization: session.authorizationHeader },
    })

    expect(res.status).toBe(404)
  })
})
```

### Rules checklist before finishing controller tests

- [ ] Tests drive the real app from `createApp()` with real middleware, services and repositories.
- [ ] No `vi.mock` of services, repositories, the database client or middleware.
- [ ] Authenticated requests use a real test session or token from `tests/helpers/auth.ts`.
- [ ] `resetTestDatabase()` runs in `beforeEach`.
- [ ] Every route has a happy path test that reads the persisted state back.
- [ ] Every route has at least one error path test (4xx or 5xx).
- [ ] Auth rejection and validation failures assert that nothing was written.
- [ ] Response status code and envelope shape are asserted on every test.
- [ ] Only third-party APIs are mocked (`msw` or a fake passed into `createApp()` options).
- [ ] Coverage and doubles pass the checklist in `skills/coding/test-verification-policy/SKILL.md`.
