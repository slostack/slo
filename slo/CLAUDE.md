When asked to write, modify, or reason about code in this repository, read `AGENTS.md` first. Skip this for general questions about syntax, language semantics, or topics that don't require project context.

## Feature-request and specification locations

For Slo feature work:
- read incoming requests from the repo-local `feature-requests/` directory;
- write final specs under the repo-local `specifications/` path (a symlink to the
  canonical specification root on the operator's machine);
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

**Dynamic workflows shorthand:** if the user says **"dynamic workflows"** or the misspelling **"dyanmic workflows"**, interpret that as an explicit request to execute the named workflow **in the current session** (sync dynamic workflow) — the orchestrator decomposes phases and dispatches them with `spawn_sub_agents`, blocking until the synthesis is returned in the same turn. To detach the workflow as a headless orchestrator process, the user must add an explicit detach qualifier: the word **"headless"**, **"detached"**, or **"independent"** applied to the request (e.g., **"headless dynamic workflows"**, **"detached dynamic workflows"**, **"independent dynamic workflows"**), or equivalent detach wording (**"in the background"** / **"without blocking"**). Only a detach-qualified request routes to `launch_workflow`; a detached orchestrator never calls `launch_workflow`.

**Orchestrator timeouts for slow-test projects:** `spawn_sub_agents` blocks the orchestrator's own stream while a child runs, so the parent guard `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` (default `4800`) — not the child's `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` (default `3600`) — is the real ceiling on a single blocking phase. A busy child never trips its own guard; when a phase's gates run long (e.g. `go test -race ./...`), the orchestrator falsely aborts with `TimeoutError: main agent stream produced no events ...; treated as hung`. Before launching a dynamic/headless workflow against such a project, export both guards (parent > child) — the optimal values are `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800` and `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200` — and prefer splitting phases so no single `spawn_sub_agents` call exceeds the parent guard. See `AGENTS.md` and KB `slo/headless-workflow-orchestration.md`.
