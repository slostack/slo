---
name: typescript-build-api-documentation
description: Build OpenAPI/Swagger documentation in TypeScript projects by deriving the spec from Zod
  schemas — no hand-written YAML.
when_to_use: Use when adding API documentation to a TypeScript Node.js project using Hono, Express, or
  Fastify.
group: languages
kind: skill
---

# TypeScript Build API Documentation

## Skill summary

- **Name:** `typescript-build-api-documentation`
- **Description:** Build OpenAPI/Swagger documentation in TypeScript projects by deriving the spec from Zod schemas — no hand-written YAML.
- **When to use:** Use when adding API documentation to a TypeScript Node.js project using Hono, Express, or Fastify.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- add swagger docs to my Hono API
- generate OpenAPI spec from my Zod schemas
- serve Swagger UI at /docs
- set up zod-openapi for my Express routes
- add request and response schemas to my route documentation

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

API documentation must be derived from the same Zod schemas used for runtime validation. This guarantees the spec and the running API can never drift. Never hand-write OpenAPI YAML or JSON — always generate it.

### Hono + `@hono/zod-openapi` (recommended for Hono projects)

Install:
```bash
pnpm add hono @hono/zod-openapi @hono/swagger-ui zod
```

#### Define schemas with OpenAPI metadata

```typescript
// src/schemas/user.schema.ts

import { z } from '@hono/zod-openapi'

export const UserSchema = z
  .object({
    id: z.string().uuid(),
    email: z.string().email(),
    name: z.string().min(1),
    createdAt: z.string().datetime(),
  })
  .openapi('User')

export const CreateUserBodySchema = z
  .object({
    email: z.string().email().openapi({ example: 'alice@example.com' }),
    name: z.string().min(1).openapi({ example: 'Alice' }),
  })
  .openapi('CreateUserBody')

export const UserParamsSchema = z.object({
  id: z.string().uuid().openapi({ example: '550e8400-e29b-41d4-a716-446655440000' }),
})
```

#### Define a route with full documentation

```typescript
// src/routes/users.route.ts

import { createRoute, z } from '@hono/zod-openapi'
import { UserSchema, CreateUserBodySchema, UserParamsSchema } from '../schemas/user.schema'
import { errorResponseSchema } from '../schemas/api-response.schema'

export const getUserRoute = createRoute({
  method: 'get',
  path: '/users/{id}',
  tags: ['users'],
  summary: 'Get a user by ID',
  description: 'Returns a single user object for the given UUID.',
  request: {
    params: UserParamsSchema,
  },
  responses: {
    200: {
      content: { 'application/json': { schema: UserSchema } },
      description: 'User found',
    },
    404: {
      content: { 'application/json': { schema: errorResponseSchema } },
      description: 'User not found',
    },
  },
})

export const createUserRoute = createRoute({
  method: 'post',
  path: '/users',
  tags: ['users'],
  summary: 'Create a user',
  request: {
    body: {
      content: { 'application/json': { schema: CreateUserBodySchema } },
    },
  },
  responses: {
    201: {
      content: { 'application/json': { schema: UserSchema } },
      description: 'User created',
    },
    422: {
      content: { 'application/json': { schema: errorResponseSchema } },
      description: 'Validation error',
    },
  },
})
```

#### Wire up the app and serve the spec

```typescript
// src/app.ts

import { OpenAPIHono } from '@hono/zod-openapi'
import { swaggerUI } from '@hono/swagger-ui'
import { getUserRoute, createUserRoute } from './routes/users.route'
import { UserService } from './services/user-service'
import { successResponse, errorResponse } from './lib/response'

const app = new OpenAPIHono()

app.openapi(getUserRoute, async (c) => {
  const { id } = c.req.valid('param')
  const user = await UserService.findById(id)
  if (!user) return c.json(errorResponse('User not found', 'USER_NOT_FOUND'), 404)
  return c.json(successResponse(user), 200)
})

app.openapi(createUserRoute, async (c) => {
  const body = c.req.valid('json')
  const user = await UserService.create(body)
  return c.json(successResponse(user), 201)
})

// Serve OpenAPI JSON spec
app.doc('/openapi.json', {
  openapi: '3.0.0',
  info: { title: 'My API', version: 'v1' },
})

// Serve Swagger UI
app.get('/docs', swaggerUI({ url: '/openapi.json' }))

export default app
```

### Express + `@asteasolutions/zod-to-openapi` (recommended for Express projects)

Install:
```bash
pnpm add @asteasolutions/zod-to-openapi swagger-ui-express zod
pnpm add -D @types/swagger-ui-express
```

#### Register schemas and routes

```typescript
// src/openapi/registry.ts

import {
  OpenAPIRegistry,
  OpenApiGeneratorV3,
  extendZodWithOpenApi,
} from '@asteasolutions/zod-to-openapi'
import { z } from 'zod'

extendZodWithOpenApi(z)

export const registry = new OpenAPIRegistry()

// Register schemas
const UserSchema = registry.register(
  'User',
  z.object({
    id: z.string().uuid().openapi({ example: '550e8400-...' }),
    email: z.string().email().openapi({ example: 'alice@example.com' }),
    name: z.string().openapi({ example: 'Alice' }),
  }),
)

// Register route
registry.registerPath({
  method: 'get',
  path: '/api/v1/users/{id}',
  tags: ['users'],
  summary: 'Get a user by ID',
  request: {
    params: z.object({ id: z.string().uuid() }),
  },
  responses: {
    200: {
      description: 'User found',
      content: { 'application/json': { schema: UserSchema } },
    },
    404: { description: 'User not found' },
  },
})

export function generateOpenAPIDocument() {
  const generator = new OpenApiGeneratorV3(registry.definitions)
  return generator.generateDocument({
    openapi: '3.0.0',
    info: { title: 'My API', version: 'v1' },
    servers: [{ url: '/api/v1' }],
  })
}
```

#### Serve the spec and UI in Express

```typescript
// src/app.ts

import express from 'express'
import swaggerUi from 'swagger-ui-express'
import { generateOpenAPIDocument } from './openapi/registry'

const app = express()
app.use(express.json())

const spec = generateOpenAPIDocument()

app.get('/openapi.json', (_req, res) => res.json(spec))
app.use('/docs', swaggerUi.serve, swaggerUi.setup(spec))

export default app
```

### Rules and checklist

- [ ] Documentation is generated from Zod schemas — no hand-written YAML
- [ ] Every route has: `summary`, `description`, `tags`, `request` schemas, and `responses` for all status codes (200 + errors)
- [ ] Spec served at `/openapi.json`; Swagger UI served at `/docs`
- [ ] All routes versioned under `/api/v1/`
- [ ] Routes tagged by domain resource (`tags: ['users']`, `tags: ['orders']`)
- [ ] Error response schemas are registered and consistent with the `ApiResponse` envelope
- [ ] CI job generates the spec and asserts it is non-empty (smoke test)
