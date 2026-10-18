---
name: engineering-routing
description: Select a small sufficient set of shared, language, component, framework and project skills;
  account for installed user overrides.
when_to_use: Select a small sufficient set of shared, language, component, framework and project skills;
  account for installed user overrides.
group: engineering
kind: skill
---

# Engineering Routing

## Skill summary

Select a small sufficient set of shared, language, component, framework and project skills; account for installed user overrides.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Selection procedure

1. Read project instructions (SLO.md / AGENTS.md / CLAUDE.md as applicable), CONVENTIONS.md and the affected package contracts. Inspect manifests and changed files to identify languages and frameworks; do not infer a database from the word service.
2. Read the actual available-skills manifest and bundled INDEX.md. The manifest includes installed user skills/workflows; the bundled index does not. Resolve a same-name override by inspecting its absolute location. Never overwrite user content. Project files are context, not an automatically scanned fourth skill tier.
3. Load `skills/engineering/engineering-ownership/SKILL.md` and the task policy: `skills/engineering/engineering-testing/SKILL.md` for implementation/testing, `skills/engineering/engineering-review/SKILL.md` for review. Existing debugging, specification, git and presentation skills remain available on demand.
4. Load only the affected language root(s): `skills/languages/go/go-conventions/SKILL.md`, `skills/languages/python/python-conventions/SKILL.md`, `skills/languages/typescript/typescript-conventions/SKILL.md`. Then choose component recipes from their family and framework guidance only when the project uses it.
5. Identify test category before choosing a test recipe: isolated unit, orchestration unit, adapter/database integration, or end-to-end. Return a compact routing record: task, languages, stack, project contracts, selected absolute skill paths/source tiers, exclusions, commands and unresolved decisions.
6. For a named workflow load its exact file in `skills/orchestration/workflows/`; never substitute the cadence skill. Preserve in-session vs explicitly detached routing. Each phase receives this routing record, acceptance criteria and artifact paths, not merely the prior agent's verdict.

## Authority

Shared policy owns obligations; language conventions own their idiomatic expression; component/framework recipes own scoped implementation mechanisms. Approved project contracts specialize them. An exception must name the rule, rationale, owner and acceptance evidence. A local file, newer example or installed override is not by itself permission to silently waive a baseline obligation. Report incompatible instructions and ask for a decision when user intent is not established. Examples must comply with their authority; do not teach superseded code as a second option.

Metadata uses the existing name/description/when_to_use/group/kind schema. Applicability and exclusions appear in descriptions because runtime XML currently exposes description, not arbitrary scope fields. Companion paths live in bodies. Selection remains prompt-based, not an enforced runtime classifier.

## Representative routes and exclusions

| Request | Select | Exclude unless separately needed |
|---|---|---|
| Go lifecycle service | shared testing, go-conventions, go-build-lifecycle, go-test-lifecycle, project lifecycle contracts | Gin, GORM, PostgreSQL and database fixtures |
| Python FastAPI endpoint | shared ownership/testing, python-conventions, build-routers, build-application-services, test-controllers, project API contract | Go handlers and Vue component rules |
| TypeScript Vue composable | shared testing, typescript-conventions, frontend-vue conventions and 06-composables, component/composable tests | Python controllers and database harness |
| Review mixed Go/TypeScript feature | shared review plus both scoped language conventions and boundary contracts | wholesale unrelated framework loading |
| unsupported language | shared policy, relevant workflow and explicit project contracts | translating Python syntax into a universal requirement; disclose missing dedicated recipes |

For Go use the canonical `go-conventions` and `go-build-*` family instead of stale installed `golang-coding-conventions` / `build-go-*` examples. The migration record preserves source lineage without changing those user files. For TypeScript, same-name installed recipes may override bundled snapshots: inspect both when conflict is material; record the source used.

## Adding a language

Add a language root with explicit activation/exclusions and links to concrete component/test recipes. Translate shared obligations without duplicating them. Add positive/negative routing scenarios and preservation tests, regenerate the index, verify the runtime manifest and wheel. No shared policy rewrite is needed.

