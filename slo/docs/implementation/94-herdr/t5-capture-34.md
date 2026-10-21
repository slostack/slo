# T5 continuation 34 — INCOMPLETE

Capture-family READY is withheld. This continuation adds tested private scalar capture and equality adoption helpers, but **does not wire activation facts or actual policy/persistence commits**. It is not complete T5, session lifetime, or feature acceptance.

## Changes and exact evidence

Only `src/agents/slo_agent/sessions/service.py` and new `tests/agents/slo_agent/herdr/test_session_capture.py` changed in production/test scope. Existing provenance/bootstrap work remains intact.

1. `_capture_herdr_pool` / `_capture_herdr_pool_entry`: ordered tuples, five scalar copies, strict frozen validation and reconstructed mutable-entry provider validation. Tests prove later source list/entry mutation cannot alter capture; reject provider mismatch, short pool, bool priority; None remains None. RED `t5-34-pool-red.log` / `.exit`: 4 failed, 62 passed, exit 1. GREEN `t5-34-pool-green.log` / `.exit`: 170 passed, exit 0.
2. `_capture_herdr_restore` / `_herdr_capture_eligible`: initialized inactive facts, canonical UUID check, configured identity/effective reasoning, private immutable DAO and fail-closed malformed policy. RED `t5-34-capture-red.log` / `.exit`: 1 failed, 66 passed, exit 1. First green attempt `t5-34-capture-green.log` / `.exit`: 1 failed, 170 passed, exit 1 (incorrect positional call to keyword-only UUID predicate). Corrected call; `t5-34-capture-green2.log` / `.exit`: 171 passed, exit 0.
3. `_adopt_herdr_capture`: initialize generation/capture/session identity; compare capture and ID before advancing. Tests prove repeated equal capture/None does not advance; eligibility loss and changed ID do. RED `t5-34-generation-red.log` / `.exit`: 1 failed, 66 passed, exit 1. GREEN `t5-34-generation-green.log` / `.exit`: 171 passed, exit 0.

Every production increment was below approximately 50 lines before running its tests and surroundings. No full gate was run.

All commands used repository cwd and `bash docs/implementation/94-herdr/t1-dao-check.sh`, which includes test_daos.py and test_projection.py. RED adds `tests/agents/slo_agent/herdr/test_session_capture.py`. Every GREEN and final adds:

```
tests/agents/slo_agent/herdr/test_session_capture.py
tests/agents/slo_agent/herdr/test_session_publication.py
tests/agents/slo_agent/orchestrator/test_bootstrap.py
tests/agents/slo_agent/test_session.py
tests/agents/slo_agent/test_session_usage.py
```

Each command redirects complete output to its named log and writes the actual pytest shell status to the adjacent `.exit` before tailing output. Final after Black: `t5-34-final.log` / `.exit`, **171 passed, 9 warnings, exit 0**. Black on changed service and new test: `t5-34-black.log` / `.exit`, exit 0. `git diff --check`: `t5-34-diff.log` / `.exit`, silent/0. `dpkg -V coreutils`: `t5-34-coreutils.log` / `.exit`, silent/0. Baseline lint 300 errors/64 files remains unwaived; no lint-green claim.

## Precise remaining obligations

- Activation-time off-loop actual default-root/persisted-metadata eligibility and cached resolved workspace/plugin paths; no history creation. Current test manually establishes boolean facts; it is NOT activation evidence.
- Path-input fingerprints/out-of-band mutation refusal; current helper copies `_plugin_paths` and must not be considered resolved-path acceptance.
- Real configuration commit wiring at model selection, reasoning changes, prepared snapshot/startup adoption, history ensure/rename creation, and provenance changes. Equality helper tests alone do not establish generation integration.
- Broader exclusion/invalid-input matrix, fully composed Faux config-backed session, no-churn usage/rename/fallback/catalog tests, and credential/history/public-channel forbidden-effect assertions.
- Remaining applicable C/T5 sample and full selected-skill reading: some bulk reads truncated. Consumed routing/scope plan, root research, supplied docs research, shared engineering/coding/workflow guidance, relevant DAO/service snippets, actual session/bootstrap/DAO and C capture/eligibility/C7.10/C7.11 portions. This is not a full required-reading completion claim.
- Publication, attention, activation/close, TUI/headless/scheduler/viewer integration and future full gates remain separate unfinished work.

No agents, commit/push/PR, destructive Git commands, global/live/spec/other-worktree edits. No providers, Herdr or terminal windows launched. Parent accounting preserved as supplied: turn 1, started 1/completed 0/historical partial 1/dispatch 34/retries 0; unlimited turns and dispatches. No numeric budget stop or independent review claimed.
