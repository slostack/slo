---
name: review-feature-code
description: Reviewing a feature implementation against its spec.
when_to_use: Use as a structured pre-landing review for a feature PR.
group: design-and-analysis
kind: workflow
source_prompt: review-feature-code.md
---

# Review Feature Code

## Skill summary

- **Name:** `review-feature-code`
- **Description:** Reviewing a feature implementation against its spec.
- **When to use:** Use as a structured pre-landing review for a feature PR.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `review-feature-code.md`

## Examples

- The user asks for an end-to-end workflow that fits: Reviewing a feature implementation against its spec.
- Use as a structured pre-landing review for a feature PR.

## Guidance

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

Guide for conducting AI-assisted feature code reviews against a specification document.

Covers all stacks in the Orders platform monorepo: **FastAPI/Python**, **Vue 3/TypeScript**, **Typer CLI**, and **Textual TUI**.

> **POST-HOOK — mandatory:** After completing Steps 1–8 below, run
> [`skills/languages/python/code-review-rules/SKILL.md`](../../languages/python/code-review-rules/SKILL.md) as a hard-rules pass
> against the same diff. That prompt is the enforcement checklist;
> this prompt is the completeness and flow analysis. Both must complete
> before the review is done. Findings from the hard-rules pass are
> added to the Step 8 findings tiers — Blockers slot into **Glaring Gaps**,
> Warnings into **Nice-to-Haves**.

---

## When To Use This Guide

Use this guide when reviewing a feature implementation against its specification (Confluence page, JIRA ticket, or local spec document). The goal is a structured review that identifies completeness gaps, integration issues, and convention violations — not just surface-level code style.

---

## Review Process

### Step 0: Identify the Stack(s)

Before anything else, determine which stacks the feature touches. A single feature can span multiple.

| Stack | Indicator |
|---|---|
| **FastAPI/Python** | Changes under `src/` with `routers/`, `domains/`, `app_services/`, or `workers/` |
| **Vue 3/TypeScript** | Changes under `web/src/` with `.vue`, `.ts`, `composables/`, `stores/` |
| **Typer CLI** | Changes under `src/cli/` |
| **Textual TUI** | Changes under `src/tui/` |
| **AI/LangGraph Agent** | Changes to `*Graph` classes, `build()`, `invoke()`, or graph node functions |
| **DBOS workflows** | Changes involving `@dbos_class`, `WorkflowQueue`, scheduled workflows |

Steps 3–6 below are stack-specific — apply only the sections that match.

---

### Step 1: Load The Specification

1. Fetch the specification document (Confluence, JIRA, or local file).
2. Extract the **feature requirements** as a checklist — every distinct behavior, table, endpoint, worker, component, or integration the spec describes.
3. Identify the **end-to-end flow** the spec describes: what triggers the feature, what intermediate steps occur, and what the final output is.

### Step 2: Inventory The Implementation

1. List every file in the feature's source directory.
2. Categorize files by layer:

| Stack | Layers |
|---|---|
| FastAPI | domains (DAO, model, service), application services, routers/controllers, workers/tasks, migrations |
| Vue | views, components, composables, stores, types, API client |
| CLI | `app.py`, `typer_dispatch.py`, feature helpers |
| TUI | `app.py`, `slash_router.py`, `event_renderer.py`, widgets, screens, `.tcss` |

3. List every file in the corresponding test directory.

### Step 3: Spec-to-Code Mapping

For each requirement extracted in Step 1, find the corresponding implementation:

| Requirement | Implemented? | File(s) | Notes |
|---|---|---|---|
| _requirement from spec_ | Yes / No / Partial | _file path_ | _any caveats_ |

Be explicit about what is **missing entirely** vs what is **partially implemented** vs what is **fully done**.

### Step 4: End-to-End Flow Trace

Trace the feature from trigger to completion through the actual code. The trace structure differs by stack.

#### FastAPI/Python flow

1. **Entry point**: What starts the feature? (Cron job, API call, event handler, queue consumer)
2. **Orchestration**: Which application service coordinates the steps?
3. **Domain logic**: Which domain services are called and in what order?
4. **External I/O**: What external systems are touched? (S3, ClickHouse, databases, APIs, SFTP)
5. **Terminal state**: How does the feature signal completion? (Job status, event, API response)

Common disconnects to check:
- A worker is defined but never registered in the DBOS queue configuration
- A service creates a job but never enqueues it for processing
- A materialized view exists but no consumer reads from it
- An exporter writes to S3 but no downstream system is configured to read from that path

#### Vue flow

1. **Entry point**: Which view/page component mounts the feature?
2. **Data fetching**: Which composable or store action fetches data? Does it call the correct API endpoint?
3. **State management**: Which Pinia store holds state? Are field names the exact camelCase derivation of the API's snake_case fields?
4. **Component tree**: View → feature components → reusable components — are props/emits typed?
5. **Terminal state**: Does the UI reflect loading, error, and success states correctly?

#### CLI flow

1. **Entry point**: Which Typer command is the user-facing surface?
2. **Dispatch**: Does `typer_dispatch.py` assemble all runtime objects before calling domain code?
3. **Feature logic**: Is the actual behavior in a separate helper module (not in `app.py`)?
4. **Name traceability**: Can every CLI flag name be traced back to an env var and a Makefile variable via the dispatcher's mapping table?

#### TUI flow

1. **App shell**: Does `app.py` only declare the widget tree, bindings, and lifecycle hooks?
2. **Event routing**: Does `slash_router.py` or a dedicated router interpret UI events (slash commands, key presses)?
3. **Rendering**: Does `event_renderer.py` or a dedicated renderer convert domain events to widget updates?
4. **Domain interaction**: Are session/service calls isolated from UI composition?

#### LangGraph Agent flow

1. **Gateway**: Does the graph class expose `invoke()` as the canonical entry point?
2. **Node registration**: Are all nodes registered with `graph.add_node()`? Are all routing functions `@staticmethod`?
3. **Diagram**: Is the ASCII execution flow diagram present as a module-level comment block above the class definition?
4. **Streaming**: If streaming is required, does `invoke_streaming()` exist and share `_build_initial_state()` with `invoke()`?

Draw the flow as a pipeline diagram. Verify that **every component in the chain is actually wired to the next**.

### Step 5: Test Coverage Analysis

For each production file:

1. Identify the corresponding test file(s).
2. List every test method and what it asserts.
3. Identify **untested production files** (zero coverage).
4. Identify **missing test scenarios** within tested files:
   - Happy path covered?
   - Error/failure path covered?
   - Edge cases (empty input, duplicates, retries, concurrent access)?
   - Negative cases (invalid input should be rejected)?

**Stack-specific test checks:**

| Stack | What to verify |
|---|---|
| FastAPI | Each route has 200/404/422 tests; each domain service method has decision-point tests |
| Vue | Each component has render + emit tests; each composable has mocked-API tests; Pinia actions are unit tested |
| CLI | `CliRunner` tests for each command; dispatcher logic tested below Typer |
| TUI | `App.run_test()` pilot tests for key flows; event renderer and slash router tested in isolation |
| LangGraph | Graph node functions tested independently; routing functions (`@staticmethod`) tested without full graph boot |

### Step 6: Convention Compliance

Apply the checks for every stack the feature touches.

#### Module-depth design review

Apply [Module-depth design guidance](../../coding/declarative-method-structure/SKILL.md#module-depth-design-guidance)
with actual call-site evidence in Python, Go and TypeScript. What must callers know
about constructors, ordering, flags and errors? What complexity is actually owned,
and can internals change without callers? A single invoke/Execute gateway is not
proof of depth. Prefer meaningful outcomes and cohesive private helpers in existing
owners, not wrapper proliferation or god objects. Preserve required thin routers,
CLI adapters and agent-tool bridges, public compatibility, security and gateway rules.
Verify documented retry limits, cancellation, durability and meaningful errors.
Depth is advisory, not an automatic blocker or an exemption from the hard ~8-line
extraction rule. Rank any finding by demonstrated impact, not interface size alone.
Use Go context-first/named-field structs and TypeScript named options/explicit types;
do not impose Python keyword arguments or private underscores on those languages.
Load their applicable language, application/domain, documentation and testing skills.

#### Universal Conventions (all stacks)

| Convention | What To Check |
|---|---|
| `skills/coding/declarative-method-structure/SKILL.md` | Shared flat structure, early returns, single decision per method, and meaningful decomposition; load the language specialization for syntax and thresholds |
| `skills/languages/python/named-arguments-and-type-hints/SKILL.md` | Named args for 2+ params; type hints on all params and return values |
| `skills/languages/python/method-docstrings/SKILL.md` | Google-style docstrings on all public methods |
| `skills/design-and-analysis/ubiquitous-language/SKILL.md` | One concept, one canonical name across every layer — no synonyms anywhere in the diff |
| `skills/coding/code-test-loop/SKILL.md` | Evidence that tests were written per unit during development, not after a 500-line dump |

#### FastAPI / Python Conventions

| Convention | What To Check |
|---|---|
| `skills/languages/python/application-structure/SKILL.md` | File layout, `app.py` / `main.py` patterns, lifespan wiring |
| `skills/languages/python/build-domain-features/SKILL.md` | `dao.py` / `service.py` / `model.py` three-file structure; DAO field names identical to model column names (no aliasing) |
| `skills/languages/python/build-application-services/SKILL.md` | `invoke()` pattern; orchestration only in `invoke()`; private `_step_*` methods; no business logic inline |
| `skills/languages/python/build-routers/SKILL.md` | Service namespace prefix `<ns>/api/v1` mandatory; `SuccessResponseDAO` wrapper on all responses; permissions wired |
| `skills/languages/python/build-dbos-workflow-orchestration-pattern/SKILL.md` | Queue/workflow naming; enqueuer pattern; dedup IDs; queue registered in config |
| `skills/languages/python/build-schedulers-tasks-with-dbos/SKILL.md` | Cron schedule, worker concurrency, queue definitions |
| `skills/languages/python/build-vscode-launch-configurations/SKILL.md` | Every new long-lived process has a matching VSCode launch config |

#### Vue / TypeScript Conventions

| Convention | What To Check |
|---|---|
| `skills/frontend-vue/vue-coding-conventions/SKILL.md` | `<script setup lang="ts">` everywhere; Options API absent; one component per file |
| Props & emits | `defineProps<{...}>()` and `defineEmits<{...}>()` with TypeScript generics — no runtime object syntax |
| camelCase derivation | Every API snake_case field (`question_limit`) appears in the store/props as the exact camelCase derivation (`questionLimit`) — no creative synonyms |
| Views are thin | View components only compose and wire; business logic lives in composables or services |
| `composables/` | Stateful logic extracted to `use*` composables; not inline in components |
| `skills/frontend-vue/build-websocket-endpoints/SKILL.md` | Streaming handled via `useAgentStream` composable; no raw `EventSource` inline in components |

#### CLI (Typer) Conventions

| Convention | What To Check |
|---|---|
| `skills/cli/build-typer-cli-apps/SKILL.md` | `app.py` → parse only; `typer_dispatch.py` → assemble only; feature logic in separate helpers |
| `skills/cli/build-cli-commands/SKILL.md` | Command help text present; error surfaces handled; exit codes explicit |
| `skills/cli/build-cli-command-class/SKILL.md` | Class-based commands use the Command class pattern; no logic in `__init__` |
| `skills/cli/build-cli-modules/SKILL.md` | Module entry points wired in `pyproject.toml`; `__main__.py` present |
| `skills/design-and-analysis/ubiquitous-language/SKILL.md` §4 | New operator-facing concepts named at Makefile level first; dispatcher mapping table updated |

#### Textual TUI Conventions

| Convention | What To Check |
|---|---|
| `skills/tui/build-textual-tuis/SKILL.md` | `app.py` = widget tree + bindings only; no business logic in App shell |
| Event routing | Slash commands and key events routed through `slash_router.py` or equivalent; not inline in App methods |
| Rendering | Domain events converted to widget updates in `event_renderer.py` or equivalent — not in App |
| Styling | All layout and presentation in `.tcss` files, not inline styles |
| Worker isolation | Async domain work runs in `app.run_worker()`; not in message handlers |

#### AI / LangGraph Agent Conventions

| Convention | What To Check |
|---|---|
| `skills/languages/python/graph-gateway-invoke-convention/SKILL.md` | `invoke()` is the gateway; `invoke_streaming()` exists if streaming needed |
| Execution flow diagram | Module-level `#` comment block above class definition showing all nodes, conditional edges, loops |
| `@staticmethod` | Routing functions, phase helpers, parsers are `@staticmethod` |
| State isolation | `_build_initial_state()` extracted and shared between `invoke` and `invoke_streaming` |
| Module-level aliases | Backward-compat module-level wrappers exist when refactoring from free functions |

### Step 7: Ubiquitous Language Audit

This step is universal and runs regardless of stack. For every concept that crosses a layer boundary in the diff:

1. Pick a concept name from the PR.
2. Trace it from its origin layer through every subsequent layer.
3. Flag any layer where the name changes (even minor: `env_id` vs `environment_profile_id`).

Common violation patterns to catch:
- Dropping qualifier prefix (`difficulties` instead of `question_difficulties`)
- Abbreviations breaking the chain (`n` instead of `question_limit` in a Python class)
- DAO field name differs from model column name (aliasing)
- Vue store key does not derive from the API field name
- Test fixture uses shorthand not matching production parameter name

### Step 8: Compile Findings

Organize findings into three tiers:

#### Glaring Gaps (Must Fix)
- Spec requirements that are entirely missing
- Components that exist but are not wired together (dead code)
- Production entry points with zero test coverage
- Security or data integrity issues
- Convention violations that are non-negotiable hard rules (ubiquitous language violations, missing `invoke()` gateway, Options API in Vue, missing service namespace prefix)

#### Nice-to-Haves (Should Fix)
- Missing edge-case tests
- Minor convention violations (missing docstrings, weak assertions)
- Code that works but could be more robust
- Unused helper code (e.g. test factories defined but never called)

#### Temporary Shortcuts (Acknowledged Technical Debt)
- Workarounds that are pragmatically correct but not ideal
- Assumptions that should be validated
- Missing retry/resilience logic on specific operations
- Configuration-dependent behavior that has no code-level guard

---

## Output Format

Produce a markdown document with these sections:

1. **Stack Summary** — which stacks this feature touches and which convention sets apply
2. **Executive Summary** — 2-3 sentences on overall status
3. **Feature Completeness Table** — Spec requirement vs implementation status
4. **End-to-End Flow Verification** — Stack-specific pipeline diagram + verdict for each flow
5. **Unit Tests Assessment** — Coverage table, untested files, missing scenarios
6. **Convention Adherence** — Per-convention compliance with specific violations noted, organized by stack
7. **Ubiquitous Language Audit** — Cross-layer name trace table; flag every synonym found
8. **Findings Summary** — Three-tier findings (Glaring Gaps, Nice-to-Haves, Shortcuts)
9. **Architecture Diagram** — Mermaid diagram showing implemented and missing components

---

## Tips

- **Read the spec first, code second.** Build your mental model from the spec, then validate against code. This catches omissions that reading code alone would miss.
- **Trace data flow, not just code structure.** A well-organized codebase can still have broken pipelines if components aren't connected.
- **Check constants.** Queue names, workflow names, job types, route prefixes, and cron schedules are often defined in central files. A missing constant means the feature can't run even if the code exists.
- **Run the tests.** Test failures caught during review are far cheaper than failures in production.
- **Don't just check that tests exist — check what they assert.** A test file with 10 methods that only test the happy path gives false confidence.
- **Flag dead code.** Materialized views that populate but are never queried, factory helpers that are never used, and services with no consumer are all signs of incomplete implementation.
- **Treat ubiquitous language violations as bugs, not style issues.** A renamed concept is a latent bug — a developer reading code after the rename cannot tell whether two names refer to the same thing or to genuinely different things.

---

## Post-Hook: Hard Rules Pass

When the flow analysis (Steps 1–8) is complete, immediately run the hard-rules
checklist in [`skills/languages/python/code-review-rules/SKILL.md`](../../languages/python/code-review-rules/SKILL.md). Work through every
section that matches the stacks identified in Step 0. Merge those findings into
the Step 8 output before delivering the review.
