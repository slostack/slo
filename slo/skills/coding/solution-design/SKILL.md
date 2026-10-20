---
name: solution-design
description: Prepare a self-contained design document before implementation by investigating callers, choosing a deep module and real seam, defining its whole interface, comparing authorized alternatives, and saving design.md, and design complete vertical solutions domain-first.
when_to_use: Use when a coding agent is asked to investigate and design a solution document before implementation, not to implement the solution.
group: coding
kind: skill
---

# Solution Design Before Implementation

## Skill summary

- Investigate actual callers, variation, and ownership before proposing a design.
- Define the complete interface, lifecycle, failure, and testing contract before implementation.
- Compare alternatives only within the user's authorization and preserve unresolved decisions.
- Design complete vertical slices domain-first and present them journey-first; see `## Vertical solution design`.

## Examples

```text
caller → design seam → hidden implementation → observable outcome
```

## Guidance

## Applicability and precedence

This skill is guidance for future design-document work. It is not an implementation
plan to execute automatically, and creating this skill does **not** execute the design
exercise described here. When this skill is invoked, investigate, design, explain, and
save the requested document; do not implement code, write tests, edit wiring, or alter
related documents unless the user separately asks for that work.

Apply repository-specific instructions, applicable language/framework rules, and the
user's explicit constraints first. Use the linked [code design principles](../code-design-principles/SKILL.md)
and [coding rules](../coding-rules/SKILL.md) as design guidance. The repository-relative path `skills/coding/code-design-principles/SKILL.md` is authoritative in this checkout. Repositories that retain an older nested spelling may resolve that legacy path to the same rule family; do not silently replace or drop an explicit user path. More specific project rules override generic guidance on the point they govern; generic obligations remain intact. Preserve user-provided paths exactly. If instructions conflict, identify the conflict and ask for a decision rather than inventing a resolution.

## Inputs and output

Before starting, collect and retain these inputs:

- The problem or request description, or its path.
- The repository path.
- Paths to existing plans.
- Paths to review feedback, or review feedback supplied as text.
- The coding rules at `/root/Code/slo-skills-reorganization/slo/skills/coding/coding-rules/SKILL.md`.
- The skill index, normally `skills/INDEX.md`, and every relevant skill it points to.
- The requested output destination; save the design as `<destination>/design.md`.
- Whether the user says yes or no to exploring alternative interfaces with sub-agents.

Keep all supplied paths in the design's sources section. Resolve a path relative to the
repository only as an additional notation when the original path is ambiguous; show
both forms when needed. Preserve supplied source artifacts, plans, ledgers, and review
notes as named inputs; if an artifact is incomplete or reconstructed, label that
limitation and do not imply byte-for-byte fidelity. Do not overwrite `design.md` or any
related document unless the user explicitly authorizes overwriting it. This skill's own
creation is not permission to run the design exercise.

## Shared vocabulary

Use these terms precisely and do not replace them with `component`, `service`, `API`,
or `boundary` when explaining the design. Preserve existing source identifiers exactly
when citing them.

- **Module**: anything with an interface and an implementation: a function, class,
  package, or slice spanning layers. It need not be a package or deployed application.
- **Interface**: everything a caller must know: types, invariants, ordering, errors,
  required configuration, defaults, side effects, ownership, and performance. The
  operations collectively form **one interface per module**.
- **Implementation**: the hidden code and decisions behind that interface.
- **Depth**: the behaviour callers and tests can exercise for the amount of interface
  they must learn. Assess depth through examples, not lines of code.
- **Seam**: where the interface lives and behaviour can change without editing callers.
  Choose seam placement separately from implementation choice.
- **Adapter**: a concrete thing satisfying an interface at a seam. “Adapter” describes
  its role, not its size or complexity.
- **Leverage**: capability provided by a small interface.
- **Locality**: concentration of knowledge, changes, fixes, and verification rather
  than their distribution across callers.

Use the governing question throughout: **How much useful behaviour can callers and
tests exercise through this interface, and how much change can stay inside its
implementation?**

## 1. Read and verify before designing

Read the request, coding rules, existing plans, review feedback, the skill index, and
relevant skills before recommending a shape. Apply project-specific guidance only where
it governs the work; do not blindly copy unrelated patterns. Inspect the actual callers
and their needs, existing interfaces and seams, duplicated decisions, real variation,
dependency categories, ownership, lifecycle, and failure behaviour. Trace enough code to
know what really varies and where decisions currently live.

Verify every review claim against the repository. Separate the document's observations
into facts, recommendations, assumptions, and unresolved decisions. Do not infer that
an interface exists merely because a similarly named hook or method exists. Cite source
identifiers and paths when they establish a fact, while retaining the shared vocabulary
above in the explanation.

## 2. Choose the module and its seam

Group behaviour that shares knowledge, state, rules, or recovery. Explain:

1. What callers are trying to accomplish.
2. Which knowledge and decisions the module hides.
3. Where the interface belongs and why that is the seam.
4. Which implementation choices remain hidden.
5. What callers are responsible for, including ownership and lifecycle.

Prefer a small interface with sensible defaults and pull unavoidable complexity inward.
Do not create one module per execution step, a mechanical accessor/pass-through layer,
or a parameter that merely defers a decision to callers.

Apply this deletion test verbatim: **“If this module disappeared, would complexity disappear too, or would its work have to be repeated across callers?”** If the answer is
that complexity disappears, reconsider whether the module has value. If its work would
spread, explain the module's leverage and locality. Do not invent a hypothetical
flexibility seam: identify actual variation and actual adapters. One adapter leaves a
seam hypothetical; two adapters make it real. A test adapter must have meaningful
alternative behaviour, not merely satisfy a checkbox.

## 3. Define the whole interface before implementation

State the module's purpose and promises before giving an implementation sketch. For
each module, specify all of the following:

- Essential operations and named input/output types.
- Invariants and ordering guarantees.
- Required configuration and defaults.
- Effects, side effects, and ownership.
- Startup, shutdown, cancellation, and cleanup behaviour.
- Errors and recovery semantics.
- Limits and performance expectations.

Types are necessary but insufficient: pair typed examples with plain-language promises.
Show at least one common caller example and one failure or advanced example. Accept a
dependency only when behaviour varies; do not force unnecessary caller configuration or
dependencies. Prefer returned outcomes over hidden mutation and make effects explicit.

Distinguish the caller/test interface, private internal seams, adapters, and ordinary
implementation details. Do not expose an internal merely to make tests convenient.
Tests should exercise the caller/test interface; if they must reach past it, reconsider
the shape or identify a genuine private seam and explain why it is private.

Short illustrative interfaces may use any language without mandating a framework. Keep
the examples equivalent in intent and supplemental to the prose:

```python
from typing import Protocol

class ReservationStore(Protocol):
    def reserve(self, *, request: ReservationRequest) -> ReservationOutcome: ...
```

```go
type ReservationStore interface {
    Reserve(ctx context.Context, request ReservationRequest) (ReservationOutcome, error)
}
```

```typescript
interface ReservationStore {
  reserve(request: ReservationRequest): Promise<ReservationOutcome>;
}
```

Explain the invariants, ownership, duplicate-request behaviour, cancellation, and error
outcomes around these sketches; do not pretend the signatures alone define the
interface. Do not require Python, Go, TypeScript, or any framework in the design.

## Vertical solution design

- Always design a complete solution involving all the components in the systems.
- For instance if the system contains a
  - frontend, backend, task worker, database, and service
  - And if a feature touches all the components, your solution should be structure as completely deliverable chunks.
  - Designing and executing just the backend is a horizontal chunk and can lead to gaps in the interfaces and seams.
  - Always plan for a full vertical slice of self contained work when relevant.

**Design order:** understand current state and intended outcome → identify
state-owning domains and data contracts → complete workflows, interfaces and
steps → tests → detailed implementation.
**Presentation order:** current state and end-to-end journey first → domains,
workflows/application services and interfaces → implementation and verification.
Do not confuse the order of decisions with the order of explanation.

### Always explain the current state

Explain how the journey works today, which components own state and behavior,
what is missing, incorrect, duplicated or unnecessarily complicated, and what
will be reused, extended, replaced or removed. Cite verified paths and symbols;
separate observations from assumptions. State explicitly when work is greenfield.
Search for existing responsibility owners by behavior, not proposed feature
terminology. Never create a second owner for an existing responsibility; apply
[code design principles](../code-design-principles/SKILL.md).

### First design step: domains and intuitive data structures

A domain is a cohesive responsibility that creates, mutates, manages or publishes
state, identified by its concept and rules, not a table, method or screen.
State includes in-memory buffers/collections/caches; files, persisted records and
configuration; sessions and UI state; queued work, progress, checkpoints and
lifecycle status; messages buffered/flushed to a bus and their delivery outcomes.
Message flushing is an operation of the message-delivery domain, not a domain.

| Item | Required explanation |
|---|---|
| Meaning | What the concept represents |
| Ownership | State and behavior owned, and explicitly not owned |
| Representation | Named, typed data structures |
| Identity and lifetime | Identity and duration |
| Rules | Valid values, relationships, invariants |
| Operations | Creation, mutation, reading, publication, removal |
| Authority | Authoritative, derived, or cached state |

Define named intuitive DTO/DAO structures before bodies; use repository terminology
consistently. No anonymous maps, positional tuples or long unrelated parameter
lists for meaningful boundary data. Data objects carry data; domain services own
behavior (validation and mechanical conversion may live with structures).
For every attribute state name, type, meaning, required/optional, default and
constraints/units. Distinguish absent vs null vs empty when meanings differ.
Separate request/stored-state/result structures when contracts differ, but do not
duplicate identical data under new names. Static types do not validate external
input: name runtime validation boundaries. Standardize meaning and contracts,
not physical layout across languages.

Equivalent boundary data (all attributes required, no defaults; units not applicable):

| Attribute | Type | Required | Meaning / constraint |
|---|---|---|---|
| message_id | String | Yes | Stable delivery correlation identity; non-empty |
| destination | String | Yes | Logical destination; non-empty |
| body | String | Yes | Message content; empty allowed |

```python
class OutboundMessageDAO(BaseModel):
    """One message submitted for delivery."""

    message_id: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    body: str
```

```go
// OutboundMessageDAO carries one message submitted for delivery.
// MessageID and Destination must be non-empty; Body may be empty.
// Validate this contract at the receiving boundary.
type OutboundMessageDAO struct {
    MessageID   string `json:"message_id"`
    Destination string `json:"destination"`
    Body        string `json:"body"`
}
```

```typescript
/** One message submitted for delivery.
 * Validate non-empty messageId and destination at runtime boundaries.
 */
interface OutboundMessageDAO {
  readonly messageId: string
  readonly destination: string
  readonly body: string
}
```

### Identify workflows end to end

A workflow runs from initiating action to observable outcome. Include CLI, API,
controllers/routers, UI, worker tasks, schedules and events as relevant entry
points. Design the complete vertical slice, not disconnected horizontal pieces.

```text
User action
    ↓
UI component → Client state / API client
    ↓
Controller / Router
    ↓
Application service
    ├─ Domain service → Database tables
    ├─ Another application service
    └─ Message-bus adapter → Worker
                                ↓
                         Application service
                                ↓
                         Persisted outcome
                                ↓
                      API / event → UI update
```

Arrows show handoffs toward an observed result. Include only necessary
participants; do not invent a frontend for a CLI-only workflow.
For each workflow describe trigger/input, preconditions/authorization, ordered
operations, state changes and external effects, successful outcome, failure
outcomes/recovery and how the caller observes completion. Cross-service handoffs
must name contracts, ownership, correlation and consistency. An acknowledgement
that work was queued is not journey completion.

### Define interfaces before implementation bodies

Inventory entry-point requests/responses, application-service inputs/results,
domain operations, persistence/external-service boundaries, events/messages/worker
payloads, and frontend state/component contracts where relevant. Document what
each does, who calls it, inputs/outputs, state changes/side effects, errors and
guarantees, and lifetime/ordering/concurrency where relevant. Comments explain
behavior, never merely restate symbol names. Apply the whole-interface checklist
in §3 at every boundary.

```text
PublishMessages.execute(PublishMessagesRequest) → PublishMessagesResult

Caller:
  CLI command or worker task.
Behavior:
  Validate the batch, submit eligible messages, and record delivery outcomes.
Guarantees:
  Return one outcome per submitted message.
  Do not report broker acceptance as downstream processing completion.
Failures:
  Reject invalid input before publication.
  Represent partial publication explicitly in the result.
```

### Application services: one public workflow entry point

Expose one primary execution entry point (`execute`, `invoke`, or the repository's
established equivalent). Internal steps remain private, never exposed publicly:

```text
execute(request)
    1. validate_request
    2. load_required_state
    3. prepare_changes
    4. apply_changes
    5. publish_effects
    6. build_result
```

A step may call a domain-service method, another application service through its
public entry point, an integration adapter or a focused internal calculation.
Unrelated workflows belong in separate application services; no circular calls
or collections of unrelated operations masquerading as one service.
Make transaction boundaries, ordering, retries, idempotency, concurrency and
partial-failure behavior explicit. Database update plus message publication is
never implied atomic unless the proposed mechanism guarantees it.

### Design tests alongside the contracts

| Level | Invocation | Verification |
|---|---|---|
| End-to-end journey | Actual initiating boundary | Complete observable outcome across the vertical |
| Application service | Public execution entry point directly | Coordination, sequencing, results, errors, effects |
| Domain service | Domain operations directly | Invariants, transitions, persistence behavior |
| Focused unit test | Individual methods where relevant | Non-trivial calculations and isolated decisions |
| Boundary / contract test | API, message, storage, or UI boundary | Validation, serialization, interoperability |

```text
Journey test:             Entry point ──────────────→ Observable outcome
Application-service test:       Workflow execution → Result and effects
Domain-service test:                State operation → Rules and transitions
Focused method test:                   Calculation → Specific behavior
```

Arrows show the scope each test proves. Specify setup, invocation and observable
assertions, including meaningful failures. A mock-only application-service test
does not replace a full-journey test. For asynchronous work verify the eventual outcome,
not task submission. Avoid private implementation coupling unless the
method contains independently significant behavior.

### Present specifications top down; implementation details last

1. Current state.
2. Intended end-to-end journey.
3. Solution diagram (participants and handoffs).
4. Domains and data contracts.
5. Workflows/application services.
6. Interfaces.
7. Implementation details (files, symbols, migrations, wiring, compatibility, rollout).
8. Tests and acceptance criteria.

Introduce concepts in prose before code. This ordering governs explanation inside
design content; it integrates with, never replaces, the document contract in §5
or the repository's [feature-specification family](../../design-and-analysis/feature-specifications/SKILL.md).

Describe database changes as migrations, not only a desired final schema: tables,
columns, constraints and indexes added/changed; backfill; nullability/defaults;
deployment compatibility and ordering; rollback/recovery limitations.
Python uses SQLAlchemy schema declarations accompanied by explicit migration
operations. Go and TypeScript use pure SQL migration definitions even when
runtime code uses an ORM or query builder.

```python
delivery_messages = sa.Table(
    "delivery_messages",
    metadata,
    sa.Column("message_id", sa.String(64), primary_key=True),
    sa.Column("destination", sa.Text(), nullable=False),
    sa.Column("body", sa.Text(), nullable=False),
)
```

```sql
CREATE TABLE delivery_messages (
    message_id VARCHAR(64) PRIMARY KEY,
    destination TEXT NOT NULL,
    body TEXT NOT NULL
);
```

These equivalent declarations alone are not a migration plan. For a new empty
table, specify the create operation before deploying writers and removal only
when no dependent reader/writer remains. Existing rows require an explicit
backfill and constraint-validation sequence. State where validation constraints
are enforced: boundary validation rejects empty identity/destination; storage
limits message_id to 64 characters, so the boundary must enforce that limit too.
Keep schema and boundary contracts compatible; document any destructive rollback.

### Keep the result readable and concise

Use simple language, outcome first rather than a file catalog, short paragraphs,
contract tables and focused examples. Use one overview diagram; add sequence or
state diagrams only when they clarify behavior. Explain decisions and guarantees,
not generic architecture lectures. Do not repeat contracts across sections.
Mark irrelevant concerns "not applicable" instead of inventing components.
Add detail where ambiguity would force guessing, not to lengthen the document.

**Design completion rule:** a reader can follow the whole journey, identify the
owner of every state change, understand each boundary contract, and see which
tests prove the outcome.

## 4. Design it twice only with explicit consent

Explore alternatives with sub-agents **only when the user explicitly requests
alternative interfaces and explicitly authorizes sub-agents**. The input “explore
alternative interfaces with sub-agents: yes/no” is a consent condition, not a default.
This request creates a reusable skill and does not authorize or execute its own design
exercise.

When both permissions are present, first show the chosen module/problem, constraints,
known dependency categories, and a small illustrative **non-recommendation** code
sketch. Then dispatch at least three parallel agents. Give every brief the exact
repository, plan, review, and other input paths; verified coupling; known dependency
categories; behaviour to hide; and the vocabulary/project glossary from this skill.
Ask each agent to use a materially different constraint:

- Minimal interface: one to three entrypoints with high leverage.
- Maximum useful flexibility across actual callers.
- Trivial common caller.
- Optional dependency adapters (use this as an additional lens when relevant).

The alternatives must be radically different interfaces, not the same design with
renamed methods. Each agent must return the whole interface: invariants and ordering,
errors, a caller example, hidden implementation, dependencies and adapters, and the
trade-offs in leverage, locality, and seam placement. Present and compare the results,
then recommend one or justify a combination. Never concatenate every proposal into an
oversized interface.

Without explicit sub-agent permission, compare plausible alternatives yourself and say
that the comparison was not an independent sub-agent review. Preserve these consent
conditions exactly; do not imply independent review that did not occur.

## 5. Write the concise design document

Write approximately 1000–1500 words unless the user asks otherwise. Use the exact
requested destination and produce `<destination>/design.md`. Begin with a title in this
form:

```text
# <Problem>: <plain-language approach>
```

Immediately state status (`proposed`, `approved`, or `implemented`), sources, linked
inputs, and how this design refines any earlier plan. The document must contain these
sections, in order:

1. **Approach** — problem, recommendation, benefit, a one-sentence summary, and a
   small system diagram.
2. **Modules and seams** — a table with module, interface/callers, hidden
   implementation, leverage, and locality.
3. **Caller use** — compact examples, promises, ownership, lifecycle, and failure.
4. **Existing code changes** — reused modules, changed interfaces, new adapters,
   implementation changes, and the strongest alternative comparison.
5. **Main journeys** — two or three user-visible journeys with short sequence or
   decision diagrams.
6. **Tests, limits, and next steps** — interface behaviour tests, unresolved decisions,
   and a short delivery order.

End with a clear takeaway. Use plain prose to define terms. Fenced text diagrams must
be fewer than 20 lines, use the same vocabulary as the document, and explain their
arrows. Include facts, recommendations, assumptions, unresolved decisions, and source
links without pretending that design approval or implementation has happened.

When the design covers a full vertical slice, apply the presentation order in
`## Vertical solution design`: its sections refine this document's Approach,
Modules and seams, and Main journeys rather than replacing this contract.

## 6. Verification before saving and reporting

Before saving, check all of the following:

- Current state is explained with verified paths before proposed changes.
- Every state change has an identified owning domain.
- Interfaces and their behavioral documentation precede implementation bodies.
- Each application service exposes one primary public execution entry point.
- Journey, application-service, domain, focused, and boundary tests are identified with setup and assertions.
- Database changes are described as migrations.

- The interface hides meaningful complexity and the governing question has been answered.
- Depth is demonstrated with behaviour examples, not LOC.
- Each important decision has one owner.
- The design is based on actual variation, not hypothetical flexibility.
- Callers and tests use the same public interface.
- Internal changes can remain inside the implementation without editing callers.
- Startup, shutdown, cancellation, cleanup, ownership, and failure/recovery are complete.
- The deletion test is present verbatim.
- Assumptions and unresolved decisions are visible.
- All links resolve, including the two design-rule links.
- Tests verify results, effects, failures, and cleanup through the interface.
- Any test that reaches past the interface triggers reconsideration, or is justified as a
  genuine private seam.
- The output is saved at the requested destination and related documents were not
  overwritten.

Report the exact saved path and a short summary of the design. Report verification
checks and any unresolved decision. Do not claim implementation, approval, independent
review, or test execution merely because a design document was saved.
