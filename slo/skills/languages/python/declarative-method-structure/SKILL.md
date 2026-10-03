---
name: declarative-method-structure
description: 'Python: ''Tell, don''t ask'' — flat structure, early returns.'
when_to_use: For Python projects only. Apply to every method you write. Non-negotiable style.
group: languages
kind: skill
source_prompt: declarative-method-structure.md
---

# Declarative Method Structure: Tell, Don't Ask

## Skill summary

- **Name:** `declarative-method-structure`
- **Description:** 'Tell, don't ask' — flat structure, early returns.
- **When to use:** Apply to every method you write. Non-negotiable style.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `declarative-method-structure.md`

## Examples

- The user asks for help with: 'Tell, don't ask' — flat structure, early returns.
- Apply to every method you write. Non-negotiable style.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

Writing declarative code means organizing methods so they clearly communicate **what** happens, not **how** it happens through nested conditionals. This approach makes code easier to read, test, and maintain.

## Core Principles

### 1. Single Decision Per Method

Each method should make only **one type of decision**. When a method needs to make multiple decisions, extract those decisions into separate methods.

**Why?**
- Each method has a clear, single responsibility
- The call stack naturally documents the decision tree
- Testing becomes straightforward - one test per decision point
- Code reads like a table of contents

### 2. Tell, Don't Ask

Methods should **tell** other objects what to do, not **ask** them about their state and then make decisions based on that state.

**Why?**
- Reduces coupling between components
- Encapsulates decision logic where it belongs
- Makes code more declarative and easier to understand
- Prevents "feature envy" code smell

### 3. Flat is Better Than Nested

Avoid nesting conditionals more than one level deep. Use early returns and delegation to keep code flat.

**Why?**
- Nested conditionals are exponentially harder to understand
- Each level of nesting doubles the cognitive load
- Flat code reads linearly, like a story

## Pattern: Nested Conditionals → Declarative Delegation

### ❌ Bad: Multiple Nested Decisions

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

**Problems:**
- Three levels of nested conditionals
- Multiple decision points: workflow type, query existence, query engine
- Reader must hold all three conditions in mind simultaneously
- Difficult to test each decision independently
- Validation logic mixed with dispatch logic

### ✅ Good: Single Decision Per Method

```python
async def _execute_workflow(self) -> None:
    """Dispatch to appropriate workflow executor based on type."""
    if self.workflow.workflow_type == WorkflowType.QUERY_EXECUTION:
        await self._execute_query_execution()
        return
    if self.workflow.workflow_type == WorkflowType.MERGE_S3_FILES:
        await self._execute_merge_s3_files()
        return
    raise ValueError(f"Workflow type {self.workflow.workflow_type} not supported")

async def _execute_query_execution(self) -> None:
    """Execute query and validate requirements."""
    if not self.query:
        raise ValueError(f"Query not found for workflow run {self.workflow_run.id}")

    if self.query.query_engine == QueryEngine.CLICKHOUSE:
        await self._execute_query_and_store_to_s3_clickhouse()
        return

    raise ValueError(f"Query engine {self.query.query_engine} not supported")
```

**Benefits:**
- Each method makes exactly one type of decision
- `_execute_workflow`: decides on workflow type
- `_execute_query_execution`: decides on query engine
- Linear reading: no nested mental models required
- Each method can be tested independently
- Clear separation: dispatch vs validation vs execution

## Pattern: Validation Chains

### ❌ Bad: Deeply Nested Validation

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

**Problems:**
- Five levels of nesting
- Error messages at the bottom, hard to find
- Cannot understand flow without reading all conditions
- Testing requires setting up all nested states

### ✅ Good: Guard Clauses + Delegation

```python
async def process_order(self, order_id: str) -> None:
    """Process a pending order by charging customer and sending confirmation."""
    order = await self._load_and_validate_order(order_id)
    await self._charge_customer(order)
    await self._send_confirmation(order)

async def _load_and_validate_order(self, order_id: str) -> Order:
    """Load order and validate it's ready for processing."""
    order = await self.get_order(order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")

    if order.status != "pending":
        raise ValueError(f"Order status is {order.status}, expected pending")

    self._validate_order_customer(order)
    self._validate_order_amount(order)

    return order

def _validate_order_customer(self, order: Order) -> None:
    """Validate order has verified customer."""
    if not order.customer:
        raise ValueError("Order has no customer")

    if not order.customer.is_verified:
        raise ValueError("Customer not verified")

def _validate_order_amount(self, order: Order) -> None:
    """Validate order has positive amount."""
    if order.total_amount <= 0:
        raise ValueError("Order amount must be positive")
```

**Benefits:**
- Main method reads like a clear workflow: load → charge → confirm
- All validations up front with guard clauses
- Each validation method focuses on one concern
- Error messages at the top, immediately visible
- Easy to test each validation independently
- Easy to add new validations without changing existing code

## Pattern: Strategy/Command with Lookup Tables

When you have multiple conditional branches doing different things, consider using a lookup table or strategy pattern.

### ❌ Bad: Long If-Else Chain

```python
async def format_report(self, report_type: str, data: dict) -> str:
    if report_type == "pdf":
        formatted = await self._format_as_pdf(data)
        return formatted
    elif report_type == "excel":
        formatted = await self._format_as_excel(data)
        return formatted
    elif report_type == "csv":
        formatted = await self._format_as_csv(data)
        return formatted
    elif report_type == "json":
        formatted = await self._format_as_json(data)
        return formatted
    elif report_type == "xml":
        formatted = await self._format_as_xml(data)
        return formatted
    else:
        raise ValueError(f"Unsupported report type: {report_type}")
```

### ✅ Good: Lookup Table Pattern

```python
async def format_report(self, report_type: str, data: dict) -> str:
    """Format report data according to specified type."""
    formatter = self._get_formatter(report_type)
    return await formatter(data)

def _get_formatter(self, report_type: str) -> Callable:
    """Get appropriate formatter for report type."""
    formatters = {
        "pdf": self._format_as_pdf,
        "excel": self._format_as_excel,
        "csv": self._format_as_csv,
        "json": self._format_as_json,
        "xml": self._format_as_xml,
    }

    formatter = formatters.get(report_type)
    if not formatter:
        raise ValueError(f"Unsupported report type: {report_type}")

    return formatter
```

**Benefits:**
- Main method is two lines: get formatter, use formatter
- Adding new formats is trivial: add to dictionary
- No conditional logic in the main flow
- Easy to test: mock the formatter lookup
- Dictionary documents all available formats in one place

## Pattern: Tell, Don't Ask with Services

### ❌ Bad: Asking and Deciding

```python
async def sync_user_data(self, user_id: str) -> None:
    """Sync user data to external systems."""
    user = await self.user_service.get_by_id(user_id)

    # Asking about state and making decisions
    if user.email and user.email_verified:
        await self.email_service.sync_contact(
            email=user.email,
            name=user.full_name,
            tags=["verified"]
        )

    if user.subscription and user.subscription.is_active:
        await self.billing_service.sync_subscription(
            user_id=user.id,
            plan=user.subscription.plan,
            status="active"
        )

    if user.preferences and user.preferences.marketing_enabled:
        await self.marketing_service.add_to_campaigns(
            user_id=user.id,
            segments=user.preferences.segments
        )
```

**Problems:**
- This method knows too much about user state
- Tightly coupled to user structure
- Changes to user model ripple here
- Business logic scattered (what makes a user syncable?)

### ✅ Good: Telling Services What to Do

```python
async def sync_user_data(self, user_id: str) -> None:
    """Sync user data to external systems."""
    user = await self.user_service.get_by_id(user_id)

    # Tell each service to sync - they know what they need
    await self.email_service.sync_user_if_eligible(user)
    await self.billing_service.sync_user_if_eligible(user)
    await self.marketing_service.sync_user_if_eligible(user)
```

Then in each service:

```python
# email_service.py
async def sync_user_if_eligible(self, user: User) -> None:
    """Sync user contact to email system if they're eligible."""
    if not self._is_eligible_for_sync(user):
        return

    await self._sync_contact(user)

def _is_eligible_for_sync(self, user: User) -> bool:
    """Check if user is eligible for email sync."""
    return bool(user.email and user.email_verified)

async def _sync_contact(self, user: User) -> None:
    """Sync contact to email system."""
    await self.external_client.sync_contact(
        email=user.email,
        name=user.full_name,
        tags=["verified"]
    )
```

**Benefits:**
- Main method doesn't know about eligibility rules
- Each service encapsulates its own logic
- Easy to change eligibility rules per service
- Each service is independently testable
- Single Responsibility: coordinator just coordinates

## Pattern: Polymorphism Over Conditionals

When conditionals are based on type, consider using polymorphism.

### ❌ Bad: Type-Based Conditionals

```python
async def execute_notification(self, notification: Notification) -> None:
    """Execute notification delivery."""
    if notification.channel == "email":
        await self.email_client.send(
            to=notification.recipient,
            subject=notification.subject,
            body=notification.body
        )
    elif notification.channel == "sms":
        await self.sms_client.send(
            to=notification.recipient,
            message=notification.body
        )
    elif notification.channel == "push":
        await self.push_client.send(
            device_token=notification.recipient,
            title=notification.subject,
            body=notification.body
        )
    elif notification.channel == "webhook":
        await self.http_client.post(
            url=notification.recipient,
            json=notification.payload
        )
```

### ✅ Good: Strategy Pattern with Handlers

```python
# Base handler interface
class NotificationHandler(ABC):
    @abstractmethod
    async def can_handle(self, notification: Notification) -> bool:
        """Check if this handler can process the notification."""
        pass

    @abstractmethod
    async def execute(self, notification: Notification) -> None:
        """Execute notification delivery."""
        pass


# Concrete handlers
class EmailNotificationHandler(NotificationHandler):
    async def can_handle(self, notification: Notification) -> bool:
        return notification.channel == "email"

    async def execute(self, notification: Notification) -> None:
        await self.email_client.send(
            to=notification.recipient,
            subject=notification.subject,
            body=notification.body
        )


class SMSNotificationHandler(NotificationHandler):
    async def can_handle(self, notification: Notification) -> bool:
        return notification.channel == "sms"

    async def execute(self, notification: Notification) -> None:
        await self.sms_client.send(
            to=notification.recipient,
            message=notification.body
        )


# Coordinator
class NotificationExecutor:
    def __init__(self, handlers: List[NotificationHandler]):
        self.handlers = handlers

    async def execute_notification(self, notification: Notification) -> None:
        """Execute notification using appropriate handler."""
        handler = await self._find_handler(notification)
        await handler.execute(notification)

    async def _find_handler(self, notification: Notification) -> NotificationHandler:
        """Find handler that can process this notification."""
        for handler in self.handlers:
            if await handler.can_handle(notification):
                return handler

        raise ValueError(f"No handler for notification channel: {notification.channel}")
```

**Benefits:**
- No conditionals in coordinator
- Each handler is independently testable
- Adding new channels: create new handler class, no existing code changes
- Each handler encapsulates all channel-specific logic
- Open-closed principle: open for extension, closed for modification

## Pattern: Orchestrator Methods Read Like a Table of Contents

When a method orchestrates a multi-step workflow (e.g., a graph node, a pipeline step), the body should read as a flat sequence of **named delegations** — each line tells you *what* happens, the called method handles *how*.

### ❌ Bad: Procedural Orchestrator

```python
async def assess_node(state: AgentState) -> dict:
    iteration: int = state["iteration"] + 1
    updates: dict = {}

    # Inline conditional logic with nested if-not-None checks
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
    # ... 20 more lines of inline computation ...

    web_count, local_count, pubmed_count = _count_tool_calls(
        messages=state["messages"],
        web_search_count=state.get("web_search_count", 0),
        local_search_count=state.get("local_search_count", 0),
        pubmed_search_count=state.get("pubmed_search_count", 0),
    )
    # ... more inline computation ...
    return { ... big dict ... }
```

**Problems:**
- The orchestrator is doing extraction, conditional merging, counting, limit resolution, phase detection, and prompt building — all inline
- Reader must parse every line to understand the flow
- Each concern is tangled with the others — untestable in isolation

### ✅ Good: Declarative Orchestrator

```python
async def assess_node(state: AgentState) -> dict:
    iteration: int = state["iteration"] + 1
    updates: dict = _extract_first_iteration_updates(
        iteration=iteration,
        messages=state["messages"],
    )
    tool_counts: dict = _count_tool_calls_from_state(state=state)
    budgets: dict = _resolve_budgets(updates=updates, state=state)
    phase: str = _determine_phase(iteration=iteration, max_iterations=budgets["max_iterations"])
    assessment: str = _build_assessment_prompt(
        iteration=iteration,
        budgets=budgets,
        tool_counts=tool_counts,
        phase=phase,
    )
    return _build_assess_state_update(
        assessment=assessment,
        iteration=iteration,
        tool_counts=tool_counts,
        phase=phase,
        updates=updates,
    )
```

**Benefits:**
- The orchestrator reads like a table of contents: extract → count → resolve → determine → build → return
- Each step is a named method that can be tested independently
- A new developer reads five method names and understands the whole flow
- No conditionals, no nesting, no inline computation

### Rule: If a method body has more than ~8 lines of logic, it is doing too much. Extract named steps.

The test for "too much" is simple: can you describe what the method does in one sentence? If the answer is "it extracts classification, then extracts limits, then resolves budgets, then counts tools, then determines phase, then builds a prompt" — that's six things. Each one should be its own method.

---

## Quick Reference: When to Refactor

### Refactor When You See:

1. **More than 2 levels of nested if statements**
   - Extract inner conditionals to separate methods
   - Use guard clauses for validations

2. **Multiple decisions in one method**
   - Split into separate methods, one decision per method
   - Each method should answer one question

3. **Asking about state then deciding**
   - Push the decision into the object that owns the state
   - Tell objects what to do, don't ask then decide

4. **Long if-elif-else chains**
   - Use lookup tables/dictionaries
   - Consider strategy pattern
   - Consider polymorphism

5. **Repeated conditional patterns**
   - Extract to a method
   - Use configuration over conditionals

### Keep When You See:

1. **Simple guard clauses** (one level, early return)
2. **Single decision points** (one if with 2-3 branches)
3. **Clear, readable conditionals** (sometimes if-else is clearest)

## Testing Benefits

Declarative code is dramatically easier to test:

```python
# Testing nested conditionals requires complex setup
async def test_execute_workflow_query_clickhouse(self):
    # Must set up: workflow type, query existence, query engine
    workflow = Mock(workflow_type=WorkflowType.QUERY_EXECUTION)
    query = Mock(query_engine=QueryEngine.CLICKHOUSE)
    service = WorkflowService(workflow=workflow, query=query)
    await service._execute_workflow()
    # Assert...


# Testing single-decision methods is straightforward
async def test_execute_workflow_dispatches_to_query_execution(self):
    # Only need to set up: workflow type
    workflow = Mock(workflow_type=WorkflowType.QUERY_EXECUTION)
    service = WorkflowService(workflow=workflow)

    with patch.object(service, '_execute_query_execution') as mock:
        await service._execute_workflow()
        mock.assert_called_once()


async def test_execute_query_execution_validates_query_exists(self):
    # Only need to set up: missing query
    service = WorkflowService(query=None)

    with pytest.raises(ValueError, match="Query not found"):
        await service._execute_query_execution()


async def test_execute_query_execution_dispatches_clickhouse(self):
    # Only need to set up: query engine
    query = Mock(query_engine=QueryEngine.CLICKHOUSE)
    service = WorkflowService(query=query)

    with patch.object(service, '_execute_query_and_store_to_s3_clickhouse') as mock:
        await service._execute_query_execution()
        mock.assert_called_once()
```

## Summary Checklist

When writing or reviewing code, ask:

- [ ] Does each method make only one type of decision?
- [ ] Are validations using guard clauses at the top?
- [ ] Are there more than 2 levels of nesting? (Refactor if yes)
- [ ] Am I asking about state and then deciding? (Push decision down if yes)
- [ ] Do method names clearly describe what they do?
- [ ] Can each method be tested independently?
- [ ] Would a new developer understand the flow by reading method names?
- [ ] Are conditional branches based on type? (Consider polymorphism)
- [ ] Could a lookup table replace if-elif chains?
- [ ] Does the orchestrator method body read like a table of contents?
- [ ] If a method body exceeds ~8 lines of logic, have you extracted named steps?

**Remember:** Code is read far more often than it's written. Optimize for the reader.
