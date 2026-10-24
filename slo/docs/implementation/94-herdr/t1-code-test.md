# T1 consolidated code/test handoff — READY

2026-10-18. **Entire T1 foundations are implemented and verified for T2 handoff.** This is not full Feature 94 acceptance, independent review, native Windows certification, or live Herdr compatibility. No enabled assembly was introduced. Earlier partial/no-code receipts and slice-only READY statements are historical; this document consolidates them without erasing their recorded cadence exceptions.

## Complete T1 requirements

| Requirement | Owners/evidence |
|---|---|
| Pre-import and per-test inherited HERDR stripping, forced disabled defaults | tests/state_isolation.py, tests/conftest.py, tracked Makefile and environments/.env.template; t1-isolation.md and test_test_isolation.py |
| Explicit safe fake capability | FakeHerdrSpawnGuard + frozen FakeHerdrFixture; root conftest fake_herdr_guard/fake_herdr; test_spawn_guard.py and test_fake_fixture.py prove actual regular fake execution, capture, missing/link/traversal/outside/nonregular/hardlink/nonexecutable/substitution refusal; T2 actual transport wrapper intentionally deferred |
| Shared immutable public/private schemas, protocols, session attention/provenance vocabulary | herdr/dao.py and sessions/dao.py; t1-daos.md, test_daos.py, test_projection.py; no session activation |
| Complete lower-layer identity closure and strict canonical UUID predicate | sessions/identity.py and CLI compatibility import; t1-identity-format.md, test_session_identity.py and unchanged headless-request regression suite |
| Exact half-up formatter and footer compatibility delegation | sessions/token_format.py, usage_status_bar.py; test_token_format.py and existing mounted footer tests |
| Secure single lease mechanism with distinct pane/restore scopes | herdr/sequence_store.py; test_sequence_store.py actual temp filesystem, OS-process contention/no stealing, graceful restart and crash lock release |
| Durable hashed namespace counters | strict nonbool integer validation and signed-64 bounds at store boundary; independent source counters; unknown-version/corrupt/overflow/refusal never reset; unchanged AtomicFileWriter persistence before return and durability-warning refusal; retained files and safe gaps |
| Safety and regression gates | full default suite, smoke, all changed Python Black, exact lint baseline comparison, silent coreutils verification |

Required source: canonical Herdr tasks.md T1 plus B 7.1/7.5/7.6/final safety and lease contracts, C identity/vocabulary, D declarations. `routing.md` and `scope-plan.md` preserved unchanged. Individual evidence: t1-isolation.md, t1-foundations.md (historical incomplete), t1-daos.md, t1-identity-format.md, t1-sequence-fixtures.md.

## Final unchanged-code verification

CWD `/root/Code/slo-94-herdr-integration/slo`; pyenv slo-harness Python 3.11.7, Makefile fallback. Targeted checks use the exact fallback exports recorded in routing and t1-dao-check.sh; no development environment or real provider credentials. Full logs and exits reside beside this document.

| Command | Receipt | Result |
|---|---|---|
| Focused and surrounding Herdr/atomic/identity/formatter/footer/CLI/isolation/terminal tests | sequence-surrounding-final.log/.exit | 240 passed, 3 warnings, exit 0; before final three test-only cases |
| Final Herdr branch suite | sequence-final-branches.log | 109 passed, 2 warnings; final race-test type annotation subsequently corrected and covered by full suite |
| `make test` | sequence-full.log/.exit | **6435 passed, 19 deselected, 406 warnings; 480.27s; exit 0** |
| `make smoke` | sequence-smoke.log/.exit | **283 passed, 2 warnings; exit 0** |
| `make lint` | sequence-lint-final.log/.exit | **301 errors in 64 files; exit 2**; checked 695 files |
| Black --check all 18 changed/new Python files | sequence-black-final.log/.exit | **18 unchanged, exit 0** |
| `dpkg -V coreutils` | sequence-coreutils.log/.exit | **empty output, exit 0** |
| Exact lint diagnostic diff against latest DAO baseline | sequence-lint-baseline.diff | **empty**; not merely equal counts |

Lint remains failing and unwaived; no new diagnostic remains. The earlier concurrent 348-error receipt is not the baseline. New adapter typing and race-test annotation errors were diagnosed/fixed, not ignored. No tests were skipped or weakened to obtain these results. The default 19 E2E deselections remain the existing suite policy. Final source diff and new files reviewed for bounded ownership and unchanged writer/terminal guard; git diff --check passes.

## Limits and next tasks

- T1 is an inert foundation. T2 must wrap the actual `_spawn` boundary with the fixture capability before activation tests and prove disabled mounted/headless zero-spawn behavior. Fixture registration alone is not runtime permission.
- T2 owns off-loop calls/joins and persist-before-send composition; T1 proves durable return/refusal, not an absent reporter send path. T3 owns restore records/quota/security beyond its shared lock mechanism. T4 viewer, T5 session/app assembly, T6 composed/live acceptance remain pending.
- Windows native byte locking is branch-tested with a recording adapter on Linux, not executed on Windows. Unsupported/insecure filesystem semantics fail closed; no network-filesystem certification.
- Independent full-scope implementation review and fresh completion assessment remain pending. No live Herdr, providers, global changes, worktree/spec edits, commits, pushes or agents were performed. Real process tests use only test-owned children and temporary state.

Workflow accounting: turn 1 active; started 1, completed 0, historical partial 0; dispatch **8 consumed / 12 remaining of 20**; unlimited turns; retries 0. Continuation after provider interruption preserves those counts.
