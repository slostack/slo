---
name: typescript-test-verification-policy
description: TypeScript evidence for meaningful decisions, changed boundaries and required failure paths.
when_to_use: Use to verify TypeScript acceptance evidence with the project test runner.
group: languages
kind: skill
---

# TypeScript Test Verification Policy

## Skill summary

- **Name:** `typescript-test-verification-policy`
- **Description:** TypeScript evidence for meaningful decisions, changed boundaries and required failure paths.
- **When to use:** Verify TypeScript acceptance evidence with the project test runner.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write tests for the user service"
- "Add unit tests for this function"
- "Make sure every branch is covered before we move on"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

### Core rule

Every changed behavior needs appropriate passing evidence before completion. Follow `skills/coding/test-verification-policy/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md`; existing tests may supply adequate evidence when rerun. Critical safety paths and explicit specification matrices remain mandatory.

### What must be tested

Use this table as a gap-discovery checklist for meaningful decisions, not a test-count formula. One behavioral test may traverse several branches; parameterized cases can cover equivalent outcomes. Do not duplicate proof at every test level. Pure delegation still needs evidence that its real caller is wired correctly.

| Code Pattern | What to test |
|---|---|
| `if / else` | One test for the truthy branch, one for the falsy branch |
| `if / else if / else` | One test per branch |
| `switch / case` | One test per case arm, including the `default` fallback |
| Early returns / guard clauses | One test that triggers the early return, one that proceeds past it |
| `try / catch` | One test for the success path, one that triggers the caught error |
| Ternary expressions (`a ? b : c`) | One test per outcome |
| Optional chaining (`a?.b`) | One test where `a` is defined, one where it is `undefined` |
| Nullish coalescing (`a ?? b`) | One test where `a` is non-null, one where it is null/undefined |
| Loop with conditional `break` / `continue` | Tests that exercise both the break/continue path and the full iteration path |
| Dynamic dispatch (factory, strategy, registry) | One test per concrete dispatch target |

### Test naming convention

Test names describe the specific code path being exercised, not just the method being called.

```typescript
// Bad — says nothing about the path
it('getUser works', async () => { ... })

// Good — describes the outcome and the condition
it('returns null when user does not exist', async () => { ... })
it('throws ForbiddenError when user is not an admin', async () => { ... })
it('returns the user when found by id', async () => { ... })
```

The pattern is: `it('<expected outcome> when <condition>', ...)`

### Test file co-location

```
src/services/user.service.ts       → src/services/user.service.test.ts
src/controllers/auth.controller.ts → src/controllers/auth.controller.test.ts
```

Or in a parallel `tests/` tree mirroring `src/`:

```
src/services/user.service.ts  → tests/services/user.service.test.ts
```

Pick one and stay consistent. Never mix both.

### Complete example: testing a service with a guard clause

Given this service method:

```typescript
// src/services/document.service.ts
export class DocumentService {
  constructor(private readonly repo: DocumentRepository) {}

  async create(input: CreateDocumentInput): Promise<DocumentDAO> {
    if (!input.body) {
      throw new ValidationError('Document body is required')
    }

    const embeddings = input.skipEmbeddings
      ? null
      : await this.repo.generateEmbeddings(input.body)

    return this.repo.create({ ...input, embeddings })
  }
}
```

The required tests are:

```typescript
// src/services/document.service.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { DocumentService } from './document.service'
import { ValidationError } from '../errors'
import type { DocumentRepository } from '../repositories/document.repository'

const makeRepo = (): DocumentRepository => ({
  create: vi.fn(),
  generateEmbeddings: vi.fn(),
})

describe('DocumentService.create', () => {
  let repo: DocumentRepository
  let service: DocumentService

  beforeEach(() => {
    repo = makeRepo()
    service = new DocumentService(repo)
  })

  // Guard clause — early throw path
  it('throws ValidationError when body is missing', async () => {
    await expect(
      service.create({ title: 'Test', body: '', skipEmbeddings: false })
    ).rejects.toThrow(ValidationError)

    expect(repo.generateEmbeddings).not.toHaveBeenCalled()
    expect(repo.create).not.toHaveBeenCalled()
  })

  // Conditional branch — skipEmbeddings: false
  it('generates embeddings and persists the document when skipEmbeddings is false', async () => {
    const fakeEmbeddings = [0.1, 0.2, 0.3]
    vi.mocked(repo.generateEmbeddings).mockResolvedValue(fakeEmbeddings)
    vi.mocked(repo.create).mockResolvedValue({ id: '1', title: 'Test', body: 'content', embeddings: fakeEmbeddings })

    const result = await service.create({ title: 'Test', body: 'content', skipEmbeddings: false })

    expect(repo.generateEmbeddings).toHaveBeenCalledWith('content')
    expect(repo.create).toHaveBeenCalledWith(expect.objectContaining({ embeddings: fakeEmbeddings }))
    expect(result.embeddings).toEqual(fakeEmbeddings)
  })

  // Conditional branch — skipEmbeddings: true
  it('persists the document without embeddings when skipEmbeddings is true', async () => {
    vi.mocked(repo.create).mockResolvedValue({ id: '1', title: 'Test', body: 'content', embeddings: null })

    await service.create({ title: 'Test', body: 'content', skipEmbeddings: true })

    expect(repo.generateEmbeddings).not.toHaveBeenCalled()
    expect(repo.create).toHaveBeenCalledWith(expect.objectContaining({ embeddings: null }))
  })
})
```

These scenarios demonstrate distinct outcomes, not a universal branch-to-test formula.

### Bad test vs. good test

```typescript
// BAD — asserts almost nothing; passes even if the method is broken
it('create runs', async () => {
  const result = await service.create({ title: 'T', body: 'B', skipEmbeddings: false })
  expect(result).not.toBeNull()
})

// GOOD — asserts the specific outcome of this exact code path
it('returns a document with embeddings when skipEmbeddings is false', async () => {
  vi.mocked(repo.generateEmbeddings).mockResolvedValue([0.1])
  vi.mocked(repo.create).mockResolvedValue({ id: '1', title: 'T', body: 'B', embeddings: [0.1] })

  const result = await service.create({ title: 'T', body: 'B', skipEmbeddings: false })

  expect(result.embeddings).toEqual([0.1])
})
```

### Mocking with `vi.mock()` and `vi.fn()`

```typescript
import { vi } from 'vitest'

// Mock an entire module
vi.mock('../repositories/document.repository', () => ({
  DocumentRepository: vi.fn().mockImplementation(() => ({
    create: vi.fn(),
    generateEmbeddings: vi.fn(),
  })),
}))

// Or create a typed mock factory inline (preferred for unit tests)
const makeRepo = (): jest.Mocked<DocumentRepository> => ({
  create: vi.fn(),
  generateEmbeddings: vi.fn(),
})
```

### Async tests

```typescript
// Always use async/await with async service methods
it('throws when the database is unreachable', async () => {
  vi.mocked(repo.create).mockRejectedValue(new Error('Connection refused'))

  await expect(
    service.create({ title: 'T', body: 'B', skipEmbeddings: false })
  ).rejects.toThrow('Connection refused')
})
```

### Rules on `.skip` and `.todo`

- Never leave `.skip` or `.todo` without a comment explaining when it will be removed.
- A `.skip` is a failed test that doesn't surface. Treat it as a bug.

### Workflow: verification checklist before marking a task complete

1. [ ] Acceptance outcomes, meaningful changed decisions and critical failure paths have evidence
2. [ ] Required project gates pass; baseline exceptions require explicit approval
3. [ ] No existing tests were broken by the change
4. [ ] Test names describe the specific code path they exercise
5. [ ] No `.skip` or `.todo` without an explanatory comment

### Running the suite

```bash
# Run only the file you changed
pnpm vitest run src/services/document.service.test.ts

# Run the full suite before finishing
pnpm vitest run

# Watch mode during development
pnpm vitest

# With coverage
pnpm vitest run --coverage
```
