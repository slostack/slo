---
name: typescript-code-review-rules
description: Fast-pass review checklist for TypeScript and Node.js code — violations are blockers, not
  suggestions.
when_to_use: Use when reviewing any TypeScript pull request, code change, or newly written module for
  correctness, type safety, structure, and test coverage.
group: languages
kind: skill
---

# TypeScript Code Review Rules

## Skill summary

- **Name:** `typescript-code-review-rules`
- **Description:** Fast-pass review checklist for TypeScript and Node.js code — violations are blockers, not suggestions.
- **When to use:** Use when reviewing any TypeScript pull request, code change, or newly written module for correctness, type safety, structure, and test coverage.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Review this TypeScript service for code review violations"
- "Check this pull request against our TypeScript standards"
- "I wrote a new route handler — can you fast-pass it against the checklist?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

This checklist is applied in order. A violation in any section is a **blocker** — it must be fixed before the code ships. The checklist is not a style guide; every rule here prevents a class of real bugs or causes significant maintenance burden if ignored.

---

## Section 1: Universal rules (all TypeScript code)

### 1.1 Options object pattern for 2+ parameters

Any function or method with two or more parameters MUST use an options object. A positional multi-argument signature is a blocker.

```typescript
// Blocker: positional arguments
function buildReport(title: string, format: string, includeArchived: boolean): Report { ... }

// Required: options object
interface BuildReportOptions {
  readonly title: string;
  readonly format: ReportFormat;
  readonly includeArchived: boolean;
}
function buildReport({ title, format, includeArchived }: BuildReportOptions): Report { ... }
```

### 1.2 Explicit return types on all public and exported symbols

Every exported function, method, and class getter must declare its return type explicitly. TypeScript inference is not a substitute.

```typescript
// Blocker: return type inferred
export async function fetchInvoice({ invoiceId }: FetchInvoiceOptions) {
  return db.invoices.findById(invoiceId);
}

// Required: explicit return type
export async function fetchInvoice({ invoiceId }: FetchInvoiceOptions): Promise<Invoice | null> {
  return db.invoices.findById(invoiceId);
}
```

### 1.3 No `any` without a comment

`any` disables the type checker. Every use of `any` must have an inline comment explaining why `unknown` or a proper type cannot be used.

```typescript
// Blocker: unexplained any
const payload: any = await parseRequest(req);

// Required: explained any, or better — use unknown
const payload: unknown = await parseRequest(req);
const validated = RequestSchema.parse(payload); // narrow after validation
```

### 1.4 JSDoc on every exported symbol

Every exported function, class, method, and interface must have a JSDoc comment. The comment must describe *what it means*, not restate the signature. See the `typescript-method-docstrings` skill for the full format.

```typescript
// Blocker: no JSDoc on an exported service method
export async function triggerVerificationRun({ runId }: TriggerOptions): Promise<Run> { ... }

// Required: JSDoc with @param, @returns, and @throws where applicable
/**
 * Trigger an async verification run and return its initial record.
 *
 * @param {string} runId - UUID of the pre-created run record.
 * @returns {Promise<Run>} The run record in QUEUED status.
 * @throws {NotFoundError} If no run exists for the given ID.
 */
export async function triggerVerificationRun({ runId }: TriggerOptions): Promise<Run> { ... }
```

### 1.5 Single decision per method; max ~8 lines of logic

A method that makes more than one type of decision must be split. If a method body exceeds ~8 lines of substantive logic, extract named private steps.

```typescript
// Blocker: orchestrator with inline computation and multiple decision types
async processWorkflow(): Promise<void> {
  if (this.type === "query") {
    if (this.query) {
      if (this.query.engine === "clickhouse") { await this._runClickHouse(); return; }
      throw new Error("bad engine");
    }
    throw new Error("no query");
  }
  if (this.type === "merge") { await this._merge(); return; }
  throw new Error("bad type");
}

// Required: one decision per method
async processWorkflow(): Promise<void> {
  if (this.type === "query") { await this._processQueryWorkflow(); return; }
  if (this.type === "merge") { await this._merge(); return; }
  throw new Error(`Unsupported workflow type: ${this.type}`);
}
private async _processQueryWorkflow(): Promise<void> {
  if (!this.query) throw new Error(`No query for run ${this.runId}`);
  if (this.query.engine === "clickhouse") { await this._runClickHouse(); return; }
  throw new Error(`Unsupported engine: ${this.query.engine}`);
}
```

### 1.6 No more than 1 level of nesting

More than one level of nested `if` statements is a blocker. Use guard clauses and early returns.

```typescript
// Blocker: two levels of nesting
if (user) {
  if (user.isVerified) {
    await send({ user });
  }
}

// Required: guard clauses flatten the nesting
if (!user) return;
if (!user.isVerified) return;
await send({ user });
```

---

## Section 2: TypeScript type safety

### 2.1 `unknown` over `any` for external / untrusted data

Data arriving from HTTP requests, file parsing, third-party libraries, or `JSON.parse` must be typed `unknown` and validated before use.

```typescript
// Blocker: external data accepted as any
app.post("/webhook", (req) => {
  const event: any = req.body; // unsafe
  processEvent(event.type);
});

// Required: validate with a schema library before narrowing
app.post("/webhook", (req) => {
  const event = WebhookEventSchema.parse(req.body); // Zod throws on invalid input
  processEvent(event.type);
});
```

### 2.2 Discriminated unions with exhaustive checks

When a function branches on a union type, use a `switch` with a `never` default to enforce exhaustiveness.

```typescript
// Blocker: non-exhaustive branching — new variants are silently ignored
function handleEvent(event: AppEvent): void {
  if (event.type === "created") { onCreate(event); return; }
  if (event.type === "updated") { onUpdate(event); return; }
  // "deleted" variant silently dropped
}

// Required: exhaustive switch
function handleEvent(event: AppEvent): void {
  switch (event.type) {
    case "created": onCreate(event); return;
    case "updated": onUpdate(event); return;
    case "deleted": onDelete(event); return;
    default: {
      const _exhaustive: never = event;
      throw new Error(`Unhandled event type: ${JSON.stringify(_exhaustive)}`);
    }
  }
}
```

### 2.3 No type assertions (`as SomeType`) on untrusted data

Casting external or unvalidated data to a type with `as` bypasses the type checker entirely. Use runtime validation (Zod, valibot, typebox) instead.

```typescript
// Blocker: assertion on untrusted data
const body = req.body as CreateUserRequest; // no runtime check

// Required: parse and validate
const body = CreateUserRequestSchema.parse(req.body); // throws if invalid
```

### 2.4 `readonly` on options objects and value objects

Options object interfaces and value object interfaces must mark all properties `readonly` to prevent accidental mutation by the receiving function.

```typescript
// Blocker: mutable options object
interface SearchOptions {
  query: string;
  limit: number;
}

// Required: readonly properties
interface SearchOptions {
  readonly query: string;
  readonly limit: number;
}
```

---

## Section 3: Node.js / Express / Nitro route handlers

### 3.1 Route handlers delegate to a service layer — no inline business logic

A route handler's body must only: parse the request, call a service, and send the response. Business logic inside a handler is a blocker. The response objects in these mechanics examples are historical/unknown-profile illustrations; use the selected API response profile for their concrete fields, version, errors, and status behavior.

```typescript
// Blocker: business logic inline in the route handler
router.post("/orders", async (req, res) => {
  const order = await db.orders.create(req.body);
  if (order.totalAmount > 10000) {
    await notificationService.sendHighValueAlert({ order });
  }
  await billingService.reserve({ orderId: order.id });
  res.status(201).json({ data: order });
});

// Required: delegate to a service
router.post("/orders", async (req, res) => {
  const body = CreateOrderRequestSchema.parse(req.body);
  const order = await orderService.create({ body });
  res.status(201).json({ data: order });
});
```

### 3.2 All responses follow the selected API response profile

Every API response must follow the project's selected and documented response profile. The [TypeScript API response profile](../typescript-api-response-conventions/SKILL.md) owns the current TypeScript adapter, while the [language-independent response contract](../../../coding/api-response-conventions/SKILL.md) owns shared semantics and compatibility rules. Preserve existing deployed/project-documented wire bytes and require an explicit existing/project contract before changing root fields, version, pagination, error shape, status mapping, or helper behavior. The `{ data: ... }` and `{ error: ... }` snippets below are retained as historical or unknown-profile review examples; they are not a universal standard and do not define an additional TypeScript profile.

```typescript
// Historical/unknown-profile example: raw data in response
res.json(user);

// Historical/unknown-profile example: a selected profile may require an envelope;
// use that profile's factory/helper and exact fields rather than copying this shape.
res.json({ data: user });

// Historical/unknown-profile example: error root shape is profile-specific.
res.status(400).json({
  error: { code: "VALIDATION_ERROR", message: err.message },
});
```

### 3.3 Auth and permissions declared as middleware — not inline

Authorization checks must be applied as middleware on the route, not as inline conditionals inside the handler body.

```typescript
// Blocker: inline auth check
router.delete("/posts/:id", async (req, res) => {
  if (req.user?.role !== "admin") {
    return res.status(403).json({ error: "Forbidden" });
  }
  await postService.delete({ postId: req.params.id });
  res.status(204).send();
});

// Required: middleware on the route declaration
router.delete(
  "/posts/:id",
  requireRole("admin"),
  async (req, res) => {
    await postService.delete({ postId: req.params.id });
    res.status(204).send();
  },
);
```

---

## Section 4: Testing

### 4.1 Every decision point has a test

Each `if`, `switch` branch, early return, guard clause, and `try/catch` path must have at least one dedicated test. A test that only exercises the happy path is incomplete.

```typescript
// Blocker: only the success path is tested
it("creates a user", async () => {
  const user = await userService.create({ email: "a@b.com", name: "Alice" });
  expect(user.id).toBeDefined();
});

// Required: each decision point gets its own test
it("throws ValidationError when email is missing", async () => {
  await expect(userService.create({ email: "", name: "Alice" }))
    .rejects.toThrow(ValidationError);
});

it("throws ConflictError when email already exists", async () => {
  await userService.create({ email: "a@b.com", name: "Alice" });
  await expect(userService.create({ email: "a@b.com", name: "Bob" }))
    .rejects.toThrow(ConflictError);
});

it("returns the created user on success", async () => {
  const user = await userService.create({ email: "a@b.com", name: "Alice" });
  expect(user).toMatchObject({ email: "a@b.com", name: "Alice" });
});
```

### 4.2 No `.skip` or `.todo` without a removal comment

Skipped tests hide regressions. Any `it.skip`, `describe.skip`, `it.todo`, or `xit` must have an inline comment stating the ticket or condition under which it will be unskipped.

```typescript
// Blocker: skip without explanation
it.skip("syncs to external CRM", async () => { ... });

// Required: explanation and ticket
it.skip("syncs to external CRM — pending CRM sandbox credentials (AGI-1234)", async () => { ... });
```

### 4.3 Tests assert decision points, not just "it ran"

Assertions must verify the outcome of the specific decision under test, not merely that the function completed without throwing.

```typescript
// Blocker: assertion proves nothing
it("processes the order", async () => {
  await expect(orderService.process({ orderId: "123" })).resolves.not.toThrow();
});

// Required: assert the specific outcome of the decision being tested
it("marks the order as completed after successful charge", async () => {
  const order = await orderService.process({ orderId: "123" });
  expect(order.status).toBe("completed");
  expect(chargeSpy).toHaveBeenCalledWith({ orderId: "123", amount: order.totalAmount });
});
```

---

## Fast-pass checklist

Copy this into a review comment to share findings systematically:

```
## TypeScript Review Checklist

### Section 1 — Universal rules
- [ ] Options object for all functions with 2+ params
- [ ] Explicit return types on all exported symbols
- [ ] No `any` without an explanatory comment
- [ ] JSDoc on every exported symbol
- [ ] Single decision per method; max ~8 lines of logic
- [ ] No more than 1 level of nesting

### Section 2 — Type safety
- [ ] `unknown` (+ schema validation) for all external data
- [ ] Discriminated unions with exhaustive `never` default
- [ ] No `as SomeType` on unvalidated data
- [ ] `readonly` on all options/value object interfaces

### Section 3 — Route handlers
- [ ] Handlers delegate to service layer (no inline business logic)
- [ ] All responses follow the selected/project API response profile; no unqualified universal envelope is assumed
- [ ] Auth/permissions applied as middleware, not inline

### Section 4 — Testing
- [ ] Every decision point (if/switch/guard/catch) has a test
- [ ] No .skip / .todo without a ticket comment
- [ ] Assertions verify decision outcomes, not just "it ran"
```
