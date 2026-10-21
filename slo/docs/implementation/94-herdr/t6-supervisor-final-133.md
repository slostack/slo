# T6 supervisor final 133 — INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 133, retries 0. Effective turns and dispatches unlimited; no agents dispatched. This is not process-family READY, independent review or workflow completion.

## Changes and bounded evidence

Owned only bootstrap and safety-test code. Added instance-local nonblocking capture admission around `supervisor_resources`: simultaneous context entry cannot overwrite the first resource, and an already-retained resource refuses another entry. No global registry. `await_supervisor_ready` now accumulates a bounded exact READY prefix across reads using one monotonic deadline; partial EOF fails and partial timeout never admits TERM. Handler installation remains before READY in the actual supervisor. This is parser proof, not closure of the composed startup race.

Test-first increments, each below approximately 50 implementation lines:

1. `test_supervisor_capture_admission_preserves_active_identity`: actual second thread, no process/signals, independently restores first owner for RED cleanup. RED **1 failed, 68 passed** (second context admitted); GREEN **69 passed**.
2. `test_partial_ready_requires_complete_frame`: injected read/select boundaries for fragmentation, EOF and timeout, killpg explicitly forbidden. RED **2 failed, 70 passed** (fragmentation and timeout rejected as malformed); GREEN **72 passed**. EOF already passed; no red-first claim for that row.

Final post-format chain: **72 passed, 2 warnings, 48.64s**, Black two files unchanged, scoped mypy no issues in two files, `git diff --check` silent, `dpkg -V coreutils` silent; chained exit 0. Earlier mypy required one test annotation; the annotation then required Black formatting. Both corrected before final chain. Warnings: pythonjsonlogger deprecation and LangGraph pending deprecation.

Cwd `/root/Code/slo-94-herdr-integration/slo`. Verified `PYENV_VERSION=slo-harness pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; Poetry Python **3.11.7**. Every pytest command used:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Existing preimport HERDR stripping, synthetic environment and terminal/Herdr spawn guards retained. No new subprocess tests were added. Existing actual leader/grandchild/sentinel tests reran within this explicit safety module. The last final chain used `&&` (not the earlier semicolon chain whose final status alone could mask mypy failure). Output is in tool transcripts, no separate logs created. Both Python files were pre-existing untracked work: diff check cannot inspect their contents; exact replacements and affected source were reviewed directly.

## Finite remaining process-owner rows

These are outstanding semantic cases, not a request to enumerate arbitrary errno combinations.

| Owner / finite obligation | Existing evidence | Remaining required proof/correction |
|---|---|---|
| Parent READY admission | invalid identity/extra bytes/EOF, refusal before READY; new complete-prefix/partial EOF/timeout units | Actual generated startup failure and interrupted partial delivery; handler-installed barrier then TERM before workload creation; prevent spawn after accepted stop |
| Parent capture admission | New concurrent second-context refusal preserves first resource | Concurrent full `run_supervised`, retained-context refusal and distinct-owner capture identities; legacy `run` shares `_process` and must not bypass admission; drain versus active-context coordination |
| Parent pipe allocation/disposal | Existing spawn-failure closes allocated pipe | Close-before/after-error identity handling, both descriptors attempted despite first fault, preserve original exception and typed retention of unresolved descriptor; later drain must dispose retained FDs without closing reused slots |
| Parent capture streams/files | Existing capture survival and later removal under failed join | Open stdout, open stderr after stdout, read, and close failure cases; retain exact stream/resource until disposed and child reaped; cleanup failure must transfer typed capability rather than only add a note |
| Parent stop/wait | Existing ordinary killpg/waitid/getpgid failure still joins; first KeyboardInterrupt plus failed wait transfers typed owner | Repeated KeyboardInterrupt/CancelledError at stop/wait/finalization boundaries with actual finite child and independent cleanup; every cleanup owner attempted; first failure retained |
| Child startup | Linux/isolation refusal, handler before READY in source | Handler/READY write/close/spawn failures, stop-before-spawn cut-off and no workload admission after stop; composed parent EOF/no-signal and cleanup receipts |
| Child status/signals/reaping | Existing actual ordinary status/identity/signal faults retain until explicit barrier; anchor-based signals only | Repeated injected BaseException during monitor, independent TERM/KILL, reap, receipt write, retained status and retry sleep/release; wrapper cannot lose its exact capability |
| Generated wrapper retained lifetime | 132 ordinary-error family reruns green, exact resource, separate sentinel, later two-child receipts and parent join | Preserve indefinite HOLD when drain unproved; repeated injected interruptions must not escape; controlled test cleanup opens barriers and performs actual joins even on RED |
| Normal/timeout/orphan closure | Existing `test_supervisor_reaps_real_descendants[early,timeout,ignore]`, parent timeout, generated wrapper and independent sentinel tests rerun green | Carry actual waitpid receipts into final composed startup/FD/capture/interrupt cases; existing passes do not prove new failure cases |

`RetainedResourceError` is the existing typed capability name; no second generic framework or renamed exception introduced. Its current parent reachability is not sufficient for missing FD/stream ownership. A Popen returncode alone is not a descendant-reap receipt. SIGKILL/crash recovery and escaped descendant groups remain outside the stated fixture contract.

Exec/mutation guards remain a **separate subsequent gate**: actual approved entry/fake identity, descriptor mutation capability, capture bounds/root/script substitution and receipt namespace. No positive parent/entry wiring, old probe, positive family or full make until parent HOLD is explicitly lifted. No new errno matrix is proposed.

## Reads / safety boundaries

AGENTS.md, CLAUDE.md and docs/RESEARCH.md supplied in full context; root RESEARCH read directly. Read routing/scope plan, 129–132 supervisor receipts, current safety-123, complete actual bootstrap and 806-line pre-edit safety module, state_isolation and root conftest guards. Read checkout engineering routing/testing/ownership, coding-rules/code-test-loop, shared declarative, Python root/declarative/named-arguments/docstrings and canonical workflow SKILL without truncation. Python declarative was read before its shared owner, then the shared owner fully read before implementation. No dedicated Python process skill was identified.

Read KB Welcome, slo README/gotchas, machine guardian ROLE first, then README, complete workload detail in bounded pieces and security guardian rules. Canonical Herdr B default-suite isolation lines 1872–1925 and C lifetime/drain mapping lines 2060–2105 consulted read-only, not entire B/C chapters. No claim of complete specification reread or independent acceptance. Broader mandatory affected-flow reads were not completed for the unimplemented families; only the two bounded changes above are verified.

No agents, commits/push/PR/reset/clean/stash, global/live/spec/other-worktree/KB/shared-workflow-status edits, real providers/Herdr/windows, old probe or full suite. Only this receipt and safety-123 current section are documentation outputs; historical sections remain intact. No live-host operation or system executable mutation. **Requested complete finite PROCESS safety closure was not achieved; INCOMPLETE/HOLD.**
