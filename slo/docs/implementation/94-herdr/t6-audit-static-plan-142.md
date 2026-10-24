# T6 mounted author audit and exact static plan — 142

## Verdict

**INCOMPLETE: mounted author read closure is not complete. Static remediation PLAN delivered; static acceptance remains RED.** No independent review or whole-feature approval is claimed. Do not demote the retained READY135 privacy or READY64 ownership evidence merely because this audit is incomplete; equally, do not promote this audit into READY using those authors' ingestion claims.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 142, retries 0. Unlimited turns and dispatches supersede old limits. No agents dispatched. Production/tests were not edited. Writes are this report and `t6-audit-static-plan-142-receipts/`; no shared status/spec/KB/other-worktree/global changes, installs, live calls or git mutation. One unnecessary scratch copy of root RESEARCH was written to `/tmp/t142-research-read` during initial retrieval; this is disclosed rather than represented as an authorized report receipt. Tool-generated truncation spills also exist. No source was copied into another worktree or executed from a scratch tree.

## Fresh evidence

Cwd `/root/Code/slo-94-herdr-integration/slo`; approved `/root/.pyenv/versions/slo-harness/bin/python` reports Python 3.11.7. Inspected Makefile, pyproject dependencies/checker settings, guarded wrapper, root fixture and state-isolation entry. No development environment sourced.

Executed **`PYENV_VERSION=slo-harness make lint`**. `lint.log` and `lint.exit` in the receipt directory retain output and exit **2** (mypy child exit 1):

> Found 281 errors in 58 files (checked 801 source files)

`exact-errors.txt` preserves all 281 diagnostics, original file/line/message/code, grouped by file. No deduplication, line-number normalization or baseline waiver. Seven production files account for 10 diagnostics; 51 test files account for 271. No Herdr-specific source diagnostic appears. This is fresh execution, not repetition of 121's 295/60 baseline. No pytest/full make test was run; two-process HOLD respected. Prior test counts below are retained evidence, not fresh runs.

## Mounted journey interpretation — no invented extra scenario

Canonical root H is `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr` (read-only). H/tasks.md T6 acceptance, lines 255–264, says:

> Actual PromptInput → Faux tool/retry/pool fallback → usage/idle, rename/model/new, attached and detached typed viewer requests

C section 8 separately requires real session submission scope across tool/retry attempts and a pool fallback snapshot fixture. D section 8 requires the functional PromptInput/configuration/viewer journey. These passages do **not** require retry and fallback sequentially inside a single app instance. Separate parameterized complete journeys meet that structural allocation; requiring a combined seventh scenario would invent scope. This conclusion is bounded to the directly inspected passages, not a claim of full canonical-family ingestion.

Directly read `test_herdr_full_flow.py:236–408,1427–end` and all `herdr_unified_141.py`. Six cases are `single/retry/fallback × successful/uncertain second split`. Each calls the existing prompt implementation and invokes its continuation **inside the same `app.run_test()` context**. The continuation opens both public viewer routes, then Pilot rename/model/new. The detached parent is another persisted session, not another mounted app or a real workflow child. Provider failure is pre-output injection into Faux; real retry/pool policy handles it. Assertions require one user message/tool result/completion, totals 8, configured pool distinct from routed fallback, exact private record/generation, immutable old revisions, release before successor claim, old history preserved and successor totals unknown. Both viewer routes assert exact parent argv and no duplicate attempt after uncertainty. Queue submission is not paint.

Retained 141 evidence: final surrounding selection 248 passed; post-final six-case focus plus 62 foundation tests 68 passed. Retained 135: 289-pass privacy selection, publication capture before coalescing, both mounted destination routes. Retained 140: exact 64 unique final matrix IDs, 44 separate G1/G2/all-owner/platform cases, 92 safe initialization/registration surrounds. Counts overlap and must not be summed. Their receipt files were not exhaustively revalidated here.

## Requirement/AC navigation map (not a completed coverage certification)

The following names point to actual repository test files; a mapped file is not proof that every assertion or branch has been read or freshly run. `Htests` abbreviates `tests/agents/slo_agent/herdr/`, `Ttests` is `tests/tui/`.

| Requirement | Actual evidence destination | Remaining qualification |
|---|---|---|
| R1 optional/nonblocking | full_flow `test_prompt_tool_usage_completes_while_report_cli_is_stalled`, `test_inactive_prompt_has_zero_integration_attempts`; Htests gate/diagnostic suites | Single route holds real CLI barrier; retry/fallback are unstalled variants |
| R2 product/panes | unified helper `open_both`; docs INSTALL | Actual pane/paint live acceptance pending; editor redesign excluded |
| R3 private handoff | Htests/test_session_publication.py, test_session_capture.py, test_save_worker_closure.py | Owner/source read closure outstanding |
| R4 config versus display generation | test_session_mutation.py, test_session_publication_compositions.py; unified `assert_saved` | Full branch audit outstanding |
| R5 G1 newest usage | test_session_publication_compositions.py::test_real_session_save_barrier_latest_publication | Retained 140 separate two cases |
| R6 immutability/bounds | test_daos.py, test_session_capture.py, test_save_worker_closure.py | Not re-audited here |
| R7 privacy | full_flow labels, reporter-lifetime credentials, tool-error parity, both viewer privacy nodes | READY135 retained; no global-redactor claim |
| R8 exact restore | unified `assert_advertised/assert_saved`; Htests/test_restore*.py; tests/cli/test_herdr_restore.py | **Two-process positive restore HOLD**, not replaced by same-process records |
| R9 uncertainty/drain | test_final_lifetime_closure.py, test_reporter_final_drain.py; Ttests/test_herdr_all_owner_cutoffs.py | Persistent retention separate from 64 draining rows |
| R10 post-lock admission | test_cli_transport.py, test_viewer_authority_closure.py | Source atomic-section closure pending |
| R11 stale effects/cancel | test_policy_accounting_closure.py, test_transport_lifetime.py, test_visualizer_lifecycle.py; lifetime matrix | No full-family approval inferred |
| R12 all operation families | test_batch_failures.py, test_restore_batch_closure.py, test_reporter_shutdown_closure.py | Exact branch ledger still to reconcile |
| R13 G2 | test_reporter.py::test_viewer_lock_waiter_superseded_report_never_spawns | Retained 140 eight distinct cases |
| R14 lifecycle/attention | full_flow prompt node; test_attention_*; test_session_attention.py | Unified run is not all attention coverage |
| R15 child environment | tests/scheduling/test_runtime_helpers.py; tests/cli/test_headless_exclusions.py; orchestrator/test_spawn_env.py | Source/negative-path audit pending |
| R16 identity compatibility | test_session_identity.py; tests/cli/test_herdr_restore.py; Htests/test_resume_bounds.py | Ordinary slug policy remains separate |
| R17 provenance | orchestrator/test_bootstrap.py; Htests/test_session_capture.py | Tool-name equality alone not proof |
| R18 destination/one shot | full_flow six cases and destination privacy; Htests/test_visualizer*.py; Ttests/test_visualizer_launcher.py | Live manual reuse/paint pending |
| R19 single context parser | orchestrator/test_context_reader.py; Ttests/test_workflow_visualizer_loader.py | Consolidation source audit pending |
| R20 replacement/inbox | tests/integration/test_herdr_lifetime_matrix.py; Ttests/test_herdr_all_owner_cutoffs.py, test_herdr_prompt_registration.py, test_herdr_initialization.py | READY64 retained; separate quarantine/inbox races required |
| R21 numeric limits | Htests/test_projection.py, test_sequence_store.py, test_restore_boundaries.py, test_resume_bounds.py | Full boundary assertion read outstanding |
| R22 conventions/all gates | Fresh lint receipt, 121 docs; required full regression/Black | **Static RED; full gate HOLD** |
| R23 preserve scope | Read-only production/tests in this lane | Initial scratch-copy deviation disclosed above |
| R24 no implementation/live/external action | This report-only task | No code authorization exercised |
| R25 independent verification | Accepted H/review-evidence/independent-review-turn4.md | Spec acceptance only; independent implementation review outstanding |
| R26 editor redesign | Intentionally excluded | No new visual/input scope |

AC allocation: B1→R1, B2→R9/R11, B3→R21, B4→R4/R12 plus full_flow `test_actual_session_unknown_usage_explicitly_clears_before_patch`, B5→`test_token_format.py`, B6→R7, B7→offline/live separation. C1→R3/R14, C2→R1/R9 and headless parity, C3→R8/R16/R17, C4→R20, C5→R20 final registration/claim disposition, C6→full_flow `test_enabled_disabled_outside_exact_ordered_parity`. D1→R18/R19, D2→R18, D3→R9/R11, D4→full/static plus separate live, D5→live pane acceptance only. This is a navigation/delegation map, not a falsely completed assertion audit.

## All 72 sample delegations

Read H/review-evidence/task-sample-inventory.md and exact T6 attachment. Preserve canonical allocation without copying snippets into duplicate classes:

| Task | Complete sample IDs | Source-read / implementation owner plan |
|---|---|---|
| T1 | B01,B03,B07,B23,C27 | DAO/gate/formatter/identity/sequence plus isolation fixtures; inspect originals and actual validators/guards |
| T2 | B04,B06,B08–B22,B24,B25,C28,C29 | service/reporter/transport/sequence; read all ticket, save and drain continuations as one owner |
| T3 | C03,C05,C06,C07,I04 | restore and CLI admission; I04 historical only; process acceptance remains held |
| T4 | D04–D07 | visualizer/context reader/shared transport admission; no new parser or automatic recovery |
| T5 | B02,B05,C01,C02,C04,C08–C26,C30,D01–D03,D08,I02,I03 | session/bootstrap/headless/scheduler/app/workflow service/renderer; I02/I03 historical only |
| T6 | B26,C31,D09,O01–O03 | exact chapter gates and owner/flow/pane diagrams; full test held, lint now failed, live separate |

This accounts for 72 allocated IDs (69 current + three historical). Ten exclusions remain I01,I05–I08,P01–P04,R01 with canonical reasons, not omitted work to revive. No fresh hash/fence equivalence validation was executed. All sample bodies and surrounding chapter prose still need the finite source-read closure listed below; inventory reading is not full sample ingestion.

## Five nonoverlapping static partitions

`receipts/partitions.md` enumerates **every one of the 58 files**, diagnostic counts/codes and explicit scoped mypy commands. Matching `*.files` and `*.tests` contain exact paths, not directory globs. They partition all 281 errors once:

| Partition | Errors/files | Intended correction |
|---|---:|---|
| A-projector | 81 / 4 | Three fake contracts + actual nullable partial-update boundary |
| B-fixtures | 53 / 5 | Compaction result/store, OAuth keyword factory and timeout fixtures |
| C-provider | 45 / 11 | Faux/SDK declarations and provider test narrowing |
| D-local-types | 101 / 37 | Local annotations, explicit arguments, narrowing and scoped test patches |
| E-yaml | 1 / 1 | Missing third-party typing dependency; separate permission |

These are sequential ownership partitions, **not dispatched agents** or permission to edit during this read-only task. Each file stays with one owner. Additional regression files may be read/run across partitions without competing writes.

### A — fix the real contracts, not 80 call sites

Inspected `TranscriptMountHost`, FakeHost/FakeToolBlock/FakeAssistantBlock and partial/recovery fake implementations. The host requires optional tool names; FakeHost and _PartialHost incorrectly require str. Recovery fake additionally lacks thinking mount, `before` keyword compatibility and bool separator result. Correct the complete signatures once. Return real widget instances or initialized recording subclasses with compatible properties; do not merely annotate duck objects as widgets or skip base initialization to silence the checker. Keep per-test mount order, seal/finalize and result assertions. Partial tests must narrow the retrieved block to `_PartialRecordingToolBlock` before reading `partials`; do not narrow a mutable base dictionary covariantly.

`src/tui/transcript_projector.py:340` can pass None into required `ToolOutputUpdateDAO.tool_name`. This is not fixed by an assert invented from typing. Add an early partial event with both names absent as RED; choose and test the existing unknown-name display semantics (the block explicitly supports None). Either an existing supported empty-string representation or a boundary-model change needs contract evidence before selection. No unrelated rendering redesign.

Tests: exact A `.tests` list, plus `tests/tui/test_replay_resume.py`, `tests/tui/test_tool_execution_block.py` if that path exists (resolve actual widget test filename before executing), and explicit mounted full_flow node after change. Do not use `tests/integration/` discovery.

### B — replace incomplete test doubles, preserve timing semantics

Compaction updater consumes a concrete CompactionResult and the full store protocol. Current `_CompactionResult` is only a stand-in and `_InMemoryStore` implements append only. Use the real CompactionResult (import does not itself justify a network call) and a test-owned protocol-complete store with explicit unsupported operations raising, or reuse an existing complete fixture. Preserve exactly one append, envelope and metadata assertions. Do not enlarge production API solely to satisfy an incomplete fake. This is 27 diagnostics from two causes, not 27 behavioral changes.

`test_auth_screen.py:98` calls a positional Callable with six named keywords. Define a local callable Protocol with exactly `provider/login_method/browser_present/device_present/receiver/callback_unavailable`; retain existing factory's public OAuthFactory signature. Replace the function with dynamically attached capability in headless auth tests by an instance implementing both `__call__` and `supported_login_methods`. Narrow actual screen/widget types; give the intentional raising function the true keyword signature. For the local aiohttp socket helper, narrow to the actual asyncio Server before reading sockets and assert nonempty sockets; do not pretend AbstractServer always has them.

`test_oauth_flow.py:381,396,414` passes fractional timeout to int-only signatures. Source currently stores supplied values via `value or int(env)` and uses them as timeouts: annotation-only float acceptance may be truthful, but requires checking every consumer and preserving zero/default behavior. Alternative: inject a timeout boundary while keeping deadline/cancel coverage, not slower sleeps. If changing production timeout annotations, add `src/auth/oauth_flow.py` exclusively to B's write set after scope approval; it is not one of the current diagnostic files. Do not change auth behavior under mechanical-maintenance cover.

### C — exact SDK/fake boundaries

- `faux.py:73` custom Pydantic queue kwargs are rejected by the BaseChatModel typed constructor. Use properly declared default factories followed by typed owned queue initialization, preserving non-shared queues, chunk alignment, clone semantics and underrun. Do not route fields through an untyped dict just to evade checking.
- `bind_tools` must accept the actual upstream tool input union and keyword-only tool_choice; match upstream signature and preserve captured values/clone behavior. Update `bound_tools` truthfully, not to bare Any. Test callable, schema/class and BaseTool forms plus tool_choice and existing streamed scripts. Broader input annotation is not a new production provider feature.
- `assistant_chunk_normalizer.py:327–343` only reads raw tool mappings. `list[Mapping[str, object]]` (including the TypedDict ToolCall) is a truthful candidate; check `_stringify_tool_arguments` boundary and both chunk/fallback forms. No new coercion.
- `openai_codex.py:179–181`: candidate `base_url=` alias and `SecretStr(cred.access_token)`. Before edit inspect pinned ChatOpenAI field aliases/constructor, then capture exact offline request URL, Authorization and account/session headers, Responses body and no-retry behavior. A local Protocol is useful for injected clients/callables, **not** for falsely declaring constructor parameters accepted or hiding SDK mismatches.
- `anthropic_claude_code.py:251` reads undeclared `self.kwargs`; the class has no bind_tools override in this source. It is unsafe to add a fictional annotation. Reproduce absent tools, present tools and real RunnableBinding request paths offline; locate actual kwargs ownership. Any relocation of tool-name normalization must preserve current canonical names, no replay/global mutable bound-tool state. This is a genuine semantic investigation, not a mechanical cast.
- Provider tests: assert actual ChatOpenAI/ChatAnthropic/Faux/AIMessage/RunnableBinding types before model-specific reads; retain Mapping for kwargs, list[BaseMessage] for invariant message inputs; scoped patch.object for method replacement; explicit exception subclass carrying headers instead of assigning arbitrary attributes to RuntimeError.

Run C `.tests` plus existing offline Codex wire/Anthropic binding/normalizer tests resolved by filename; never enable e2e or real credentials. Full Faux consumers need later full regression after HOLD lifts.

### D — finite local repairs, no runtime redesign

Every file/error is listed in `partitions.md` and `exact-errors.txt`. Apply these concrete operations at those listed coordinates:

1. `registry.py:209`: assign `kind: Literal['skill','workflow']` via explicit literal branches preserving unknown fallback; test skill/workflow/invalid kind.
2. Three OpenRouter race fixture files: replace `function: object,*args: object,**kwargs: object` wrappers around to_thread with `Callable[P,R]`, `P.args/P.kwargs`, return R; retain held-result ordering. Do not use callable(object) as fake proof of its argument signature. Explicit result type follows R.
3. Catalog store lock fixture: use a local flock Protocol with exact used signature or retain a typed module reference; no `object.flock`. Budget evidence asserts capabilities non-None.
4. History/tree/read/default-orchestrator/workflow/startup/pending/picker/plugin tests: assert expected object/non-None/text shape before access. Tool-name sets must assert names are strings rather than silently filtering missing names. Schema tests narrow `args_schema` to a Pydantic model class and description to non-None before access. AST test asserts Lambda.body/return expression exists before ast.Expression construction.
5. `test_pool_fallback_e2e.py:246`: return `SessionHistoryStoreProtocol`, the actual session accessor contract; import missing AgentStreamEventDAO at 452. Do not assert concrete flat-store identity for the tree wrapper.
6. `test_agent_runtime_event.py:20`: `Callable[[AgentRuntimeEventDAO], Awaitable[None]]`, preserving async factory. `test_agent_recovery.py` fake subclasses: explicitly forward `responses` in their constructors rather than suppressing call-arg diagnostics. `test_refresh_catalog_notice.py:90`: exact refresh-status Literal type. CLI terminal lifetime: StreamEventKind and `ContextVar[CredentialDAO | None]`.
7. `test_harness_contract.py:138,144`: explicit named invoke_fixture arguments (or precise TypedDict), not `dict[str,object]` splat. `test_live_openrouter.py` gets AIMessage narrowing only; **do not run its paid/live tests**. Static checking includes e2e files; verification does not authorize e2e execution.
8. Image/executor/nonstream tests: assert list then dict content shape before string-key indexing. Cache-control tests narrow SystemMessage. No string conversion that erases payload structure.
9. Scoped monkeypatch/patch.object for pool/manual-compaction method assignment; assert recorded mock call exists before kwargs. Keep exact ordering/failure expectations.
10. Capture/relaunch fixtures: use real temp-owned binary IO objects and `Task[IO[bytes]]`, or a truthful narrow IO consumer seam only after full caller audit. `object.fileno` is not a contract. Preserve retained descriptor/reap checks; do not touch the held Herdr process harness.
11. Selection/renderable tests: narrow Content/Text according to actual renderer, normalize Binding tuples using the existing Binding facility, use distinct variables for answer/thinking/user/focus widget types, and subclass Vertical for the raw-copy method fixture. No production selection behavior changes. Narrow the selection observer's optional state before reading `was_following`.

### E — genuinely blocked by current no-install permission

Fresh error is `src/agents/slo_agent/skills/service.py:13` import-untyped yaml. pyproject declares runtime PyYAML but no types-PyYAML dev dependency. Adding an import ignore, cast, Any, checker exclusion or fictitious local YAML stub would not be truthful acceptance.

Preferred explicit request: **authorize adding a pinned compatible `types-PyYAML` development dependency and updating only pyproject.toml/poetry.lock, then installing that declared stub into the existing approved slo-harness environment through the machine-guardian approval process; no global/pipx/system changes or runtime dependency upgrade.** Exact version must be selected against the lock, not invented here. This permission has not been granted. If no environment installation is permitted, an independently justified vendored upstream typing package with provenance/configuration would need a separate repository scope decision; it is not silently substituted now.

The all-gates feature mandate supports small truthful gate-enabling declaration/test-fake maintenance in a later coding lane; it is not blanket permission for unrelated provider/auth semantics. Request **bounded offline correction authorization only if reproductions show a real behavioral change is necessary** for Anthropic bound-tool lookup, nullable partial tool names, or OAuth timeout semantics. Codex alias/SecretStr can be treated as mechanical only after pinned-SDK and wire equivalence proof. No mandatory massive refactor has been demonstrated. At least the YAML dependency/environment decision blocks final static acceptance under the present restrictions; other semantic blockers are candidates requiring proof, not established excuses to stop all authorized work.

## Verification plan for the partitions

For each small increment: retain current exact mypy RED → add behavioral regression where behavior changes → smallest correction → whole affected module → scoped mypy → Black check. Never implement an entire partition before testing. No ignores, hidden casts, assert deletion, skips or new Any escape hatches.

From application root, after reviewing each selected module's safety:

```bash
export PYENV_VERSION=slo-harness
R=docs/implementation/94-herdr/t6-audit-static-plan-142-receipts
# Replace A-projector with the one partition being repaired.
mapfile -t FILES < "$R/A-projector.files"
mapfile -t TESTS < "$R/A-projector.tests"
poetry run mypy --follow-imports=silent "${FILES[@]}"
bash docs/implementation/94-herdr/t1-dao-check.sh "${TESTS[@]}"
dpkg -V coreutils
poetry run black --check "${FILES[@]}"
```

The wrapper prepends 62 foundation tests; report counts honestly. D's live module is static-only unless its non-e2e collection has been explicitly checked; do not change markers or turn on paid modes. Scoped `--follow-imports=silent` does not replace final **`make lint`**. After explicit process HOLD release only: exact B26/C31/D09 gates, make test, make smoke, make lint, changed-file Black, binary integrity, independent implementation review and fresh completion. While HOLD persists, no full make test or integration-directory collection.

## Finite outstanding read closure

Fully visible in this audit: shared engineering routing/ownership/testing, coding rules/test-loop, Python gateway; frozen routing/scope-plan/assessment; 141 report, 135 privacy and 140 matrix reports, 121 static report (some initial bulk output truncated, later relevant portions consulted); accepted spec review turn4; sample inventory; exact T6 normative/attachments; C8–10 and matrix paragraph, D late test/manual/AC sections. Actual source inspection covered the unified helper/prompt body, named static boundaries and fake owners above. Supplied AGENTS/CLAUDE/docs RESEARCH were consulted. KB Welcome/gotchas were visible; actual slo README was **not** consumed. Root RESEARCH copy-to-file is **not reading**.

Before author READY, consume in bounded, untruncated reads: root RESEARCH; actual KB slo/README; remaining selected shared/Python declarative/Faux/Textual/style/workflow prerequisites; full canonical overview and B/C/D relevant ledgers/sample prose; current source continuations in session publication/capture/activation/close, app registration/replacement/inbox/unmount/viewer workers, reporter save/admission/ack/drain, transport, restore/viewer/context reader and service/renderer/launcher; full full_flow/privacy/parity/matrix assertion bodies and safe fixture continuations. Reconcile each requirement/AC with actual assertions, not filenames, and verify retained receipts against current bytes. This task has not done that complete finite audit. No arbitrary dispatch cap or claimed independent-review gate caused the incomplete verdict.

Distinct remaining outcomes: (1) mounted author read/audit closure **INCOMPLETE**, (2) two-process positive acceptance **HOLD**, (3) full static **RED 281/58**, (4) complete post-edit full regression **not run/HOLD**, (5) live disposable named-session version/restart/pane/paint acceptance **unauthorized and unproven**, (6) independent implementation review/completion **pending**. None substitutes for another.
