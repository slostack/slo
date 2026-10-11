---
name: declarative-method-structure
description: "Shared declarative design: coherent decomposition, Tell Don't Ask, flat control flow, explicit ownership, and readable orchestrators."
when_to_use: Use when designing or reviewing methods, functions, services, handlers, and workflow orchestration in any supported language.
group: coding
kind: skill
---

# Declarative Method Structure: Tell, Don't Ask

## Skill summary

This is the active, full language-independent owner for declarative method
structure. The central rule is **coherent decomposition**: make each method own
one understandable decision or workflow step, and extract only clean,
independently understandable abstractions.

Read this owner before the applicable specialization:

- Python: `skills/languages/python/declarative-method-structure/SKILL.md`
- Go: `skills/languages/go/go-declarative-method-structure/SKILL.md`
- TypeScript: `skills/languages/typescript/typescript-declarative-method-structure/SKILL.md`

The specialization owns syntax, language idioms, explicit types, error forms,
framework adjustments, and its stated threshold at the point it addresses.
Shared semantics remain here. An applicable specific rule prevails only on the
specific point it governs; it does not silently override generic ownership,
framework, test, security, or protocol requirements. If two applicable
specific rules conflict, record and resolve the conflict explicitly rather than
averaging or weakening them.

## Examples

- The user asks for a language-neutral refactor that separates decisions, delegates behavior to its owner, or makes an orchestrator readable.
- Use this owner for the complete before/after teaching patterns and decision-path testing guidance.
- Read the Python, Go, or TypeScript specialization afterward for syntax, error, type, framework, and threshold rules.

## Guidance

Declarative code communicates **what** happens instead of making the reader
reconstruct **how** it happens from nested conditionals and incidental detail.
The patterns in this skill are language-independent design guidance. The code
examples retain their language syntax deliberately: each example is labelled,
is illustrative rather than a project contract, and does not replace the
language specialization.

### Coherent decomposition and meaningful helpers

The approved `core-coding-rules.md` design source requires splitting code at a
clean independent abstraction: shared knowledge, a decision, a state owner, or
a contract. Do not create a helper that is merely a fragment
of a thought and cannot be understood without its caller. A line-count signal
may prompt review, but it is never a mechanical quota.

A useful decomposition has an explicit input, output, owner, and test seam. It
should make the caller easier to read without moving confusion into a chain of
shallow helpers. Keep one coherent operation together when splitting it would
hide rather than clarify the operation.

### Single decision per method

Each method should make one kind of decision. When it needs another decision,
delegate it to a named method or collaborator with a clear contract. Keep
dispatch, validation, policy, persistence, transport mechanics, and rendering
separate when they are independently understandable.

```text
execute → prepare → validate → apply → publish
```

The rule is about ownership, not about banning a short conditional. A small,
closed choice can remain together when that is clearer than a registry.

### Tell, Don't Ask

Tell collaborators to perform behavior instead of asking for internal state and
reimplementing their policy in the caller. The object that owns a state
transition or eligibility rule owns the decision that governs it. This reduces
coupling, prevents feature envy, and keeps policy changes local.

### Flat control flow

Use guard clauses and early returns so the happy path reads linearly. Avoid
deeply nested conditionals. Normally keep nesting to one level; if a framework
or language construct requires another shape, make the contract explicit rather
than disguising the nesting with boolean expressions.

### Lookup tables, strategies, and polymorphism

Use a lookup or strategy boundary when alternatives are independently named,
tested, or extended. Use polymorphism when each alternative owns meaningful
behavior. Keep a direct conditional when the alternatives are small, closed,
and easier to read together. The owner of the decision chooses the boundary;
do not add indirection for its own sake.

### Readable orchestrators

An orchestrator should show ordering and boundaries, not inline every
implementation detail:

```python
async def execute(self, request: Request) -> Result:
    prepared = await self._prepare(request=request)
    self._validate(prepared=prepared)
    result = await self._apply(prepared=prepared)
    return await self._publish(result=result)
```

This Python fragment is an illustrative source-preserved example, not a
production requirement. Keyword arguments, Go context-first signatures,
TypeScript options objects, and project-specific framework contracts belong to
the applicable language and framework owners.

### Error and lifecycle boundaries

Handle expected errors at the boundary that owns the operation. Preserve
meaningful context when wrapping an error, and keep exact error text when it is
an observable CLI, RPC, or wire contract. A lifecycle owner owns cancellation,
cleanup, joining, and terminal state; do not scatter those responsibilities
across callers.

A caller may coordinate a collaborator's result, but it must not reproduce the
collaborator's private policy. A background operation must have one identifiable
owner for start, stop/cancel, wait, cleanup, and terminal reporting.

### Testing boundaries

Test every decision and meaningful failure boundary at the layer that owns it.
Test dispatch variants, guards, failure cutoffs, absent later effects, and
lifecycle cleanup. A generic structural rule is not a substitute for a
language-specific test recipe, persistence proof, HTTP proof, security test,
or end-to-end verification.

## Source-preserved patterns

The following detailed patterns preserve the historical declarative-method-
structure recipe. They are retained here because the generic owner must carry
the teaching examples, before/after reasoning, and review checklist rather
than reducing them to headings. The Python syntax is intentionally labelled;
Python-specific obligations still belong to the Python specialization.

### Pattern: Nested conditionals → declarative delegation

#### Bad: multiple nested decisions (illustrative Python)

```python
async def _execute_workflow(self) -> None:
    if self.workflow.workflow_type == WorkflowType.QUERY_EXECUTION:
        if self.query:
            if self.query.query_engine == QueryEngine.CLICKHOUSE:
                await self._execute_query_and_store_to_s3_clickhouse()
                return
            raise ValueError(
                f"Query engine {self.query.query_engine} not supported"
            )
        raise ValueError(f"Query not found for workflow run {self.workflow_run.id}")
    if self.workflow.workflow_type == WorkflowType.MERGE_S3_FILES:
        await self._execute_merge_s3_files()
        return
    raise ValueError(f"Workflow type {self.workflow.workflow_type} not supported")
```

Problems:

- Three levels of nested conditionals hide the workflow and query decisions.
- The reader must hold workflow type, query presence, and engine in mind.
- Validation and dispatch are mixed, so each decision is harder to test.

#### Good: one decision per method (illustrative Python)

```python
async def _execute_workflow(self) -> None:
    """Dispatch to an executor based on workflow type."""
    if self.workflow.workflow_type == WorkflowType.QUERY_EXECUTION:
        await self._execute_query_execution()
        return
    if self.workflow.workflow_type == WorkflowType.MERGE_S3_FILES:
        await self._execute_merge_s3_files()
        return
    raise ValueError(f"Workflow type {self.workflow.workflow_type} not supported")

async def _execute_query_execution(self) -> None:
    """Validate and execute the query workflow."""
    if not self.query:
        raise ValueError(f"Query not found for workflow run {self.workflow_run.id}")
    if self.query.query_engine == QueryEngine.CLICKHOUSE:
        await self._execute_query_and_store_to_s3_clickhouse()
        return
    raise ValueError(f"Query engine {self.query.query_engine} not supported")
```

The first method decides workflow dispatch; the second owns query validation and
engine dispatch. The call stack documents the decision tree.

### Pattern: validation chains

#### Bad: deeply nested validation (illustrative Python)

```python
async def process_order(self, order_id: str) -> None:
    order = await self.get_order(order_id)
    if order:
        if order.status == "pending":
            if order.customer:
                if order.customer.is_verified:
                    if order.total_amount > 0:
                        await self._charge_customer(order)
                        await self._send_confirmation(order)
                    else:
                        raise ValueError("Order amount must be positive")
                else:
                    raise ValueError("Customer not verified")
            else:
                raise ValueError("Order has no customer")
        else:
            raise ValueError(f"Order status is {order.status}, expected pending")
    else:
        raise ValueError(f"Order {order_id} not found")
```

#### Good: guards and named validation (illustrative Python)

```python
async def process_order(self, order_id: str) -> None:
    """Process a pending order by charging and confirming it."""
    order = await self._load_and_validate_order(order_id=order_id)
    await self._charge_customer(order=order)
    await self._send_confirmation(order=order)

async def _load_and_validate_order(self, order_id: str) -> Order:
    """Load an order and reject each invalid prerequisite early."""
    order = await self.get_order(order_id=order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    if order.status != "pending":
        raise ValueError(f"Order status is {order.status}, expected pending")
    self._validate_order_customer(order=order)
    self._validate_order_amount(order=order)
    return order


def _validate_order_customer(self, order: Order) -> None:
    """Validate that the order has a verified customer."""
    if not order.customer:
        raise ValueError("Order has no customer")
    if not order.customer.is_verified:
        raise ValueError("Customer not verified")


def _validate_order_amount(self, order: Order) -> None:
    """Validate that the order amount is positive."""
    if order.total_amount <= 0:
        raise ValueError("Order amount must be positive")
```

The main method reads load → validate → charge → confirm. Each guard and
validation has an independently testable failure boundary.

### Pattern: strategy/command with lookup tables

#### Bad: long conditional chain (illustrative Python)

```python
async def format_report(self, report_type: str, data: dict) -> str:
    if report_type == "pdf":
        return await self._format_as_pdf(data)
    elif report_type == "excel":
        return await self._format_as_excel(data)
    elif report_type == "csv":
        return await self._format_as_csv(data)
    elif report_type == "json":
        return await self._format_as_json(data)
    elif report_type == "xml":
        return await self._format_as_xml(data)
    raise ValueError(f"Unsupported report type: {report_type}")
```

#### Good: lookup table (illustrative Python)

```python
from collections.abc import Awaitable, Callable

Formatter = Callable[[Report], Awaitable[str]]

async def format_report(self, report: Report, report_type: str) -> str:
    """Format a report through the selected formatter."""
    formatter = self._get_formatter(report_type=report_type)
    return await formatter(report)


def _get_formatter(self, report_type: str) -> Formatter:
    """Return one formatter or reject an unsupported type."""
    formatters: dict[str, Formatter] = {
        "pdf": self._format_as_pdf,
        "excel": self._format_as_excel,
        "csv": self._format_as_csv,
        "json": self._format_as_json,
        "xml": self._format_as_xml,
    }
    formatter = formatters.get(report_type)
    if formatter is None:
        raise ValueError(f"Unsupported report type: {report_type}")
    return formatter
```

A registry is useful when formats are independently extensible. A small closed
choice can remain a conditional if that is clearer.

### Pattern: Tell, Don't Ask with services

#### Bad: asking and deciding (illustrative Python)

```python
async def sync_user_data(self, user_id: str) -> None:
    """Sync user data to external systems."""
    user = await self.user_service.get_by_id(user_id=user_id)
    if user.email and user.email_verified:
        await self.email_service.sync_contact(
            email=user.email, name=user.full_name, tags=["verified"]
        )
    if user.subscription and user.subscription.is_active:
        await self.billing_service.sync_subscription(
            user_id=user.id, plan=user.subscription.plan, status="active"
        )
    if user.preferences and user.preferences.marketing_enabled:
        await self.marketing_service.add_to_campaigns(
            user_id=user.id, segments=user.preferences.segments
        )
```

This coordinator knows another service's eligibility fields. Policy changes
ripple into the coordinator and couple it to the user model.

#### Good: telling services what to do (illustrative Python)

```python
async def sync_user_data(self, user_id: str) -> None:
    """Ask each integration to apply its own eligibility policy."""
    user = await self.user_service.get_by_id(user_id=user_id)
    await self.email_service.sync_user_if_eligible(user=user)
    await self.billing_service.sync_user_if_eligible(user=user)
    await self.marketing_service.sync_user_if_eligible(user=user)
```

Each service owns its policy:

```python
# email_service.py — a usable companion example, not an orphan heading
async def sync_user_if_eligible(self, user: User) -> None:
    """Sync a contact only when this service's policy permits it."""
    if not self._is_eligible_for_sync(user=user):
        return
    await self._sync_contact(user=user)


def _is_eligible_for_sync(self, user: User) -> bool:
    """Apply the email service's eligibility rule."""
    return bool(user.email and user.email_verified)


async def _sync_contact(self, user: User) -> None:
    """Send the owned contact representation to the external client."""
    await self.external_client.sync_contact(
        email=user.email, name=user.full_name, tags=["verified"]
    )
```

### Pattern: polymorphism over conditionals

When alternatives have independently owned behavior, move the behavior into
handlers rather than growing a type-based coordinator.

#### Bad: type-based conditionals (illustrative Python)

```python
async def execute_notification(self, notification: Notification) -> None:
    """Deliver a notification by branching on every channel."""
    if notification.channel == "email":
        await self.email_client.send(
            to=notification.recipient,
            subject=notification.subject,
            body=notification.body,
        )
    elif notification.channel == "sms":
        await self.sms_client.send(to=notification.recipient, message=notification.body)
    elif notification.channel == "push":
        await self.push_client.send(
            device_token=notification.recipient,
            title=notification.subject,
            body=notification.body,
        )
    elif notification.channel == "webhook":
        await self.http_client.post(url=notification.recipient, json=notification.payload)
```

#### Good: strategy handlers with a coordinator (illustrative Python)

```python
from abc import ABC, abstractmethod

class NotificationHandler(ABC):
    @abstractmethod
    async def can_handle(self, notification: Notification) -> bool:
        """Return whether this handler owns the notification."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, notification: Notification) -> None:
        """Deliver a notification owned by this handler."""
        raise NotImplementedError


class EmailNotificationHandler(NotificationHandler):
    async def can_handle(self, notification: Notification) -> bool:
        """Match email notifications."""
        return notification.channel == "email"

    async def execute(self, notification: Notification) -> None:
        """Deliver an email notification."""
        await self.email_client.send(
            to=notification.recipient,
            subject=notification.subject,
            body=notification.body,
        )


class SMSNotificationHandler(NotificationHandler):
    async def can_handle(self, notification: Notification) -> bool:
        """Match SMS notifications."""
        return notification.channel == "sms"

    async def execute(self, notification: Notification) -> None:
        """Deliver an SMS notification."""
        await self.sms_client.send(to=notification.recipient, message=notification.body)


class NotificationExecutor:
    def __init__(self, handlers: list[NotificationHandler]) -> None:
        self.handlers = handlers

    async def execute_notification(self, notification: Notification) -> None:
        """Find the owning handler and tell it to execute."""
        handler = await self._find_handler(notification=notification)
        await handler.execute(notification=notification)

    async def _find_handler(self, notification: Notification) -> NotificationHandler:
        """Find one handler or report the unsupported channel."""
        for handler in self.handlers:
            if await handler.can_handle(notification=notification):
                return handler
        raise ValueError(f"No handler for notification channel: {notification.channel}")
```

The `email_service.py`, concrete handler, and coordinator fragments are now
shown in usable code context; they are not orphan headings or claims about a
particular production framework.

### Pattern: orchestrators read like a table of contents

#### Bad: procedural orchestrator (illustrative Python)

```python
async def assess_node(state: AgentState) -> dict:
    iteration: int = state["iteration"] + 1
    updates: dict = {}
    if iteration == 1:
        classification = _extract_classification(state["messages"])
        if classification is not None:
            updates.update(classification)
            log_debug(f"extracted classification: {classification}")
        limits = _extract_limits(state["messages"])
        if limits is not None:
            updates.update(limits)
            log_debug(f"extracted limits: {limits}")
    max_iterations = updates.get("max_iterations", state["max_iterations"])
    # ... more inline computation, counting, phase detection, and prompt work ...
    return {"iteration": iteration, "updates": updates, "max_iterations": max_iterations}
```

The method mixes extraction, merging, counting, policy resolution, phase
selection, and state construction.

#### Good: declarative orchestrator (illustrative Python)

```python
async def assess_node(state: AgentState) -> dict:
    """Build an assessment update from named decisions."""
    iteration = state["iteration"] + 1
    updates = _extract_first_iteration_updates(
        iteration=iteration, messages=state["messages"]
    )
    tool_counts = _count_tool_calls_from_state(state=state)
    budgets = _resolve_budgets(updates=updates, state=state)
    phase = _determine_phase(
        iteration=iteration, max_iterations=budgets["max_iterations"]
    )
    assessment = _build_assessment_prompt(
        iteration=iteration, budgets=budgets, tool_counts=tool_counts, phase=phase
    )
    return _build_assess_state_update(
        assessment=assessment,
        iteration=iteration,
        tool_counts=tool_counts,
        phase=phase,
        updates=updates,
    )
```

Read the method as extract → count → resolve → determine → build → return.
Each named step has a contract and can be tested independently.

## Cross-language examples

These are small standalone design examples, not copied production code. They
show the same ownership rule in all supported languages. The snippets are
complete enough to validate the central shape in a local harness once the
placeholder domain types are supplied; they are not framework or dependency
requirements.

### Python — Tell, Don't Ask and a flat workflow

This small harness is complete Python syntax; the in-memory store owns the
lookup decision rather than exposing it to its caller:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Receipt:
    receipt_id: str


class ReceiptStore:
    def __init__(self) -> None:
        self._receipts: dict[str, Receipt] = {}

    def load_or_create(self, *, receipt_id: str) -> Receipt:
        receipt = self._receipts.get(receipt_id)
        if receipt is not None:
            return receipt
        receipt = Receipt(receipt_id=receipt_id)
        self._receipts[receipt_id] = receipt
        return receipt
```

### Go — typed boundary, error ownership, and early return

This is a complete standard-library-free example after adding the `context`
and `fmt` imports shown below; its types and in-memory collaborators make the
ownership boundary executable in a temporary harness:

```go
package example

import (
    "context"
    "fmt"
)

type Receipt struct{ ID string }

type ReceiptStore struct{ receipts map[string]Receipt }

func (s *ReceiptStore) LoadOrCreate(ctx context.Context, id string) (Receipt, error) {
    if err := ctx.Err(); err != nil {
        return Receipt{}, fmt.Errorf("checking receipt context: %w", err)
    }
    receipt, ok := s.receipts[id]
    if ok {
        return receipt, nil
    }
    receipt = Receipt{ID: id}
    s.receipts[id] = receipt
    return receipt, nil
}
```

### TypeScript — options boundary and owned fallback

This fragment uses only TypeScript syntax and is intentionally labelled as a
compile-oriented example; the repository has no `tsc` executable available in
this environment, so compilation remains unverified here:

```typescript
interface Receipt {
  readonly receiptId: string;
}

interface LoadReceiptOptions {
  readonly receiptId: string;
}

class ReceiptStore {
  private readonly receipts = new Map<string, Receipt>();

  loadOrCreate({ receiptId }: LoadReceiptOptions): Receipt {
    const receipt = this.receipts.get(receiptId);
    if (receipt !== undefined) return receipt;
    const created: Receipt = { receiptId };
    this.receipts.set(receiptId, created);
    return created;
  }
}
```

The language recipes define the broader import, documentation, error, options,
and threshold contracts for production code. These examples validate the
shared ownership shape without implying a framework or project dependency.

## Refactor triggers

### Refactor when you see

1. More than one normal level of nested conditionals: extract a named guard,
   policy, or workflow step.
2. Multiple decisions in one method: give each decision a named owner.
3. A caller checking another object's state before deciding: move the policy to
   the state owner.
4. A long conditional chain over independently extensible alternatives: use a
   lookup table, strategy, or polymorphism.
5. Repeated conditional patterns: extract shared policy or use configuration.
6. A method name that joins unrelated work with “and”: split only at a clean
   independent boundary.
7. An orchestrator mixing persistence, transport, decoding, and policy: keep
   mechanics in the owning adapter or step.

### Keep when you see

1. A simple one-level guard clause.
2. One decision with a small, closed set of branches.
3. A clear conditional whose alternatives are easier to read together than a
   new abstraction.

## Testing benefits and decision-path examples

Declarative code makes each decision boundary visible. A nested workflow test
must arrange every surrounding condition before reaching the branch. A
single-decision test can arrange only the state owned by that method:

```python
# The nested version requires workflow type, query, and engine setup.
workflow = Mock(workflow_type=WorkflowType.QUERY_EXECUTION)
query = Mock(query_engine=QueryEngine.CLICKHOUSE)
service = WorkflowService(workflow=workflow, query=query)
await service._execute_workflow()

# The split version tests dispatch independently.
workflow = Mock(workflow_type=WorkflowType.QUERY_EXECUTION)
service = WorkflowService(workflow=workflow)
with patch.object(service, "_execute_query_execution") as mock:
    await service._execute_workflow()
    mock.assert_called_once()
```

The corresponding test matrix should cover: each dispatch branch; missing
prerequisites; unsupported alternatives; successful delegation; failure
cutoffs; and the absence of later effects after a failure. Use the applicable
language, framework, persistence, lifecycle, and end-to-end recipes for the
actual boundary under test.

## Review checklist

- [ ] Does each method own one coherent decision or workflow step?
- [ ] Are extracted helpers independently understandable, typed where required, and testable?
- [ ] Does the caller tell collaborators to act rather than inspect their state?
- [ ] Is the happy path flat, with guards and expected errors at owned boundaries?
- [ ] Does the orchestrator read as named steps and preserve lifecycle ownership?
- [ ] Are lookup/strategy boundaries used only for independently named or extensible alternatives?
- [ ] Are exact error, cancellation, cleanup, and terminal-state contracts preserved?
- [ ] Do tests cover each decision, failure cutoff, absent later effect, and relevant integration boundary?
- [ ] Did I load the applicable Python, Go, or TypeScript specialization?
- [ ] Did I preserve project-specific framework, security, protocol, and test obligations?
