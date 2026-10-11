---
name: typescript-api-response-conventions
description: Standard JSON response envelope for all TypeScript API endpoints — success, error, and list
  responses in a consistent shape.
when_to_use: Use when building or reviewing TypeScript API endpoints that need a consistent response envelope.
group: languages
kind: skill
---

# TypeScript API Response Conventions

## Skill summary

- **Name:** `typescript-api-response-conventions`
- **Description:** Standard JSON response envelope for all TypeScript API endpoints — success, error, and list responses in a consistent shape.
- **When to use:** Use when building or reviewing TypeScript API endpoints that need a consistent response envelope.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- add api response envelope to my route handlers
- what shape should my API responses take?
- write the successResponse and errorResponse helpers
- validate API responses with Zod in tests
- add a list endpoint with pagination

## Guidance

**Scope:** TypeScript; load `skills/coding/api-response-conventions/SKILL.md` for the language-independent envelope semantics and `skills/languages/typescript/typescript-conventions/SKILL.md` for TypeScript routing. Framework examples apply only to the declared stack. This file owns TypeScript types, factories, Zod schemas, and TypeScript contract tests for the selected wire profile; it does not silently change an existing API's version, pagination, or error-code values. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

Load `skills/coding/api-response-conventions/SKILL.md` for the language-independent envelope semantics and compatibility rules. This focused recipe owns the TypeScript adapter: its types, factories, Zod schemas, framework examples, and tests for the selected wire profile. Every endpoint in that profile — success path and error path alike — returns the same JSON envelope. Existing deployed wire values remain authoritative.

### The envelope type

```typescript
// src/types/api-response.ts

export interface ApiResponse<T = unknown> {
  data: T | null
  errors: {
    msg: string[]
    code: string | null
  }
  api_version: string
}
```

Rules:
- **Success in this profile:** `data` carries the payload; `errors` is `{ msg: [], code: null }`.
- **Error in this profile:** `data` is `null`; `errors.msg` has one or more human-readable messages; `errors.code` uses the profile's stable public-code policy.
- This profile rejects unapproved extra root-level fields (`success`, `meta`, `pagination`); everything else remains inside `data` or `errors`.
- `api_version` is always present in this profile; its value comes from an env var or constant (the example uses `"v1"`).
- Existing endpoints with a different version, error, or pagination profile require an explicit compatibility decision.

### Factory helpers

```typescript
// src/lib/response.ts

import type { ApiResponse } from '../types/api-response'

const API_VERSION = process.env.API_VERSION ?? 'v1'

export function successResponse<T>(data: T): ApiResponse<T> {
  return {
    data,
    errors: { msg: [], code: null },
    api_version: API_VERSION,
  }
}

export function errorResponse(
  msg: string | string[],
  code: string,
): ApiResponse<never> {
  return {
    data: null,
    errors: {
      msg: Array.isArray(msg) ? msg : [msg],
      code: code.toUpperCase(),
    },
    api_version: API_VERSION,
  }
}
```

### Route handler usage (Express)

```typescript
// src/routes/users.ts

import { Router, Request, Response } from 'express'
import { successResponse, errorResponse } from '../lib/response'
import type { ApiResponse } from '../types/api-response'
import { UserService } from '../services/user-service'

const router = Router()

router.get('/:id', async (req: Request, res: Response) => {
  const user = await UserService.findById(req.params.id)

  if (!user) {
    const body = errorResponse('User not found', 'USER_NOT_FOUND') satisfies ApiResponse<never>
    return res.status(404).json(body)
  }

  const body = successResponse(user) satisfies ApiResponse<typeof user>
  return res.status(200).json(body)
})

export default router
```

The `satisfies ApiResponse<T>` assertion gives compile-time verification that the returned object matches the envelope shape without widening the inferred type.

### List page DTO

List endpoints never return a bare array at `data`. They return a page DTO so clients always know the total count and can paginate.

```typescript
// src/types/page.ts

export interface Page<T> {
  page: number
  size: number
  total: number
  items: T[]
}
```

```typescript
// Usage in a list route
import type { Page } from '../types/page'

router.get('/', async (req: Request, res: Response) => {
  // This illustrative profile uses page 1 and size 20; a project profile may differ.
  const page = Number(req.query.page ?? 1)
  const size = Number(req.query.size ?? 20)

  const [items, total] = await UserService.list({ page, size })

  const pageDto: Page<UserDTO> = { page, size, total, items }
  return res.status(200).json(successResponse(pageDto))
})
```

### Zod schema for the envelope

Use this schema to validate responses in integration tests and in client-side code.

```typescript
// src/schemas/api-response.schema.ts

import { z } from 'zod'

export const errorsSchema = z.object({
  msg: z.array(z.string()),
  code: z.string().nullable(),
})

export function apiResponseSchema<T extends z.ZodTypeAny>(dataSchema: T) {
  return z.object({
    data: dataSchema.nullable(),
    errors: errorsSchema,
    api_version: z.string(),
  })
}

// Usage in tests
import { apiResponseSchema } from '../schemas/api-response.schema'
import { userSchema } from '../schemas/user.schema'

const responseSchema = apiResponseSchema(userSchema)
const parsed = responseSchema.parse(responseBody) // throws on mismatch
```

### Test helper

```typescript
// tests/helpers/assert-response.ts

import { apiResponseSchema } from '../../src/schemas/api-response.schema'
import type { ZodTypeAny } from 'zod'

export function assertSuccessResponse<T extends ZodTypeAny>(
  body: unknown,
  dataSchema: T,
) {
  const schema = apiResponseSchema(dataSchema)
  const result = schema.safeParse(body)
  if (!result.success) throw new Error(result.error.toString())
  if (result.data.data === null) throw new Error('Expected data, got null')
  if (result.data.errors.code !== null) throw new Error('Expected no error code')
  return result.data.data
}

export function assertErrorResponse(body: unknown, expectedCode: string) {
  const schema = apiResponseSchema(z.never())
  const result = schema.safeParse({ ...body, data: null })
  if (!result.success) throw new Error(result.error.toString())
  if (result.data.errors.code !== expectedCode) {
    throw new Error(
      `Expected error code ${expectedCode}, got ${result.data.errors.code}`,
    )
  }
}
```

### Summary checklist

- [ ] Every route returns `ApiResponse<T>` — success and error paths both
- [ ] `successResponse()` and `errorResponse()` factories used everywhere — no inline object literals
- [ ] Error codes follow the selected profile's stable public-code policy
- [ ] List endpoints return `Page<T>` inside `data` for this profile, never a bare array
- [ ] No unapproved extra root-level keys (`success`, `meta`, `pagination`)
- [ ] Zod schema validates responses in tests
- [ ] `satisfies ApiResponse<T>` used in route handlers for compile-time safety
