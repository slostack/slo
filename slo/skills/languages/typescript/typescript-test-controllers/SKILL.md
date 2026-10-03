---
name: typescript-test-controllers
description: TypeScript route/controller test conventions — test the full HTTP layer using supertest or
  framework-native test clients with mocked services.
when_to_use: Use when writing tests for Express, Hono, Fastify, or Nitro route handlers to ensure the
  HTTP layer, middleware, and response envelope are all exercised.
group: languages
kind: skill
---

# TypeScript Test Controllers

## Skill summary

- **Name:** `typescript-test-controllers`
- **Description:** TypeScript route/controller test conventions — test the full HTTP layer using supertest or framework-native test clients with mocked services.
- **When to use:** Use when writing tests for Express, Hono, Fastify, or Nitro route handlers to ensure the HTTP layer, middleware, and response envelope are all exercised.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the POST /users route"
- "Test the auth middleware rejection case"
- "Add controller tests for the documents API"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Core rule

Route handler tests call the HTTP layer — not the service directly. The purpose is to test the full middleware chain: routing, request parsing, authentication, validation, response shaping. The service layer is mocked so that controller tests never hit a real database.

### What each controller test must cover

- The **2xx happy path** for each route
- At least one **error path** (400/401/403/404/500) per route
- **Middleware behavior** (auth rejection, validation errors) tested as separate cases
- **Response envelope shape** — not just status code, but the body structure
- **Status code** must be asserted on every test

### Structure rules

- Use `beforeEach`/`afterEach` to reset mocks (`vi.clearAllMocks()`)
- Mock the service at the module level — never let a route test reach the real service
- One test file per router/controller file
- Test file lives next to the controller: `src/controllers/user.controller.test.ts`

### Example: Express + Supertest + Vitest

```typescript
// src/controllers/user.controller.ts
import { Router, Request, Response } from 'express'
import { UserService } from '../services/user.service'
import { requireAuth } from '../middleware/auth'

export const userRouter = Router()

userRouter.get('/:id', requireAuth, async (req: Request, res: Response) => {
  const user = await UserService.getById(req.params.id)
  if (!user) {
    return res.status(404).json({ error: 'User not found' })
  }
  return res.status(200).json({ data: user })
})

userRouter.post('/', requireAuth, async (req: Request, res: Response) => {
  const { name, email } = req.body
  if (!name || !email) {
    return res.status(400).json({ error: 'name and email are required' })
  }
  const user = await UserService.create({ name, email })
  return res.status(201).json({ data: user })
})
```

```typescript
// src/controllers/user.controller.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import request from 'supertest'
import express from 'express'
import { userRouter } from './user.controller'

// Mock the service module — no database
vi.mock('../services/user.service', () => ({
  UserService: {
    getById: vi.fn(),
    create: vi.fn(),
  },
}))

// Mock auth middleware — pass-through by default
vi.mock('../middleware/auth', () => ({
  requireAuth: vi.fn((req, res, next) => next()),
}))

import { UserService } from '../services/user.service'
import { requireAuth } from '../middleware/auth'

const buildApp = () => {
  const app = express()
  app.use(express.json())
  app.use('/users', userRouter)
  return app
}

describe('GET /users/:id', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Happy path
  it('returns 200 and the user when found', async () => {
    const fakeUser = { id: '1', name: 'Alice', email: 'alice@example.com' }
    vi.mocked(UserService.getById).mockResolvedValue(fakeUser)

    const res = await request(buildApp()).get('/users/1')

    expect(res.status).toBe(200)
    expect(res.body).toEqual({ data: fakeUser })
    expect(UserService.getById).toHaveBeenCalledWith('1')
  })

  // Not found path
  it('returns 404 when user does not exist', async () => {
    vi.mocked(UserService.getById).mockResolvedValue(null)

    const res = await request(buildApp()).get('/users/nonexistent')

    expect(res.status).toBe(404)
    expect(res.body).toEqual({ error: 'User not found' })
  })

  // Auth failure path
  it('returns 401 when the request is unauthenticated', async () => {
    vi.mocked(requireAuth).mockImplementationOnce((req, res) => {
      res.status(401).json({ error: 'Unauthorized' })
    })

    const res = await request(buildApp()).get('/users/1')

    expect(res.status).toBe(401)
    expect(UserService.getById).not.toHaveBeenCalled()
  })
})

describe('POST /users', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Happy path
  it('returns 201 and the created user when input is valid', async () => {
    const newUser = { id: '2', name: 'Bob', email: 'bob@example.com' }
    vi.mocked(UserService.create).mockResolvedValue(newUser)

    const res = await request(buildApp())
      .post('/users')
      .send({ name: 'Bob', email: 'bob@example.com' })

    expect(res.status).toBe(201)
    expect(res.body).toEqual({ data: newUser })
    expect(UserService.create).toHaveBeenCalledWith({ name: 'Bob', email: 'bob@example.com' })
  })

  // Validation error — missing name
  it('returns 400 when name is missing', async () => {
    const res = await request(buildApp())
      .post('/users')
      .send({ email: 'bob@example.com' })

    expect(res.status).toBe(400)
    expect(res.body).toEqual({ error: 'name and email are required' })
    expect(UserService.create).not.toHaveBeenCalled()
  })

  // Validation error — missing email
  it('returns 400 when email is missing', async () => {
    const res = await request(buildApp())
      .post('/users')
      .send({ name: 'Bob' })

    expect(res.status).toBe(400)
    expect(res.body).toEqual({ error: 'name and email are required' })
    expect(UserService.create).not.toHaveBeenCalled()
  })

  // Service error propagation
  it('returns 500 when the service throws an unexpected error', async () => {
    vi.mocked(UserService.create).mockRejectedValue(new Error('DB connection lost'))

    // Express must have an error handler registered for this to work
    const app = buildApp()
    app.use((err: Error, req: express.Request, res: express.Response, next: express.NextFunction) => {
      res.status(500).json({ error: 'Internal server error' })
    })

    const res = await request(app)
      .post('/users')
      .send({ name: 'Bob', email: 'bob@example.com' })

    expect(res.status).toBe(500)
    expect(res.body).toEqual({ error: 'Internal server error' })
  })
})
```

### Example: Hono with `app.request()`

Hono has a built-in test helper — no supertest needed.

```typescript
// src/routes/documents.route.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Hono } from 'hono'
import { documentsRoute } from './documents.route'

vi.mock('../services/document.service', () => ({
  DocumentService: {
    getById: vi.fn(),
  },
}))

import { DocumentService } from '../services/document.service'

describe('GET /documents/:id', () => {
  const app = new Hono()
  app.route('/documents', documentsRoute)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns 200 with document data when found', async () => {
    vi.mocked(DocumentService.getById).mockResolvedValue({ id: '1', title: 'Spec' })

    const res = await app.request('/documents/1')

    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body).toEqual({ data: { id: '1', title: 'Spec' } })
  })

  it('returns 404 when document is not found', async () => {
    vi.mocked(DocumentService.getById).mockResolvedValue(null)

    const res = await app.request('/documents/missing')

    expect(res.status).toBe(404)
  })
})
```

### Rules checklist before finishing controller tests

- [ ] Every route has a happy path test
- [ ] Every route has at least one error path test (4xx or 5xx)
- [ ] Auth middleware rejection is tested separately
- [ ] Response status code is asserted on every test
- [ ] Response body shape (envelope) is asserted — not just the presence of a field
- [ ] Service mock is cleared in `beforeEach`
- [ ] Service is never called on validation/auth failure paths
- [ ] No real database connections in any controller test
