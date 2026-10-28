# CI repair — independent EARLY Code+Test feedback

**Verdict: REVISE.** Advisory early integration review, not final Review, Completion, CI approval, or live acceptance. Reviewed 2026-10-21 against HEAD `4ab10b02727d433779233cd758e35875b09acd78` plus the five-file working diff. No production/test files edited. No subagents, full suite, commits, pushes, live Herdr, or real terminal launches.

Accounting: current continuation dispatch **2**, previous dispatch **1** was parallel; inherited turn/dispatch budgets are unlimited. Historical counts remain as recorded in `current-ci-repair-plan.md`; this report neither resets them nor invents an exact historical total.

## Scope and authority

Read the current repair plan, all three author reports, actual diff and callers, repository instructions, root/project research, KB Welcome and Slo README/gotchas (no Slo `index.md` exists). Applied the vendored `review-feature-code` **early mode**, engineering routing/ownership/review/testing, Python conventions and hard-rules review, Textual guidance, declarative-method guidance and test-verification policy. Relevant requirements are the repair plan's preserve-all-assertions rule, AGENTS.md's one observation timer/owner and ordered teardown, and Herdr 94.b.2 replacement/captured-delivery contracts (§7.8–7.9). No unrelated CLI verb, database, provider, or feature-wide audit was introduced.

The concurrent separation is appropriate: A owns the headless fixture, B app observation ownership, C viewport/layout. Continue those independent repairs concurrently; perform integrated gates after fan-in. Ordinary defect corrections below need **no user decision**.

## Requirement / evidence map

| Repair contract | Assessment | Evidence / remaining work |
|---|---|---|
| Headless child-control fixture implements reporting lifecycle | Missing-method cause correctly repaired; fixture results still need a truthful contract | All 25 child-abort tests pass independently; ER-04 |
| One mount observation timer, old projection discarded | Normal paths improved, not complete ownership repair | Observation class: 13 pass / 1 fail; ER-01 and ER-02 |
| Exact coordinator → service → sink → panel teardown | **Failing production path**, not conflicting test | Existing assertion fails before unmount; ER-01 |
| Delivery failure cannot orphan observation | **Not satisfied** | Real mounted failure diagnostic leaves service unclosed even after unmount; ER-02 |
| Saved viewport survives delayed layout | New deferred-render case passes; six twenty-child variants pass | Useful bounded evidence, not complete race proof |
| Reachable vertical offset survives legitimately absent horizontal scrolling | **Regressed** | Settled narrow-content diagnostic remains `(0,0)` instead of clamped `(0,5)`; ER-03 |
| Delayed horizontal-scrollbar appearance triggers restore, user navigation wins | Wiring looks appropriate; committed test does not isolate this condition | Require deterministic scrollbar-only regression and navigation invalidation; ER-03 |
| Full integrated/static/CI gates | Pending by design | Not run in this early review; no baseline waiver |
| Live installed Herdr compatibility / acceptance | User-deferred, unverified | Unchanged |

## Findings and closure conditions

### ER-01 — High: double close resets the persistent panel before `/new` returns

**Where:** `src/tui/app.py:1352,1377,1390–1403,2715,2857`; `tests/tui/test_workflow_session_list.py:534–573`; `ci-repair-observation.md`, failure 3 diagnosis.

**Actual call chain:**

```text
_start_new_session
  → retained replacement commit
    → _finish_replacement_commit
      → adopt candidate
      → _close_workflow_observation
          coordinator.close → service.close → sink.dispose → panel.reset
      → _finish_replacement_ui
        → _finish_replacement_runtime
          → _ensure_workflow_observation_bound (identity was cleared)
            → _bind_workflow_observation
              → _close_workflow_observation (all owner slots now None)
                  → panel.reset AGAIN
              → construct/start successor observation
  → exact assertion at line 569, still INSIDE async with app.run_test
```

`_close_workflow_observation` documents “a no-op when unbound” but unconditionally resets the panel. The assertion sees `['coordinator', 'service', 'sink', 'panel', 'panel']` **before context exit**. Unmount has not caused the failure. The `[unmount]` variant asserts separately after context exit at line 573. There is no irreducible contract conflict and no reason to change `order` into `order[:4]`, skip unmount cleanup, or make the panel per-owner.

**Correction:** make close genuinely idempotent for an absent observation binding: no panel reset when there is no owner to retire. Close and clear the actual coordinator/service/sink together through one ownership path; reset once after that owner's teardown. Keep the explicit replacement close so old observation is retired even when successor runtime startup is suppressed by shutdown. A later bind may safely call an unbound no-op close.

**Closure:** both existing teardown parameter cases pass with their exact assertions unchanged; one mount timer and old-projection tests remain green. Add explicit repeated-unbound-close evidence if the corrected ownership path is not already exercised sufficiently. Correct the author report's false unmount/conflict diagnosis. No operator decision is required.

### ER-02 — High: inbox rollback still drops the observation service while its coordinator remains alive

**Where:** `src/tui/app.py:1190,1236–1243,1353–1377,1391–1403`; `tests/tui/test_herdr_init_rollback.py:264–320`; `src/tui/workflows/progress_coordinator.py:181–200`.

The new session-id bookkeeping does not establish a healthy binding. Delivery initialization captures the **same** `_workflow_app_service` used by the coordinator. Its rollback clears that app slot without closing the service or clearing the coordinator/sink/binding ID. The newly added ensure helper sees the matching ID and returns despite the missing service. On unmount, coordinator close stops reads but does not own `service.close`; the app now has no service reference to close.

**Independent mounted diagnostic:** with a real temp-root session and `SessionInboxStore.ensure_session_inbox` raising a synthetic error:

```text
ROLLBACK: app_service=None, binding_id_matches=True,
          coordinator_closed=False, service_closed=False
ENSURE:   same_coordinator=True, app_service=None
AFTER UNMOUNT: coordinator_closed=True, service_closed=False
```

This is a directly affected pre-existing rollback edge left unresolved by the repair, plus a false “intact binding” inference in the new helper—not evidence that all Herdr initialization behavior was newly broken. The normal `/new` correction does not cover it. The existing rollback tests assert the app slot is None, but do not prove the original observation service was closed. While mounted, the coordinator can keep painting through a service unavailable to app child-abort/dismiss routing; its caches/other owned work miss canonical teardown.

**Correction:** keep one authoritative observation binding. Delivery rollback must retire the captured observation owner through its full close path when clearing it, or preserve its separately owned lifecycle reference until that close occurs. Preserve the existing captured-identity checks: rollback must never close or clear a successor published during the lease-release await. Keep lease/timer cleanup and refusal behavior, including current assertions that failed delivery leaves its app service slot absent. Do not merely reset the new string ID and overwrite the orphaned service on the next bind.

**Closure:** extend the mounted inbox/timer failure cases to retain the real original coordinator/service and assert its timer/read joined, service closed, sink disposed and panel reset exactly once; subsequent unmount must not leave it open. Rerun successor-displacement cases in `test_herdr_init_ownership.py` and `test_herdr_init_rollback.py`. Preserve historyless observation and all exact current assertions.

**Is the new ID/ensure helper necessary?** No demonstrated requirement needs it. A simpler arrangement can remove the redundant initial bind in `on_mount` and bind once at the shared retained `_finish_replacement_runtime` boundary, which already runs for mount and replacement before delivery/reporting. Keep explicit old-owner close during commit and make the unbound close inert. This preserves the Herdr submission gate, runtime cutoff checks, candidate-before-close rule and irreversible adoption. Check the mount phase-order tests and historyless path. If the author retains the helper instead, that is acceptable once real ownership/rollback correctness is proved. Removing it is **not** a cosmetic acceptance requirement; a matching session-ID string alone is insufficient evidence of a valid trio.

### ER-03 — Medium: horizontal unavailability now prevents valid vertical restoration

**Where:** `src/tui/workflows/dao.py:746–764`; `src/tui/workflows/session_progress_screen.py:260–270,517–545`; new test at `tests/tui/workflows/test_session_progress_screen.py:952–998`.

The deferred-render guard is sensible for provisional content. The separate `self.x > 0 and not log.allow_horizontal_scroll` return is too broad: no horizontal scrollbar can be a **settled valid layout**, not a race. A reopened view can be wider, or bounded/refreshed content can be narrower than when the viewport was saved. In that case x should clamp to zero while reachable y still restores. The new early return suppresses both axes indefinitely.

**Independent reproduction using the existing real `_ScreenHost`:** saved viewport `(4,5,following=False)`, 120×40 screen, `_entries(count=40,width=1)`, after layout settles:

```text
size_known=True, deferred=0, max_scroll=(0,98), allow_x=False
scroll=(0.0,0.0), pending=x=4.0 y=5.0 following=False
Direct restore returns False and still leaves scroll=(0.0,0.0).
```

Previously the normal clamping path applied y=5. Keeping unmet x intent pending is consistent with the existing convergence policy; preventing reachable y from landing is not.

**Correction:** distinguish provisional content from a settled zero horizontal range. Once content is measurable, apply reachable/clamped axes even if the horizontal bar is absent, and only report success when the requested reachable movement actually landed. Keep pending intent for genuinely blocked or clamped offsets under existing paint/navigation guards. Do not “fix” this by declaring every restore successful or dropping the new scrollbar watcher.

**Required regression coverage:**

1. Settled narrow content with saved x>0/y>0 restores y and clamps x, including reopening after terminal widening or equivalent content shrink.
2. Sufficient horizontal range with `_size_known=True`, no deferred renders, but horizontal scrolling temporarily disallowed: restoration remains pending, then **only scrollbar availability changes** and it lands exactly. Isolate this from `virtual_size`/`LayoutChanged` retries so removing the new watcher fails the test.
3. User navigation before that scrollbar transition cancels pending intent; the late transition cannot snap back. Retain existing deferred-render, navigation, pending-across-paint, and six fleet parameter assertions.

The committed new test forces `_size_known=False` and explicitly posts `LayoutChanged`; it proves useful first-layout convergence, but does not independently prove the scrollbar-only race. The author's congestion/stress experiments are reported evidence, not a retained deterministic regression or reviewer-reproduced CI environment.

### ER-04 — Medium: headless lifecycle fixture should return real typed drain outcomes, not fabricated AsyncMock objects

**Where:** `tests/cli/test_headless_child_abort.py:593–595`; consumer `src/cli/headless.py:154–167`; session contract `src/agents/slo_agent/sessions/service.py:2604–2644,2725–2744`.

The missing protocol methods explain the seven original child-control failures. No production runner repair is indicated. However, bare `AsyncMock()` returns another mock when awaited, not the documented `None` activation result or `HerdrReporterCloseOutcomeDAO`. Such an object fabricates arbitrary attributes and truthiness; recording calls is not “fail closed.” Matching another old fixture is not contract evidence.

**Important qualification:** this runner currently **ignores** both close return values and unconditionally awaits final cleanup. Therefore these mocks are not presently causing a truthy `resources` branch or proving an actual production drain violation. The 25 passing child tests are meaningful child-control evidence, **not reporting-resource drain evidence**.

**Correction:** use a small typed inert recording stub, or explicitly configure the existing mocks: activation returns None; close and final cleanup return `HerdrReporterCloseOutcomeDAO(replacement="safe", resources="drained")` for this resource-free fixture. Assert activation/close/final-cleanup awaits at the relevant runner normal/cancel boundaries, reusing existing lifecycle tests instead of expanding the child-abort suite into a Herdr test matrix. No production permissiveness or special mock handling.

**Closure:** child-control module and nearby headless lifecycle/retained-cleanup tests remain green with explicit return contracts and no pending/unretrieved task exceptions. Correct the report's “fail closed” characterization.

## Verification performed independently

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Reviewed `environments/tests.env`; used its local model (`gpt-6.1-sol`), with `SLO_HERDR_DISABLED=1`, `SLO_AUTO_VISUALIZE=0`, `PYTHONPATH=$PWD`. `pyenv which python` resolves to `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. Normal pytest isolation fixtures remained enabled.

1. `python -m pytest -q tests/tui/test_workflow_session_list.py::TestObservationLifecycle tests/cli/test_headless_child_abort.py tests/tui/workflows/test_session_progress_screen.py`
   - **Exit 1: 1 failed, 89 passed, 2 warnings, 28.43 s.** Sole failure: exact teardown assertion `[new_session]`, line 569.
2. `python -m pytest -q tests/integration/test_workflow_progress_tui.py::TestTwentyChildFleetJourney tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_init_ownership.py tests/cli/test_headless_herdr.py`
   - **101 passed, 4 warnings, 54.02 s.** Includes all six fleet size/theme variants. Existing tests passing does not negate the unasserted rollback defect.
3. Two bounded in-memory diagnostic scripts, no source/test edits:
   - Existing real progress host with saved `(4,5)`, narrow 40-entry snapshot: settled y loss reproduced (ER-03).
   - Real mounted temp-root session, synthetic inbox-init failure, Faux factory, retained coordinator/service references: orphaned service and false ensure success reproduced (ER-02).
   - Both exited 0 after printing the defect state; these are diagnostic reproductions, **not passing acceptance tests**. All state was scoped to `TemporaryDirectory` with HOME/SLO_HOME redirected before app imports.
4. `git diff --check`: exit 0, no output. `dpkg -V coreutils`: exit 0, no output after diagnostics and focused suites.

No full suite/static/smoke or exact-SHA CI rerun performed here. No CI-default-model rerun independently performed; author claims remain distinct. No stress processes launched by this reviewer.

Reviewed file SHA-256s (freeze identifiers; re-review affected evidence if changed):

```text
f45cd66277b5a2920784fe37837e279d637bea12c678751f3f7b2405ee387fad  src/tui/app.py
76bb98f08e50c2a1c1c9573a69b5168494a3c756b098d50ef6176d848af35b06  src/tui/workflows/dao.py
7ea3647368a31dd82a1b3f3440680362a58f19c7ad225c739e20ed340574a11a  src/tui/workflows/session_progress_screen.py
835fa7992343cb57fa7390b6e49b3906cee266ddbb4635f776e9167119f2c694  tests/cli/test_headless_child_abort.py
5b6eeaa6e546696e10eaa44ca85092a5ce50dcbf747a490b82d9b599bf092258  tests/tui/workflows/test_session_progress_screen.py
```

## Fan-in checklist

- [ ] B: fix ER-01 and ER-02 together at the existing observation owner, preserving exact assertions and captured-successor safety.
- [ ] C: fix ER-03 and retain a deterministic scrollbar-only race regression.
- [ ] A: make reporting fixture results explicit (ER-04), without production changes absent new evidence.
- [ ] Update the three author receipts; retract the impossible-contract premise rather than requesting assertion relaxation.
- [ ] Re-run affected focused tests, then the plan's full integrated/static/smoke gates after final production edits; repair newly found failures without exclusions.
- [ ] Obtain independent final Review and Completion afterward. This early report grants neither.

Hard-rules pass: changed calls/types/layer responsibilities and lifecycle/test claims inspected. The defects above concern ownership, behavior and evidence, not a demand for broad app refactoring. The pinned Textual private-layout dependency is acknowledged maintenance coupling, not by itself a blocker. No product/specification question is outstanding for these corrections. Live acceptance remains explicitly user-deferred.
