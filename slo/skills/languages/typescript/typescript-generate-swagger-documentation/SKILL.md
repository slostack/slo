---
name: typescript-generate-swagger-documentation
description: Step-by-step guide to generating and publishing OpenAPI/Swagger documentation from a TypeScript
  Node.js app using zod-to-openapi.
when_to_use: Use when setting up OpenAPI spec generation from scratch in a TypeScript project, or when
  wiring existing Zod schemas into a Swagger-compatible spec.
group: languages
kind: skill
---

# TypeScript Generate Swagger Documentation

## Skill summary

- **Name:** `typescript-generate-swagger-documentation`
- **Description:** Step-by-step guide to generating and publishing OpenAPI/Swagger documentation from a TypeScript Node.js app using zod-to-openapi.
- **When to use:** Use when setting up OpenAPI spec generation from scratch in a TypeScript project, or when wiring existing Zod schemas into a Swagger-compatible spec.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- generate swagger docs for my TypeScript API
- set up zod-to-openapi in my project
- create an openapi.registry.ts file
- how do I add openapi metadata to my Zod schemas?
- run a CI smoke test against my OpenAPI spec

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

The canonical approach: use `@asteasolutions/zod-to-openapi` to register all schemas and routes in a single registry file, generate the spec programmatically, and serve it alongside Swagger UI. The Zod schemas used for runtime validation are the same ones that produce the docs — no drift is possible.

### Step 1 — Install dependencies

```bash
pnpm add @asteasolutions/zod-to-openapi swagger-ui-express zod
pnpm add -D @types/swagger-ui-express
```

For Hono, prefer `@hono/zod-openapi` + `@hono/swagger-ui` instead (see `typescript-build-api-documentation` skill).

### Step 2 — Extend Zod and create the registry

Call `extendZodWithOpenApi(z)` exactly once, before any schema definitions. The cleanest place is a dedicated module that exports the patched `z` and the shared registry.

```typescript
// src/openapi/registry.ts

import {
  OpenAPIRegistry,
  OpenApiGeneratorV3,
  extendZodWithOpenApi,
} from '@asteasolutions/zod-to-openapi'
import { z } from 'zod'

extendZodWithOpenApi(z)

// Re-export the patched z so every schema file imports from here, not from 'zod'
export { z }

export const registry = new OpenAPIRegistry()
```

Every schema file in the project imports `z` from `src/openapi/registry` rather than directly from `zod`. This ensures `.openapi()` is always available.

### Step 3 — Register schemas with OpenAPI metadata

```typescript
// src/schemas/user.schema.ts

import { registry, z } from '../openapi/registry'

// Define the Zod schema with .openapi() metadata
const UserSchema = z.object({
  id: z.string().uuid().openapi({ example: '550e8400-e29b-41d4-a716-446655440000' }),
  email: z.string().email().openapi({ example: 'alice@example.com' }),
  name: z.string().min(1).openapi({ example: 'Alice' }),
  createdAt: z.string().datetime().openapi({ example: '2024-01-15T10:30:00Z' }),
})

// Register it so it appears in the OpenAPI components/schemas section
export const UserSchemaRef = registry.register('User', UserSchema)

export const CreateUserBodySchema = z.object({
  email: z.string().email().openapi({ example: 'alice@example.com' }),
  name: z.string().min(1).openapi({ example: 'Alice' }),
})

export const CreateUserBodySchemaRef = registry.register('CreateUserBody', CreateUserBodySchema)
```

Rule: register every request body and response DTO. Anonymous inline schemas work but won't appear in the `components/schemas` section and can't be referenced by name from other routes.

### Step 4 — Register routes in the registry

Keep all route registrations in one file: `src/openapi/routes.ts`. Import schemas from their respective schema files and register each route with its full documentation.

```typescript
// src/openapi/routes.ts

import { registry, z } from './registry'
import { UserSchemaRef, CreateUserBodySchemaRef } from '../schemas/user.schema'

const ErrorSchema = z.object({
  data: z.null(),
  errors: z.object({
    msg: z.array(z.string()),
    code: z.string().nullable(),
  }),
  api_version: z.string(),
})

registry.registerPath({
  method: 'get',
  path: '/api/v1/users/{id}',
  tags: ['users'],
  summary: 'Get a user by ID',
  description: 'Returns a single user for the given UUID. Returns 404 if not found.',
  request: {
    params: z.object({
      id: z.string().uuid().openapi({ example: '550e8400-e29b-41d4-a716-446655440000' }),
    }),
  },
  responses: {
    200: {
      description: 'User found',
      content: { 'application/json': { schema: UserSchemaRef } },
    },
    404: {
      description: 'User not found',
      content: { 'application/json': { schema: ErrorSchema } },
    },
  },
})

registry.registerPath({
  method: 'post',
  path: '/api/v1/users',
  tags: ['users'],
  summary: 'Create a user',
  description: 'Creates a new user and returns the created object.',
  request: {
    body: {
      content: { 'application/json': { schema: CreateUserBodySchemaRef } },
    },
  },
  responses: {
    201: {
      description: 'User created',
      content: { 'application/json': { schema: UserSchemaRef } },
    },
    422: {
      description: 'Validation error',
      content: { 'application/json': { schema: ErrorSchema } },
    },
  },
})
```

### Step 5 — Generate the spec

```typescript
// src/openapi/generate.ts

import { OpenApiGeneratorV3 } from '@asteasolutions/zod-to-openapi'
import { registry } from './registry'

// Import routes module to trigger route registrations (side effects)
import './routes'

export function generateOpenAPIDocument() {
  const generator = new OpenApiGeneratorV3(registry.definitions)
  return generator.generateDocument({
    openapi: '3.0.0',
    info: {
      title: 'My API',
      version: 'v1',
      description: 'Auto-generated from Zod schemas.',
    },
    servers: [
      { url: '/api/v1', description: 'Current version' },
    ],
  })
}
```

### Step 6 — Serve the spec and Swagger UI (Express)

```typescript
// src/app.ts

import express from 'express'
import swaggerUi from 'swagger-ui-express'
import { generateOpenAPIDocument } from './openapi/generate'

const app = express()
app.use(express.json())

// Generate once at startup — not on every request
const openApiDocument = generateOpenAPIDocument()

app.get('/openapi.json', (_req, res) => {
  res.setHeader('Content-Type', 'application/json')
  res.json(openApiDocument)
})

app.use('/docs', swaggerUi.serve, swaggerUi.setup(openApiDocument, {
  customSiteTitle: 'My API Docs',
}))

export default app
```

### Step 7 — CI smoke test

Add a script that generates the spec and asserts it is valid — catches missing route registrations and schema drift.

```typescript
// scripts/check-openapi.ts

import { generateOpenAPIDocument } from '../src/openapi/generate'
import { writeFileSync } from 'fs'

const doc = generateOpenAPIDocument()

// Basic sanity: paths must exist and be non-empty
if (!doc.paths || Object.keys(doc.paths).length === 0) {
  console.error('ERROR: OpenAPI spec has no paths registered.')
  process.exit(1)
}

console.log(`OpenAPI spec OK — ${Object.keys(doc.paths).length} paths registered.`)

// Optional: write to disk for review or commit
writeFileSync('openapi.json', JSON.stringify(doc, null, 2))
console.log('Wrote openapi.json')
```

Add to `package.json`:
```json
{
  "scripts": {
    "docs:check": "tsx scripts/check-openapi.ts",
    "docs:generate": "tsx scripts/check-openapi.ts"
  }
}
```

Add to CI pipeline:
```yaml
# .github/workflows/ci.yml
- name: Check OpenAPI spec
  run: pnpm docs:check
```

### The single `openapi.registry.ts` rule

Keep **one** registry file. All schemas import `z` from it. All route registrations live in `routes.ts` which is imported into `generate.ts`. The spec is generated once at process startup and cached. This structure means:

- Adding a new route = add a schema file + add a `registerPath` call in `routes.ts`
- No grep-hunting for where OpenAPI metadata lives
- No possibility of registering a schema with a different library import

### Summary checklist

- [ ] `extendZodWithOpenApi(z)` called once in `registry.ts`; `z` re-exported from there
- [ ] Every schema module imports `z` from `openapi/registry`, not from `zod`
- [ ] All request/response DTOs registered with `registry.register()`
- [ ] All routes registered with `registry.registerPath()` in `openapi/routes.ts`
- [ ] Every route has: `summary`, `description`, `tags`, `request` + `responses` for all status codes
- [ ] Spec served at `/openapi.json`; Swagger UI served at `/docs`
- [ ] CI smoke test runs `generateOpenAPIDocument()` and asserts paths are non-empty
- [ ] No hand-written YAML or JSON in the repo
