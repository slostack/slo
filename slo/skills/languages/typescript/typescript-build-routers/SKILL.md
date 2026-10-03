---
name: typescript-build-routers
description: Build typed Express/Hono server route files with thin handlers, Zod validation, auth middleware,
  and standard response envelopes.
when_to_use: Use when building TypeScript HTTP route handlers in Express or Hono, adding API endpoints,
  or structuring a new router file for a domain resource.
group: languages
kind: skill
---

# TypeScript Build Routers

## Skill summary

- **Name:** `typescript-build-routers`
- **Description:** Build typed Express/Hono server route files with thin handlers, Zod validation, auth middleware, and standard response envelopes.
- **When to use:** Use when building TypeScript HTTP route handlers in Express or Hono, adding API endpoints, or structuring a new router file for a domain resource.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "add a POST /users route that validates the body and delegates to UserService"
- "create a router file for the orders resource with auth middleware"
- "build a Hono route group for the /api/v1/documents endpoints"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

Route files in TypeScript follow the same thin-handler discipline as their Python FastAPI equivalents. The route handler's only job is to parse the incoming request, call the relevant service method, and wrap the result in the standard response envelope. No business logic lives inline.

### Core rules

1. **Handlers are thin**: parse request → call service → wrap response. Nothing else.
2. **Auth is declared as middleware**, never as an inline `if (!user) return res.status(401)...` check inside the handler.
3. **Zod validates all request bodies** at the boundary. Never trust `req.body` with a bare type assertion.
4. **Response shape is always `{ data, errors }`** — success sets `data`, failures set `errors` with a code and message.
5. **Error handling is centralized** in an error middleware registered after all routes. Route handlers never catch-and-return inline.
6. **One router file per domain resource** — `users.router.ts`, `orders.router.ts`, etc.
7. **Each router file exports one Hono app group** (or one Express `Router` instance).

---

### Standard response envelope

Define this once in `src/lib/response.ts` and import it everywhere:

```typescript
// src/lib/response.ts

export interface ApiError {
  code: string;
  message: string;
}

export interface ApiResponse<T> {
  data: T | null;
  errors: ApiError[] | null;
}

export function ok<T>(data: T): ApiResponse<T> {
  return { data, errors: null };
}

export function fail(code: string, message: string): ApiResponse<never> {
  return { data: null, errors: [{ code, message }] };
}
```

---

### Typed error class

```typescript
// src/lib/errors.ts

export class AppError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode: number = 400,
  ) {
    super(message);
    this.name = 'AppError';
  }
}

export class NotFoundError extends AppError {
  constructor(resource: string) {
    super('NOT_FOUND', `${resource} not found`, 404);
  }
}

export class UnauthorizedError extends AppError {
  constructor() {
    super('UNAUTHORIZED', 'Authentication required', 401);
  }
}
```

---

### Auth middleware (Hono)

```typescript
// src/middleware/auth.middleware.ts
import { createMiddleware } from 'hono/factory';
import { verify } from 'hono/jwt';
import { UnauthorizedError } from '../lib/errors.js';

export interface AuthContext {
  userId: string;
  email: string;
  roles: string[];
}

export const authMiddleware = createMiddleware<{
  Variables: { auth: AuthContext };
}>(async (ctx, next) => {
  const authHeader = ctx.req.header('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    throw new UnauthorizedError();
  }

  const token = authHeader.slice(7);
  const payload = await verify(token, process.env.JWT_SECRET!).catch(() => {
    throw new UnauthorizedError();
  });

  ctx.set('auth', {
    userId: payload.sub as string,
    email: payload.email as string,
    roles: (payload.roles as string[]) ?? [],
  });

  await next();
});
```

---

### Zod request schema

```typescript
// src/domains/users/users.schemas.ts
import { z } from 'zod';

export const CreateUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(200),
  role: z.enum(['admin', 'member', 'viewer']).default('member'),
});

export type CreateUserRequest = z.infer<typeof CreateUserSchema>;

export const UpdateUserSchema = CreateUserSchema.partial().omit({ email: true });
export type UpdateUserRequest = z.infer<typeof UpdateUserSchema>;
```

---

### Router file (Hono — preferred)

```typescript
// src/domains/users/users.router.ts
import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { authMiddleware } from '../../middleware/auth.middleware.js';
import { UserService } from './users.service.js';
import { CreateUserSchema, UpdateUserSchema } from './users.schemas.js';
import { ok } from '../../lib/response.js';
import { NotFoundError } from '../../lib/errors.js';

const usersRouter = new Hono();

// All routes in this group require authentication.
usersRouter.use('/*', authMiddleware);

usersRouter.get('/', async (ctx) => {
  const auth = ctx.get('auth');
  const users = await UserService.listForAccount(auth.userId);
  return ctx.json(ok(users));
});

usersRouter.post(
  '/',
  zValidator('json', CreateUserSchema),
  async (ctx) => {
    const body = ctx.req.valid('json');
    const auth = ctx.get('auth');
    const user = await UserService.create({ ...body, createdBy: auth.userId });
    return ctx.json(ok(user), 201);
  },
);

usersRouter.get('/:userId', async (ctx) => {
  const { userId } = ctx.req.param();
  const user = await UserService.getById(userId);
  if (!user) throw new NotFoundError('User');
  return ctx.json(ok(user));
});

usersRouter.patch(
  '/:userId',
  zValidator('json', UpdateUserSchema),
  async (ctx) => {
    const { userId } = ctx.req.param();
    const body = ctx.req.valid('json');
    const user = await UserService.update(userId, body);
    if (!user) throw new NotFoundError('User');
    return ctx.json(ok(user));
  },
);

usersRouter.delete('/:userId', async (ctx) => {
  const { userId } = ctx.req.param();
  await UserService.delete(userId);
  return ctx.json(ok(null), 204);
});

export { usersRouter };
```

---

### Error middleware (Hono)

```typescript
// src/middleware/error.middleware.ts
import type { ErrorHandler } from 'hono';
import { ZodError } from 'zod';
import { AppError } from '../lib/errors.js';
import { fail } from '../lib/response.js';

export const errorHandler: ErrorHandler = (err, ctx) => {
  if (err instanceof ZodError) {
    return ctx.json(
      fail('VALIDATION_ERROR', err.errors.map((e) => e.message).join('; ')),
      422,
    );
  }

  if (err instanceof AppError) {
    return ctx.json(fail(err.code, err.message), err.statusCode as 400 | 401 | 404 | 500);
  }

  console.error('[unhandled error]', err);
  return ctx.json(fail('INTERNAL_ERROR', 'An unexpected error occurred'), 500);
};
```

---

### App assembly

```typescript
// src/app.ts
import { Hono } from 'hono';
import { usersRouter } from './domains/users/users.router.js';
import { ordersRouter } from './domains/orders/orders.router.js';
import { errorHandler } from './middleware/error.middleware.js';

export function buildApp(): Hono {
  const app = new Hono();

  // Register domain routers under the API namespace.
  app.route('/api/v1/users', usersRouter);
  app.route('/api/v1/orders', ordersRouter);

  // Centralized error handler — must be last.
  app.onError(errorHandler);

  return app;
}
```

---

### Router file checklist

Before finishing a router file, verify:

- [ ] No business logic inline — every non-trivial operation delegates to a service
- [ ] Auth is declared with `usersRouter.use('/*', authMiddleware)` at the top
- [ ] Every POST/PATCH/PUT uses `zValidator('json', Schema)` — no raw `req.body` access
- [ ] Every response is wrapped with `ok(data)` or throws an `AppError` subclass
- [ ] The router is exported as a named export and mounted in `app.ts`
- [ ] Error handling happens in `errorHandler`, not per-route try/catch blocks
