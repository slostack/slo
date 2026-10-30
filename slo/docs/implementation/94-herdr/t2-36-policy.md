# T2-36 policy/accounting TEST lane — READY, family only

No production changes. Exclusive authored file: `tests/agents/slo_agent/herdr/test_policy_accounting_closure.py` (91 cases). This closes the finite policy/accounting assignment, not whole T2, dependency admission, full-feature review or acceptance. Latest whole-package gate is **not green**: a concurrent other-lane cleanup-recovery regression is recorded below. Parent must reconcile that gate.

Budgets unlimited turns/unlimited dispatch; supplied counters preserved: turn1 started1/completed0/historicalpartial1 dispatch23 retries0. No internal dispatch, agents, commit, push, PR, reset, clean, stash, global/live/specification/other-worktree changes. Save/close production ownership remains with the other lane.

## Authority, audit and plan

Read frozen routing/scope-plan, t2-35-integration and t2-code-test; supplied AGENTS/CLAUDE/docs RESEARCH plus root RESEARCH; engineering routing/testing/ownership, coding-rules/code-test-loop, Python root/DAO/declarative/style guidance, KB Welcome and actual slo/README (no index.md), gotchas. Python isolated policy/orchestration plus actual fake-executable transport composition; no database, provider, terminal or TUI changes. The long combined initial reads truncated; relevant routing/scope/Python and code material were recovered separately. This is scoped prerequisite ingestion, not a new claim of complete B/C/D/T1–T6 ingestion.

Canonical reference-only root: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/`. Policy authority: B 7.8–7.11, especially exact binding/confirmed policy and result accounting, B 7.13 correction preserving confirmed same-capture identity; C 7.3/7.8 private publication and exact capture binding. Tasks T2 samples B13–B16 checked against resolved chapter policy; C28/C29 stay other-lane ownership.

Audit first: `reporter.py`, complete `test_reporter.py`, `test_operation_results.py`, `test_t2_remaining.py`. Existing 108-case terminal matrix and 42-case real-lock currentness matrix were **not duplicated or edited**. Plan executed in finite increments: binding/association → release/display ack → spawn/uncertain install → result guards → package/static/safety evidence. Existing-correct behavior was tested coverage-first; no artificial production RED.

## Finite requirement → assertion map

All paths below are under `tests/agents/slo_agent/herdr/`. New names refer to `test_policy_accounting_closure.py`.

| Family / exact B7.11 decisions | Actual assertion evidence | Disposition |
|---|---|---|
| Binding none/same | New `test_nonconflicting_claim_release_policy`, claim/release × absent/same: no release needed, claim allowed, unnecessary release refused. Existing `test_reporter::test_binding_policy` covers bound clear absent/same. | Covered |
| Changed capture/generation/session, withdrawal, wrong release binding, missing publication | New `test_binding_conflict_policy`: six ordinary operations × six cases. Exact release alone allowed for a conflict; wrong release refused; unchanged binding/no admitted effect/no filesystem writes. Missing publication first asserts real DAO rejection, then explicitly constructs defensive helper input via model_copy to exercise unreachable guard. | Covered |
| Confirmed-policy admission | New `test_confirmed_policy`: lifecycle/clear/set/restore × absent/possible/confirmed. Only confirmed same-capture binding admits. Exact restore positive included. | Covered |
| Wrong reference/capture/no saved and generation | New `test_restore_association_policy`: missing ticket save, missing owner save, changed reference/capture/generation; additionally ticket==owner wrong-capture/wrong-generation proves `_matches_save` rather than merely inequality. Same session ID retained. No install ack. | Covered |
| Currentness for every ordinary operation | Existing `test_t2_remaining::test_ordinary_operation_currentness`: 6 operations × current/revision/generation/closing/disabled/no-latest/revoked, real lock/executable; exact admitted/status/zero-entry assertions. | Retained covered evidence |
| Nonmatching/stale release | New `test_release_accounting`: replace/shutdown × nonmatching/stale revision/stale generation. Seed all three acknowledgements and withdrawal; only exact matching release clears them and binding. Nonmatching retains every sentinel. Only matching shutdown sets released; slots cleared. This is direct accounting policy, not an impossible concurrent writer claim. | Covered |
| Partial/final clear/set; current/stale revision/stale generation/closing | New `test_display_acknowledgement`: 16 cases through real durable reservation, lock admission, guarded fake spawn, completion barrier and terminal accounting. Exactly one metadata command, source sequence 1/5000ms TTL; only current final sets display ack; binding retained, semantic acks untouched, admitted slot drained. Partial set is defensive ticket behavior (normal batch emits final set). Existing bootstrap/report_steps proves real multi-patch final selection. | Covered |
| Current lifecycle/current restore and non-ok current/stale results | Existing 108 `test_operation_results::test_terminal_operation_matrix`: 9 operations × 6 statuses × 2 currentness variants; binding/reference/certainty/three ack slots/activation/shutdown flags/terminal slots. Cancellation diagnostics strengthened previously and untouched. | Retained covered evidence |
| Definitive spawn failure prior/no-prior | New `test_definitive_spawn_failure`: claim without prior, claim with prior, restore with prior × current/stale. Real transport with registered guard, injected OSError only at `asyncio.create_subprocess_exec`; observed admission/provisional binding plus explicit reached-refusal marker prevents swallowed assertion errors from faking success. Exact prior object restored, no new ack/JSON/capture, ownership drained and lock free. Restore without prior cannot pass binding admission and is covered by confirmed-policy absence. | Covered |
| Claim after uncertain install | New `test_claim_after_uncertain_install`: actual claim success → fake executable install exit 9 → identity-only claim success, sequences 1/2/3. Exact five-word resume payload only on install; retry omits argv but retains exact possible reference and confirmed identity; restore ack remains absent, lifecycle ack becomes truthful. No mocked invoke or fabricated install result. | Covered |
| Suppressed/not admitted/wrong ticket/duplicate | New `test_unowned_result_cannot_account`: preserves another admitted ticket, prior binding, current binding and empty ack/diagnostic state. Existing reporter `test_terminal_accounting[duplicate]` proves completed ticket cannot account twice; bridge refusal test proves admission object cannot be reused. | Covered |

No unresolved production defect found in these families. No blanket “full matrices pending” applies to this finite assignment. Save/adoption/close, transport lifetime diagnostics, worker/rename, projection/privacy and remaining T2 acceptance are separate assignments, not certified by this map.

## Exact execution evidence

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; `make test-env` = fallback. Unchanged safe `t1-dao-check.sh` sources no dev environment, defaults HERDR disabled; root test isolation strips inherited settings. It adds test_daos/test_projection to every invocation. Only registered temp-owned regular fake files, inode/containment checked; no system symlinks, live Herdr/provider/window or unrelated file edits.

Command prefix `bash docs/implementation/94-herdr/t1-dao-check.sh`; suffixes and results:

| Receipt prefix (all have .log/.exit) | Suffix / result |
|---|---|
| t2-36-policy-first | new file + test_reporter.py + test_t2_remaining.py: **6 failed, 276 passed**, exit 1. Test construction errors: ordinary missing-publication ticket rejected by DAO before helper. Corrected to assert rejection then explicitly test defensive guard. Not a production RED. |
| t2-36-policy-binding | same suffix: **282 passed**, exit 0 |
| t2-36-policy-ack | new file + test_operation_results.py: **247 passed**, exit 0 |
| t2-36-policy-spawn | new file + test_operation_results.py + test_reporter.py: **346 passed**, exit 0 |
| t2-36-policy-guards | new file + test_operation_results.py: **261 passed**, exit 0 |
| t2-36-policy-package | `tests/agents/slo_agent/herdr`: **729 passed, 4 warnings**, exit 0, 46.62s; before final reached-refusal assertion strengthening and concurrent new test |
| t2-36-policy-final-package | same package: **1 failed, 729 passed, 4 warnings**, exit 1, 45.85s; exact other-lane failure below |
| t2-36-policy-final-family | new file + test_operation_results.py + test_reporter.py + test_t2_remaining.py: **426 passed, 2 warnings**, exit 0, 6.81s, final authored test bytes |

Every file suffix above is prefixed `tests/agents/slo_agent/herdr/`. Final Black: `poetry run black --check tests/agents/slo_agent/herdr/test_policy_accounting_closure.py`: **1 unchanged, exit 0**, t2-36-policy-black.log/.exit. Final `git diff --check`: silent exit 0 (tracked changes); the new untracked test was separately read and Black checked. `dpkg -V coreutils`: **silent, exit 0**, t2-36-policy-coreutils.log/.exit. Source/test SHA256 snapshot in t2-36-policy-hashes.txt; concurrent package additions mean counts are not a frozen whole-worktree certificate.

No long full gate, make smoke or lint run. Historical 301 errors/64 files remains unwaived and is not claimed green. Full-feature independent review later.

## Concurrent package failure — report to parent, do not edit

`test_final_lifetime_closure.py::test_retained_cleanup_emits_one_recovery_after_actual_drain`, line 305:

```text
E AssertionError: assert ['herdr_cleanup_unavailable'] ==
  ['herdr_cleanup_unavailable', 'herdr_cleanup_unavailable_recovered']
E Right contains one more item: 'herdr_cleanup_unavailable_recovered'
```

This test appeared between the two package runs; it is outside this lane's exclusive file. Full failure output retained in `t2-36-policy-final-package.log`. Its cleanup reaches drained resources and releases the lease, but the recovery message is absent. Parent/owning lane must resolve it at the transport's successful retained-drain diagnostic boundary without changing sticky uncertainty or emitting recovery on persistent failure. No production fix or assertion weakening performed here. Whole-package acceptance remains blocked until that independent defect is reconciled.
