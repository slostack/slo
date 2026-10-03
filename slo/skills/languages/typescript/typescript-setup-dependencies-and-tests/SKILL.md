---
name: typescript-setup-dependencies-and-tests
description: Install and configure the TypeScript test stack — Vitest, coverage, Supertest for HTTP routes,
  and msw for mocking external HTTP calls.
when_to_use: Use when adding or configuring the test infrastructure for a TypeScript project.
group: languages
kind: skill
---

# TypeScript Setup Dependencies and Tests

## Skill summary

- **Name:** `typescript-setup-dependencies-and-tests`
- **Description:** Install and configure the TypeScript test stack — Vitest, coverage, Supertest for HTTP routes, and msw for mocking external HTTP calls.
- **When to use:** Use when adding or configuring the test infrastructure for a TypeScript project.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up the test stack for this TypeScript project"
- "Add Vitest and coverage to the project"
- "How do I mock HTTP calls in TypeScript tests?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Why Vitest over Jest

Vitest is preferred for TypeScript projects because:
- Native TypeScript support — no Babel transform, no `ts-jest`
- Identical API to Jest (`describe`, `it`, `expect`, `vi` === `jest`) — migration is trivial
- Runs in the same Vite process as bundled code — path aliases work automatically
- Significantly faster on large suites due to parallelism and module caching

### Step 1 — Install

```bash
# Core test tools
pnpm add -D vitest @vitest/coverage-v8

# HTTP route testing (works with Express, Fastify, Hono, etc.)
pnpm add -D supertest @types/supertest

# External HTTP mocking
pnpm add -D msw

# Optional: in-memory Postgres for integration tests
pnpm add -D @databases/pg-test
```

### Step 2 — vitest.config.ts

```typescript
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    // Run in Node — no DOM, no jsdom overhead
    environment: 'node',

    // Don't use globals — explicit imports make it clear where vi/expect come from
    globals: false,

    // Runs before each test file — not before each test
    setupFiles: ['./tests/setup.ts'],

    // File patterns to include
    include: ['tests/**/*.test.ts'],

    // Exclude build artifacts
    exclude: ['node_modules', 'dist'],

    // Timeout for async tests (ms)
    testTimeout: 10_000,

    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.ts'],
      exclude: [
        'src/index.ts',        // entrypoint — no logic to test
        'src/**/*.d.ts',
        'src/config/cfg.ts',   // env loading — tested implicitly
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80,
      },
    },
  },
  resolve: {
    alias: {
      // Must match tsconfig.json paths exactly
      '@': resolve(__dirname, 'src'),
    },
  },
});
```

### Step 3 — tests/setup.ts

Global setup that runs before every test file:

```typescript
import { vi, afterEach, beforeAll, afterAll } from 'vitest';
import { db } from '@/connectors/db';

beforeAll(async () => {
  // Any one-time global setup (e.g., run migrations against test DB)
});

afterEach(() => {
  // Reset all mocks between tests — critical to prevent test pollution
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

afterAll(async () => {
  // Close DB connection pool so the process can exit cleanly
  await db.$disconnect();
});
```

### Step 4 — tests/helpers/factories.ts

Factory functions create valid test data without repetition. Use named parameters throughout:

```typescript
import { v4 as uuid } from 'uuid';
import type { User } from '@/domains/user/entity';
import type { CreateUserDto } from '@/domains/user/dto';

export function buildUser(overrides: Partial<User> = {}): User {
  return {
    id:        overrides.id        ?? uuid(),
    email:     overrides.email     ?? `user-${uuid()}@example.com`,
    fullName:  overrides.fullName  ?? 'Test User',
    createdAt: overrides.createdAt ?? new Date(),
    updatedAt: overrides.updatedAt ?? new Date(),
  };
}

export function buildCreateUserDto(overrides: Partial<CreateUserDto> = {}): CreateUserDto {
  return {
    email:    overrides.email    ?? `user-${uuid()}@example.com`,
    fullName: overrides.fullName ?? 'Test User',
  };
}
```

### Step 5 — Writing a Domain Service Test

```typescript
// tests/domains/user/user.service.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { UserService } from '@/domains/user/service';
import { db } from '@/connectors/db';
import { buildCreateUserDto, buildUser } from '../../helpers/factories';

vi.mock('@/connectors/db', () => ({
  db: {
    user: {
      findUnique: vi.fn(),
      create:     vi.fn(),
      update:     vi.fn(),
      delete:     vi.fn(),
    },
  },
}));

describe('UserService', () => {
  describe('getById', () => {
    it('returns the user when found', async () => {
      const user = buildUser();
      vi.mocked(db.user.findUnique).mockResolvedValueOnce(user);

      const result = await UserService.getById(user.id);

      expect(result).toEqual(user);
      expect(db.user.findUnique).toHaveBeenCalledWith({ where: { id: user.id } });
    });

    it('returns null when not found', async () => {
      vi.mocked(db.user.findUnique).mockResolvedValueOnce(null);

      const result = await UserService.getById('non-existent-id');

      expect(result).toBeNull();
    });
  });

  describe('create', () => {
    it('creates and returns the new user', async () => {
      const dto   = buildCreateUserDto();
      const saved = buildUser({ email: dto.email, fullName: dto.fullName });
      vi.mocked(db.user.create).mockResolvedValueOnce(saved);

      const result = await UserService.create(dto);

      expect(result).toEqual(saved);
      expect(db.user.create).toHaveBeenCalledWith({ data: dto });
    });
  });
});
```

### Step 6 — Writing an HTTP Route Test with Supertest

```typescript
// tests/routers/user.router.test.ts
import { describe, it, expect, vi } from 'vitest';
import request from 'supertest';
import { createApp } from '@/app';
import { UserService } from '@/domains/user/service';
import { buildUser } from '../helpers/factories';

vi.mock('@/domains/user/service');

const app = createApp();

describe('POST /users', () => {
  it('creates a user and returns 201', async () => {
    const user = buildUser();
    vi.mocked(UserService.getByEmail).mockResolvedValueOnce(null);
    vi.mocked(UserService.create).mockResolvedValueOnce(user);

    const response = await request(app)
      .post('/users')
      .send({ email: user.email, fullName: user.fullName })
      .set('Accept', 'application/json');

    expect(response.status).toBe(201);
    expect(response.body).toMatchObject({ id: user.id, email: user.email });
  });

  it('returns 409 when email is already taken', async () => {
    const user = buildUser();
    vi.mocked(UserService.getByEmail).mockResolvedValueOnce(user);

    const response = await request(app)
      .post('/users')
      .send({ email: user.email, fullName: 'Someone Else' });

    expect(response.status).toBe(409);
  });
});
```

### Step 7 — Mocking External HTTP with msw

```typescript
// tests/helpers/msw-server.ts
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

export const mswServer = setupServer();

// tests/setup.ts — add to global setup
import { mswServer } from './helpers/msw-server';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());
```

In a test:
```typescript
import { http, HttpResponse } from 'msw';
import { mswServer } from '../helpers/msw-server';

it('handles upstream API returning 503', async () => {
  mswServer.use(
    http.get('https://api.stripe.com/v1/customers/*', () => {
      return HttpResponse.json({ error: 'Service unavailable' }, { status: 503 });
    }),
  );

  await expect(StripeClient.getCustomer('cus_123')).rejects.toThrow('Service unavailable');
});
```

### Step 8 — Running Tests

```bash
# Run all tests once (CI mode)
pnpm vitest run

# Watch mode (development)
pnpm vitest

# Run a single file
pnpm vitest run tests/domains/user/user.service.test.ts

# Run tests matching a name pattern
pnpm vitest run --reporter=verbose -t "creates a user"

# With coverage
pnpm vitest run --coverage

# Update snapshots
pnpm vitest run --update-snapshots
```

### package.json Scripts

```json
{
  "scripts": {
    "test":          "vitest run",
    "test:watch":    "vitest",
    "test:coverage": "vitest run --coverage",
    "test:ui":       "vitest --ui"
  }
}
```

### Key Rules

1. **Never import from `src/config/cfg.ts` in tests** — mock the connector, not the config.
2. **Always call `vi.clearAllMocks()` in `afterEach`** — failure to do so causes tests to bleed into each other.
3. **Factory functions use named overrides** — `buildUser({ email: 'x@y.com' })`, never positional.
4. **Mock at the module boundary** — mock `@/connectors/db`, not individual ORM methods inline.
5. **Supertest creates the real Express app** — don't mock the router layer; test it.
6. **msw intercepts at the network level** — use it for external services, not internal modules.
