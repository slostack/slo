# T5 publication evidence — continuation 45

**INCOMPLETE for the complete requested family.** Nine attributed test-file mypy errors are removed. Fourteen additional cases pass, and the targeted surrounding gate passes. No production RED was demonstrated. This is not workflow acceptance or full T5 readiness.

Accounting retained: turn 1 started 1, completed 0, historical partial 1, dispatch 45, retries 0; unlimited turns/dispatches. No agents dispatched. Only the two authorized test files and this receipt were edited. No production, other tests, shared status, specification, global/KB or other-worktree edits; no commit/push/PR/reset/clean/stash.

## Finite branch map and evidence limits

| Contract | Evidence added here | Result / qualification |
|---|---|---|
| Nine typing errors | compositions: explicit BaseChatModel dictionary, exact Faux stream parameters with nullable callback/stop, explicit latest-publication assertion | No diagnostics in either owned file. No Any, casts or ignores added |
| Startup superseded config cutoff | `test_stale_startup_never_publishes[success,failure,cancel]` | Actual startup blocked at catalog await, config replaced, zero adopt/publication; old capture/generation retained, cancellation object preserved |
| Caller mutation → actual saved bytes | `test_caller_pool_mutation_preserves_actual_saved_bytes` | Real session capture, bounded thread save barrier, list reorder/removal and entry scalar edits; actual store reload equals complete original config, bytes unchanged after withdrawal. Direct store scheduling, not reporter scheduling; existing G1 reporter composition retained |
| Full successful invoke under synchronous publication faults | `test_full_faux_invoke_survives_publication_fault[projection,reporter,diagnostic]` | Config-backed factory-patched Faux execution, original answer, exactly one durable completed event, no failed/aborted event; native capture exists. Null reporter's publication boundary is fault-injected; not transport-failure evidence |
| Original run error and external cancellation | `test_full_invoke_terminal_isolation[False,True]` | Public session invoke and actual persistence/finalizers; injected run-stream boundary, exact ValueError object preserved; externally cancelled stream retains existing cancellation-to-run_aborted semantics, exactly one terminal history event. **Not a provider-error test and not a concurrent real-save cancellation composition** |
| Metadata refresh/reset | `test_metadata_refresh_withdraws_then_recovers[missing,unreadable,wrong_identity]` | Resume metadata initially exists without ensured flag; bad refresh withdraws, later real read restores equal capture |
| Standard headless origin | `test_standard_origin_interactive_gate[False,True]` | Actual standard bootstrap with mocked pool construction; marker exists in both, native capture only interactive |
| Existing G1/no-I/O/fallback/provenance | Existing tests unchanged except typing fixes | Rerun, not duplicated as new coverage |

Still outstanding for a whole-family READY: real provider/run failure and cancellation crossed with projection/reporter/diagnostic faults and an actually running save; explicit injected-agent standard-origin composition; full four-provider public-channel sentinel/rotation proof if included in family acceptance. No future attention or working-state contract was asserted. Parent/parallel owner retains production guard corrections; this lane changed none.

## Commands and actual output

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; `python --version` → Python 3.11.7; `make test-env` → fallback, all exit 0. No environment installation or new venv.

H = `bash docs/implementation/94-herdr/t1-dao-check.sh`; P = `tests/agents/slo_agent/herdr/test_session_publication_compositions.py`; I = `tests/agents/slo_agent/herdr/test_session_publication_isolation.py`. H includes DAO/projection tests; counts are total executed, not unique additions. Logs are tool transcript output, summarized verbatim below; no separate log files were written because the requested documentation write set is only this file.

| Command in execution order | Actual summary | Exit |
|---|---|---|
| H P after typing edits | 90 passed, 5 warnings in 3.23s | 0 |
| H I after startup cases | 65 passed, 2 warnings in 1.37s | 0 |
| H I after saved-byte case | 1 failed, 65 passed, 2 warnings in 1.52s | 1 |
| H I after correcting test activation | 66 passed, 2 warnings in 1.38s | 0 |
| H I after successful full invokes | 69 passed, 5 warnings in 1.78s | 0 |
| H I after terminal isolation | 71 passed, 5 warnings in 2.19s | 0 |
| H I after metadata/headless | 76 passed, 5 warnings in 2.13s | 0 |
| poetry run black P I | 2 files reformatted | 0 |
| H P I tests/agents/slo_agent/herdr/test_session_publication.py tests/agents/slo_agent/herdr/test_session_capture.py tests/agents/slo_agent/herdr/test_reporter.py tests/agents/slo_agent/herdr/test_reporter_compositions.py tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py | **343 passed, 16 warnings in 13.57s** | 0 |
| poetry run mypy P I | Found 12 errors in 7 files (checked 2 source files); zero in P or I | 1 |
| poetry run black --check P I | 2 files would be left unchanged | 0 |
| git diff --check | silent | 0 |
| dpkg -V coreutils | silent | 0 |

Initial saved-byte failure was a **test setup defect**, not production RED: `assert session._herdr_capture is None` failed because reporting remained inactive, which intentionally bypasses publication/withdrawal. Corrected by enabling the publication boundary before refreshing; immutable save equality had already passed. No assertion weakened. All other new cases passed initially against existing/concurrently changing production, not red-to-green production repair evidence.

Final scoped mypy diagnostics (unwaived): skills/service.py:13 missing yaml stubs; tui/transcript_projector.py:340 nullable tool_name; providers/faux.py:73 two constructor kwargs and :87 bind_tools signature; assistant_chunk_normalizer.py:332 ToolCall item type; anthropic_claude_code.py:251 kwargs; openai_codex.py:179 openai_api_base and :181 api_key; concurrently edited sessions/service.py:2202–2204 nullable config accesses. Earlier scoped run had those final three at 2178–2180. Neither scoped run diagnosed an owned test file. Historical full baseline 299/63 is not waived or declared green. No full make/test/lint integration gate ran.

## Safety, review and reading

Actual execution tests patch factory and synthetic credential resolution before session construction. No injected agent was used to claim native eligibility. Root guards strip HERDR, disable by default, isolate state and forbid real terminal/Herdr execution. Existing executable compositions retain registered actual fake capability. New save test creates only a contained private directory and uses real store files; no system symlinks. Barriers are bounded and released/joined in finally. Source changed concurrently, so these receipts are not an atomic source freeze.

Read supplied AGENTS/CLAUDE/docs RESEARCH, actual root RESEARCH, routing/scope plan, 44 evidence/mutation and lint attribution, actual session startup/capture/publication/terminal code and surrounding tests, Makefile/test fallback and isolation guards. Read engineering routing/testing/ownership, coding rules/cadence/declarative and Python root/DAO/service/declarative plus workflow SKILL. Bulk truncation of Python rules and KB entry was recovered by reading omitted prefixes. Read KB Welcome/actual slo README/gotchas. Read canonical C 7.8/7.9 capture and section 8, B privacy excerpts, all T5 sample attachment lines 2401–3720 and accepted independent turn-4 review.

Full additional routed KB pages/style companion files and complete actual on-disk AGENTS/CLAUDE/docs RESEARCH (beyond supplied context) were not re-ingested. Therefore complete prerequisite compliance is not claimed. Remaining composition and reading work above precludes READY; no arbitrary dispatch/turn stop is asserted. Independent review and completion remain pending.
