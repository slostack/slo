# T6 privacy diagnosis 130 — INCOMPLETE (no production repair)

## Scope and accounting

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 130, retries 0. Unlimited user turn/dispatch budgets apply; no agent dispatched and no numeric budget invoked as a stopping reason. This continuation wrote only this report and `t6-privacy-130/` receipts. No source/test/harness changes, Git mutations, shared status, KB, canonical specification, installation, live provider, Herdr, or window actions.

Two-process HOLD retained: only one explicitly named full-flow test family plus the approved helper's DAO/projection foundation was collected. No integration-directory or full-suite collection.

## Fresh evidence

Approved `PYENV_VERSION=slo-harness pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`.

Commands from application root:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh 'tests/integration/test_herdr_full_flow.py::test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting[openai-False-True]'
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_full_flow.py::test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting
```

- `t6-privacy-130/red.log`, `red.exit`: **1 failed, 62 passed**, exit 1.
- `t6-privacy-130/family-red.log`, `family-red.exit`: **8 failed, 70 passed**, exit 1. Counts include overlapping 62 foundation cases; do not sum.
- `coreutils.log`: empty; `dpkg -V coreutils` exit 0 after both runs.
- `diff-check.log`: empty; `git diff --check` exit 0.
- Black/mypy not run: no code edits. Global supplied 281 errors / 58 files remains unwaived; not remeasured.

All eight error variants remain enabled and failing. No assertion weakened, skipped, or removed.

## Causal diagnosis and contract distinction

`tests/integration/test_herdr_full_flow.py:619–623` supplies a synthetic configured credential in a RuntimeError from the actual NowTool invocation. The prompt is a separate intentional-conversation string. This is **not** a user asking Slo to print the secret.

`tool_execution/executors.py:123–129` catches the exception, logs it, and makes its text the terminal ToolMessage content. `sessions/service.py:5862–5868` forwards stream events to subscribers without redaction. The observed `tool_result` contains the literal configured sentinel. The test adds every session event into its publication scan at line 718; the final assertion at 733 detects that literal. The fresh family run reproduces all eight variants.

The canonical `SLO_HERDR_PUBLICATION_CONTRACT.md:247–260` says **the reporter** must not publish prompts, answers, thinking, tool input/output, authentication data or raw errors; it explicitly notes terminal output is visible to authorized viewers. B §8 (`94.b.1-herdr-reporting-adapter.md:2186–2187`) specifies sentinel absence in argv/logs/sequence files; B §9 distinguishes private restore paths from public report argv/logs/sequence state. Those passages do not themselves establish universal redaction of Slo transcript events. Therefore distinguish:

1. Herdr reporting privacy: no leak was established in snapshots/argv/transport outcomes by this failure.
2. Configured credential disclosure in Slo's session event: actually reproduced, and subject to the user's stricter explicit requirement. It must not be concealed by dropping events from the assertion or describing this as intentional user conversation.

No final contract adjudication against all accepted companion reviews is claimed.

## Important missing prerequisite for the requested tiny repair

The assumed reusable all-provider captured redaction context is not present in the inspected owners:

- `CredentialResolver.operation_credential()` returns the existing task-local capture without I/O.
- `bind_operation_credential` documents an admitted **OpenRouter** credential, or None for a non-OpenRouter operation (`credential_resolver.py:68–83`).
- `redact_openrouter_text` calls `_resolve_openrouter_credential_for_redaction()` on every invocation and filters to OPENROUTER (`credential_resolver.py:102–123`). That helper resolves live credentials (`:126–150`). Simply applying it to every public session event violates the requested no-per-event-lookup condition and would not redact the OPENAI fixture credential.
- Session operation binding uses `_admitted_openrouter_credential` (`sessions/service.py:3420–3422`); the investigated test uses a direct `gpt-5.4` Faux factory. Its resolver patch returns an OPENAI CredentialDAO for **every requested provider**, including the nominal openrouter variant (`test_herdr_full_flow.py:666–673`). The four labels are sentinel categories, not four correctly typed provider admissions.
- The executor has no existing credential redactor. Changing its terminal ToolMessage would also change model-visible content, contrary to the requested private/public split.

Thus a one-line public-event call to the existing redactor is not a valid fix. A compliant correction needs to identify and reuse a real runtime credential capture for direct/pool paths, or explicitly establish the missing capture ownership without duplicate resolution or a new secret store. That work has not been implemented or verified. This report does not claim it is impossible within the authorized owners.

## Remaining work / disposition

**INCOMPLETE**, not bounded READY. The fresh RED is established; no GREEN or repair exists. Remaining: finish required context/accepted-review reading, resolve direct/pool capture ownership and typed fixture scope, implement a narrow public-event correction without changing ToolMessage/history/error semantics, prove zero lookup and rotation, run all eight regressions plus surrounding tool/session/history/headless cases and own static checks. Complete high-level viewer outcomes, actual session failure, config-label/rotation/privacy family remain outstanding exactly as in handoff 129.

Context reading was partial: handoff, fixture/test family, selected production owner sections, B tests/acceptance and publication-contract passages, KB entry/index/gotchas were read. A combined skill read truncated; mandatory full-reading closure is not certified. No claim of independent review, full T6 acceptance, live compatibility, or full-suite cleanliness.
