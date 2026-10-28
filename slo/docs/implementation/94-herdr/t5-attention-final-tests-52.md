# T5 attention execution tests 52 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 52, retries 0. Unlimited turns/dispatches; no agents dispatched. No independent review or workflow completion claimed.

## Exclusive changes

Added only `tests/agents/slo_agent/herdr/test_attention_execution_composed.py` and this report/`t5-attention-final-tests-52-*` receipts. No production edits, prior-test edits, shared status, specifications, KB, global/live state, git lifecycle actions or other worktree edits. Parallel usage changes are preserved and not accepted by this report.

19 new parametrized cases exercise actual config-backed lazy factory → graph → Faux → local echo → session finalizer paths:

- Nine tool-barrier cases: completion/abort/task cancellation × no attention/authentication/newer preparation attention. Busy second submission refuses without allocating another operation. Final shared usage is refreshed while working; both the last working publication and settlement contain 8 completed tokens, or 3 before interrupted tool completion. Existing task cancellation translates to run_aborted. Matching attention identity survives; stale clear cannot clear newer preparation attention.
- Two pool cases: real `LLMFactory.create_pool`, real tool binding and ModelPool selection/switch. Only member `create` is replaced before session construction. Primary 429 triggers actual classifier/cooldown fallback; secondary executes echo and final response. Configured primary/pool remain unchanged. Compact publication contains cumulative 8; detail projector over actual routed usage contains latest 5 and current RPM, with unavailable context and arbitrary labels omitted. This is not activated detail-profile wiring proof.
- Six pre-output failure cases: retry/recovery/fatal × reporter normal/throwing. Actual session/agent retry and recovery policies run, not private helper simulations. Retry and recovery finish the local tool flow; fatal preserves the original exception object. Every streamed event and all pre-settlement publications remain working; exactly one operation retires. Reporter exceptions do not change execution.
- Two retry-event barriers: actual rate-limit failure establishes cooldown, then abort/cancel yields run_aborted without tool execution or invented attention. A subsequent usage refresh remains idle, never blocked.

Factory and synthetic CredentialResolver patches precede construction. No real provider, Herdr activation/process, terminal window, filesystem fixture write, system symlink or command stub is introduced. Existing pre-import/per-test isolation, independent fake-only Herdr spawn guard and terminal guard remain active. Events use bounded waits and tasks are joined in finally.

## Finite attention evidence map

| Obligation | Evidence / remaining boundary |
|---|---|
| Pure state/reason, precedence, suspension, stale end/clear, closing | Existing `test_session_attention.py` / DAO/projection tests; surrounding green. Actual approval wait is not introduced. |
| Accepted run before preparation, busy refusal, one operation | Existing scope tests plus new real tool-barrier cases. |
| Tool text is not approval/auth | Actual echo text `Approval required`; no inferred attention in new no-attention paths. |
| Startup preparation newer-token success/failure/cancel | Prior `test_attention_preparation_races.py`, six Event cases retained and rerun. |
| Auth matching/stale/cancelled completion during run | Prior three `test_attention_auth_composed.py` cases retained and rerun. Callback-level, not mounted-modal evidence. |
| Manual persisted failure/cancel/busy and final refresh | Prior `test_attention_compaction_composed.py` retained and rerun. Not successful rewrite/rollback proof. |
| Real pool route/fallback and configured identity | Two new actual pool cases; route-aware numeric detail projection explicitly separate from compact reporter handoff. |
| Pre-output retry/recovery continuous working | Six new model-boundary failure cases, real policies and local tool completion. |
| Abort/cancel during tool and retry | Nine tool-barrier plus two retry-barrier cases. Existing translated run_aborted semantics preserved. |
| Passive cooldown is not human attention | New retry interruption plus idle refresh; no invented attention. No real Herdr wait/notification command proof. |
| Final usage before settlement | Exact last working/settled totals for completion/tool abort/cancel; retry/recovery final cumulative total asserted. Fatal-before-output final usage ordering is not separately instrumented. |
| Reporter faults | New retry/recovery/fatal composition; prior broad successful tool matrix. |
| Forbidden I/O during actual route observation | Existing helper isolation tests only; new pool proof does not install boundary-specific forbidden-I/O spies. OPEN. |
| Fresh submission clears prior terminal error, preserves auth; escaped cancellation before agent | Existing unit scope proof; complete composed follow-up/early-cancellation matrix remains OPEN. |
| Mounted modal/session identity and full T5 lifetime | Outside this exclusive test file; not claimed complete. |
| Parallel usage accounting, full make/static integration | Not accepted here. Full make gates deferred as requested; baseline 299/63 unwaived. |

Therefore no bounded whole-attention-family READY claim. The remaining items above are not waived or replaced by passing counts.

## Executed receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. All pytest uses `bash docs/implementation/94-herdr/t1-dao-check.sh <arguments>` (safe fallback; automatically includes DAO/projection tests). No environment created.

All files have prefix `docs/implementation/94-herdr/t5-attention-final-tests-52-`; matching `.exit` files hold actual exit status.

| Receipt | Result |
|---|---|
| terminal | 68 passed, exit 0; first three terminal cases + auth surrounding |
| pool | 2 failed, 74 passed, exit 1; test incorrectly requested detail key `turn` from compact snapshot (KeyError), not production RED |
| pool-corrected | 76 passed, exit 0; compact assertion and separate real-usage detail projection corrected |
| retry | 86 passed, exit 0; all then-new cases + session rate limits |
| cooldown | 147 passed, exit 0; new retry barriers + session attention |
| stale | 90 passed, exit 0; expanded nine terminal cases + auth/preparation races |
| surrounding | 1814 passed, 157 warnings, exit 0, 134.15s |
| final | 93 passed, 40 warnings, exit 0, 40.92s; final test bytes plus auth/preparation/manual composition |
| black | own new file passes, exit 0 |
| diff / coreutils | `git diff --check` and `dpkg -V coreutils` both silent, exit 0 |
| mypy-initial | 21 errors / 7 files, including 12 own variadic forwarding errors; corrected with explicit model stream signatures |
| mypy | 9 errors / 6 imported dependency files, exit 1; zero diagnostics in own test. NOT a green global/static gate; no ignores added |

Surrounding arguments: `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py tests/agents/slo_agent/test_agent.py tests/agents/providers/test_pool_fallback_integration.py tests/auth`.

Final arguments: `tests/agents/slo_agent/herdr/test_attention_execution_composed.py tests/agents/slo_agent/herdr/test_attention_auth_composed.py tests/agents/slo_agent/herdr/test_attention_preparation_races.py tests/agents/slo_agent/herdr/test_attention_compaction_composed.py`.

Scoped typing: `poetry run mypy tests/agents/slo_agent/herdr/test_attention_execution_composed.py`. Retained imported failures: yaml stubs, transcript_projector optional tool_name, Faux constructor/bind signature, assistant_chunk_normalizer ToolCall type, Anthropic kwargs, Codex constructor/API key types. Full 299/63 baseline was not rerun or comparison-certified. Surrounding excludes parallel `test_agent_usage_commit_regressions.py`, so it is not whole-package integration evidence.

## Read closure and limits

Read 50/51 reports; full frozen routing/scope-plan; root RESEARCH, actual Makefile/.python-version/pyproject; supplied AGENTS/CLAUDE/docs RESEARCH; KB Welcome/slo README/gotchas. Read engineering routing/testing/ownership, coding rules/cadence/shared declarative, Python root/declarative/named arguments/docstrings/Faux testing/application-service recipes, workflow SKILL and exact Code-Test-Review. Truncated combined engineering/coding beginning was recovered from spill. Read actual session operation/attention/event/rate/recovery owners, Faux, factory/pool streaming/binding, adjacent pool/attention/auth/manual/usage tests and root safety guards.

Canonical read-only C7.10, C7.11 and section 8 read fully; C7.9 read in two large ranges with truncated leading remainder recovered through 1035 (the output retained subsequent lines). Read C7.1 state/operation rules; B typed state/reason and batch ordering; exact T5 task and first allocated samples; accepted independent turn-4 review. Full remaining T5 attachment and full routed build/domain/documentation read closure are NOT established. No blanket required-read completion claimed. No specification example probes executed or counted as product tests.

No production RED established by these new tests. No arbitrary test-count/dispatch cap imposed. Remaining matrix and normative read gaps prevent the requested family completion; future continuation should close those exact gaps without editing the parallel usage owner or weakening expectations.
