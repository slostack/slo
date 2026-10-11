---
name: orchestrator
description: Gateway workflow that decides which skill or workflow to load next for
  the current task. Routes "dynamic workflows" / "dyanmic workflows" (no detach
  qualifier) to in-session multi-agent orchestration via spawn_sub_agents; routes
  a detach-qualified request ("headless" / "detached" / "independent" dynamic
  workflows, or a named workflow with "in the background" / "without blocking") to
  the headless-orchestration skill via launch_workflow. A detached orchestrator
  never calls launch_workflow.
when_to_use: Use at the start or end of a turn when you need to route the task into
  the right Slo workflow, category, or individual skill.
group: design-and-analysis
kind: workflow
---

# Orchestrator

## Skill summary

- **Name:** `orchestrator`
- **Description:** Gateway workflow that decides which skill or workflow to load next for the current task.
- **When to use:** Use at the start or end of a turn when you need to route the task into the right Slo workflow, category, or individual skill.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`

## Examples

- The user asks: "Implement this feature request." Route into the feature-request workflow, then the matching build and test skills.
- The user asks: "Why is this integration test flaky?" Route into the integration-test anti-patterns and debugging workflow.

## Guidance

**Workflow-turn accounting:** Follow
`skills/design-and-analysis/workflows/SKILL.md#workflow-turns-and-limits`.
Count a full pass through the workflow, not individual phases or agent calls.
Report partial passes and separate harness limits explicitly; never skip review
or treat repeated authoring dispatches as completed workflow turns.


**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.
Read `skills/coding/coding-rules/SKILL.md` as the generic baseline after project
context, then route to the applicable language root and feature/component recipes.
Applicable specifics override generic defaults on the affected point; unresolved
specific-to-specific conflicts remain explicit blockers.

## Goal

Route the current task into the **fewest high-signal skills** needed next.
The orchestrator is the gateway workflow for the Slo skill library.

## Workflows (prefer a workflow for compound, multi-phase tasks)

Before routing to individual skills, check whether the task is a whole
compound job. If so, route into a workflow file — it already sequences its
sub-skills and lists them at its top:

| Task shape | Route to |
|---|---|
| Implement a feature request / JIRA story end-to-end | `skills/design-and-analysis/implement-feature-request/SKILL.md` |
| Write / spec out / break down a feature specification | `skills/design-and-analysis/workflows/specification-development.md` |
| Implement a spec or task slice into tested, reviewed code | `skills/design-and-analysis/workflows/code-test-review.md` |
| Same, tracked through a GitLab issue + MR lifecycle | `skills/design-and-analysis/workflows/gitlab-code-test-review.md` |
| Learn what workflows exist / run a named workflow | `skills/design-and-analysis/workflows/SKILL.md` |
| User says `dynamic workflows` / `dyanmic workflows` without a detach qualifier — in-session orchestration with spawn_sub_agents | `skills/design-and-analysis/workflows/SKILL.md` |
| User says `dynamic workflows` / `dyanmic workflows` **with** a detach qualifier ("headless" / "detached" / "independent") or detach wording ("in the background" / "without blocking") — headless dynamic workflow via launch_workflow | `skills/design-and-analysis/headless-orchestration/SKILL.md` |
| Sequence a git task (branch → commit → push → PR) | `skills/git-ops/git-ops-orchestrator/SKILL.md` |

For narrower, single-purpose tasks, skip the workflows and use the category
routing hints below.

## Task Routing Order

1. **Detect whether this is a workflow task or an individual-skill task.**
   - The phrases `dynamic workflows` and `dyanmic workflows` **without a detach qualifier** are an explicit request for in-session multi-agent workflow execution; route them to `workflows` (spawn_sub_agents runs the phases in-session).
   - The same phrases **with a detach qualifier** ("headless", "detached", "independent") or detach wording ("in the background", "without blocking") are a detachment request; route them to `headless-orchestration` (launch_workflow detaches a headless orchestrator). A detached orchestrator never calls `launch_workflow`.
   - **Stopping a detached workflow** goes through `/workflows abort <workflow-id>` (or `SIGTERM` to the orchestrator pid for a shell-launched `slo run --orchestrator`), never `pkill` / `kill` from the bash tool. A raw kill leaves the session's workflow handle out of step with the orchestrator's status, and every later `launch_workflow` in that session fails with `no evidence-backed correction`. Details: `headless-orchestration` → "Stopping a running workflow".
   - Workflow tasks span multiple phases: context gathering, spec writing,
     implementation, testing, review, or documentation updates.
   - Individual-skill tasks are narrower: write a router, update a client,
     fix a test, add a CLI command, build a Textual widget, and so on.
2. **Check for feature artifacts first.**
   - If the request references a JIRA story, feature request, or `request.md`,
     route into `implement-feature-request` first.
   - Default storage roots:
     - Feature requests: `<SLO_FEATURE_REQUESTS_DIR or resolved-Slo-home/projects/<project_name>/feature-requests>`
     - Feature specifications: `<SLO_FEATURE_SPECIFICATIONS_DIR or resolved-Slo-home/projects/<project_name>/feature-specifications>`
3. **Choose the category.**
   - `design-and-analysis` for specs, tracing, debugging narratives, docs, KB, and review workflows.
   - `coding` for backend conventions and test conventions.
   - `git-ops` for syncing main, branching, committing, pushing, PR creation, PR review follow-up, and worktrees.
   - `cli` for Typer/operator-command work.
   - `tui` for Textual work.
   - `integration-tests` for cross-service scenarios and flaky-test debugging.
   - `frontend-vue` for Vue conventions and tutorials.
4. **Load companion skills only when the main skill calls for them.**
   - Example: `feature-specifications` owns context gathering and self-check; independent verification is separate.
   - Example: integration-test authoring starts with `10-cardinal-rules-and-anti-patterns` before scenario-specific prompts.
5. **Return only the next best skills.**
   Prefer a short ordered list over a long exhaustive catalog.

## Category Routing Hints

### Feature work

- Implementation request for a feature or story → `implement-feature-request`
- Need to draft a spec only → `feature-specifications` (Gather context → Draft → Self-check → Revise)
- Need to break an approved spec into tasks → `breakdown-feature-spec-to-tasks`
- Need to review shipped code against a spec → `review-feature-code`

### Backend / coding conventions

- Routers → `build-routers`
- Application services → `build-application-services`
- Domain models/services → `build-domain-features`
- Clients → `build-clients`
- Middleware → `build-middleware`
- Event handlers → `build-event-handlers`
- Celery → `build-celery-workers`
- DBOS workflow/schedulers → `build-dbos-workflow-orchestration-pattern`, `build-schedulers-tasks-with-dbos`
- Agent tools / LangGraph → `build-agent-tools`, `build-react-agent-with-langgraph`, `graph-gateway-invoke-convention`
- Tests → `code-test-loop`, `test-verification-policy`, plus the matching `test-*` skill

### Git operations

- Need the umbrella git policy first → `branching-and-commit-conventions`
- Need latest `main` before work starts → `sync-main`
- Need a task branch from latest `main` → `create-feature-branch`
- Need to save local work to git and push it → `commit-and-push`
- Need PR title/body only → `generate-pr-description`
- Need to open a PR → `create-pull-request` (after `generate-pr-description`)
- Need current PR context before review/follow-up → `load-pr-context`
- Need to address PR comments or conflicts → `fix-pr-review`
- Need latest `main` or parallel work without disturbing the current tree → `worktrees`

### CLI / TUI

- Product CLI under `src/cli/` → `cli-readme`, then `build-typer-cli-apps`
- Operator/deployment CLI → `cli-readme`, then the relevant `build-cli-*` skills
- Textual app/screens/widgets → `tui-readme`, then `build-textual-tuis`

### Integration tests

- Any integration-test task starts with `10-cardinal-rules-and-anti-patterns`
- New scenario stack/setup → `01-test-setup`
- Scenario authoring → `02-test-execution`, `04-scenario-conventions`, `05-step-definitions-with-domain-helpers`
- Feature request / plan → `06-generate-feature-requests`, `08-generating-test-plans`, `09-plan-to-code`
- Failing test → `07-debugging-failing-tests`, optionally `11-integration-test-investigation-format`

### Documentation / knowledge capture

- KB updates → `update-knowledge-base`
- Repo docs / AGENTS / RESEARCH refresh → `update-documentation-after-code-changes`, `generate-agents-md`, `generate-research-md`
- Session learnings → `distill-learnings`

## Output Format

Return a short ordered list:

```text
Relevant skills:
1. <skill-name> — why it applies now
2. <skill-name> — why it applies next
```

If no skill applies, return `Relevant skills: none`.
