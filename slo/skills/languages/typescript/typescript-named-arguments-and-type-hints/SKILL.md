---
name: typescript-named-arguments-and-type-hints
description: Enforce options-object pattern for multi-parameter functions and require explicit TypeScript
  types on every signature.
when_to_use: Use when writing or reviewing any TypeScript function, method, or class that has 2+ parameters,
  boolean arguments, or missing return type annotations.
group: languages
kind: skill
---

# TypeScript Named Arguments and Type Hints

## Skill summary

- **Name:** `typescript-named-arguments-and-type-hints`
- **Description:** Enforce options-object pattern for multi-parameter functions and require explicit TypeScript types on every signature.
- **When to use:** Use when writing or reviewing any TypeScript function, method, or class that has 2+ parameters, boolean arguments, or missing return type annotations.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write a search function with query, limit, and offset parameters"
- "Review this service method for named argument compliance"
- "I need to add a boolean flag to this function — how do I do it cleanly?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

In TypeScript, "named arguments" do not exist as a language feature the way they do in Python. The idiomatic equivalent is the **options object pattern**: group all parameters into a single typed object and destructure at the call site. This makes every argument self-documenting, eliminates order-dependency bugs, and makes the function signature trivially extensible without breaking callers.

---

### Rule 1: Functions with 2+ parameters MUST use an options object

Define a named `interface` or `type alias` for the options. Never inline the object shape inside the function signature — that hides the type name and makes it ungreppable.

```typescript
// Bad: positional parameters — order matters, meaning is invisible at call sites
async function searchDocuments(
  query: string,
  limit: number,
  maxDistance: number,
  includeArchived: boolean,
): Promise<SearchResult[]> { ... }

// Call site: what does `true` mean? What is `0.5`?
await searchDocuments("AI imaging", 10, 0.5, true);


// Good: options object — self-documenting at the call site
interface SearchDocumentsOptions {
  readonly query: string;
  readonly limit: number;
  readonly maxDistance: number;
  readonly includeArchived: boolean;
}

async function searchDocuments({
  query,
  limit,
  maxDistance,
  includeArchived,
}: SearchDocumentsOptions): Promise<SearchResult[]> { ... }

// Call site: every argument is labelled; order doesn't matter
await searchDocuments({
  query: "AI imaging",
  limit: 10,
  maxDistance: 0.5,
  includeArchived: true,
});
```

---

### Rule 2: Boolean parameters are ALWAYS in the options object — never positional

A positional boolean at a call site is unreadable and frequently swapped by mistake. Even if it is the only parameter, put it in an options object.

```typescript
// Bad: what does `true` mean?
await sendEmail(user, true);

// Good: unambiguous
await sendEmail({ user, sendCopy: true });
```

---

### Rule 3: Every parameter has an explicit TypeScript type

Never rely on inference for parameter types. Optional parameters use `?: T` (TypeScript shorthand for `T | undefined`) and must declare a `default` in the destructuring or handle `undefined` explicitly.

```typescript
// Bad: parameter types missing or too broad
function buildArticle(pmid, title = "Untitled", authors) { ... }

// Good: every parameter typed; optional has explicit fallback
interface BuildArticleOptions {
  readonly pmid: string;
  readonly title?: string;
  readonly authors: readonly string[];
}

function buildArticle({
  pmid,
  title = "Untitled",
  authors,
}: BuildArticleOptions): ArticleDAO { ... }
```

---

### Rule 4: Return types are ALWAYS declared explicitly — never inferred from implementation

TypeScript can infer return types, but that inference is fragile: a future code change can silently widen or change the inferred type, breaking callers without a type error at the declaration site. Explicit return types act as a contract.

```typescript
// Bad: return type inferred — what does this actually return?
async function fetchUser(options: FetchUserOptions) {
  const row = await db.query(...);
  return row ?? null;
}

// Good: explicit return type is a contract checked on every code path
async function fetchUser({ userId }: FetchUserOptions): Promise<User | null> {
  const row = await db.query(...);
  return row ?? null;
}
```

Return types must be **honest**: every code path must return the declared type. An `async` function that sometimes returns `string` and sometimes throws an untyped object is a violation.

```typescript
// Bad: return type lies — error path returns a string, not User[]
async function searchUsers(options: SearchOptions): Promise<User[]> {
  try {
    return await db.findUsers(options);
  } catch (err) {
    return `Error: ${err}`; // string !== User[]
  }
}

// Good: every path returns User[]
async function searchUsers(options: SearchOptions): Promise<User[]> {
  try {
    return await db.findUsers(options);
  } catch (err) {
    logger.error({ err }, "searchUsers failed");
    return [];
  }
}
```

---

### Rule 5: `unknown` over `any` for external / untrusted data

`any` disables all type checking. Use `unknown` when the type is truly unknown at compile time; validate and narrow before use.

```typescript
// Bad: any disables all safety
async function parseWebhook(payload: any): Promise<WebhookEvent> { ... }

// Good: unknown forces the caller to narrow the type
async function parseWebhook(payload: unknown): Promise<WebhookEvent> {
  const result = WebhookEventSchema.safeParse(payload); // Zod, valibot, etc.
  if (!result.success) throw new InvalidPayloadError(result.error);
  return result.data;
}
```

If you must use `any`, add an inline comment explaining why:

```typescript
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const legacyAdapter = thirdPartyLib.create() as any; // TODO: vendor types not yet published
```

---

### Rule 6: Use `readonly` on options objects and value objects

Options objects should not be mutated by the function they are passed to. Mark properties `readonly` in the interface declaration.

```typescript
interface CreateUserOptions {
  readonly email: string;
  readonly name: string;
  readonly role?: UserRole;
}
```

---

### Rule 7: Container types are specific

Never use bare `Array`, `object`, or `Map` without type parameters.

```typescript
// Bad: too vague
function processItems(items: Array, meta: object): Map { ... }

// Good: specific and checkable
function processItems({
  items,
  meta,
}: {
  readonly items: readonly ArticleDAO[];
  readonly meta: Record<string, unknown>;
}): Map<string, ArticleDAO> { ... }
```

---

### Summary checklist

Before submitting any TypeScript code, verify:

- [ ] Every function with 2+ parameters uses a named options object interface
- [ ] Every boolean argument is inside an options object, never positional
- [ ] Every parameter has an explicit type annotation
- [ ] Optional parameters use `?: T` or `T | undefined`, not bare `= undefined`
- [ ] Every function and method declares an explicit return type
- [ ] `unknown` is used instead of `any` for untrusted data; `any` is commented
- [ ] Options object interfaces are `readonly`
- [ ] Container types are specific (`string[]`, `Map<string, User>`, `Record<string, unknown>`)
- [ ] Return types are honest — every code path returns the declared type
