# Dispatch 11 — DC09 bounded matrices and prerequisite reconciliation

**REVISE / tested partial milestone; cutover GATED.** No final review or completion. Production TyperDispatch constructions unchanged (no true flags); constructor defaults remain false. No waiver. Turn1 started1/completed0/partial1, dispatch11/20, zero retries, 60turnmax. Code+Test requested gpt-6.1-sol/medium; independent final gpt-6-astra/medium remains pending. No agents, nested workflow, commit/push/merge/PR, package installation, host modification or harness expansion. Existing SLO.md/docs/prior edits preserved. README and explicitly required KB runtime page updated narrowly.

## Boundary and plan

Original DC09 read in full; original DC01–08 §8 A-rows reconciled against routing/handoff/ledger and dispatch5–10 reports and actual tests. Project README/SLO, Makefile/pyproject, ancestor inventory, KB Welcome/slo README/gotchas/conventions/environment/operational reference/tui-cli-session and supported MEMORY consumed. Installed workflow/shared, engineering routing/testing/ownership, coding rules/design/naming/declarative/testing/cadence, Python root/style/application/test/agent recipes and Textual guidance read. Continuation routing reused, not invented. RESEARCH absent as previously recorded; no replacement created and user docs untouched.

Plan: reconcile source rows → add real missing prerequisite journeys → mounted matrix → failing rollback/invariant tests → narrow guards → affected suites → static gates → compact handoff. No sibling specifications, urgency implementation, schema, new public configuration or deletion of legacy responsibilities.

## This dispatch's owned changes

- `sessions/service.py`: `has_messaging_store()` presence-only canonical path predicate, no open or schema inspection.
- `tui/app.py`: legacy ordinary Enter refuses before clearing with fixed rollback text; `_register_prompt_task` and `_queue_prompt` raise invariant errors for messaging compositions (before closing checks).
- `cli/headless.py`: legacy execution refuses store presence inside existing run_failed/error lifecycle, no provider request.
- `tests/cli/test_headless.py`: existing ephemeral session fixture and blocked watchdog fixture implement new synchronous presence predicate. No assertions weakened or tests excluded.
- `tests/cli/test_headless_messaging.py`: real legacy runner empty-store refusal/no-provider journey.
- New `tests/tui/test_composer_prerequisites.py`: real worker/SQLite sender-limit and queue-full × unchanged/newer draft, plus both admission/lookup deadlines and original-ID slash retry.
- New `tests/tui/test_composer_visual_matrix.py`: six mounted legacy/messaging geometry/focus/recall/literal/band comparisons; twelve provider/admission-held keyboard/paint cells.
- New `tests/tui/test_messaging_failure_matrix.py`: rollback, invariants, corrupt/owned/urgent/ui_notice/machine-recovery/ephemeral/storage failure rows. **Urgent row intentionally remains a visible failing requirement, not skipped/xfail.**
- `tests/tui/test_legacy_inbox_bridge.py`: mounted recovered scan held after real page read with an admitted/applied, ackable original claim; displacement/shutdown cutoff prevents ack and paint; real damaged SQLite machine verification retains claim and next admission refuses storage_unavailable.
- README additive runtime/rollout/rollback section; KB `/root/Code/KnowledgeBase/KB/slo/tui-cli-session.md` additive current-runtime section labels cutover gated. Historical docs preserved.

No lasting change to messaging/client.py or session urgency policy: two attempted refusal locations were reverted when they broke existing mandatory delivery tests.

## Prerequisite A-row reconciliation (original rows, not test totals)

| Original rows | Actual evidence / status |
|---|---|
| DC01 A1–A3 | Injected activation/binding/refusal/lease reacquisition tests in `test_injected_activation.py`; rerun in 482-pass source regression. |
| DC01 A4–A8 | Mounted reporting/prepare/start, fail-closed ownership, non-durable receipts, client-before-session cleanup/retention, legacy Enter in durable composer/protocol tests. Current affected101 and source482. Cancellation/displacement activation gateway remains complementary to mounted activation, not full /new proof by itself. |
| DC02 A1 | Real three busy Enters, ordered distinct IDs, exact application/history/provider contexts and answers; current affected101. |
| DC02 A2–A4 | Earlier scripted evidence was insufficient for specified real SQLite cases. **Now added:** `test_real_sender_limit_preserves_or_restores_draft[False/True-sender_limit/queue_full]` and `test_real_unknown_outcome_retry_observes_single_committed_identity`. Held real worker, no B row/provider, exact refusal, newer C preserved/draft listed or B restored/cursor end; retry one original applied ID/provider context. Current affected101 includes all five. |
| DC02 A5–A12 | Existing capacity/bytes/eager/lifecycle/static/revision/literal/sealed tests preserved. Durable composer affected101 and protocol482; adapter static snippets are historically mapped in dispatch4 and require final all-suite revalidation. No promotion of scripted branches to real persistence proof. |
| DC03 A1–A11 | Full mapping dispatch5: flat/tree live/replay, reset/clear, receipt-before/after ordering, double overflow, machine style, invalid provenance/conflict, compaction, observer authority and presentation. Current identity affected101; observation/source482; transcript was in earlier 590/597 passing portions but the corresponding command failed overall (not a green gate). |
| DC04 A1–A8 | Full map dispatch6: real held admission retirement, repeat cancellation, exact acknowledged handoff/budget/refusal, successor suppression, exit/forced teardown. Current affected101. |
| DC05 A1–A9 | Full map dispatch7: flat/tree combined restart states, explicit continue/cancel, replay/lost reply, expiry/stale/forged/capacity, point identity and slash confirmation. Domain/source482 + mounted affected101; unchanged earlier detailed receipts retained. |
| DC06 A1–A7 | Full map dispatch8: reusable abort/resume, display-only clear, joined /new old/new leases/stores/drafts, running/full refusal, Ctrl+C. Current affected101. |
| DC07 A1–A11 | Dispatch9 map preserved; finite/source482 + runner/steer affected101. A4 actual revision/check/wake race has no await between final revision comparison and event.wait; no additional injectable seam needed. A8 remains complementary real hung runner/actual cancellation + prepared-journal repair; **not a combined runner/prepared-journal crash injection**. Required outputs have individual real proofs, no waiver claimed; independent reviewer must assess sufficiency against original row. |
| DC08 A1–A11 | Dispatch10 map preserved; original domain/source482 + mounted bridge affected101; original Inbox disposition/cutoff112. New mounted ackable held-page cutoff tests and machine-verification storage failure close previously absent dedicated cases. Scan test invokes same scan gateway in a mounted app after initial mount (initial mounting await cannot be held across run_test entry); displacement uses actual adoption gateway, shutdown flips its real cutoff flag. **Not full /new or native unmount inside initial scan.** No claim of held verify-await displacement, concurrent claim-edit/ack, or every receipt state separately. Existing broader lifecycle tests remain complementary, not replacement for these combinations. |

## DC09 acceptance map

| Row | Result / precise limitation |
|---|---|
| A1 / S01-07 | **PASS** all 2 themes × 3 sizes: exact mounted editor region/focus matches legacy; multiline brackets/Up recall equal; Ctrl+Enter newline; same band region and baseline one-cell input margin. Recall seeded through real public accepted-prompt command; actual application recall separately in DC03. |
| A2 / S01-07 | **PASS** 2 themes × 3 sizes × provider/admission hold: 20 individual keys, each text prefix and `pilot.pause()` within2s, provider/worker still held, release→one exact provider input and settled run, newer draft survives/no legacy owner. |
| A3 / S01-08 | **PARTIAL / FAIL** urgent admission returns a receipt, not required unsupported. Other enumerated rows pass: real queue-full/sender-limit (prerequisite five-case suite), corrupt startup, ownership conflict, post-start SQLite storage failure and next refusal/observation notice, ui_notice unsupported, machine recovery unauthorized, ephemeral nondurable receipt, Ctrl+Enter newline. All on explicit messaging composition, **not yet production-default composition**. |
| A4 | **GATED / NOT IMPLEMENTED** TyperDispatch true flags and actual composition test. Do not flip before failing A3 and prerequisite evidence resolve. Existing test_app surface15 passes but does not prove future true flags. No config/env alternative introduced. Invariant guard tests pass. |
| A5 | **PASS** mounted legacy Enter preserves draft/no task/no history; real headless legacy empty-store returns run_failed fixed text/exit1/no provider. Presence check does not open corrupt bytes. |
| A6 | **NOT COMPLETE** affected/source suites pass as listed below; full default non-e2e gate not run in bounded dispatch (explicit user allows later separate dispatch). Independent family verification/final review/completion pending. |

### Blocking contract conflict: urgent refusal vs retained responsibilities

DC09 §6.2 expressly demands urgent priority refusal. Existing `test_delivery.py::test_retry_after_empty_selection_keeps_late_urgent_input_for_next_boundary[False/True]` and `::test_boundary_slot_priority_and_invalid_cursor_are_exact` expressly submit urgent through **LocalSessionMessagingClient**, not only private queue operations, and assert accepted ordering/high-water/frozen boundary. Session-wide refusal and client-wide refusal each caused exactly these3 failures (590/597 other tests passed). Both attempts reverted. No tests rewritten to accept the regression. Current source482 passes including all3, while the new DC09 urgent row fails visibly. Need an authorized source-specific refusal seam/contract decision that preserves the existing callers; do not silently add a global feature flag, alter low-level urgency behavior, implement sibling step02, or call either side waived. Production flags remain off.

## Verification environment reconciliation

Read-only discovery: shell `poetry run python` without selected venv resolves `/root/.pyenv/versions/3.11.7/bin/python`, missing xdist/yaml stubs. Existing approved `/root/.pyenv/versions/slo-harness/bin/python` already provides pytest9.0.3, xdist3.8.0, exact declared types-PyYAML6.0.12.20260906, Black26.5.1, mypy1.20.2, Textual8.2.8. Per-command selection:

```sh
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
```

Poetry then uses that interpreter. **No environment repair/install necessary; no shared environment modified.** Cached exact types-PyYAML wheel also exists, but not installed/copied. make lint now passes979files without ignores/stubs/exclusions. Prior missing-dependency blocker was interpreter selection, not proof deps unavailable. Serial `poetry run pytest -m 'not e2e'` remains valid if workers unavailable elsewhere; no serial impossibility claim.

## Exact current receipts

Cwd app root `/root/Code/slo-message-queue/slo`, branch message-queue. Environment above plus:
`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`.
Every pipeline `set -o pipefail`, explicit PIPESTATUS recorded in tool output. All logs in `logs/`.

| Command (prefix above) | Exit / result | Receipt |
|---|---|---|
| `timeout 300 poetry run pytest tests/tui/test_prompt_component_protocol.py tests/integration/test_session_messaging.py tests/agents/slo_agent/messaging/ -m 'not e2e' -q --tb=short` |0;482passed/331warnings/127.21s | dispatch11-source8-messaging.log |
| `timeout 300 poetry run pytest tests/cli/test_headless.py tests/cli/test_headless_herdr.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_herdr_inbox_disposition.py -m 'not e2e' -q --tb=short` |0;112passed/18warnings/12.70s | dispatch11-source8-legacy-final.log |
| `timeout 300 poetry run pytest tests/tui/test_composer_prerequisites.py tests/tui/test_durable_composer.py tests/tui/test_composer_transcript_identity.py tests/tui/test_composer_retirement.py tests/tui/test_messages_command.py tests/tui/test_messaging_session_controls.py tests/tui/test_messaging_steer.py tests/tui/test_legacy_inbox_bridge.py tests/cli/test_headless_messaging.py -m 'not e2e' -q --tb=short` |0;101passed/56warnings/106.66s (before final stronger ackable scan assertion; that final assertion rerun below) | dispatch11-affected-final.log |
| `timeout 120 poetry run pytest tests/tui/test_composer_visual_matrix.py tests/tui/test_messaging_failure_matrix.py tests/tui/test_composer_prerequisites.py tests/tui/test_legacy_inbox_bridge.py tests/cli/test_app.py -m 'not e2e' -q --tb=short` |1;**1failed/57passed/27warnings/51.03s**, sole urgent refusal failure; no skipped/deselected | dispatch11-source8-matrix-final.log |
| `timeout 120 make lint` |0;979files clean | dispatch11-lint-final.log |
| `poetry run black --check $(git diff --name-only --relative -- '*.py'; git ls-files --others --exclude-standard '*.py' \| grep -v '^docs/')` |0;44 cumulative changed Python files unchanged; docs exclusion is only user-owned untracked docs, not src/tests gate | dispatch11-black.log |
| `poetry run mypy --no-incremental` nine this-dispatch Python files above |0;9files clean | dispatch11-scoped-mypy.log |
| `make test-env`; interpreter/dependency read |fallback; existing approved environment versions above | dispatch11-environment.log |
| `git diff --check`; `dpkg -V coreutils` |0/no output each; no command stubs added | tool receipts |
| `/root/.pyenv/versions/slo-harness/bin/python /root/Code/KnowledgeBase/graph/validate.py` |1; preexisting graph missing many documents, STALE; no graph rebuild or broad KB edits | dispatch11-kb-validation.log |

Intermediate failures kept: prerequisite first2failed/1passed was test assuming done tasks removed (adapter deliberately retains them), fixed predicate to done; visual literal test assumed load_text positions cursor at end, corrected actual cursor explicitly; band has baseline one-cell margin (not zero). Initial held-initial-mount scan timed out100s (13 dots, exit124): run_test entry waits mount; replaced by same mounted scan gateway, no production change. First storage tests queried readiness-guarded properties after failure, corrected capture before corruption. First failure matrix omitted ephemeral session_id/expected recovery exception instead of DAO, corrected to actual contracts. Urgent blanket-policy attempts failed3 regression tests and were reverted as above. First headless legacy run111passed/1failed revealed old ephemeral fixture lacking new predicate; fixture contract completed,112pass final. First lint4 introduced test typing errors corrected (tuple page, callable mount property, optional adapter), final full lint passes. No hidden skip/ignore/xfail.

## Next bounded closure and full-verification plan

1. Resolve urgent boundary conflict explicitly while preserving retained low-level caller behavior; leave visible failing test until fixed. No default flags yet.
2. Decide/close DC08 remaining exact lifecycle proof: initial-mount displacement/verification-await guard versus current mounted same-gateway/page proof and complementary /new/shutdown suites. DC07 A4/A8 complementary proof needs independent assessment, not invented waiver. Add only necessary exact cases, not combinatorial harness expansion.
3. Only after prerequisites and DC09 failure matrix green: `messaging_enabled=True` solely at all three TyperDispatch roots (normal+resume interactive, Herdr restored interactive, headless); actual wiring test in tests/cli/test_app.py; rerun matrix on root-composed default path and affected CLI tests. README/KB wording switch from gated to activated only then.
4. Full gate in a **separate dispatch** with existing environment selection: `make lint`; changed-files Black/mypy/diff; `make test PYTEST_WORKERS=6` with no file exclusions. If xdist absent, full serial `poetry run pytest -m 'not e2e'` is valid. Capture exact full counts/status. No broad all-fixes mandate; isolate each actual regression and bound next target.
5. Independent gpt-6-astra/medium final review and completion after all gates. Existing early feedback fulfilled, never substitute it for final review. No workflow turn completed here.
