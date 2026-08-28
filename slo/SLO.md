# Slo Repo Conventions

- Read `AGENTS.md` first for any code, architecture, workflow, or testing task in
  this repository. It is the authoritative reference for module layout, the
  runtime chain, the tool bundle, and the style rules.

- **Named workflows come from the `workflows/` folder.** When the user names a
  workflow, load `skills/design-and-analysis/workflows/<name>.md` — never a skill
  with a similar-sounding name. `code-test-loop` is Step 1 *inside* the
  Code-Test-Review workflow, not the workflow itself; loading it silently skips
  the review and completion-check steps.

- **"Dynamic workflows" runs in the current session by default.** If the user
  says **"dynamic workflows"** (or the common misspelling **"dyanmic
  workflows"**), decompose the named workflow into phases and dispatch them with
  `spawn_sub_agents`, blocking until the synthesis is ready in the same turn.
  Only detach into a headless orchestrator when the request carries an explicit
  detach qualifier — **"headless"**, **"detached"**, **"independent"**, **"in the
  background"**, or **"without blocking"**. A detached orchestrator never calls
  `launch_workflow` itself.

- Outside that shorthand, preserve the normal policy: only use orchestrator /
  `spawn_sub_agents` execution when the user explicitly asks for it.

- **Orchestrator timeouts for slow-test projects.** `spawn_sub_agents` blocks the
  orchestrator's own stream while a child runs, so the parent guard
  `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` (default `10800`) — not the child's
  `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` (default `7200`) — is the real
  ceiling on a single blocking phase, and a continuously busy child never trips
  its own guard. When a phase's gates run long (e.g. `go test -race ./...`) the
  orchestrator falsely aborts with
  `TimeoutError: main agent stream produced no events ...; treated as hung`.
  Keep parent > child, export both before starting the orchestrator, and prefer
  splitting phases so no single blocking call exceeds the parent guard. See
  `AGENTS.md` and KB `slo/headless-workflow-orchestration.md`.

- **Verify before you claim.** Every code change needs a passing test covering
  each decision point it touches, and the full non-e2e suite must be green
  before the work is called done. Report failures with their output rather than
  summarising them away.
