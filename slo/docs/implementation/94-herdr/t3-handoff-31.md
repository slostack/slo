# T3 technical handoff 31 — READY

**READY for the entire T3 technical dependency (store + already implemented CLI), not full-feature acceptance.** The five remaining rows from `t3-composition-30.md` are closed below. Integrated make gates remain sequenced after T3/T4 readiness as requested. Latest supplied global lint baseline **300 errors / 64 files remains unwaived, not green**. Independent full-feature Review/Completion and T5/T6 remain later.

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1, dispatch 31, retries 0. User turn and dispatch budgets unlimited; old numeric limits void. No agents dispatched here. No CLI/viewer/shared-lease/DAO edits, commits, push/PR, reset/clean/stash, global/live/specification/other-worktree changes. All pre-existing partials retained.

## Exact change and test-first evidence

Production change is only `src/agents/slo_agent/herdr/restore.py`: private copied-config serialization now uses `model_dump(warnings=False)` before the existing full `model_validate`. Invalid nested values still refuse; validation is not bypassed. Pydantic previously emitted the invalid provider/priority input in a serializer warning BEFORE validation translated the exception. An initial exception/log-only test passed but exposed warnings in pytest output. Strengthened warning-channel assertions produced **2 failed / 71 passed**, then this one-line behavior correction produced **223 passed** with surrounding store/shared-lease tests. No fake RED claim for the initially correct branches.

New file: `tests/agents/slo_agent/herdr/test_restore_remaining.py` (19 parameterized cases). Final inspected source has typed helpers, no ignores/Any, no fixture touching system paths, and contained dangling links only. No actual ownership changes: owner faults alter one observed stat field on real test-owned directories. Syscall faults operate on actual restore lock descriptors and verify closure/reacquisition. AtomicFileWriter remains unchanged.

## Five-row closure and finite decision map

| Remaining row | Actual decision paths and evidence | Result |
|---|---|---|
| 1. Distinct directory ownership / creation depth | `test_distinct_directory_owner[state,records] × [save,load]` changes ONLY that level's observed UID; writer forbidden, old bytes retained. `test_creation_parent_depth[private,public,foreign,missing]` checks immediate existing creation parent, successful creation of the two owned levels, refusal without recursive ancestor creation. Existing security tests retain mkdir error/private-vs-insecure race and linked root/parent proofs. | Closed; initial pass |
| 2. Copied invalid nested pool / privacy | `test_copied_invalid_nested_pool_private[provider,priority,entries]` uses bypassed copied nested input; store revalidates provider enum, strict scalar and minimum tuple size. Writer forbidden; previous bytes/load retained; str/repr/formatted traceback/logs AND emitted warnings scanned. | Closed; real warning leak RED → GREEN |
| 3. Allocation / precommit collisions | `test_occupied_name_never_calls_writer[allocation,commit_file,commit_link]`: dangling name consumes all three draws; file/link introduced after actual capacity inspection refuses at commit. Exact draw counts and writer-not-called; occupied content/link and old revision preserved. Existing boundaries test covers 0/1/2/3 regular collisions. | Closed; initial pass |
| 4. Acquire-stage reconciliation | New `test_acquire_stage_refuses_and_releases[create,write,open,fstat,flock]`: actual lock setup/open, private error translation, no writer, all opened fds closed, subsequent save succeeds. Shared evidence below covers the remaining meaningful lease branches. | Closed; initial pass |
| 5. Required context refresh | Explicit disk-read audit below; current normative C and exact T3 attachments reconciled with actual store and CLI, not inferred from prior receipts. | Closed for this scoped T3 continuation |

### Shared-lease proof reconciliation (not a new unbounded matrix)

`test_sequence_store.py` is the shared mechanism evidence, freshly included in focused and package gates:

- `test_lease_refuses_unsafe_files`: missing/nonregular/symlink/hardlink/mode/parent-mode validation.
- `test_lease_contention_and_distinct_restore_scope`, `test_actual_process_contention_restart_and_crash`: native nonblocking exclusion and independent lock scope, actual process release/crash.
- `test_substitution_between_validation_and_open[lease_open]`: pre-open versus opened inode mismatch.
- `test_replaced_lock_refused_and_repeated_acquire_retains_lock`: reentrant misuse cannot surrender held ownership.
- `test_windows_byte_lock_contract`: recording native-adapter branch, NOT a live Windows certification.
- `test_unsupported_locking_closes_descriptor`: unsupported semantics refuse and release.
- `test_unheld_and_invalid_source_refused`: require-held absence.
- Store `test_lock_substitution_refuses_commit`: held pathname revalidation before commit.
- Store security missing-lock save/load cases distinguish create versus noncreating load; platform/open refusal and directory validation remain covered.
- `test_lease_close_fault_is_private`: cleanup error translation after actual release; not a promise of recovery from a permanently unresolved OS close.

No new recovery subsystem or hostile-same-user atomic-exclusive-create requirement is inferred. C explicitly excludes privileged same-user tampering and preserves AtomicFileWriter replacement semantics. Successful and failed native operations, privacy translation and ownership cleanup are the required boundaries—not every possible operating-system errno.

## Retained full T3 contract map

| Family | Existing passing proof retained and rerun |
|---|---|
| Constructor / noncreating load / reference syntax | `test_restore.py`; security missing root/lock cases |
| Fresh immutable private save / exact old revision | `test_restore_save.py`, CLI old-reference test; no latest pointer/history creation/eviction |
| Byte/count/total quotas and bounded scan | `test_restore_boundaries.py`: exact below/at/above limits, actual 1,025-entry iterator stop, independently padded reads |
| Scan / record security and I/O | `test_restore_security.py`, `test_restore_faults.py`, `test_restore_io.py`: insecure entries, identity/schema/ref, short reads, open/inode/mode/close faults |
| Durability and crashes | real file/directory fsync tests; `test_restore_process.py` pre-replace child death, durable orphan death, contention and concurrent save/load |
| Real store → reporter failure | `test_restore_composition.py::test_real_store_failure_withdrawal`: actual store/reporter/guarded fake executable, accepted/rejected withdrawal, no failed-generation advertisement/ack, old immutable bytes |
| Reporter revision uncertainty | retained `test_restore_batch_closure.py`; T2 binding/save/release/ack proofs remain part of package gate |
| CLI admission and compatibility | `tests/cli/test_herdr_restore.py` plus app/dispatch/headless_request/headless regression modules |

### CLI already implemented: no ambient merge

Actual chain: `_default → TyperDispatch.tui → argument admission → exact existing metadata + resolver agreement → HerdrRestoreStore.load → new validated pool + SessionConfigDAO → ordinary build(allow_pending_preparation=True) → SloTUI.run`.

`--herdr-restore` requires literal canonical UUID resume and rejects explicit workdir/workspace/plugins and subcommand combination before runtime construction. Exact history identity is checked before name resolution can redirect it. Errors are fixed and unchained; unavailable data does not fall back to preferences or newest revision. Ordinary slug/name resume remains on the original path.

Saved policy is recursively immutable. `_restore_model_pool` constructs NEW `ModelPoolEntryDAO` objects from all five scalar fields in exact order and a NEW `ModelPoolDAO` list, running current provider validators. No frozen alias, ambient preferences or routed-fallback policy is merged. Workspace/plugins/effective reasoning are copied, history is enabled at the default root, and standard prompt/tools/hook defaults remain. Current admission and plugin trust remain normal runtime responsibilities. Existing tests mutate the reconstructed pool and reload unchanged saved policy, forbid preference loading, reject invalid provider ownership, and exercise production reporter five-token argv through actual parser/dispatch/lazy session construction with Faux safeguards and no inference/replay. TUI.run is mocked in that bounded proof; mounted two-process acceptance is T6, not claimed here.

**No additional CLI contract gap identified in this T3 reconciliation.** No CLI edit made.

## Explicit read audit

Fresh reads in this continuation (not assumed from system context):

- Actual `AGENTS.md` 1–510 and 511–1013, full `CLAUDE.md`, root `RESEARCH.md`, full `docs/RESEARCH.md` 1–633; Makefile, relevant pyproject dependency/test/static declarations, approved fallback script, actual isolation/terminal/fake-capability fixtures.
- Full `t3-composition-30.md`, `t3-store-28.md` (reread separately after combined-output truncation), `t3-store-29.md`, `t3-code-test.md`, `t3-cli-28.md`, `routing.md`, `scope-plan.md`. Frozen records left unchanged; their historical counters/status are not current authority.
- Canonical read-only `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/94.b.2-session-publication-and-native-restore.md`: 1–229, 230–542, 543–1142, 1143–1742, 1743–2175. Exact `tasks.md` 1906–2108. Full accepted `review-evidence/independent-review-turn4.md` and `finalization-receipt.md`. Accepted spec review is not implementation approval.
- Vendored `skills/engineering/{engineering-routing,engineering-testing,engineering-ownership}/SKILL.md`; `coding/{coding-rules,code-test-loop,declarative-method-structure,test-verification-policy}/SKILL.md`; `languages/python/{python-conventions,build-domain-features,build-application-services,declarative-method-structure,named-arguments-and-type-hints,method-docstrings,application-structure,switch-environments-and-run-tests}/SKILL.md`; exact `design-and-analysis/workflows/code-test-review.md` and shared `workflows/SKILL.md`; product `cli/build-typer-cli-apps/SKILL.md`. Full DAO recipe covered in 1–800 and 801–1525 reads, including tail. No ORM/web/worker stack manufactured from examples; approved instance-owned save/load seam preserved.
- Routed KB: actual `/root/Code/KnowledgeBase/KB/Welcome.md`, `slo/README.md` (actual index), `slo/gotchas.md`; complete `skills-and-kb.md`, `tui-cli-session.md`, `headless-workflow-orchestration.md` in retained combined output. Initial combined KB output truncated at its beginning; entry/index and gotchas beginning/tail were explicitly recovered. Historical paths/timeouts/publishing advice are not current source authority. No KB writes under this scope.
- Actual restore owner, shared lease and atomic writer, private pool/config/record schemas, restore security/save/boundary/I/O/fault tests, shared lease tests, CLI restore assembly and entire CLI restore test module. Read-only CLI parse flag/dispatch examined. New untracked test file inspected directly; ordinary git diff cannot show untracked bodies.

This does not claim a fresh full-family B/D/T5/T6 implementation review or rereading every unrelated companion in the full-feature routing document. Those remain the later independent full-feature phase, not additional pending T3 rows.

## Commands, logs and exits

CWD `/root/Code/slo-94-herdr-integration/slo`; branch `feature-94-herdr-integration`. `pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env` returned `fallback`. No venv/package installation. P below is exactly `bash docs/implementation/94-herdr/t1-dao-check.sh`; it adds DAO/projection cases and approved safe fallback exports. HERDR stripping/default disable, fake-only spawn capability and terminal guard remain active.

All prefixes below live in this directory and have `.log` and `.exit` unless noted:

| Prefix | Command suffix/check | Actual result |
|---|---|---|
| t3-31-directories | P tests/agents/slo_agent/herdr/test_restore_remaining.py tests/agents/slo_agent/herdr/test_restore_security.py | 116 passed, 2 warnings, exit 0 |
| t3-31-pool | same | 119 passed, 4 warnings, exit 0; warning leak discovered, not accepted privacy proof |
| t3-31-pool-red | P tests/agents/slo_agent/herdr/test_restore_remaining.py | 2 failed, 71 passed, 2 warnings, exit 1 |
| t3-31-pool-green | P tests/agents/slo_agent/herdr/test_restore*.py tests/agents/slo_agent/herdr/test_sequence_store.py | 223 passed, 2 warnings, exit 0 |
| t3-31-collisions | P remaining + test_restore_boundaries.py | 93 passed, 2 warnings, exit 0 |
| t3-31-acquire | P remaining + test_sequence_store.py | 122 passed, 2 warnings, exit 0 |
| t3-31-package-cli | P tests/agents/slo_agent/herdr tests/cli/test_herdr_restore.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/cli/test_headless_request.py tests/cli/test_headless.py | 1153 passed, 6 warnings, exit 0 |
| t3-31-final | same after final test typing correction | **1153 passed, 6 warnings, exit 0** |
| t3-31-black-final | poetry run black --check src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore*.py | exit 0 |
| t3-31-types | poetry run mypy src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore_remaining.py | 8 errors/5 files, exit 1; one new test enum-typing error corrected |
| t3-31-types-final | same | 7 dependency errors/4 files, exit 1; none in either checked file |
| t3-31-diff | git diff --check | exit 0 |
| t3-31-coreutils-final | dpkg -V coreutils | silent, exit 0 |

Formatting command (log only): `poetry run black src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore_remaining.py`, `t3-31-format.log`. Initial black/coreutils receipts also retained. Final package count includes other existing lanes; it is not solely this continuation's increment. Six warnings include existing deprecations and unawaited AsyncMock warnings in CLI tests; full output retained, not suppressed. Private serializer-warning regression is fixed, not pytest-filtered.

Scoped mypy remaining files: providers/faux.py (3), anthropic_claude_code.py (1), openai_codex.py (2), herdr/reporter.py (1 protocol return mismatch). These are unwaived and outside this edit scope. No fresh full make/lint-green claim. Run integrated make test/smoke/lint after T3/T4 readiness, retain the 300/64 supplied baseline, and conduct independent full-feature review later. Technical dependency READY is not release or workflow completion.
