# T6 harness edge close 143 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 143, retries 0. Unlimited turn/dispatch budgets; no agents dispatched. Positive entry and full make remain HOLD for parent verification. This is not overall READY.

## Concrete corrections and evidence

Only bootstrap and safety-test code changed. Entry/parent wiring preserved.

1. Capture refusal could close a newly reused descriptor slot. A deterministic test closes the original only at the descriptor-admission seam, opens a contained regular victim into that slot, then refuses admission. RED: `OSError: [Errno 9] Bad file descriptor`, 1 failed/143 deselected. The writer now records opened identity in the existing OwnedDescriptor and closes by identity; it does not close the replacement. Full module GREEN: 144 passed.
2. Renaming the opened capture and replacing its original pathname was incorrectly admitted because `/proc/self/fd` followed the renamed original. The four-case capture-specific matrix exposed this: replacement reached the forbidden os.write seam. RED: 1 failed/147 passed. The writer now also requires the resolved opened path equal the requested absolute capture path. Full module GREEN: 148 passed, 2 warnings in 63.91s.

The same matrix covers a real hardlink added after open, unlink after open, and mode change on the same inode. All files and links are confined to the test's temporary directory. Refusals assert no write syscall; replacement victim and retained original bytes are checked. Mode 0400 on an already-open writable regular FD remains admissible: permissions are not an immutable capture-registration contract, and this does not bypass containment/type/link/identity validation. No atomic append or zero-byte guarantee after a write/close I/O failure is claimed.

The identity-less initial fstat failure retains the existing exclusive-allocation close behavior. This is not proof against arbitrary concurrent close/reuse before initial inspection. After identity capture, existing OwnedDescriptor semantics avoid closing a different inode and never retry an ambiguous close. Capture-specific close-failure tests remain to be added; existing supervisor-close tests are not substituted for them.

## Finite requirement reconciliation

| Initial/later gap | Current proof / remaining work |
|---|---|
| 122 descendant timeout / 127 cleanup ownership | PROCESSREADY136 evidence retained; existing module tests rerun |
| 122 alternate execution | Actual exec/spawn refusals 138, Popen/run/asyncio registered/substituted proofs 140 retained and rerun |
| 122 unsafe sibling probe | Contained-victim supervised parent probe 141 retained and rerun; old probe not executed |
| 122 integer/dir_fd omissions | Existing descriptor/directory-capability tests retained and rerun |
| Generated capture check/open substitution | SENSITIVITY140 actual generated writer evidence retained and rerun |
| Parent positive API wiring | Exact request tests 141 retained and rerun; positive entry never executed |
| Generic special/hardlink descriptor metadata | 142 evidence retained and rerun, no duplicate generic matrix |
| Actual installed AtomicFileWriter / HerdrFileLease | 142 regression retained and rerun |
| Capture path disappearance/hardlink/mode/replacement after opening | New capture-specific four-case matrix passes; rename defect corrected |
| Capture admission descriptor reuse / unsafe close | New contained-victim RED/GREEN passes |
| Capture-specific nonregular substitution, close-error dispositions, registration refusals | Not yet fully enumerated/proved |
| Actual reachable ENTRY persistence inventory | Not completed: complete history/private-event/preferences/restore/context/capture mutation traversal and installed path/FD/dir_fd proof mapping remain required |
| Unsupported reachable syscall policy | Not reconciled; no universal Python sandbox claim |
| Required read tails | Not completed; exact accounting below |

## Read accounting

Fully read 141 and 142 receipts, root RESEARCH, scope-plan, machine guardian ROLE then README; engineering routing/testing/ownership, coding rules/cadence, Python root/declarative and method-docstrings. AGENTS, CLAUDE and docs/RESEARCH supplied in session context. Bootstrap 1–240 and 500–end; entry 1–240; safety tests 420–504, 1500–1739 plus grep navigation. Named-arguments guidance 1–180 only. Four malformed parallel read calls returned missing-path validation errors and read nothing.

The already-known read tails from 141/142 remain outstanding rather than being claimed read: shared declarative owner; named-arguments tail; Faux recipe; workflow SKILL and selected INDEX; remaining guardian detail/KB Slo context; routing.md; canonical B prerequisite, C construction/two-process details, exact T6 attachments and accepted review/task-breakdown evidence; historical safety-test gaps and affected persistence owner traversal. No unrelated documentation was bulk-read. This report does not falsely discharge that list.

## Commands and logs

Cwd `/root/Code/slo-94-herdr-integration/slo`. No env file sourced. Each test invocation used:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
```

- `$P -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py -k capture_admission_reused_slot`: exit 1, `edge143-red.log`.
- Same command without `-k`: exit 0, 144 passed, `edge143-green.log`.
- Same full module after new matrix: exit 1, 1 failed/147 passed, `edge143-matrix.log`.
- Same full module after pathname correction: exit 0, 148 passed, `edge143-matrix-green.log`.
- `dpkg -V coreutils` immediately after every invocation: silent, no anomaly.
- Black formatting bootstrap/safety test: 2 files unchanged.
- Black `--check` all four harness files: 4 files unchanged.
- Mypy `--follow-imports=skip` all four: Success, no issues in 4 source files.
- `git diff --check`: silent. Untracked file bodies are not represented by HEAD diff; edited regions inspected directly.

Static commands used the exact four paths: `tests/integration/herdr_restore_process_bootstrap.py`, `tests/integration/herdr_restore_process_entry.py`, `tests/integration/test_herdr_two_process_restore.py`, `tests/integration/test_herdr_restore_harness_safety.py`. Static output was returned by the command tool, not separately persisted. Root fixtures retain HERDR stripping, fake-only execution and terminal guard. No positive process, full make, provider, real Herdr or window ran. No system/global/live/spec/other-worktree edits; no commit/push/PR/reset/clean/stash or shared workflow-status edits.

## Verdict

**INCOMPLETE.** Two concrete pre-write/cleanup defects are fixed with failing tests first and complete safety-module green after each increment. Overall harness acceptance remains withheld for the finite missing capture cases, reachable-operation map and listed mandatory reads. No arbitrary workflow/unit cap is asserted and no completed workflow turn is claimed.
