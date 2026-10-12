---
name: typescript-switch-environments-and-run-tests
description: How to switch between development and test environments in a TypeScript project and run the
  test suite against the correct database.
when_to_use: Use when running tests, switching databases, or verifying that the correct environment is
  active.
group: languages
kind: skill
---

# TypeScript Switch Environments and Run Tests

## Skill summary

- **Name:** `typescript-switch-environments-and-run-tests`
- **Description:** How to switch between development and test environments in a TypeScript project and run the test suite against the correct database.
- **When to use:** Use when running tests, switching databases, or verifying that the correct environment is active.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "How do I run tests against the test database?"
- "How do I switch to the development environment?"
- "My tests are writing to the wrong database — how do I fix it?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Environment File Convention

```
.env.development    # Primary development env — real DB on dev port, real Redis
.env.test           # Test run env — test DB, mock-friendly settings
.env.local          # Machine-specific overrides — git-ignored, loaded last
.env.production     # Production — never loaded locally, git-ignored
```

**Rule:** Never read `process.env.*` in service code. Always read through `src/config/cfg.ts`.

### .env.development

```
NODE_ENV=development
PORT=3000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/myservice_development
REDIS_URL=redis://localhost:6379
JWT_SECRET=dev-secret-not-for-production
LOG_LEVEL=debug
```

### .env.test

```
NODE_ENV=test
PORT=3001
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/myservice_test
REDIS_URL=redis://localhost:6379
JWT_SECRET=test-secret
LOG_LEVEL=silent
```

### .env.local (machine-specific, git-ignored)

```
# Override DATABASE_URL if your local Postgres runs on a non-standard port or password
DATABASE_URL=postgresql://postgres:mypassword@localhost:5434/myservice_development
```

### src/config/cfg.ts — The Single Load Point

Load env files here, before any other module touches `process.env`:

```typescript
import { config as dotenvConfig } from 'dotenv';
import { existsSync } from 'fs';

const envFile = process.env.NODE_ENV === 'test' ? '.env.test' : '.env.development';

// 1. Load environment-specific file first
dotenvConfig({ path: envFile, override: false });

// 2. Load .env.local — machine-specific overrides win
if (existsSync('.env.local')) {
  dotenvConfig({ path: '.env.local', override: true });
}

function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Missing required environment variable: ${key}`);
  return value;
}

export const config = Object.freeze({
  env:         process.env.NODE_ENV ?? 'development',
  port:        parseInt(process.env.PORT ?? '3000', 10),
  databaseUrl: requireEnv('DATABASE_URL'),
  redisUrl:    process.env.REDIS_URL ?? 'redis://localhost:6379',
  jwtSecret:   requireEnv('JWT_SECRET'),
  logLevel:    process.env.LOG_LEVEL ?? 'info',
  isTest:      process.env.NODE_ENV === 'test',
  isDev:       process.env.NODE_ENV === 'development',
  isProd:      process.env.NODE_ENV === 'production',
});
```

### vitest.config.ts — Automatic NODE_ENV=test

Vitest sets `NODE_ENV=test` automatically before running any tests. This means `cfg.ts` will load `.env.test` without any extra configuration.

```typescript
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    environment: 'node',
    setupFiles: ['./tests/setup.ts'],
    // vitest sets NODE_ENV='test' automatically
    // cfg.ts will load .env.test as a result
  },
  resolve: {
    alias: { '@': resolve(__dirname, 'src') },
  },
});
```

If you need to force a specific env file (uncommon):
```typescript
// vitest.config.ts
import { loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    test: {
      env, // injects all .env vars into process.env for tests
    },
  };
});
```

### Verifying the Active Database Before Running Tests

Add a log to `tests/setup.ts` so you can confirm at a glance:

```typescript
// tests/setup.ts
import { config } from '@/config/cfg';
import { db } from '@/connectors/db';

beforeAll(async () => {
  // Print the active DATABASE_URL so misconfiguration is immediately obvious
  console.log(`[test setup] DATABASE_URL = ${config.databaseUrl}`);

  if (!config.databaseUrl.includes('_test')) {
    throw new Error(
      `Tests must run against a *_test database. Got: ${config.databaseUrl}\n` +
      `Set NODE_ENV=test or check your .env.test file.`,
    );
  }
});
```

This guard prevents tests from accidentally writing to the development database.

### Running the Tests

```bash
# Full suite — CI mode (exits after one pass)
pnpm vitest run

# OR via package.json script
pnpm test

# Watch mode — re-runs affected tests on file save
pnpm vitest

# Single file
pnpm vitest run tests/domains/user/user.service.test.ts

# Tests matching a name pattern
pnpm vitest run -t "creates a user"

# With coverage (always use run mode for coverage)
pnpm vitest run --coverage

# Verbose output (see each test name)
pnpm vitest run --reporter=verbose
```

### Switching to Development Mode

When working outside of tests (running migrations, starting the server, running scripts):

```bash
# Explicitly set NODE_ENV if needed — cfg.ts will load .env.development
NODE_ENV=development pnpm dev

# Or just use the dev script (package.json sets NODE_ENV=development)
pnpm dev
```

Verify which database is active:
```typescript
// Quick one-liner to print the active URL
NODE_ENV=development npx tsx -e "import('@/config/cfg').then(m => console.log(m.config.databaseUrl))"
```

### Running Database Migrations

Always confirm `NODE_ENV` before migrating. Migrations against the test DB are safe (it's throwaway), but migrations against production without a review are catastrophic.

```bash
# Migrate development
NODE_ENV=development pnpm prisma migrate dev

# Migrate test DB (after running `pnpm prisma migrate dev` in development first)
NODE_ENV=test pnpm prisma migrate deploy

# Check current migration status
NODE_ENV=development pnpm prisma migrate status
```

### Full Verification Sequence (Before Committing)

```bash
# 1. Typecheck
pnpm typecheck

# 2. Lint
pnpm lint

# 3. Run tests with coverage
pnpm vitest run --coverage

# 4. Confirm all green
echo "All checks passed"
```

### Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| `NODE_ENV` not set when running tests | cfg.ts loads `.env.development` → tests hit dev DB | `pnpm test` (Vitest sets `NODE_ENV=test` automatically) |
| `.env.local` overrides `DATABASE_URL` to dev DB | Tests write to dev DB | Check `.env.local` — remove the `DATABASE_URL` override for test runs |
| `process.env.DATABASE_URL` read directly in a service | DB URL not affected by env file loading order | Move all `process.env` reads to `cfg.ts` |
| Forgot to close DB pool in `afterAll` | Process hangs after tests complete | Add `await db.$disconnect()` in `tests/setup.ts` `afterAll` |
| Running `pnpm prisma migrate dev` with `NODE_ENV=test` | Schema pushed to test DB, not development | Always check `NODE_ENV` before migrating |
| Schema out of sync on test DB | "relation does not exist" in tests | `NODE_ENV=test pnpm prisma migrate deploy` |

### Returning to Development After Running Tests

Vitest sets `NODE_ENV=test` only for the Vitest process. Your shell's `NODE_ENV` is unchanged. After tests finish, running `pnpm dev` will load `.env.development` as normal — no manual reset needed.

If you set `NODE_ENV=test` in your shell manually, unset it:
```bash
unset NODE_ENV
pnpm dev
```
