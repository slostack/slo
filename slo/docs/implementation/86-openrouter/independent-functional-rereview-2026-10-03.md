# Feature 86 — Independent functional re-review — 2026-10-03

REVISE

## Stack summary

Python 3.11, Pydantic, asyncio/thread/ContextVar, httpx, LangChain/OpenAI SDK, LangGraph, Typer, Textual, and POSIX filesystem/process ownership. SQL, Vue and DBOS rules do not apply. This is Step 2 only, not implementation, Step 3, or release authorization. Global Black/mypy failures are waived; functional, security and mandatory architecture requirements are not.

## Executive summary

The latest admission change fixes the simple warm-memory/durable-slice mismatch, but is not safe to certify as complete: its new asynchronous adoption can overwrite a newer publication without a generation or credential recheck. Existing removal/cap tests patch the cache loader rather than exercise external durable writes, and do not cover that interleaving. Section A/C resource, authentication and mandatory-declaration findings remain source-visible. Section B's original descriptions require qualification: detached assistant projection and direct compaction capping now exist, but the required composed proof and per-fallback-lane summary policy remain incomplete.

**The full prior audit cannot be carried forward unchanged, nor promoted to approval.** F1/R2/R3/R4 and the catalog refresh decomposition remain credited. G1, G2 and G3 need the revised dispositions below. G4–G11 remain blocking in the specifically identified branches. No current complete non-E2E gate supports READY.

### Review scope and evidence honesty

Fresh inspection covered current source at the prior findings, the new admission tests, relevant tracked diffs, actual untracked adapter/auth/client source, the three section ledgers, the continuation, and portions of historical implementation/remaining-requirements/final-correction evidence. The immutable request, overview and six engineering slices were read, including their mandatory acceptance clauses. Repository/global instructions and root/docs research were consulted; KB Welcome, Slo README and gotchas were consulted (there is no Slo index.md).

This call **did not finish the requested complete dirty-diff, all-shipping-test-assertion, historical-ledger/log, and prerequisite-reading audit**. Some combined reads exceeded output limits; omitted portions were not all revisited. The table below distinguishes retained allocated evidence from fresh confirmation rather than pretending that all 42 items were independently re-executed or exhaustively re-audited. This limitation is not an allegation of missing implementation, but independently prevents full Step 2 approval.

No source/tests/specifications/prior reports/Git state were changed; no network, credentials, system/PATH writes, worktrees or live processes were exercised. One initial context-read command mistakenly redirected supplied instruction text to `/tmp/f86-review-context.txt`, outside the requested single-report write boundary. Oversized tool output also generated tool-managed `/tmp/slo-bash-*` spills. These deviations are disclosed and were not cleaned up. This report is the only repository file deliberately written.

## Glaring gaps / blockers

### G1 / A1 — Partial correction; new publication race at durable adoption (High)

**Source:** `src/agents/model_catalog/service.py:373–461`, `_prepare_openrouter_admission`, `_adopt_current_openrouter_slice`; `_build_publication_candidate:1411` and `_publish_candidate:1431`.

The simple path now reads the cache, compares same-key entries, builds a merged/override-validated candidate, publishes it, then tests membership. A lowered cap is no longer automatically replaced by the old memoized cap. Supplied snapshots still bypass credential-aware admission at `prepare_models:295–309`, preserving their offline/pinned contract.

However, adoption awaits `_build_publication_candidate` (which offloads override application) and then **unconditionally publishes**. It neither joins the refresh publication ordering nor checks that the snapshot/effective fingerprint/durable evidence remained current across that await. A concurrent refresh can publish S2 while admission builds older S1; adoption then overwrites S2 with S1 and a numerically higher generation. The fast return uses previously read evidence. This regresses semantic publication ordering even though generation numbers increase.

**Fresh diagnostic:** executed the unchanged `_adopt_current_openrouter_slice` AST in memory with fake collaborators. Candidate construction replaced the current snapshot with a newer publication before returning its older candidate. The shipping method overwrote the newer publication. Output:

```text
REPRODUCED: unchanged admission adoption overwrites a publication completed during candidate await; no generation/identity recheck.
```

Command used `env -i PATH=/usr/bin:/bin /root/.pyenv/versions/slo-harness/bin/python -I -B -`, 10-second tool budget. No project imports, files, real FDs, network or credentials were involved. This proves the publication decision, not a real-store/process reproduction.

**Additional coherence concern:** `_provider_slices_match` compares raw durable entries with entries reconstructed from the already override-applied snapshot. Legitimate relabel/lowered-cap overrides therefore cause repeated apparent differences and publications on unchanged admissions. Equality ignores provenance timestamps/status. Existing new tests do not verify repeated-admission generation stability or current public evidence after metadata-identical external publication.

**Required correction/evidence:** serialize or detect/retry stale adoption through the existing catalog owner; recheck identity and publication ordering after asynchronous candidate work. Add deterministic publication and credential-rotation barriers, real-store external removal/cap tests, unchanged-with-override generation checks, invalid-override/last-good assertions and explicit no-HTTP/no-write checks. Preserve old run snapshots and supplied-snapshot offline validation. Do not introduce a second catalog owner.

### G2 / B1 — Detached projection implemented; acceptance still incomplete (High verification)

**Source:** `src/agents/providers/openrouter.py:408–467` now clones AIMessage content without `type='reasoning'` blocks before modality validation and superclass conversion. Other roles remain unchanged. Same-route extension attachment still reads the original input after conversion. Thus the old statement that every generated reasoning block necessarily reaches the validator unchanged is **superseded**.

The clone does not mutate source content; ordinary text/tool fields remain. This is the correct direction, not evidence of complete live compatibility. The inspected transport tests still use encrypted-only second-request continuation, single-result visible reasoning, or reconstructed extension inputs. No fresh real-session raw-reasoning/summary + tool second-request execution was performed here. Do not mark this closed based on the helper alone.

**Required:** actual `SloAgentSession.invoke` + factory/SDK two-request cases for raw reasoning and summary, nonstream continuation, source-message immutability, exact private extension/tool result, different-route stripping and user/tool reasoning/image rejection. Retain existing committed-output barriers and encrypted continuation tests.

### G3 / B2 — Direct cap partially fixed; pooled summary cap still wrong (High)

**Source:** `compaction/compacter.py:510–608`; `providers/model_pool.py:300,344,388`; `graph/service.py:96–125`.

`compact` now passes its snapshot into `_invoke_llm_summary`, and `_summary_output_token_limit` bounds an OpenRouter route by reserve, reported-or-4096 ceiling and half context. The old unconditional-direct-16384 finding is superseded. New `test_compacter.py::TestInvokeLlmSummaryShaping::test_openrouter_summary_uses_prepared_output_ceiling` asserts a mocked `ainvoke(max_tokens=3000)`; it does not assert a real SDK request or committed summary.

The cap is calculated **once from model_name**, before ModelPool selects/falls back. Per-member adaptation still only performs ChatGPT-backend shaping; it does not recompute the OpenRouter summary ceiling. A direct initial route or larger OpenRouter route can pass 16384/3000 into a smaller OpenRouter fallback whose adapter rejects it. This remains a concrete integration defect.

**Required:** summary-specific per-member pinned cap selection without relaxing explicit caller validation. Real summary SDK absent/small-ceiling and smaller fallback cases must assert legal wire fields, committed summary/retained tail, and automatic/overflow delegation. Preserve Codex omission and direct-provider behavior.

### G4 / C1 — Append lease does not survive launcher exit (High)

**Source:** `orchestrator/spawn_env.py:329–386`: lease retained by `_CapturePipe`; writer `Popen(close_fds=True)` passes only ACK/control descriptors. The independent writer cannot retain the append flock after launcher death. Its old buffered tail can race a replacement writer.

Prior same-parent exact ordering and qualified post-reap EBADF reporter tests remain useful but do not combine reaped launcher + held old tail + competing replacement append. Transfer existing lease lifetime to the independent writer and prove readiness/order with deterministic barriers. Do not change workload PID/group, reporter activation or add a registry.

### G5 / C2 — Late capture acquisition and reservation cancellation ownership (High)

**Source:** `relaunch.py:94–123`; `workflow_registry.py:1332–1361`.

Both off-loop capture opens await `asyncio.to_thread` before entering their results into ExitStack. Cancellation cannot stop the worker; a late endpoint has no explicit closer. Command cancellation with `ownership is None` re-raises before undoing the pid-zero reservation. Source is unchanged in the relevant branches.

Required tests must cover stdout and stderr acquisition, late success/error, endpoint/control closure and writer reap, plus durable pre-adoption rollback. Preserve post-adoption no-kill semantics. Existing “no workload spawn” assertion is not resource-ownership proof.

### G6 / A2,C3 — Descriptor allocation/failure leaks (High)

**Source:** catalog `store.py:72–94,148–157`; capture `spawn_env.py:330–350,425–438`.

Catalog opens in a thread before release protection; late cancellation result is unowned. Path chmod after open can raise without closing. Capture obtains append lease before the three pipe allocations; early allocation cleanup omits the lease. Unexpected flock exceptions also omit close. Catalog pre-flock leak is not evidence of a held lock; capture lease leak can prevent later acquisition.

Own each FD immediately, drain allocation results on cancellation, and test first/second/third pipe failure, post-open chmod, unexpected flock failure and reacquisition using verified temporary paths. Existing destination-open cleanup starts too late to refute these branches.

### G7 / C4 — Private capture creation missing (Medium/security contract)

**Source:** `spawn_env.py:329,333,352`; process capture opener. Default mkdir and `Path.open('ab')` rely on umask, rather than a.6 §7.2's 0700/0600 contract. Implement safe private creation at the existing owner before content writes, preserving existing append data; assert creation modes and safe existing-path handling. No global umask or unrelated chmod.

### G8 / A3,A4 — Auth rejection/timeout and stale credential presentation (Medium)

**Source:** `integrations/openrouter/client.py:240–250`; `auth/openrouter_authentication.py:100–108,118–121,174–200`; modal `auth_screen.py:276–282`.

Timeout and HTTP transport errors collapse to generic APIError; pre-verification auth failures all paint the same retry-auth message. After A verification, listing-time `credential_changed` is flattened to catalog-refresh failure while `key_verified=True` and private A dismissal survive. The modal selects Success solely on that flag. Prior verification-time environment-race correction does not cover this later boundary.

Use bounded safe rejection/timeout/protocol/credential-changed outcomes, clear obsolete dismissal evidence, retain factual saved-state information, and add service plus painted modal listing-barrier tests. Existing byte-preservation/cancellation evidence remains credited. The inspected fixed environment failure notice is 135 characters; no over-240 notice counterexample is asserted. Missing refresh count/time is separate G11.

### G9 / B4 — Known enabled efforts disabled by absent mandatory flag (Medium)

**Source:** `model_catalog/openrouter.py:280–310` requires `mandatory` to be bool before any reasoning control is available. Overview §7.3 instead preserves known enabled efforts while withholding permission to disable. Existing missing-mandatory test expectations need correction, not blind acceptance as policy. Prove converter→factory→wire enabled effort and absence of `enabled=false`. Keep unknown efforts conservative; none-only ambiguity needs an explicit policy assertion, not an invented expanded vocabulary.

### G10 — Mandatory declarations/typing/decomposition (Medium, not waived)

Freshly confirmed missing Field descriptions in `model_catalog/dao.py:362–428`, adapter `openrouter.py:370–372`, and broad internal codec `Any` at `:296–297`; catalog `refresh_lease` lacks its return annotation. New acquisition/admission methods still mix decisions and resource transfer. The existing catalog refresh helper extraction remains credited; its old monolith finding is not reinstated.

Complete explicit new-field descriptions, bounded JsonValue internals/localized SDK casts, public lifetime/error documentation and owner-local named-step extraction. Preserve the stdlib-only isolated writer; do not force Pydantic or a graph/pool rewrite into it. Black/mypy waiver does not waive these explicit specification requirements.

### G11 — Product/delivery obligations (Medium)

- `CatalogRefreshResultDAO` has only status/generation/message; session/router return safe_message without required count/check-time (a.5 §7.6). Add bounded literal output assertions.
- Session pending checks around `sessions/service.py:2213,2226` reject all selection, including the required direct-model escape. Test direct selection plus late-startup immunity.
- Unknown qualified selection at catalog `prepare_models` gives generic preparation text, not explicit unlisted-variant guidance. Preserve exact rejection; no suffix stripping/single-model lookup.
- `tests/fixtures/openrouter/` and `tests/integrations/openrouter/test_live_openrouter.py` are absent. Required sanitized provenance/disabled authorization-gated artifacts are not replaced by inline synthetic metadata. No live execution is requested.
- README:86–92 still describes generic superseded matrices and non-green static gates. Latest continuation correctly says no new full suite, but its claim that durable adoption preserves all publication semantics exceeds its tests and conflicts with G1. Historical evidence must remain historical; reconcile current pointers and exact test scope. Static failures are waived, not green.

## F86-01..42 disposition ledger

`Retained` means prior A/B/C allocated source/test evidence is credited, not freshly executed or exhaustively re-audited here. `Partial` means an identified blocker/evidence obligation prevents approval. Clause references below use overview §7 and engineering a.N §7, with the detailed exact mappings in the unchanged section reports.

| ID | Clauses / prior allocation | Current disposition and concrete evidence |
|---|---|---|
| F86-01 | a.1 identity; a.5 auth / A | Retained implemented: credential enum/resolver/factory capabilities; resolver/auth tests. No new counterexample. |
| F86-02 | a.1 GET; a.5 temporal/modal / A | Partial G8: auth `_refresh`, `_failure_message`, modal success predicate; missing distinct painted outcomes/listing rotation. |
| F86-03 | a.1/a.6 private data / A | Partial G4–G8. R2 `_emit`/`_notify_terminal` binding freshly inspected and retained accepted; terminal lifetime tests remain bounded evidence. |
| F86-04 | a.1 identity; a.3 factory / A | Retained implemented: `provider_for_model`, converter/factory exact route tests. |
| F86-05 | a.4 selection / A | Partial: simple external removal correction present; G1 ordering and G11 pending escape remain. New admission removal test inspected. |
| F86-06 | a.4 precedence / A | Retained implemented: Typer explicit model before pool, session selection; precedence/race tests. |
| F86-07 | a.1 pool invariant / A | Retained implemented: config parser and ModelPoolEntryDAO; config/provider tests. |
| F86-08 | a.3 constructor / A | Retained implemented: factory/adapter fixed Chat Completions; transport tests. G2 continuation qualification separate. |
| F86-09 | a.3 headers/cache / A | Retained implemented: fixed attribution/no explicit cache; transport assertions. |
| F86-10 | a.3 stream/tools / A | Partial G2: detached projection now present; required actual visible-reasoning live two-request proof not established. |
| F86-11 | a.3 extension/history / A | Partial G2 verification; existing encrypted anchor/projector/resume coverage retained, not invalidated. |
| F86-12 | a.1/a.2 authenticated list / A | Retained fixed endpoint/no public fallback. G1 admission provenance is a separate unresolved boundary. |
| F86-13 | a.1 bounded pages / A | R3 remains corrected: client no-progress full-page rejection freshly inspected; pagination/retention tests retained. |
| F86-14 | a.2 eligibility / A | Retained converter filtering; partial next-admission ordering G1. |
| F86-15 | a.2/a.3 caps/images / B | Partial G3: direct summary helper exists; smaller pooled lane can still reject. Mock cap test insufficient for real compaction. |
| F86-16 | a.2 exact variants / B | Retained exclusion; partial G11 explicit variant guidance. |
| F86-17 | a.2/a.3 reasoning / B | Partial G9 and G2 proof. Missing mandatory suppresses known enabled efforts. |
| F86-18 | a.2/a.3 profiles / B | Retained normal defaults/require_parameters; partial G3 summary consumer. |
| F86-19 | a.2 offline views / B | Retained offline load/read-view tests. Supplied snapshot admission still bypasses new adoption; no fresh full offline gate. |
| F86-20 | a.4/a.5 startup/auth / B | Partial G8/G11; pending startup tests retained, direct pending escape rejected. |
| F86-21 | a.5 refresh / B | Routing retained; partial G11 count/time result contract. |
| F86-22 | a.4 headless/child / B | Preparation/R2 retained; partial G4–G7 capture lifecycle. |
| F86-23 | a.2 publication/a.4 pinning / B | Partial G1: stale asynchronous adoption can overwrite later publication; G3 consumer remains. |
| F86-24 | a.2 last-good / B | Existing atomic/failed-page preservation retained. New adoption last-good/override/interleaving combinations not proved; G1. |
| F86-25 | a.2 concurrency/a.4 runs / B | Partial G1/G6/G3. Existing immutable runs remain pinned; allocation and new publication ordering unsafe. |
| F86-26 | a.2 fingerprint/TTL / B | Partial G1 identity recheck across new await. Existing A→B SDK and refresh-race tests retained. |
| F86-27 | a.2 removal/a.4 resume / B | Partial G1. New loader-stub removal check proves simple rejection, not full concurrent durable ordering. |
| F86-28 | a.2 projections / B | R4 presentation rename freshly inspected and accepted; partial G1/G3/G10. |
| F86-29 | a.2 raw/overrides / C | Retained raw-store separation; new raw-versus-overridden equality concern G1. Exact remove-override/reload proof remains prior bounded evidence task. |
| F86-30 | a.5 search / C | Retained engine/picker full-flow assertions; no fresh counterexample. |
| F86-31 | a.5 viewport/no I/O / C | Retained painted viewport/1000-row assertions; mandatory decomposition G10 distinct. |
| F86-32 | a.5 honest status / C | Partial G8 stale success; G1 metadata-identical evidence adoption not tested. Historical-status coverage retained. |
| F86-33 | a.3 pool / C | Sole fallback owner retained; G3 per-lane summary failure and previously unestablished successful durable tool/audit composition remain. |
| F86-34 | a.3 taxonomy / C | Retained shared explicit error matrix; no new classifier defect asserted. |
| F86-35 | a.3/a.6 errors/secrecy / C | R2 accepted, committed-error tests retained; partial G4–G7 cross-channel resource/privacy. |
| F86-36 | a.3 bounded retries / C | Retained zero SDK retries/first-chunk barrier/pinned wait cap. No new retry owner found in inspected scope. |
| F86-37 | a.4 contexts / C | Retained exact route/resume/active inbox evidence; partial G1/G4–G6/G11. Same-process resume is not process restart inference proof. |
| F86-38 | a.6 gates / C | Partial: no complete current non-E2E gate after latest edits; 5047 historical, not approval. |
| F86-39 | a.6 provenance/paint/live / C | Partial missing named fixture/live-test artifacts; local synthetic evidence retained. Live execution not required or authorized. |
| F86-40 | a.6 docs / C | Partial G11: current docs mix historical gate/matrix statements; latest preservation claims overreach G1 tests. |
| F86-41 | all slices ownership / C | Existing owners retained in inspected scope; partial mandatory G10, complete dirty-diff scope audit unfinished. |
| F86-42 | a.5/a.6 unseeded choice / C | Retained mounted auth→unseeded picker→SDK tool→new-session evidence; no remote entitlement claim. |

## Latest correction verification

The two added admission tests construct a tmp-path variable and assert ancestry but **do not write/read that path**. They patch `ModelCatalogStore.load_provider_cache` with initial/removed or changed DAOs. That is useful deterministic loader-seam coverage, not the real-store external writer described in the stronger requirement. Removal asserts rejection and absence from global entries; cap asserts 3000→512 in returned/global runtime profile. Neither asserts generation, unchanged old snapshot, publication barriers, no HTTP call count, invalid overrides, or real durable bytes.

Removal still enters refresh when membership is missing; there is no explicit HTTP tripwire in this new test. Consequently “no client configured/invoked” is not established by the shown assertions. The cap fast path has no refresh call by source inspection. No production HTTP was invoked during this review.

Successful-generation semantics are not certified: `_publish_candidate` increments monotonically, but G1 demonstrates newer numbers can carry older data. Last-good failure remains supported by existing refresh tests, not automatically by this new adoption seam. Supplied snapshot and old-run immutability remain structurally separate from global publication and should be preserved during repair.

## End-to-end trace

```text
/auth → captured credential → /key → candidate persistence → /models/user
 → canonical raw cache/publication → cached picker → exact selection
 → session prompt admission → pinned factory/pool → SDK → tool result
 → detached assistant wire projection → same-route extension → history/resume

external cache → new admission adoption await → global publication [G1 race]
compaction → one summary cap → pool fallback → smaller route [G3]
launcher → parent-only append lease → independent writer → launcher exit [G4]
cancel off-loop opener → late endpoint + reserved handle [G5/G6]
```

The existing composed flows are genuine useful offline evidence, not absent. Active inbox keeps the target route; it is not inactive scheduled-child proof. Native-I/O writer/reporter evidence after launcher reap remains qualified shipped-body evidence, not native interpreter-startup equivalence. No argv-equality or arbitrary FD raw-body-filter requirement is introduced.

## Tests assessment: historical, current source, new execution

- **Historical:** independently read `.f86-final-correction/full-final.log` tail: `5015 passed, 15 deselected, 194 warnings in 334.32s`. Later 5047/15 result is the retained pre-latest-edit gate, not current verification.
- **Latest retained focused:** independently read `.f86-catalog-surrounding-MpBUHa` log tail: `57 passed, 2 warnings in 3.40s`. Continuation reports 13 focused and 57 surrounding; not executed by this reviewer. The slight duration difference from prose is not a functional failure.
- **Fresh:** read-only `git diff --check` exited 0. In-memory unchanged-method race diagnostic exited 0 reproducing G1; that is not acceptance green. Fixed auth notice length diagnostic reported 135.
- **Not run:** pytest/full suite, Black, mypy, real-store/process capture experiments, any network/live provider. No long reruns manufactured a status.
- **Explicit limitations:** 15 E2E deselections stay outside historical offline gates. Synthetic/local transports do not establish authenticated provider availability or paid inference. Neither installed/locked SDK cross-version equivalence nor complete current all-branch coverage was established here.

## Conventions / hard rules / ubiquitous language

Single canonical catalog, resolver, factory, pool and extension owners remain recognizable. `model_name`, `api_model_name`, `provider`, `catalog_generation` and private credential fingerprint have distinct roles. `ModelPickerRowDAO` correctly names the presentation projection. There is no justification for a second catalog or generic provider framework.

Hard-rules pass is **not clean**: explicit field descriptions, internal Any narrowing, allocation lifetime and declarative structure findings above remain. Full every-call-site and every-test-branch audit was not completed. Static formatting/type-tool waiver is honored and is not used as a hidden blocker.

## Nice-to-haves

- Correct stale helper/test docstrings that describe already-added behavior as future work.
- Prefer exact assertion names: loader seam is not external-process persistence; one mocked summary call is not committed SDK compaction; no-workload-spawn is not writer/FD cleanup.
- Keep a single dated current evidence entry pointing to historical artifacts rather than stacking contradictory “Latest” headings.

## Final verdict and finite handoff

**REVISE. Do not advance to Step 3.**

- Must-fix code: G1 publication ordering/identity, G3 per-lane summaries, G4–G7 resource/private creation, G8 auth outcomes, G9 reasoning policy, G10 mandatory structure, G11 required visible behavior.
- Required tests: exact deterministic barriers and real composed assertions listed above; G2 live continuation qualification; existing override-removal and mixed-pool durable audit evidence must be located or supplied, not inferred from counts.
- Documentation/artifacts: truthful current dispositions and named provenance/disabled live procedure; preserve prior reports.
- Final verification: fresh full non-E2E gate after corrections, followed by completed independent full-diff review. Global Black/mypy waiver remains explicit; no live provider claim.
