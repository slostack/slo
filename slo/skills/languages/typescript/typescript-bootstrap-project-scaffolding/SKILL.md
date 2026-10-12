---
name: typescript-bootstrap-project-scaffolding
description: Step-by-step guide to bootstrapping a new TypeScript Node.js project from scratch with pnpm,
  strict tsconfig, Vitest, and the standard src/ layout.
when_to_use: Use when initialising a brand-new TypeScript backend or library project.
group: languages
kind: skill
---

# TypeScript Bootstrap Project Scaffolding

## Skill summary

- **Name:** `typescript-bootstrap-project-scaffolding`
- **Description:** Step-by-step guide to bootstrapping a new TypeScript Node.js project from scratch with pnpm, strict tsconfig, Vitest, and the standard src/ layout.
- **When to use:** Use when initialising a brand-new TypeScript backend or library project.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up a new TypeScript Node.js project from scratch"
- "Bootstrap a fresh TypeScript backend with pnpm"
- "Create the initial project scaffold for a TypeScript service"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Step 1 — Initialise the Package

```bash
mkdir my-service && cd my-service
pnpm init
```

Edit `package.json` to set `"type": "module"` and `"engines"`:
```json
{
  "name": "my-service",
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "dev":       "tsx watch src/index.ts",
    "build":     "tsc --noEmit && tsc -p tsconfig.build.json",
    "start":     "node dist/index.js",
    "test":      "vitest run",
    "test:watch":"vitest",
    "coverage":  "vitest run --coverage",
    "lint":      "eslint src tests --max-warnings 0",
    "typecheck": "tsc --noEmit"
  }
}
```

### Step 2 — Install Core Dependencies

```bash
# Runtime
pnpm add zod

# TypeScript and execution
pnpm add -D typescript tsx @types/node

# Testing
pnpm add -D vitest @vitest/coverage-v8

# Linting and formatting
pnpm add -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin prettier
```

For Express:
```bash
pnpm add express
pnpm add -D @types/express supertest @types/supertest
```

### Step 3 — tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "exactOptionalPropertyTypes": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

Also create `tsconfig.build.json` for production builds (excludes tests):
```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "outDir": "dist",
    "noEmit": false
  },
  "include": ["src/**/*"]
}
```

### Step 4 — vitest.config.ts

```typescript
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.ts'],
      exclude: ['src/index.ts', 'src/**/*.d.ts'],
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
      '@': resolve(__dirname, 'src'),
    },
  },
});
```

### Step 5 — Env Files

**`.env.development`**:
```
NODE_ENV=development
PORT=3000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/myservice_development
REDIS_URL=redis://localhost:6379
JWT_SECRET=dev-secret-change-in-production
```

**`.env.test`**:
```
NODE_ENV=test
PORT=3001
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/myservice_test
REDIS_URL=redis://localhost:6379
JWT_SECRET=test-secret
```

**`.env.local`** (machine-specific, git-ignored):
```
DATABASE_URL=postgresql://postgres:mypassword@localhost:5432/myservice_development
```

Add to `.gitignore`:
```
.env.local
.env.production
dist/
node_modules/
coverage/
```

### Step 6 — src/config/cfg.ts

```typescript
import { config as dotenvConfig } from 'dotenv';

// Load env file based on NODE_ENV — call this before anything else
dotenvConfig({
  path: process.env.NODE_ENV === 'test' ? '.env.test' : '.env.development',
  override: false, // don't override already-set vars (shell exports win)
});

// Then load .env.local overrides if present
dotenvConfig({ path: '.env.local', override: true });

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
  isTest:      process.env.NODE_ENV === 'test',
  isDev:       process.env.NODE_ENV === 'development',
  isProd:      process.env.NODE_ENV === 'production',
});
```

### Step 7 — Create the Folder Scaffold

```bash
mkdir -p src/{config,domains,services,routers,middleware,connectors,workers,utils}
mkdir -p tests/{domains,services,routers,helpers}
touch tests/setup.ts
touch src/index.ts src/app.ts
```

**`tests/setup.ts`**:
```typescript
import { vi, afterEach } from 'vitest';

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});
```

### Step 8 — Initial src/index.ts

```typescript
import { config } from '@/config/cfg';
import { createApp } from './app';

async function main(): Promise<void> {
  const app = createApp();
  app.listen(config.port, () => {
    console.log(`[${config.env}] Server listening on port ${config.port}`);
  });
}

main().catch((err: unknown) => {
  console.error('Fatal startup error:', err);
  process.exit(1);
});
```

### Step 9 — ESLint + Prettier

**`.eslintrc.json`**:
```json
{
  "parser": "@typescript-eslint/parser",
  "parserOptions": { "project": "./tsconfig.json" },
  "plugins": ["@typescript-eslint"],
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended-type-checked"
  ],
  "rules": {
    "@typescript-eslint/no-unused-vars": ["error", { "argsIgnorePattern": "^_" }],
    "@typescript-eslint/explicit-function-return-type": "error",
    "@typescript-eslint/no-explicit-any": "error"
  }
}
```

**`.prettierrc`**:
```json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}
```

### Verification Checklist

After scaffolding, confirm:
- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm test` runs (even with 0 tests)
- [ ] `pnpm lint` exits 0
- [ ] `pnpm dev` starts the server
- [ ] Imports using `@/` resolve correctly in both `tsc` and `vitest`
