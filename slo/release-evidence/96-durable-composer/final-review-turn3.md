# Aggregate final review — turn3 dispatch2

## Verdict: REVISE — two finite cumulative convention findings

The eight requested repair IDs are closed at their specified scope. The original functional acceptance evidence is supported by the three independent partition maps and the affected re-review below. **Aggregate acceptance is blocked by AGG-01 and AGG-02**, discovered while completing the previously unfinished cumulative convention pass. Neither is a demonstrated runtime/data-loss defect. No new product requirement, test framework, warning-cleanup project or broad legacy refactor is requested.

Independent of implementation authorship. Counters carried unchanged: **3 started / 0 completed; turn1 partial15; turn2 partial5; turn3 dispatch2/20; max60; zero execution retries**. This review is not a completed workflow turn. Separate independent completion remains required after accepted review; no local commit yet.

Authority ONLY `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`. No sibling specification was used to expand scope. A durable in-progress milestone was saved to this path before the completed report. No source/test edits, nested agents, staging, commit, publishing, package or host changes. User SLO/docs/ASCII content preserved.

## Findings — finite return to implementer

### AGG-01 — Medium: four new boundary fields still lack mandatory descriptions

**Rule:** installed `languages/python/build-domain-features/SKILL.md`, Field-Declaration Convention (required and optional Pydantic fields alike); full Python hard-rule documentation/boundary-data pass. This is the same applicable rule used by R567-02, not a newly invented standard.

**Locations:**

- `src/agents/slo_agent/messaging/dao.py:327–329`: the newly introduced `LegacyInboxAdmissionDAO.message_id`, `kind`, `text` are bare annotations.
- `src/tui/slash_router.py:142`: the newly introduced `SlashCommandResultDAO.messages_command` uses bare `= None`.

**Consequence:** these feature boundary fields remain undocumented in generated schema despite the specified documented boundary convention. The ten recovery fields and MessagesCommandDAO repairs do not cover them. Existing unrelated bare fields are not part of this finding.

**Correction / closure:** use described `Field` declarations on these four fields only; preserve requiredness, default None, Literal choices, frozen inheritance and existing validation. Inspect generated schema and run affected DAO/legacy-admission/slash/default-path checks plus required final gates. No schema migration or new validation policy.

### AGG-02 — Medium: 19 feature-added parametrizations still violate keyword-call convention

**Rule:** README Style rules; installed named-arguments-and-type-hints §§1/4 and hard checklist §1.1. `pytest.mark.parametrize` supports `argnames=` and `argvalues=`; these are not positional-only calls. The earlier DC-R04 list was finite and its listed sites were corrected, but the unfinished cumulative pass had not covered these remaining sites.

**Exact locations (current line numbers):**

| File under tests/ | Lines |
|---|---|
| agents/slo_agent/messaging/test_finite_completion.py | 30,168,436 |
| cli/test_app.py | 54 |
| cli/test_headless_messaging.py | 22 |
| tui/test_composer_prerequisites.py | 48,49 |
| tui/test_composer_visual_matrix.py | 24,25,84,85,86 |
| tui/test_inbox_displacement.py | 56 |
| tui/test_legacy_inbox_bridge.py | 504 |
| tui/test_messaging_failure_matrix.py | 57 |
| tui/test_messaging_session_controls.py | 82,155,367,439 |

**Correction / closure:** name the existing arguments, preserving every parameter value, ID, matrix cell and assertion. No conversion of unchanged historical decorators. Verify unchanged collection and affected execution, then required final gates. An AST comparison against HEAD identified these added calls; the finite finding concerns supported keyword calls, not a general ban on variadic asyncio/Textual/native APIs.

## All eight repaired findings — independently inspected disposition

| Stable ID | Disposition and decisive source/assertions |
|---|---|
| DC-R01 | **Closed.** `app.py:347,385,504` provides public typed prompt_factory with production component default; recording/failure behavior exists only in `tests/tui/recording_prompt.py`. No `_recorded_outcomes` or `_outcome_failures_remaining` remains in Python production source. Component outcome handling deletes settled tracked entries and records only bounded recall identity/text. Test-owned recorder delegates real typed handle and retains original receipt/failure oracles. `test_successful_draft_snapshots_are_released_across_reset_and_rebind` uses the default production editor,24 weakrefs, completed adapter joins, empty component/adapter maps, GC checks after every completion and after reset/rebind. It proves enclosing snapshots are collectible, not that all prompt text is erased (recall intentionally retains text). Failure test still checks raised receiver failure, sibling completion and borrowed client not closed; complementary held-sibling/cancellation tests in the partition remain applicable. |
| DC-R02 | **Closed.** `test_durable_composer.py:1342–1432` installs a narrow Python3.11 task factory, steps the actual `_submit_flow` inline, fails on suspension and restores prior factory in finally. Injected PrecommitProbe sees uncommitted entry and unchanged `eager` text, delegates the real receiver, observes early stash/no recall, then requires empty editor/maps and exactly one submission/delivery/recall. No private assignment of early_outcome; not merely an immediate async response. Future completion uses the task factory's supported Future return surface; Any is confined and explained as heterogeneous asyncio typing. |
| DC-R03 | **Closed.** `test_durable_composer.py:1109–1151` now covers C→Backspace→empty before same-binding delayed sender_limit. Empty stays empty, exact B is recoverable, one submit/no lookup and no SQLite row. Untouched-clear restoration and revision-boundary tests remain. Component restore predicate still requires cleared revision equality, binding identity, empty text and unsealed/open lifetime. |
| DC-R04 | **Closed at its listed locations.** MessagesCommandDAO frozen/extra-forbid and its three fields described; SubmitDraft, DiscardDraft, accepted-message ID and verified application fields described. Recoverable tuples are specific; HeldReplaySession constructor has concrete inputs; listed multi-argument decorators now named. Additional cumulative omissions are separately AGG-01/02 rather than falsely reopening the repaired sites. |
| R567-01 | **Closed.** `queue.py:440–455` checks health then sealed under `_mutex`, before constructing the store mutation. `service.py:1810–1884` returns cached outcome first and all-cancelled durable outcome before new-mutation/expiry checks. Real-session test pauses through public abort then seals while session remains open: continue and cancel return completing, exact retained envelopes and closed rows remain unchanged, no provider request. Cached and lost-response durable replay explicitly survive seal and expiry. The standalone seal is deliberately not claimed to be the session's consumer-stop protocol. |
| R567-02 | **Closed.** `dao.py:610–683` describes all10 fields without changing defaults, bounds or validators. Schema regression checks descriptions, required sets,16-item bounds/default cursor and malformed consent. Real atomicity/replay/SQLite tests remain. |
| DC89-F01 | **Closed.** `typer_dispatch.py:66–156` has typed session/TUI factories, resolves real defaults at invocation, and applies them to ordinary fresh/resume and private restore. Logging, config resolution and true flags remain at the existing composition owner. `tests/cli/test_app.py:22–105` injects acquisition/construction rather than patching session.build; actual host is returned and mounted. Native `.run` capture is the explicit no-real-terminal boundary. Real unmodified-session root journeys remain complementary evidence for defaults; six geometry and twelve held-work cells retain their parameter sets and persisted forbidden-effect assertions. No test-only production branches introduced. |
| DC89-F02 | **Closed.** All eight changed `_capture_runner` signatures at386,415,448,484,521,557,610,675 have SessionConfigDAO/bool/optional str and MagicMock return annotations; directly associated containers are typed. True-flag/config/reasoning/resume assertions remain. Ninth untouched historical helper is not included in this repair scope. |

New seams are construction seams only: production defaults remain real session builder/SloTUI/editor; constructors remain nonmessaging by default while Typer roots explicitly enable messaging. No new CLI flag, environment variable, provider path, persistence substitute or execution consumer.

## Original acceptance aggregation — all 83 A rows retained

Detailed row-by-row source/assertion maps are incorporated by reference, not replaced by test counts:

- `review-dc01-dc04.md`: **39 rows**, original DC01.A1–A8, DC02.A1–A12, DC03.A1–A11, DC04.A1–A8.
- `review-dc05-dc07.md`: **27 rows**, DC05.A1–A9, DC06.A1–A7, DC07.A1–A11.
- `review-dc08-dc09.md`: **17 rows**, DC08.A1–A11, DC09.A1–A6.

Read all three reports completely; directly reconciled original §8 tables for01–07 and complete original08/09, and inspected affected repair source/tests. Reuse is the user-authorized scoped aggregate method, not a claim of independently rereading every unchanged source line.

| Original acceptance | Aggregate implementation/evidence disposition | Remaining |
|---|---|---|
| DC01 A1–A8 | **Implemented.** Injected activation, lease refusal/unwind, reporting/preparation order, ephemeral notice, client-before-session close and legacy default journey supported by partition source/assertion audit; recorder migration preserves evidence. | None functional |
| DC02 A1–A12 | **Implemented.** Three distinct applied busy inputs; real sender/queue refusal and uncertain same-ID retry; four waits/16 drafts/1MiB; genuine eager branch and edit-empty refusal now proven; lifecycle/static/slash/literal/sealed behavior retained. A11 means whitespace no-admission and literal normalization/admission per actual routing, not that nonempty literals are discarded. | AGG-02 conventions in complementary tests |
| DC03 A1–A11 | **Implemented.** Flat/tree live+replay identity, receipt/application ordering, two257-event overflows, machine styling, corruption/conflict/compaction and run presentation; exact514-ID oracle retained after public hydration join. | None functional |
| DC04 A1–A8 | **Implemented.** Joined reset/rebind/close/unmount, bounded acknowledged handoff, cancellation and old-binding safety, exit/forced-teardown notices. | None functional |
| DC05 A1–A9 plus §6.2 | **Implemented.** Real restart reconciliation, exact consent/transfer/cancel replay, expiry/change/forgery/capacity and slash flow; sealed new cancellation now refused under mutex. | None functional |
| DC06 A1–A7 | **Implemented.** Reusable pause/resume, display-only clear, old target retirement/lease release, running/full-handoff refusal and Ctrl+C. | AGG-02 test-call convention |
| DC07 A1–A11 | **Implemented with complementary proof**, not fictitious combined experiments: finite cutoff/admission ordering, revision wake, notes, cancellation/close, actual hard stop, orphan applying and steer; legacy headless regression evidence retained. | AGG-02 test-call convention |
| DC08 A1–A11 and §5.6 | **Implemented with explicit boundaries below.** Original UUID/source/principal/digest, receipt ack/retry/restart/pruning, capability refusal, bounded paging and displacement. Legacy matrix source audit completed here. | AGG-01 DAO descriptions; AGG-02 decorators |
| DC09 A1–A6 | **Implemented functional cutover/matrices/rollback; aggregate acceptance Partial.** Production root journeys and18 matrix cells; current full/static gates pass. Sole README feature hunk documents runtime/commands/upgrade/rollback. | AGG-01/02; accepted review then separate completion |

No acceptance rows missing, deferred or operator-waived. Passing implementation evidence does not override mandatory convention findings.

### Complementary evidence limits, explicitly reconciled

- **DC07 A4:** accept the partition's invariant proof: captured revision/event before awaited cutoff check; synchronous increment/swap/set notification; no suspension between final revision comparison and Event.wait. Existing deterministic test advances revision by admission during execution-lock wait, not a literal terminal insertion between synchronous statements. It supports the lost-wake invariant without claiming impossible injected interleaving.
- **DC07 A8:** accept the real HeadlessRunner held-provider/grace/exit2 journey together with session tests for consumer cancellation/join, observer run_aborted and prepared-journal reconciliation/readback. No one test is claimed to combine every crash-window state.
- **DC08 A1:** partition proves idle scheduler note gives no provider call and busy workflow terminal enters the same machine-admission gateway; source `_inbox_delivery_may_start` removes the idle task condition only for messaging and leaves notes on their existing session lane. This is complementary evidence, not a claimed dedicated busy-scheduler-note matrix cell or handle spy count. Durable handle result and unchanged producer policy remain the oracle.
- **DC08 §5.6:** held-page/verified-identity `/new` tests exercise the exact activation scan gateway on a mounted host, not initial-mount concurrency. Current source checks captured session/store/lease/owner before paging, after malformed await, before each item and after successful verification before ack. Separate manually armed shutdown cutoff is not native-unmount proof.

### DC08 legacy A11 — completed source trace

Read complete unchanged `tests/tui/test_herdr_inbox_disposition.py` (599 lines) and `test_herdr_inbox_cutoffs.py` (204 lines), and current `app.py:1746–2110`. Both files have no HEAD diff. Nonmessaging constructors remain false; `_inbox_delivery_may_start` retains idle task gating plus closing/transition/quiescing/replacement guards. Captured session is revalidated after claim and workflow advancement; legacy ack uses captured store. ui_notice/transcript_note/context_note/chat_turn routes retain their distinct behavior; chat registration retains final cutoff.

The original11-case disposition matrix asserts exact original bytes/lane, invocation/ack counts, no local echo/queue/recall and context idempotence. Displacement at claim/advance retains old claim/no invocation. Context-write shutdown preserves admitted write/ack. Three shutdown cutoffs×throwing notice preserve handle state and no execution, with real restart retaining the claim. Already-registered task cases preserve exact task and captured-store ack through operator abort/store displacement. Companion cutoff tests exercise four modes×closing, claim/advance/registration shutdown and local-echo-pending registration refusal. Full12272 receipt executes these unchanged tests. Historical patch-based fault harness is not expanded or used as a precedent for new tests.

## Historical finding reconciliation

| IDs | Aggregate disposition |
|---|---|
| EF01 | Closed: exact provider HumanMessage/application/history/closed SQLite oracle, plus full three-input journey retained. |
| EF02 | Closed: all siblings joined, shared close barrier, sticky observed failure and borrower release after join; test-owned failure receiver preserves oracle. |
| EF03 | Closed: actual reset/retire/rebind/close/native remove, outcome acceptance during join and acknowledged handoff. |
| EF04 | Closed: public session close after client attempts, including failure; no host private startup-task ownership decision. |
| EF05 | Closed: submitted human text recall shares bounded identity with application fallback; replay/machine do not add human recall. |
| FR01 | Closed: loop guard then closed then input type; real public lifetimes, no reopening private closed state. |
| FR02 | Closed: completion callback observes/releases Tasks, bounded first failure/traceback; repeated completion and held sibling cancellation proof retained. |
| FR03 | Closed: public replace_submission_binding with fresh adapter/borrower checks replaces private client swaps. |

These use the detailed independent partition closure maps and affected source/test inspection. The separate component-retention defect was DC-R01, now closed; it is not silently folded into FR02.

## Required receipts and current-source relationship

Cwd `/root/Code/slo-message-queue/slo`. Existing approved slo-harness Python3.11.7, explicit VIRTUAL_ENV/PATH and routing synthetic test environment. HEAD remains `5dd059cbf00134d5c5eef706875310a2eb677cdd`. Current changed+untracked Python set exactly equals `logs/turn3-black-paths.txt`: **60 paths,24 production/36 tests/helpers**, no missing/extra paths. No src/tests Python mtime is later than confirm-full.started. This corroborates receipt reuse; no immutable full-source hash snapshot was supplied, so timestamps are not represented as cryptographic provenance.

| Existing receipt under logs/ | Verified result |
|---|---|
| turn3-confirm-full.command/.exit/.log/.started/.finished | Exact **make test PYTEST_WORKERS=6**, exit0; **12272 passed,1272 warnings,516.00s**;10:16:46Z–10:25:24Z November3. No execution skips/failures reported. Historical12269 superseded. |
| turn3-repeat-1/2/3.command/.exit/.log | Each exact complete three-file command: `poetry run pytest tests/tui/test_composer_transcript_identity.py tests/tui/test_chat_transcript_precise_scroll.py tests/tui/test_herdr_all_owner_cutoffs.py -n 6 -m 'not e2e' -q`; each exit0,47passed40warnings;54.04/53.56/55.73s. |
| turn3-affected.command/.exit/.log | Complete TUI+messaging plus CLI app/dispatch,6workers/not e2e; exit0,3439passed541warnings,262.00s. |
| turn3-final-focused.exit/.log | exit0,209passed79warnings,65.40s. Full selected14-file command is in turn3-repair.md; no separate .command exists for this receipt, so command attribution is the author report rather than a command sidecar. |
| turn3-confirm-lint.exit/.log | make lint → mypy src/ tests/,exit0,981files clean. |
| turn3-confirm-black.exit/.log | exit0,60files unchanged; cumulative manifest reconciled above. |
| turn3-confirm-diff and confirm-coreutils .exit/.log | Both exit0,empty logs. |

No ceremonial full rerun. Reviewer ran read-only `git diff --check` (exit0) and post-probe `dpkg -V coreutils` (exit0,empty). Earlier interrupted/failing receipts remain historical; none promoted to pass.

### Exact21 exclusion scope — independently enumerated

Reviewer ran **collection only**, not e2e execution: `poetry run pytest --collect-only -m e2e -q -p no:cacheprovider`, approved synthetic environment; **exit0,21/12293 collected,12272 deselected,2 dependency warnings,3.91s**. Makefile/pyproject/e2e files are unchanged. Inverting the project's `not e2e` selection identifies precisely these21 nodes:

1. `tests/agents/slo_agent/orchestrator/test_dev_agent_launch.py::test_development_descendant_imports_running_source`
2–3. `tests/cli/test_hosted_installer_smoke.py::test_direct_pipx_regeneration_recovers_through_packaged_finalizer[pip|uv]`
4. Same file `::test_hosted_installer_installs_and_runs_the_tagged_product`
5. `tests/cli/test_install_mirror_e2e.py::test_real_pipx_install_and_update_during_gitlab_outage`
6. `tests/cli/test_install_smoke.py::test_requested_e2e_fails_when_docker_is_unavailable`
7–10. Same file `::test_installer_bootstraps_and_finalises_shell_environment[ubuntu:22.04|ubuntu:24.04|debian:12|debian:13]`
11. Same file `::test_macos_runner_contract_requires_a_real_macos_host`
12. `tests/cli/test_wheel_contents.py::TestWheelShipsSkills::test_wheel_contains_every_authored_skill_file_in_current_snapshot`
13. Same file `::TestWheelShipsSkills::test_wheel_contains_the_workflow_entry_points`
14. Same file `::TestWheelShipsBundledPlugins::test_wheel_contains_the_bundled_bash_live_output_payload`
15. Same file `::TestWheelConsoleScripts::test_wheel_declares_slo_and_slo_entry`
16. Same file `::TestWheelConsoleScripts::test_local_pipx_install_generates_two_unwrapped_console_scripts`
17. Same file `::TestWheelShipsInstaller::test_wheel_contains_install_sh_at_its_root`
18. `tests/integrations/openrouter/test_live_openrouter.py::test_live_harness_when_disabled_rejects_before_credential_resolution_or_network`
19. Same file `::test_live_harness_when_fixture_discovery_is_enabled_uses_synthetic_resolver_and_safe_output`
20. Same file `::test_live_harness_when_paid_fixture_mode_is_enabled_sets_documented_bounds`
21. `tests/tui/authentication/test_authentication_device_e2e.py::test_live_openai_device_authorization_paints_instructions_then_cancels`

These remain unexecuted by this review, not passing/skipped execution claims. No extra feature exclusion or waiver.

### Warnings disposition

Read the current confirm-full warning section. It contains pythonjsonlogger relocation, LangGraph serializer pending deprecation, LangGraph instance model_fields deprecation and provider model_kwargs UserWarnings. RuntimeWarning groups now include CLI dispatcher and a later integration GC site; do not copy the older report's four-warning count or attribution as current fact.

A bounded allocation probe was justified to distinguish a concrete new lifecycle regression from GC attribution: **`PYTHONTRACEMALLOC=5 poetry run pytest tests/cli/test_typer_dispatch.py -q -p no:cacheprovider`**, same approved synthetic environment, **exit0,38passed3warnings,18.80s**, plus a post-summary GC RuntimeWarning. Allocation stacks identify test `_run_headless_capture_config` / `_capture_config` → `TyperDispatch.run_headless:344` → `runner.invoke` AsyncMock. Those helpers patch `asyncio.run` to return0, so the created coroutine is not consumed. HEAD source at the same helpers already contains that AsyncMock-plus-patched-run combination; current changes add typing/true-flag assertions, not the coroutine ownership pattern.

**Disposition:** the reproduced allocation mechanism is historical test-harness behavior, not evidence that the real messaging scheduler leaks. This does not identify every allocation in the parallel full run or certify all1272 warnings harmless/baseline-equivalent. Under unchanged passing warning policy, no concrete new production regression is established by these warnings; no warning suppression, package change or unrelated cleanup is required. Warning limitations remain explicit, separate from AGG-01/02.

## Complete applicable hard-rule/checklist verdict

| Checklist family | Aggregate verdict |
|---|---|
| §1.1 explicit signatures / truthful returns / specific containers | Eight repaired recorders and new protocol/component seams typed. AST changed-signature scan found no remaining missing parameter/return annotations. **FAIL keyword calls: AGG-02.** Native positional-only and variadic APIs are not findings. |
| §1.2 documentation / schema | Lifecycle contracts explain ownership/order; **FAIL new schema descriptions: AGG-01**. The literal-input test docstring is misleading but assertions are correct; nonblocking wording note, not a new behavior mandate. |
| §1.3 declarative / Tell Don't Ask | Existing owners retained; session owns execution/consent, queue mutex owns cutoff, store owns transactions/digest, component owns draft revision/adoption, host owns specified bridge/lifecycle presentation. Python specialization treats ~8 lines as a cohesion signal, not mechanical quota. No new service/wrapper framework required. |
| §1.4 canonical vocabulary | Original message_id/target/generation/principal/draft_revision/receipt/handoff terminology preserved across boundaries. No new naming migration. |
| §1.5 test-first / evidence / doubles | Author chronology distinguishes real sealed-cancel RED, seam TypeError RED and assertion-only evidence; no invented eager RED. Real SQLite/files/history/Pilot/provider substitutes; new acquisition/receiver seams injected. Existing historical harness patches not expanded. Original assertions retained; current full and repeats pass. |
| §2 backend | Pydantic boundary rule applicable as above. FastAPI namespace/envelopes, ORM trio/migrations, DBOS/workers absent from changed stack; not imposed. Existing session facade is not a newly introduced `_app_service.py`. |
| §3 Vue/SSE | Not applicable. |
| §4 CLI | Product Typer parse→dispatch→host/runner separation preserved. Typed construction/defaults checked, logging isolation retained. No new operator-facing verb/Make/env mapping obligation or HTTP CLI platform. |
| §5 Textual | Semantic messages, typed commands, existing projector/TCSS geometry and tracked/joined tasks preserved. Original specs expressly assign host bridge responsibilities and create_task lifetimes; generic run_worker wording does not require replacing these owners. Production test-only outcome/failure hooks removed. |
| §6 graph | No graph topology/node/gateway change; source binding extends existing agent lifecycle. Existing ASCII left untouched. |
| §7 ownership/review | One SQLite/history writer and scheduler; no copied model/table, no migration. Complete original-row and stable-finding aggregation above; directory/read-model SQL rules not relevant. |
| §8 findings/report | Finite sourced blockers, severity, exact paths, correction/closure, evidence and limitations supplied. No optional preference promoted to product scope. |

Cumulative hard-rule conclusion is **FAIL**, not blanket compliance: AGG-01/02 must close. Partition ownership/correctness audits are reused within their verified scope; all eight changed repair boundaries were re-reviewed. No unbounded new audit or speculative refactor is handed back.

## Guidance loaded and scope

Installed root exactly `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Read actual exact workflow/shared workflow, engineering routing/testing/ownership/review, feature-review including post-hook, full1107-line Python hard checklist; generic solution-design/coding-rules/naming/test-verification/code-design/declarative/cadence; Python root/types/docstrings/declarative/imports, full application/domain build and application/domain/graph test recipes; full Textual and Typer product CLI/module recipes; installed INDEX (including recovered tail after64KB truncation). Manifest has no applicable personal override. Build-clients excluded: this feature changes an in-process messaging protocol, not a third-party HTTP/SDK wrapper. No Command class/new CLI verb/ORM/HTTP/worker framework invented. Shared test-verification policy controls obsolete mock-heavy recipe examples; project synthetic environment supersedes unrelated PostgreSQL/local-env examples.

Read current SLO, README opening/runtime feature hunk/style/testing, routing/handoff/current ledger plus historical entries as needed; KB Welcome→slo README/gotchas and checked runtime-chain entry. Root/docs RESEARCH absent; not recreated. User's explicit report destination overrides historical KB-only report guidance. No claim of reading every unrelated README/KB chapter or every installed recipe.

## Preservation and next gate

Current README diff is one feature hunk at1678: durable runtime/commands/normal-only capability/default flags/upgrade-rollback and legacy qualification, within DC09 scope. SLO workflow-budget edit and preexisting docs remain unrelated and untouched.60-path Python manifest is an inventory, not stage authorization. Evidence directory is not a blanket commit payload.

- [ ] **Must-fix code documentation:** AGG-01 four Field descriptions, preserving schema semantics.
- [ ] **Must-fix test convention:** AGG-02 nineteen keyword decorator calls, preserving exact collection/assertions.
- [ ] **Required verification:** affected checks and final gates on revised content, then independent affected re-review; reuse unchanged original maps and this completed legacy/exclusion audit.
- [ ] **Completion:** separate independent completion after accepted review. Only then may separately authorized local commit proceed.
- [x] **Product decisions:** none needed; no deferrals/waivers requested.
- [x] **Warning disposition:** passing policy acknowledged without false harmlessness; reproduced origin traced; no unrelated cleanup requirement.
