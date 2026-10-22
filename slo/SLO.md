# Slo Repo Conventions

- Read `README.md` first for any code, architecture, workflow, or testing task in
  this repository. It is the authoritative reference for module layout, the
  runtime chain, the tool bundle, and the style rules. `RESEARCH.md` holds the
  exact operational specifics (timeouts, limits, commands, how-tos).

## Skills maintenance

Use this checkout's vendored `skills/` tree, not the pipx installation, when
working on its skills. Authored `SKILL.md` files and companion resources are the
source of truth; `skills/INDEX.md` is generated.

From the application root (the directory containing this file), run:

```bash
make refresh-skills
# Equivalent; run either command, not both:
make build-skill-index
```

Both commands recursively scan `skills/**/SKILL.md` and rebuild only
`skills/INDEX.md`. They preserve skill bodies, workflow definitions, samples and
assets, including non-code families such as PDF/presentation. Refresh delegates
to the index builder; it no longer imports upstream prompts or uses
`SLO_CODE_PROMPTS_DIR`. Runtime discovery and user override behavior are unchanged.
See `README.md` for the layered skill structure.

## Workflow-turn counting

Use `skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`
for counting and stopping rules. One workflow turn is a complete pass through
all required phases, not one agent dispatch. Track partial passes, phase retries
and dispatch limits separately. Disclose a harness budget conflict before launch;
never claim repeated writing attempts were complete writing-and-review cycles.
Limits: eight workflow turns started per task (partial turns included), six
dispatch calls per turn, three retries per failed task, and no retries after an
abort. Resume and takeover preserve task-wide counts. Use `single` at review
gates; process completion alone does not establish workflow acceptance.

## Workflow and testing rules

- **Named workflows come from the `workflows/` folder.** When the user names a
  workflow, load `skills/orchestration/workflows/<name>.md` — never a skill
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
  `RESEARCH.md` and KB `slo/headless-workflow-orchestration.md`.

- **Verify before you claim.** Follow `skills/engineering/engineering-testing/SKILL.md`
  and `skills/coding/test-verification-policy/SKILL.md` for meaningful behavior,
  boundary and critical failure-path evidence. Run the full non-e2e suite before
  acceptance; baseline exemptions need explicit approval. Report failures and
  blocked checks honestly, never as passing.
