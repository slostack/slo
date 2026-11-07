# 96.a.2 — independent early re-review of append repairs

**Verdict: REVISE — finite defects/closure below.** R2 and R3 behavioral repairs are accepted at the restricted-admission source level. R1 now certifies before success, but not before existing-event metadata repair. Mandatory class ownership and an incompatible new test file remain unresolved.

This is advisory EARLY feedback inside Step 1, **not** final review, milestone acceptance, completion, or a completed workflow turn. No tests, static checks, collection, product execution or nested agents were run. Only this new artifact was written; no source, tests, old reports, SLO.md, docs/, preflight or KB files were edited.

## Authority and inspection

- Repository `/root/Code/slo-message-queue/slo`, branch `message-queue`, baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`. Reviewed actual baseline-to-worktree diffs and untracked tests, not just repair prose.
- Exact original spec: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`, §§4.3, 6.2, plus §2.4's successful re-fsync requirement and A8. No substitute specification.
- Read `early-review-append.md`, `repair-marker.md`, `repair-opening.md`, `repair-fsync.md`, `current-handoff.md`, routing/acceptance and referenced receipts. README first; root RESEARCH.md is absent and was not created under this one-artifact authorization. Consulted KB Welcome, slo/README, gotchas and operational-reference.
- Both skill environment variables actually equal `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Used that installed root per task routing (this is not skills maintenance): exact `orchestration/workflows/code-test-review.md` early-feedback checklist; engineering routing/review/ownership/testing; overarching solution-design, coding-rules, naming-and-clarity, test-verification-policy, declarative structure; Python conventions/review, types/keyword arguments, docstrings and declarative specialization. No unrelated framework, system, presentation or final-review workflow was invoked.
- Operator ledger preserved: **turn 5, dispatch 8/20; prior partial calls 7/4/4/8; 60-turn ceiling; eight retries (audit 1/provider 1/repair 2/proof 1/append 2/fsync 1); never retry an abort.** Handoff's dispatch 2/seven-retry stanza is historical, not the current counter. No model selection/fallback or model-call execution was performed by this review; primary exact DeepSeek default and quota-only `gpt-6.1-sol` medium fallback remain unchanged. The requested reviewer identity is `gpt-6.1-sol` high; this artifact does not independently attest harness model configuration.

## Findings and exact closure

### ER1 — High: incompatible, unfinished new certification test is outside the green receipts

**Source:** `tests/agents/slo_agent/history/test_history_file_certification.py:34–60,175–187`; actual constructors `history/filesystem_store.py:315–330`, `tree_store.py:52–70`.

The new untracked file calls both constructors with **`certifier=`**, but they accept **`file_certification=`**. By signature inspection, its two parameterized `test_equal_event_retry_requires_successful_refsync_certification` cases cannot reach persistence: construction raises `TypeError`. Its `_ScriptedCertifier.certify(path, descriptor)` also does not implement the actual `FileCertification.certify(path)` contract and never delegates to real fsync after exhausting failures. Changing only the constructor keyword would not repair that proof. The final stale-metadata test ends after `ensure_session`, with no event, failed certification, retry or assertion.

This is not evidence of a production default bypass: the real default does fsync. It is a concrete broken/unfinished candidate test artifact that the 22/247 receipts omit. No collection or execution was used to discover it.

**Closure:** reconcile this file with the actual one-method seam; successful certification must delegate to the real production implementation and the stale-metadata case must assert the ordering claimed. Alternatively, consolidate genuinely duplicate proofs into the working messaging test owner through an explicit author disposition, not silent deselection/skip or deletion to manufacture green. Keep all distinct required assertions. Supply a safe focused receipt covering every retained certification test. No executable fixtures or new harness are needed.

### ER2 — Medium: R1 existing retry repairs metadata before event certification

**Source:** `history/filesystem_store.py:681–688`; tests `messaging/test_history_cooperative_append.py:636–677`.

Actual order is `metadata.latest_sequence = high_water` → `_write_metadata_sync` → existing-event `certify(events.jsonl)` → return. After first append leaves a complete sequence-1 line but certification raises, metadata remains 0. The next exact retry writes metadata 1 **before** its second certification fails. Thus raw presence still advances the durable high-water marker before that line is certified. The new test asserts one line and eventual metadata 1, but never inspects metadata after the failed retry.

The original false-success defect is materially repaired: a failed re-certification no longer returns success. This narrower ordering defect remains against the original R1 closure (“only then complete metadata repair/return”), the requested before-metadata check and the certification test's own stated contract. Do not describe it as a continuing raw-presence-success bug, or as proof that a provider already continued.

**Closure:** on an equal existing event, certify the raw file before writing repaired metadata and before returning, still within the same locked/joined worker. Preserve the spec's pre-new-append high-water repair and application-specific guard/error translation. Both adapters should assert metadata remains stale after failed retry certification, then advances only after successful real certification; also preserve exact ID/sequence/time/digest and one-line assertions. An injected certifier can read real session metadata at the certification boundary; no global/private patch is necessary.

### ER3 — Medium, mandatory: R2's class-owner correction was not performed

**Source:** `history/dao.py:253–384`, called from `filesystem_store.py:649`; rule `README.md:4201–4205` (Style rules).

`validate_cooperative_history_event` and the marked-tool/opening-array/diagnostic/no-start helper chain remain free functions, and R2 added more policy to that chain. They are neither tool bridges, LangGraph nodes nor test helpers. The original R2 explicitly required a cohesive class owner; all three repair reports/handoff acknowledge no class extraction. This is a mandatory finite convention defect, not optional future cleanup.

**Closure:** move this cohesive admission policy behind one class owner, with the repository's classmethod/public-entry convention and named private validation steps; update the flat caller/export and preserve the same public-store behavior. Use explicit types, keyword calls and declarative guards. Do not create a framework or a class per check, or reopen unrelated pre-existing free functions. Rerun the existing admission proofs against that owner through both real adapters.

## Bounded requirement mapping

| Requirement | Actual source/test assessment | Disposition |
|---|---|---|
| R1 / §6.2 / §2.4 successful certification | `FileCertification.certify` opens the supplied file read-only and calls real `os.fsync`; constructors default to it; tree forwards the collaborator. First append writes complete LF line, flushes/closes, certifies the exact `events.jsonl`, then `_append_event_sync` updates metadata/returns (1135–1141, 1586–1599). Existing retry now certifies before return, but after metadata repair. | Partial: ER2. No no-op production default or separate fake certification port found in these paths. |
| Both adapters / real failure proofs | Messaging tests inject a `FileCertification` subclass that raises a bounded number of times and otherwise calls `super().certify`; both adapters cover first-line survival, second certification failure, later exact one-line recovery and lost reply after real persistence. | Useful bounded proofs; do not confuse them with the incompatible separate file (ER1), physical crash proof, or metadata ordering proof. |
| R2 / §4.3 complete opening | `dao.py:316–343` requires nonempty full ordered IDs equal to group metadata, each nonempty string name and dict args, selected name/input equal to selected entry. Both-adapter negative fixtures cover absent/empty/reversed/truncated/malformed array, empty name, missing/mismatched selected input/name; positive readback asserts full array/args. | Behavioral defect repaired at admission level; ER3 convention remains. No demand here for cross-record sibling/anchor validation. |
| R3 / §4.3 markers/no-start reason | Tool kinds require `tool_group_v1` and reject presence of `cooperative_yield_v1` even null/schema2. `run_retrying` requires exactly one known marker. Parsed carriers reject invalid versions. No-start requires outer `metadata['reason']=='cooperative_yield'` and group `disposition='not_started'`. Both-adapter refused-candidate readback/cursor tests exist. | Accepted for this bounded repair. No new history kind or fabricated result required. |
| Error / lock / join | Cooperative wrapper translates failures to fixed `CooperativeYieldSettlementError`; application retains projector validation and `MessageStoreError`. One flat lock encloses worker creation and shielded repeated-cancellation drain before unlock. Tree delegates without enrichment and advances cursor only on newer returned sequence. Agent/session terminal exclusions precede generic retry/recovery. | No additional defect identified in these inspected paths. Flat cancellation-success test is not evidence for every tree cancellation/error interleaving. No automatic retry was added. |

The positive “accepts no-start and diagnostic records” test still persists a result and a no-start marker for one group. This is individual admission-shape coverage, **not** a valid settled history or recovery proof. Planned §6.3 must reject that combination; it is not a new raw-validator blocker for this increment.

## Receipt provenance and chronology — read, not rerun

All receipt names below are relative to this directory's `logs/`. No aggregate/full-suite total is inferred.

| Receipt/source | What can actually be traced |
|---|---|
| `turn5-r3-append-red.log` / `…green.log` | Raw headers name cwd, Poetry argv, env, UTC and statuses 1/0; summaries 4 failed/12 passed and 16 passed. RED explicitly lacks pre-repair hashes; GREEN has the older dao/test hashes. RED's env text includes a stray `SLO` token and is not a clean executable environment manifest. Current R2/R1 edits supersede those hashes; these are historical R3 receipts. |
| `repair-opening.md` | Reports R2 RED 2 failed/16 passed, GREEN 18, focused pair 21 and scoped 137, with env/runner template and source hashes. No distinct R2 raw logs are present in the inspected log inventory. Treat these as author-reported results, not independently traced raw receipts. Current dao hash matches its final source hash; test hash was later superseded. |
| `turn5-r1-fsync-green-focused-final.log` | Output-only pytest capture: 22 passed, 2 warnings, 1.92s. No command/cwd/env/status/source header in that raw file. Companion `turn5-r1-fsync-commands.md` supplies cwd, eight-file regression list, runner/environment and claimed exit 0; `repair-fsync.md` supplies final hashes. |
| `turn5-r1-fsync-regression-app.log` | Output summary 247 passed, 320 warnings, 69.10s. Companion metadata supplies command/environment/claimed exit 0. This selection excludes `history/test_history_file_certification.py`; it cannot establish that file passes. The separate `…regression.log` says 141 passed; do not combine or substitute totals. |
| `turn5-r1-fsync-red-revert-probe.log` | Two named re-certification failures, both adapters; 2 failed, 2 warnings, 1.62s. Explicitly a **post-fix revert probe**, not original test-first RED. Companion says “same focused command,” yet full-file GREEN has 22 cases and RED has only two; exact selector/argv for the two-case probe is missing. Do not invent it. |
| `turn5-r1-fsync-mypy.log` / `…black-final.log` | Raw cwd/UTC, two exact source paths and EXIT=0; mypy reports two source files; Black two unchanged. Companion specifies `python -m`, raw headers omit that prefix: launcher provenance is companion-reported. Earlier `…black.log` retains EXIT=1 for source plus messaging test; final check excludes the test. Not an all-changed-files or full static pass. |

**Current identity verified by SHA-256:** dao `86e72efc04db2730ba223d3d294f77596324bee8002f4d62d0e1d633b883a8f3`; filesystem store `ca0e2b70e4f891b45e8c9b9a9eff615f76a5e85c261e2a644a38e69756b07582`; tree store `01d05bc725c4518612fc03b729985edcc8092c2c04ad714af87ef1b33a2b52d3`; messaging append test `4cfafdbad080585fba751acb50fcc02a1ec91a4ba7db5c6e1565851d5e5f2065`. The latter three match repair-fsync's recorded identities. The incompatible extra test hash is `27f048984c6399406ac9ddd31fa7caa0bbd36b5f717b5e7f5a36084920c1ed18`. Matching retrospective prose hashes do not establish a contemporaneous tested-dirty-tree manifest.

**Evidence closure:** preserve every old receipt. After finite repairs, capture exact expanded argv (including any selector), cwd, env, status and final source inventory alongside scoped output covering retained new tests. Link R2's original raw captures if available; otherwise retain the missing-receipt limitation. Current-handoff's blanket bounded READY must not conceal ER1–ER3 or provenance limits.

**Test-first limitation remains:** R3 supplies chronological RED/GREEN artifacts; R2 reports test-first chronology without raw captures here. R1 records GREEN then a deliberately labelled revert-probe RED. That proves detection of the removed check, not compliance with mandatory original test-first ordering. Retain this process deviation explicitly; it cannot be repaired by rewriting history or relabelling the probe. The earlier post-implementation duplicate/corruption cases likewise remain post-implementation verification.

## Stop boundary

Close ER1–ER3 and the stated receipt gaps, then request another bounded early re-review. This report does **not** demand future raw startup/context/compaction validation, producers, T2 provider control/race/cleanup, tools or TUI as repairs to this API subset. Those original requirements, the actual urgent runnable milestone, independent final review and completion remain pending.

`make test PYTEST_WORKERS=6` remains **BLOCKED** by other specific executable-fixture consent; full static is **UNRUN** and YAML-stub baseline **UNESTABLISHED**. No skip/xfail, alternative suite total, model substitution or mode evasion is authorized. The sole consented deploy-worker tmp `bin/curl` fixture was not run. No binaries/executables, installers, packages, infrastructure, commits, pushes, merges or PRs were touched. Preflight SHA-256 remains `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
