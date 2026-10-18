---
name: implement-feature-request
description: End-to-end workflow for turning a feature request or JIRA story into
  specs, code, tests, review, and documentation updates.
when_to_use: Use when the user asks for implementation of a feature request, JIRA
  story, or request.md artifact rather than a narrow one-off code change.
group: design-and-analysis
kind: workflow
---

# Implement Feature Request

## Skill summary

- **Name:** `implement-feature-request`
- **Description:** End-to-end workflow for turning a feature request or JIRA story into specs, code, tests, review, and documentation updates.
- **When to use:** Use when the user asks for implementation of a feature request, JIRA story, or request.md artifact rather than a narrow one-off code change.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`

## Examples

- The user asks: "Implement /path/to/request.md." Use this workflow to gather context, draft or verify specs, implement, test, and document the result.
- The user asks: "Take this JIRA story from request to code." Use this workflow to break the work into spec, task, implementation, review, and docs phases.

## Slo defaults for request and specification artifacts

Resolve Slo home and artifact roots using [the authoring path contract](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery).

Unless the user explicitly overrides these paths, use:

```text
<feature-requests-root> = <SLO_FEATURE_REQUESTS_DIR or resolved-Slo-home/projects/<project_name>/feature-requests>
<feature-specifications-root> = <SLO_FEATURE_SPECIFICATIONS_DIR or resolved-Slo-home/projects/<project_name>/feature-specifications>
```

Use one folder per feature:

```text
<feature-requests-root>/
└── 01-example-feature/
    └── request.md

<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md
    ├── 01.a-sub-step.md
    └── plan.md
```

## Guidance

## Goal

Deliver a feature request or JIRA story from planning artifact to tested
implementation without skipping the intermediate workflow steps.

## Default Slo Artifact Layout

Unless the user explicitly overrides these paths, use:

```text
<SLO_FEATURE_REQUESTS_DIR or resolved-Slo-home/projects/<project_name>/feature-requests>
└── <feature_slug>/
    └── request.md

<SLO_FEATURE_SPECIFICATIONS_DIR or resolved-Slo-home/projects/<project_name>/feature-specifications>
└── <feature_slug>/
    ├── overview.md
    ├── 01.a-sub-step.md
    └── ...
```

Honor `SLO_FEATURE_REQUESTS_DIR` and `SLO_FEATURE_SPECIFICATIONS_DIR` when
they are present. Otherwise, derive the roots above under the active
`<project_name>`.

## Workflow

1. **Load context first.**
   - Read the relevant request artifact, story, or `request.md`.
   - Read project guardrails (`CLAUDE.md`, `AGENTS.md`, `RESEARCH.md`).
   - Read the Knowledge Base before inferring architecture or domain rules.
2. **Produce or validate the implementation spec, then break it into tasks.**
   - Run the **Specification Development** workflow — load and follow
     `skills/orchestration/workflows/specification-development.md`. It
     sequences `feature-specifications` (gather/draft/self-check/revise) →
     `feature-specification-verification`
     → `breakdown-feature-spec-to-tasks` (and lists those sub-skills at its top).
   - If a draft spec already exists, that workflow runs
     `feature-specification-verification` rather than rewriting blindly.
Before choosing implementation skills, read `skills/coding/coding-rules/SKILL.md`
and record the handoff order: project context → generic coding rules → applicable
language root → applicable feature/framework recipes → bounded implementation and
verification. Preserve applicable specific guidance over generic defaults and
surface unresolved specific-to-specific conflicts instead of resolving them silently.

3. **Choose the implementation skills.**
   - Match the task shape to the right build/test skills (`build-routers`,
     `build-domain-features`, `build-application-services`, `build-clients`,
     `build-agent-tools`, CLI/TUI skills, etc.).
4. **Implement, test, and review each task.**
   - Run the **Code-Test-Review** workflow per task — load and follow
     `skills/orchestration/workflows/code-test-review.md`. It sequences
     `code-test-loop` → `review-feature-code` → `is-the-feature-completed`
     (and lists those sub-skills at its top). Land one small unit, run its
     tests, then continue.
   - Use `development-reviews` when the review-agent handshake applies.
5. **Update documentation and knowledge capture.**
   - Use `update-documentation-after-code-changes`.
   - Use `update-knowledge-base`.
   - Use `distill-learnings` when you discovered something subtle.

## Non-Negotiables

- Do not jump straight from a request into coding when a spec is missing or stale.
- Do not invent storage paths for requests/specifications; use the Slo roots above.
- Do not skip the code+test loop.
- Do not close the task without documentation and KB updates when the work changed conventions or surfaced new gotchas.

## Output Expectation

When following this workflow, keep the user informed of the current phase:

- Context gathered
- Spec drafted or verified
- Tasks broken down
- Implementation in progress
- Tests passing
- Docs / KB updated
