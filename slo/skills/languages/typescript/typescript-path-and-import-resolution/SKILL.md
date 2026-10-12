---
name: typescript-path-and-import-resolution
description: Configure tsconfig path aliases and module resolution so TypeScript imports use @/ instead
  of deep relative paths, with matching config for Vitest and Node execution.
when_to_use: Use when setting up path aliases, debugging import resolution errors, or migrating from relative
  to aliased imports.
group: languages
kind: skill
---

# TypeScript Path and Import Resolution

## Skill summary

- **Name:** `typescript-path-and-import-resolution`
- **Description:** Configure tsconfig path aliases and module resolution so TypeScript imports use @/ instead of deep relative paths, with matching config for Vitest and Node execution.
- **When to use:** Use when setting up path aliases, debugging import resolution errors, or migrating from relative to aliased imports.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Set up @/ path aliases in this TypeScript project"
- "My @/ imports aren't resolving in Vitest"
- "How do I avoid ../../../ relative imports in TypeScript?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### The Problem

Without aliases, imports accumulate relative path noise as the project grows:
```typescript
// Bad — 3 levels up, then back down
import { UserService } from '../../../domains/user/service';
import { config } from '../../../../config/cfg';
import { buildUser } from '../../helpers/factories';
```

With aliases:
```typescript
// Good — always from the src root
import { UserService } from '@/domains/user/service';
import { config } from '@/config/cfg';
import { buildUser } from '../helpers/factories';  // same-level relative is fine
```

### tsconfig.json — The Canonical Declaration

All path aliases are declared here. Every other tool (Vitest, ts-node, tsx) must derive its alias config from this.

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "moduleResolution": "bundler",
    "paths": {
      "@/*": ["src/*"]
    }
  }
}
```

Key settings:
- `"baseUrl": "."` — makes `paths` relative to the project root
- `"moduleResolution": "bundler"` — correct for Vite/Vitest projects; use `"node16"` or `"nodenext"` for pure Node without a bundler
- `"paths": { "@/*": ["src/*"] }` — `@/foo` resolves to `src/foo`

### vitest.config.ts — Must Match tsconfig

Vitest uses its own module resolver (esbuild-based), not `tsc`. The `paths` in `tsconfig.json` do **not** automatically apply to Vitest. You must mirror them in `resolve.alias`:

```typescript
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    environment: 'node',
  },
  resolve: {
    alias: {
      // Must match tsconfig.json paths: "@/*" → "src/*"
      '@': resolve(__dirname, 'src'),
    },
  },
});
```

If these two configs drift apart — e.g., tsconfig says `src/` but vitest says `./source/` — you will get resolution errors that only appear in tests, not in the type-checker. Keep them in sync.

### tsx and ts-node — Running Scripts Directly

For scripts run directly with `tsx` or `ts-node`, path aliases are read from `tsconfig.json` automatically by `tsx`. No extra config needed:

```bash
# Works with @/ aliases — tsx reads tsconfig.json
npx tsx src/scripts/seed.ts

# ts-node also reads tsconfig.json paths
npx ts-node --esm src/scripts/migrate.ts
```

If you use `ts-node` without `--esm` and paths are not resolving, add `tsconfig-paths` to the invocation:
```bash
npx ts-node -r tsconfig-paths/register src/scripts/seed.ts
```

### Production Builds — Resolving Aliases in dist/

`tsc` does not rewrite `@/` to relative paths in the compiled output. The `dist/` files will contain `@/` imports that Node cannot resolve at runtime.

Solutions:

**Option A (preferred): Use `tsc-alias` after `tsc`**
```bash
pnpm add -D tsc-alias
```
```json
{
  "scripts": {
    "build": "tsc -p tsconfig.build.json && tsc-alias -p tsconfig.build.json"
  }
}
```

**Option B: Use a bundler (esbuild / tsup)**
```bash
pnpm add -D tsup
```
```typescript
// tsup.config.ts
import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['esm', 'cjs'],
  dts: true,
  sourcemap: true,
  clean: true,
});
```
```json
{
  "scripts": {
    "build": "tsup"
  }
}
```
Bundlers resolve aliases at build time — no post-processing needed.

### Nuxt 3 — Auto-Configured

In Nuxt 3, `~/` and `#/` are auto-configured to point to the project root and `src/` equivalent. No manual alias setup needed:

```typescript
// In Nuxt 3 — works out of the box
import { useUserStore } from '~/stores/user';
import type { User } from '~/types/user';
```

Do not add manual `paths` to `tsconfig.json` in a Nuxt project — it already sets them.

### Good vs Bad Import Examples

```typescript
// Bad — 4-level relative path
import { EmailService } from '../../../../domains/email/service';

// Bad — 1 level but still avoidable
import { config } from '../config/cfg';

// Good — absolute from src root
import { EmailService } from '@/domains/email/service';
import { config } from '@/config/cfg';

// OK — same directory relative is acceptable
import { buildUser } from './factories';
import type { CreateUserDto } from './dto';
```

Rule of thumb: if an import goes up (`../`) more than once, use `@/` instead.

### Import Order Convention

Keep imports in this order (enforced by ESLint `import/order` or `simple-import-sort`):

```typescript
// 1. Node built-ins
import { readFileSync } from 'fs';
import { resolve } from 'path';

// 2. External packages
import express from 'express';
import { z } from 'zod';

// 3. Internal aliases (@/)
import { config } from '@/config/cfg';
import { UserService } from '@/domains/user/service';
import type { User } from '@/domains/user/entity';

// 4. Relative same-directory imports
import { buildUser } from './factories';
```

Install `eslint-plugin-simple-import-sort` to enforce this automatically:
```bash
pnpm add -D eslint-plugin-simple-import-sort
```
```json
{
  "plugins": ["simple-import-sort"],
  "rules": {
    "simple-import-sort/imports": "error",
    "simple-import-sort/exports": "error"
  }
}
```

### No Barrel Re-Exports Inside Domains

Do not create `src/domains/user/index.ts` that re-exports everything. Import the specific file:

```typescript
// Bad — barrel file hides what you're actually importing
import { UserService, UserResponseDto, User } from '@/domains/user';

// Good — explicit, traceable
import { UserService } from '@/domains/user/service';
import type { UserResponseDto } from '@/domains/user/dto';
import type { User } from '@/domains/user/entity';
```

Barrel files are acceptable at public API boundaries (e.g., an npm package's `src/index.ts`), not inside the application's own domain folders.

### Verifying Aliases Work

Run a test that imports via `@/` and confirm it passes:

```typescript
// tests/helpers/alias.test.ts
import { describe, it, expect } from 'vitest';
import { config } from '@/config/cfg';

describe('path alias', () => {
  it('@/ resolves to src/', () => {
    // If this import succeeded, the alias is working
    expect(config).toBeDefined();
    expect(typeof config.env).toBe('string');
  });
});
```

```bash
pnpm vitest run tests/helpers/alias.test.ts
```

If this test fails with `Cannot find module '@/config/cfg'`, the alias is not configured in `vitest.config.ts`. Check that `resolve.alias['@']` points to the correct absolute path.

### Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| `paths` in tsconfig but no `resolve.alias` in vitest.config.ts | Tests fail: `Cannot find module '@/...'` | Add matching `resolve.alias` to `vitest.config.ts` |
| `baseUrl` missing from tsconfig | `tsc` ignores `paths` entirely | Add `"baseUrl": "."` to `compilerOptions` |
| `moduleResolution: "node"` with ESM imports | Import extensions errors at runtime | Use `"moduleResolution": "bundler"` for Vite/Vitest or `"node16"` for pure Node ESM |
| Aliases not rewritten in `dist/` | Runtime: `Cannot find module '@/...'` | Add `tsc-alias` post-build step or switch to `tsup` |
| Barrel re-exports everywhere | Circular dependency errors, slow test startup | Remove barrels; import directly from specific files |
| `~/` used instead of `@/` outside Nuxt | Does not resolve | `~/` is Nuxt-specific; use `@/` everywhere else |
