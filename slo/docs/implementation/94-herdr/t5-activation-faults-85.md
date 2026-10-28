# T5 activation faults 85 — INCOMPLETE finite family

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 85, retries 0. Effective turns and dispatches unlimited. No agents launched. No production files modified by this continuation; no app.py or other activation-test edits. No commit/push/PR, global/live/specification/other-worktree changes. Existing parallel work preserved.

## Delivered evidence

Added only `tests/tui/test_herdr_activation_faults.py` (14 parameter cases) and this report plus `t5-85-*` receipts. Reuses the existing native Faux factory, command reader and bounded waiter without editing their owning file. Every mounted session is config-backed, with real temporary history, actual reporter/transport and registered regular fake executable. Wire cases use actual captured child argv and real CLI timeout/reaping, not substituted outcome DAOs.

| Branch | New mounted evidence | Outcome |
|---|---|---|
| Integration-parent preparation error | `_prepare_herdr_parent` throws before reporter assembly | uncertain/drained; successor suppressed; zero commands |
| Executable validation error | `_validate_executable` throws before lease | uncertain/drained; successor suppressed; zero commands |
| Activation release rejected / timeout | Registered child exits 7 / sleeps past transport deadline | uncertain/drained; no successor activation or metadata |
| Claim rejected / timeout, subsequent release confirmed | Actual possible binding followed by successful shutdown withdrawal | safe/drained; new session claims |
| Restore install rejected / timeout | Actual saved native capture and attempted reference install; identity remains confirmed, restore ack absent | confirmed shutdown release permits new claim |
| Shutdown release rejected / timeout | Actual previously acknowledged display, then failing release | uncertain/drained; no metadata clear or successor activation |
| Shutdown metadata clear rejected / timeout | Withdrawal confirmed before failed clear | safe/drained; provisional retained close does not poison final safe outcome; new claim |
| Reporter close raises after actual cleanup | Real close runs, wrapper raises | sticky uncertain/drained; two successors suppressed |
| Final transport gateway raises after actual cleanup | Real transport seals/drains/unlocks, wrapper raises | sticky uncertain/retained from last returned provisional outcome; app retains predecessor, successors suppressed |

The two local-probe cases additionally submit through actual PromptInput, wait for the Faux answer, assert the same original session remains selected and has durable `run_completed`, then replace it. This proves original-session usability for those faults, not every wire fault.

No production defect was demonstrated. The first close-fault run failed one **test assumption**: a throwing final gateway does not return final drained evidence. Session correctly retains the prior returned provisional outcome conservatively, despite the actual getter reporting drained. Corrected assertion preserves that contract and verifies the app-retained predecessor; no uncertainty flag or production policy changed. This is not a RED-to-GREEN production repair.

## Finite parent map / remaining work

Retained 82/83/84 evidence remains applicable: native mount/save/display/replacement; disabled/outside parity; assembly/start cancellation; actual lease contender refusal; persistent unlock retention; remote/cleanup drained uncertainty and collectability. T2 remains the errno/transport-accounting matrix owner; this file does not duplicate every errno.

The family is **not READY**. Remaining closure obligations:

1. Complete canonical audit: exact T5 attachments and accepted reviews, full affected B/C uncertainty clauses, and remaining requested build/style/Textual guidance. This continuation read B A2/restore-composition clauses, B branch ledger excerpts, C7.2/C7.11 and actual close/activation/accounting APIs, not the entire requested canonical closure set.
2. Mount-level definitive spawn-failure contrast versus admitted remote ambiguity; cancellation/late-result variants and stale restore/replacement-release composition need explicit reuse or new proof in the finite map.
3. Actual claim/probe cutoffs outside these executable/parent probes (including runtime capability/diagnostic failure cutoffs) need mapping against the parallel owner, not an assumption that low-level tests close app interpretation.
4. Original-session prompt/history usability is proved for local probes only. Extend it across the relevant remaining optional fault classes.
5. Final transport throwing-gateway case checks retained ownership during replacement, but does not independently assert the explicit final local drain/collection result after teardown.
6. Full parent activation closure and independent acceptance remain outstanding; no inbox/viewer work began. No app.py fix need has been established.

This is a coverage/prerequisite shortfall, not a turn/dispatch budget stop. No arbitrary case-count acceptance cap is asserted.

## Verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Pytest commands all use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <arguments>`, including its 62 DAO/projection cases, approved fallback, HERDR stripping, temporary state and terminal/fake-only spawn guards. No new venv or real provider/Herdr/window.

| Prefix | Arguments / action | Result |
|---|---|---|
| t5-85-probe | new fault file | 64 passed, exit 0 |
| t5-85-probe-surrounding | new file + reporter_shutdown_closure + session_lifetime | 129 passed, exit 0 |
| t5-85-wire | new file | 72 passed, exit 0 |
| t5-85-wire-surrounding | new file + reporter + reporter_shutdown_closure + session_lifetime | 229 passed, exit 0 |
| t5-85-restore | new file | 74 passed, exit 0 |
| t5-85-restore-surrounding | new file + entire herdr directory | Tool timeout at 120s; partial log only, NO completion/exit receipt |
| t5-85-close | new file + session_lifetime | 1 failed, 134 passed; incorrect drained expectation described above |
| t5-85-close-corrected | same | 135 passed, exit 0 |
| t5-85-format | Black new file | exit 0 |
| t5-85-surrounding | full arguments below | 1754 passed, 165 warnings, 332.86s, exit 0 |
| t5-85-static | mypy --follow-imports=silent new file | 5 nullable-task errors; fixed with explicit assertions |
| t5-85-static-final | same | no issues, exit 0 |
| t5-85-black-final | Black --check new file | exit 0 |
| t5-85-final-focus | new file + session_lifetime, after static assertions | 135 passed, 4 warnings, exit 0 |
| t5-85-diff | git diff --check | silent exit 0 |
| t5-85-coreutils / coreutils-final | dpkg -V coreutils after suites | silent exit 0 |

Surrounding arguments:
```
tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_queued_prompt_block.py tests/tui/test_openrouter_startup.py
```

Final focused gate follows the added static narrowing assertions; the broad surrounding receipt precedes only those assertions/removal of an unused import. Own-file mypy uses silent imported-module following and is not a full static gate. Historical 299 errors/63 files remains UNWAIVED, not freshly compared. Full make/integration gates remain for parent integration. No skips/xfails/ignores added.

## Read accounting

Read 82/83/84 reports, root research, routing record, scope plan (combined output truncated; no full fresh-ingestion claim), actual reporter activation/close/accounting, session assembly/close, isolation fixtures and existing composed/low-level tests. Consulted KB entry/gotchas (no slo/index.md; README not freshly completed). Loaded engineering routing/testing/ownership, Python root, shared coding/cadence, Python declarative, application-service, Faux and workflow SKILL; Textual read partial. Supplied AGENTS/CLAUDE/docs research context is not claimed as fresh full actual-file ingestion. These explicit read gaps prevent canonical readiness certification.
