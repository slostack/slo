---
name: typescript-method-docstrings
description: Write JSDoc comments for every exported TypeScript function, class, method, and interface
  following a consistent style with @param, @returns, and @throws tags.
when_to_use: Use when writing or reviewing any exported TypeScript symbol — function, class, method, interface,
  or type alias — that lacks a JSDoc comment or has a comment that only restates the signature.
group: languages
kind: skill
---

# TypeScript Method Docstrings (JSDoc Style)

## Skill summary

- **Name:** `typescript-method-docstrings`
- **Description:** Write JSDoc comments for every exported TypeScript function, class, method, and interface following a consistent style with @param, @returns, and @throws tags.
- **When to use:** Use when writing or reviewing any exported TypeScript symbol — function, class, method, interface, or type alias — that lacks a JSDoc comment or has a comment that only restates the signature.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add JSDoc to this service class"
- "Write a docstring for an async method that can throw NotFoundError"
- "When should I skip writing a JSDoc comment?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

TypeScript's type system documents the *shape* of your code but not its *intent*. JSDoc fills that gap: it describes what a function *means*, when it can *fail*, and what the caller is expected to do. Good JSDoc reads like a contract, not a transcription of the signature.

---

### Format

Every JSDoc block follows this structure:

```typescript
/**
 * One-line imperative summary ending with a period.
 *
 * Optional: one or two sentences of additional context when the summary
 * alone does not capture why the function exists or what makes it non-obvious.
 *
 * @param {Type} paramName - Description of what this parameter controls.
 * @param {Type} [optionalParam] - Description. Defaults to `value`.
 * @returns {Type} Description of what the return value represents, not just its type.
 * @throws {ErrorClassName} Condition under which this error is thrown.
 */
```

Rules:
- The first line is a short **imperative** summary ending with a period — no blank line before it.
- A blank line separates the summary from the tag block.
- `@param`, `@returns`, and `@throws` are present only when applicable — omit sections that do not apply.
- Optional parameters use `[bracketNotation]` around the name.
- `@returns` describes the **meaning** of the value, not just the type name.
- `@throws` lists every error the caller must handle.

---

### Example: async service method with parameters and return value

```typescript
// Bad: restates the signature, adds no information
/**
 * Fetches a user by ID.
 * @param userId - The user ID.
 * @returns A user.
 */
async fetchUser({ userId }: FetchUserOptions): Promise<User | null> { ... }


// Good: describes what it means, including the null case
/**
 * Fetch a user record by primary key.
 *
 * Returns `null` if no user exists for the given ID rather than throwing —
 * the caller decides whether a missing user is an error in context.
 *
 * @param {string} userId - The UUID primary key of the user to fetch.
 * @returns {Promise<User | null>} The user record, or `null` if not found.
 */
async fetchUser({ userId }: FetchUserOptions): Promise<User | null> { ... }
```

---

### Example: constructor with dependency injection

```typescript
/**
 * Orchestrates the end-to-end payment flow for a first-party vendor account.
 *
 * @param {PaymentContext} context - Resolved account, vendor, and session identifiers.
 * @param {PaymentGateway} gateway - Vendor integration layer used to dispatch payment items.
 * @param {Logger} logger - Structured logger for tracing payment events.
 */
constructor(
  private readonly context: PaymentContext,
  private readonly gateway: PaymentGateway,
  private readonly logger: Logger,
) {}
```

---

### Example: method that throws

```typescript
/**
 * Load the active session token for the most recent succeeded verification.
 *
 * @param {string} accountId - The Collin account UUID.
 * @returns {Promise<string>} The raw session token string from `verification_response`.
 * @throws {BadRequestError} If no succeeded session exists for this account —
 *   the caller must re-initiate verification before retrying.
 * @throws {DatabaseError} If the database query fails unexpectedly.
 */
async getSessionToken({ accountId }: GetSessionTokenOptions): Promise<string> { ... }
```

---

### Example: class-level JSDoc

Class-level JSDoc describes what the class **represents**, not how to instantiate it. One or two sentences.

```typescript
// Bad: describes the constructor call, not the concept
/**
 * Creates a new HTTP client for the Affirm API. Pass the base URL and
 * credentials to the constructor, then call the individual methods.
 */
class AffirmApiClient { ... }

// Good: describes what the class is
/**
 * HTTP client for Affirm's authentication and PIN verification endpoints.
 */
class AffirmApiClient { ... }

/**
 * Application service that processes mid-call payments for a first-party vendor account.
 */
class MakePaymentService { ... }
```

---

### Example: interface JSDoc

Interfaces benefit from a short description of what the shape represents, especially when the name alone is ambiguous.

```typescript
/**
 * Options for initiating a phone PIN challenge via the vendor verification API.
 */
interface PhonePinChallengeOptions {
  /** Customer phone number in E.164 format (e.g. "+14155552671"). */
  readonly phoneNumber: string;

  /** UUID of the active conversation; used as the vendor-side conversation ID. */
  readonly conversationId: string;

  /** Number of PIN requests already made in this session. Defaults to `0`. */
  readonly pinRequestCount?: number;
}
```

Inline property-level comments use `/** ... */` on the line above the property, not `//`.

---

### Example: route handler / controller method

```typescript
/**
 * Trigger a new verification run for the given environment profile.
 *
 * Validates the request body, instantiates the trigger service, and returns
 * the created run ID. The run executes asynchronously — poll `/runs/:id` for status.
 *
 * @param {Request} req - Express request; body must conform to `TriggerRunRequestBody`.
 * @param {Response} res - Express response.
 * @returns {Promise<void>} Resolves after the response is sent.
 * @throws {ValidationError} If the request body fails schema validation.
 * @throws {NotFoundError} If the specified environment profile does not exist.
 */
async triggerVerificationRun(req: Request, res: Response): Promise<void> { ... }
```

---

### When NOT to write a JSDoc

Skip the JSDoc only when **all** of the following are true:
1. The symbol is private (prefixed `_` or uses `#`).
2. The name plus type annotations make the intent completely unambiguous.
3. There are no non-obvious defaults, side effects, or failure conditions.

```typescript
// Acceptable — name + types are fully self-explanatory; no failure conditions
private _isActive(user: User): boolean {
  return user.isActive;
}

// Acceptable — one-liner property
get fullName(): string {
  return `${this.firstName} ${this.lastName}`;
}

// NOT acceptable — even though private, the "most recent succeeded" qualifier
// is domain-specific and needs documentation
private async _loadLatestSucceededSession(accountId: string): Promise<VerifiedSession> { ... }
// → Write the JSDoc
```

---

### What NOT to write

```typescript
// Bad: restates the function name — adds zero information
/**
 * Creates a user.
 */
async createUser({ userDao }: CreateUserOptions): Promise<User> { ... }

// Bad: describes the implementation, not the behaviour
/**
 * Queries the verified_session_request table and returns the token field.
 */
async getSessionToken({ accountId }: GetSessionTokenOptions): Promise<string> { ... }

// Good: describes what it means and when it fails
/**
 * Return the active session token for the most recent succeeded verification.
 *
 * @param {string} accountId - The Collin account UUID.
 * @returns {Promise<string>} The raw session token from `verification_response`.
 * @throws {BadRequestError} If no succeeded session exists — re-initiate verification.
 */
async getSessionToken({ accountId }: GetSessionTokenOptions): Promise<string> { ... }
```

---

### Summary checklist

- [ ] Every exported function, class, method, and interface has a JSDoc comment.
- [ ] The first line is a short imperative summary ending with a period.
- [ ] `@param` is present for every parameter; optional params use `[bracketNotation]`.
- [ ] `@returns` describes the meaning of the return value, not just its type name.
- [ ] `@throws` is present for every error the caller must handle.
- [ ] Class-level JSDoc describes what the class represents (one or two sentences).
- [ ] Interface properties use inline `/** ... */` comments for non-obvious fields.
- [ ] The comment does not merely restate the function name or signature.
