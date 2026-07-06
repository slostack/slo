---
name: ubiquitous-language
description: 'Cross-layer naming rule: one concept, one canonical name across CLI,
  services, DAOs, APIs, and frontend code.'
when_to_use: Use when introducing, renaming, or reviewing domain terms that flow across
  more than one layer.
group: design-and-analysis
kind: skill
source_prompt: ubiquitous-language.md
---

# Ubiquitous Language

## Skill summary

- **Name:** `ubiquitous-language`
- **Description:** Cross-layer naming rule: one concept, one canonical name across CLI, services, DAOs, APIs, and frontend code.
- **When to use:** Use when introducing, renaming, or reviewing domain terms that flow across more than one layer.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `ubiquitous-language.md`

## Examples

- The user asks: "Rename this concept across the API, DAO, and Vue store."
- You are reviewing a diff with several synonyms for the same concept and need the naming rule that breaks the tie.

## Guidance

**This is a project-wide rule.** It governs every layer of the
Orders platform monorepo — application services, domain services, DAOs,
SQLAlchemy models, FastAPI routers, HTTP request/response bodies,
database columns, Vue components, Pinia stores, TypeScript props, and
test fixtures. The Makefile → CLI example that follows is the most
visible and most auditable instance of the principle; it is not the
only place it applies.

Names drift. The Makefile operator types `GRADE=hard,medium N=4`, but
by the time those values reach a Python service class they can become
`question_count`, `difficulty_filter`, or `max_q` — whatever the next
developer guessed at. Each synonym is a latent bug: the developer after
that cannot tell whether two names refer to the same concept or to
genuinely different things. The same drift happens between an
Application Service and the DAO it writes to, between a router and
the service it delegates to, between a model column and the DAO field
that mirrors it, and between the API JSON field and the Vue store key
that stores it.

**The mandatory answer: every domain concept has exactly one canonical
English phrase. That phrase is adapted to each layer's naming idiom,
but the semantic root never changes.**

---

## Cross-references

- CLI construction rules → `skills/cli/build-cli-commands/SKILL.md`
- CLI module layout rules → `skills/cli/build-cli-modules/SKILL.md`
- Type hints and named args → `skills/coding/named-arguments-and-type-hints/SKILL.md`
- Declarative structure → `skills/coding/declarative-method-structure/SKILL.md`

---

## 1. Example: `make verify-flow` End-to-End Mapping

The `verifier` service's `make verify-flow` entry point is the
reference implementation of this convention. Every concept introduced
at the Make level must flow — unchanged in meaning, adapted in form —
through every downstream layer. **Every other cross-layer concept in
the project must have an equally traceable mapping.**

**Current canonical mapping for `make verify-flow`:**

| Make variable | Env var (exported by Makefile) | Typer flag | Python attribute / API field |
|---|---|---|---|
| `ENV=local` | `ENV` | `--env` | `env` |
| `N=4` | `QUESTION_LIMIT` | `--question-limit` / `--n` | `question_limit` |
| `GRADE=hard,medium` | `QUESTION_DIFFICULTIES` | `--question-difficulty` | `question_difficulties` |
| `BASELINES=true` | `INCLUDE_BASELINES` | `--baselines/--no-baselines` | `include_baselines` |
| `ENV_PROFILE_ID=<uuid>` | `VERIFIER_ENV_PROFILE_ID` | `--env-profile-id` | `env_profile_id` |
| `ENV_PROFILE_NAME=<str>` | `VERIFIER_ENV_PROFILE_NAME` | `--env-profile-name` | `env_profile_name` |
| `DRY_RUN=true` | `VERIFIER_DRY_RUN` | `--dry-run/--no-dry-run` | `dry_run` |

This table is authoritative for the CLI path. Every file that touches
these concepts must derive its names from it. The same authority
applies to every concept that does not pass through the CLI: its
canonical name must be traceable from the layer where it is first
introduced all the way to the layer where it is consumed or persisted.

**Why the translation exists:** Make idioms favor terse uppercase vars
(`N`, `GRADE`); env vars use descriptive screaming-snake
(`QUESTION_LIMIT`); Typer flags use kebab-case (`--question-limit`);
Python uses snake_case (`question_limit`). The form changes per layer;
the root semantic concept does not. `N=4` is operator shorthand.
`QUESTION_LIMIT`, `--question-limit`, and `question_limit` all mean
exactly the same thing: the cap on how many questions fan out.

---

## 2. Layer-Specific Naming Idioms

The full layer stack for the Orders platform monorepo:

| Layer | Idiom | Examples |
|---|---|---|
| Make variable | `SCREAMING_SNAKE` — terse, operator-friendly | `N`, `GRADE`, `BASELINES`, `DRY_RUN` |
| Env var exported by Makefile | `SCREAMING_SNAKE` — descriptive, full phrase | `QUESTION_LIMIT`, `QUESTION_DIFFICULTIES`, `INCLUDE_BASELINES`, `VERIFIER_DRY_RUN` |
| Typer flag | `--kebab-case` — full descriptive | `--question-limit`, `--question-difficulty`, `--baselines/--no-baselines` |
| Python function/method parameter | `snake_case` — full descriptive | `question_limit`, `question_difficulties`, `include_baselines` |
| Application Service attribute | `snake_case` — identical to the parameter that was passed in | `self.question_limit`, `self.correlation_id` |
| Domain Service method name | `snake_case` verb phrase matching the DAO it writes to | `create_verification_run`, `update_status` |
| DAO field | `snake_case` — identical to the model column it maps | `question_limit`, `correlation_id`, `environment_profile_id` |
| SQLAlchemy model column | `snake_case` — same as DAO field, no aliasing | `question_limit`, `correlation_id`, `environment_profile_id` |
| HTTP API request/response field | `snake_case` — same as Python attribute and DAO field | `question_limit`, `correlation_id`, `run_id` |
| Database column | `snake_case` — same as model column | `question_limit`, `correlation_id` |
| Vue/TypeScript component prop | `camelCase` derivation of the snake_case API field | `questionLimit`, `correlationId`, `runId` |
| Pinia store key | `camelCase` — same derivation as the prop | `questionLimit`, `correlationId` |
| Test fixture parameter | `snake_case` — identical to the production parameter it stands in for | `question_limit=10`, `correlation_id="abc"` |
| Test assertion key | matches the field name in the subject under test — no shorthand | `result["question_limit"]`, `run.correlation_id` |

**Rule:** If the canonical phrase is "question limit", the env var is
`QUESTION_LIMIT`, the flag is `--question-limit`, the Python name is
`question_limit`, the DAO field is `question_limit`, the model column
is `question_limit`, the JSON field is `question_limit`, the database
column is `question_limit`, and the Vue store key is `questionLimit`.
There is no step that allows `max_questions`, `question_count`,
`limit`, or any other synonym.

---

## 3. Project-Wide Naming Consistency

The Makefile example is the most auditable cross-layer trace in the
project, but the same principle applies everywhere a concept crosses a
layer boundary. This section names the non-CLI violations that are
most common and most damaging.

### 3.1 Application Services → DAOs → Routers

The name used in an Application Service's `__init__` must match the
name used in the DAO it writes to, and the name used in the router
that calls the service. No silent renaming anywhere in the chain.

**Bad:**

```python
# router: invents "idempotency_key"
body: TriggerRunRequestDAO
service = VerificationRunTriggerAppService(
    idempotency_key=body.correlation_id,   # wrong name at the call site
    ...
)

# Application Service: stores it under a different name
class VerificationRunTriggerAppService:
    def __init__(self, *, request_key: str, ...) -> None:
        self.request_key = request_key     # third name for the same concept
```

**Good:**

```python
# router: passes the canonical name through unchanged
service = VerificationRunTriggerAppService(
    correlation_id=body.correlation_id,    # canonical name
    ...
)

# Application Service: stores the canonical name
class VerificationRunTriggerAppService:
    def __init__(self, *, correlation_id: str | None, ...) -> None:
        self.correlation_id = correlation_id
```

### 3.2 Domain Services → DAOs → Model Columns

Domain Service method parameters must match the DAO they write to, and
DAO fields must have identical names to the SQLAlchemy model columns
they map.

**Bad:**

```python
# domain service: uses "limit" as a parameter name
@staticmethod
async def create(limit: int, ...) -> VerificationRun:
    run = VerificationRun(question_cap=limit, ...)  # wrong column name

# DAO: uses yet another name
class VerificationRunDAO(BaseModel):
    max_questions: int   # does not match the column
```

**Good:**

```python
# domain service: uses the canonical name throughout
@staticmethod
async def create(
    verification_run_dao: VerificationRunDAO,
    db_session: AsyncSession,
) -> VerificationRun:
    run = VerificationRun(**verification_run_dao.model_dump())  # column names match DAO names

# DAO: field names are identical to model column names
class VerificationRunDAO(BaseModel):
    question_limit: Optional[int] = None    # matches VerificationRun.question_limit
    correlation_id: Optional[str] = None    # matches VerificationRun.correlation_id
```

The verifier's existing `VerificationRunDAO` and `VerificationRun`
model are the reference implementation: every DAO field name is
identical to the SQLAlchemy column name. This is not accidental — it
is the rule.

### 3.3 Routers → Application Services

Router request/response field names must match the Application Service
they delegate to. The router body must not rename fields when passing
them to the service.

**Bad:**

```python
# router: renames fields silently
@router.post("/verification/runs")
async def trigger_verification_run(request: Request, body: TriggerRunRequestDAO):
    service = VerificationRunTriggerAppService(
        env_id=body.environment_profile_id,   # renamed
        n=body.question_limit,                 # shortened
        grade=body.question_difficulties,      # shortened
        ...
    )
```

**Good:**

```python
# router: passes canonical names unchanged
@router.post("/verification/runs")
async def trigger_verification_run(request: Request, body: TriggerRunRequestDAO):
    service = VerificationRunTriggerAppService(
        environment_profile_id=body.environment_profile_id,
        question_limit=body.question_limit,
        question_difficulties=body.question_difficulties,
        correlation_id=body.correlation_id,
        ...
    )
```

### 3.4 Models → DAOs: No Aliasing

Every `Column` (or `mapped_column`) in a SQLAlchemy model must have a
matching field in the corresponding DAO with the **identical** Python
attribute name. No aliasing. No renaming.

**Bad:**

```python
# model
class VerificationRun(Base):
    question_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

# DAO
class VerificationRunDAO(BaseModel):
    max_questions: Optional[int] = None   # wrong — does not match the column
```

**Good:**

```python
# model
class VerificationRun(Base):
    question_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

# DAO
class VerificationRunDAO(BaseModel):
    question_limit: Optional[int] = None  # identical to the column name
```

### 3.5 Tests: Fixture Parameters and Assertion Keys

Test fixture parameter names must match the production code parameters
they stand in for. Tests are documentation; if a test builds a
`VerificationRunDAO` with `n=10`, the reader cannot tell whether `n`
is the real name or a shortcut.

**Bad:**

```python
dao = VerificationRunDAO(
    n=10,                            # not the canonical name
    grade=["hard"],                  # not the canonical name
    env=uuid4(),                     # not the canonical name
)
assert result["count"] == 10        # "count" is not the field name
```

**Good:**

```python
dao = VerificationRunDAO(
    question_limit=10,               # canonical
    question_difficulties=["hard"],  # canonical
    environment_profile_id=uuid4(),  # canonical
)
assert result["question_limit"] == 10  # matches the actual DAO/model field
```

### 3.6 Frontend: Vue/TypeScript camelCase Derivation

When the API returns a snake_case field, the Vue component, Pinia
store key, and template variable must all use the exact camelCase
derivation of that snake_case name. No synonyms, no creative
renamings.

**Bad:**

```typescript
// API returns { question_limit: 10, correlation_id: "abc", run_id: "xyz" }

// store.ts: invents new names
const maxQuestions = ref<number>(0)   // wrong — should be questionLimit
const idempotencyKey = ref<string>('') // wrong — should be correlationId
const verificationRunId = ref<string>('') // wrong — should be runId

// Component.vue: uses yet another variant
defineProps<{ limit: number }>()   // wrong
```

**Good:**

```typescript
// store.ts: camelCase derivation of the API field name
const questionLimit = ref<number>(0)    // snake: question_limit
const correlationId = ref<string>('')   // snake: correlation_id
const runId = ref<string>('')           // snake: run_id

// Component.vue: prop name mirrors the store key
defineProps<{
  questionLimit: number   // camelCase derivation of question_limit
  correlationId: string
  runId: string
}>()
```

The derivation rule is mechanical: `snake_case` → `camelCase`.
`question_limit` → `questionLimit`. `correlation_id` → `correlationId`.
No exceptions. No creative synonyms.

---

## 4. The Makefile Is the Vocabulary Authority for Operator-Facing Concepts

**Why:** The Makefile is the operator-facing surface. It is the first
place a human types the concept name. Whatever that name is defines
the semantic concept for the CLI path. All downstream layers derive
from it.

**Rule:** New operator-facing concepts must be named at the Makefile
level first. Open the relevant Makefile, add the `make` target
variable, document it in the help block, and only then propagate the
name through the remaining layers.

For backend-only concepts not exposed through the CLI (e.g., a new
domain model field), name the concept in the SQLAlchemy model column
definition first, then derive the DAO field name and all downstream
uses from that.

**How to apply:** When asked to add a new parameter to `make verify-flow`:

1. Add the Make variable to the `verify-flow` recipe and its comment
   block in the Makefile.
2. Decide on the descriptive env-var name (expand terse Make
   shorthands: `N` → `QUESTION_LIMIT`).
3. Export it in the Makefile recipe: `DESCRIPTIVE_NAME=$(TERSE_VAR)`.
4. Add the Typer flag in `cli/verify_run.py` using the kebab-case
   derivation.
5. Add the translation in `cli/verify_flow_dispatch.py`'s
   `_build_swarm_argv` (for swarm mode) and confirm the bash script
   reads the env var directly (for dev mode).
6. Use the snake_case attribute name throughout every Python class
   that holds the value.
7. Use the snake_case field name in the HTTP API body, the DAO, the
   model column, and the database column.
8. Use the camelCase derivation in Vue store keys, component props, and
   template variables.

---

## 5. Translation Layers Must Be Explicit and Centralized

Every name transformation — Make var → env var → Typer flag → Python
attribute — lives in ONE dispatcher file per CLI entry point. For
`make verify-flow` that file is `cli/verify_flow_dispatch.py`. No
other file performs this translation.

### Bad: Silent ad-hoc remapping scattered through the codebase

```python
# services/verification_trigger.py — a new developer invents a synonym
class VerificationTriggerService:
    def __init__(self, max_questions: int, difficulties: list[str]) -> None:
        # "max_questions" is not in the canonical mapping table.
        # "difficulties" drops the "question_" prefix — now ambiguous.
        self.max_questions = max_questions
        self.difficulties = difficulties
```

```python
# routers/verification_runs_router.py — the router introduces yet another synonym
@router.post("/verify-flow")
async def trigger_run(
    question_count: int = Query(default=10),  # third name for the same concept
):
```

Now there are three words for one concept — `N`, `question_limit`, and
`max_questions` / `question_count` — and a new developer cannot tell
whether they refer to the same concept or to different subtleties.

### Good: All translation in the dispatcher; all downstream layers use the canonical name

```python
# cli/verify_flow_dispatch.py — the ONLY place that translates Make → Typer
def _question_limit_flag(*, env_dict: dict[str, str]) -> list[str]:
    """Translate ``QUESTION_LIMIT`` (``N=`` Make var) to ``--n <int>``."""
    value: str = env_dict.get("QUESTION_LIMIT", "").strip()
    if not value:
        return []
    return ["--n", value]
```

```python
# cli/verify_run.py — uses the canonical Typer flag name; Python attribute is canonical too
question_limit: Annotated[
    int,
    typer.Option("--question-limit", "--n", min=1, max=200),
] = 10
```

```python
# services/verification_trigger.py — downstream Python uses the canonical snake_case name
class VerificationTriggerService:
    def __init__(
        self,
        *,
        question_limit: int,         # canonical — matches all other layers
        question_difficulties: list[str],  # canonical
        include_baselines: bool,     # canonical
    ) -> None:
```

```python
# routers/verification_runs_router.py — API field uses canonical snake_case
class VerifyFlowRequest(BaseModel):
    question_limit: int = Field(default=10, ge=1, le=200)
    question_difficulties: list[str] = Field(default_factory=list)
    include_baselines: bool = Field(default=False)
```

---

## 6. Cross-Layer Violation Examples (Verifier Codebase)

These are the concrete Bad/Good pairs for the most common
cross-layer violations in the verifier.

### 6.1 — `correlation_id` must not become `idempotency_key` or `request_key`

**Bad:** Three names for the same idempotency concept:

```python
# CLI Typer flag: --correlation-id → Python attribute: correlation_id  ✓
# TriggerRunRequestDAO field: correlation_id                           ✓

# Application Service: renames it on the way in
class VerificationRunTriggerAppService:
    def __init__(self, *, idempotency_key: str | None, ...) -> None:
        self.request_key = idempotency_key   # two renames in two lines
```

**Good:** One name through every layer:

```python
# Typer flag: --correlation-id
# TriggerRunRequestDAO.correlation_id
# VerificationRunTriggerAppService.__init__(*, correlation_id: str | None)
# self.correlation_id = correlation_id
# VerificationRunDAO.correlation_id
# VerificationRun.correlation_id (model column)
# API response: {"correlation_id": "..."}
# Vue store: correlationId
```

### 6.2 — `question_limit` must not become `max_questions`, `n`, or `question_cap`

**Bad:**

```python
# Make: N=4
# CLI: --question-limit / --n → question_limit  ✓
# Router body: renames it
service = VerificationRunTriggerAppService(
    max_questions=body.question_limit,   # wrong
)
# Application Service attr: self.n = max_questions   # wrong
# DAO field: question_cap                             # wrong
# Model column: question_cap                          # wrong
```

**Good:** The canonical mapping table (Section 1) is the proof. Every
layer uses `question_limit`:

```
N=4 → QUESTION_LIMIT → --question-limit / --n → question_limit
  (CLI attr) → question_limit (service attr) → question_limit
  (DAO field) → question_limit (model column) → question_limit (DB column)
```

### 6.3 — `environment_profile_id` must not be shortened to `env_id` or `profile_id`

**Bad:**

```python
service = VerificationRunTriggerAppService(
    env_id=body.environment_profile_id,  # dropped the qualifier
)
```

**Good:**

```python
service = VerificationRunTriggerAppService(
    environment_profile_id=body.environment_profile_id,  # full canonical name
)
```

### 6.4 — `run_id` in the API response must stay `runId` in Vue, not `verificationRunId`

**Bad:**

```typescript
// API returns { run_id: "abc123" }
// Vue store:
const verificationRunId = ref<string>('')   // expanded the name unnecessarily
// Component prop:
defineProps<{ runId: string }>()            // inconsistent with the store key
```

**Good:**

```typescript
// API returns { run_id: "abc123" }
// Vue store:
const runId = ref<string>('')   // camelCase derivation of run_id
// Component prop:
defineProps<{ runId: string }>()   // same camelCase derivation
```

---

## 7. The Dispatcher's Module Docstring Must Contain the Full Mapping

Any file that performs name translations between layers **must**
contain a mapping table in its module docstring or an explicit comment
block. This is not optional documentation — it is the navigational
index that lets a reader trace any concept through all layers without
grepping the entire codebase.

### Bad: No table, implicit mapping

```python
"""Dispatch entry point for make verify-flow."""

def _build_swarm_argv(env: str, env_dict: dict) -> list[str]:
    argv = [...]
    if env_dict.get("QUESTION_LIMIT"):
        argv.extend(["--n", env_dict["QUESTION_LIMIT"]])
    if env_dict.get("QUESTION_DIFFICULTIES"):
        # ... no comment explaining where QUESTION_DIFFICULTIES comes from
```

### Good: Explicit mapping table in the docstring

```python
"""Dispatch entry point for ``make verify-flow ENV=<env>``.

Name mapping — Make var → env var → Typer flag → Python attribute:

  N=<int>              → QUESTION_LIMIT         → --n / --question-limit → question_limit
  GRADE=<list>         → QUESTION_DIFFICULTIES   → --question-difficulty  → question_difficulties
  BASELINES=true       → INCLUDE_BASELINES       → --baselines            → include_baselines
  ENV_PROFILE_ID=<uuid>→ VERIFIER_ENV_PROFILE_ID → --env-profile-id       → env_profile_id
  DRY_RUN=true         → VERIFIER_DRY_RUN        → --dry-run              → dry_run

The operator never types Typer flag names. The bash runner reads env vars
natively; the swarm runner has them translated here into matching flags.
"""
```

---

## 8. Concept Registration Pattern

Every new domain concept should be registered as a named constant or
comment at the top of the domain's `dao.py` file. This is the
canonical home for the concept's English phrase and its allowed values
(where applicable).

**Example from `verifier/src/domains/verification_run/dao.py`:**

```python
"""Pydantic DAO + status constants for verification_runs."""

STATUS_QUEUED: str = "QUEUED"
STATUS_RUNNING: str = "RUNNING"
STATUS_COMPLETED: str = "COMPLETED"
STATUS_FAILED: str = "FAILED"
STATUS_CANCELLED: str = "CANCELLED"

DIFFICULTY_EASY: str = "easy"
DIFFICULTY_MEDIUM: str = "medium"
DIFFICULTY_HARD: str = "hard"
DIFFICULTIES: tuple[str, ...] = (DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD)
```

These constants are then imported by every other file that references
the concept — router request DAOs, application services, Alembic
migrations, test factories. This ensures the vocabulary is defined
once and derived everywhere.

**What to register:**

- Status enum values for a domain entity
- Allowed values for filter fields (`DIFFICULTIES`, `TRIGGER_MODES`)
- Canonical string literals that appear in multiple layers

**What not to register here:** runtime config values, per-request data,
anything that changes at runtime.

---

## 9. New Concepts: Trace Through All Layers in the Same PR

When you introduce a new concept, you **must** deliver the complete
trace in the same PR. The layers that apply depend on whether the
concept is CLI-facing, API-only, or backend-only:

**For a CLI-facing concept (new `make verify-flow` parameter):**

1. Make variable (with help-block documentation)
2. Env var name exported by the Makefile recipe
3. Typer flag in the CLI command
4. Translation function in the dispatcher
5. Python attribute in every Command class and service that receives the value
6. HTTP API request/response field (if the value reaches the API)
7. DAO field (if the value is stored)
8. SQLAlchemy model column (if the value is persisted)
9. Database column name
10. Vue store key and component prop (if the value reaches the frontend)
11. Update to the dispatcher's mapping table docstring
12. Update to this file's canonical mapping table (Section 1)

**For a backend-only domain concept (new model field):**

1. SQLAlchemy model column (the vocabulary authority for backend-only concepts)
2. DAO field with the identical name
3. Domain Service method parameter with the identical name
4. Application Service attribute with the identical name
5. HTTP API response field with the identical name (if exposed)
6. Vue store key and component prop (if the concept reaches the frontend)
7. Test fixture parameter with the identical name
8. Register in the domain's `dao.py` top-level constants if the concept has enumerated values

**A PR that adds a field to the model but leaves a different name in
the DAO, or uses a third name in the Application Service, is not
complete — it is a bug waiting to happen.** The reviewer must reject it
until the complete trace is present.

---

## 10. Prohibited Patterns

These are naming violations this convention explicitly bans.

### 10.1 — Synonyms for the Same Concept

```python
# Bad: three names for "the number of questions to fan out over"
max_questions: int       # invented downstream
question_count: int      # invented in a router
limit: int               # invented in a service

# Good: one name, used everywhere
question_limit: int
```

### 10.2 — Dropping the Qualifier Prefix

```python
# Bad: "difficulties" is ambiguous — whose difficulties? of what?
difficulties: list[str]

# Good: the qualifier makes the concept unambiguous
question_difficulties: list[str]
```

### 10.3 — Abbreviations That Break the Chain

```python
# Bad: "n" in a Python class loses the explicit meaning
self.n: int = question_limit   # n means nothing without context

# Good: keep the canonical name
self.question_limit: int = question_limit
```

The `--n` Typer flag alias exists as a convenience shortcut for the
operator. It does not license using `n` as a Python attribute name
anywhere in the codebase.

### 10.4 — Inventing a New Make Variable Without Updating the Mapping Table

```
Bad: the Makefile gets a new variable but the dispatcher's docstring
and this file's Section 1 table are not updated.
The next developer cannot find the canonical mapping.
```

### 10.5 — Performing Translation Outside the Dispatcher

```python
# Bad: a service class silently remaps the incoming name
class VerificationRunTriggerAppService:
    async def invoke(self) -> VerificationRunDAO:
        payload = {
            "max_questions": self.question_limit,  # renames on the way to the API body
            "grade_filter": self.question_difficulties,  # renames again
        }
```

All translation happens in one dispatcher file. Downstream code passes
the canonical name end-to-end.

### 10.6 — DAO Field Name Differs from Model Column Name

```python
# Bad: the DAO aliases the column with a different name
class VerificationRunDAO(BaseModel):
    max_questions: Optional[int] = None   # column is question_limit

# Good: field name is identical to the column name
class VerificationRunDAO(BaseModel):
    question_limit: Optional[int] = None
```

### 10.7 — Vue Store Key Does Not Derive from the API Field Name

```typescript
// Bad: API sends "question_limit", store uses "maxQuestions"
const maxQuestions = ref<number>(0)

// Good: camelCase derivation of "question_limit"
const questionLimit = ref<number>(0)
```

### 10.8 — Test Shorthand Names

```python
# Bad: test fixture uses shorthand that doesn't match production code
dao = VerificationRunDAO(n=10, grade=["hard"])

# Good: test fixture uses the canonical production names
dao = VerificationRunDAO(question_limit=10, question_difficulties=["hard"])
```

### 10.9 — The `flow` / `_flow_async` Naming Asymmetry

The Typer command `flow` is registered with `@app.command()`. Its
async body is `_flow_async`. The Make target is `verify-flow`. The
module is `cli.verify_run`. This naming already deviates slightly from
a pure derivation, and it has caused confusion: a developer looking
for "verify_flow" in Python will not find the Typer command. The
convention is:

- The Typer command function's name must match the verb used in the
  make target when that verb is a single word. `verify-flow` → `flow`
  is acceptable because the module name is already `verify_run` and
  the verb `flow` is unambiguous in context.
- The async body must be named `_<verb>_async` to make the delegation
  visible. `_flow_async` is correct.
- Do NOT name the async body the same as the Typer command (`flow`) —
  that collapses two distinct functions into one name and makes the
  delegation invisible.

---

## 11. When You Encounter a Name You Don't Recognize

If you see a name in the code — `max_questions`, `grade_filter`,
`difficulty_level` — and it does not appear in the canonical mapping
table for its layer, you have found either:

1. A violation of this convention that must be corrected, or
2. A genuinely new concept that has not been registered yet.

**Do not guess.** Do not treat the mystery name as correct. Open the
mapping table, the domain's `dao.py` constants, and the dispatcher,
and determine which case it is. If it is a violation, correct it. If
it is a new concept, register it and trace it through all layers before
merging.

---

## 12. Before-Merge Checklist

Walk through this checklist when adding any new concept to any layer.

### CLI path
- [ ] The new concept is named at the Makefile level first, with
      documentation in the Make target's comment block and the `help` target.
- [ ] The Makefile exports a descriptive env var derived from the Make
      variable (terse shorthands expanded: `N` → `QUESTION_LIMIT`).
- [ ] The Typer flag uses kebab-case derived from the canonical phrase.
- [ ] The dispatcher's translation function reads the env var and
      produces the Typer flag — in `_build_swarm_argv` for swarm mode;
      the bash script reads the env var natively for dev mode.
- [ ] The dispatcher's module docstring mapping table is updated.
- [ ] Section 1 of this file is updated with the new row.

### All paths (CLI, API, backend-only)
- [ ] Every Python layer — router, application service, domain service,
      DAO, model — uses the **same** field/attribute name for this concept.
- [ ] The DAO field name is identical to the SQLAlchemy model column name.
      No aliasing.
- [ ] The HTTP API request/response field name matches the Application
      Service attribute and the DAO field.
- [ ] The Vue store key is the exact camelCase derivation of the
      snake_case API field name.
- [ ] Every Vue component prop and template variable uses the same
      camelCase derivation.
- [ ] Every test fixture parameter uses the canonical production name —
      no shorthands, no invented synonyms.
- [ ] Every test assertion key matches the actual field name in the
      subject under test.
- [ ] If the concept has enumerated allowed values, they are registered
      as named constants at the top of the domain's `dao.py`.
- [ ] No synonym exists anywhere in the PR diff — search for all
      plausible alternatives before declaring done.

---

## 13. Summary: The Single Rule

**One concept, one canonical English phrase. Every layer derives its
name from that phrase mechanically. No layer invents a synonym.
Translation between idioms (screaming-snake → kebab-case → snake_case
→ camelCase) is the only permitted transformation. Translation between
layers is centralized in the dispatcher for CLI concepts; for all
other concepts, the first layer where a concept is introduced is the
vocabulary authority.**

If every developer working on this codebase follows this rule, a
concept introduced at any layer can be traced to any other layer — and
back — by applying a single, deterministic naming transformation. That
is the goal.
