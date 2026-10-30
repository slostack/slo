# T5 finite SESSION attention boundary — READY

READY applies only to the finite session attention evidence family requested in dispatch 53. It is not T5 app completion, whole-feature acceptance, independent review, a full-suite/static pass, or live Herdr certification.

Accounting unchanged: unfinished turn 1; started 1, completed 0, historical partial 1; supplied dispatch 53; retries 0; unlimited turns and dispatches. No agents dispatched. No artificial unit-count cap.

## Exclusive changes and safety

Modified only `tests/agents/slo_agent/herdr/test_attention_execution_composed.py`, added `tests/agents/slo_agent/herdr/test_attention_boundary_closure.py`, and wrote this receipt plus `t5-attention-53-*` receipts. No production, shared status, specification, KB/global/live state, other-worktree or git lifecycle changes. Parallel usage ownership remains untouched and unaccepted by this verdict.

Factory patches precede config-backed session construction; actual lazy graph/Faux/local echo and ModelPool remain exercised. Early cancellation proves factory never called. No provider or Herdr activation/window was introduced. Existing pre-import/per-test HERDR stripping, disable flag, independent identity/containment-bound fake executable guard and real-terminal guard remain active. New tests create no filesystem fixtures, symlinks or command stubs. Event waits are bounded; owned tasks are gathered in finally. Surrounding adapter tests retain their existing temp-only regular-file capabilities.

## Closed finite ledger

All paths below ran in the final surrounding receipt. Paths are relative to `tests/agents/slo_agent/herdr/` unless stated otherwise.

| C obligation | Evidence and boundary |
|---|---|
| C7.10 state/reason vocabulary, precedence, suspension, stale clear/end, other active owner, closing | `test_session_attention.py::test_attention_tokens_and_operation_precedence`, `test_attention_publication_and_closing`; DAO/projection cases. Suspension is a pure contract; no approval-wait product feature is invented. |
| Accepted submission before preparation; busy rejection allocates no second operation | Existing actual scope/readiness tests and nine `test_tool_barrier_terminal_usage_and_busy_refusal` cases. |
| Actual route observer has no path resolution, credential resolution, metadata load, model construction or usage commit | Strengthened `test_config_pool_route_preserves_working_and_numeric_projection[False,True]`: observer installed before session construction; actual subscriber delegates to original observer under forbidden-call spies. Counts asserted AFTER dispatch, so exception isolation cannot swallow test failures. Actual observer transition is exactly gpt-5.4→gpt-4.1 on fallback, none otherwise. Real pool/classifier/tool execution remains intact. |
| Configured policy unchanged by routed display; numeric metadata and omitted labels | Same actual pool cases retain configured primary/pool and exact total 8; detail projection over real usage asserts latest 5/RPM/context omission. Detail projection is not activated detail-profile transport wiring. |
| Tools/retry/recovery stay working; no approval inference | Existing 19 execution cases retained, plus prior `test_real_faux_tool_submission_keeps_working_and_commits_totals` matrix. Tool text literally contains Approval required without creating attention. |
| Final fatal usage refresh before retirement and blocked settlement; reporter faults cannot replace error | Strengthened `test_provider_failure_continuity[False-fatal,True-fatal]`: original exception identity, one attempt/no tool, exact final order `refresh, working, refreshed, end, blocked`, one retirement, equal last-working/settled tokens. Unknown usage remains None and session_tokens is omitted. Retry/recovery variants still complete actual tools. |
| Next accepted submission clears terminal failure only; preserves auth | New `test_next_submission_attention_at_real_preparation` (2 cases): first public invoke fails at preparation; second public invoke executes original preparation and real Faux/tool flow. Serial is 2, prior generic failure is cleared before preparation; auth token identity survives both failures/success. Final total 8. This is fresh submission, not the agent's queued followUp API. |
| Early escaping cancellation before agent, with/without auth | New `test_early_cancellation_escapes_after_settlement` (2 cases): public invoke paused at accepted preparation; task cancel sentinel escapes, no lazy factory call, exact prior attention retained, one token retired, running/lock clear, working publications then idle/auth-blocked. No change to later translated run_aborted semantics. |
| Abort/cancel during actual tool/retry; passive cooldown not attention | Nine tool barriers and two actual retry-event barriers in execution file; idle refresh never becomes blocked from cooldown alone. |
| Startup preparation matching/newer token success/failure/cancel | `test_attention_preparation_races.py` six deterministic catalog barriers plus startup unit cases. |
| Auth matching/stale/cancelled completion during actual run | `test_attention_auth_composed.py` three tool-boundary cases; original lazy credential error identity covered by `test_auth_requirement_preserves_original_lazy_error`. Session-level completion-token evidence, not mounted modal proof. |
| Manual compaction working/final refresh/failure/cancel/busy | `test_attention_compaction_composed.py` real persisted history/audit preservation and `test_session_attention.py` manual status/fault matrix. Existing `tests/agents/slo_agent/test_session_manual_compaction.py` also rerun. No new rewrite/rollback claim. |
| Usage accounting/projection remains sole-owner | Existing usage/token tests and full surrounding partition rerun. No new counter or production usage edit; parallel usage regression file not included or certified. |

The three OPEN session boundaries in report 52 are closed. No additional matrix is required to close this finite family.

## Explicit caller boundary, not a session blocker

Canonical authority is read-only `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/94.b.2-session-publication-and-native-restore.md`:

- C7.1 requires `SloTUI._push_auth_modal` / `_on_auth_dismissed` to retain captured `(session, token)` and check selected identity; C7.10 says cancelled auth retains its token if the existing credential check still fails.
- C7.9 names mounted `test_new_delivery[late_auth,...]`, replacement/subscription/inbox ownership and exact final prompt-registration cutoffs. C7.11 and section 8 require activation/cleanup and mounted lifetime evidence separately.
- Exact T5 attachments C22/C23 carry session attention/lifetime; C13–C21/C24–C26/C30 carry app and coupled lifetime contracts. Accepted `review-evidence/independent-review-turn4.md` approves specification breakdown, not implementation.

Those not-yet-wired mounted caller paths remain future T5 app work, not waived and not imported as an impossible prerequisite into this session-only assignment. Full make/integration/static gates belong to the other integration owner; baseline 299/63 remains unwaived. No remote wait/notification, mounted modal, full T5 lifetime, two-process restore, or live compatibility claim is made.

## Executed commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7. No venv created. Every pytest command used approved `bash docs/implementation/94-herdr/t1-dao-check.sh`, which supplies safe fallback environment and adds DAO/projection tests. All following receipt stems are under this directory with prefix `t5-attention-53-`; `.log` is full output and `.exit` is actual exit status.

| Stem | Result |
|---|---|
| route | 64 passed, 17 deselected, exit 0 |
| followup | 83 passed, exit 0 |
| cancel | 66 passed, exit 0 |
| final | 2 failed, 83 passed, exit 1: test-author mistake described below |
| final-corrected | 85 passed, 38 warnings, exit 0 |
| surrounding | 1818 passed, 161 warnings, exit 0 |
| route-final | 64 passed, 17 deselected, exit 0; exact observed transition assertion added |
| surrounding-final | **1818 passed, 161 warnings, exit 0, 132.58s**, final Python bytes |
| black-final | both owned Python files pass, exit 0 |
| mypy-final | 9 imported errors in 6 files, exit 1; **zero diagnostics in either owned test file** |
| diff | git diff --check silent, exit 0 |
| coreutils-final | dpkg -V coreutils silent, exit 0 |

Initial fatal instrumentation erroneously asserted unknown total equals 0. Actual failure was `AssertionError: assert None == 0` in both reporter-fault variants; preceding exact ordering/identity assertions passed. B7.6 explicitly requires unknown values omitted, so corrected to `is None` AND absence of session_tokens. This is correcting a contradictory test oracle, not weakening the contract or fixing production. Full failing output retained. No production RED established.

Commands (arguments after helper):

- route / route-final: `tests/agents/slo_agent/herdr/test_attention_execution_composed.py -k 'pool or daos or projection'` (17 deselections intentional focused selection).
- followup / final / final-corrected: `tests/agents/slo_agent/herdr/test_attention_execution_composed.py tests/agents/slo_agent/herdr/test_attention_boundary_closure.py`.
- cancel: `tests/agents/slo_agent/herdr/test_attention_boundary_closure.py`.
- surrounding / surrounding-final: `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py tests/agents/slo_agent/test_agent.py tests/agents/providers/test_pool_fallback_integration.py tests/auth`.
- Static: `poetry run black --check tests/agents/slo_agent/herdr/test_attention_execution_composed.py tests/agents/slo_agent/herdr/test_attention_boundary_closure.py`; same paths with `poetry run mypy`.
- Hygiene: `git diff --check`; `dpkg -V coreutils`.

Mypy failures: yaml stubs; transcript_projector optional tool_name; Faux constructor/bind signatures; assistant_chunk_normalizer ToolCall; Anthropic kwargs; Codex constructor/API-key types. No ignores or dependency edits. This is NOT a clean global/static gate; full baseline comparison was not rerun.

## Affected required-read closure

Read frozen routing.md and scope-plan.md completely, report 52, root RESEARCH, supplied complete docs/RESEARCH and actual AGENTS/CLAUDE, Makefile/.python-version/pyproject and helper. Consulted KB Welcome, slo README and gotchas read-only. Loaded committed engineering routing/testing/ownership, coding rules/cadence/shared declarative/test-verification policy, Python root/declarative/named-arguments/docstrings/Faux testing/application structure/build-domain/build-application/environment recipes, exact workflow SKILL and Code-Test-Review. Generic SQL/web deployment examples do not add infrastructure to this offline session test assignment.

Canonical C7.1, complete C7.9–7.11 and section 8 read; complete T5 attachment tasks.md 2401–3720 read in bounded ranges; B typed state/reason and numeric unknown/omission contract read; accepted independent turn-4 review read completely. Truncated leading ranges recovered from actual tool spill files, not assumed read. This closes report 52's remaining T5 attachment/build/domain read gaps for this affected session scope; it does not claim a new independent full-spec review.

Inspected actual session invoke/scope/operation/attention/publication/observer owners and existing attention/auth/preparation/manual tests, plus root safety fixtures. Reviewed owned final test changes: original production methods still delegate; forbidden-call assertions survive subscriber isolation; final ordering is checked outside isolated reporters; no assertions removed, no sleeps/skips added. Full app/CLI/Textual implementation recipes and independent review phases remain outside this test-only write scope, as do their future implementation obligations.
