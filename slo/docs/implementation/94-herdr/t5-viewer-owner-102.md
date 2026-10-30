# T5 viewer owner 102 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 102, retries 0. User turn/dispatch budgets unlimited; no agents dispatched here. No commit/push/PR/reset/clean/stash/global/live/specification/other-worktree edits. Selection and detached-parser owners untouched.

## Changes

- `src/tui/app.py`: shared pending scheduler now checks the existing master auto-visualize predicate before creating a task. Shutdown cancels and joins the registry outside `_prompt_submission_lock`, before reporter close. Drain snapshots parent/task identities, cancels each once, joins via existing `HerdrTaskJoin`, and invokes existing exception-retrieving identity cleanup. It does not clear a potentially newer registry entry blindly.
- `tests/tui/test_herdr_viewer_registry.py`: mounted Faux-backed auto-off refusal regression; mounted shutdown barrier regression whose cancelled worker finalizer acquires the submission gate. Repeated public shutdown cancellation cannot complete before the worker finalizer drains. Both initial reporter close and the session's final cleanup attempt see the empty registry.
- Existing registry capture/dedup test explicitly enables auto-visualize now that scheduler admission honors it.

No attached caller was connected. The worker still discards typed outcomes. Replacement still does NOT drain this registry. Therefore this is safe partial groundwork, NOT the requested cohesive completed family.

## Test-first receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Test prefix:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
The script includes DAO/projection tests, disabled Herdr, mocked-provider test environment and existing suite terminal guard.

| Receipt prefix | Result |
| --- | --- |
| t5-102-gate-red | registry module: 1 failed, 63 passed; scheduler called worker while auto-off; exit 1 |
| t5-102-gate-green | registry + visualizer + launcher + workflows + receive-path + shutdown + replacement: 198 passed, 2 warnings; exit 0 |
| t5-102-drain-red | registry: 1 failed, 64 passed; shutdown never cancelled worker, finalizer barrier timed out; exit 1 |
| t5-102-drain-green | same surrounding partition: 1 failed, 198 passed; test expected one close but actual session performs initial close and final cleanup attempt; exit 1 |
| t5-102-drain-green2 | corrected exact two-close assertion: 199 passed, 2 warnings; exit 0 |
| t5-102-surrounding | prior partition plus auth capture and inbox cutoff/disposition modules: 243 passed, 16 warnings; exit 0 |
| t5-102-black | Black app.py and registry test; exit 0 |
| t5-102-diff | git diff --check; silent exit 0 |
| t5-102-coreutils / coreutils-final | dpkg -V coreutils; silent exit 0 |

Full logs/exit files are adjacent. Full make integration/static gates remain later; no mypy-green or whole-suite claim. Historical baseline failures remain unwaived.

## Continuation required

1. Finish prerequisite ingestion: actual complete AGENTS/CLAUDE/docs RESEARCH reads were supplied in context, not freshly read in full here. Read remaining C 7.9–7.14 and accepted review documents in full. This session read D 7.1–7.5, exact D01/D02/D03/D08 samples, C 7.13 first portion, routing/scope-plan, KB Welcome/slo README/gotchas, Makefile and selected shared/Python/Textual/Faux/workflow skills. Some bulk output truncated; do not claim complete prerequisite coverage.
2. Replacement drain must be designed around actual gate ownership: `_start_new_session` currently holds `_prompt_submission_lock` while `_replace_idle_session_and_clear_queue` joins `_session_replacement_task`. Do NOT simply insert a worker join inside `_commit_replacement_session`: worker finalizers may require that same gate. Reconcile transient transition admission with delivery quiescing and test the real replacement transaction.
3. Add captured-session, post-await lifetime checks; async typed outcome rendering once; safe renderer failure handling and exact failure guard reset. Keep renderer ownership in mind while detached migration remains a separate family; avoid a duplicate permanent formatter/parser.
4. Wire attached sub_agent_spawned to the single scheduler, not direct sync launch. Prove auto-off, opened/submitted/reused/skipped/failed, unavailable/no platform fallback, no late notices after replacement/closing, identity-mismatched callbacks and exception retrieval.
5. Mounted real gateway/temp history/context plus registered fake Herdr attached exact split/rename/run once; platform thread barriers and actual guarded spawn seam; replacement/shutdown registry terminal before old lease close, repeated cancellation. Existing registry tests are orchestration evidence, not this composed acceptance.
6. Detached typed parser migration, broader integration and independent review remain next families. Full make gates are not waived.

**Verdict: INCOMPLETE.** Only master-gate admission and shutdown registry draining landed and passed the bounded surrounding partition. Do not connect runtime callers until replacement lifetime and outcome handling are completed and tested.
