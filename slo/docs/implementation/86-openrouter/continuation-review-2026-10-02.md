# Feature 86 — independent Step 2 continuation review

**Date:** 2026-10-02  
**Verdict: REVISE. Do not advance to READY or declare Feature 86 complete.**

## Scope and evidence policy

This is an additive review of the current dirty/untracked worktree, not an implementation pass or replacement for `review-report.md`. The continuation deliverables are **A: static baseline/repair; B: documentation reconciliation; C: populated scheduler/notifier/inbox security verification**. They are distinct from recovery-plan sections A/B/C (capture adoption, append drain, source sanitation).

Reviewed the supplied AGENTS/SLO/CLAUDE instructions, root and docs RESEARCH, KB entry point and Slo README/gotchas/status, the Feature 86 overview, dependency index and all six implementation contracts. The checkout has no `specifications` link; contracts were read at `/root/Code/specifications/projects/slo/specifications/86-openrouter-intergration/`. Consulted current status, implementation ledger, remaining requirements, recovery plan, historical review and completion documents. Historical findings/results are not automatically current facts. Applied the Step 2 feature-review and hard-rule checklists.

Inspected actual source, selected test bodies, tracked diffs, untracked files and retained static output. This is sufficient to establish blockers, not exhaustive line/branch certification of the entire feature. No pytest, Black, mypy, provider call, credential access, workload launch, process inspection/control, Git mutation, environment repair or system change was performed. Static results below are **recorded command evidence independently cross-checked against files**, not newly executed gates. Read-only shell comparisons were used to check manifests and diagnostic attribution. Oversized early reads caused tool-managed output spills under `/tmp`; these were not intentional review artifacts and were not modified or removed. The only deliberately authored file is this note.

## Stack and implementation summary

Python 3.11; Pydantic contracts; httpx metadata client; LangChain/OpenAI Chat Completions adapter; LangGraph agent; Typer/headless entry points; Textual auth/picker; filesystem history/catalog/inbox/status; POSIX capture writers and locks. No database or frontend web stack is involved.

The feature is substantially implemented beyond its old foundation assessment:

- `CredentialResolver` and `provider_for_model` own effective credentials and exact OpenRouter identity.
- `integrations/openrouter`, canonical catalog service/store/converter, and authentication service implement verification/discovery/publication boundaries.
- `LLMFactory._build_openrouter`, the adapter and message extension implement the local SDK/tool/private-continuation path; the existing pool remains fallback owner.
- Session preparation/pinning, explicit model/pool precedence, headless preparation and mounted picker/auth paths exist.
- `test_openrouter_full_flow.py:296–522` contains a real mounted auth/picker/router/session/tool/newly prepared resume composition. It asserts three SDK requests and exact continuation/tool-result content. Its final history scan excludes `events.jsonl`; it is not a complete private/public artifact scan or OS-process restart proof.

All six slices have implementation assets; a.1–a.5 retain adverse/composed verification boundaries, and a.6 remains blocked on security acceptance and delivery gates. No percentage is assigned.

## Continuation source-versus-test mapping

| Deliverable | Actual changes/owners | Evidence and what it proves | Assessment |
|---|---|---|---|
| **A — static baseline/repair** | `test_compaction_checker.py:123–130` changes `supported_levels` and `templates` from lists to tuples. Static artifacts live under `evidence/20261002T000000Z-static-baseline/`. | The two-line constructor-shape repair matches immutable DAO inputs. Ledger reports 24 module tests; retained static outputs report 68 files clean and global failures. Manifest and attribution checks below invalidate the claim that this is the complete changed-feature scope. | **Partial; revise evidence and scope before accepting SCOPED_READY.** No runtime production repair was made by A. |
| **B — documentation reconciliation** | README, AGENTS, root/docs RESEARCH, headless/scheduler guides, current-status matrix. | New wording correctly distinguishes implemented paths from full acceptance, keeps capture blocked, and does not claim live inference or current full gates. Source/tests support ordinary route forwarding and bounded local auth/SDK paths. Shell examples and static-ledger wording still need correction. | **Substantive bounded reconciliation, not documentation/feature completion.** |
| **C — populated scheduler/notifier/inbox security** | Existing `ScheduleSubprocessRunner`, scheduling executor/report writers, `WorkflowNotifier`, inbox consumer/store, history/headless/status/fleet owners; no new completed C composition. | `test_runtime_helpers.py:240–270` mocks `create_subprocess_exec` and asserts argv. `test_executor.py` checks enqueue into a test double, not active consumption. Notifier/history tests cover narrower serialization paths; history writer test uses the currently effective env/store key. | **Not implemented as the requested continuation deliverable.** The requested pre-write symlink-resolved containment proof would require framework/owner-level broad changes prohibited by that task; work stopped rather than weakening the safety requirement. This is an unmet deliverable, not a waiver or proof of impossibility. |

## Blockers

### B1 — High: static scope excludes every tracked changed Python file

**Where:** `implementation-log.md:15–29`, `remaining-requirements.md:5–13`, and the static evidence manifest/scope/exclusion files.

The ledger says excluding only generated temporary artifacts leaves 68 Feature-86 paths. That is false for the retained manifests:

- `tracked-changed-python-paths.txt` contains 79 paths prefixed with `slo/` (Git-root relative).
- `feature86-python-paths.txt` contains 68 checkout-relative paths, all from the untracked implementation/test set; it omits tracked owners such as `src/agents/base.py`, catalog service/store, session service and spawn/launch/relaunch.
- `excluded-generated-python-paths.txt` is **byte-identical to the 79 tracked changed paths** (`cmp -s` returned 0). These are not generated artifacts.
- `scope-summary.json` labels those 79 exclusions generated, conflicting with the ledger's claim about 647 generated scripts.
- Stripping the known `slo/` prefix and unioning the two retained source lists yields **147 distinct paths**, not 68. This is a manifest reconciliation, not a new static run.

**Impact:** 68-file success is real only for that enumerated subset. It cannot certify all touched Feature-86 Python, and even excludes A's repaired tracked test.

**Next Step 1:** normalize every manifest path to one root before existence/filter checks; exclude only resolved generated prefixes; retain explicit reasons; run the corrected tracked-plus-untracked scope and append a correction to the ledgers. Do not delete preexisting artifacts. Withdraw A's complete-scope claim until this is done.

### B2 — High evidence error: seven of the claimed 18 introduced mypy diagnostics are baseline errors at shifted lines

**Where:** `mypy-introduced-errors-after-repair.txt`, baseline/current full mypy outputs, `implementation-log.md:31–50`, remaining-requirements static entry.

Independent line-insensitive comparison of file + diagnostic text/code, preserving duplicate counts, leaves **11**, not 18, current diagnostics absent from the baseline logs:

| Current location | Baseline location | Finding |
|---|---|---|
| `test_process.py:939` | `:900` | Same `MonkeyPatch` used as a path (`[operator]`). |
| `test_process.py:1041,1066` | `:1002,1027` | Same optional mock-call `.kwargs` diagnostics. |
| `test_session.py:1924` (two), `:1926` (two) | `:1903` (two), `:1905` (two) | Same `BaseChatModel | None` attribute diagnostics. |

The baseline snapshot and current test bodies corroborate the unchanged faulty expressions. The remaining 11 are ten tuple-contract errors in `tests/agents/test_reasoning_capabilities.py:346–448` and one in `tests/tui/test_model_catalog.py:164`. These consumers need not themselves be edited to be affected by the new immutable DAO contract. A's tuple repair removed two analogous errors in the compaction test.

**Impact:** exact location comparison is not regression attribution. The ledger incorrectly assigns existing debt to Feature 86 and describes the residual as five touched paths although only four paths have residual entries and two are unchanged consumers.

**Next Step 1:** append semantic/diff-aware attribution, retain raw outputs, fix the 11 demonstrated contract regressions in a narrowly authorized test-typing pass, and classify the seven moved diagnostics as baseline debt. Do not claim that resolving these alone makes global mypy green.

### B3 — High: capture acceptance remains explicitly blocked; append ordering and cancellation remain open

**Where:** `launch_tool.py:288–376`, `spawn_env.py:101–245,305–365`, `capture_writer.py:149–177`, `relaunch.py:76–130`, `workflow_registry.py:1303–1382`; capture lifetime/helper tests.

**Current source correction:** the private control-FD handoff is wired. Launch persists the actual workload PID before activation; command-owned resume awaits `store.relaunch` before `ownership.activate`; `_CapturePipe` sends the frame, and the writer reads it and reports through the existing store authority. Do **not** repeat the historical claim that current activation changes only a parent object or that resume has no adoption lifetime.

Nevertheless, there is **no proof of launching parent reaped → genuine late unmodified production writer I/O failure → unchanged isolated reporter → fresh durable health/status preserving actual workload PID/group/state**. Latest guard work is tests/helpers/ledgers only and did not launch production writers/reporters. Clean drain, isolated reporter preconditions and finite descriptor probes cannot be joined rhetorically into that missing failure proof.

The current opener has no append-drain lease; `_resume_locked` still promises old-tail drain in its docstring without calling a drain barrier. Plan B old-tail-before-new-output and two-OS-process resume contention remain pending. Launch's first allocation/spawn try catches `OSError`, while its close-finally begins only around subsequent persistence: cancellation during the first awaited spawn is not covered by that cleanup scope. This is a source-level lifecycle gap, not a claim that this review leaked a process.

**Next Step 1:** first obtain an authorized bounded safe fixture plan. Preserve production writers/reporters and current control protocol. Establish exact child-local admission and finite pre-identity cleanup, then prove the required launch chain and command-owned resume/fault/cancellation cases. Separately prove bounded append drain/refusal/cancellation and cross-process single workload admission. Do not add a second durable authority or bypass safety guards to get a green test.

### B4 — High: populated security deliverable missing, with a concrete old-key sanitation gap

**Where:** `credential_resolver.py:49–90`; `sessions/service.py:4147`; history store redaction calls at `:621,779,791,1137`; notifier `:217`; scheduling tests identified above.

`bind_build_credential` lasts only through synchronous `_build_agent()`. `redact_openrouter_text` subsequently resolves the current effective key plus that short-lived binding. If admitted run A continues after B becomes effective, history/notifier sanitation has no retained A at these boundaries. The existing history secrecy test protects the current env/store key and preserves an unrelated opaque anchor; it does not prove rotated A or resolver-failure behavior. This is a missing lifetime guarantee, not an assertion that every normalized SDK failure leaks today.

C did not add the required completed/failed notifier → populated pending/processed inbox, actual scheduled headless preparation, active target consumption, status/fleet/report/private-history composition. Argv and enqueue tests do not prove these consumers. Capture literal-key redaction is not a substitute for raw-body normalization. Current capture creation uses ordinary `mkdir/open('ab')`; private modes are not established by that source alone.

**Next Step 1:** request a precise scope decision for the pre-write symlink-resolved containment prerequisite; do not silently implement a broad framework/owner change or run unsafe fixtures. Once authorized, bind output protection to the admitted operation at existing owners, test A→B and resolver failure, and populate every expected artifact before scanning two distinct synthetic sentinels. Preserve opaque continuation only in authorized private replay and the same-route SDK request. Include private-mode checks and actual active/inactive schedule paths.

### B5 — High: current catalog status still overqualifies cold persisted evidence

**Where:** `model_catalog/service.py:169–260`; `tui/model_catalog.py:190–269`.

Cold load can hydrate `state="checked"` solely from fresh persisted timestamps without a captured effective credential. Picker rows prefer that lifecycle summary over resolver-derived `requires /auth`/configured status. A cached A slice can therefore display checked evidence with absent/B credentials until a lifecycle operation qualifies it. Stale timestamps are discarded by the fresh-only parser rather than preserved as stale historical evidence. Admission revalidation does not make the initial UI claim correct.

**Next Step 1:** keep offline load pure, but distinguish historical cache evidence from effective-key-qualified status at lifecycle boundaries; preserve successful timestamps separately from freshness. Add cold A/no-key/B, exact-TTL/future and mounted repaint tests with no per-keystroke I/O. Current docs appropriately call adverse status acceptance incomplete; do not upgrade it based on the existing status test inventory.

### B6 — High: current full regression and global static gates are not green

The full current non-E2E gate was **not run**. Earlier full-suite passes predate subsequent changes and cannot establish current regression safety. Global Black and mypy retained outputs are failures, not waivers. Missing composed acceptance remains blocking even if those gates are later repaired.

**Next Step 1:** after resolving fixture safety and the bounded implementation defects, run affected partitions and the full non-E2E gate in the approved environment, then corrected-scope and global static checks. Capture complete outputs. Obtain explicit authorization for unrelated baseline formatting/type debt or a formal debt disposition; never relabel a failing gate green.

### B7 — Mandatory convention/ownership correction: duplicate relaunch spawn paths remain

`WorkflowRelauncher.invoke` still implements a separate allocation/spawn/close sequence rather than delegating to `spawn_for_adoption`; its docstring says the command service calls it, but the command uses the latter directly. Launch/relaunch activation also uses `getattr` on `IO[bytes]`, and command cleanup accepts `object` to recover process identity. These weaken the explicit private lifetime contract that recovery selected.

Consolidate within the existing owner using a typed private protocol/lifetime and retain compatibility through delegation. Correct lifecycle docstrings and keep decision-focused cleanup tests. This does not authorize a new capture framework or unrelated broad refactoring.

## Warnings and documentation corrections

1. **Unquoted shell placeholders are not runnable examples.** `docs/SLO_HEADLESS_README.md` and `docs/SLO_SCHEDULER_README.md` use `--model openrouter:<exact-remote-id>` in Bash fences. `<`/`>` are shell redirection syntax. Use a quoted illustrative discovered route, or quote the placeholder and clearly require substitution. Verify parse-only syntax and the CLI argv; no provider call is needed.
2. **Resume precedence needs one unambiguous sentence.** The headless guide first says resume uses persisted route unless explicit model, then separately mentions configured pools. State: explicit model → configured pool → resumed route → saved default → cfg default. The current-status guide is clearer but should not leave operators reconciling paragraphs.
3. **Guard-test names are stronger than their proof.** `test_capture_contained_lifetime.py:339–363::test_clean_writer_does_not_spawn_reporter` launches a script that writes `clean`; it never calls the production writer/reporter. Counter absence proves only that finite script's behavior. Ledger qualifications are correct; rename/describe this as a guard sentinel and require separate production reporter-nonexecution evidence.
4. **Keep historical artifacts historical.** The new current-facing documents correctly retain REVISE and the exact capture blocker. Old disconnected-handoff findings, foundational “not implemented” tables and prior completion estimates must not be treated as current. This note does not overwrite them. B's scoped success is defensible only as bounded reconciliation, not complete documentation acceptance; A's scope/attribution claims require the explicit correction above.

## Gate truth

Evidence directory below is `docs/implementation/86-openrouter/evidence/20261002T000000Z-static-baseline/`.

| Gate | Retained evidence | Review determination |
|---|---|---|
| Selected 68 Black | `current-feature86-black-after-repair.txt`: 68 unchanged | Recorded pass for listed subset only; tracked changed files omitted. |
| Selected 68 mypy | `current-feature86-mypy-after-repair.txt`: `Success: no issues found in 68 source files`, exit 0 | Same scope defect; not all Feature-86 static coverage. |
| Compaction constructor repair | Two tuple changes; ledger reports 24 passed and file-scoped static pass | Source correction is appropriate; tests not rerun by reviewer. |
| Baseline global mypy | `Found 343 errors in 55 files (checked 555 source files)`, exit 1 | Recorded baseline failure. |
| Current global mypy | `Found 299 errors in 49 files (checked 623 source files)`, exit 1 | Recorded current failure. Claimed 18 introduced reduces to 11 new diagnostic signatures/counts after correcting line drift; seven are demonstrably inherited. |
| Baseline global Black | 10 files would reformat / 551 unchanged | Recorded baseline failure. |
| Current global Black | 5 files would reformat / 624 unchanged, exit 1 | The five are `config/timeout_resolver.py`, `test_openai_codex.py`, `test_spawn_tool.py`, `test_install.py`, `test_release_automation.py` at their recorded paths. All are baseline failures and have no current tracked diff. Zero introduced failing Black paths is supported by these artifacts. |
| Full current non-E2E | No current run | **Unverified, not pass.** Historical full runs do not apply to this final worktree. |
| Exact late writer acceptance | No qualifying composed proof | **Blocked.** Latest guard-only checks do not close it. |
| C populated security composition | Not implemented under allowed containment scope | **Blocked; no execution/pass claim.** |
| Live discovery/inference | Not run | Intentional; optional live checks are not demanded for offline completion. |

## Precise next Step 1 sequence

1. **Repair evidence first:** normalize manifests; include the 79 tracked paths plus 68 untracked paths (reconfirm current inventory); correct exclusions and semantic baseline attribution. Append corrections rather than rewrite historical reports. Fix the 11 demonstrated tuple-contract consumer diagnostics in an authorized narrow pass; separately classify baseline debt.
2. **Resolve safety authority before runtime tests:** obtain an explicit bounded decision on C's pre-write containment requirement and on production writer/reporter child-local admission. No generic framework expansion, system mutation, real credentials or uncontrolled processes are authorized by this review.
3. **Close capture lifetime and ordering:** preserve the already-wired control handoff; fix cancellation ownership/consolidate relaunch; prove reaped-parent genuine failure through unchanged writer/reporter and fresh store/status. Then implement/prove Plan B append drain and independent-process reservation.
4. **Close cross-channel protection:** retain admitted-key sanitation through output persistence; exercise actual scheduler preparation and active inbox consumption, completed/failed notifier paths, rotation/resolver failure, populated public/private artifacts and exact private replay. Fix only reproduced leaks at existing owners.
5. **Close status/adverse integration and documentation:** effective-key-qualified cold/stale status, removal-next-resume and remaining auth/selection/pool/cancellation cases; quote CLI examples and make precedence explicit.
6. **Run authorized current gates and return for independent review:** affected modules, full non-E2E, corrected-scope/global Black and mypy with full failure/debt accounting. Do not use skips, test-only substitutes or scoped counts as acceptance replacements.

**Final Step 2 verdict: REVISE.** A contains a valid small repair but incorrect scope and regression attribution; B materially improves truthfulness but has residual corrections; C is not delivered. Capture/security/status/lifecycle and current-gate blockers prevent READY and Feature 86 completion.
