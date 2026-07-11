When asked to write, modify, or reason about code in this repository, read `AGENTS.md` first. Skip this for general questions about syntax, language semantics, or topics that don't require project context.

## Feature-request and specification locations

For Slo feature work:
- read incoming requests from `/Users/siddharth/Code/Pi/slo/feature-requests/`;
- write final specs under `/Users/siddharth/Code/Pi/slo/specifications/` or the repo-local `specifications/` symlink;
- use one numbered folder per feature: `<number>-<title>/`;
- the primary spec document is always named `overview.md` inside that folder;
- sub-specs follow the naming convention `<spec-number>.<letter>.<index>-<title>.md`
  (e.g., `28.a.1-moonshot-credential-lane.md`); never name a spec file `request.md`.

## Workflow Routing

When the user explicitly mentions a "workflow" or names one, load the workflow file directly from `skills/design-and-analysis/workflows/` — do NOT substitute a skill with a similar-sounding name.

| User request | Load this file |
|---|---|
| "use the code-test-review workflow" | `skills/design-and-analysis/workflows/code-test-review.md` |
| "use the specification-development workflow" | `skills/design-and-analysis/workflows/specification-development.md` |
| "what workflows are available" | `skills/design-and-analysis/workflows/SKILL.md` |

**Critical:** `code-test-loop` (`skills/coding/code-test-loop/SKILL.md`) is NOT the code-test-review workflow. It is Step 1 (the coding cadence) inside that workflow. Loading it instead of the workflow silently skips Step 2 (Code Review) and Step 3 (Completion Check). Always read the `workflows/` file when a workflow is requested.

**Dynamic workflows shorthand:** if the user says **"dynamic workflows"** or the misspelling **"dyanmic workflows"**, interpret that as an explicit request to use the orchestrator / headless workflow path — a Slo orchestrator that launches multiple Slo agents to perform each part of the workflow.
