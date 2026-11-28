---
name: debug-and-fix
description: Permission-first diagnosis and test-first remediation with safe diagnostics, controlled reproduction, correlated terminal verification and target-only restart ownership.
when_to_use: Use when investigating and fixing a failure, especially when error normalization hides its cause or a running session must load and verify a patch.
group: coding
kind: skill
---

# Debug and Fix

## Skill summary

Diagnose with evidence before changing behavior. Repair the responsible owner with a failing regression test, then verify the actual affected journey. This is project-agnostic guidance, not permission to operate a live system or a replacement for a requested review workflow.

## Examples

- “Find why this request fails, then fix it without breaking continuation.”
- “The UI shows a generic error; preserve safe evidence of the original failure.”
- “Verify this patch in the affected development session.”

## Guidance

### 1. Establish permission and the failure

Read project instructions, architecture and relevant knowledge before acting. Use
[engineering routing](../../engineering/engineering-routing/SKILL.md) to select
language and component rules. Record the exact target, expected versus observed
behavior, reproduction steps, environment and unresolved assumptions using
[describe a problem](../../design-and-analysis/describe-a-problem/SKILL.md).

Separate diagnosis from remediation. Inventory scopes already granted by the
user: read-only inspection, instrumentation, tests, source edits, live reproduction,
restart, external sends and escalation. Acknowledge those grants; do not repeatedly
ask for the same scope. Ask only for missing authority before crossing its boundary.
A debugging request is not blanket permission to restart unrelated processes,
install packages, change credentials, delete data or publish code. Start read-only.

### 2. Preserve evidence before it is lost

Trace the real failing path, following
[debug by isolation](../../design-and-analysis/debug-by-isolation/SKILL.md).
Before changing semantics, add safe logging where necessary **before normalization**
or wrapping loses original exception types, bounded cause-chain structure, stack
locations (file/function/line), structural reason and correlation IDs. Distinguish
an upstream rejection from local decoding, validation or lifecycle failure.

Use an allowlisted diagnostic projection: no secrets, credentials, raw payloads,
request/response bodies, reasoning content, arbitrary exception messages, source
lines or locals. Bound chain/frame counts and field sizes. IDs must be operational
correlation identifiers, not opaque provider payload fields. Keep existing SDK
privacy/redaction active, including DEBUG logs and formatted exceptions; test with
synthetic secret and payload sentinels. Do not enable raw SDK dumps to diagnose.

Inspect the actual logging/config startup owners and all relevant entry paths.
Default ordinary logging to INFO and respect explicit DEBUG configuration; safe
preserved diagnostics must remain visible at DEBUG. Existing ERROR diagnostics
may remain ERROR: do not demote or delete them merely to meet a level setting.
Do not claim logging exists from source alone: verify the emitted safe record.

### 3. Reproduce in a controlled development session

Prefer a minimal deterministic reproduction through the real entry point, with
real disposable storage and controlled external boundaries. Match the failing
route, streaming mode and continuation state. Separate observations from hypotheses;
a locally passing substitute does not prove the live provider's behavior.

For an authorized live reproduction, verify the exact target and loaded checkout,
interpreter and session identity. Keep the operator responsive with a supported
persistent development terminal. As a **Slo-specific example**, from the intended
checkout, after satisfying ownership and permission gates:

```sh
SLO_DEV_MODE=1 poetry run python -m src.cli --resume <session_id>
```

This example is not a universal launcher and grants no live access. Do not silently
replace the requested interactive reproduction with a different headless session.

Every send command requires monitoring the exact correlated terminal response:
never fire-and-forget. Use the supported public channel API, retain its actual
message/request ID, map it to the target turn/run ID, and follow that run to
success, failure or abort under a bounded deadline. Queued/accepted is not finished.
Record terminal status and relevant forbidden effects (for example zero tool
execution); do not dump conversation bodies. On timeout report unverified/still
running, not success, and never automatically resend an uncertain request.
When requested, put long monitoring in the background using a supported supervised
mechanism, retain its identity/deadline and report progress and final outcome.
Background operation does not waive correlation, cancellation or cleanup.

### 4. Repair the cause with RED then GREEN

Name the violated invariant and its responsible owner from evidence. Follow
[code-test-loop](../code-test-loop/SKILL.md),
[coding-rules](../coding-rules/SKILL.md) and
[test-verification-policy](../test-verification-policy/SKILL.md).
Write the regression first and observe RED for the intended defect. Implement the
smallest coherent fix, observe GREEN, then refactor while green. Preserve existing
integrations, model paths, replay/continuation metadata and external contracts.

Cover meaningful variants and critical failures, not just the observed happy path.
Assert no blind tool replay, no discarded opaque state, no duplicate side effects
and no incomplete success. Do not bypass validation, invent provider identity rules,
or swallow a failure just to make the reproduction pass. Reuse valid surrounding
tests; mocks belong at third-party boundaries, not internal persistence or engines.

### 5. Load the patch without duplicating ownership

A source edit is not proof a running process loaded it. When a restart is required
and permitted, establish singleton ownership for the exact session/target and
confirm no active turn before target-only graceful shutdown. Stop/join owned
monitors and stale pollers; preserve unrelated sessions and their resources.
Verify the old owner exited and its ownership was released before starting one
replacement. If shutdown does not settle, stop and report unless a specific
authorized escalation exists; do not improvise a force kill or duplicate owner.

Verify replacement identity, actual loaded source and readiness, not just a PID
or successful spawn. Never manually inject history or IPC, edit ownership records,
or replay tools to manufacture verification. Unknown ownership remains a blocker.

### 6. Verify and report honestly

Repeat the original affected journey after the fix and, when authorized, after
restart. Correlate its terminal evidence again. Run affected tests and required
regression/static gates on final code to establish no regressions. Follow
[engineering testing](../../engineering/engineering-testing/SKILL.md): distinguish
focused evidence, full-suite evidence, live evidence, baseline failures and blocked
checks. A focused pass is not whole-system acceptance; existing failures need an
explicit disposition, not an implicit waiver.

Report the cause, owned changes, RED/GREEN commands and artifacts, diagnostic ID
and terminal correlation when applicable, privacy checks and remaining limitations.
Retire only owned temporary monitors/resources. Preserve useful evidence in the
approved handoff location and record durable learning under project conventions.
Do not claim completion while required verification is missing, and do not commit,
push, deploy or spawn another workflow without the corresponding authorization.
