# T5 combined 114 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 114, retries 0. User budgets unlimited; no agents launched. No production changes, external actions, canonical/global/other-worktree edits or git mutations. Historical work preserved.

## Delivered evidence

`tests/tui/test_herdr_viewer_retention_composed.py` exposes optional `before_shutdown` and `registry_fault` test-fixture inputs. Defaults preserve all 113 cases. The new `tests/tui/test_herdr_all_owner_cutoffs.py` uses that actual resource fixture, not a mock reporter/transport/lease.

Three cases compose an enabled real registered fake CLI split child retained across `/new`, identical shared transport/sequence lease, repeated-new suppression and GC retention, with current occupied registry and actual inbox storage:

| Cutoff | New direct assertions |
|---|---|
| claim_pending | Real claim finishes after shutdown prefix; exact bytes remain claimed; no ack/task; workflow remains running |
| workflow_advance_pending | Real terminal workflow write completes before cutoff; completed state retained; exact claimed bytes/no ack/task |
| before_chat_registration | Synchronous notice boundary seals admission; completed workflow and exact claimed bytes retained; no ack/task |

All three also run 113's successful final-drain assertions: current final cleanup completes while retired reap is held, repeated shutdown cancellation cannot abandon cleanup, same child reaped on final release, same lease unlocked, no additional wire commands. Current registry worker's cancellation finalizer takes the real submission gate and completes without deadlock. This current worker is a barrier coroutine; the retired viewer is the actual gateway/CLI resource. Do not call both workers real CLI launches.

Initial increment failed because the inherited registry join fault correctly sets `_replacement_delivery_safe=False`, leaving no successor inbox timer. This was a test composition error, NOT production RED. Separating registry-fault injection from actual reap retention enables genuine successor inbox admission without overriding application state. No production fix was warranted.

## Executed receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`. Pytest prefix:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
Helper adds 62 DAO/projection cases. Counts below overlap; no additive coverage claim.

- `t5-114-fixture`: retention file, 65 passed, exit 0.
- `t5-114-initial`: new claim + retention, 1 failed / 65 passed, exit 1; exact failing timer assertion retained.
- `t5-114-claim`: corrected composition, 66 passed, exit 0.
- `t5-114-refusal`: three refusal + retention + combined110, 78 passed, exit 0.
- `t5-114-occupied`: add current gate-dependent registry worker, same partition 78 passed, exit 0.
- `t5-114-surrounding`: **767 passed, 87 warnings, 261.64s, exit 0**, timeout 1800. Arguments: `tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py tests/agents/slo_agent/herdr/test_final_lifetime_closure.py tests/cli/test_headless_retained.py`.
- `t5-114-static`: mypy `--follow-imports=silent` on both owned test files: no issues, exit 0. Not whole-repo lint.
- `t5-114-format` then `t5-114-black`: Black check passes both files, exit 0.
- `t5-114-diff`: tracked `git diff --check`, silent exit 0 (untracked tests separately read/formatted/executed).
- `t5-114-coreutils`: `dpkg -V coreutils`, silent exit 0; also silent after each focused subprocess run.

Each named check except formatter has log and exit files. No full make gate rerun: family is not ready. Historical 295 errors / 60 files remains unwaived and was NOT freshly compared in 114.

## Finite remaining family map — not a closed acceptance map

| Required family | Status / evidence boundary |
|---|---|
| Refusal three cutoffs + real retained resource + occupied registry | New three cases pass, as qualified above |
| Already registered + same resource composition, original/displaced ack, operator abort | **Missing**. 110 assertions remain separate, not equivalent |
| Refusal fresh-mounted restart/no automatic replay with same composition | **Missing**; new test checks no reclaim through original store, not full restart assertions from 110 |
| Healthy/throwing diagnostics and exact all-owner independent cleanup call order | **Missing in new composition**; surrounding existing tests are not substituted |
| Persistent retired final drain with same inbox/registry composition | **Missing**; 113 persistent case passes separately |
| Multiple actual workers with first join failure and later joins attempted | **Missing in real-resource composition** |
| Replacement CALLER cancellation while real child held | **Missing**; shutdown cancellation is not replacement cancellation |
| GC one predecessor / sticky successors / shared lease | Executed inherited 113 assertions in all new cases |
| Scoped C7.9–7.14 F1/F4 and D registry, exact T5 samples/accepted reviews read closure | **Incomplete**. C7.14 and scoped source inspected; not all required current canonical ranges/samples/reviews read |
| Full relevant family map, whole suite and exact 295/60 comparison | **Pending**, not waived |
| T6 64 matrix/live acceptance/independent review | Separate later work, not run or claimed |

Read 113, 110 combined and audit, actual three test modules/inbox tests, root research, scope plan, engineering routing/ownership/testing, coding rules/cadence, Python root/declarative/types/docstrings, Faux, Textual and workflow SKILL. KB Welcome/gotchas consulted. An aggregate routing/KB read truncated; required actual AGENTS/CLAUDE/docs RESEARCH fresh-read closure and remaining shared declarative/routing/KB index/canonical slices were not completed. Supplied prompt context and historical read receipts are not claimed as fresh closure.

**Verdict: INCOMPLETE.** Three useful composed refusal regressions landed and surrounding checks pass. The requested four-cutoff/all-owner family is not complete; no READY, full-64, T6, full-suite or independent acceptance claim.
