# Slo coding conventions

This is the project-wide coding convention owner, not an implementation or acceptance
report. Source assessment and follow-up priorities are recorded in
[the assessment](../../specifications/projects/slo/specifications/101-slo-claude-bridge/refactor/01-refactor.md). Existing governing skills remain binding; source examples demonstrate
specific contracts, not blanket compliance of their files.

## 1. Authority and scope

Read [README.md](README.md) for architecture/runtime orientation and
[SLO.md](SLO.md) for repository workflow instructions. This document collects
project-wide coding guidance; follow its linked governing skills for details.
Use this checkout's `skills/`, not an installed copy, for repository work.
Specific approved project contracts specialize generic recipes; surface unresolved
conflicts rather than silently inventing exceptions. A TUI contract below does
not impose its lifecycle API on every service, tool or collaborator.

**Example:** a transcript adapter uses `handle(event=...)`; an agent tool follows
[build-agent-tools](skills/languages/python/build-agent-tools/SKILL.md), not a
new `register/reset/close` interface copied from the TUI.

## 2. NON-NEGOTIABLE foundations

**All five apply project-wide, including changed production code and tests, not
only TUI components or adapters.** Language and framework requirements specialize
syntax; they do not waive ownership, meaningful verification or no-regression obligations.

- **Tell, don't ask:** tell the responsibility owner to perform an operation;
  do not read its private state and duplicate its policy in callers.
- **Test-first development:** establish the observable contract, write a failing
  behavior/regression test, implement the smallest coherent change, then refactor
  with passing tests. Do not invent a RED result you did not observe.
- **Named arguments:** name multi-argument calls, Boolean arguments and overridden
  defaults. Preserve framework/positional-only API requirements; an obvious
  single argument such as `len(entries)` is allowed by the Python skill.
- **Type hints:** explicitly type parameters and returns, meaningful state and
  non-obvious locals; use specific containers and truthful nullable results.
- **No regression:** introduced regressions block acceptance. Existing failures
  are not automatically waived; disclose failures, skips and blocked checks.

**Example:** `await transcript.handle(command=ClearTranscriptDAO())` requests
presentation clearing from its owner; callers must not clear the component's
private collections themselves. Test that presentation clears **without deleting
history** before changing that behavior.

Governing details: [declarative structure](skills/coding/declarative-method-structure/SKILL.md),
[Python signatures](skills/languages/python/named-arguments-and-type-hints/SKILL.md),
[test policy](skills/coding/test-verification-policy/SKILL.md), and
[verification obligations](skills/engineering/engineering-testing/SKILL.md).

## 3. Design around ownership and useful interfaces

Investigate callers and existing responsibility owners before adding a module.
Keep shared rules, formats and lifecycle decisions together. Prefer a small
behavior-oriented interface that hides substantial complexity; do not add
pass-through layers, speculative adapters or one helper per execution step.
Define inputs, results, invariants, failure behavior, resource ownership and
cancellation before implementation. Application workflows coordinate; domain
owners retain their rules. Design complete runnable slices, not disconnected
horizontal layers.

**Example:** `WorkflowNoticeAdapter` borrows a `TranscriptNoticeTarget` and
translates delivery into `handle(command=...)`; it does not own workflow execution
or close the borrowed transcript. `PromptHistoryNavigator` is a stateful helper,
not automatically an adapter merely because a component uses it.

See [solution design](skills/coding/solution-design/SKILL.md) and
[coding rules](skills/coding/coding-rules/SKILL.md). Apply the deletion test:
“If this module disappeared, would complexity disappear too, or would its work
have to be repeated across callers?”

## 4. Declarative Python and explicit data

Use flat guard clauses and cohesive named operations. Split unrelated decisions,
not arbitrary line chunks. **For Python, approximately eight substantive lines
is a review signal, not an extraction quota.** The generic declarative skill
still says “hard extraction rule”; the Python specialization explicitly owns
this Python-specific signal and permits a longer cohesive operation when splitting
would create shallow fragments. Apply that more specific rule here, under the
precedence in coding-rules: review independent policies, inputs, outputs and
ownership, not physical line count. This does not change the generic skill for
other languages. A short method containing unrelated policies still needs decomposition.
Keep orchestration readable without concealing effects behind vague helpers.

Use Pydantic `BaseModel` classes with `DAO` suffixes for new project data carriers,
not new `TypedDict` or dataclass carriers. Do not replace meaningful types with
bare `Any`. Preserve vendor-required heterogeneous signatures at the external
boundary and validate/narrow before internal use; they are not permission for
unbounded internal `dict[Any, Any]` contracts. Core logic belongs in cohesive
classes, with classmethods for stateless operations and established entry points
(`invoke`, `build`, `load`, `create`) where applicable. Stateful owners require
instance methods, not forced classmethods. Framework hooks, `@tool` bridges,
LangGraph nodes and test helpers retain their prescribed function shapes.
Do not resolve a class-convention violation by adding a shallow utility wrapper;
place shared policy with its cohesive owner. Use Black's configured 110-column format.

**Example:** [TranscriptNoticeDAO](src/tui/components/chat_transcript/commands.py)
names `content`, `classes` and optional `before`, rather than passing an anonymous
tuple through multiple layers. Frozen outer DAOs do not make nested values
immutable: detach borrowed mutable values where the ownership contract requires it.

See [Python conventions](skills/languages/python/python-conventions/SKILL.md) and
[Python declarative structure](skills/languages/python/declarative-method-structure/SKILL.md).

## 5. Names and documentation describe actual effects

Use the existing domain vocabulary. Distinguish pure `is_*` predicates, raising
`ensure_*` guards, state-changing actions, transient `build_*`, and background
`start_*`/`launch_*`. Memory is state too: CRUD terminology is not disk-only.
Name lock attributes as nouns; occupancy is not current-task ownership.
Preserve framework-reserved names. Google-style docstrings explain behavior,
callers/timing when relevant, inputs/results, errors and resource lifetime;
comments explain constraints rather than repeating statements.

**Example:** `WorkflowNoticeAdapter._ensure_workflow_notice_adapter_open()` only
rejects closed delivery; `_update_delivery_loop()` may store the first running
loop and therefore is not a pure guard. Its `_delivery_lock.locked()` check is
occupancy, not proof that the caller owns the lock.

See [naming and clarity](skills/coding/naming-and-clarity/SKILL.md) and
[method docstrings](skills/languages/python/method-docstrings/SKILL.md).
Existing names are history, not permission to repeat violations; avoid unrelated
renaming and preserve serialized/external compatibility during authorized changes.

## 6. Scoped TUI components and delivery adapters

This section applies to `src/tui/components/`, alongside
[Textual guidance](skills/tui/build-textual-tuis/SKILL.md). Separate app composition,
semantic input, domain interaction and presentation. Components own local UI state;
sessions/services own execution and persistence. Keep Textual's native lifecycle,
message queue and reserved `_closed`/`_closing` fields intact.

The actual [protocols](src/tui/components/protocols.py) distinguish:

| Role | Contract | Source example |
|---|---|---|
| Component | `handle(command=...)`, `reset()`, `close()`; applied completion, not paint | [PromptInputComponent](src/tui/components/prompt_input/component.py) owns draft, suggestions and recall |
| Delivery adapter | `handle(event=...)`, `reset()`, `close()`; translation and ordered delivery | [WorkflowNoticeAdapter](src/tui/components/chat_transcript/adapters/workflow_notice.py) sends notices to a borrowed command receiver |
| Specialized registration | Fresh, inert registration with typed borrowed capabilities | [WorkflowProgressUpdatesAdapter.register](src/tui/components/workflow_progress/adapters/workflow_progress.py) takes separate `host` and `presenter` |
| Mount leaf | Internal mounting after admission, not command reentry | [TranscriptNoticeMountTarget](src/tui/components/chat_transcript/adapters/transcript.py) avoids reacquiring public transcript locks |

**Example:** `WorkflowNoticeAdapter.register(tui=transcript_target)` must not
mount, subscribe, start work or capture an event loop. Its first delivery/reset
pins the loop; `await adapter.close()` retires its own work, not the target.
`handle` awaits applied delivery; a visual assertion still needs a mounted
Pilot/compositor check. Closed delivery rejects with `RuntimeError` before
unsupported-input `TypeError`, per the protocol contract.

Preserve admission order, post-await validity checks and stale-callback policy.
UI reset invalidates stale presentation while retaining borrowed dependencies;
close seals admission and joins owned cleanup, including cancellation paths.
These reset semantics are not universal: Claude's `ToolCallResponseAdapter.reset`
retains accepted submissions and anti-replay state, including uncertain sends.
Reset must never silently authorize resending a native tool result.
Use narrow consumer capabilities rather than passing the whole app everywhere.
Keep adjacent TCSS and semantic theme tokens. Do **not** turn every navigator,
controller, renderer, service or widget into an adapter: justify the translation
seam and lifetime first.

Observed legacy gaps are **not desired rules**: the notice adapters contain
unannotated significant state/locals, and older README examples use former module
paths. These examples establish ownership contracts only; this documentation task
neither repairs nor certifies those implementations.

## 7. Verification and safe delivery

Use the [test policy](skills/coding/test-verification-policy/SKILL.md) as the sole
owner of test levels/doubles, and [engineering testing](skills/engineering/engineering-testing/SKILL.md)
for risk mapping, evidence and baselines. Start at observable journeys; use real
disposable persistence, third-party mocks only at their boundary, and injected
stubs for internal collaborators. Do not patch private methods to manufacture
proof. Assert meaningful failures and forbidden effects as well as success.

**Example:** drive prompt submission with Textual Pilot through a real session
and temporary history store, inject `FauxChatModel` at the provider boundary,
then read back the user message. For adapter cleanup, verify that closing it
leaves its borrowed target usable; merely asserting a close method was called
cannot prove that contract.

Use README's actual environment/command instructions: inspect the test environment,
run focused checks incrementally, then full non-e2e and applicable static gates
before acceptance. Tests write only inside their resolved owned temporary paths;
never mutate system binaries or use real credentials/providers by default. Report
exact commands, results and unverified boundaries. Documentation preservation
hashes prove preservation, not runtime correctness or feature acceptance.

## 8. Documentation and historical memory

README remains the architecture/runtime guide; this file owns coding conventions. Durable project knowledge and historical receipts belong in
the existing external KB discovered through
[locate-knowledge-base](skills/design-and-analysis/locate-knowledge-base/SKILL.md).
Follow [update-knowledge-base](skills/design-and-analysis/update-knowledge-base/SKILL.md)
and the actual vault's ingestion rules. Do not recreate root `RESEARCH.md` after
its verified migration. The current documentation-only authorization covers this file, README/SLO alignment
and `../../specifications/projects/slo/specifications/101-slo-claude-bridge/refactor/01-refactor.md`; it is not blanket permission
for implementation, tests, configuration changes, commits or further repository reports.

**Example:** the original claude-bridge `RESEARCH.md` is preserved byte-for-byte
at KB `slo/research-snapshots/claude-bridge-2026-11-07/RESEARCH.md`; provenance and
historical-status warnings are in KB `slo/codebase-index.md` under “Local research
snapshot — claude-bridge, 2026-11-07”. Its old readiness claims and relative
handoff paths remain historical evidence, not current acceptance findings.
