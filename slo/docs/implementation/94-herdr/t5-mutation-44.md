# T5 mutation guard continuation 44 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch count 44 supplied by user, retries 0. Unlimited turn/dispatch budgets;
no agents launched. No attention/app/headless changes.

## Owned changes

- `src/agents/slo_agent/sessions/service.py`: establish scalar fingerprint at
  construction; ordinary adoption allows no source changes, reasoning commits
  allow effective reasoning only, model selections allow model/pool/effective
  reasoning only. Check precommit state before supported changes. Observed
  invalidation remains sticky. Capture requires literal `enable_history is True`.
  Preserve original pristine custom-policy verdict for bootstrap permission.
- `src/agents/slo_agent/orchestrator/bootstrap.py`: recheck pristine permission,
  session identity and scalar sources after tool construction, before attachment.
- New `tests/agents/slo_agent/herdr/test_session_mutation.py`: 19 cases.

No other existing test file modified. Existing unrelated changes preserved.

## Evidence

CWD `/root/Code/slo-94-herdr-integration/slo`; approved pyenv interpreter
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; make test-env:
fallback. H = `bash docs/implementation/94-herdr/t1-dao-check.sh` (adds DAO and
projection tests). All receipts have prefix `t5-mutation-44-` here; logs and
exit files retain actual outcomes.

Focused RED commands: H tests/agents/slo_agent/herdr/test_session_mutation.py.
GREEN commands add test_session_capture.py, test_session_publication.py and
orchestrator/test_bootstrap.py.

| Unit | RED | GREEN |
|---|---|---|
| unrelated reasoning/history/pool edits | 3 failed, 62 passed | 120 passed |
| restoring value after withdrawal | 2 failed, 66 passed | 123 passed |
| literal history/provenance construction | 2 failed, 71 passed | first 1 failed/127 passed; corrected 128 passed |
| preexisting effective reasoning | 3 failed, 73 passed | 131 passed |
| first activation postbuild edits | 2 failed, 76 passed | 133 passed |
| removed custom prompt | 1 failed, 79 passed | 135 passed |
| selection before activation | 1 failed, 80 passed | 136 passed |

Surrounding H herdr directory plus session, usage, bootstrap, rate-limit and
manual-compaction modules: 1295 passed (before unit 7). Unit 7 surrounding is
136 passed as above. Full final `make test`: **7532 passed, 19 deselected,
413 warnings, exit 0**, 600.21s. Includes concurrent test-only lane additions.
Changed-file Black: three files unchanged, exit 0. `git diff --check`: silent,
exit 0. `dpkg -V coreutils` after full: silent, exit 0; also silent after
intermediate stubbing suites.

`make lint`: **308 errors in 64 files**, exit 2. Normalized comparison to retained
299/63 t5-40 baseline identifies exactly nine additions, all in parallel-owned
`test_session_publication_compositions.py`; none in these three owned files.
See lint-attribution.log; no waiver and no edit to that lane. Baseline remains
unwaived.

## Remaining blockers — do not claim family READY

1. Sticky invalidation currently has no explicit authorized recovery boundary;
   verify the intended supported-selection recovery contract before acceptance.
2. Numeric tuple indexes in adoption encode field permissions; replace with a
   clearly named cohesive comparison and prove every commit's pre/post boundary.
3. Full malformed-config matrix is incomplete: current strict test covers history
   and one malformed pool. Python equality conflates bool/int; source model and
   configured reasoning validation, malformed sequences, prompt/tool container
   types and alias retention require exhaustive truthful validation evidence.
4. Bootstrap snapshots scalar sources before building, but does not prove exact
   final tool additions against mutation inside the attach seam. Permission must
   not permit later out-of-band provenance laundering.
5. Prerequisite ingestion incomplete: canonical C capture/provenance and branch
   table read, but full accepted reviews/T5 attachments and all requested routed
   skill/KB content have not been fully consumed. Some bulk output truncated;
   redirecting skill content to a temporary file did not constitute reading it.
6. No independent review/completion claim, no full family assertion, no fresh
   smoke gate. Full suite passing is not evidence that the above gaps are solved.

No spec/global/KB/other-worktree edits, destructive Git commands, commits,
pushes/PRs, installations, actual providers, Herdr commands or terminal windows.
No history/provider execution policy intentionally changed. Synthetic tests use
existing isolation and no model execution in the new tests; retained surrounding
suite exercises config-backed Faux factory paths.
