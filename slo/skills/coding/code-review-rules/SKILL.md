---
name: code-review-rules
description: Fast-pass review checklist of stack-agnostic non-negotiable hard rules
  extracted from the full convention library. A violation is a blocker, not a suggestion.
when_to_use: Use on every diff regardless of language or stack, before deeper feature-level
  review.
group: coding
kind: skill
source_prompt: code-review-rules.md
---

# Code Review: Hard Rules and Convention Enforcement

## Skill summary

- **Name:** `code-review-rules`
- **Description:** Fast-pass review checklist of stack-agnostic non-negotiable hard rules extracted from the full convention library. A violation is a blocker, not a suggestion.
- **When to use:** Use on every diff regardless of language or stack, before deeper feature-level review.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `code-review-rules.md`

## Examples

- The user asks for help with: Fast-pass review checklist of stack-agnostic non-negotiable hard rules extracted from the full convention library. A violation is a blocker, not a suggestion.
- Use on every diff regardless of language or stack, before deeper feature-level review.

## Guidance

A fast-pass review checklist that the agent applies to every diff, regardless of
stack. These are **non-negotiable hard rules** extracted from the full convention
library. A violation here is a blocker, not a suggestion.

---

## How to Use

1. Read the diff.
2. For each section below, tick every check that the diff satisfies.
3. Any unchecked box is a finding. Report it with file + line.
4. Organize findings into three tiers: **Blocker** (hard rule broken),
   **Warning** (soft convention bent), **Note** (style drift worth flagging).

---

## Section 1 — Universal Rules (all stacks, always)

### 1.1 Named Arguments + Type Hints

- [ ] Every function/method with **2 or more parameters** uses **keyword
      arguments at every call site**.
- [ ] Every parameter and return value has an **explicit type annotation**.
      `Any` is never used without a comment explaining why.
- [ ] No implicit `None` return from a function that the caller uses. `-> None`
      or `-> Optional[T]` must be stated.

```python
# Bad — positional args, missing return type
def process(user, order, flag):
    ...

# Good
def process(*, user: User, order: Order, flag: bool) -> ProcessResult:
    ...
```

---

### 1.2 Google-Style Docstrings

- [ ] Every **public** function, method, and class has a docstring.
- [ ] Docstrings follow Google style: `Args:`, `Returns:`, `Raises:` sections.
- [ ] Private helpers (`_*`) do not require docstrings but must have one if
      the WHY is non-obvious.
- [ ] No multi-paragraph wall-of-text docstrings. One short line max unless
      the interface is complex.

```python
# Bad — no docstring, or stale "does X" description that just restates the name
def invoke(self) -> str:
    ...

# Good
def invoke(self, *, query: str, max_iterations: int = 5) -> str:
    """Run the agent graph end-to-end and return the final response.

    Args:
        query (str): The user's question.
        max_iterations (int): Maximum tool-call rounds before forcing synthesis.

    Returns:
        str: The agent's final text response.
    """
```

---

### 1.3 Declarative Method Structure — Tell, Don't Ask

- [ ] No method body exceeds **~8 lines of logic**. If it does, named steps
      must be extracted.
- [ ] No more than **1 level of nested conditionals**. Guard clauses +
      early returns replace nesting.
- [ ] Orchestrator methods read like a **table of contents** — a flat
      sequence of named delegations, no inline computation.
- [ ] No method makes **multiple types of decisions**. Split decision types
      into separate methods.
- [ ] Long `if/elif` chains on a type/variant replaced by a **lookup table**
      or **strategy/handler pattern**.

```python
# Bad — 3-level nesting, inline computation, multiple decision types → blocker
async def execute(self) -> None:
    if self.workflow.type == WorkflowType.QUERY:
        if self.query:
            if self.query.engine == Engine.CLICKHOUSE:
                await self._run_clickhouse()
                return
            raise ValueError("engine not supported")
        raise ValueError("no query")
    raise ValueError("type not supported")

# Good — one decision per method, flat, named delegations
async def execute(self) -> None:
    if self.workflow.type == WorkflowType.QUERY:
        await self._execute_query()
        return
    raise ValueError(f"Workflow type {self.workflow.type} not supported")

async def _execute_query(self) -> None:
    if not self.query:
        raise ValueError(f"No query for workflow run {self.workflow_run.id}")
    if self.query.engine == Engine.CLICKHOUSE:
        await self._run_clickhouse()
        return
    raise ValueError(f"Engine {self.query.engine} not supported")
```

---

### 1.4 Ubiquitous Language — One Concept, One Name

- [ ] Every domain concept that crosses a **layer boundary** uses the
      **same canonical name** at every layer. No synonyms.
- [ ] DAO field names are **identical** to the SQLAlchemy model column names.
      No aliasing, no renaming.
- [ ] Router request/response field names match the Application Service
      attributes they pass to.
- [ ] Vue/TypeScript store keys and props are the **exact camelCase
      derivation** of the API's snake_case field (mechanical transformation,
      no creative synonyms).
- [ ] Test fixture parameters use the **production canonical names**.
      No shorthand (`n=10` instead of `question_limit=10`).
- [ ] No qualifier prefix is dropped (`difficulties` → violation;
      `question_difficulties` → correct).
- [ ] If the diff introduces a new concept, the canonical name is **defined
      at the vocabulary-authority layer first** (Makefile for CLI-facing;
      SQLAlchemy model column for backend-only) and then derived
      mechanically downstream.

```python
# Bad — three names for the same concept across three files
# router:
service = TriggerAppService(idempotency_key=body.correlation_id)
# app service:
class TriggerAppService:
    def __init__(self, *, request_key: str) -> None:
        self.request_key = request_key
# DAO:
class RunDAO(BaseModel):
    max_questions: Optional[int] = None  # column is question_limit

# Good — one name, mechanical derivation at each layer
# router:
service = TriggerAppService(correlation_id=body.correlation_id)
# app service:
class TriggerAppService:
    def __init__(self, *, correlation_id: str | None) -> None:
        self.correlation_id = correlation_id
# DAO:
class RunDAO(BaseModel):
    question_limit: Optional[int] = None  # identical to model column
```

```typescript
// Bad — Vue store invents its own synonym for the API field
// API returns { question_limit: 10, run_id: "abc" }
const maxQuestions = ref<number>(0)       // wrong — synonym
const verificationRunId = ref<string>('') // wrong — expanded unnecessarily

// Good — exact camelCase derivation, no deviation
const questionLimit = ref<number>(0)  // snake: question_limit → camelCase: questionLimit
const runId = ref<string>('')         // snake: run_id → camelCase: runId
```

---

### 1.5 Code-Test Loop Evidence

- [ ] Every new **production unit** (function, class, route, store action,
      component) has a corresponding test file or test additions.
- [ ] No more than **~50 lines of new production code** without accompanying
      new tests in the same diff.
- [ ] Tests assert **decision points**, not just that the function runs.
      A test that calls `invoke()` and asserts `result is not None` is not
      a test.
- [ ] No test is marked `@pytest.mark.skip`, `xfail`, or `TODO` without an
      accompanying tracking comment explaining when it will be removed.

```python
# Bad — test exists but asserts nothing meaningful
async def test_trigger_runs(self):
    result = await self.service.invoke()
    assert result is not None  # proves nothing about behaviour

# Good — each test covers one decision point
async def test_invoke_raises_when_no_query(self):
    service = WorkflowExecutorService(query=None)
    with pytest.raises(ValueError, match="No query for workflow run"):
        await service.invoke()

async def test_invoke_dispatches_clickhouse_for_clickhouse_engine(self):
    service = WorkflowExecutorService(query=Mock(engine=Engine.CLICKHOUSE))
    with patch.object(service, "_run_clickhouse") as mock:
        await service.invoke()
    mock.assert_called_once()

# Bad — skip with no removal condition
@pytest.mark.skip  # no comment, no ticket, no condition
async def test_payment_webhook():
    ...

# Good
@pytest.mark.skip(reason="Payment gateway sandbox unavailable; remove after AGI-11500 closes")
async def test_payment_webhook():
    ...
```

---

## Section 2 — FastAPI / Python Backend

### 2.1 Domain Layer (3-File Pattern)

- [ ] Domain lives in `src/domains/<name>/` with `dao.py`, `model.py`,
      `service.py`. No extra business logic files without justification.
- [ ] `dao.py` uses Pydantic `BaseModel` with `ConfigDict(from_attributes=True)`.
- [ ] Every `dao.py` field that maps to a model column has an **identical
      name** to that column. `model_dump()` must be usable directly in the
      model constructor without remapping.
- [ ] Status/enum constants are defined as **named constants** at the top of
      `dao.py` and imported everywhere they are referenced.
- [ ] `service.py` methods follow `snake_case` verb phrases that match the
      DAO they write to.

```python
# Bad — DAO field name differs from model column; constants inline in service
# dao.py
class VerificationRunDAO(BaseModel):
    max_questions: Optional[int] = None   # column is question_limit — MISMATCH

# service.py
async def create(self, limit: int) -> VerificationRun:
    run = VerificationRun(question_cap=limit)  # three different names for one concept

# Good — field names are identical to columns; constants at top of dao.py
# dao.py
STATUS_QUEUED: str = "QUEUED"
STATUS_RUNNING: str = "RUNNING"
STATUS_COMPLETED: str = "COMPLETED"

class VerificationRunDAO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    question_limit: Optional[int] = None   # identical to VerificationRun.question_limit
    correlation_id: Optional[str] = None   # identical to VerificationRun.correlation_id

# service.py — model_dump() works directly; no remapping needed
@staticmethod
async def create(
    *,
    verification_run_dao: VerificationRunDAO,
    db_session: AsyncSession,
) -> VerificationRun:
    run = VerificationRun(**verification_run_dao.model_dump())
    db_session.add(run)
    await db_session.flush()
    return run
```

---

### 2.2 Application Service (`invoke()` Pattern)

- [ ] Application service has a **single public method: `invoke()`**.
- [ ] `invoke()` is **orchestration only** — it calls private `_step_*`
      methods; no inline SQL, no direct external I/O.
- [ ] Each private step method is independently testable with a mock.
- [ ] No business logic inline in `invoke()`.

```python
# Bad — inline SQL, direct I/O, and business logic all crammed into invoke()
class CreateReportAppService:
    async def invoke(self) -> Report:
        rows = await self.db.execute(
            select(Run).where(Run.status == "COMPLETED").limit(100)
        )
        report = Report(
            total=len(rows),
            by_status={r.status: r.id for r in rows},
        )
        await self.s3_client.put_object(
            Bucket="reports", Key=f"{report.id}.json", Body=report.json()
        )
        return report

# Good — invoke() is a table of contents; each step is private and testable
class CreateReportAppService:
    async def invoke(self) -> Report:
        """Orchestrate report creation: load runs, build report, export to S3."""
        runs: list[Run] = await self._load_completed_runs()
        report: Report = await self._build_report(runs=runs)
        await self._export_to_s3(report=report)
        return report

    async def _load_completed_runs(self) -> list[Run]:
        return await RunDomainService.fetch_completed(db_session=self.db_session)

    async def _build_report(self, *, runs: list[Run]) -> Report:
        return await ReportDomainService.create(
            run_ids=[r.id for r in runs],
            db_session=self.db_session,
        )

    async def _export_to_s3(self, *, report: Report) -> None:
        await self.s3_client.put_object(
            bucket="reports",
            key=f"{report.id}.json",
            body=report.model_dump_json(),
        )
```

---

### 2.3 Routers

- [ ] Every `app.include_router(...)` sets
      `prefix="<service-namespace>/api/v1"`. Bare `/api/v1` is a blocker.
- [ ] Every successful response is wrapped in `SuccessResponseDAO`.
- [ ] Every new FastAPI app or sub-app ships with a matching **VSCode launch
      configuration** in `.vscode/launch.json`.
- [ ] Permissions are explicitly declared on routes that require them.

```python
# Bad — bare /api/v1 prefix, unwrapped response, missing permissions
app.include_router(router=reports_router, prefix="/api/v1")  # blocker

@router.post("/reports")
async def create_report(body: CreateReportRequestDAO) -> Report:
    report = await CreateReportAppService(body=body).invoke()
    return report  # unwrapped — blocker

# Good — namespace prefix, SuccessResponseDAO wrapper, explicit permission
app.include_router(router=reports_router, prefix="/v/api/v1")

@router.post("/reports", dependencies=[Depends(require_internal_auth)])
async def create_report(
    request: Request,
    body: CreateReportRequestDAO,
) -> SuccessResponseDAO:
    report = await CreateReportAppService(
        correlation_id=body.correlation_id,
        question_limit=body.question_limit,
        db_session=request.state.db_session,
    ).invoke()
    return SuccessResponseDAO(data=VerificationRunDAO.model_validate(report))
```

---

### 2.4 DBOS / Workers

- [ ] Every DBOS workflow function and queue follows the project naming
      convention.
- [ ] Every workflow function is **registered in the DBOS queue config**.
      A function that exists but is not registered is dead code.
- [ ] Dedup/idempotency IDs are present on enqueue calls.

```python
# Bad — workflow function defined but never registered; no dedup ID on enqueue
@DBOS.workflow()
async def process_report_workflow(run_id: str) -> None:
    ...

# somewhere in the app: queue not configured, no dedup ID
await WorkflowQueue("some_queue").enqueue(process_report_workflow, run_id)
# queue "some_queue" never appears in the DBOS config → dead code

# Good — queue defined in config, registered, dedup ID present
# dbos_config.py
REPORT_WORKFLOW_QUEUE = WorkflowQueue(
    name="report_workflow_queue",
    concurrency=5,
)

# worker.py
@DBOS.workflow()
async def process_report_workflow(*, run_id: str) -> None:
    """Durable workflow for report generation."""
    ...

# enqueuer — dedup ID prevents double-processing on retry
await REPORT_WORKFLOW_QUEUE.enqueue(
    process_report_workflow,
    run_id=run_id,
    dedup_id=f"report-{run_id}",
)
```

---

## Section 3 — Vue 3 / TypeScript Frontend

### 3.1 Component Structure

- [ ] Every component uses **`<script setup lang="ts">`**. Options API is a
      blocker.
- [ ] `defineProps` and `defineEmits` use **TypeScript generic syntax**, not
      the runtime object form.
- [ ] **One component per `.vue` file**. Multiple `export default` in one
      file is a blocker.
- [ ] Views are thin — they compose and wire; no business logic inline.
- [ ] Stateful logic is in `composables/use*.ts`, not inline in components.

```vue
<!-- Bad — Options API, runtime props, business logic inline in a view -->
<script lang="ts">
export default {
  props: {
    message: { type: Object, required: true }
  },
  data() {
    return { isLoading: false }
  },
  methods: {
    async submitForm() {
      this.isLoading = true
      const resp = await fetch('/v/api/v1/reports', { method: 'POST', body: ... })
      const data = await resp.json()
      this.isLoading = false
      // ... 30 more lines of fetch/parse/validate inline
    }
  }
}
</script>

<!-- Good — Composition API, typed props, logic in composable -->
<script setup lang="ts">
import type { Message } from '@/types/chat'
import { useReportSubmit } from '@/composables/useReportSubmit'

const props = defineProps<{
  message: Message
  questionLimit: number
}>()

const emit = defineEmits<{
  submitted: [reportId: string]
  error: [reason: string]
}>()

const { submit, isLoading } = useReportSubmit()

async function handleSubmit() {
  const reportId = await submit({ questionLimit: props.questionLimit })
  emit('submitted', reportId)
}
</script>
```

---

### 3.2 Naming and API Field Derivation

- [ ] Every API snake_case field has the **exact camelCase derivation** as
      the store key and prop name. The transformation is mechanical:
      `question_limit` → `questionLimit`. No alternatives.
- [ ] No Vue component or store introduces a **synonym** for a backend
      concept.

```typescript
// API response shape: { question_limit: 10, correlation_id: "abc", run_id: "xyz" }

// Bad — store invents new names, component uses yet another
// stores/report.ts
const maxQuestions = ref<number>(0)          // wrong — synonym for question_limit
const idempotencyKey = ref<string>('')        // wrong — synonym for correlation_id

// ReportView.vue
defineProps<{ limit: number }>()             // wrong — abbreviated synonym

// Good — exact camelCase derivation, used consistently in store AND component
// stores/report.ts
const questionLimit = ref<number>(0)         // question_limit → questionLimit ✓
const correlationId = ref<string>('')        // correlation_id → correlationId ✓
const runId = ref<string>('')               // run_id → runId ✓

// ReportView.vue
defineProps<{
  questionLimit: number    // camelCase of question_limit — matches store ✓
  correlationId: string    // camelCase of correlation_id — matches store ✓
}>()
```

---

### 3.3 SSE / Streaming

- [ ] SSE streams consumed via the `useAgentStream` composable pattern.
      Raw `EventSource` inline in a component is a violation.

```typescript
// Bad — raw EventSource wired directly inside a component
// ChatView.vue
const source = new EventSource('/la/api/v1/chat/stream')
source.onmessage = (event) => {
  messages.value.push(JSON.parse(event.data))
}
source.onerror = () => {
  isError.value = true
  source.close()
}

// Good — composable owns the EventSource lifecycle; component only reacts
// composables/useAgentStream.ts
export function useAgentStream(endpoint: string) {
  const messages = ref<AgentMessage[]>([])
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  function start(query: string) {
    isStreaming.value = true
    const source = new EventSource(`${endpoint}?query=${encodeURIComponent(query)}`)
    source.onmessage = (e) => messages.value.push(JSON.parse(e.data))
    source.onerror = () => { error.value = 'Stream error'; source.close(); isStreaming.value = false }
    source.addEventListener('done', () => { source.close(); isStreaming.value = false })
  }

  return { messages, isStreaming, error, start }
}

// ChatView.vue — component is three lines
const { messages, isStreaming, error, start } = useAgentStream('/la/api/v1/chat/stream')
```

---

## Section 4 — CLI (Typer)

### 4.1 Separation of Concerns

- [ ] `app.py` contains **only** Typer declarations: app, callback, option
      definitions, and thin wrappers. No runtime assembly, no feature logic.
- [ ] `typer_dispatch.py` (or equivalent dispatcher) handles **all** path
      resolution, env/config reads, and runtime object construction.
- [ ] Feature logic lives in **separate helper modules** — not in `app.py`
      or the dispatcher.

```python
# Bad — app.py does path resolution, config loading, and business logic
# src/cli/app.py
@app.command()
def verify(
    env: str = typer.Option("local"),
    n: int = typer.Option(10),
) -> None:
    config_path = Path.home() / ".config" / "orders" / f"{env}.toml"
    config = toml.load(config_path)                  # runtime assembly — wrong place
    session = Session(api_key=config["api_key"])     # runtime assembly — wrong place
    runs = session.fetch_runs(limit=n)               # feature logic — wrong place
    for run in runs:
        typer.echo(run.id)

# Good — app.py is parse-only; dispatch handles assembly; helper handles logic
# src/cli/app.py
@app.command()
def verify(
    env: str = typer.Option("local", help="Target environment."),
    question_limit: int = typer.Option(10, "--question-limit", "--n", min=1, max=200),
) -> None:
    """Trigger a verification run against the target environment."""
    typer_dispatch.run_verify(env=env, question_limit=question_limit)

# src/cli/typer_dispatch.py
def run_verify(*, env: str, question_limit: int) -> None:
    """Assemble runtime objects and delegate to the verify feature."""
    config: AppConfig = _load_config(env=env)
    session: Session = _build_session(config=config)
    verify_feature.run(session=session, question_limit=question_limit)

# src/cli/verify_feature.py
def run(*, session: Session, question_limit: int) -> None:
    """Fetch and display verification runs."""
    runs = session.fetch_runs(limit=question_limit)
    for run in runs:
        rprint(f"[green]{run.id}[/green]  {run.status}")
```

---

### 4.2 Name Traceability

- [ ] New CLI-facing concepts are **named at the Makefile level first**.
- [ ] The dispatcher's module docstring contains an **explicit mapping table**
      (`Make var → env var → Typer flag → Python attribute`).
- [ ] No name translation happens outside the dispatcher.

```python
# Bad — no mapping table; translation scattered across two files
# src/cli/app.py
def verify(n: int = typer.Option(10)):  # "n" not traced to anything
    dispatch.run(limit=n)               # renamed on the way in

# src/cli/typer_dispatch.py — no docstring, implicit translation
def run(*, limit: int) -> None:
    session.fetch_runs(max_q=limit)     # renamed again — three names total

# Good — mapping table in dispatcher docstring; one translation point only
# src/cli/typer_dispatch.py
"""Dispatch entry point for ``make verify-flow ENV=<env>``.

Name mapping — Make var → env var → Typer flag → Python attribute:

  N=<int>        → QUESTION_LIMIT       → --n / --question-limit → question_limit
  ENV=<str>      → ENV                  → --env                  → env
  DRY_RUN=true   → VERIFIER_DRY_RUN     → --dry-run              → dry_run

The dispatcher is the ONLY file that translates. All downstream code
uses the canonical Python attribute name without further remapping.
"""

def run_verify(*, env: str, question_limit: int, dry_run: bool) -> None:
    verify_feature.run(
        env=env,
        question_limit=question_limit,   # canonical name flows through unchanged
        dry_run=dry_run,
    )
```

---

## Section 5 — Textual TUI

### 5.1 Layer Separation

- [ ] `app.py` (App subclass) contains **only** widget tree, bindings, and
      lifecycle hooks. No slash command parsing, no rendering logic.
- [ ] Slash commands and key events are routed through a dedicated
      `slash_router.py` or equivalent — not inline in App methods.
- [ ] Domain events are converted to widget updates in `event_renderer.py`
      or equivalent — not in App.
- [ ] All async domain work runs via `app.run_worker()` — not in message
      handlers.

```python
# Bad — App class handles slash parsing, rendering, and domain calls inline
class SloApp(App):
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.startswith("/help"):          # slash parsing — wrong place
            self.query_one(RichLog).write("[bold]Commands:[/bold] /help /clear")
        elif event.value.startswith("/clear"):
            self.query_one(RichLog).clear()
        else:
            response = await self.session.send(event.value)   # domain call — wrong place
            for line in response.split("\n"):
                self.query_one(RichLog).write(Markdown(line)) # rendering — wrong place

# Good — App delegates to router, renderer, and run_worker
class SloApp(App):
    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="transcript")
        yield Input(placeholder="Message…", id="input")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        handled = self.slash_router.route(command=event.value, app=self)
        if not handled:
            self.run_worker(self._stream_response(query=event.value))

    async def _stream_response(self, *, query: str) -> None:
        async for domain_event in self.session.stream(query=query):
            self.event_renderer.render(event=domain_event, log=self.query_one(RichLog))

# src/tui/slash_router.py — isolated, testable
class SlashRouter:
    def route(self, *, command: str, app: SloApp) -> bool:
        if command == "/help":
            app.query_one(RichLog).write(HELP_TEXT)
            return True
        if command == "/clear":
            app.query_one(RichLog).clear()
            return True
        return False

# src/tui/event_renderer.py — isolated, testable
class EventRenderer:
    def render(self, *, event: DomainEvent, log: RichLog) -> None:
        if event.type == "text_delta":
            log.write(event.content)
        elif event.type == "done":
            log.write(Rule())
```

---

### 5.2 Styling

- [ ] Layout and presentation are in `.tcss` files. No inline styles on
      widgets.

```python
# Bad — inline styles in compose() and widget definitions
class SloApp(App):
    def compose(self) -> ComposeResult:
        yield Header(style="bold white on blue")          # inline style — wrong
        yield RichLog(id="transcript", styles="height: 80%; border: solid green")

# Good — styles live in app.tcss; widget definitions are style-free
class SloApp(App):
    CSS_PATH = "app.tcss"

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="transcript")
        yield Input(id="input")
```

```css
/* app.tcss */
Header {
    background: $primary;
    color: $text;
}

#transcript {
    height: 1fr;
    border: solid $accent;
}

#input {
    height: 3;
    dock: bottom;
}
```

---

## Section 6 — AI / LangGraph Agents

### 6.1 Gateway Convention

- [ ] The graph class exposes **`invoke()`** as the canonical entry point.
      No other name (e.g. `run()`, `execute()`, `query()`) is the primary
      public method.
- [ ] If streaming is supported, **`invoke_streaming()`** exists as an async
      generator.
- [ ] Both `invoke()` and `invoke_streaming()` share
      **`_build_initial_state()`** — no duplication.

```python
# Bad — no invoke() gateway; streaming duplicates state setup
class PubmedSearchGraph:
    async def search(self, query: str) -> str:         # wrong method name
        state = {"messages": [HumanMessage(query)], "iteration": 0}
        graph = self.build()
        result = await graph.ainvoke(state)
        return result["messages"][-1].content

    async def stream_search(self, query: str):          # duplicated state setup
        state = {"messages": [HumanMessage(query)], "iteration": 0}
        graph = self.build()
        async for chunk in graph.astream(state):
            yield chunk

# Good — invoke() gateway; shared _build_initial_state(); invoke_streaming() consistent
class PubmedSearchGraph:
    async def invoke(self, *, query: str, max_iterations: int = 10) -> str:
        """Run the agent graph end-to-end and return the final response."""
        state = self._build_initial_state(query=query, max_iterations=max_iterations)
        graph = self.build()
        result = await graph.ainvoke(state)
        return result["messages"][-1].content

    async def invoke_streaming(self, *, query: str, max_iterations: int = 10):
        """Stream progress events as the agent graph executes."""
        state = self._build_initial_state(query=query, max_iterations=max_iterations)
        graph = self.build()
        async for chunk in graph.astream(state):
            yield chunk

    def _build_initial_state(self, *, query: str, max_iterations: int) -> dict:
        """Shared by invoke() and invoke_streaming() — single source of truth."""
        return {
            "messages": [HumanMessage(content=query)],
            "iteration": 0,
            "max_iterations": max_iterations,
        }
```

---

### 6.2 Static vs Instance

- [ ] Routing functions and pure helpers (phase detectors, parsers,
      assessment builders) are **`@staticmethod`**.
- [ ] Node factories (`_make_*_node`) and `build()` are **instance methods**.

```python
# Bad — routing function is an instance method; it takes self but uses none of it
class PubmedSearchGraph:
    def _should_continue(self, state: AgentState) -> str:
        if len(state["messages"]) > 10:
            return "synthesize"
        return "tools"

    # node factory correctly instance — but wrongly calling self._should_continue
    def build(self) -> CompiledStateGraph:
        graph.add_conditional_edges("agent", self._should_continue)  # can't pass self-method here cleanly

# Good — pure routing logic is @staticmethod; node factories are instance methods
class PubmedSearchGraph:
    @staticmethod
    def _should_continue(state: AgentState) -> str:
        """Route after agent node. No side effects, no instance state."""
        if len(state["messages"]) > 10:
            return "synthesize"
        return "tools"

    def _make_agent_node(self, *, llm: LLM) -> NodeFn:
        """Instance method — uses self.temperature and self.model_name."""
        model = llm.bind_tools(self.tools, temperature=self.temperature)
        async def agent_node(state: AgentState) -> dict:
            response = await model.ainvoke(state["messages"])
            return {"messages": [response]}
        return agent_node

    def build(self) -> CompiledStateGraph:
        llm = ChatOpenAI(model=self.model_name)
        graph.add_node("agent", self._make_agent_node(llm=llm))
        graph.add_conditional_edges("agent", PubmedSearchGraph._should_continue)
```

---

### 6.3 Execution Flow Diagram

- [ ] A **module-level ASCII comment block** appears **above** the class
      definition showing all nodes, conditional edges, loops, and the
      `END` terminal.
- [ ] The diagram uses `[function_name?]` notation for routing decision
      points and shows all values the routing function can return.

```python
# Bad — no diagram; reader must trace graph.add_node() calls manually
class PubmedSearchGraph:
    def build(self) -> CompiledStateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._make_agent_node(llm=llm))
        graph.add_node("tools", ToolNode(self.tools))
        graph.add_node("synthesize", self._make_synthesize_node(llm=llm))
        graph.add_conditional_edges("agent", PubmedSearchGraph._should_continue)
        ...

# Good — execution flow diagram as module-level comment above the class
# ---------------------------------------------------------------------------
# PubmedSearchGraph — Execution Flow
# ---------------------------------------------------------------------------
#
# invoke() / invoke_streaming()
#   → _build_initial_state()
#     → graph.ainvoke() / graph.astream()
#
# Graph Node Sequence:
#
#               ┌──────────────────────────────────┐
#               │                                  │
#               ▼                                  │
# START ──► agent ──► [_should_continue?]           │
#                           │          │            │
#                       "tools"   "synthesize"      │
#                           │          │            │
#                           ▼          ▼            │
#                         tools    synthesize ──► END
#                           │
#                           └──────────────────────┘
#
# _should_continue returns: "tools" | "synthesize"
# ---------------------------------------------------------------------------

class PubmedSearchGraph:
    """Encapsulates the LangGraph-based PubMed research agent."""
    ...
```

---

## Section 7 — Findings Report Format

```markdown
## Blockers (hard rule broken — must fix before merge)

| # | File | Line | Rule | Description |
|---|------|------|------|-------------|
| 1 | src/routers/foo.py | 42 | Router prefix | Missing service namespace; bare /api/v1 |
| 2 | web/src/stores/report.ts | 18 | Ubiquitous language | `maxQuestions` should be `questionLimit` (camelCase of API field) |

## Warnings (soft convention bent — should fix)

| # | File | Line | Rule | Description |
|---|------|------|------|-------------|

## Notes (style drift — worth flagging)

| # | File | Line | Rule | Description |
|---|------|------|------|-------------|
```

---

## Quick Grep Patterns

```bash
# Positional args (2+ params) — potential named-arg violation
grep -rn "def \w\+(self, \w\+, \w\+" src/

# Missing type hints on public methods
grep -rn "def [^_]\w\+(" src/ | grep -v " -> "

# Bare /api/v1 router prefix (missing service namespace)
grep -rn 'prefix="/api/v1"' src/

# Options API in Vue
grep -rn "export default {" web/src/

# Raw EventSource (should be useAgentStream)
grep -rn "new EventSource" web/src/

# DAO field name candidates for mismatch (manual check required)
grep -rn "class .*DAO" src/domains/

# Ubiquitous language synonym candidates (expand this list per project)
grep -rn "max_questions\|question_count\|question_cap\|idempotency_key\|env_id\|profile_id" src/

# invoke() gateway missing on Graph classes
grep -rn "class .*Graph" src/ | grep -v "def invoke"

# Inline styles in Textual widgets
grep -rn "styles=" src/tui/
```
