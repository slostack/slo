---
name: derive-new-convention
description: Process for deriving a new repeatable convention when no existing prompt
  covers the requested pattern.
when_to_use: Use when the task introduces a new architectural pattern that does not
  fit any existing skill cleanly.
group: design-and-analysis
kind: skill
source_prompt: derive-new-convention.md
---

# Derive New Convention

## Skill summary

- **Name:** `derive-new-convention`
- **Description:** Process for deriving a new repeatable convention when no existing prompt covers the requested pattern.
- **When to use:** Use when the task introduces a new architectural pattern that does not fit any existing skill cleanly.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `derive-new-convention.md`

## Examples

- The user asks for a brand-new pattern that has no sibling prompt in the library.
- You need to formalize a new convention before implementing a feature that will recur.

## Guidance

When you encounter a feature type, paradigm, or architectural pattern that has **no existing code-prompt**, follow this process to derive a repeatable convention, agree on it with the user, and cement it as a new code-prompt.

**Do not improvise conventions on the fly.** Every new pattern must go through discovery, derivation, proposal, and confirmation before any production code is written.

---

## When To Use This Guide

Use this when **all** of the following are true:

1. The user asks you to build something that doesn't fit cleanly into an existing code-prompt (e.g., a new integration type, a new orchestration pattern, a new UI paradigm).
2. You've checked every skill under `skills/coding/` and confirmed no existing prompt covers the pattern.
3. The work will be repeated — it's not a one-off script or throwaway spike.

If the pattern is a one-off, skip convention creation and just write the code following the closest existing conventions.

---

## Phase 1: Discover

### 1.1 Scan Existing Code-Prompts

Read every code-prompt file and identify the **three closest** to the new pattern. Note:

- Their file structure conventions
- Their naming conventions (file suffixes, class prefixes/suffixes)
- Their required interface methods
- Their wiring/registration requirements
- Their test expectations

These become your **style anchors** — the new convention must feel like a sibling of these, not a foreign import.

### 1.2 Scan The Codebase

Search the workspace for any existing implementations that resemble the new pattern, even partial or experimental ones:

```
# Look for similar file names, class names, folder structures
Glob: **/*<pattern_keyword>*
Grep: class.*<PatternKeyword>
```

If you find existing implementations:

- Note which conventions they already follow (intentionally or accidentally)
- Note where they deviate from project norms
- These become your **reference implementations** — the convention should formalize what already works and correct what doesn't

If you find nothing:

- The convention will be derived purely from the style anchors and project-wide conventions
- Flag this to the user — a convention without a reference implementation carries more risk

### 1.3 Identify Cross-Cutting Conventions

The new convention must not conflict with these project-wide rules. Re-read these files and note anything relevant:

| Convention File | What To Check |
|---|---|
| `skills/coding/application-structure/SKILL.md` | Folder layout, config patterns, connector usage |
| `skills/coding/declarative-method-structure/SKILL.md` | Flat code, single decision per method, early returns |
| `skills/coding/named-arguments-and-type-hints/SKILL.md` | All function signatures must use named args + type hints |
| `skills/coding/method-docstrings/SKILL.md` | Google-style docstrings on all public methods |
| `skills/coding/python-path-and-import-resolution/SKILL.md` | Import path conventions |
| `skills/coding/test-verification-policy/SKILL.md` | Every decision point must have a test |
| `skills/git-ops/branching-and-commit-conventions/SKILL.md` | Git workflow |

---

## Phase 2: Derive

From what you discovered, extract the repeatable skeleton. Every convention must define **all six** of the following:

### 2.1 Folder Placement

Where do files for this pattern live? Follow the existing hierarchy:

- Domain logic → `src/domains/<domain_name>/`
- Application services → `src/services/<workflow_name>/`
- Workers/tasks → `src/tasks/`
- Integrations/clients → `src/integrations/<service_name>/`
- Event handlers → `src/event_handlers/`
- Routers → `src/routers/`

If the new pattern doesn't fit any of these, propose a new top-level folder under `src/` with a clear rationale. Avoid nesting deeper than two levels.

### 2.2 File Naming

Every file name must follow the existing suffix convention:

| Layer | Suffix Pattern | Example |
|---|---|---|
| Domain service | `service.py` | `src/domains/payments/service.py` |
| Domain DAO | `dao.py` | `src/domains/payments/dao.py` |
| Domain model | `model.py` | `src/domains/payments/model.py` |
| Application service | `_app_service.py` | `src/services/refund/refund_app_service.py` |
| Worker | `_worker.py` | `src/tasks/refund_processor_worker.py` |
| Client | `client.py` | `src/integrations/stripe/client.py` |
| Router | `_router.py` or `router.py` | `src/routers/payments_router.py` |
| Test file | `test_<module_name>.py` | `tests/domains/payments/test_service.py` |

Define the suffix for the new pattern. It must be:

- Consistent with the table above (don't invent a new style)
- Descriptive enough that a developer can identify the file's role from the name alone

### 2.3 Class and Module Naming

Classes follow `<DomainOrFeature><LayerSuffix>` naming:

| Layer | Class Pattern | Example |
|---|---|---|
| DAO | `<Name>DAO` | `PaymentDAO` |
| Service (domain) | `<Name>Service` | `PaymentService` |
| Application service | `<Name>AppService` | `RefundAppService` |
| Client | `<Name>APIClient` | `StripeAPIClient` |
| Worker | function named `<name>_worker` | `refund_processor_worker` |
| Event handler | `<Name>EventHandler` | `PaymentReceivedEventHandler` |

Define the class naming pattern for the new convention. It must follow `<Domain><Role>` structure.

### 2.4 Required Interface Methods

Every pattern has a set of methods that all implementations must respond to. These are the **contract** that makes the pattern predictable.

Examples from existing conventions:

| Pattern | Required Methods |
|---|---|
| Application service | `invoke()` as the single entry point |
| Domain service | `create()`, `build()`, `build_and_create()`, `update()`, `get()`, `delete()` |
| Client | `make_request()` as the central HTTP method |
| Worker | Async function + sync Celery bridge function |
| Event handler | `process(event_dao, db_session)` |

Define the required methods for the new pattern:

1. **Entry point method** — the single method that callers invoke (like `invoke()` or `process()`)
2. **Internal step methods** — private methods prefixed with `_` that the entry point delegates to
3. **Initialization** — what `__init__` must accept and store

### 2.5 Wiring and Registration

Most patterns require registration in a central location. Document every place a new instance of this pattern must be registered:

Examples:

| Pattern | Registration Points |
|---|---|
| Router | Added to `src/web_app.py` include list |
| Celery worker | Added to worker.py include list, task_routes, and optionally beat_schedule |
| Event handler | Added to `src/event_handlers/base.py` handlers list |
| DBOS workflow | Queue defined in `src/tasks/dbos_queues.py` |

Define the registration checklist for the new pattern. Be explicit — missing a registration step is the most common source of "it doesn't work" bugs.

### 2.6 Test Structure

Define the test file location and minimum test scenarios:

1. **Test file location**: Mirror the source path under `tests/`. For `src/services/refund/refund_app_service.py` → `tests/services/refund/test_refund_app_service.py`
2. **Test class naming**: `Test<ClassName>` or `Test<MethodName>` for focused test classes
3. **Minimum scenarios** (from `skills/coding/test-verification-policy/SKILL.md`):
   - Happy path for each public method
   - Error/exception path for each `try/except`
   - Each branch of every `if/elif/else`
   - Edge cases specific to this pattern
4. **Fixture expectations**: What test fixtures are needed? (db sessions, mock clients, sample DAOs)
5. **Mocking policy**: What should be mocked vs real? (e.g., external API calls are always mocked, database calls depend on test type)

---

## Phase 3: Propose

Present the derived convention to the user in this exact structure:

### Convention Proposal: `<Pattern Name>`

**Style anchors**: List the 2-3 existing code-prompts this is modeled after.

**Reference implementations**: List any existing code in the codebase that follows (or partially follows) this pattern. If none exist, state that explicitly.

#### File Tree

```
src/<location>/
├── file_one.py      # Role description
├── file_two.py      # Role description
└── __init__.py
```

#### Naming Table

| Element | Convention | Example |
|---|---|---|
| Folder | ... | ... |
| File | ... | ... |
| Class | ... | ... |
| Methods | ... | ... |

#### Canonical Code Template

Provide a **complete, runnable** code template. Not pseudocode — real Python that could be dropped into the project and work with minimal modification. Include:

- All imports
- Class definition with `__init__`
- Entry point method
- At least two private step methods
- Type hints on every parameter and return value
- Google-style docstrings on public methods

#### Test Template

Provide a **complete, runnable** test file template with:

- Test class structure
- At least one happy-path test
- At least one error-path test
- Fixture definitions or references

#### Wiring Checklist

A numbered list of every file that must be modified when adding a new instance of this pattern.

#### Differences From Existing Conventions

Explicitly list anything in this convention that is **new** (not present in any existing code-prompt). The user needs to approve these departures specifically.

---

## Phase 4: Cement

After the user confirms the proposal (with any modifications they request):

### 4.1 Write The Code-Prompt File

1. Create a new skill at `skills/coding/build-<pattern-name>/SKILL.md`
2. Follow the format of existing `build-*` skills:
   - H1 title
   - Brief description of what this pattern is and when to use it
   - File structure section with tree diagram
   - Naming conventions section
   - Complete code templates with syntax-highlighted Python blocks
   - Registration/wiring section
   - Test conventions section
   - Cross-references to related code-prompts
3. Use real examples from the codebase wherever possible, falling back to the canonical template only for genuinely new patterns

### 4.2 Update The README

Add the new file to the directory listing in `skills/orientation/readme/SKILL.md` in the appropriate position (alphabetical within its category).

### 4.3 Mirror To Local Prompts

If the project uses prompt syncing (check `skills/`), copy the new code-prompt there as well so it's available in the project directory.

---

## Rules

1. **Never conflict with existing conventions.** If the new pattern seems to require breaking an existing rule (e.g., nested conditionals, missing type hints), the new pattern is wrong — redesign it.

2. **Always show real code.** Templates must be complete and runnable. No `# TODO` placeholders, no `pass` bodies, no `...` ellipsis in method signatures.

3. **Match the tone and depth of existing prompts.** Read `skills/coding/build-clients/SKILL.md` and `skills/coding/build-celery-workers/SKILL.md` as your quality bar. The new prompt should feel like it was written by the same author.

4. **One pattern per file.** Don't combine multiple conventions into a single prompt. If the new feature involves a new domain pattern AND a new worker pattern, create separate prompts for each (or extend the existing ones).

5. **The user must confirm before any code-prompt is written.** Never skip Phase 3. The convention is a contract — both the AI and the developer must agree on it.

6. **Conventions decay.** After writing the prompt, the first 2-3 implementations should be reviewed against it. If the convention doesn't survive contact with real code, update it immediately rather than forcing the code to fit.
