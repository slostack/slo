---
name: typescript-build-domain-features
description: Build the three-file TypeScript domain pattern — entity.ts (DB interface) + dto.ts (Zod schema
  + inferred type + status constants) + service.ts (domain service class) — with identical field names
  across all three.
when_to_use: Use when adding a new domain model, creating a new database-backed entity, or scaffolding
  the entity/dto/service triple for a domain resource in TypeScript.
group: languages
kind: skill
---

# TypeScript Build Domain Features

## Skill summary

- **Name:** `typescript-build-domain-features`
- **Description:** Build the three-file TypeScript domain pattern — entity.ts (DB interface) + dto.ts (Zod schema + inferred type + status constants) + service.ts (domain service class) — with identical field names across all three.
- **When to use:** Use when adding a new domain model, creating a new database-backed entity, or scaffolding the entity/dto/service triple for a domain resource in TypeScript.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "add a VerificationRun domain feature with entity, dto, and service files"
- "create the three-file pattern for a Document domain with status constants"
- "scaffold the user domain with entity/dto/service following the ubiquitous language rule"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

The TypeScript domain pattern mirrors the Python `model.py + dao.py + service.py` triple. Each domain resource lives in its own directory and consists of exactly three files:

- **`entity.ts`** — TypeScript interface representing the database row. Field names are identical to column names.
- **`dto.ts`** — Zod schema for validation, the inferred TypeScript type (`z.infer<typeof Schema>`), and all status/enum constants for the domain.
- **`service.ts`** — Domain service class with static async methods named as verb phrases. Methods accept DTO types and return entity types.

The cardinal rule from the ubiquitous language convention applies: **DTO field names must be identical to entity field names, which must be identical to database column names.** No aliasing, no renaming between layers.

---

### Directory structure

```
src/
  domains/
    verification-run/
      entity.ts          # DB row interface
      dto.ts             # Zod schema, inferred type, status constants
      service.ts         # domain service class
    document/
      entity.ts
      dto.ts
      service.ts
    user/
      entity.ts
      dto.ts
      service.ts
```

---

### `entity.ts` — the database row interface

The entity interface is the vocabulary authority for field names. Every other file in the domain derives its names from here.

```typescript
// src/domains/verification-run/entity.ts

/**
 * Represents a row in the verification_runs table.
 * Field names are identical to column names — no aliasing.
 */
export interface VerificationRun {
  id: string;                       // uuid, primary key
  correlation_id: string | null;    // idempotency key
  environment_profile_id: string;   // fk → environment_profiles.id
  question_limit: number | null;    // cap on fanned-out questions
  question_difficulties: string[];  // e.g. ['easy', 'medium']
  include_baselines: boolean;
  status: string;                   // see VerificationRunStatus in dto.ts
  run_started_at: Date | null;
  run_completed_at: Date | null;
  created_at: Date;
  updated_at: Date;
}
```

---

### `dto.ts` — Zod schema, inferred type, and status constants

Status constants are defined at the top of `dto.ts` as `const` objects so they can be imported by any layer — routers, services, tests — without circular dependencies.

```typescript
// src/domains/verification-run/dto.ts
import { z } from 'zod';

// ------------------------------------------------------------------
// Status constants — import these everywhere; never use raw strings.
// ------------------------------------------------------------------
export const VerificationRunStatus = {
  QUEUED: 'QUEUED',
  RUNNING: 'RUNNING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
} as const;

export type VerificationRunStatusValue =
  (typeof VerificationRunStatus)[keyof typeof VerificationRunStatus];

// ------------------------------------------------------------------
// Difficulty constants
// ------------------------------------------------------------------
export const QuestionDifficulty = {
  EASY: 'easy',
  MEDIUM: 'medium',
  HARD: 'hard',
} as const;

export type QuestionDifficultyValue =
  (typeof QuestionDifficulty)[keyof typeof QuestionDifficulty];

export const DIFFICULTIES = Object.values(QuestionDifficulty) as [
  QuestionDifficultyValue,
  ...QuestionDifficultyValue[],
];

// ------------------------------------------------------------------
// Zod schemas — field names are IDENTICAL to entity field names.
// ------------------------------------------------------------------
export const CreateVerificationRunSchema = z.object({
  correlation_id: z.string().uuid().nullable().default(null),
  environment_profile_id: z.string().uuid(),
  question_limit: z.number().int().min(1).max(200).nullable().default(null),
  question_difficulties: z.array(z.enum(DIFFICULTIES)).default([]),
  include_baselines: z.boolean().default(false),
});

export type CreateVerificationRunDTO = z.infer<typeof CreateVerificationRunSchema>;

export const UpdateVerificationRunSchema = z.object({
  status: z.enum([
    VerificationRunStatus.QUEUED,
    VerificationRunStatus.RUNNING,
    VerificationRunStatus.COMPLETED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.CANCELLED,
  ]),
  run_started_at: z.date().nullable().optional(),
  run_completed_at: z.date().nullable().optional(),
});

export type UpdateVerificationRunDTO = z.infer<typeof UpdateVerificationRunSchema>;

// Full read DTO — matches the entity interface exactly.
export const VerificationRunSchema = CreateVerificationRunSchema.extend({
  id: z.string().uuid(),
  status: z.string(),
  run_started_at: z.date().nullable(),
  run_completed_at: z.date().nullable(),
  created_at: z.date(),
  updated_at: z.date(),
});

export type VerificationRunDTO = z.infer<typeof VerificationRunSchema>;
```

---

### `service.ts` — domain service class

Domain service methods are `static` and `async`. Method names are verb phrases that map to the operation: `create`, `getById`, `updateStatus`, `list`, `delete`. No business logic beyond data persistence and retrieval — orchestration belongs in application services.

```typescript
// src/domains/verification-run/service.ts
import type { Kysely, Transaction } from 'kysely';
import type { Database } from '../../lib/database.js';
import type { VerificationRun } from './entity.js';
import type {
  CreateVerificationRunDTO,
  UpdateVerificationRunDTO,
} from './dto.js';
import { VerificationRunStatus } from './dto.js';
import { NotFoundError } from '../../lib/errors.js';

export class VerificationRunService {
  /**
   * Insert a new verification run row.
   *
   * @param dto - Validated create payload.
   * @param db - Kysely database instance or transaction.
   * @returns The created VerificationRun entity.
   */
  static async create(
    dto: CreateVerificationRunDTO,
    db: Kysely<Database> | Transaction<Database>,
  ): Promise<VerificationRun> {
    const [run] = await db
      .insertInto('verification_runs')
      .values({
        ...dto,
        status: VerificationRunStatus.QUEUED,
        created_at: new Date(),
        updated_at: new Date(),
      })
      .returningAll()
      .execute();

    return run;
  }

  /**
   * Fetch a verification run by primary key.
   *
   * @param id - The run UUID.
   * @param db - Kysely database instance.
   * @returns The VerificationRun entity or null if not found.
   */
  static async getById(
    id: string,
    db: Kysely<Database>,
  ): Promise<VerificationRun | null> {
    const run = await db
      .selectFrom('verification_runs')
      .selectAll()
      .where('id', '=', id)
      .executeTakeFirst();

    return run ?? null;
  }

  /**
   * Fetch a run by ID, throwing NotFoundError if absent.
   *
   * @param id - The run UUID.
   * @param db - Kysely database instance.
   * @returns The VerificationRun entity.
   * @throws NotFoundError if no run exists with the given ID.
   */
  static async getByIdOrThrow(
    id: string,
    db: Kysely<Database>,
  ): Promise<VerificationRun> {
    const run = await VerificationRunService.getById(id, db);
    if (!run) throw new NotFoundError('VerificationRun');
    return run;
  }

  /**
   * Apply status and timestamp updates to an existing run.
   *
   * @param id - The run UUID.
   * @param dto - Validated update payload.
   * @param db - Kysely database instance or transaction.
   * @returns The updated VerificationRun entity.
   * @throws NotFoundError if no run exists with the given ID.
   */
  static async update(
    id: string,
    dto: UpdateVerificationRunDTO,
    db: Kysely<Database> | Transaction<Database>,
  ): Promise<VerificationRun> {
    const [run] = await db
      .updateTable('verification_runs')
      .set({ ...dto, updated_at: new Date() })
      .where('id', '=', id)
      .returningAll()
      .execute();

    if (!run) throw new NotFoundError('VerificationRun');
    return run;
  }

  /**
   * List runs for a given environment profile.
   *
   * @param environmentProfileId - Filter by environment profile UUID.
   * @param db - Kysely database instance.
   * @returns Array of VerificationRun entities, most recent first.
   */
  static async listByEnvironmentProfile(
    environmentProfileId: string,
    db: Kysely<Database>,
  ): Promise<VerificationRun[]> {
    return db
      .selectFrom('verification_runs')
      .selectAll()
      .where('environment_profile_id', '=', environmentProfileId)
      .orderBy('created_at', 'desc')
      .execute();
  }

  /**
   * Hard-delete a verification run by ID.
   *
   * @param id - The run UUID.
   * @param db - Kysely database instance.
   */
  static async delete(
    id: string,
    db: Kysely<Database>,
  ): Promise<void> {
    await db
      .deleteFrom('verification_runs')
      .where('id', '=', id)
      .execute();
  }
}
```

---

### Type compatibility check: DTO ↔ Entity

TypeScript's structural typing lets you verify DTO fields match the entity without a runtime `model_dump()`. Use `satisfies` for spot checks in tests:

```typescript
// tests/domains/verification-run/service.test.ts
import type { VerificationRun } from '../../../src/domains/verification-run/entity.js';
import type { CreateVerificationRunDTO } from '../../../src/domains/verification-run/dto.js';

// Compile-time check: CreateVerificationRunDTO fields are a subset of VerificationRun fields.
// If you rename a field in CreateVerificationRunDTO without updating the entity (or vice versa),
// this assignment will produce a type error.
const _typeCheck: Omit<VerificationRun, 'id' | 'status' | 'run_started_at' | 'run_completed_at' | 'created_at' | 'updated_at'> = {
  correlation_id: null,
  environment_profile_id: 'env-123',
  question_limit: null,
  question_difficulties: [],
  include_baselines: false,
} satisfies CreateVerificationRunDTO;

void _typeCheck; // suppress unused-variable warning
```

---

### Naming invariant: entity = DTO = column

The following is a violation because the DTO field renames the entity column:

```typescript
// BAD — DTO field name differs from entity/column name
export const CreateRunSchema = z.object({
  max_questions: z.number().nullable(),   // entity has question_limit
  grade_filter: z.array(z.string()),       // entity has question_difficulties
  env_id: z.string().uuid(),              // entity has environment_profile_id
});
```

The correct form uses the identical field names across all three files:

```typescript
// GOOD — DTO field names are identical to entity field names
export const CreateRunSchema = z.object({
  question_limit: z.number().nullable(),
  question_difficulties: z.array(z.string()),
  environment_profile_id: z.string().uuid(),
});
```

---

### Domain feature checklist

Before finishing a domain feature triple, verify:

- [ ] `entity.ts` defines an interface (not a class) whose fields match the database column names exactly
- [ ] `dto.ts` defines Zod schemas whose field names are identical to the entity interface fields
- [ ] Status and enum constants are `as const` objects in `dto.ts` — no raw string literals elsewhere
- [ ] `service.ts` methods are `static async` with full parameter and return type annotations
- [ ] Method names are verb phrases matching what they do (`create`, `getById`, `updateStatus`, `list`)
- [ ] No business logic in service.ts — only persistence operations (insert, select, update, delete)
- [ ] `getByIdOrThrow` pattern is used when callers always expect the entity to exist
- [ ] Compile-time `satisfies` check in tests confirms DTO ↔ entity field alignment
- [ ] No `any` in entity, DTO, or service types
