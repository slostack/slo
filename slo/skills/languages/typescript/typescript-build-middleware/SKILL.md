---
name: typescript-build-middleware
description: Build single-concern TypeScript middleware for Express or Hono — auth, logging, rate-limiting
  — with correct async error propagation and context attachment.
when_to_use: Use when adding auth, logging, rate-limiting, or request-context middleware to a TypeScript
  Express or Hono application.
group: languages
kind: skill
---

# TypeScript Build Middleware

## Skill summary

- **Name:** `typescript-build-middleware`
- **Description:** Build single-concern TypeScript middleware for Express or Hono — auth, logging, rate-limiting — with correct async error propagation and context attachment.
- **When to use:** Use when adding auth, logging, rate-limiting, or request-context middleware to a TypeScript Express or Hono application.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "add a JWT auth middleware that attaches the user to the Hono context"
- "write request logging middleware that records method, path, status, and duration"
- "create an error handling middleware for Express that normalizes AppError and ZodError"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

**Response-profile status:** the retained `ok()`/`fail()` calls and envelope are profile-specific implementation examples from an unknown-profile historical framework recipe, not a universal response standard. For new or changed TypeScript APIs, select the [TypeScript API response profile](../typescript-api-response-conventions/SKILL.md) and the [language-independent response contract](../../../coding/api-response-conventions/SKILL.md); those owners decide concrete fields, version, error shape, status mapping, pagination, and helper behavior. For an existing API, preserve observed/project-documented wire bytes and require an explicit existing/project contract before changing them. This middleware recipe owns lifecycle mechanics, not a competing wire format.

Middleware in TypeScript follows the same single-concern discipline as its Python counterpart. Each middleware function does one thing: it either enriches the request context (auth, request ID, parsed tenant) or it intercepts a specific lifecycle stage (logging, error normalization). Business logic never appears inside middleware.

### Core rules

1. **One concern per middleware function** — auth OR logging OR rate-limit. Never combined.
2. **No business logic** — middleware sets context values (user, request ID, tenant) that route handlers read. It does not perform domain operations.
3. **Context values go on `ctx.set()` (Hono) or `res.locals` (Express)** — never mutate `req.body`, `req.params`, or `req.query`.
4. **Async errors must propagate** — in Express, catch async errors and call `next(error)`. In Hono, throw — the framework propagates automatically.
5. **Order is load-order and must be documented** — log → auth → validation → route handler. Document the order in the app setup file.
6. **Middleware signatures are strict** — Express: `(req, res, next) => void`. Hono: `(ctx, next) => Promise<Response | void>`.

---

### Middleware execution order (document this in `app.ts`)

```typescript
// src/app.ts
// Middleware order (top to bottom):
//   1. requestIdMiddleware  — attach unique request ID before anything else
//   2. requestLogMiddleware — log after ID is set, before auth can short-circuit
//   3. authMiddleware       — validate JWT, attach AuthContext
//   4. Route handlers
//   5. errorHandler         — catch all thrown AppError / ZodError

app.use('/*', requestIdMiddleware);
app.use('/*', requestLogMiddleware);
app.use('/api/*', authMiddleware);   // only API routes need auth
app.route('/api/v1/users', usersRouter);
app.onError(errorHandler);
```

---

### Request ID middleware (Hono)

```typescript
// src/middleware/request-id.middleware.ts
import { createMiddleware } from 'hono/factory';
import { randomUUID } from 'node:crypto';

declare module 'hono' {
  interface ContextVariableMap {
    requestId: string;
  }
}

export const requestIdMiddleware = createMiddleware(async (ctx, next) => {
  const requestId =
    ctx.req.header('X-Request-Id') ?? randomUUID();

  ctx.set('requestId', requestId);
  ctx.res.headers.set('X-Request-Id', requestId);

  await next();
});
```

---

### Request logging middleware (Hono)

```typescript
// src/middleware/request-log.middleware.ts
import { createMiddleware } from 'hono/factory';

export const requestLogMiddleware = createMiddleware(async (ctx, next) => {
  const start = Date.now();

  await next();

  const durationMs = Date.now() - start;
  const requestId = ctx.get('requestId') ?? '-';

  console.log(
    JSON.stringify({
      type: 'http_request',
      method: ctx.req.method,
      path: new URL(ctx.req.url).pathname,
      status: ctx.res.status,
      duration_ms: durationMs,
      request_id: requestId,
    }),
  );
});
```

---

### Auth middleware (Hono)

Validates a JWT, attaches `AuthContext` to the Hono context. Route handlers read it with `ctx.get('auth')`.

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

declare module 'hono' {
  interface ContextVariableMap {
    auth: AuthContext;
  }
}

export const authMiddleware = createMiddleware(async (ctx, next) => {
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
    roles: Array.isArray(payload.roles) ? (payload.roles as string[]) : [],
  });

  await next();
});
```

Usage in a route handler (historical unknown-profile helper example; use the selected TypeScript profile's helper in a real project):

```typescript
usersRouter.get('/me', async (ctx) => {
  const auth = ctx.get('auth'); // typed as AuthContext
  const user = await UserService.getById(auth.userId);
  return ctx.json(ok(user));
});
```

---

### Role guard middleware (Hono)

Compose on top of `authMiddleware` — never combine the JWT check and the role check into one function:

```typescript
// src/middleware/require-role.middleware.ts
import { createMiddleware } from 'hono/factory';
import { ForbiddenError } from '../lib/errors.js';

export function requireRole(...roles: string[]) {
  return createMiddleware(async (ctx, next) => {
    const auth = ctx.get('auth');
    const hasRole = roles.some((r) => auth.roles.includes(r));

    if (!hasRole) {
      throw new ForbiddenError(
        `Requires one of: ${roles.join(', ')}`,
      );
    }

    await next();
  });
}
```

Usage:

```typescript
adminRouter.use('/*', authMiddleware);
adminRouter.use('/*', requireRole('admin'));
```

---

### Error handling middleware (Hono)

Registered with `app.onError()`. Normalizes `AppError`, `ZodError`, and unknown errors through the selected response profile. The `fail()` calls below are retained historical unknown-profile implementation examples, not a universal envelope:

```typescript
// src/middleware/error.middleware.ts
import type { ErrorHandler } from 'hono';
import { ZodError } from 'zod';
import { AppError } from '../lib/errors.js';
import { fail } from '../lib/response.js';

export const errorHandler: ErrorHandler = (err, ctx) => {
  if (err instanceof ZodError) {
    const messages = err.errors.map((e) => `${e.path.join('.')}: ${e.message}`).join('; ');
    return ctx.json(fail('VALIDATION_ERROR', messages), 422);
  }

  if (err instanceof AppError) {
    return ctx.json(
      fail(err.code, err.message),
      err.statusCode as 400 | 401 | 403 | 404 | 409 | 500,
    );
  }

  const requestId = ctx.get('requestId') ?? '-';
  console.error(
    JSON.stringify({ type: 'unhandled_error', request_id: requestId, error: String(err) }),
  );

  return ctx.json(fail('INTERNAL_ERROR', 'An unexpected error occurred'), 500);
};
```

---

### Express equivalents

For teams using Express, the signatures differ but the rules are identical. The retained `fail()` calls below use the same historical unknown-profile example; route concrete response shape, fields, version, errors, and statuses through the selected TypeScript profile and generic owner.

```typescript
// Express auth middleware
import type { Request, Response, NextFunction } from 'express';
import { verify } from 'jsonwebtoken';
import { UnauthorizedError } from '../lib/errors.js';

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const authHeader = req.headers.authorization;

  if (!authHeader?.startsWith('Bearer ')) {
    return next(new UnauthorizedError());
  }

  const token = authHeader.slice(7);

  try {
    const payload = verify(token, process.env.JWT_SECRET!);
    res.locals.auth = {
      userId: (payload as Record<string, unknown>).sub,
      email: (payload as Record<string, unknown>).email,
      roles: (payload as Record<string, unknown>).roles ?? [],
    };
    next();
  } catch {
    next(new UnauthorizedError());
  }
}

// Express error middleware — MUST have 4 arguments for Express to recognize it
export function errorMiddleware(
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof AppError) {
    res.status(err.statusCode).json(fail(err.code, err.message));
    return;
  }
  res.status(500).json(fail('INTERNAL_ERROR', 'An unexpected error occurred'));
}
```

---

### Middleware checklist

Before finishing a middleware, verify:

- [ ] It does exactly one thing — no combined auth + logging + rate-limit
- [ ] No business logic or domain service calls inline
- [ ] Context values go on `ctx.set()` or `res.locals` — not on `req.body`
- [ ] Async errors propagate: throw (Hono) or `next(error)` (Express) — never swallowed
- [ ] `ContextVariableMap` is augmented (Hono) or `res.locals` is typed (Express) so downstream handlers are typed
- [ ] The middleware is registered in the correct order in `app.ts`, with a comment documenting the stack
- [ ] Response helpers and concrete response fields/statuses follow the selected TypeScript response profile; do not treat the historical `ok()`/`fail()` example as universal
