# Scope/routing assessment — READY

Date: 2026-10-17. **READY for the bounded READ/ANALYSIS prerequisite deliverable.** Full requested spec/sample and routing ingestion is complete; execution plan and gate treatment are recorded. This is NOT T1 readiness/completion, implementation approval, independent implementation review, a static-gate waiver or live compatibility acceptance. T1–T6 remain pending.

## Delivered artifacts

- `docs/implementation/94-herdr/scope-plan.md`: full seven-document reading coverage (9,859 lines), accepted evidence, actual six-node/six-edge graph, bounded assignments, R1–R26 and B/C/D acceptance mapping, numeric/semantic invariants, all exact attachment locations, safety and live prerequisites.
- `docs/implementation/94-herdr/routing.md`: frozen phase handoff; selected absolute paths/tiers, override resolution, Python/asyncio/Pydantic/Typer/Textual/Faux boundaries, scoped exclusions, test categories, exact commands, runtime evidence and preserved counts.
- This assessment: diagnosed baseline treatment and precise authorization boundaries.
- `docs/implementation/94-herdr/workflow-state.md`: updated state without resetting counts or claiming review.

Original `baseline.md`, `baseline-continuation.md` and every baseline command/log/exit receipt remain unchanged. Their historical FAILED-preconditions interpretation is superseded below, not their factual results.

## Actual baseline rule and correction

**Authoritative source:** canonical H/tasks.md line 263 (T6 acceptance): “Full non-E2E green is required; baseline failures are reported, not silently waived.” Common execution rules at lines 60–66 require test-first increments, scoped/surrounding checks and full gates before declaring implementation done. B/C/D prescribed commands retain Black/mypy; current user explicitly requires all gates and no regressions. The committed Code-Test-Review preconditions require spec/context/conventions/KB/feature checkout; they do **not** say every pre-existing static diagnostic must be repaired before reading a specification or starting a safely isolated unit. Engineering-testing requires distinguishing reproduced baseline defects from new failures.

Therefore:

1. **No blanket early stop.** Pre-existing lint/format failures do not block independent reading, this plan/routing deliverable, or otherwise authorized bounded feature coding. Calling all preconditions FAILED solely because lint was nonzero was too broad.
2. **No silent waiver.** The baseline is not green. Historic Feature 86 waivers and a green test run do not waive Feature 94 static requirements. Final acceptance cannot claim all gates pass while lint remains failing.
3. **No automatic unrelated rewrite.** Full gate requirements are not unlimited authorization to redesign unrelated TUI/provider code. Diagnose the concrete diagnostic and smallest correction, classify ownership and verify behavior before broadening the write set.
4. **No remediation now.** This assignment expressly forbids code/tests implementation. Safe repairs belong to later authorized bounded coding, not this analysis phase. No user decision is needed merely to finish these reads/artifacts.

## Retained gate facts

At unchanged feature base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`:

| Receipt | Exit | Actual result |
|---|---:|---|
| baseline-test.command/log/exit | 0 | make test: 6272 passed, 19 deselected, 408 warnings, 466.80s |
| baseline-smoke.command/log/exit | 0 | make smoke: 278 passed, 2 warnings, 2.70s |
| baseline-lint.command/log/exit | 2 | make lint: 301 errors in 64 files, 682 checked |
| baseline-black.command/log/exit | 1 | broad scoped check: 5 would reformat, 185 unchanged |
| coreutils-after-test / coreutils-after-smoke | 0 | dpkg -V coreutils silent |

No long gates rerun in this documentation-only pass. Parsing the existing lint receipt independently counted 301 `error:` lines and 64 unique file paths. These are pre-feature errors, not demonstrated regressions. They remain unresolved and unwaived.

The five formatting files are `src/tui/authentication/auth_screen.py`, `tests/cli/test_openrouter_terminal_lifetime.py`, `tests/cli/test_wheel_contents.py`, `tests/tui/test_openrouter_reasoning_presentation_recovery.py`, `tests/tui/test_openrouter_picker.py`. The original broad directory check is explicitly not the finalized whole-feature scope. The chapter Black fences plus changed-file checks must all pass later; neither relabel this historical check as passed nor expand unrelated editor behavior just because a broad check included it.

## Concrete diagnosis and safe remediation boundary

This is sufficient classification to plan, not a claim that all 301 fixes have been proved safe. Existing log examples identify several distinct causes, not one missing executable:

| Baseline evidence | Treatment during later coding |
|---|---|
| src/cli/app.py:44 TyperGroup parse_args Context override mismatch (2 errors) | Direct T3 owner. Inspect actual Typer/Click context types; smallest truthful signature correction with CLI parsing/ordinary resume tests is gate-enabling work within touched scope, not unrelated TUI work. Do not relax mypy globally. |
| tests/cli/test_headless.py (9 errors), tests/tui/workflows/test_workflow_app_service.py (5 errors) | Direct T5 test owners. Align recording protocols, explicit types and monkeypatch seams while preserving assertions; focused tests plus full lint. Existing error count is not permission to add more. |
| missing yaml stubs in registry/loader/tests; registry.py:209 kind str versus Literal | Distinguish environment typing dependency from actual source typing. No `mypy --install-types`, pip install or global environment repair in this task. A declared dependency/environment change needs an explicitly scoped follow-up respecting host rules; a truthful local annotation/validation correction may be proposed separately. |
| tests/tui/test_transcript_projector.py (66 errors), test_tool_block_partial.py (9), test_recovery_ux.py (5), slodiff/renderable/selection tests | Existing fake/protocol/renderable narrowing mismatches, outside primary Herdr write set. Do not redesign selection, rendering, input geometry or add ignores to make green. First propose bounded behavior-preserving type-only/test-fake repairs with exact files and focused tests; if substantive unrelated TUI behavior is required, ask user authorization. |
| providers/faux.py override/Pydantic ctor errors; Anthropic/OpenAI SDK typing; compaction test doubles (27 errors) | Shared test/runtime dependencies or unrelated existing owners. Analyze pinned SDK types and truthful protocols, not broad Any/cast/ignore workarounds. Do not claim all repairs authorized merely because Herdr tests use Faux. Escalate required out-of-scope behavioral or package changes specifically. |
| five broad Black failures | Formatting-only diffs are distinguishable from redesign, but current assignment authorizes neither. Later apply scoped formatter only to authorized touched files; if retaining the broader baseline command as a final gate requires these unrelated files, request/record explicit narrowly mechanical scope, not a general TUI rewrite. |

**Operational conclusion:** future feature work can proceed through T1/T2 and direct T3/T5 corrections without treating baseline debt as a universal blocker, once coding is authorized. The complete lint gate is a known acceptance dependency. Maintain an attributable baseline-to-current diagnostic ledger; never replace the full gate with “no new errors.” If remaining green-gate work truly requires unrelated behavior changes, host/package installation, global settings or excluded TUI scope, present those exact required actions for user authorization before performing them. No such action is necessary to finish this deliverable, so FAILED is not justified here.

The existing instruction “all gates” establishes the required outcome, not approval to waive gates or mutate protected system paths. This record neither accepts debt as release-ready nor asserts that the entire 64-file repair is safely inside Herdr. It separates direct gate-enabling maintenance from a concrete future scope decision.

## Runtime and routing evidence

- Actual parent PID 2689048: allowlisted argv confirms `--model gpt-6-astra --session-id de61c798-b11e-4f0a-b8c5-008a25d65e98 --orchestrator`; no reasoning flag. Parent cwd is `/root/Code/slo-workflow-budget-overrides/slo`; no writes there.
- Actual parent environment lacks stream/child timeout overrides and child legacy alias. Read source config defaults in both checkouts: 10800s parent / 7200s child. No claim of runtime memory introspection and no ineffective child-shell export attempted.
- Attributable metadata session.json confirms ID/model. Allowlisted reasoning fields in session.json/orchestrator.json/orchestrator_context.json do not establish effective reasoning. No transcript or raw prompt/global preference/credential output. High reasoning is **unverified**, not inferred from model identity or current prefs; no global mutation is authorized or needed for this plan.
- Effective SLO_SKILLS_DIR remains installed pipx tree. Selected committed workflow/shared/Python/Typer/Textual files and index were compared byte-for-byte with installed counterparts: same. No selected-name personal overrides found; user-workflows directory absent. Runtime loader merge and config precedence inspected directly. Routing.md records exact paths and scoped applicability rather than assuming the committed directory is the runtime override.
- Actual `.python-version` is slo-harness; `pyenv which python` and `python --version` confirm approved Python 3.11.7. No interpreter/alias/package changes.
- `/root/.local/bin/herdr` observed regular mode 755; no invocation, version probe, server operation or compatibility claim.

## Remaining decisions and required later evidence

No genuine blocker prevents this prerequisite from being READY. Implementation remains unstarted by instruction, not blocked by incomplete reading.

Later requirements that need separate authorization/evidence:

1. Coding authorization after this bounded deliverable; no implicit transition into T1 here.
2. Exact out-of-scope gate-remediation actions if inspection shows required behavior/package/host changes; do not request a blanket baseline waiver.
3. Explicit disposable named Herdr session/restart/cleanup permission and supported-version/pane/paint acceptance. Never operate the existing live workspace/server.
4. If explicit high reasoning for a future worker is required, supply it at that worker's launch and record it; do not edit global prefs or claim it for the already-running parent.
5. Fresh full non-E2E/smoke/lint/scoped Black and branch-specific integration evidence after code, independent **full-scope** review, then fresh completion assessment. Accepted spec review and this self-check are not substitutes.

## Executed artifact verification

Read-only stdlib check from the feature application root compared every task sample fence with its canonical source ordinal: **72/72 exact unique attachments match** (exit 0). It also checked all selected absolute skill paths exist and all four output Markdown files have balanced fences (exit 0). Existing baseline exit receipts reconfirm 0/0/2/1 without rerunning gates. `git diff --check` exited 0; tracked diff is empty and status contains only the existing untracked `docs/implementation/94-herdr/` directory. Since these artifacts are untracked, diff-check alone does not validate their content; the explicit document checks and content self-check supply that evidence. No product verification is implied.

Frozen `routing.md` SHA-256: `ca705057a4b22709de4873be158b3c7117be0c84cf51770969c78022d9cc0bb7`. Pass those exact bytes to later phases. Scope plan SHA-256: `c0c3e1ec1708bc7aefe93881389c8e8921f26b334103aac9730ed4585dd562c5`.

## Accounting and preservation

User-supplied current counts supersede the older workflow-state receipt: turn 1 active; started 1, completed 0, historical partial 0; dispatches **3 consumed / 17 remaining of 20**; unlimited turns; retries consumed 0. No spawn or reset. No independent review/completed workflow turn claimed.

Only requested local Markdown deliverables/state are written. Production/test code, specifications, skill files/index, baseline receipts, global preferences/configuration, KB, other worktrees and system/PATH files remain untouched. Read chunk corrections and two malformed parallel read calls were tool-use corrections, not execution retries or missing final reads. No product sample/check script was executed.
