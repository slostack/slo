---
name: typescript-declarative-method-structure
description: Enforce Tell-Don't-Ask, single-decision-per-method, and flat orchestrator patterns in TypeScript
  classes and modules.
when_to_use: Use when writing or reviewing any TypeScript class method, service, or route handler that
  contains nested conditionals, inline computation, or type-based branching.
group: languages
kind: skill
---

# TypeScript Declarative Method Structure

## Skill summary

- **Name:** `typescript-declarative-method-structure`
- **Description:** Enforce Tell-Don't-Ask, single-decision-per-method, and flat orchestrator patterns in TypeScript classes and modules.
- **When to use:** Use when writing or reviewing any TypeScript class method, service, or route handler that contains nested conditionals, inline computation, or type-based branching.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Review this service class for declarative structure"
- "My method has a nested if inside another if — how should I restructure it?"
- "I have a long switch statement on an event type — what's the TypeScript pattern?"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

Declarative code organises methods so they communicate **what** happens, not **how** it happens through nested conditionals. Each method should have a single, clear responsibility. The goal is that a new developer can understand the high-level flow by reading only the top-level orchestrator method — the private methods fill in the details.

---

### Rule 1: Single decision per method

Each method or function makes only ONE type of decision. When a method needs to make multiple decisions, extract each into a separate named private method.

```typescript
// Bad: three levels of nesting — workflow type, query presence, query engine
async _executeWorkflow(): Promise<void> {
  if (this.workflow.type === WorkflowType.QueryExecution) {
    if (this.query) {
      if (this.query.engine === QueryEngine.ClickHouse) {
        await this._runClickHouseQuery();
        return;
      }
      throw new Error(`Unsupported engine: ${this.query.engine}`);
    }
    throw new Error(`No query for run ${this.workflowRunId}`);
  }
  if (this.workflow.type === WorkflowType.MergeS3Files) {
    await this._mergeS3Files();
    return;
  }
  throw new Error(`Unsupported workflow type: ${this.workflow.type}`);
}

// Good: each method makes one decision
async _executeWorkflow(): Promise<void> {
  if (this.workflow.type === WorkflowType.QueryExecution) {
    await this._executeQueryWorkflow();
    return;
  }
  if (this.workflow.type === WorkflowType.MergeS3Files) {
    await this._mergeS3Files();
    return;
  }
  throw new Error(`Unsupported workflow type: ${this.workflow.type}`);
}

private async _executeQueryWorkflow(): Promise<void> {
  if (!this.query) {
    throw new Error(`No query for workflow run ${this.workflowRunId}`);
  }
  if (this.query.engine === QueryEngine.ClickHouse) {
    await this._runClickHouseQuery();
    return;
  }
  throw new Error(`Unsupported engine: ${this.query.engine}`);
}
```

---

### Rule 2: No method body exceeds ~8 lines of logic

If you cannot describe what a method does in one sentence without using "and" or "then", it is doing too much. Extract named steps.

```typescript
// Bad: orchestrator with inline computation — reader must parse 25 lines to understand the flow
async assessNode(state: AgentState): Promise<Partial<AgentState>> {
  const iteration = state.iteration + 1;
  const updates: Partial<AgentState> = {};

  if (iteration === 1) {
    const classification = extractClassification(state.messages);
    if (classification !== null) {
      Object.assign(updates, classification);
    }
    const limits = extractLimits(state.messages);
    if (limits !== null) {
      Object.assign(updates, limits);
    }
  }

  const maxIterations = updates.maxIterations ?? state.maxIterations;
  const webCount = countToolCalls(state.messages, "web_search");
  const localCount = countToolCalls(state.messages, "local_search");
  // ... 15 more lines of inline computation ...
  return { ...updates, iteration, assessment };
}

// Good: orchestrator reads like a table of contents
async assessNode(state: AgentState): Promise<Partial<AgentState>> {
  const iteration = state.iteration + 1;
  const firstIterationUpdates = this._extractFirstIterationUpdates({ iteration, state });
  const toolCounts = this._countToolCallsFromState({ state });
  const budgets = this._resolveBudgets({ updates: firstIterationUpdates, state });
  const phase = this._determinePhase({ iteration, maxIterations: budgets.maxIterations });
  const assessment = this._buildAssessmentPrompt({ iteration, budgets, toolCounts, phase });
  return this._buildStateUpdate({ assessment, iteration, toolCounts, phase, firstIterationUpdates });
}
```

---

### Rule 3: No more than 1 level of nested conditionals — use guard clauses

Validation belongs at the top of the method as early-return guard clauses. Business logic follows without nesting.

```typescript
// Bad: five levels of nesting — impossible to follow
async processOrder({ orderId }: ProcessOrderOptions): Promise<void> {
  const order = await this.orderRepo.findById(orderId);
  if (order) {
    if (order.status === "pending") {
      if (order.customer) {
        if (order.customer.isVerified) {
          if (order.totalAmount > 0) {
            await this._chargeCustomer({ order });
            await this._sendConfirmation({ order });
          } else {
            throw new Error("Order amount must be positive");
          }
        } else {
          throw new Error("Customer not verified");
        }
      } else {
        throw new Error("Order has no customer");
      }
    } else {
      throw new Error(`Order status is ${order.status}, expected pending`);
    }
  } else {
    throw new Error(`Order ${orderId} not found`);
  }
}

// Good: guard clauses at the top; happy path is flat
async processOrder({ orderId }: ProcessOrderOptions): Promise<void> {
  const order = await this._loadAndValidateOrder({ orderId });
  await this._chargeCustomer({ order });
  await this._sendConfirmation({ order });
}

private async _loadAndValidateOrder({ orderId }: { orderId: string }): Promise<Order> {
  const order = await this.orderRepo.findById(orderId);
  if (!order) throw new Error(`Order ${orderId} not found`);
  if (order.status !== "pending") throw new Error(`Expected pending, got ${order.status}`);
  this._validateOrderCustomer({ order });
  this._validateOrderAmount({ order });
  return order;
}

private _validateOrderCustomer({ order }: { order: Order }): void {
  if (!order.customer) throw new Error("Order has no customer");
  if (!order.customer.isVerified) throw new Error("Customer not verified");
}

private _validateOrderAmount({ order }: { order: Order }): void {
  if (order.totalAmount <= 0) throw new Error("Order amount must be positive");
}
```

---

### Rule 4: Long if-else-if chains → `Record` lookup map

When branching on a string or enum key to invoke different handlers, use a `Record<K, Handler>` map instead of a long if-else chain.

```typescript
// Bad: long if-else chain
async formatReport({ reportType, data }: FormatReportOptions): Promise<string> {
  if (reportType === "pdf") return this._formatAsPdf({ data });
  if (reportType === "excel") return this._formatAsExcel({ data });
  if (reportType === "csv") return this._formatAsCsv({ data });
  if (reportType === "json") return this._formatAsJson({ data });
  throw new Error(`Unsupported report type: ${reportType}`);
}

// Good: lookup map — adding a new type is one line, no existing code changes
type ReportType = "pdf" | "excel" | "csv" | "json";
type ReportFormatter = (options: { data: unknown }) => Promise<string>;

private readonly _formatters: Record<ReportType, ReportFormatter> = {
  pdf: ({ data }) => this._formatAsPdf({ data }),
  excel: ({ data }) => this._formatAsExcel({ data }),
  csv: ({ data }) => this._formatAsCsv({ data }),
  json: ({ data }) => this._formatAsJson({ data }),
};

async formatReport({ reportType, data }: FormatReportOptions): Promise<string> {
  const formatter = this._formatters[reportType];
  if (!formatter) throw new Error(`Unsupported report type: ${reportType}`);
  return formatter({ data });
}
```

---

### Rule 5: TypeScript discriminated unions + exhaustive checks over if-else

When branching on a union type variant, use a `switch` with an exhaustive check. TypeScript's `never` type enforces that all cases are handled.

```typescript
// Bad: verbose if-else on union — not exhaustive, easy to miss a new variant
function renderNotification(n: Notification): string {
  if (n.type === "email") return `Email to ${n.recipient}`;
  if (n.type === "sms") return `SMS to ${n.recipient}`;
  // Forgot "push" — TypeScript won't catch this
  return "Unknown notification";
}

// Good: exhaustive switch — TypeScript errors if a new variant is added but not handled
type Notification =
  | { type: "email"; recipient: string; subject: string }
  | { type: "sms"; recipient: string }
  | { type: "push"; deviceToken: string; title: string };

function renderNotification(notification: Notification): string {
  switch (notification.type) {
    case "email":
      return `Email to ${notification.recipient}: ${notification.subject}`;
    case "sms":
      return `SMS to ${notification.recipient}`;
    case "push":
      return `Push to ${notification.deviceToken}: ${notification.title}`;
    default: {
      const _exhaustive: never = notification;
      throw new Error(`Unhandled notification type: ${JSON.stringify(_exhaustive)}`);
    }
  }
}
```

---

### Rule 6: Tell, don't ask — push decisions into the object that owns the state

Methods should tell other objects what to do, not interrogate their state and then decide externally.

```typescript
// Bad: the caller knows too much about the internals of EmailService
async syncUser({ user }: SyncUserOptions): Promise<void> {
  if (user.email && user.emailVerified) {
    await this.emailService.syncContact({ email: user.email, name: user.fullName });
  }
  if (user.subscription?.isActive) {
    await this.billingService.syncSubscription({ userId: user.id, plan: user.subscription.plan });
  }
}

// Good: each service encapsulates its own eligibility logic
async syncUser({ user }: SyncUserOptions): Promise<void> {
  await this.emailService.syncUserIfEligible({ user });
  await this.billingService.syncUserIfEligible({ user });
}

// Inside EmailService:
async syncUserIfEligible({ user }: { user: User }): Promise<void> {
  if (!this._isEligibleForSync({ user })) return;
  await this._syncContact({ user });
}

private _isEligibleForSync({ user }: { user: User }): boolean {
  return Boolean(user.email && user.emailVerified);
}
```

---

### Quick-reference refactor triggers

| Signal | Action |
|---|---|
| More than 1 level of nested `if` | Extract inner block to named method |
| Method body > ~8 lines | Extract named steps |
| `if/else if` chain on a string or enum | Replace with `Record<K, Handler>` lookup |
| Branch on a union type | Use exhaustive `switch` with `never` |
| Caller checks an object's state then decides | Push the decision into the object |
| Method name has "and" in it | Split into two methods |
