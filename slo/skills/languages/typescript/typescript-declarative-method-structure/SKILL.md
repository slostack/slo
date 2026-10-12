---
name: typescript-declarative-method-structure
description: "TypeScript-specific syntax and contracts for the shared Tell Don't Ask and coherent-decomposition rule."
when_to_use: Use for TypeScript functions, methods, services, route handlers, and workflow nodes after reading the generic owner.
group: languages
kind: skill
---

# TypeScript Declarative Method Structure

## Skill summary

This is the TypeScript specialization of the shared owner at
`skills/coding/declarative-method-structure/SKILL.md`. Read that owner first
for coherent decomposition, one decision per method, Tell, Don't Ask, flat
control flow, meaningful examples, testing boundaries, and the generic review
checklist. This file does not restate those generic lessons.

This specialization owns TypeScript-specific expression: typed options objects,
explicit return contracts, `Record<K, Handler>` dispatch, discriminated unions
with exhaustive `never` checks, and the approximate **8 lines of substantive
logic** refactoring signal. The signal is not a mechanical quota; clean
abstractions and project/framework contracts prevail.

## Examples

- Use this file to choose the TypeScript form of a shared declarative design.
- Use it for typed options, `Record` dispatch, exhaustive unions, or the TS ~8-line signal.
- Use the generic owner for the full language-independent before/after teaching patterns.

## Guidance

**Scope:** TypeScript. Load
`skills/languages/typescript/typescript-conventions/SKILL.md` and the applicable
router, client, framework, and test recipes. Framework examples apply only to
the declared stack. Shared ownership, security, protocol, and test-category
rules remain applicable. Compile-only evidence is not runtime proof.

### Typed boundaries and flat orchestration

Use options objects at multi-value boundaries and explicit return types. An
orchestrator should name steps rather than inline state extraction, policy,
persistence, or transport mechanics:

```typescript
async assessNode(state: AgentState): Promise<Partial<AgentState>> {
  const iteration = state.iteration + 1;
  const updates = this._extractFirstIterationUpdates({ iteration, state });
  const toolCounts = this._countToolCallsFromState({ state });
  const budgets = this._resolveBudgets({ updates, state });
  const phase = this._determinePhase({ iteration, maxIterations: budgets.maxIterations });
  return this._buildStateUpdate({ iteration, updates, toolCounts, budgets, phase });
}
```

The generic owner retains the full procedural/declarative before/after
orchestrator teaching example. This excerpt owns the TypeScript options and
return syntax.

### `Record<K, Handler>` for extensible dispatch

When a string or enum selects independently extensible handlers, use a typed
`Record<K, Handler>` map close to the owner of those alternatives. A small
closed choice may remain a direct conditional. Keep the unsupported-key error
observable and test it:

```typescript
type ReportType = "pdf" | "json";
type ReportFormatter = (options: { data: ReportData }) => Promise<string>;

private readonly _formatters: Record<ReportType, ReportFormatter> = {
  pdf: ({ data }) => this._formatAsPdf({ data }),
  json: ({ data }) => this._formatAsJson({ data }),
};

async formatReport({ reportType, data }: FormatReportOptions): Promise<string> {
  const formatter = this._formatters[reportType];
  if (!formatter) throw new Error(`Unsupported report type: ${reportType}`);
  return formatter({ data });
}
```

### Exhaustive discriminated unions

For a closed union, use a `switch` and assign the default value to `never` so a
new variant fails at compile time:

```typescript
type Notification =
  | { type: "email"; recipient: string; subject: string }
  | { type: "sms"; recipient: string }
  | { type: "push"; deviceToken: string; title: string };

function renderNotification(notification: Notification): string {
  switch (notification.type) {
    case "email": return `Email to ${notification.recipient}: ${notification.subject}`;
    case "sms": return `SMS to ${notification.recipient}`;
    case "push": return `Push to ${notification.deviceToken}: ${notification.title}`;
    default: {
      const exhaustive: never = notification;
      throw new Error(`Unhandled notification: ${String(exhaustive)}`);
    }
  }
}
```

### TypeScript decomposition signal and refactor triggers

The TypeScript signal is approximately **8 lines of substantive logic**. Count
meaningful computation and decisions, not signatures, braces, type syntax, or
a straightforward return. Extract when the method contains multiple decisions
or when a helper has a clean input, output, owner, and test contract. Do not
split a coherent operation solely to meet the number.

| TypeScript signal | Action |
|---|---|
| More than one normal level of nested conditional | Extract a named guard/validator or restructure the owner. |
| Approximately 8 lines of substantive logic | Review for meaningful decomposition, not a quota. |
| Extensible string/enum dispatch | Use a typed `Record<K, Handler>`. |
| Closed union branch | Use an exhaustive `switch` with `never`. |
| Caller checks object state before deciding | Move policy into the state owner. |
| Method name joins unrelated work with “and” | Split only at a clean independent boundary. |

## TypeScript checklist

- [ ] Did I read the generic owner first?
- [ ] Do multi-value boundaries use typed options objects and explicit returns?
- [ ] Are guards early and is the success path flat?
- [ ] Is extensible dispatch a typed `Record<K, Handler>` rather than a growing chain?
- [ ] Are closed discriminated unions exhaustive through `never`?
- [ ] Is approximately 8 lines used as a review signal, not an artificial quota?
- [ ] Does each extracted helper satisfy meaningful decomposition?
- [ ] Do tests cover every decision, failure boundary, compatibility effect, and relevant build/runtime gate?
- [ ] Did I load the applicable TypeScript framework and test recipes?
