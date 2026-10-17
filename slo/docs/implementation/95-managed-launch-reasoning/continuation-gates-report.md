# Feature 95 — Call 7 verification gates

**REVISE — behavioral tests pass; required static gates remain nonzero and unwaived.**

2026-10-18. TURN1 CALL7/20; previous6, remaining13; started/completed/partial1/0/1, retries0, aborts0. Unlimited legitimate revision turns; no nested agents. This is verification-scope Code+Test only, not original-feature completion or independent review.

## Authority and scope

Used retained `routing-and-plan.md`, `continuation-e2e-report.md`, accounting, current code/tests and operator authorization. Missing original specifications were not accessed, searched for, recreated or demanded. Original-source preservation and original-spec compliance remain **unverifiable**. P4 docs/skill/guidance work remains **OUTSTANDING**, explicitly outside this continuation's implementation scope. Existing skill health was tested, not substituted for P4 completion.

Verified application cwd `/root/Code/slo-managed-launch-reasoning-20261017/slo`, branch `feature-95-managed-launch-reasoning-20261017`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. Reused retained Python/Pydantic/LangChain/Typer/pytest routing and project-specific fixture conventions; read governing workflow, cadence, generic coding rules, Python root, testing recipe, Makefile and safety/state helpers. No production modification: no behavioral bug was demonstrated.

## Small refinement and behavioral evidence

Ran all 21 composed cases before refinement, then strengthened `run_recorded_child` with an optional expected-active-reasoning assertion against the retained real `HeadlessRunner._session`. The missing-Kimi negative case now explicitly expects **off**, in addition to its exact credential failure, started/failed notifications, no child factory call and no durable attempt start. Real constructor/readiness remain intact. All 21 cases passed afterward; this was characterization strengthening, not a manufactured failing product test.

Existing composition covers real lazy owner/bootstrap/tool → recorded argv → serial real child CLI/session → controlled factory, canonical overrides/defaults/clamps, malformed input cutoff, distinct unknown-model/credential/OpenRouter admission failures, phase independence, registered lifecycle/status/inbox reconciliation, supported injected abort, capture endpoint cleanup. Surrounding tests cover schema/provider projection, immutable snapshot/replacement, resume and lifecycle races. Captures remain endpoint-lifecycle evidence rather than native workload stdout proof. No successful dynamically discovered OpenRouter child or live provider-effective reasoning claim.

## Exact receipts

All names below have prefix `continuation-gates-` and suffixes `.command`, `.log`, `.exit` beside this report. Commands were run using unchanged approved `run-gate.sh`, with scoped VIRTUAL_ENV/PATH `/root/.pyenv/versions/slo-harness` (3.11.7), test fallback/PYTHONPATH; no install/global environment change. Complete output is retained, including failures. Logs are locally retained but Git-ignored.

| Receipt | Command/scope | Actual result | Exit |
|---|---|---|---:|
| 01-composed-before | pytest composed module | 21 passed, 46 warnings, 9.79s | 0 |
| 02-lint | `make lint` (src AND tests) | 297 errors in 62 files, 683 checked | 2 |
| 03-black | Exact plan bounded Black scope | 1 would reformat, 41 unchanged | 1 |
| 04-composed-after | pytest composed module after active-off assertion | 21 passed, 46 warnings, 9.79s | 0 |
| 05-focused | Exact ten-file plan focused partition | 367 passed, 59 warnings, 18.29s | 0 |
| 06-full | `make test`, full non-E2E | **6347 passed, 19 deselected, 452 warnings, 502.70s** | 0 |
| 07-coreutils | `dpkg -V coreutils` | empty output | 0 |
| 08-skills | Four prescribed committed/refresh/limit/turn skill modules | 31 passed, 2 warnings, 1.99s | 0 |
| 09-index | Two `make refresh-skills`, compare initial/first/second SHA | 186 skills, all three hashes identical | 0 |
| 10-black-final | Exact plan bounded Black, after refinement | 1 would reformat, 41 unchanged | 1 |
| 11-baseline | First archive attempt | INVALID baseline evidence: incorrect archive-relative path, cd failed, command reran current checks | 2 |
| 12-baseline-corrected | Fail-fast archive/extract inside app root; base `make lint` and bounded Black | 301 errors in 64 files / 682 checked; Black 1 would reformat / 40 unchanged; inner exits 2 and 1 | 2 |
| 13-lint-final | Final current `make lint` | 297 errors in 62 files / 683 checked | 2 |
| 14-comparison | Exact diagnostic multiset comparison, seven policy hashes, Black-file base-byte check | no introduced diagnostics; four removed; all seven match | 0 |
| 15-diff | diff check, base inventory, status | whitespace check empty; inventory retained | 0 |
| 16-coreutils | integrity | empty | 0 |
| 17-cleanup | Remove only two owned baseline extraction directories | removed contained disposable extracts | 0 |
| 18-affected | Full orchestrator folder + CLI/headless/reasoning/executors | **892 passed, 62 warnings, 51.76s** | 0 |
| 19-integrity | integrity after final affected suite | empty | 0 |

No tests disabled or skipped to pass. Full-suite exclusions are the existing `-m "not e2e"` selection: 19 deselected, no skipped tests reported. Warning totals are not zero: dependency deprecations, SDK option warnings and AsyncMock coroutine warnings remain in logs; focused/affected teardown emits additional coroutine warning text outside the summary. No waiver is implied. Full test ran after the only code/test edit; subsequent index regeneration was byte-identical and remaining edits are evidence documents only.

Index SHA-256 before/after both refreshes: `d66e7a6403b5d4e5f80637467c82e0197634cbfe6db8ef52aa87230891694d8d`.

## Precise baseline classification and acceptance conflict

The first archive attempt used `slo/src` from an app-relative Git invocation; extraction/cd failed. Receipt 11 is preserved and explicitly rejected as baseline proof. Corrected receipt 12 used `set -euo pipefail` for extraction/cd, `git archive BASE src tests config pyproject.toml poetry.toml Makefile`, and ran static tools inside an owned `.f95-baseline-*` extraction, with local PYTHONPATH. No other worktree or source file was changed. Extracts were removed after evidence comparison.

Every one of the **297 current error diagnostics**, including path, line, message and multiplicity, appears identically at base. No introduced diagnostic. Four baseline diagnostics no longer occur: `test_relaunch.py:249` Task[Endpoint] vs Task[IO[bytes]], and `test_workflow_routing_e2e.py:174,187,188` nullable-config attribute access. These improvements were already in prior continuation work, not this call. Baseline includes missing YAML stubs, existing provider typing, CLI override typing and test protocol/assignment errors; all exact diagnostics are in receipts 12/13, not silently waived.

Black's sole failure is `tests/agents/slo_agent/orchestrator/test_spawn_tool.py`, byte-identical to base and reproduced there. All directly touched files pass bounded Black. This unrelated file was not reformatted. Baseline reproduction explains provenance; **it does not satisfy the required green static gates**. Acceptance remains blocked until separately authorized baseline remediation or an explicit operator gate-policy decision. Do not fix hundreds of unrelated errors under Feature95 or treat this report as a waiver.

## Changed-file inventory

Existing feature changes preserved (application-relative):
- Production: `src/agents/slo_agent/orchestrator/bootstrap.py`, `launch_tool.py`; documentation-only `src/cli/typer_dispatch.py`.
- Tests: `tests/agents/slo_agent/orchestrator/test_bootstrap.py`, `test_launch_tool.py`, `test_process.py`, `test_relaunch.py`, `test_workflow_routing_e2e.py`; `tests/cli/test_typer_dispatch.py`.
- New existing composed test: `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`.

This call changes only the composed helper/assertion, this report, accounting, E2E-report addendum and fresh `continuation-gates-*` receipts. No authored skill, index bytes, policy, production, shared fixture, README, AGENTS or research change. The seven protected repository-policy hashes match the retained plan. Missing-source hashes were not checked. Production diff inspection confirms existing reasoning transport/default binding and dispatcher-docstring scope; this is implementer verification, not independent review.

## Safety and next gate

Read `capture_test_safety.py`, state isolation and conftest before suites. Tests use isolated state, synthetic credentials, injected workload transport/signals/terminal spawn and finite contained helper subprocesses; no native workflow/provider workload or paid call was initiated. Coreutils verification remained empty. No commit/push/PR/publish, install, global configuration, external KB write or other-worktree mutation.

**REVISE:** required static gates conflict with reproduced preexisting baseline failures and remain unwaived. Behavioral verification is green; P4 remains outstanding by authorization. After resolving gate acceptance, genuine independent high-reasoning review and fresh completion assessment are still required, in order. No full-original-feature claim.
