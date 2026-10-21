# T6 bounded capture fault gate 144 — READYCAPTUREGATE

**READY for the three capture-proof rows only.** This is not whole-map, parent-positive, full-suite, independent-review, live Herdr, or feature acceptance. Parent positive and full make remain **HOLD**. No old unsafe probe ran.

Accounting preserved: same unfinished turn 1; started 1, completed 0, historical partial 1, supplied dispatch 144, retries 0. User's turn AND dispatch limits are unlimited; no agents dispatched here.

## Scope and routing

Only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py` were edited as code. Entry and parent wiring were read-only. Existing work and other-lane whole-map ownership were preserved. Documentation writes are this receipt and `capture144-*` evidence only; no shared status/safety123/spec/KB/global edits, commits, pushes, PRs, reset, clean or stash.

Python 3.11.7 approved `slo-harness`; deterministic syscall-boundary units plus contained real descriptors and the existing supervised safety module. Shared engineering routing/testing/ownership, coding rules/cadence, Python root, shared/Python declarative guidance, named arguments, method docstrings, Faux guidance and workflow SKILL were loaded. AGENTS/CLAUDE/docs RESEARCH were supplied in context; root RESEARCH, routing.md, scope-plan.md and receipt143 were read. KB ROLE first, README, Slo README/gotchas and workload detail consulted. The first combined KB output truncated; Welcome and os README were subsequently read separately. No claim of complete unrelated KB/spec ingestion. Six malformed parallel read calls read nothing and were replaced with direct reads. B 1872–2043 fixture prerequisite and C 295–325/2100–2175 construction/functional-restore clauses were read; state_isolation guard, root conftest stripping/terminal/spawn guards and relevant entry/parent wiring inspected. No broader source-map approval is inferred.

Plan executed: reproduce close-primary defect first → minimal bootstrap correction → complete safety module green; then nonregular opened substitution → green; close dispositions → green; registration/refusal inventory in small units → green; static checks and final post-format safety rerun. Existing correct behavior received coverage without manufacturing a RED.

## Three finite rows

| Row | Evidence and result |
|---|---|
| Nonregular opened substitution | `test_capture_opened_nonregular_substitution[directory,fifo]` returns an owned preopened directory or O_RDWR\|O_NONBLOCK FIFO FD at the open seam. Refuses before write, original bytes unchanged, allocated FD closed. FIFO never blocks; no system FD used. Initially correct, coverage-only. |
| Capture close-error dispositions | `test_capture_refusal_preserves_primary_on_close_error` exposed an actual defect: finally's close exception replaced admission PermissionError. RED 1 failed/148 deselected. Bootstrap now preserves primary while retaining the close owner. `test_capture_close_error_dispositions` covers refusal/success × remains-open/closed/reused (6 cases), exact original identity, one close attempt, retained ambiguity, no retry of reused slot, victim unchanged. `test_capture_primary_io_failure_with_close_failure` adds initial-fstat and partial-write boundaries. |
| Capture registration refusal inventory | Actual `FakeHerdrSpawnGuard`, not a duplicate validator: `test_capture_registration_refusal_inventory` covers executable/capture/barrier × relative/traversal/outside/root/directory/symlink/hardlink/missing (24); `test_capture_registration_revalidation_inventory` covers all three × identity/mode/missing/stat-error/hardlink/directory/symlink (21); `test_capture_registration_boundary_errors` covers root missing/root inspection error, executable mode, wrong executable and each file's registration inspection error (7). Valid registration/revalidation precedes mutations. Failed initial registration grants nothing; wrong executable stays refused. All writes/links/renames concern contained test-owned files, and no execution follows these guard-only tests. Initially correct behavior, coverage-only. |

The actual contract binds a caller-supplied existing resolved root and regular single-link file identities. It does not impose immutable root directory inode/mode or capture/barrier permission modes. Owner-execute is required for the executable at registration and revalidation. Capture/barrier mode 0400 remains admissible; real OS I/O permissions determine later writes. Root equality as a file, outside containment, missing roots and resolution errors are tested; no invented root permission/inode contract or all-errno matrix. Existing generated-script and registered/substituted Popen/run/async execution proofs reran as part of the safety module.

## Corrected ownership and truthful I/O semantics

`ProcessSafety.retained_captures` retains the existing `OwnedDescriptor` after failed cleanup. An already-active exception remains the raised primary; otherwise the close error propagates. The descriptor owner keeps device/inode and ambiguity, and reconciliation never retries an ambiguous close. Reused slots are relinquished without closing the new file. The generated writer is disposable: process exit ultimately releases descriptors that could not be safely closed. No automatic retry, finalizer, new process manager or general recovery subsystem was added.

Before-write refusals leave bytes unchanged. After a successful append, close failure can leave the complete appended bytes; after partial write failure, a prefix can remain. Tests assert both outcomes. This is not atomic capture, rollback, durability or zero-byte-on-I/O-failure semantics. Initial fstat failure has no captured identity: exclusive allocation ownership is assumed, with one close attempt and retained ambiguity on failure. It is not proof against arbitrary same-process malicious close/reuse before the first inspection. Existing initial-inspection/cleanup and 143 pathname/reuse proofs remain intact.

## Exact execution and receipts

Cwd: `/root/Code/slo-94-herdr-integration/slo`. No env file sourced. Every pytest command used:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
$P -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
```

Root fixtures remove inherited case-insensitive HERDR settings before application imports/per-test binding, disable integration, isolate state and retain independent fake-only spawn/terminal guards. New tests use no provider/model runtime. Existing module subprocess tests use owned finite/supervised workloads only. No positive entry/full make/real Herdr/window/provider ran.

| Receipt prefix | Result |
|---|---|
| capture144-red | Same command with `-k capture_refusal_preserves_primary_on_close_error`: exit 1, 1 failed/148 deselected |
| capture144-green1 | exit 0, 149 passed |
| capture144-green2 | exit 0, 151 passed |
| capture144-green3 | exit 0, 157 passed |
| capture144-green4 | exit 0, 181 passed |
| capture144-green5 | exit 0, 196 passed |
| capture144-green6 | exit 0, 202 passed |
| capture144-green7 | exit 0, 209 passed |
| capture144-green8 | exit 0, 211 passed |
| capture144-final | **exit 0, 211 passed, 2 warnings in 71.70s**, after final formatting |

Each prefix has `.log` and `.exit`. Full safety gate after each increment, not just new selections. Deprecation warnings only. `dpkg -V coreutils` ran immediately after every test invocation and was silent; final output/exit persisted.

Four-file static set:

- tests/integration/herdr_restore_process_bootstrap.py
- tests/integration/herdr_restore_process_entry.py
- tests/integration/test_herdr_two_process_restore.py
- tests/integration/test_herdr_restore_harness_safety.py

`$P -B -m black --check <four paths>`: exit 0, four unchanged (`capture144-black-final.*`). `$P -B -m mypy --follow-imports=skip <four paths>`: exit 0, no issues in four source files (`capture144-mypy-final.*`); scoped check, not repository-wide lint. Black formatted only the two owned files (`capture144-format-final.log`). `git diff --check`: exit 0/silent (`capture144-diff-final.*`). Files are untracked in this feature worktree, so HEAD diff cannot represent their bodies; edited regions inspected directly. Four-file hashes: `capture144-files.sha256`. `capture144-coreutils-final.*`: exit 0/empty log.

## Handoff

**READYCAPTUREGATE**: all three requested capture families proved, one newly reproduced defect corrected test-first, 63 added cases over the 148 baseline. Other-lane whole-map/reachable syscall reconciliation remains independent and read-only here. Parent-positive/full make remain HOLD pending their owner; no aggregate T6 READY or completed workflow turn claimed.
