---
name: typescript-auth-security-patterns
description: Secure authentication and authorization patterns for Node.js/TypeScript — password hashing,
  session cookies, JWT, permission middleware, and Zod input validation.
when_to_use: Use when implementing authentication, authorization, or input validation in a TypeScript
  Node.js API.
group: languages
kind: skill
---

# TypeScript Auth Security Patterns

## Skill summary

- **Name:** `typescript-auth-security-patterns`
- **Description:** Secure authentication and authorization patterns for Node.js/TypeScript — password hashing, session cookies, JWT, permission middleware, and Zod input validation.
- **When to use:** Use when implementing authentication, authorization, or input validation in a TypeScript Node.js API.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- hash a password with bcrypt in TypeScript
- set up HttpOnly session cookies in Express
- sign and verify JWTs with the jose library
- add permission middleware to my routes
- validate request bodies with Zod before they reach my handler

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

Security is layered. Each layer below is independent — use all of them in a production API.

---

### Layer 1 — Password hashing (bcrypt)

Install:
```bash
pnpm add bcryptjs
pnpm add -D @types/bcryptjs
```

**Why bcrypt:** It is slow by design (configurable cost factor) and resistant to GPU-based brute force. Cost factor 12 is the minimum for new projects in 2024; increase to 13–14 on hardware that can afford it.

**The 72-byte limit:** bcrypt silently truncates input at 72 bytes. Pre-hash with SHA-256 before bcrypt if your password policy allows long passphrases.

```typescript
// src/lib/password.ts

import bcrypt from 'bcryptjs'
import { createHash } from 'crypto'

const COST_FACTOR = 12

/**
 * Pre-hash with SHA-256 to avoid the bcrypt 72-byte truncation issue.
 * The hex digest is always 64 bytes, well within bcrypt's limit.
 */
function prehash(password: string): string {
  return createHash('sha256').update(password).digest('hex')
}

export async function hashPassword(password: string): Promise<string> {
  const preHashed = prehash(password)
  return bcrypt.hash(preHashed, COST_FACTOR)
}

export async function verifyPassword(
  password: string,
  hash: string,
): Promise<boolean> {
  const preHashed = prehash(password)
  return bcrypt.compare(preHashed, hash)
}
```

Rules:
- Never store plaintext passwords — not in the DB, not in logs, not in Redis
- Never log the raw `password` field from `req.body`
- Use `verifyPassword` for login; never compare hashes with `===`

---

### Layer 2 — Session cookies (Express)

Prefer sessions over JWTs for web apps. The session store is server-side (Redis) so tokens can be invalidated instantly.

Install:
```bash
pnpm add express-session connect-redis ioredis
pnpm add -D @types/express-session
```

```typescript
// src/middleware/session.ts

import session from 'express-session'
import RedisStore from 'connect-redis'
import { Redis } from 'ioredis'
import { randomBytes } from 'crypto'

const redisClient = new Redis(process.env.REDIS_URL ?? 'redis://localhost:6379')

export const sessionMiddleware = session({
  store: new RedisStore({ client: redisClient, prefix: 'sess:' }),
  secret: process.env.SESSION_SECRET ?? randomBytes(32).toString('hex'),
  name: '__Host-sid',      // __Host- prefix requires Secure + no Domain
  resave: false,
  saveUninitialized: false,
  cookie: {
    httpOnly: true,        // not accessible to JS
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'strict',    // CSRF protection
    maxAge: 1000 * 60 * 60 * 24 * 7, // 7 days
  },
})
```

```typescript
// src/app.ts — wire it up before routes
import { sessionMiddleware } from './middleware/session'
app.use(sessionMiddleware)
```

```typescript
// src/routes/auth.ts — login handler
import { Router } from 'express'
import { UserService } from '../services/user-service'
import { verifyPassword } from '../lib/password'
import { errorResponse, successResponse } from '../lib/response'

const router = Router()

router.post('/login', async (req, res) => {
  const { email, password } = req.body  // Zod validation shown in Layer 5
  const user = await UserService.findByEmail(email)

  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    return res.status(401).json(
      errorResponse('Invalid credentials', 'INVALID_CREDENTIALS'),
    )
  }

  // Regenerate session ID after login (session fixation protection)
  req.session.regenerate((err) => {
    if (err) return res.status(500).json(errorResponse('Session error', 'SESSION_ERROR'))
    req.session.userId = user.id
    req.session.role = user.role
    res.status(200).json(successResponse({ userId: user.id }))
  })
})

router.post('/logout', (req, res) => {
  req.session.destroy(() => {
    res.clearCookie('__Host-sid')
    res.status(204).send()
  })
})

export default router
```

---

### Layer 3 — JWT (when needed)

Use JWTs for machine-to-machine auth or stateless API tokens. For user-facing web sessions, prefer the cookie approach above. Use `jose` — it is standards-compliant and has zero runtime dependencies.

Install:
```bash
pnpm add jose
```

**RS256 (asymmetric — recommended for multi-service):**

```typescript
// src/lib/jwt.ts

import { SignJWT, jwtVerify, generateKeyPair } from 'jose'

// In production: load key pair from env or a secrets manager
// Here: generate once for illustration
const { privateKey, publicKey } = await generateKeyPair('RS256')

const ISSUER = 'https://api.example.com'
const AUDIENCE = 'https://api.example.com'
const ACCESS_TOKEN_TTL = '15m'
const REFRESH_TOKEN_TTL = '7d'

export interface JwtPayload {
  sub: string       // user ID
  role: string
  type: 'access' | 'refresh'
}

export async function signAccessToken(payload: Omit<JwtPayload, 'type'>): Promise<string> {
  return new SignJWT({ ...payload, type: 'access' })
    .setProtectedHeader({ alg: 'RS256' })
    .setIssuedAt()
    .setIssuer(ISSUER)
    .setAudience(AUDIENCE)
    .setExpirationTime(ACCESS_TOKEN_TTL)
    .sign(privateKey)
}

export async function verifyAccessToken(token: string): Promise<JwtPayload> {
  const { payload } = await jwtVerify(token, publicKey, {
    issuer: ISSUER,
    audience: AUDIENCE,
  })

  if (payload.type !== 'access') {
    throw new Error('Not an access token')
  }

  return payload as unknown as JwtPayload
}
```

Rules:
- Never put sensitive data (passwords, PII) in the JWT payload — it is base64-encoded, not encrypted
- Validate: signature, expiry (`exp`), issuer (`iss`), audience (`aud`) — `jose` does all four automatically
- Short access token TTL (15 min); longer refresh token TTL (7 days)
- Refresh tokens must be stored server-side so they can be revoked

**JWT auth middleware:**

```typescript
// src/middleware/jwt-auth.ts

import { Request, Response, NextFunction } from 'express'
import { verifyAccessToken } from '../lib/jwt'
import { errorResponse } from '../lib/response'

export async function jwtAuth(req: Request, res: Response, next: NextFunction) {
  const authHeader = req.headers.authorization
  if (!authHeader?.startsWith('Bearer ')) {
    return res.status(401).json(errorResponse('Missing token', 'MISSING_TOKEN'))
  }

  const token = authHeader.slice(7)

  try {
    const payload = await verifyAccessToken(token)
    req.user = payload   // augment Request type (see type declaration below)
    next()
  } catch {
    return res.status(401).json(errorResponse('Invalid or expired token', 'INVALID_TOKEN'))
  }
}
```

```typescript
// src/types/express.d.ts — augment the Express Request type
import type { JwtPayload } from '../lib/jwt'

declare global {
  namespace Express {
    interface Request {
      user?: JwtPayload
    }
  }
}
```

---

### Layer 4 — Permission middleware

Declare permissions as middleware applied to routes — never check permissions inline inside route handlers. Fail fast, before business logic runs.

```typescript
// src/lib/permissions.ts

export const Permission = {
  USERS_READ: 'users:read',
  USERS_WRITE: 'users:write',
  ADMIN: 'admin',
} as const

export type Permission = typeof Permission[keyof typeof Permission]
```

```typescript
// src/middleware/require-permission.ts

import { Request, Response, NextFunction } from 'express'
import { errorResponse } from '../lib/response'
import type { Permission } from '../lib/permissions'

// Maps roles to the permissions they hold — in production, load from DB or config
const ROLE_PERMISSIONS: Record<string, Permission[]> = {
  admin: ['users:read', 'users:write', 'admin'],
  editor: ['users:read', 'users:write'],
  viewer: ['users:read'],
}

export function requirePermission(permission: Permission) {
  return (req: Request, res: Response, next: NextFunction) => {
    const user = req.user   // set by jwtAuth or session middleware
    if (!user) {
      return res.status(401).json(errorResponse('Not authenticated', 'UNAUTHENTICATED'))
    }

    const userPermissions = ROLE_PERMISSIONS[user.role] ?? []
    if (!userPermissions.includes(permission)) {
      return res.status(403).json(
        errorResponse('Insufficient permissions', 'FORBIDDEN'),
      )
    }

    next()
  }
}
```

```typescript
// src/routes/users.ts — permission applied at the route level
import { jwtAuth } from '../middleware/jwt-auth'
import { requirePermission } from '../middleware/require-permission'
import { Permission } from '../lib/permissions'

router.get(
  '/:id',
  jwtAuth,
  requirePermission(Permission.USERS_READ),
  getUserHandler,
)

router.post(
  '/',
  jwtAuth,
  requirePermission(Permission.USERS_WRITE),
  createUserHandler,
)
```

---

### Layer 5 — Zod input validation middleware

All external input — `req.body`, `req.params`, `req.query` — must pass through Zod before reaching a handler. Never trust raw request data.

```typescript
// src/middleware/validate.ts

import { Request, Response, NextFunction } from 'express'
import { ZodSchema, ZodError } from 'zod'
import { errorResponse } from '../lib/response'

export function validateBody<T>(schema: ZodSchema<T>) {
  return (req: Request, res: Response, next: NextFunction) => {
    const result = schema.safeParse(req.body)
    if (!result.success) {
      const messages = result.error.errors.map(
        (e) => `${e.path.join('.')}: ${e.message}`,
      )
      return res.status(422).json(
        errorResponse(messages, 'VALIDATION_ERROR'),
      )
    }
    req.body = result.data  // replace with parsed + typed data
    next()
  }
}

export function validateParams<T>(schema: ZodSchema<T>) {
  return (req: Request, res: Response, next: NextFunction) => {
    const result = schema.safeParse(req.params)
    if (!result.success) {
      return res.status(400).json(
        errorResponse('Invalid path parameters', 'INVALID_PARAMS'),
      )
    }
    req.params = result.data as Record<string, string>
    next()
  }
}
```

```typescript
// Usage in routes
import { z } from 'zod'
import { validateBody, validateParams } from '../middleware/validate'

const createUserBodySchema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(100),
  password: z.string().min(12),
})

router.post(
  '/',
  jwtAuth,
  requirePermission(Permission.USERS_WRITE),
  validateBody(createUserBodySchema),
  createUserHandler,   // req.body is fully typed and validated here
)
```

---

### Summary checklist

- [ ] Passwords hashed with bcrypt, cost factor 12+; pre-hashed with SHA-256 for long inputs
- [ ] No plaintext passwords in logs, DB, or cache
- [ ] Session cookies: `HttpOnly`, `Secure`, `SameSite=Strict`, stored in Redis
- [ ] Session ID regenerated after login (`req.session.regenerate`)
- [ ] JWTs signed with RS256 for multi-service; HS256 only for single-service
- [ ] JWT validation checks: signature, `exp`, `iss`, `aud` — use `jose`, not `jsonwebtoken`
- [ ] Sensitive data never in JWT payload
- [ ] Access token TTL 15 min; refresh token TTL 7 days; refresh tokens stored server-side
- [ ] Permissions declared as middleware; never checked inline in handlers
- [ ] `Permission` is a typed const object, not loose strings
- [ ] All `req.body`, `req.params`, `req.query` parsed through Zod before handler runs
- [ ] Validation failures return 422 with `VALIDATION_ERROR` code in the standard envelope
