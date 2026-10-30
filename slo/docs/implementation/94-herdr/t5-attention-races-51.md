# T5 attention races 51 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 51, retries 0. Unlimited turns/dispatches; no agents dispatched. An upstream model API error interrupted reading; continuation recovered without restarting repository work or resetting counts.

## Delivered bounded work

- `sessions/service.py::_startup_reporting_scope`: one-line identity guard prevents a delayed preparation failure from replacing attention established after startup began. Config identity alone was insufficient. Original exception translation and startup status remain unchanged.
- `test_attention_preparation_races.py`: six Event-barrier cases exercise actual startup/catalog boundary/reporter projection, success/failure/cancellation against newer authentication and newer same-reason preparation tokens. Working persists until settlement and the exact newer token survives. Failure reproduced as token 3 replacing token 2 before the fix; success/cancellation passed initially.
- `test_attention_auth_composed.py`: three config-backed factory/Faux/graph/echo-tool submissions exercise matching auth completion, stale completion after newer preparation attention, and cancelled auth (no clear). All initially passed; no causal production fix claimed for these. One operation remains working, tool and run complete, shared usage reaches 10, and the expected idle/blocked snapshot settles. This is session callback-boundary composition, NOT a mounted authentication-modal test or actual OAuth cancellation.

The auth composition scripts the factory before session construction and resolves only a synthetic credential. No provider or Herdr process/window runs. Root per-test isolation and independent fake-Herdr/terminal guards remain intact. No agent.py, parallel usage tests, shared status, specifications, KB/global/live state, or other worktree changes were made by this continuation. Existing partial changes were preserved.

## Actual receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All pytest commands used `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` with approved existing slo-harness fallback; no venv created. Prefix `t5-attention-races-51-`, logs and matching exit files in this directory:

| Receipt | Actual result |
|---|---|
| red | 1 failed, 64 passed; exit 1. Genuine newer-attention overwrite on startup failure. |
| green | 158 passed; exit 0. Race + session_attention + publication_isolation, including automatic DAO/projection partition. |
| surrounding | 1783 passed; exit 0. Six race cases plus surrounding list below. |
| auth | 143 passed; exit 0. Auth + race + session_attention; initial passing coverage, not RED. |
| final | 1786 passed, 125 warnings; exit 0. Fresh post-format surrounding list below. |
| black-check | three touched Python files pass; exit 0. |
| diff-check / coreutils | both silent; exit 0. |
| typing | 9 errors in 6 imported dependency files, checked 3 source files; exit 1. No diagnostic names either new test or sessions/service.py. NOT a green static gate. |

Surrounding arguments: `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py tests/agents/slo_agent/test_agent.py tests/auth`.

Typing command: `poetry run mypy src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_attention_preparation_races.py tests/agents/slo_agent/herdr/test_attention_auth_composed.py`. No ignores added. Full make lint baseline 299/63 remains unwaived and was not rerun/comparison-certified here. The final surrounding partition excludes the parallel owner's new `test_agent_usage_commit_regressions.py`; it cannot establish whole-package integration green.

## Finite audit / remaining work

| Family | Status |
|---|---|
| Persisted manual failure/cancel/busy | Prior 50 proof retained; surrounding passed. |
| Newer startup attention on late success/failure/cancel | Six new composed barrier cases pass; overwrite defect corrected. |
| Matching/stale/cancelled auth callback during real run/tool | Three new passing config-backed Faux cases; mounted modal identity/cancellation remains outside this proof. |
| Real pool fallback / route numeric projection / forbidden I/O and reporter faults | OPEN; no new composed proof. |
| Retry/recovery/passive cooldown/abort/submission cancellation continuity | OPEN; no new composed matrix. |
| Final usage-before-settled across every remaining terminal branch | OPEN; existing run/manual evidence is not complete family proof. |
| Parallel partial/eventless usage integration | Not owned or accepted here. |
| Full non-E2E/smoke/static acceptance | Not run; requires lane integration and family closure. |

## Read closure (not complete)

Read supplied project AGENTS/CLAUDE/docs RESEARCH context, actual root RESEARCH, Makefile/.python-version/pyproject; 49/50 reports, routing/scope-plan (combined initial output truncated, so no full ingestion claim), relevant session startup/selection/run/auth owners and attention/manual tests, root conftest guards. Consulted KB Welcome/slo README/gotchas. Read engineering routing/ownership/testing, coding rules/cadence/declarative, Python root/declarative/service/DAO/Faux recipe (recovered truncated first 1045 lines separately), and workflow definition plus workflow SKILL.

Read canonical C7.10 and section 8 directly; C7.11 only first portion. Still OPEN: full affected C7.9/7.11, exact B state/reason surrounding contract, exact T5 attachments and accepted reviews, complete actual documentation/routing read closure. No blanket normative acceptance claimed.

No READY attention-family or independent review verdict. The one-line fix and nine cases are bounded progress, not completion of the requested cohesive family.
