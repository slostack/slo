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

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. This recipe covers TypeScript test-stack setup only.

- Tests run against a real, disposable test database (`DATABASE_URL` in the test environment). Never mock `@/connectors/db`, repositories or internal services.
- `msw` is for third-party HTTP only.

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

# Third-party HTTP mocking (vendor APIs only)
pnpm add -D msw
```

- Run a disposable Postgres for tests (Docker Compose service or CI service container) and apply migrations before the suite, for example `DATABASE_URL=$TEST_DATABASE_URL pnpm prisma migrate deploy`.

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

    // Test files share one test database; run them one at a time so resets do not collide
    fileParallelism: false,

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
import { afterAll, beforeAll } from 'vitest';
import { db } from '@/connectors/db';

beforeAll((): void => {
  // Refuse to run against anything but the test database
  if (!process.env.DATABASE_URL?.includes('_test')) {
    throw new Error('DATABASE_URL must point at the disposable test database');
  }
});

afterAll(async (): Promise<void> => {
  // Close DB connection pool so the process can exit cleanly
  await db.$disconnect();
});
```

### Step 3b — tests/helpers/db.ts

- `resetTestDatabase()` truncates every application table in the test database from `DATABASE_URL`.
- Call it in `beforeEach` of every test that touches persistence. `typescript-test-domain-services`, `typescript-test-app-services` and `typescript-test-controllers` use it.

```typescript
// tests/helpers/db.ts
import { db } from '@/connectors/db';

/** Truncate every application table in the test database so each test starts empty. */
export async function resetTestDatabase(): Promise<void> {
  const tables: Array<{ tablename: string }> = await db.$queryRaw<Array<{ tablename: string }>>`
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename <> '_prisma_migrations'
  `;
  if (tables.length === 0) {
    return;
  }
  const tableList: string = tables.map(({ tablename }): string => `"public"."${tablename}"`).join(', ');
  await db.$executeRawUnsafe(`TRUNCATE TABLE ${tableList} RESTART IDENTITY CASCADE`);
}
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

- Use the real repository against the test database. See `typescript-test-domain-services` for the full recipe.

```typescript
// tests/domains/user/user.service.test.ts
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '@/connectors/db';
import { UserRepository } from '@/domains/user/repository';
import { UserService } from '@/domains/user/service';
import { buildCreateUserDto } from '../../helpers/factories';
import { resetTestDatabase } from '../../helpers/db';

describe('UserService', (): void => {
  let repo: UserRepository;
  let service: UserService;

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase();
    repo = new UserRepository({ db });
    service = new UserService({ repo });
  });

  describe('getById', (): void => {
    it('returns the stored user when the user exists', async (): Promise<void> => {
      const stored: User = await repo.create({ input: buildCreateUserDto() });

      const result: User | null = await service.getById({ userId: stored.id });

      expect(result).toMatchObject({ id: stored.id, email: stored.email });
    });

    it('returns null when the user does not exist', async (): Promise<void> => {
      const result: User | null = await service.getById({ userId: 'non-existent-id' });

      expect(result).toBeNull();
    });
  });

  describe('create', (): void => {
    it('persists the new user when input is valid', async (): Promise<void> => {
      const dto: CreateUserDto = buildCreateUserDto();

      const created: User = await service.create({ input: dto });

      expect(await repo.findById({ id: created.id })).toMatchObject({ email: dto.email, fullName: dto.fullName });
    });
  });
});
```

### Step 6 — Writing an HTTP Route Test with Supertest

- Drive the real app: real middleware, real services, test database. See `typescript-test-controllers` for auth helpers and the full recipe.

```typescript
// tests/routers/user.router.test.ts
import { beforeEach, describe, expect, it } from 'vitest';
import request, { type Response } from 'supertest';
import type { Express } from 'express';
import { createApp } from '@/app';
import { db } from '@/connectors/db';
import { UserRepository } from '@/domains/user/repository';
import { buildCreateUserDto } from '../helpers/factories';
import { createTestSession, type TestSession } from '../helpers/auth';
import { resetTestDatabase } from '../helpers/db';

const app: Express = createApp();

describe('POST /users', (): void => {
  let session: TestSession;

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase();
    session = await createTestSession();
  });

  it('returns 201 and persists the user when the email is new', async (): Promise<void> => {
    const dto: CreateUserDto = buildCreateUserDto();

    const response: Response = await request(app)
      .post('/users')
      .set('Authorization', session.authorizationHeader)
      .send(dto);

    expect(response.status).toBe(201);
    expect(response.body).toMatchObject({ data: { email: dto.email } });
    expect(await new UserRepository({ db }).findByEmail({ email: dto.email })).not.toBeNull();
  });

  it('returns 409 and keeps one row when the email is already taken', async (): Promise<void> => {
    const dto: CreateUserDto = buildCreateUserDto();
    await new UserRepository({ db }).create({ input: dto });

    const response: Response = await request(app)
      .post('/users')
      .set('Authorization', session.authorizationHeader)
      .send({ ...dto, fullName: 'Someone Else' });

    expect(response.status).toBe(409);
    expect(await db.user.count({ where: { email: dto.email } })).toBe(1);
  });
});
```

### Step 7 — Mocking External HTTP with msw

- Use `msw` only for third-party APIs (payment, email, SMS, LLM vendors). Never for internal services.

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

1. **Never import from `src/config/cfg.ts` in tests** — set test values through the test environment (`DATABASE_URL`, API keys) instead.
2. **Use the real test database** — never `vi.mock('@/connectors/db')`, repositories or internal services.
3. **Reset state with `resetTestDatabase()` in `beforeEach`** — each test starts from empty tables.
4. **Factory functions use named overrides** — `buildUser({ email: 'x@y.com' })`, never positional.
5. **Supertest drives the real app** — real router, middleware and services; authenticate with a real test session.
6. **msw intercepts at the network level** — use it for third-party services, not internal modules.
7. **Inject other collaborators** — clocks, ID generators and third-party clients are passed in through options objects as stubs or fakes; nothing is patched.
