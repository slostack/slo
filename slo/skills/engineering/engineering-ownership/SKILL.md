---
name: engineering-ownership
description: Language-independent model, boundary-data, service, adapter, naming, dependency and resource
  ownership obligations.
when_to_use: Language-independent model, boundary-data, service, adapter, naming, dependency and resource
  ownership obligations.
group: engineering
kind: skill
---

# Engineering Ownership

## Skill summary

Language-independent model, boundary-data, service, adapter, naming, dependency and resource ownership obligations.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Separate stable resolved models, transient typed boundary data, cohesive services and boundary adapters where those roles exist. Do not manufacture layers for trivial code. A service owns one cohesive capability or cross-domain workflow; callers delegate policy instead of inspecting state and reproducing it.

Dependencies flow from entry/wiring to application orchestration to domain/support owners to adapters. Inject narrow dependencies; no mutable global dependency graph or service locator. A long-lived runtime is published only when construction invariants succeed. Constructors must not expose partially assembled state.

Orchestration reads as named steps and explicit failure boundaries. Policy, protocol decoding and persistence mechanics belong in named owners, not hidden inside entry points. One domain concept has one canonical vocabulary across schema, boundary data, code and tests; preserve external names unless a change is approved. The naming authority is `skills/coding/naming-and-clarity/SKILL.md`.

Each resource/background operation has one owner for start, cancellation, cleanup and wait. Failed startup must unwind everything already acquired. Cancellation and shutdown are observable behavior, not implementation trivia. Meaningful contracts are typed; untyped bags must not replace reviewed boundary shapes.

Language roots specify syntax, function size/nesting expectations, documentation format and construction idioms. This policy does not prescribe keyword arguments, invoke(), ORM, directory layout, exception mechanism, test runner or framework. Review ownership changes with a current → target map, migration plan and compatibility analysis.

