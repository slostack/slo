# T6 harness author audit 141 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 141, retries 0. Effective turn and dispatch budgets unlimited; no agents dispatched. Positive family and full make remain HOLD. This is author evidence, not independent acceptance.

## Changes and bounded test-first evidence

Only the three harness files and `tests/integration/test_herdr_restore_harness_safety.py` changed as code. Documentation writes are this file and a current section in safety123. No production, other-lane full-flow, specifications, shared workflow status, KB, other worktree, host settings, installed commands or Git state mutations.

1. Parent positive requests now use the actual `OwnedProcessRun.run_supervised` API, not `subprocess.run` or PATH resolution. A new regular temp-owned `slo` source shim is created after containment checks, chmodded and registered with `FakeHerdrSpawnGuard` before first entry. The same registered identity is rechecked before restore. Both requests are `[sys.executable, '-I', '-B', absolute_shim, ...]`, with explicit HOME/SLO_HOME/T6_ROOT and phase-specific policy/capability only. The literal advertised `slo --resume ... --herdr-restore ...` remains asserted independently and its argument tail reaches the actual CLI entry. Same SLO_HOME is preserved.
2. Publisher no longer rewrites/chmods the parent's registered shim. This avoids silently changing the admitted entry content between phases.
3. Parent bootstrap probe now uses supervised isolated Python and a contained generated probe script. Its only real negative mutation targets its own precreated sibling victim. Network/execution refusal checks are inert audit calls: guard regression cannot contact a port or resolve an unqualified command. Bytes/device/inode/mode are checked after completion.
4. Generated fake shebang now includes `-B`: its bootstrap import must not create repository bytecode before guard installation. This flag is explicit because Python flags are not inherited by shebang children.
5. Eight actual installed-audit mutation tests exercise write_text, touch, chmod, unlink, replace source, replace destination, mkdir and rmdir. Every negative victim is inside the enclosing test root, outside the narrower child root. Assert unchanged bytes, device/inode/mode/mtime, own source bytes and directory presence. No product entry executes.

RED/GREEN sequence, same explicit safety module:

| Selector / gate | Actual result |
|---|---|
| `-k positive_parent` before parent edit | 2 failed / 127 deselected; `AssertionError: legacy subprocess.run reached`; exit 1 |
| Whole module after parent edit | 129 passed, 2 warnings, 58.46s; exit 0 |
| `-k preserves_parent` before removing child rewrite | 1 failed / 129 deselected; AST found two shim mutation calls; exit 1 |
| Whole module after removal | 130 passed, 2 warnings, 58.46s; exit 0 |
| `-k safe_parent_probe` before probe wiring | 1 failed / 130 deselected; `AssertionError: legacy probe spawn`; exit 1 |
| Whole module after supervised probe | 131 passed, 2 warnings, 58.89s; exit 0 |
| `-k disables_bytecode` before shebang correction | 1 failed / 131 deselected; shebang lacks ` -B`; exit 1 |
| Whole module after shebang correction | 132 passed, 2 warnings, 58.98s; exit 0 |
| `-k used_mutations` | 8 passed / 132 deselected, 2 warnings, 4.02s; exit 0 |
| Final formatted safety module | **140 passed, 2 warnings, 61.42s; exit 0** |

The parent-wiring tests patch the owned runner to validate/record exact requests and synthesize only advertised.json, then stop at the second request. They forbid both legacy run and actual Popen. They do NOT prove positive application execution. The shim-preservation and bytecode checks are source-contract assertions, not dynamic substitution proofs. Prior PROCESS136 and generated-capture/exec140 evidence remains historical and was also exercised by the final safety module.

## Finite actual-used mutation map — partial reconciliation

| Used surface / caller | Admission / evidence |
|---|---|
| Parent state directory and source shim creation/chmod | Explicit ProcessSafety.contained before mutation; FakeHerdrSpawnGuard registration/revalidation; exact-request parent test |
| Supervisor wrapper, captures, reap receipt, temp directory removal | Existing contained wrapper/capture/resource paths; OwnedDescriptor lifetime; PROCESS136 tests rerun in module |
| Entry null sink, capture, generated fake, workspace/plugins, JSON observations | Installed `open`, mkdir/chmod/remove audit; `test_used_mutations_installed_guard` now actual syscall refusal, not audit-only |
| Entry plugin touch and loaded-marker unlink | `open`/utime/remove audit; actual touch/unlink cases preserve contained sibling victim |
| AtomicFileWriter temp buffered write, chmod, replace, failure unlink | Open admission and chmod/rename/remove audit; both source and destination replace refusal now executed. Complete application-call-chain inventory still pending |
| Fake append | no-create/no-truncate O_NOFOLLOW open, fstat regular/single-link + registered device/inode, descriptor_path then wrapped os.write; generated substitution sensitivity and descriptor cleanup cases rerun |
| Descriptor mutation | `test_descriptor_mutation_refuses_parent_victim`, `test_fd_syscall_wrapper_denies_before_mutation`, explicit stdio scope; existing matrix covers write/ftruncate/fchmod, not every wrapper branch |
| dir_fd | Existing open wrapper refusal and absolute normalization tests; audit-level mkdir/remove/rmdir/chmod/rename/link tests; owned-dirfd admission test |
| Link/traversal | Existing symlink/hardlink/traversal capture and mutation tests; executable hardlink/substitution refusal |
| Execution | Actual registered/substituted Popen/run/asyncio and installed refusal exec/spawn tests; audit-level fork/forkpty/system denial. Parent now uses isolated explicit Python, no PATH lookup |

This table is NOT a completed all-used-operations proof. Opened-FD special/nonregular/deleted/reused identity cases, complete used application persistence/cleanup traversal, and the exact unsupported-fallthrough reconciliation still require closure. No claim of atomic check/use filesystem isolation, malicious-Python sandbox, arbitrary API coverage, or installed-launcher compatibility.

## Reads and remaining read closure

Fresh complete reads: actual AGENTS.md (1–480, 481–1080), CLAUDE.md, root RESEARCH.md, docs/RESEARCH.md (1–360, 361–693), routing.md, scope-plan.md, safety123 and sensitivity140, all three initial harness files, state_isolation.py and root conftest through its fake fixture, Makefile. Safety module was read in relevant mutation/process sections, not every remaining historical process-test line.

Consulted KB Welcome, os ROLE/README, workloads-services-resources (1–220 and remainder), security guardian rules and Slo README/gotchas. No KB change. Selected committed engineering routing/ownership/testing, coding rules/code-test-loop/declarative, Python root/declarative/named arguments/docstrings/Faux recipe, workflow SKILL. A combined skills read truncated its beginning; engineering ownership/testing/coding rules were then reread completely. A combined KB read truncated its beginning; workloads was reread. Six malformed parallel reads returned validation errors and read nothing; no success is inferred from them.

Canonical read-only: B default-suite prerequisite and helper coverage lines 1872–2070; C tests/acceptance/dependencies 2122–2175; exact T6 task 238–285 and attachments 3721–3816; accepted independent turn4 review and finalization receipt. Complete required context closure is **not claimed**: broader C restore construction details, remaining accepted task-breakdown evidence, selected index and all affected persistence owners still need reconciliation. No dedicated Python process skill was identified; the existing scoped supervisor contract applies.

## Exact final commands/output

Cwd `/root/Code/slo-94-herdr-integration/slo`. No environment file sourced. Every pytest command used:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
"$P" --version
"$P" -B -m black tests/integration/test_herdr_restore_harness_safety.py
"$P" -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
dpkg -V coreutils
"$P" -B -m black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py tests/integration/test_herdr_two_process_restore.py tests/integration/test_herdr_restore_harness_safety.py
"$P" -B -m mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py tests/integration/test_herdr_two_process_restore.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
```

Actual final output:

```text
Python 3.11.7
140 passed, 2 warnings in 61.42s (0:01:01)
4 files would be left unchanged.
Success: no issues found in 4 source files
pytest=0 coreutils=0 black=0 mypy=0 diff=0
```

Coreutils was silent after every pytest invocation; diff check silent. Warnings: pythonjsonlogger relocation and LangGraph allowed_objects pending default. Root fixtures strip inherited HERDR before application imports and each test, preserving independent fake-only spawn and terminal guards. Supervised children use explicit environments rather than inherited credentials. Static mypy is scoped with skipped imports, not the full repository lint gate. These harness files are untracked; ordinary HEAD diff cannot describe their full contents.

## Verdict / next exact work

**INCOMPLETE — do not run positive Herdr family or full make.** Parent wiring is implemented and request-tested, safe contained probe executed, generated fake bytecode gap fixed test-first, and 140 safety tests pass. Overall safety READY is withheld because the finite mutation/opened-FD map and mandatory context reconciliation are not complete. Finish those rows, including application persistence owners, before parent verification/positive authorization. No arbitrary workflow budget limit was applied; counts remain unchanged. No real Herdr/provider/window, old unsafe probe, live/global mutation, agents, commit/push/PR/reset/clean/stash occurred.
