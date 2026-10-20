# T3 STORE 29 — INCOMPLETE; technical READY withheld

Continuation of unfinished turn 1: started 1/completed 0/historical partial 1,
dispatch 29/retries 0. Unlimited user turns/dispatches; no agents dispatched here.
No production changes, CLI/viewer changes, commits, global/live/specification or
other-worktree edits. Existing partials preserved. This receipt does not close
all assigned rows or authorize T5.

## Added evidence

- `test_restore_boundaries.py::test_scan_stops_at_overflow_entry`: wraps the
  actual `os.scandir` iterator over 1,030 real private files. Exactly 1,025
  entries are consumed; all 1,030 remain. Initially passing existing behavior.
- `test_independently_padded_load`: independently pads real JSON with whitespace
  to 65,535/65,536/65,537 bytes; first two load exactly, last refuses. Initially
  passing existing behavior.
- `test_restore_process.py::test_pre_replace_child_crash`: actual spawned child
  runs the real writer through file fsync and pauses at `os.replace`; parent
  observes temporary file/no final file, terminates and joins only that child,
  then loads the unchanged old revision. First test run failed because the
  injected callback used source/destination rather than actual src/dst keywords;
  corrected test passes. This was a fixture failure, NOT production RED.
- `test_restore_security.py`: removed untyped heterogeneous keyword expansion;
  explicit mock assignment with non-None narrowing fixes the reported STORE
  typing error without Any or ignores. Scoped mypy still reports dependency
  errors, not a green global gate.

## Receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified approved pyenv
slo-harness Python 3.11.7; make test-env returned fallback. P is
`bash docs/implementation/94-herdr/t1-dao-check.sh`, with existing isolation,
synthetic credentials, disabled Herdr and fake capability/terminal guards.
Prefixes below are in this directory, with `.log`/`.exit` unless noted.

| Prefix | Command/scope | Result |
|---|---|---|
| t3-store-29-types-test | P test_restore_security.py | 97 passed |
| t3-store-29-types | mypy security test | owned overload error remained |
| t3-store-29-types-test2 | P security test | 97 passed; log only |
| t3-store-29-boundaries | P test_restore_boundaries.py | 79 passed |
| t3-store-29-crash | P test_restore_process.py | 1 failed, 64 passed; callback mismatch |
| t3-store-29-crash2 | same | 65 passed |
| t3-store-29-types2 | mypy security test | two owned nullable mock errors |
| t3-store-29-regression | P tests/agents/slo_agent/herdr/test_restore*.py tests/cli/test_herdr_restore.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/cli/test_headless_request.py tests/cli/test_headless.py | 299 passed, 5 warnings; exit 0 |
| t3-store-29-types3 | poetry run mypy tests/agents/slo_agent/herdr/test_restore_security.py | 7 dependency errors in 4 files; no owned-file errors; exit 1 |
| t3-store-29-black | poetry run black --check src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore*.py | exit 0 |
| t3-store-29-diff | git diff --check | exit 0 |
| t3-store-29-coreutils | dpkg -V coreutils | silent, exit 0 |

## Existing proofs and remaining gaps

Retain STORE 28's branch map and CLI 28's exact admission/pool/compatibility map.
This continuation closes actual iterator-bound, independently padded load and
pre-replace child-crash rows only. Existing save-size/count/total arithmetic,
three allocation collisions, real fsync faults, post-save child death, contention,
private syntax/identity failures and immutable old bytes remain valid evidence.
CLI 28's 208 targeted / 7,286 full / 288 smoke passes predate these test changes;
they are not a fresh post-change full-suite receipt.

Still unproved here: successful concurrent save/load using actual processes;
real-store-to-reporter failed-save/no-advertisement composition; remaining exact
security/fault rows in STORE 28 (directory/mkdir/race/ownership levels, entry-stat
and insecure entry categories, copied nested pool/privacy, dangling allocation
and occupied precommit target, opened-inode/security mutation and record-specific
open/close faults). No stronger hostile-same-user or guaranteed recovery from an
unresolved OS close requirement is adopted: current C chapter explicitly excludes
privileged same-user tampering and defines safe lock refusal for restore races.
A final exact requirements-to-existing-proof reconciliation is still required.

No complete-package or fresh make integration gate executed here. Full integration
remains after T3/T4 technical readiness per instruction. Baseline lint is unwaived.
No independent review or completion assessment occurred. Required context was
partially refreshed (current store/CLI contracts C 230–542 and exact T3 attachments,
routing/scope plan, KB entry/index/gotchas, shared workflow and engineering rules);
oversized combined skill reads truncated and full requested ingestion is NOT claimed.

**Verdict: INCOMPLETE. Do not promote STORE or overall T3 to READY.**
