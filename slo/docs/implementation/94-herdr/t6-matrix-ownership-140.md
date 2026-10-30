# T6 finite lifetime matrix ownership 140 — READY64

READY64 is bounded to the canonical 64-case lifetime matrix and the adjacent offline evidence below. It is not T6 completion, independent implementation acceptance, a full-suite pass, or live certification. Two-process HOLD remains. Global static baseline **281 errors / 58 files** remains unwaived (supplied baseline, not rerun).

## Scope and plan

Changed only `tests/integration/test_herdr_lifetime_matrix.py`; helper classes remain in that file. Other writes are this report and `t6-matrix-ownership-140-receipts/`. No source/full_flow/harness/spec/shared status/KB/other-worktree edits, agents, commits, pushes, PRs, system changes or live calls. Existing unrelated dirt preserved.

Continuation accounting: unfinished turn 1; started 1, completed 0, historical partial 1; supplied dispatch label 140; retries 0. Effective turns and dispatch budgets unlimited. No child dispatch performed. Local test reruns are not workflow turns or execution retries.

Plan: reconcile the exact finite contract; capture real mounted owners; assert their trigger-appropriate terminal state and late acknowledgements in each phase family; run groups green before progressing; correct the platform precommit boundary; run exactly 64 nodes once in the final gate; run separate G1/G2/all-owner and safe initialization/prompt complements; static/ID/integrity audit.

## Canonical reading and finite contract

Read `t6-matrix-platform-139.md`, project AGENTS/CLAUDE/SLO, root RESEARCH and supplied full docs/RESEARCH. Read KB Welcome, slo README (actual index; no slo/index.md exists) and gotchas. Read checkout engineering routing/testing/ownership; coding rules/code-test-loop/declarative; Python conventions/declarative/named arguments/docstrings/Faux graph tests; Textual build guidance; integration cardinal rules; workflow SKILL accounting. Stack/category: Python 3.11, asyncio, Textual mounted composition, real temp filesystem and registered fake CLI, Faux model. No unrelated HTTP/ORM/Go/TS rules imposed.

Canonical read closure: C 7.9–7.14 and section 8 (including every bounded continuation of the long 7.9/7.13 examples), B 7.7–7.9 save/admission/accounting and 7.13 authority/drain, D platform offload lifetime/A2 and surrounding test requirements, tasks T6 acceptance, accepted specification review turn4 and workflow summary. The initial oversized tasks read truncated; the actual T6 normative section was subsequently read explicitly. No claim to have reread every unrelated sample appendix.

The exact matrix paragraph is at **C 7.14 immediately before section 8**, not in section 8's list. It specifies three independent dimensions:

- trigger: runtime disable, session close, new, unmount;
- phase: queued report, admitted report, queued viewer, admitted viewer, precommit platform, committed platform, queued capture, running save;
- diagnostic: healthy, raising.

Thus 4×8×2 = 64, not an additional cross-product over every initializer, inbox stage, or persistent quarantine fault. C requires relevant actual owners to remain accounted for, with distinct quarantine/inbox/initialization tests. It does **not** require fabricating an occupied retired slot in every row. These rows start with no retired owner and finish with none because participating transport resources drain; the separate 28 all-owner compositions genuinely exercise occupied retained owners and persistent/transient drain. This is not a cost waiver.

The prior platform `precommit_platform` blocked discovery **after thread registration**, which D explicitly treats as committed. It has been corrected: an instrumented registered app worker waits before invoking the original worker's lifetime check. New/unmount cancel it before any thread or spawn; integration-only close/disable leave independently selected platform execution available. The committed family still holds the real guarded spawn and proves repeated cancellation joins the thread before adoption/unmount. No production policy was replaced.

## Per-case assertions in the matrix

`MatrixOwnershipFacts.capture` captures the actual selected session, lease store and owner ID, both real Timer handles, preparation task if present, subscription and empty retired slot. It also enqueues and claims one real temp-owned inbox item under the submission lock. This is an already-retained claim, **not** a simulated racing claim continuation.

`assert_settled`, called from each phase body before fixture teardown, verifies:

- viewer registry empty and no accidental prompt registration;
- no undrained retired owner discarded in these draining rows;
- new/unmount: captured old lease absent, old subscription removed, both captured timers actually stopped, captured preparation terminal if present, session close task done with drained result;
- integration-only stops: same selected session, captured owner lease and subscription retained, exact timers still installed/running;
- new: distinct candidate identity, candidate subscription/lease and new timers, no old-ID lease;
- unmount: monotonic closing/quiescing, cleared timers, terminal app shutdown and selected final-drain tasks;
- a fresh real inbox poll leaves the original claimed bytes in claimed, pending/done empty, and no prompt task. This checks non-replay/late-ack for existing claims in place; it does not substitute for claim/advance/registration races.

`MatrixAcknowledgementFacts` snapshots immutable display/lifecycle/restore acknowledgement facts **after revocation and before barrier release**, then checks no late display credit and no new semantic acknowledgement. Stale semantic invalidation to None is permitted by B; advancement is not. It additionally checks ticket/save/reservation slots cleared and transport resources drained. Remote binding certainty remains separate from semantic acknowledgement.

Phase-specific existing assertions remain: zero queued sends; exact one admitted old effect with no follow-up; queued capture zero saves; running save real immutable orphan not adopted/advertised; committed platform one guarded submission and no late notice. Diagnostic sink execution is asserted in every row. Platform diagnostics exercise the real pane reporter's failure, not a fictitious throwing late renderer: late rendering is forbidden for cancelled app-lifetime work.

New assertions execute in awaited test bodies, not swallowed production callbacks or teardown. Barrier callbacks collect/hold facts; their former incidental assertions were removed. Fixture finally blocks only release/join owned work. No real system symlink or executable mutation was introduced.

## Separate adjacent proof

| Evidence | Fresh result | Boundary |
|---|---:|---|
| G1 same-capture newest usage, plus changed-reasoning contrast | 2 passed | Real save barrier, exact capture association; not matrix duplicates |
| G2 viewer/shared-lock A/B cutoff variants | 8 passed | Actual lock/admission and stale suppression |
| T5 `test_all_owner_claim_pending` | 28 passed | Seven inbox cutoffs × persistent/transient drain × healthy/throwing notice; genuine current/retired owner composition |
| Platform join/commit surrounds | 6 passed | Separate committed-thread lifetime corroboration |
| Initialization, init ownership, prompt registration, activation cutoffs | 92 passed | Safe explicitly named files; no integration-directory collection |

The first four rows are the separate **44-pass** command. These are not called an extra 44 matrix cases or an occupied-retired × 64 proof.

## Executed verification and receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`. Interpreter `/root/.pyenv/versions/slo-harness/bin/python`, verified Python 3.11.7. Explicit fallback on each pytest shell:

```text
SLO_ENV=test
SLO_PROJECT_ROOT_DIR=$PWD
SLO_APP_ROOT_DIR=$PWD
PYTHONPATH=$PWD
SLO_APP_NAME=slo
SLO_LOG_FORMAT=text
SLO_DEFAULT_MODEL=gpt-5.4
SLO_AUTO_VISUALIZE=0
SLO_HERDR_DISABLED=1
SLO_ANTHROPIC_API_KEY=synthetic-offline
COLUMNS=120 LINES=40
```

No development environment sourced. Root isolation strips inherited HERDR, defaults disabled, protects transport spawning with registered fake capability and guards real terminals. `native_factory` supplies Faux and a contained regular plain-slo stub. All waits retain existing bounded barrier budgets; Bash allowance 1800 seconds.

Commands below use that interpreter with `-m pytest tests/integration/test_herdr_lifetime_matrix.py` unless otherwise stated:

| Receipt | Suffix / command | Actual result |
|---|---|---|
| cli-phases.log | `-k 'queued_viewer or queued_report or admitted_viewer or admitted_report' -x -q` | 32 passed, 32 deselected, exit 0 |
| save-phases.log | `-k 'running_save or queued_capture' -x -q` | 1 failed, 4 passed, 48 deselected, exit 1: test-edit indentation error made finally release an unlocked lock; **not production RED** |
| save-phases-fixed.log | same selection | 16 passed, 48 deselected, exit 0 |
| platform-owners.log | `-k platform -x -q` | 16 passed, 48 deselected, exit 0 |
| retained-claim.log | `-k queued_viewer -x -q` | 8 passed, 56 deselected, exit 0 |
| precommit.log | `-k precommit_platform -x -q` | 8 passed, 56 deselected, exit 0 |
| collection.log | `--collect-only -q` | 64 collected, exit 0 |
| matrix-final.log | `-vv -o faulthandler_timeout=40` | **64 passed, 2 warnings, 70.48s, exit 0** |
| surrounds44.log | command below | **44 passed, 20 warnings, 26.28s, exit 0** |
| safe-surrounds.log | command below | **92 passed, 18 warnings, 21.77s, exit 0** |

Separate commands:

```bash
python -m pytest \
 tests/agents/slo_agent/herdr/test_session_publication_compositions.py::test_real_session_save_barrier_latest_publication \
 tests/agents/slo_agent/herdr/test_reporter.py::test_viewer_lock_waiter_superseded_report_never_spawns \
 tests/tui/test_herdr_all_owner_cutoffs.py \
 tests/tui/test_herdr_platform_commit.py -vv -o faulthandler_timeout=40

python -m pytest tests/tui/test_herdr_initialization.py \
 tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_prompt_registration.py \
 tests/tui/test_herdr_activation_cutoffs.py -vv -o faulthandler_timeout=40
```

Final Black check: one file unchanged, exit 0. Owned mypy `--follow-imports=silent tests/integration/test_herdr_lifetime_matrix.py`: no issues, exit 0. Scoped git diff check: exit 0, but the test is untracked, so that command alone does not review its content; direct source inspection was performed. `ids-audit.txt` independently compares the exact Cartesian set to collection and final PASSED lines: **64 unique nodes, each once, no missing or extra IDs**. Incremental executions are separate, not included in this once-only final run claim.

`dpkg -V coreutils` was silent before tests and after final gates; final empty log and exit 0 retained. No production RED encountered. Full make/integration-directory/two-process/live gates were not run. Independent implementation review remains required. READY64 does not erase those separate gates or waive the global static baseline.
