# Usage integration continuation 53 — INCOMPLETE gate status

The four Feature89 expectation failures are resolved with independent evidence. Usage behavior and its focused finite family are green. Overall READY is withheld: the required static baseline remains unwaived, and the single complete-suite run predates a type-safe assertion rewrite and concurrent attention-test edits. No independent review or full Feature94 acceptance is claimed.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 53, retries 0. Effective user budgets are unlimited turns and dispatches. No agents dispatched; no counter reset.

## Scope and causal conclusion

Only `tests/integration/test_feature89_model_flows.py` was edited, plus this report and `t5-usage-integration-53-*` receipts. No production changes were needed. Existing agent/session usage implementation, attention lane, policy/tool/reasoning/privacy assertions, shared status, specs, globals and other worktrees were not edited. No commit/push/PR/reset/clean/stash, live Herdr or provider calls.

Confirmed the actual failing path from continuation 52 and its focused log. The fixture has two successful HTTP streams after the initial lane's 429 refusal(s): tool response, then final answer. Independent delivered-response ledger now proves exactly two HTTP 200 responses, with the original exact request-order assertion retained. Direct API-key SDK retries remain four 429 attempts; OAuth/gateway refusals remain one. No retry behavior was changed.

Source evidence:

- `tests/agents/providers/feature89_responses.py::response_envelope`, `tool_frames`, `answer_frames`: direct Responses completed envelopes have distinct `resp_89_tool` / `resp_89_answer` IDs, each with input=10, output=4, total=14 and zero cached/reasoning details. Created frames also contain synthetic usage; tests explicitly select only `response.completed`, so created/partial frames are not billed as additional completions.
- `tests/integration/test_feature89_model_flows.py::jev_frames`: distinct `chat_89_tool` / `chat_89_answer` IDs, exactly one choices-empty usage frame per successful response, each 10/4/14.
- A test-local autospecced observer wraps, rather than replaces, `SloAgent._capture_completed_update_usage`. It records exactly two completed SDK AI messages: one tool-bearing, then one without tools; each normalized usage is 10/4/14. The original accounting method executes unchanged. Exactly one echo remains required; run completion at zero-based iteration 1 proves the two-iteration flow, with no retry/recovery/failure events.
- `agent.py::_consume_update_chunk` captures authoritative completed node deltas; `_capture_completed_update_usage` adds each to the fixed-size pending handoff. `consume_completed_usage` transfers and clears it. `sessions/service.py::_sync_usage_snapshot_commit` adds that drain to the sole cumulative session owner. A repeated refresh assertion proves no second charge.

The strengthened RED run retained the original total and passed all preceding response/count/metadata assertions in all four parameter combinations. It failed only with `(20, 8, 28) != (10, 4, 14)` at then-line 464. Therefore the precise expected cumulative total changed to **20/8/28**, not a relaxed bound. All existing later wire, auth, tool, reasoning, private continuation and public/artifact privacy assertions remain intact. There is no production duplicate-accounting fix to make.

## Routing and read context

Used supplied AGENTS/CLAUDE/docs RESEARCH, actual root RESEARCH, Makefile/helper, state isolation/terminal/fake-spawn guard context, routing.md and scope-plan.md. Selected committed shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative/named-arguments/docstrings/Faux recipe and workflow SKILL. This is Python pytest adapter/composed offline verification using the actual SDK over local MockTransport, not database integration or live-provider acceptance. No new CLI/TUI/graph architecture.

Consulted KB Welcome, slo README and gotchas read-only. Read canonical Herdr B 7.6 projection contract and C final-usage-before-operation-settled contract under `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/`. The local specifications symlink is absent in this checkout; canonical location came from scope-plan.md. No new Feature89 product-accounting requirement was necessary: existing completed fixture payloads and actual handoff settle this expectation. Large combined context reads truncated; exhaustive ingestion of every linked document is not claimed.

## Executed gates

CWD `/root/Code/slo-94-herdr-integration/slo`; subprocess `PYENV_VERSION=slo-harness`, verified existing Poetry Python **3.11.7**, no venv creation. Focused commands use `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` (adds DAO/projection tests). Existing pre-import/per-test HERDR stripping, disable flag, terminal guard and registered temp-owned regular-file fake boundary retained. No system symlinks created.

All receipts use prefix `docs/implementation/94-herdr/t5-usage-integration-53-`; test/check stages have `.log` and `.exit` unless noted:

| Stage | Command / scope | Actual result |
|---|---|---|
| red | helper + integration module `::test_prepared_mixed_pool_tool_fallback` | 4 failed, 62 passed; exit 1; only old total fails |
| green | helper + full Feature89 model-flows module + agent_usage_commit_regressions + session_usage | 162 passed, 148 warnings; exit 0 |
| surrounding | initial helper command included nonexistent `herdr/test_*usage*.py` glob | no tests ran, exit 4; retained, not evidence |
| surrounding2 | helper + `test_agent*.py`, `test_session*.py`, `herdr/test_*attention*.py`, `test_cache_control.py` | 547 passed, 192 warnings; exit 0 |
| full | **one `make test`** | **7729 passed, 19 deselected, 545 warnings**, 624.84s; exit 0 |
| smoke | `make smoke` | 288 passed, 2 warnings; exit 0 |
| lint | `make lint` | 300 errors/64 files; exit 2; one new TypedDict dynamic-key assertion error |
| final-focused | helper + Feature89 module, usage regression/session usage, attention_boundary_closure and attention_execution_composed | **185 passed, 184 warnings**; exit 0 |
| lint-final | `make lint` after literal-key rewrite | **299 errors/63 files**, checked 758 source files; exit 2 |
| black | `poetry run black --check` agent.py, sessions/service.py, usage regression test, integration test | four files unchanged; exit 0 |
| black-final | same check on final integration test | unchanged; exit 0 |
| diff-check / diff-final | `git diff --check` | silent; exit 0 |
| coreutils / coreutils-final | `dpkg -V coreutils` | silent; exit 0 |

The lint error introduced by the test instrumentation was:

```text
tests/integration/test_feature89_model_flows.py:466: error: TypedDict key must be a string literal; expected one of ("input_token_details", "input_tokens", "output_token_details", "output_tokens", "total_tokens") [literal-required]
```

It was corrected by replacing the generator over dynamic keys with the exact same three literal-key values. No expected values or branches changed. Fresh final-focused and lint gates followed. Per the requested once-only full-suite limit, `make test` was not rerun after that rewrite; the full receipt is not represented as a final-file hash match.

`lint-299-baseline.diff` is empty, exit 0: normalized diagnostic comparison against actual `t5-attention-49-lint.log` yields exactly the supplied 299/63 baseline (normalization removes source line numbers only). `baseline-lint.log` is an older 301/64 baseline: `lint-baseline.diff` separately records the two already-removed CLI override errors. Neither baseline is waived or called green. Final make output still ends:

```text
Found 299 errors in 63 files (checked 758 source files)
make: *** [Makefile:43: lint] Error 1
```

## Snapshot / concurrency qualification

`before-full.sha256` and `final.sha256` enumerate all Python source/test files; `snapshot-check.log` and `final-snapshot.diff` record drift, not a fabricated freeze. During the full/static gates the other lane changed `tests/agents/slo_agent/herdr/test_attention_boundary_closure.py` and `test_attention_execution_composed.py`. Both were included read-only in the final 185-pass focused run. Our only subsequent test change was the literal-key type correction above. Production usage files did not change across these snapshots. `change.diff` contains the final integration patch for review.

The runtime accounting blocker is closed, but strict all-gates/final-snapshot READY is **INCOMPLETE** because static baseline remains unwaived and no complete-suite receipt covers the exact final combined snapshot. No unrelated baseline remediation was attempted under this bounded authorization.
