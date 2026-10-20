# Feature 95 — Call 6 behavioral E2E continuation

## Call 7 verification addendum

See [continuation-gates-report.md](continuation-gates-report.md): full non-E2E
6347 passed, affected892 passed; negative missing-Kimi now explicitly asserts the
retained real child's active reasoning is off. Required static gates remain
nonzero, precisely reproduced at base and unwaived: verification verdict REVISE.
P4 guidance remains OUTSTANDING under the operator's narrowed scope. Independent
review/completion still required. The Call 6 receipt below remains historical.

**Bounded COMPLETE: substantive offline composition implemented and executed. Not Step 1 READY or feature acceptance.**

TURN1 CALL6/20; started/completed/partial 1/0/1; retries 0; aborts 0; 14 same-turn calls remain. Unlimited legitimate revision turns. No nested agent/orchestrator. Operator authorization supersedes every historical source-restoration mandate. No absent original source was read, searched for, demanded or reconstructed. Behavioral authority is the retained routing plan/map plus current code/tests and current operator request; original-spec compliance and original-source preservation remain unverifiable.

## Scope and actual changes

Branch `feature-95-managed-launch-reasoning-20261017`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`, application cwd `/root/Code/slo-managed-launch-reasoning-20261017/slo` verified. This call changed only the existing untracked `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`, accounting and new continuation evidence/report. All prior production/test/report work retained. No production bug demonstrated or production edit made.

The module grew from 2 foundations to **21 parameterized cases (19 additional cases)**, incrementally executed between meaningful additions. These characterize existing implemented behavior; no manufactured RED or claim that fixture failures were product defects.

## Evidence map (test names in the composed module)

| Behavioral target / retained map | New executable evidence |
|---|---|
| R3 real config/lazy construction | `test_managed_typed_factory_preserves_lazy_owner`: real readiness/graph, factory untouched until invoke; typed LLMBuildResult recorder sees owner low |
| R4/R7 registered transport | `test_managed_owner_records_reserved_identity_and_capture`: real bootstrap/tool graph, handle PID 0 at spawn, recorded child ID, test PID publication, raw high argv, closed actual capture endpoints |
| R2/R6/R7 complete child | `test_managed_child_cli_completes_registered_lifecycle`: exact recorded argv[3:] to awaited serial real Typer CLI; saved low overridden by high; ordered owner/child factory identities; actual completed status PID/IDs/exit 0; started context_note/completed chat_turn; actual workflow_status reconciles completed |
| R9 independent phase | `test_managed_phase_medium_is_independent_of_high_parent`: actual child tool/pool/task/_build_argv, only SubAgentProcess.run replaced; matching task/session result; parent high vs phase medium; real fleet terminal entry and phase inbox note |
| R6 clamping | `test_managed_child_applies_real_model_clamping` (3): gpt-5.4 high→high, kimi-k3 medium→high, kimi-for-coding high→off, raw argv unchanged |
| R5 malformed cutoff | `test_managed_malformed_arguments_have_no_launch_effects` (3): HIGH, boolean, alias key rejected through actual owner graph; no registered handle/capture/writer/spawn, durable validation observation |
| R6/R7 distinct direct failures | `test_managed_direct_failures_keep_distinct_lifecycle` (2): unknown direct raises exact `ValueError("Unsupported reasoning model 'unknown-managed-model'.")`, no structured terminal/status/inbox, injected dead-PID reconciliation fails handle; missing Kimi credential has started/failed inbox, exact resolver error, failed status, no child factory or persisted run_started |
| R6 admission failure | `test_managed_openrouter_preparation_failure_is_child_owned`: zero owner HTTP; real OpenRouter client on MockTransport GET key + empty models; real prepare rejects missing route; safe model_preparation event, failed status/inbox only, no child factory; owned HTTP client closed |
| R7 abort | `test_managed_abort_targets_registered_identity_only`: actual WorkflowCommandService.abort, durable abort file before injected SIGTERM, aborted handle, deterministic escalation callback targets only registered test PID; dead probe prevents additional signal |
| R2 precedence | `test_managed_snapshot_and_explicit_precedence_over_saved_preference` (3): omission uses bootstrap low, explicit off/high wins over saved medium |
| R2/R8 legacy | `test_managed_legacy_no_flag_uses_child_preference_or_seed` (2): original legacy factory omits flag; real CLI uses saved medium or committed gpt-5.4 seed high |

## Safety and composition boundaries

Read capture_test_safety.py and canonical tests/state_isolation.py + conftest before subprocess suites. Reuse autouse imported-root isolation; local SLO_PARENT_PID removal; clean cwd; synthetic store credentials and exact synthetic capture key. CaptureLaunchContainment denies external sockets/unapproved processes; only finite owned writer bootstrap executes. No workload subprocess, real signal, terminal window, default provider client, paid/live inference, broad cleanup or parent audit hook. Store class preserved through constructor injection with strict test-PID probe. Factory recorder accepts only owner and recorded child identities and returns LLMBuildResult. No `_build_agent`, prepare, readiness, status or notifier mock.

Owner invocation completes first. Child CLI executes on one awaited worker thread with exact captured argv slice and scoped recorded environment; no concurrent stdio/env mutation. Only signal install/restore is disabled for the worker. Delegating real runner initializer retains the actual runner; shutdown wrapper drains its pool on the child loop then delegates real catalog shutdown. Real HTTP client ownership closes MockTransport client on that loop. Phase stub replaces workload transport only. Captures are empty endpoint-lifecycle evidence, **not native child stdout capture proof**. Every retained writer is closed/joined with timeout 25 and checked against exact registered PID set. No new runtime safety API.

## Actual receipts

All prefixes below reside beside this report with `.command`, `.log`, `.exit`. Every command used unchanged `run-gate.sh` from application cwd, command-local approved VIRTUAL_ENV/PATH `/root/.pyenv/versions/slo-harness`, Python3.11.7, PYTHONPATH and existing test fallback. Logs are locally retained but Git-ignored.

- `continuation-01-owner`: 1 failed/2 passed, fixture used `prompt` instead of session `text`; corrected at 02 (3 passed).
- 03: fixture called nonexistent `list_for_owner`, 1 failed/3 passed/1 teardown error; 04 corrected to actual list API (4 passed). Spawn recorder now retains endpoints before assertions so failed assertions still have bounded cleanup ownership.
- 05 child lifecycle: 5 passed; 06 phase: 6 passed; 07 clamp/validation: 12 passed; 08 direct failures: 14 passed; 09 abort: 15 passed.
- 10 preparation: 1 failed/15 passed due whitespace-sensitive JSON assertion; 11 parses actual JSON (16 passed).
- 12 precedence: 1 failed/20 passed because test guessed seed off; committed seed `_openai_flagship_reasoning_profile` says high; 13 corrected oracle (21 passed).
- 14 mypy: 2 errors (Result import/sibling type); corrected to typer.testing.Result. 16 scoped mypy green.
- 17 surrounding: 892 passed/60 warnings before final strengthening.
- 18 strengthened typed fleet/preparation identity checks: 21 passed; 20 scoped mypy green; 21 coreutils integrity empty/exit0.
- 22 owning-loop pool drain: 21 passed.
- 25 strengthened exact unknown-error assertion: 1 failed/891 passed; incorrect guessed message corrected to observed reasoning constructor message, no production change.
- **26 final surrounding**: `poetry run pytest -q -m 'not e2e' tests/agents/slo_agent/orchestrator/ tests/cli/test_typer_dispatch.py tests/cli/test_headless.py tests/agents/test_reasoning_capabilities.py tests/agents/slo_agent/tool_execution/test_executors.py` — **892 passed, 62 warnings, 54.11s, exit0**. Includes all 21 composed cases after final code edits.
- **27 Black**: `poetry run black --check tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py` — 1 unchanged, exit0.
- **28 mypy**: same new module — no issues, exit0.
- **29 integrity**: `dpkg -V coreutils` — empty, exit0.
- **30 diff**: `git diff --check` — empty, exit0.
- **31 protected**: seven repository policy hashes from retained plan unchanged, exit0; explicitly filters to skills paths and never accesses absent sources.

Retained dependency deprecations and existing AsyncMock unawaited-coroutine warnings are visible in final log, including teardown output. Not warning-free, not silently waived. Receipt sequence numbers are local command counts, **not workflow dispatches**.

## Remaining same-phase work and limitations

- P4 feature guidance, schema-checked skill examples, budget-source verification, docs/AGENTS/research and generated index remain outstanding.
- P5 whole-repository `make lint` (src + tests), bounded full formatting scope, skill/index idempotence gates, full `make test` and final manifest/diff review remain outstanding. Scoped green does not replace them. A separate same-phase gate dispatch is appropriate; no Step1 READY claim.
- Behavioral suite proves failed OpenRouter admission, not a successful dynamically discovered OpenRouter child. No live/provider-effective reasoning claim.
- Exact unknown startup and credential terminal errors are asserted. Missing-credential case proves cutoff before factory; an explicit retained-child active-off assertion would further strengthen that negative row (positive off clamp already proved separately).
- Test fixture includes several local helpers/imports and could be tidied during review, without widening runtime scope. Full selected CLI/tool convention rereads were not completed in this call; retained routing specializations were reused. Shared routing/ownership/testing, generic coding/cadence/coverage, Python root/types/docs and agent-testing, named workflow, project context and KB entry/index/gotchas were consulted. No claim of independent review.
- Original-source preservation/compliance remains unverifiable by explicit operator decision; never reinstate restoration as prerequisite.
- Independent Step2 review then fresh Step3 completion remain mandatory. No commit/push/PR/publish/install/global configuration/other-worktree edits.
