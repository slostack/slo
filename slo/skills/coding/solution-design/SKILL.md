---
name: solution-design
description: Prepare a self-contained design document before implementation by investigating callers, choosing a deep module and real seam, defining its whole interface, comparing authorized alternatives, and saving design.md.
when_to_use: Use when a coding agent is asked to investigate and design a solution document before implementation, not to implement the solution.
group: coding
kind: skill
---

# Solution Design Before Implementation

## Skill summary

- Investigate actual callers, variation, and ownership before proposing a design.
- Define the complete interface, lifecycle, failure, and testing contract before implementation.
- Compare alternatives only within the user's authorization and preserve unresolved decisions.

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

## 6. Verification before saving and reporting

Before saving, check all of the following:

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
