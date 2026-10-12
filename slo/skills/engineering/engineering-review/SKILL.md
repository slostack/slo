---
name: engineering-review
description: Review any language or mixed-language change for ownership, correctness, compatibility, coverage
  and honest evidence; load scoped language conventions.
when_to_use: Review any language or mixed-language change for ownership, correctness, compatibility, coverage
  and honest evidence; load scoped language conventions.
group: engineering
kind: skill
---

# Engineering Review

## Skill summary

Review any language or mixed-language change for ownership, correctness, compatibility, coverage and honest evidence; load scoped language conventions.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Read the spec and diff, map each requirement to changed files and tests, then trace the end-to-end path including registration/wiring. Use `skills/engineering/engineering-routing/SKILL.md` to load language/framework rules only for their scope. For mixed Go/TypeScript review, inspect both families and their shared wire contract; never apply Python keyword arguments or docstrings to Go.

Audit ownership/dependency direction using `skills/engineering/engineering-ownership/SKILL.md`; audit proof using `skills/engineering/engineering-testing/SKILL.md`. Check security boundaries, resource lifetimes, backward compatibility, failure/cleanup paths, concurrency and observability. Check examples as code guidance, not decorative text.

Findings include severity, exact path/line, violated requirement, concrete failure scenario, recommended convention-aligned fix and verification. Distinguish blockers, improvements and acknowledged debt. Missing evidence remains missing even if the author reports READY. Return REVISE for blockers, READY only with a requirement/evidence matrix, FAILED for an execution failure. The structured feature-review and completion skills retain their full reporting procedures.

