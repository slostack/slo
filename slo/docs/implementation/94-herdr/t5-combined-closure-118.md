# T5 combined closure 118 — READY (bounded combined family only)

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1,
supplied dispatch 118, retries 0. User turn and dispatch budgets unlimited. No
agents, commits, pushes, PRs, reset/clean/stash, production, canonical-spec, global,
live-system or other-worktree edits. T6 and independent review remain separate.

## Exact change and outcome

Only `tests/tui/test_herdr_all_owner_cutoffs.py` changed in this continuation.
The second owned file, `test_herdr_multiple_viewer_owners.py`, and the real-resource
helper `test_herdr_viewer_retention_composed.py` remain unchanged.

- Captured lease gateway is asserted with the exact store object, selected session
  ID and owner ID captured before shutdown. The actual store's delegated release
  is independently asserted with those exact IDs, not merely a call count.
- Inbox timer spy is reset immediately after the deliberate fixture polling pause.
  Both actual timer handles must subsequently receive exactly one argument-free
  stop from shutdown; fixture setup can no longer satisfy the assertion.
- Actual HerdrReporter.close is recorded from before replacement and delegates the
  original implementation. Outside the callback, the entire recorded owner list
  must equal the single exact retired reporter. Its real local drain gateway is
  also independently asserted awaited once with no arguments.
- Every refused cutoff asserts original-session invoke and prompt-history record
  were never called, and reads actual durable history to assert no user_message
  or tool_call. These assertions execute in the explicitly gathered observer task,
  outside the isolated diagnostic/subscriber callbacks. Restart proof is retained.

The first strengthened run passed. No production RED was found or manufactured;
there is no production correction. Existing actual child/reap/sequence-lease,
Faux invocation and cancellation barriers were not replaced with mock-only proof.
No new axes or test cases were added.

## Whole finite combined map

C = canonical `94.b.2-session-publication-and-native-restore.md`; D =
`94.c.1-herdr-workflow-visualizer-and-acceptance.md`, under
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/`.

| Obligation | Executable evidence | Closure |
|---|---|---|
| C7.9/7.14 claim await | all-owner `claim_pending` | Exact claimed bytes, running handle, no ack/task/original invoke/user history; same-ID restart refuses replay |
| C7.9 durable advance cutoff | all-owner `workflow_advance_pending` | Completed durable handle, claimed bytes, no ack/task/invoke/user history; restart refusal |
| C7.9 last registration cutoff | all-owner `before_chat_registration` | Registration gateway observed but no task; completed handle, claimed bytes, no invoke/user history |
| C7.9 admitted original-store ack | `registered_original_store`, `registered_abort_original_store` | Exact admitted task retained through shutdown; real normal/explicit Faux abort; original ack once |
| C7.9 displaced-store ack | `already_registered`, `registered_abort` | Original ack once, displaced storage absent, exact done bytes; same admitted task |
| C7.13/F2 real quarantine | unchanged exercise_retained_viewer in every all-owner and multiworker case | Same child three reap attempts, real sequence contention, GC strong ownership, repeated /new suppression, no command retry |
| C7.13 persistent final drain | persistent cases in both owned files | Graceful unmount stays pending, child/lease retained; fixture rescue is not reported as graceful success |
| D actual multiple workers | eight multiple-viewer cases | Real scheduler/session/launcher/shared transport, one admitted split and second queued reservation; exact join list |
| D first registry join failure | registry-fault variants | Later worker still joined; real diagnostic sink raises and invocation asserted |
| C replacement cancellation + D | cancel-replacement variants | Repeated public /new caller cancellation; both gate-dependent finalizers joined before adoption |
| C7.14 diagnostic containment | both owned files | Original preparation/registry fault plus actual throwing sink; later owners still reached |
| C7.14 independent owner evidence | all-owner final assertions | Viewer/preparation/current close/current final/retired final/local drain/unsubscribe retained; exact captured lease store+IDs, shutdown-only timer stops, independent retired reporter close+drain now closed |
| Original-session refusal | all three refused cutoff variants | Original invoke/history forbidden calls and durable no-user/no-tool assertions now explicit, not inferred from restart |
| Routing/read reconciliation | below | Explicit 117 remaining skill/KB/multiple-parent/platform/inbox reads closed; no claim of full independent implementation review |

All-owner cases retain the existing seven scenarios × both final-drain outcomes ×
healthy/throwing diagnostics. Multiple-viewer cases retain their existing dimensions.
This finite map closes ledger 117's combined-family gaps; it does not purport to
implement T6's separate 64-case matrix or two-process restore journey.

## Read reconciliation

Reused unchanged ledger 117's complete canonical C7.9–7.14, full D, T5 attachments
and accepted independent-review-turn4/finalization-receipt reading, as explicitly
requested. Freshly consulted C2085–2119 for exact F1/F2/F4 obligations and the separate
T6 cross-product boundary. No canonical edits or restarted whole-family spec audit.

Fresh actual project reads: AGENTS.md (tail plus recovered 1–80), CLAUDE.md,
root RESEARCH.md, docs/RESEARCH.md (aggregate tail plus recovered 1–319), frozen
routing.md and scope-plan.md, Makefile and t1-dao-check.sh. Frozen routing's existing
scope/exclusions remain unchanged: Python, asyncio/Textual, composed offline tests;
no database/web/Go/TypeScript/new CLI implementation or new solution design.

Fresh committed skills: engineering routing/testing/ownership; coding-rules,
code-test-loop, shared declarative, code-design-principles, naming-and-clarity,
test-verification-policy, solution-design; Python root, named arguments, docstrings,
declarative, application-structure, build-domain-features, build-application-services,
switch-environments-and-run-tests, test-graphs-and-agents; Textual and product Typer;
locate-knowledge-base; exact Code-Test-Review workflow and workflow rules. Oversized
aggregate output prefixes were recovered with bounded reads rather than treating
truncation as completion. Solution-design read is guidance only, not permission to
create a new design exercise. Framework examples do not add dependencies.

KB reads: Welcome, slo/README, gotchas, skills-and-kb, tui-cli-session,
headless-workflow-orchestration, including recovered truncated prefix. Historical
paths/defaults are not current source authority. No KB writes under this scope.

Fresh affected-test reads: both owned files, complete retained-viewer helper,
combined-cutoffs and inbox-disposition (including original invocation/history and
restart tail), activation-composed factory, tests/state_isolation.py and conftest;
T2/T4 real shared transport/multiple-parent evidence in visualizer_acceptance,
visualizer_lifecycle and visualizer_lifetime_acceptance; platform lifetime tests in
test_herdr_visualizer and full test_visualizer_launcher. Inspected actual shutdown
owner chain app950–1069, timer/lease chain around2495–2578, and session2490–2669.
These close the explicit 117 reads, not an assertion of fresh full-source ingestion
of every unrelated app/session method. Earlier broader reads remain inherited.

## Verification receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`; approved
`PYENV_VERSION=slo-harness`, pyenv interpreter
`/root/.pyenv/versions/slo-harness/bin/python`, Python3.11.7; make test-env = fallback.
No venv/install/env-file changes. All test tool calls allowed 1800 seconds.
Existing HERDR stripping, default disable, independently registered regular-file
fake capability, containment/identity guards, real-terminal guard and Faux factory
remain active. No live provider/Herdr/window evidence is claimed.

All receipt stems below live beside this document, each with `.log` and `.exit`.

| Stem | Command | Actual result |
|---|---|---|
| t5-118-focused | approved t1-dao-check.sh + all_owner_cutoffs, multiple_viewer_owners, viewer_retention_composed | 101 passed,18 warnings,24.65s; exit0, initial pass |
| t5-118-surrounding | approved t1-dao-check.sh + exact arguments below | 800 passed,103 warnings,281.40s; exit0 |
| t5-118-test | PYENV_VERSION=slo-harness make test | 8205 passed,19 deselected,626 warnings,763.10s; exit0 |
| t5-118-smoke | PYENV_VERSION=slo-harness make smoke | 288 passed,2 warnings,2.70s; exit0 |
| t5-118-lint | PYENV_VERSION=slo-harness make lint | 295 errors/60 files,792 checked; exit2, UNWAIVED |
| t5-118-lint-comparison | diff sorted full ` error:` lines from117 and118 lint logs | silent exit0, byte-identical inventory |
| t5-118-black | PYENV_VERSION=slo-harness poetry run black --check, all changed/new src/tests Python paths | 140 unchanged; exit0 |
| t5-118-diff | git diff --check | silent exit0 |
| t5-118-coreutils | dpkg -V coreutils after full/smoke/static gates | silent exit0 |

Surrounding arguments:
```text
tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows
tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py
tests/agents/slo_agent/herdr/test_session_lifetime.py
tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py
tests/agents/slo_agent/herdr/test_final_lifetime_closure.py tests/cli/test_headless_retained.py
```

The approved helper prepends 62 DAO/projection cases; totals overlap, not additive.
Formatting only the owned changed test preceded surrounding/full runs; formatter
output is t5-118-format.log. No source/test changes after the full gate. The final
140-file inventory is t5-118-python-files.txt and hashes t5-118-snapshot.sha256.
Warnings, including existing unawaited AsyncMock warnings, were not hidden.
No ignores, waived diagnostics, altered deadlines or weakened existing assertions.

## Verdict and boundary

**READY for this bounded combined family.** All exact remaining rows of 117 are
closed by the assertions/read reconciliation above. Full runtime gate passes.
Static baseline is still unwaived: this is not all-gates-green, whole-T5 author
approval, independent review, workflow completion, T6 acceptance or release readiness.
Next larger work remains whole-T5 author reconciliation and the separately scoped
T6 full64/two-process/documentation work. Historical receipts remain unchanged.
