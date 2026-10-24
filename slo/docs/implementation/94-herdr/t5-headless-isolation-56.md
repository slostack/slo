# T5 headless isolation continuation 56 — INCOMPLETE

Same unfinished turn 1: started 1/completed 0/historical partial 1/dispatch 56/retries 0. User turn/dispatch budgets unlimited. No agents dispatched. No workflow completion or family READY claim.

## Owned changes

`src/cli/headless.py`: isolate ordinary reporting-close and final-drain exceptions independently, preserving the enclosing original result/exception and still attempting both gateways. A fixed stderr diagnostic is best effort; no exception text is emitted. Escaping cancellation is not caught. The real session final-drain gateway's pending behavior is unchanged. This does not prove every cancellation combination or repair watchdog/catalog cleanup.

`tests/cli/test_headless_herdr.py`: eight orchestration cases cover close/final-drain ordinary failure with successful/original-exception runs and healthy/throwing diagnostic sink. Two real config-backed session/Faux/registered fake Herdr runs cover enabled and disabled operation, final JSONL answer/terminal kind, non-injected construction, absent native restore capture/argv, synthetic credential absence from captured channels and credential-reference clearing. Enabled capture is nonempty; disabled capture is empty. This is not byte-for-byte whole-stream parity or a complete privacy matrix.

No session-service, scheduler, TUI or other source edits in this continuation. Existing partial work preserved.

## Actual commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; `PYENV_VERSION=slo-harness`, approved 3.11.7 fallback. Targeted runs use `bash docs/implementation/94-herdr/t1-dao-check.sh`, whose DAO/projection cases are included in counts. No installation/environment mutation.

| Stem | Additional test arguments / command | Result |
|---|---|---|
| t5-56-cleanup-red | tests/cli/test_headless_herdr.py | 4 failed, 62 passed; exit 1. Actual cleanup exceptions replaced original results/errors. |
| t5-56-cleanup-green | new module, test_headless.py, herdr/test_session_lifetime.py | 176 passed; exit 0 |
| t5-56-faux | new module | 68 passed; exit 0 |
| t5-56-diagnostic | new module | 4 failed, 68 passed; exit 1. Test initially broke mandatory lifecycle stderr too; corrected injection to the exact optional diagnostic. Not a product regression claim. |
| t5-56-surrounding | new module, test_headless.py, herdr/test_session_lifetime.py, scheduling/test_runtime_helpers.py, orchestrator/test_spawn_env.py | 204 passed, 4 warnings; exit 0 |
| t5-56-format | poetry run black src/cli/headless.py tests/cli/test_headless_herdr.py | formatted successfully; see log |
| t5-56-diff | git diff --check | silent, exit 0 |
| t5-56-coreutils | dpkg -V coreutils after suites | silent, exit 0 |

Every test stem has full `.log` and `.exit`. Full make test/smoke/lint were NOT rerun: family is not ready. Continuation 55's 7741/288/299-in-63 baseline is historical, not this snapshot's evidence. No new exact lint-baseline comparison or final snapshot manifest is claimed.

## Finite outstanding map

1. **C 7.2 / section 8 actual composition:** basic actual Faux plus registered CLI enabled/disabled is now exercised. Still require exact normalized JSONL parity, terminal failure/abort composition and adequate admitted-command barriers; current tests do not establish all of those.
2. **C lifetime ownership:** actual retained child/lease through runner activation, close, final drain, repeated cancellation and persistent pending-owner proof remains outstanding. Session-level tests passed but are not substituted for runner proof.
3. **Original outcome matrix:** reporting close/final-drain ordinary errors now preserve results/exceptions. Watchdog stop, signal restoration fault, catalog shutdown fault, status/notification interactions, simultaneous cleanup faults and cancellation precedence remain outstanding. No claim that catching ordinary errors establishes successful resource disposal; real persistent pending gateway must remain pending.
4. **Required reads:** routing.md, scope-plan.md, root RESEARCH, KB Welcome/slo README/gotchas and selected engineering/Python/Typer/Faux/declarative/workflow skills were consumed. C was read at 1–820 and 1980–2175 plus search context; missing middle ranges, exact T5 attachments, B optional isolation and accepted-review full reads remain outstanding. AGENTS/CLAUDE/docs RESEARCH were supplied in context; concatenating them to a temporary file was not a full tool-output ingestion and is not claimed as read closure. Remaining style/build-rule reads are likewise not claimed complete.

Scheduler 54 actual fresh/resume proof retained without rewrites; surrounding scheduler/spawn-env tests passed. Complete canonical-prefix/all-unrelated environment audit and all launch/relaunch exclusions remain to map. TUI, usage53 qualification, T6 and independent review are separate.

No commits/push/PR/reset/clean/stash/global/live/specification/other-worktree changes. No real provider, Herdr or terminal window. This is a partial correction with explicit remaining evidence, not completion.
