# T5 app registry 101 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 101, retries 0. User budgets for turns and dispatches unlimited. No agents dispatched. No commit/push/PR/reset/clean/stash, specification, global configuration, live Herdr or other-worktree edits.

## Changes actually made

- `tests/tui/test_herdr_inbox_cutoffs.py`: explicit non-null timer assertion before stop. Existing assertions preserved.
- `tests/tui/test_herdr_prompt_registration.py`: Black formatting only.
- `src/tui/app.py`: pending-task dictionary keyed by parent; synchronous scheduling captures the selected session, rejects closing/delivery-quiescing state and deduplicates pending requests. Completion callback retrieves exceptions and removes only an identical task. Worker checks captured identity and lifecycle before calling existing `VisualizerLauncher.launch_async`.
- `tests/tui/test_herdr_viewer_registry.py`: mounted Faux-backed initial registration/deduplication/completion test. Worker is replaced by an async barrier in this test. This is orchestration evidence, NOT actual gateway/registered-fake-Herdr integration proof.

The new registry is NOT connected to either existing caller. Its current worker discards the outcome. This is a partial foundation, not a ready finite owner family. Existing attached/detached runtime pathways remain unchanged. No second attempt ledger or coordinator was added.

## Required continuation

1. Expand tests for synchronous capture before execution, replacement identity, closing/quiescence, done-callback identity mismatch/cancellation/exception and failing notice renderer.
2. Add registry cancellation/join under existing replacement and shutdown ownership BEFORE old session teardown. Revoke scheduling/admission before awaiting. Explicitly reconcile transient session-transition gate with current `_delivery_quiescing` rather than assuming these concepts are equivalent.
3. Add guarded, best-effort outcome rendering and wire attached events to scheduling. Prove all five outcomes, auto-off, no Herdr fallback and no late notice/focus/mutation.
4. Mounted real async selector/gateway tests with registered fake Herdr and platform thread barriers; prove cancellation joins before replacement/unmount, including repeated cancellation. Existing selector receipt is not app-lifetime evidence.
5. Detached typed service/renderer consolidation remains NEXT unit. Combined inbox F4/T6 and independent review remain later.
6. Run full make test/smoke/lint after integration. Existing baseline findings remain unwaived.

## Receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`, existing fallback script, no venv/install changes. Prefix for pytest receipts: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (includes mandatory DAO/projection tests).

| Receipt prefix | Command suffix / result |
|---|---|
| t5-101-minor-black | `poetry run black tests/tui/test_herdr_prompt_registration.py`; exit 0 |
| t5-101-minor-test | `tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_herdr_prompt_registration.py`; 99 passed, 19 warnings, exit 0 |
| t5-101-registry-red | `tests/tui/test_herdr_viewer_registry.py`; 1 failed, 62 passed, 2 warnings, exit 1: missing registry worker |
| t5-101-registry-green | new registry test plus `tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py`; 197 passed, 2 warnings, exit 0 |
| t5-101-black | `poetry run black --check src/tui/app.py tests/tui/test_herdr_viewer_registry.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_herdr_prompt_registration.py`; four unchanged, exit 0 |
| t5-101-diff | `git diff --check`; silent exit 0 |
| t5-101-coreutils / coreutils-final | `dpkg -V coreutils`; silent exit 0; also silent after registry runs |

Full logs and exit files retained beside this document. Full make/static gates not run in this partial continuation; no claim of new-error-free mypy or whole-suite completion.

## Reading and limitations

Read gateway-final-100, routing/scope plan, whole canonical D including 7.1–7.5/A2 and D01/D02/D03/D08 task samples, Makefile, KB Welcome/slo README/gotchas, affected app registration/callers/replacement/shutdown and existing selector tests. Engineering routing/testing/ownership, Python root, coding rules/cadence and Textual/workflow guidance consulted. Bulk skill output truncated; complete prerequisite ingestion, C mounted-lifetime reread and accepted-review reread are NOT claimed complete. AGENTS/CLAUDE/research supplied context was available; a shell concatenation redirected actual files rather than displaying them, so it does not establish fresh full read coverage. Finish required reads before dependent integration.

**Verdict: INCOMPLETE.** Only initial registration/done-callback foundation and authorized minor corrections landed. Do not connect this worker to runtime callers until outcome handling and lifetime drain are tested and implemented.
