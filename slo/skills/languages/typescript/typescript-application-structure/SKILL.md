---
name: typescript-application-structure
description: Standard project layout and structural conventions for a TypeScript Node.js/Express/Nuxt
  backend application.
when_to_use: Use when starting a new TypeScript backend service, reviewing folder structure, or deciding
  where a new file should live.
group: languages
kind: skill
---

# TypeScript Application Structure

## Skill summary

- **Name:** `typescript-application-structure`
- **Description:** Standard project layout and structural conventions for a TypeScript Node.js/Express/Nuxt backend application.
- **When to use:** Use when starting a new TypeScript backend service, reviewing folder structure, or deciding where a new file should live.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Where should I put my new user service?"
- "What's the standard folder layout for a TypeScript backend?"
- "How should I structure a new domain in this project?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Standard Directory Tree

```
src/
  config/
    cfg.ts              # single typed config object — all env vars loaded here
  domains/
    user/
      entity.ts         # TypeScript interface/class mirroring the DB row
      dto.ts            # Zod schemas + inferred types for I/O shapes
      service.ts        # domain service — thin DB operations (get, create, update, delete)
    document/
      entity.ts
      dto.ts
      service.ts
  services/
    user-onboard/
      UserOnboardAppService.ts   # orchestrator — one workflow, one class, invoke() entry point
    document-ingest/
      DocumentIngestAppService.ts
  routers/
    user.router.ts      # all /users routes
    document.router.ts
    index.ts            # assembles and exports all routers
  middleware/
    auth.middleware.ts
    error.middleware.ts
    request-ctx.middleware.ts
  connectors/
    db.ts               # singleton Postgres pool / Prisma client
    redis.ts            # singleton Redis client
    s3.ts               # singleton S3 client
  workers/
    document-processor.worker.ts  # BullMQ / pg-boss job handlers
  utils/
    date.ts
    slug.ts
    pagination.ts
  index.ts              # entrypoint — creates app, registers middleware + routers, starts server
tests/
  domains/
    user/
      user.service.test.ts
  services/
    user-onboard/
      UserOnboardAppService.test.ts
  routers/
    user.router.test.ts
  helpers/
    factories.ts        # test data factory functions
    setup.ts            # global beforeEach / afterEach
vitest.config.ts
tsconfig.json
.env.development
.env.test
package.json
```

### Three-File Domain Pattern

Each domain entity lives under `src/domains/<name>/` with exactly three files.

**`src/domains/user/entity.ts`** — the raw DB shape:
```typescript
export interface User {
  id: string;
  email: string;
  fullName: string;
  createdAt: Date;
  updatedAt: Date;
}
```

**`src/domains/user/dto.ts`** — Zod schemas for all I/O shapes. The DTO is the contract between layers:
```typescript
import { z } from 'zod';

export const CreateUserDto = z.object({
  email: z.string().email(),
  fullName: z.string().min(1),
});
export type CreateUserDto = z.infer<typeof CreateUserDto>;

export const UpdateUserDto = CreateUserDto.partial();
export type UpdateUserDto = z.infer<typeof UpdateUserDto>;

export const UserResponseDto = z.object({
  id: z.string().uuid(),
  email: z.string(),
  fullName: z.string(),
  createdAt: z.coerce.date(),
  updatedAt: z.coerce.date(),
});
export type UserResponseDto = z.infer<typeof UserResponseDto>;
```

**`src/domains/user/service.ts`** — thin DB operations, no orchestration logic:
```typescript
import { db } from '@/connectors/db';
import type { CreateUserDto, UpdateUserDto } from './dto';
import type { User } from './entity';

export class UserService {
  static async getById(id: string): Promise<User | null> {
    return db.user.findUnique({ where: { id } });
  }

  static async getByEmail(email: string): Promise<User | null> {
    return db.user.findUnique({ where: { email } });
  }

  static async create(dto: CreateUserDto): Promise<User> {
    return db.user.create({ data: dto });
  }

  static async update(id: string, dto: UpdateUserDto): Promise<User> {
    return db.user.update({ where: { id }, data: dto });
  }

  static async delete(id: string): Promise<void> {
    await db.user.delete({ where: { id } });
  }
}
```

### Application Service Pattern

Application services live in `src/services/<feature>/`. One class per workflow. The `invoke()` method is the single public entry point. Private methods handle each step.

```typescript
// src/services/user-onboard/UserOnboardAppService.ts
import { UserService } from '@/domains/user/service';
import { EmailService } from '@/domains/email/service';
import type { CreateUserDto, UserResponseDto } from '@/domains/user/dto';
import { ConflictError } from '@/utils/errors';

export class UserOnboardAppService {
  private readonly dto: CreateUserDto;

  constructor({ dto }: { dto: CreateUserDto }) {
    this.dto = dto;
  }

  async invoke(): Promise<UserResponseDto> {
    await this.assertEmailIsUnique();
    const user = await this.createUser();
    await this.sendWelcomeEmail(user);
    return user;
  }

  private async assertEmailIsUnique(): Promise<void> {
    const existing = await UserService.getByEmail(this.dto.email);
    if (existing) {
      throw new ConflictError(`Email ${this.dto.email} is already in use`);
    }
  }

  private async createUser() {
    return UserService.create(this.dto);
  }

  private async sendWelcomeEmail(user: Awaited<ReturnType<typeof UserService.create>>) {
    await EmailService.sendWelcome({ to: user.email, name: user.fullName });
  }
}
```

### Config Pattern

**`src/config/cfg.ts`** — the only place `process.env` is read. Returns a frozen typed object:
```typescript
function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Missing required env var: ${key}`);
  return value;
}

export const config = Object.freeze({
  env: process.env.NODE_ENV ?? 'development',
  port: parseInt(process.env.PORT ?? '3000', 10),
  databaseUrl: requireEnv('DATABASE_URL'),
  redisUrl: process.env.REDIS_URL ?? 'redis://localhost:6379',
  jwtSecret: requireEnv('JWT_SECRET'),
  isTest: process.env.NODE_ENV === 'test',
  isDev: process.env.NODE_ENV === 'development',
});

export type Config = typeof config;
```

Never use `process.env.DATABASE_URL` in a service file. Always import from `@/config/cfg`.

### Connector Pattern

**`src/connectors/db.ts`** — exported singleton:
```typescript
import { PrismaClient } from '@prisma/client';
import { config } from '@/config/cfg';

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient };

export const db =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: config.isDev ? ['query', 'error'] : ['error'],
  });

if (!config.isTest) globalForPrisma.prisma = db;
```

### Entrypoint

**`src/index.ts`** — declarative initialization:
```typescript
import { createApp } from './app';
import { config } from '@/config/cfg';

async function main() {
  const app = createApp();
  app.listen(config.port, () => {
    console.log(`Server running on port ${config.port}`);
  });
}

main().catch(console.error);
```

```typescript
// src/app.ts
import express from 'express';
import { registerRouters } from '@/routers';
import { registerMiddleware } from '@/middleware';
import { registerErrorHandlers } from '@/middleware/error.middleware';

export function createApp() {
  const app = express();
  registerMiddleware(app);
  registerRouters(app);
  registerErrorHandlers(app);
  return app;
}
```

### Key Rules

1. **Three files per domain** — `entity.ts`, `dto.ts`, `service.ts`. Never merge them.
2. **Domain services are thin** — only DB operations. No business logic, no cross-domain calls.
3. **Business logic lives in application services** — in `src/services/<feature>/`.
4. **One config object** — `src/config/cfg.ts` is the only place `process.env` is read.
5. **Connectors are singletons** — exported from `src/connectors/`, shared across the process.
6. **Tests mirror `src/`** — `tests/domains/user/` mirrors `src/domains/user/`.
7. **No barrel re-exports inside domains** — import the specific file, not `@/domains/user`.
