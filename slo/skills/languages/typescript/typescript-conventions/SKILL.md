---
name: typescript-conventions
description: TypeScript conventions gateway for backend services and Vue components/composables; scoped
  typing, API, testing and framework recipes.
when_to_use: TypeScript conventions gateway for backend services and Vue components/composables; scoped
  typing, API, testing and framework recipes.
group: languages
kind: skill
---

# Typescript Conventions

## Skill summary

TypeScript conventions gateway for backend services and Vue components/composables; scoped typing, API, testing and framework recipes.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Shared obligations live in `skills/engineering/engineering-ownership/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md`. Load detailed sibling skills by component; do not replace their examples with generic TypeScript advice.

Style: typescript-named-arguments-and-type-hints, typescript-declarative-method-structure, typescript-method-docstrings, typescript-code-review-rules. Preserve typed object arguments, explicit contracts, readable named steps and established naming.

Backend: typescript-application-structure, typescript-build-domain-features, typescript-build-routers, typescript-build-middleware, typescript-build-clients, typescript-build-event-handlers, typescript-api-response-conventions, typescript-auth-security-patterns, typescript-build-api-documentation and typescript-generate-swagger-documentation. Framework examples apply only to that stack; no implied framework adoption.

Tooling: typescript-bootstrap-project-scaffolding, typescript-path-and-import-resolution, typescript-setup-dependencies-and-tests, typescript-switch-environments-and-run-tests, typescript-code-test-loop, typescript-test-verification-policy.

Testing: typescript-test-app-services owns isolated orchestration with injected mocks/recorders; typescript-test-domain-services and typescript-test-controllers cover their documented boundaries. Real-adapter tests remain necessary for persistence claims; distinguish them from mocked units.

Vue: `skills/frontend-vue/vue-coding-conventions/SKILL.md`, then only the affected fundamentals, TypeScript, Composition API, Pinia, router, composable, websocket, theming or build-vue-components recipe. Preserve component/composable boundaries, typed props/emits, reactivity, lifecycle cleanup, store and API contracts. Python websocket backend guidance in this family is a separate boundary, not a frontend prescription.

Installed same-name TypeScript skills may override these vendored snapshots. Inspect the manifest location; unresolved differences require an explicit decision, not deletion of the user's files.

