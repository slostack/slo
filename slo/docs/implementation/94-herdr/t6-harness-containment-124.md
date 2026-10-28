# T6 containment 124 — implemented bounded increments; INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 124, retries 0. Turns and dispatches unlimited; no agents dispatched. No workflow acceptance claimed.

## Scope and routing

Python 3.11 test-harness guards and isolated admission/syscall units, not application changes. Shared engineering routing/testing/ownership, coding rules/cadence, Python root/style/declarative and Faux guidance govern; workflow SKILL counting consulted. Existing routing.md and scope-plan.md remain unchanged. Actual AGENTS.md, CLAUDE.md, root and docs RESEARCH read, together with exact 122/123 receipts and three harness sources. KB Welcome/slo README/gotchas and os ROLE/README/workload detail consulted. Canonical read-only H B isolation prerequisite (1872–2045) and C lifetime/two-process requirements (2080–2175) consulted. This is scoped contract consultation, not full chapter re-ingestion or independent review. Oversized combined reads produced truncation; relevant routing/core rules and actual instruction/research missing portions were reread separately. No claim of full-library ingestion.

Plan executed: first contain legacy victim → descriptor/path RED/GREEN → directory-relative RED/GREEN → alternate audit execution/direct-fd syscall RED/GREEN → open-dirfd/stdio RED/GREEN → installation/executable hardlink RED/GREEN. Keep the positive family held; parent cleanup is a separate next finite unit.

Only four authorized Python files changed:
- test_herdr_two_process_restore.py: parent creates narrower child root and regular sibling forbidden-write victim within tmp_path.
- herdr_restore_process_bootstrap.py: Linux /proc/self/fd path plus fstat/dev/inode checks; reject traversal, symbolic and multiple hard links, special files; directory-relative audit admission; pre-truncation os.open wrapper; direct fd syscall wrappers; explicit identity-bound stdio write/writev allowance distinct from private-file mutation; deny exec/fork/forkpty alongside existing system/posix_spawn boundaries; revalidate registered executable containment/type/link count/identity.
- herdr_restore_process_entry.py: install guard before application imports, and generated fake installs guard before capture append. Generated fake has no executable registration, so its subprocess audit path refuses all children.
- NEW test_herdr_restore_harness_safety.py: safe import of bootstrap only; no entry import, old probe or positive harness execution. Negative mutation victims and inert executable fixtures are newly created under tmp_path. Audit execution tests only call policy, never execute a dummy or host binary. Actual write/ftruncate/fchmod/open negatives are bounded to new regular sibling files even if guards regress.

No production, shared-status, canonical spec, KB, global, other-worktree or Git mutation. No provider/Herdr/window execution, system symlink fixture, install or full make.

## Commands and receipts

Cwd: /root/Code/slo-94-herdr-integration/slo.
`PYENV_VERSION=slo-harness; pyenv which python; python --version` verified /root/.pyenv/versions/slo-harness/bin/python, Python 3.11.7.

Every test run used the explicitly authorized command:

```sh
export PYENV_VERSION=slo-harness
bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_restore_harness_safety.py
```

The reviewed script adds 62 DAO/projection surrounding tests and supplies synthetic fallback settings with Herdr/windows disabled. Root stripping and terminal/Herdr guards unchanged. No directory-wide collection or old two-process file selected.

Receipts are `t6-124-{red1,green1,red2,green2,red3,green3,red4,green4,red5,green5,final}.{log,exit}` in this directory:

| Increment | RED | GREEN |
|---|---|---|
| fd/path | 5 failed, 64 passed | 69 passed |
| dirfd | 7 failed, 69 passed | 76 passed |
| alternate audit exec/direct fd | 6 failed, 79 passed | 85 passed |
| open-dirfd/stdio | 2 failed, 85 passed | 87 passed |
| installation/executable hardlink | 2 failed, 87 passed | 89 passed |

Final after scoped Black formatting: **89 passed, 2 warnings, exit 0** (27 new safety units + 62 surrounding). All increments were below approximately 50 harness implementation lines before verification. Initial Black check correctly failed on two files; scoped format followed; final four-file Black check exit 0 (`t6-124-black.log/.exit`). No mypy result claimed. Coreutils checked after every test run; final `t6-124-coreutils.log` empty, exit 0. Source reread after formatting; untracked files are not claimed covered by git diff.

## Precise remaining blockers — do not lift hold

1. Parent timeout/descendant ownership is unchanged: subprocess.run timeout is not a retained session/group cleanup owner. Must implement and prove identity-safe descendant cleanup/reaping with unrelated owned sentinel preservation before positive execution.
2. Guard proof is incomplete. Audit negatives prove policy decisions, not actual installed subprocess/async/exec/spawn dispatch. Need safe reversible interception tests for actual entry surfaces plus narrowly approved Python-entry handling. No actual fake executable ran here.
3. Mutation coverage remains incomplete: chown/utime/xattrs and other non-audited mutation paths, descriptor duplication/reuse, preopened buffered handles, missing/deleted descriptors and root replacement need explicit inventory and decision-path tests. Direct wrappers do not claim to cover native/C bypasses.
4. os.open wrapper correctly validates dir_fd before mutation, but installed audit callback sees the relative name without dir_fd; valid contained relative opens from an outside cwd may be over-refused. Resolve and prove wrapper/audit cooperation before positive use.
5. Generated fake now installs the guard, but composed descendant execution/capture behavior has not been run or proved. Its existing capture path/inode assertion still needs opened-descriptor validation and substitution tests. Installation unit intercepts addaudithook; it is not child-process proof.
6. The legacy probe was not run. Its write victim is now parent-owned, but it still contains a loopback connection and missing-command attempt; replace those with independently safe refusal checks before any future probe execution. Parent-owned victim containment has no concurrent hostile substitution guarantee.
7. Path validation followed by syscall is bounded accident prevention, not atomic filesystem confinement or a malicious-Python sandbox. No OS sandbox claim; no protection asserted against arbitrary native code or malicious same-process monkeypatching.

**Verdict: INCOMPLETE — HOLD active.** Real repairs and safe RED/GREEN evidence are delivered, but bounded-containment READY is withheld until remaining guard proof and parent cleanup close. Parent authorization is required before the positive harness; no full-suite authorization follows from this receipt.
