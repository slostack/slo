# Feature 94 Herdr — independent completion assessment 183

## Verdict: COMPLETE — accepted OFFLINE scope, with named live deferrals

| Metric | Assessment |
|---|---:|
| Completion of accepted offline scope | **100%** |
| Incompletion of accepted offline scope | **0%** |
| Infrastructure readiness for accepted offline scope | **100%** |
| Offline deliverables | **36 Done / 0 Partial / 0 Not Started** |
| Live compatibility | **UNVERIFIED** |

**This is an independent Completion Check, not the author's completion claim and not delivery.** The fresh specification-to-source scan and executable checks below support COMPLETE for T1–T6's accepted offline scope. Independent Review 182's READY verdict was context, not the premise of the score. No blocking offline omission was found.

The operator explicitly accepted **DEFERRED SCOPE** for live installed-launcher equivalence, actual Herdr version/wire/native server restart, metadata clear/TTL/wait/notification/release, sibling placement/focus/manual reuse/retention, and actual viewer paint. Those criteria are **neither passed nor counted as incomplete offline blockers**. Herdr 0.9.2+ remains a target, not a certification. Security finding 132 is separate/open and outside this feature-completion denominator; this report does not certify a global tool-event redactor.

Accounting: **turn6, global dispatch183, Completion Check phase**. No sub-agents, fixes, commits, push, MR, CI, merge, deployment, package changes, or live provider/Herdr/pane actions. Delivery is a separate authorized step; this assessment performs none of it.

## 1. Authority, method and input boundary

Governing process: `skills/design-and-analysis/is-the-feature-completed/SKILL.md`, steps 1–5. Read `scope-plan.md`, unchanged `routing.md`, independent reviews 172/180/181 and full synthesis182, `gates-171.md`, and `final-code-status.md`. Older CURRENT/PENDING headings in the latter are historical receipts, not the current verdict.

Reference-only specification root:
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/`.

Requirement extraction used the complete overview, tasks' T1–T6 normative allocations/acceptance, B's adapter/schema/ordering/admission/branch/cleanup contracts, C's capture/store/CLI/replacement/inbox/final-drain/64-case contracts, D's viewer/caller/automated/live contracts, and both historical source documents. Final B/C/D corrective prose takes precedence over historical `--model`, free-text model labels, `--current`, automatic focus and per-source process-slot examples. I did not count the duplicated 72 illustrative task fences as 72 independent deliverables, or claim a fresh line-by-line reread of every duplicated sample.

Fresh source inspection read the full seven-file Herdr package, identity/formatter/context-reader owners, root isolation guards, session capture/activation/attention/close/viewer bodies and mutation/usage/history hooks, feature changes in CLI/headless/bootstrap/scheduler/agent/launcher/workflow callers, and the app's complete feature diff against base. The assessment also inspected actual composed-test assertions and barriers, the current uncommitted correction diff, and operator documentation. Searches found implementations and tests rather than relying on matching filenames. Large existing session/app modules were inspected by affected bodies and complete feature changes, not falsely described as fresh whole-repository line-by-line review. Prior independent reviews remain corroborating detailed branch/static evidence, not substitutes for this scan.

Routing: Python 3.11, asyncio/Pydantic support adapters, Typer, Textual, existing LangGraph/Faux, local immutable files and guarded subprocesses. Applied checkout completion/routing/shared ownership/testing/coding rules and Python conventions, with scoped type/docstring/declarative/environment and CLI/TUI guidance. Project-specific lifetime and atomic no-await contracts specialize generic service/extraction examples. No database, HTTP API, new CLI Command, provider integration, editor redesign or new process framework is required. Consulted root/documentation RESEARCH and KB Welcome, actual `slo/README.md`, and `slo/gotchas.md`; no KB or specification edits.

### Verified environment and unchanged source

- CWD: `/root/Code/slo-94-herdr-integration/slo`.
- Initial `pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`; executions verify **Python 3.11.7**.
- `make test-env`: **fallback**. Only tracked synthetic fallback values plus explicit interpreter/PYTHONPATH selection; no development env sourced or full environment printed.
- HEAD: `c2f9e562b5b0ad5b3f4592715d205bfaf756893d`; comparison base: `d0e3a756689f2675e5507034d43cd8b272d3c6b8`.
- Current **1,066** comprehensive inputs match independently reviewed181 bytes, both before the full gate and after verification. Digest: `8c576b3dda45c991f0ce1147ce7eab7570e1f30c087ea9b2c5fcd09a6cdea805`.
- Manifest includes nonignored tracked/untracked regular application files; excludes `docs/implementation/**`, the two mutable RESEARCH indexes and symlinks. This is not a claim to hash every file on disk or the receipts themselves.
- Current uncommitted `src/tui/app.py`, `tests/tui/test_startup_notice_cutoff.py`, and `tests/implementation_checks/test_conventions_audit_paths.py` are explicitly hashed in `inputs*.log`. Their fixes were included in all fresh gates, not inferred from HEAD.
- All prior dirty/untracked work was preserved. Only this report and `completion-183-receipts/` were authored; test caches are incidental.

## 2. Re-derived deliverables and status by layer

Paths in this table are application-root-relative. H = `src/agents/slo_agent/herdr/`; S = `src/agents/slo_agent/sessions/`; HT = `tests/agents/slo_agent/herdr/`. The full names are expanded in the implemented-files section and machine-readable inventory.

| # | Task / layer | Expected deliverable | Status | Actual implementation and verification evidence |
|---:|---|---|---|---|
| 1 | T1 DAOs | Closed frozen public/private/result/ticket/viewer shapes; private repr/validation safety; recursive pool immutability | Done | `H/dao.py`, `S/dao.py`; HT `test_daos.py`, `test_projection.py`. Snapshot cannot carry restore policy; operation/result and blocked-reason invariants enforced. |
| 2 | T1 identity | Complete ordinary validator extraction plus canonical UUID-only Herdr gate, without tightening ordinary slug resume | Done | `S/identity.py`, compatibility import `src/cli/headless_request.py`; identity, CLI restore and normal headless-request tests. |
| 3 | T1 formatting | Single exact half-up arithmetic owner and compatible footer delegates | Done | `S/token_format.py`, `src/tui/widgets/usage_status_bar.py`; token-format/footer regressions. |
| 4 | T1 persistence foundation | Secure distinct pane/restore leases; hashed durable per-source counters; restart/contention/overflow/corruption refusal | Done | `H/sequence_store.py`; sequence, short-read, lease-ambiguity/cleanup and failed-acquisition tests. No counter reset, lease stealing or second atomic writer. |
| 5 | T1 test infrastructure | Pre-import/per-test stripping, forced disable, independent temp-file/inode spawn capability and real-window blocker | Done | `tests/state_isolation.py`, `tests/conftest.py`; HT isolation/spawn tests and integration safety suite. Env enablement alone grants no executable permission. |
| 6 | T1 configuration | Tracked safe test fallback and documented runtime defaults | Done | `Makefile`, `environments/.env.template`; fallback verified, compact default/detail opt-in and startup disable documented. No assumed shipped tests.env. |
| 7 | T2 projection/gate | Inert construction/null, pure captured gate, numeric/fixed-only compact/detail projection, unknown omission | Done | `H/service.py`; gate/projector/profile tests. Disabled path avoids activation/capture/storage; invalid enabled configuration is unavailable, not platform fallback. |
| 8 | T2 reporting | Memory-only coalescing, bounded pending/save/binding slots and exact capture-generation save association | Done | `H/reporter.py:102–284,742–780`; save-worker/publication compositions. Same-capture G1 adopts newest display without another record; changed capture cannot adopt stale save. |
| 9 | T2 protocol | Claim/install/display and working/display/settled ordering; separate lifecycle/restore/display acknowledgements | Done | `H/reporter.py:296–471,473–740`; batch/accounting/operation-result suites. Failed display still permits truthful settlement; uncertain different-policy release blocks replacement. |
| 10 | T2 transport | One shared CLI lock/process, lock-inclusive timeout, mandatory synchronous admission immediately before tracked spawn | Done | `H/service.py:410–806`; real subprocess and G2 lock-contention tests. Reserved but stale A cannot enter executable after B supersedes it. |
| 11 | T2 cleanup | Bounded readers, terminate/kill/reap, repeated-cancel joins, sticky uncertainty, sealed drain before lease disposal | Done | `H/service.py`, `H/reporter.py:808–980`; transport lifetime/signals/retained/final-drain/failed-acquisition matrices. Intermediate default drained is not final disposal permission. |
| 12 | T2 diagnostics/privacy | Fixed throttled failures/recovery, sink isolation, no content/credential/private-path reporting | Done | Gate/transport/reporter diagnostic boundaries; privacy closure and composed sentinel tests. No credential resolution in public projection. |
| 13 | T3 store | Immutable random revisions, exact old policy, no latest pointer/overwrite/GC/history mutation | Done | `H/restore.py:112–251`; save/roundtrip/composition/crash tests. `AtomicFileWriter` reused, unchanged. |
| 14 | T3 security/bounds | Private modes, no-follow bounded reads, strict reference/session validation, nonblocking lock and refusal without eviction | Done | `H/restore.py`, `H/sequence_store.py`; restore security/boundaries/I/O/lease-retention/process tests. Load missing storage does not initialize it. |
| 15 | T3 CLI | Thin flag, canonical literal resume/conflict checks before runtime, safe fixed errors | Done | `src/cli/app.py`, `src/cli/typer_dispatch.py`; `tests/cli/test_herdr_restore.py`. Ordinary resume remains a separate compatible path. |
| 16 | T3 policy assembly | Exact saved configured pool/reasoning/paths; fresh validated mutable pool reconstruction; current trust/capability retained | Done | `TyperDispatch._load_herdr_session_config`, `_restore_model_pool`; CLI and two-process single/pool capability/trust tests. No ambient preference merge or automatic prompt replay. |
| 17 | T4 domain viewer | Per-parent one-shot immutable attempt ledger, live authority at shared lock, uncertain/known-pane retention | Done | `H/visualizer.py`; visualizer/authority/lifecycle/acceptance tests. No retry, pane close, focus, query or fabricated occupant. |
| 18 | T4 wire adapter | Exact captured-owner split/rename/run, strict bounded response parser and truthful submitted outcome | Done | `H/visualizer.py:187–260`; malformed/oversize/timeout/cancel tests. Rename rejection may continue; run admission is not paint/liveness. |
| 19 | T4 context | One lower-layer existing-context parser, used by both session eligibility and TUI loader | Done | `src/agents/slo_agent/orchestrator/context_reader.py`, `src/tui/workflow_visualizer_loader.py`; context-reader/loader tests. No reverse TUI import or new history schema. |
| 20 | T5 session capture | Committed exact policy/eligibility generation, immutable snapshots, no per-event path/credential I/O | Done | `S/service.py:2782–3057` plus policy/history hooks; capture/mutation/publication tests. Usage/name/fallback are not configured-policy changes. |
| 21 | T5 provenance | Before/after standard attachment proof, exact tool identity, general/custom/mutated input ineligible | Done | `src/agents/slo_agent/orchestrator/bootstrap.py`, `S/service.py:2243–2297`; bootstrap/provenance tests. Matching names alone are insufficient. |
| 22 | T5 lifecycle/usage | Accepted work remains working through tools/retries; final completed usage before settlement; token-scoped attention | Done | `S/service.py` run/preparation/compaction scopes, `S/dao.py`, `src/agents/slo_agent/agent.py` completed-update handoff; attention and usage-trace cancellation tests. Session remains cumulative accounting owner. |
| 23 | T5 session lifetime | Single retained activation/close, revocation, all-owner cleanup, candidate-only disposal and final retained drain | Done | `S/service.py:2382–2780`; session lifetime, failed-acquisition and retained-drain tests. Remote uncertainty and actual local resources remain separate. |
| 24 | T5 headless | Adopted reporting lifetime/outer final cleanup; original result and stdout retained; no native-restore advertisement | Done | `src/cli/headless.py`; headless Herdr/retained/regression tests. Optional diagnostics cannot replace the run result. |
| 25 | T5 child integration | Scheduler removes exactly case-insensitive HERDR_ prefix; existing subagent/detached/relaunch exclusion preserved | Done | `src/scheduling/runtime/subprocess_runner.py`, existing orchestrator spawn-env consumers; actual synthetic child environment tests. Parent environment unchanged. |
| 26 | T5 TUI replacement | Prepare candidate before destructive close; deep-copy pool; irreversible joined adoption and captured old-ID lease transfer | Done | `src/tui/app.py:2435–2765`; replacement/stale-release/viewer-replacement tests. Precommit failure preserves old session; uncertain close suppresses every successor integration. |
| 27 | T5 TUI lifetime | Monotonic shutdown/startup continuation checks, timer rollback, retained quarantine and independent cleanup despite notice errors | Done | `src/tui/app.py:611–797,994–1284`; activation/init/all-owner/quarantine suites and current startup16 regressions, including final summary-to-scroll guard. |
| 28 | T5 inbox/execution | One nonawaiting final prompt-registration cutoff; claim/advance rechecks; refused claim retained without ack/replay | Done | `src/tui/app.py:1355–1493,1756–1811,3506+`; inbox cutoff/disposition/prompt-registration tests. Pre-cutoff registered execution retains its existing policy. |
| 29 | T5 both viewer paths | Attached/detached ingress → one tracked app registry → one destination; joined platform thread; no late notices/fallback | Done | `src/tui/app.py:1531+,2867+`, `src/tui/visualizer_launcher.py`; mounted attached/detached/platform/registry tests and unified journey. |
| 30 | T5 parser/rendering | Single service raw-result parser, typed effects, schedule-only callback and shared completed-outcome notices | Done | `src/tui/workflows/{dao,service,renderer}.py`; workflow service/renderer/receive-path tests. Old renderer parser/launch callable/literal result alias removed. |
| 31 | T6 full flow | Real PromptInput/Faux/tool/retry/pool usage/history/reporting, rename/model/new and both viewers | Done | `tests/integration/test_herdr_full_flow.py`, `herdr_unified_141.py`; real graph/tool and captured fake argv assertions, not helper-only selection. |
| 32 | T6 lifetime matrix | Complete 4 triggers × 8 phases × 2 diagnostics; preserve distinct G1/G2/inbox/init/quarantine proofs | Done | `tests/integration/test_herdr_lifetime_matrix.py`: **64 distinct collected/executed cases**. Real lock/spawn/save/app-worker barriers; ownership and no-late-credit assertions. Relocated module preserves full_flow spec obligation. |
| 33 | T6 process restore | Two independent OS interpreters, actual parser/dispatch/mounted TUI, exact saved policy/current history, no automatic execution | Done | `tests/integration/test_herdr_two_process_restore.py`, `herdr_restore_process_entry.py`, bootstrap helper. Eight policy/capability combinations plus safety bootstrap; independent PID and literal policy oracle. Source shim is explicitly not installed/native-restart certification. |
| 34 | T6 parity/privacy/safety | Disabled/outside semantic parity, sentinel scans, registered executable positive/negative controls and temp-only process ownership | Done | Full-flow/parity/transport-observer helpers, `test_herdr_restore_harness_safety.py`, root guards. Trusted-fixture accident prevention, not an adversarial OS sandbox. |
| 35 | T6 verification/review | Full non-E2E, smoke, unmodified lint, relevant format checks and independent review; no baseline waiver | Done | Fresh183 gates below; Review182 complete; current static count zero. Existing warnings disclosed, no fixes/suppression added here. |
| 36 | T6 documentation | Setup/privacy/retention/rollback, runtime owners, claimed-item limitation and honest live-evidence boundary | Done | `README.md`, `docs/INSTALL.md`, `AGENTS.md`, root/docs RESEARCH, environment template. Earlier status headings remain historical; this assessment supplies current completion state. |

### Numeric acceptance cross-check

Actual code retains one CLI child; 1-second lock-inclusive deadline, 0.25-second termination grace, 2-second remote-close budget; 2-second refresh/5-second TTL; 18 owned inventory keys, at most16 per patch; token limits80 characters **and**128 UTF-8 bytes with whole-token omission; strict non-bool counters through `2**63-1`; restore65,536 bytes/1,024 entries/67,108,864 total bytes, bounded1,025-entry scan and three allocation attempts; 0700 directories/0600 records; argv64 arguments/8,192 bytes; pane ID128 bytes. The32-key remote retained-pane capacity is documented, not something Slo can locally guarantee for unrelated reporters. Offline boundary tests exercise the chosen contract; remote enforcement is deferred.

## 3. Percentage calculation and infrastructure readiness

Weights reflect coupled implementation effort rather than file count. T2's concurrency/protocol and T5's lifecycle integration outweigh the smaller pure foundations and viewer extraction. Every row within each task receives an equal share of that task's weight. Done=1, Partial=0.5, Not Started=0.

| Task | Deliverable rows | Weight | Earned | Offline status |
|---|---:|---:|---:|---|
| T1 | 1–6 | 10 | 10 | Done |
| T2 | 7–12 | 25 | 25 | Done |
| T3 | 13–16 | 15 | 15 | Done |
| T4 | 17–19 | 10 | 10 | Done |
| T5 | 20–30 | 25 | 25 | Done |
| T6 offline | 31–36 | 15 | 15 | Done |
| **Total** | **36** | **100** | **100** | **COMPLETE offline** |

Completion = `sum(weight × score) / 100 × 100 = 100%`; incompletion = `100 − completion = 0%`. Unweighted cross-check: `36 / 36 = 100%`. Deferred live criteria have no weight in this operator-accepted denominator; no percentage of the original combined offline+live release scope is asserted.

Infrastructure is scored separately across eight equally weighted prerequisites, all present: (1) approved interpreter/dependencies and real test commands; (2) shared typed identities/formatting; (3) unchanged atomic writer and private lease/storage support; (4) existing history and exact resume resolution; (5) session usage/model/trust ownership; (6) CLI/TUI/workflow entry seams; (7) fake-only isolated process/filesystem/Faux/Textual harness; (8) executable static/regression gates and operator guidance. **8/8 = 100% offline infrastructure readiness.** This does not mean a live Herdr installation, pane environment or native Windows runtime has been certified.

## 4. Implemented files

### Runtime owners (complete feature ownership list)

- `src/agents/slo_agent/herdr/__init__.py` — support package.
- `src/agents/slo_agent/herdr/dao.py` — frozen public/private/protocol contracts.
- `src/agents/slo_agent/herdr/service.py` — gate/null/projector/join/shared CLI transport; lazy compatibility exports.
- `src/agents/slo_agent/herdr/reporter.py` — sole save/report/revision/binding/acknowledgement scheduler. Splitting it from the illustrative service.py preserves one owner, not a duplicate implementation.
- `src/agents/slo_agent/herdr/sequence_store.py` — shared lease mechanism, pane namespace and durable counters.
- `src/agents/slo_agent/herdr/restore.py` — immutable private revision policy.
- `src/agents/slo_agent/herdr/visualizer.py` — one-shot per-parent pane adapter.
- `src/agents/slo_agent/sessions/dao.py`, `identity.py`, `token_format.py`, `service.py` — session vocabulary, canonical identity, shared formatter and publication/lifetime authority.
- `src/agents/slo_agent/agent.py` — completed usage captured before trace awaits and drained once into session totals.
- `src/agents/slo_agent/orchestrator/bootstrap.py`, `context_reader.py` — standard-attachment provenance and shared private context reader.
- `src/cli/app.py`, `typer_dispatch.py`, `headless_request.py`, `headless.py` — flag/admission/assembly/identity compatibility and headless cleanup.
- `src/scheduling/runtime/subprocess_runner.py` — inherited pane-key exclusion.
- `src/tui/app.py`, `visualizer_launcher.py`, `workflow_visualizer_loader.py` — captured app lifetime, one destination and shared reader use.
- `src/tui/workflows/dao.py`, `service.py`, `renderer.py` — typed effect result, sole raw parsing boundary and outcome presentation.
- `src/tui/widgets/usage_status_bar.py` — compatibility formatting delegates.

### Supporting files and tests

- `tests/state_isolation.py`, `tests/conftest.py`, `Makefile`, `environments/.env.template` — safe defaults/guards.
- `tests/agents/slo_agent/herdr/` — concrete schema, projection, reporting, lease, restore, transport, session and viewer decision-path suites, including ownership corrections.
- `tests/agents/slo_agent/test_session_identity.py`, `test_token_format.py`, `test_usage_trace_cancellation.py`, session/usage tests and `orchestrator/test_context_reader.py`, bootstrap/spawn-env tests — extracted compatibility and surrounding contracts.
- `tests/cli/test_herdr_restore.py`, `test_headless_herdr.py`, `test_headless_retained.py`, existing CLI/headless tests; `tests/scheduling/test_runtime_helpers.py` — real entry and child-lifetime boundaries.
- `tests/tui/test_herdr_*.py`, `test_startup_notice_cutoff.py`, `test_visualizer_launcher.py`, `test_workflow_visualizer_loader.py`, `test_workflow_receive_path.py`, `tests/tui/workflows/` — mounted lifetime and both callers.
- `tests/integration/test_herdr_full_flow.py`, `test_herdr_lifetime_matrix.py`, `test_herdr_two_process_restore.py`, `test_herdr_restore_harness_safety.py` — composed acceptance.
- `tests/integration/herdr_parity_124.py`, `herdr_restore_process_bootstrap.py`, `herdr_restore_process_entry.py`, `herdr_transport_observer.py`, `herdr_unified_141.py` — acceptance collaborators, not alternate production owners.
- `tests/implementation_checks/test_conventions_audit_paths.py` — current tracked-discovery/count/missing-path mutation regression.
- `pyproject.toml`, `poetry.lock` — existing test/static stack plus the reviewed typed YAML stub dependency; no dependency mutation in183.
- `README.md`, `docs/INSTALL.md`, `AGENTS.md`, `RESEARCH.md`, `docs/RESEARCH.md` — product/runtime/operating documentation.

For every exact changed runtime, test, static-repair and supporting filename relative to the feature base, see [`completion-183-receipts/implemented-and-regression-files.txt`](completion-183-receipts/implemented-and-regression-files.txt). That inventory includes adjacent A–E regression repairs; they are not additional product deliverables or evidence of an editor redesign. `current.sha256` additionally captures current untracked runtime inputs. Existing `history/atomic_io.py`, history/inbox storage semantics and orchestrator child-environment ownership remain reused, not new duplicate owners.

## 5. Fresh verification — current worktree

All receipts are in [`completion-183-receipts/`](completion-183-receipts/). Each runner invocation records exact command, cwd, interpreter, fallback variant, complete output, exit, and independent post-run coreutils output/exit. Commands were not edited to suppress errors.

| Label / actual command | Fresh result |
|---|---|
| `smoke`: unmodified `make smoke` | **288 passed**,2 warnings,3.24s; exit0 |
| `lint`: unmodified `make lint` → `poetry run mypy src/ tests/` | **Success: no issues found in816 source files**; exit0 |
| `feature`: explicit12-path pytest selection in `feature.command` | **1850 passed**,281 warnings,456.21s; exit0; no reported skips/deselections |
| `collection`: canonical lifetime matrix `--collect-only -q` | **64 tests collected**; exit0; all64 also executed in feature/full gates |
| `full`: unmodified `make test` | **8773 passed,19 deselected,780 warnings**,1174.99s; exit0 |
| `black`: scoped source/Herdr tests/current correction files, exact argv retained | **93 files would be left unchanged**; exit0 |
| `inputs`, `inputs-final`: fresh enumeration and SHA256 reconciliation | **1066 identical inputs**, same digest and current uncommitted hashes; exit0 |
| `diff-check`: `git diff --check` | silent; exit0 |
| `dpkg -V coreutils` after every runner execution | **silent/exit0 throughout** |

Counts overlap and must not be summed. The19 exclusions are the unchanged `not e2e` full-gate deselections, not skipped offline matrix cases. Warnings remain visible: dependency deprecations and existing unawaited AsyncMock RuntimeWarnings; warning-free execution is not claimed. Fresh full8773 agrees with the inspected179 receipt, but the table is this assessment's own execution, not reused author evidence. Black93 is a scoped fresh check, not a claim to rerun every historical changed-file formatting command.

No real provider, Herdr daemon or terminal window was used. Root fixtures independently refuse unregistered executable spawning and strip inherited settings. Two-process tests use test-owned source shims and synthetic state; their assertions are not native installed-launcher equivalence. No safety guarantee against malicious same-process Python or arbitrary escaped process groups is inferred from those trusted fixtures.

## 6. Deferred versus incomplete

### Accepted offline incompletion

**None.** No Partial or Not Started row remains in the accepted offline checklist, so no implementation guide, sample patch or missing-work dependency graph is required. Inventing a fix plan for deferred live observation would incorrectly turn the accepted scope decision into a blocker.

Completed dependency graph:

```text
T1 foundations [Done]
  → T2 reporter/transport [Done]
      ├→ T3 immutable store/CLI [Done] ─┐
      └→ T4 one-shot viewer/reader [Done] ─┤
                                          → T5 session/app integration [Done]
                                              → T6 offline proof/docs [Done]
                                                  → independent Review182 [READY]
                                                      → Completion183 [COMPLETE offline]
```

### DEFERRED SCOPE — not certified, not offline blockers

| Deferred criterion | What offline evidence establishes instead |
|---|---|
| Installed plain `slo` launcher equivalence | Exact advertised argv, PATH admission and actual source parser/dispatch in isolated interpreters; no installed pipx/native launcher proof. |
| Actual supported Herdr version and wire acceptance | Exact fake-executable argv/parser/bounds; no real version or interoperability claim. |
| Native Herdr server restart | Two-process exact saved policy/current history/no-auto-replay proof; no server restart performed. |
| Live metadata/sidebar clear, TTL, wait and notification behavior | Local ordering, explicit clears, refresh cadence, fixed attention and omission rules; no actual remote expiry/wait observation. |
| Graceful remote release and restore clearing | Reserved one-attempt release/accounting and local immutable-file retention; no live clearing confirmation. |
| Attached/detached sibling placement, no initial focus theft, manual reuse and retained panes | Both real app ingress paths, captured-parent argv and one-shot ledger; no operator pane/layout acceptance. |
| Actual viewer paint/liveness | Only truthful `submitted`/manual outcomes; no inference from queue submission to process readiness or painted UI. |

If later authorized, the deferred observation chain is disposable-session authorization → exact installed versions/wire → live metadata and native-restart/release → both viewer/pane/paint acceptance → authorized cleanup receipts. This is a future acceptance chain, not missing offline implementation or permission to execute it now.

### Explicit limitations and nonblocking follow-ups

- Persistent ambiguous local resources can intentionally keep graceful teardown pending; successful local drain does not erase remote uncertainty.
- No automatic claimed-message replay, reference eviction, pane discovery/focus/retry/close, cross-process viewer deduplication or old-version new-flag compatibility is promised.
- Native Windows security/locking/runtime execution is not certified by these Linux tests; unsupported safety paths refuse rather than weaken protections.
- The prior review's low-priority wording/stale-comment/relocated-ignore and receipt-navigation cleanup remain nonblocking maintenance, not unfinished feature behavior. No new checker exclusion or waiver was introduced here; full lint is genuinely green.
- Security132 remains separate/open; reporting privacy cannot be used as a claim that all ordinary Slo tool-error channels redact every secret.
- No release, external CI, commit/push/MR or merge verdict is issued.

**Final: COMPLETE for the accepted OFFLINE scope, with the named live criteria DEFERRED and compatibility UNVERIFIED.**
