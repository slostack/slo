# T6 supervisor faults 130 — INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 130, retries 0. Effective turn and dispatch budgets unlimited. No agents dispatched; no completed turn or independent review claimed.

## Outcome

**Supervisor family NOT READY.** No bootstrap or safety-test changes were made in this continuation. No RED/GREEN, pytest, Black or mypy run occurred. The 58-pass result in handoff 129 is historical evidence only, not fresh verification. Positive family, parent/entry wiring, mutation/real-exec proof, and full make remain HOLD.

## Inspected ownership failures

Read `t6-supervisor-handoff-129.md`, the current safety-123 section and its historical checklist, bootstrap lines 1–359, and safety-test lines 1–80. These are source findings, not executed fault proofs:

- `OwnedSupervisor.invoke`: identity checks and TERM/KILL calls in `finally` can raise before the subsequent reap loop. TERM failure skips KILL. The reap loop uses blocking `waitpid(-1, 0)` with no bounded pending-owner protocol. Status-receipt write happens after reaping, but status/wait/identity faults earlier in the lifetime have no complete cleanup boundary.
- READY is emitted after installing TERM handling, but a stop received before `Popen` does not gate workload creation.
- `OwnedProcessRun.run_supervised`: stop and wait share one try, so a stop failure skips the wait attempt. Cleanup failures add only an exception note, not a typed retained resource capability. The ready-pipe `finally` close can replace the primary failure.
- `supervisor_resources`: a descriptor-close failure interrupts the descriptor loop and later directory disposition. Descriptor retries have no retained identity contract. Context entry replaces `self.retained` without an active-context guard.
- `drain_supervisor`: waits and removes captures but does not drain retained pipe descriptors. Parent join alone is not evidence that the supervisor handled all descendants correctly.

All six remaining blocker rows in handoff 129 remain open. Repeated interruption, capture open/write/read/close faults, startup failure/partial handshake, bounded descendant drain and separate-sentinel survival have no new evidence here. No claim is made that injected mocks would establish actual POSIX cleanup.

## Reads and limitations

AGENTS.md, CLAUDE.md and docs/RESEARCH.md were supplied in session context. Root RESEARCH was read directly. Machine guardian `os/ROLE.md`, `os/README.md`, and `os/workloads-services-resources.md` were read fully before any test/process operation; no workload operation followed.

A combined read included routing, scope-plan, engineering routing/testing/ownership, coding rules/cadence and root RESEARCH. Its output was truncated, so complete ingestion of that combined request is NOT claimed. Python conventions was read fully. Required remaining complete reads—including KB entry/project gotchas/security detail, Python style/declarative companions, canonical workflow SKILL and read-only Herdr B/C safety contracts—were not completed. Implementation prerequisites therefore remain incomplete.

One parallel read request omitted its path arguments: four calls failed validation and read nothing. They are not consultation evidence.

## Artifact-location deviation

The combined Bash read exceeded the output limit. The tool automatically spilled its full output to `/tmp/slo-bash-z2w0u0d1.txt`, outside the user-authorized receipt/test locations. This was a mistake, not an approved artifact write. It was not reopened, altered or removed. The prior `/tmp/unused-read-output` disclosed by handoff 129 was likewise not touched. No cleanup outside authorized paths is implied or performed.

## Commands and evidence

Cwd: `/root/Code/slo-94-herdr-integration/slo`.

Read-only status command:

```text
git status --short -- tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
?? tests/integration/herdr_restore_process_bootstrap.py
?? tests/integration/test_herdr_restore_harness_safety.py
```

`dpkg -V coreutils`: empty output, exit 0 (last command in the successful combined status/line-count check). No test subprocesses or command stubs were launched. Approved interpreter identity was not freshly verified; no Python verification result is claimed. No scoped static or diff-check result is claimed.

Only this receipt and the current section of `t6-harness-safety-123.md` were intentionally written. Historical sections are preserved. No production/spec/other-worktree/shared-status/KB changes, Git mutation, live Herdr/provider/window, old probe, positive-family test or full-suite execution occurred.

## Required continuation

Finish the missing safety reads and inspect the complete affected bootstrap/test/fixture sources before execution. Then implement in approximately 50-line bounded RED/GREEN increments, running the explicit safety module before each next increment. Closure must prove all cleanup owners are attempted despite independent failures, typed retained ownership without public private-path leakage, primary-failure preservation, startup stop admission, identity-safe descriptor disposition, bounded TERM/KILL and persistent pending supervision when descendant joining cannot be established. Use contained dummy processes and barriers plus injected owner syscalls, including unrelated owned sentinel survival. Finish scoped Black/mypy, source review/diff checks and silent coreutils verification. Do not promote parent/entry or positive-family execution on partial supervisor evidence.
