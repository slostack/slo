# T5 combined handoff 117 — INCOMPLETE (bounded technical evidence)

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 117, retries 0. Effective turn/dispatch budgets unlimited. No agents or production edits. Only the two requested test files and local evidence/status documents were changed. Historical receipts preserved; no commit/push/PR/reset/clean/stash, canonical/global/live/other-worktree edits.

## Delivered

- `tests/tui/test_herdr_multiple_viewer_owners.py`: existing eight cases retained. In all four registry-fault cases the actual `_write_adapter_line` sink now raises on the exact `Viewer cleanup incomplete.` diagnostic. The sink invocation is asserted. The unchanged real-resource helper still asserts both actual registered workers, exact join list, queued reservation never admitted, repeated replacement-caller cancellation, gate-dependent finalizers, old reporter close, persistent/successful drain, GC quarantine and unchanged command capture.
- `tests/tui/test_herdr_all_owner_cutoffs.py`: seven scenarios × two final drain outcomes × healthy/throwing diagnostic = 28 cases. Refusal notice faults preserve exact claimed bytes/restart behavior. Every case additionally delegates the actual preparation cleanup then raises an original cleanup fault; healthy/throwing cleanup diagnostic is independently observed. Spies delegate actual owners and independently assert viewer drain, preparation, selected close (twice: shutdown plus cached final cleanup), selected final cleanup, retired final cleanup/local drain, unsubscribe, lease release and both timer stops. Existing admitted normal/operator-abort and original/displaced ack assertions remain intact.

No production RED was found. The new owner assertion initially expected selected close once; actual final cleanup intentionally calls the idempotent gateway again. `t5-117-owners.log` preserves all 28 assertion failures, not a product defect. Corrected exact count is two. No production behavior or deadlines changed.

## Whole finite combined map

Canonical C = `94.b.2-session-publication-and-native-restore.md`; D = `94.c.1-herdr-workflow-visualizer-and-acceptance.md` under the user-supplied read-only Herdr root.

| Obligation | Current executable evidence | Qualification |
|---|---|---|
| C7.9/7.14 T3-F1 claim await | `test_all_owner_claim_pending[claim_pending-*]` | Exact claimed bytes/no ack/no task; running handle; fresh same-ID mounted poll no invoke |
| C7.9 durable advance cutoff | `...[workflow_advance_pending-*]` | Completed handle retained; claimed bytes/no ack/task; restart refuses replay |
| C7.9 final registration cutoff | `...[before_chat_registration-*]` | Gateway called but no task; completed handle/claimed bytes retained |
| C7.9 admitted execution, original ack | `...[registered_original_store-*]`, `...[registered_abort_original_store-*]` | Same admitted task, no shutdown cancellation, normal/explicit Faux-stream abort |
| C7.9 captured displaced ack | `...[already_registered-*]`, `...[registered_abort-*]` | Original ack exactly once; displaced store not created; done bytes exact |
| C7.13 quarantine / C7.14 F2 | unchanged `exercise_retained_viewer` inherited in every case | Same child three reap attempts; sequence contention; strong GC retention; repeated `/new` suppression; no wire retry |
| C7.13 persistent final drain | persistent cases in both files | Public teardown remains pending; fixture cleanup is NOT graceful success |
| D7.1/7.4 actual multiple workers | eight `test_multiple_registered_viewers_survive_first_join_fault` cases | Real scheduler/session/launcher/shared transport; one admitted split, second queued reservation |
| D registry first join failure | four registry-fault cases | Exact first/later join list retained; throwing diagnostic added |
| C7.9 replacement caller cancellation + D ownership | four cancel-replacement cases | Public `/new` caller cancelled repeatedly; both real worker finalizers join before adoption |
| C7.14 F4 diagnostics | both files above | Actual sink throws; original registry/preparation failures retained; no production correction needed |
| C7.14 EVERY-owner identity/order/detail | **PARTIAL** | Added independent invocation checks, but timer `assert_called` includes deliberate pre-shutdown inbox stop; lease check lacks exact captured ID/owner kwargs; retired reporter-close is inherited task-state evidence, not new independent call assertion. No exhaustive exact owner-order claim. |
| C7.9 exact no-user-history/no-invoke on refusal | **PARTIAL** | Restart invoke spy and no-task assertions retained; this composition lacks an independent original-session invoke/history assertion. |
| Read reconciliation | See below | Canonical requested ranges closed; broader frozen routing and affected-test audit still not fully closed |

113–115 historical missing original-store/restart/persistent branches are superseded by actual 116 test contents, not inferred from prose. 116 multiple-worker and caller-cancellation OPEN rows are superseded by the actual eight-case helper/test implementation. No new T6 matrix is invented.

## Explicit reads

Fresh complete reads: actual AGENTS.md (cat tail 75–1013 plus read 1–80), CLAUDE.md, root RESEARCH.md, docs/RESEARCH.md 1–633, routing.md, scope-plan.md, Makefile, pyproject.toml, .python-version, t1-dao-check.sh; tests/state_isolation.py, tests/conftest.py, activation-composed fixture module; both owned files, entire retained-viewer helper, combined-cutoffs module; reports 113,114,115 and both 116 reports; KB Welcome, slo/README and gotchas.

Canonical fresh closure: C605–1134,1135–1684,1685–EOF (all C7.9–7.14 plus tests/acceptance tail); D1–EOF including registry and platform drain; tasks2401–3060 and3061–3720 (entire T5 attachment); accepted independent-review-turn4 and finalization-receipt in full. These reads are not product acceptance evidence.

Fresh skills: engineering routing/ownership/testing; coding-rules, code-test-loop, shared declarative; Python root/named arguments/docstrings/declarative/Faux testing; Textual; workflow SKILL and exact code-test-review workflow. The aggregate skill read truncated only the routing prefix, subsequently reread in full.

Concrete remaining reads (not an unspecified audit): frozen routing's code-design-principles, naming-and-clarity, test-verification-policy, solution-design, locate-knowledge-base, application-structure, build-domain-features, build-application-services, switch-environments-and-run-tests and product Typer skill; KB skills-and-kb/tui-cli-session/headless-workflow pages; existing T2/T4 multiple-parent/platform tests and full inbox-disposition original-session/history checks. App source inspected at 950–1059,2395–2630,2820–2930 and session close/final-drain2490–2659; complete affected source/test read closure is not claimed.

## Executed verification

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`, pyenv confirms `/root/.pyenv/versions/slo-harness/bin/python`, Python3.11.7; `make test-env` = fallback. No installation/env-file mutation. All test tool timeouts 1800 seconds, not production deadlines. Existing Faux factory, HERDR stripping/default-disable, independent registered fake executable identity guard and terminal guard retained.

Receipt stems below are under this directory, with `.log` and `.exit`. Pytest prefix: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (adds 62 DAO/projection cases; totals overlap).

| Stem | Arguments / command | Result |
|---|---|---|
| t5-117-multi | tests/tui/test_herdr_multiple_viewer_owners.py | 70 passed, exit0 |
| t5-117-notices | all_owner_cutoffs + multiple_viewer_owners + viewer_retention_composed | 101 passed, exit0 |
| t5-117-owners | all_owner_cutoffs | 28 failed /62 passed, exit1; invalid once-only spy expectation |
| t5-117-owners-green | all_owner_cutoffs | 90 passed, exit0 |
| t5-117-combined | same three files | 101 passed,18 warnings,25.01s, exit0 |
| t5-117-surrounding | arguments below | 800 passed,103 warnings,284.66s, exit0 |
| t5-117-test | PYENV_VERSION=slo-harness make test | 8205 passed,19 deselected,626 warnings,757.15s, exit0 |
| t5-117-smoke | PYENV_VERSION=slo-harness make smoke | 288 passed,2 warnings,2.79s, exit0 |
| t5-117-lint | PYENV_VERSION=slo-harness make lint | 295 errors/60 files,792 checked, exit2; UNWAIVED |
| t5-117-black | changed/new src/tests Python paths via git ls-files, poetry run black --check | 140 files unchanged, exit0 |
| t5-117-diff | git diff --check | silent exit0 |
| t5-117-coreutils | dpkg -V coreutils | silent exit0 after full/smoke checks |

Surrounding arguments:
```text
tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows
tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py
tests/agents/slo_agent/herdr/test_session_lifetime.py
tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py
tests/agents/slo_agent/herdr/test_final_lifetime_closure.py tests/cli/test_headless_retained.py
```

Lint comparison: unsorted diagnostics reorder (124-line diff retained). Sorting full ` error:` lines against t5-113-lint.log gives byte-identical diagnostic inventories: `t5-117-lint-sorted-comparison.log` silent, exit0. Thus exact 295/60 persists, no ignored or waived diagnostics. Full suite warnings include existing unawaited AsyncMock warnings; pass is not warning-free.

## Verdict

**INCOMPLETE**, narrowly: strengthen exact captured-lease/timer/retired-reporter assertions, original-session refusal invoke/history proof, and finish the explicitly listed routing/affected-test reads before combined-family READY. Current tests and full runtime gates pass; no runtime defect established. T6's full64/two-process/docs/live acceptance remains distinct and is not the reason for this verdict. Parent next remains whole-T5 author check, then T6; independent review/completion not performed here.
