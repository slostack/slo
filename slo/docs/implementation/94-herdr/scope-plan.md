# Herdr full-scope prerequisite plan

Status: **READY — read/analysis plan only**, 2026-10-17. T1–T6 implementation remains pending. This is not independent implementation review, a green static-gate claim, or release acceptance.

## Authority and complete ingestion

Canonical read-only source root: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/` (abbreviated H below). No source specification was edited. Current checkout: `/root/Code/slo-94-herdr-integration/slo`, branch `feature-94-herdr-integration`, HEAD `d0e3a756689f2675e5507034d43cd8b272d3c6b8`.

Read the following complete documents, including examples, corrective prose, test ledgers and exact task attachments:

| H-relative file | Lines | Explicit read coverage |
|---|---:|---|
| overview.md | 239 | 1–239 |
| 94.b.1-herdr-reporting-adapter.md (B) | 2221 | 1–655, 656–1055, 1056–1655, 1656–2221; first oversized read was completed from its actual truncation boundary |
| 94.b.2-session-publication-and-native-restore.md (C) | 2175 | 1–450, 451–1000, 1001–1600, 1601–2175 |
| 94.c.1-herdr-workflow-visualizer-and-acceptance.md (D) | 711 | 1–711 |
| tasks.md | 3816 | 1–650, 651–1450, 1451–2250, 2251–3050, 3051–3816 |
| SLO_HERDR_INTEGRATION.md | 344 | 1–344 |
| SLO_HERDR_PUBLICATION_CONTRACT.md | 353 | 1–353 |

Total seven-document ingestion: **9,859 lines**, not an overview-only read. Also read H/review-evidence/{context-bundle.md,author-self-check.md,independent-review-turn4.md,task-breakdown-report.md,task-sample-inventory.md,finalization-receipt.md,workflow-summary.md} and the parent `../request.md`. The accepted turn-4 review closes original privacy/isolation, callback, accounting, revocation, retention, shutdown and diagnostic findings; it approves specification breakdown, not shipped behavior. Earlier REVISE investigations are historical provenance, not alternative current contracts. No historical document probe was rerun or counted as a product test.

Precedence: current user constraints → project contracts → overview resolved decisions and final B/C/D corrective prose → exact task allocation → subordinate historical source recommendations. Before-code stays before-code. A necessary normative change must return to author/reviewer; a ticket cannot silently change a contract. The current request permits only these prerequisite artifacts, not code or tests. Applicable routing is frozen separately in `routing.md`.

## Goal, boundaries and ownership

Optional observation must not control execution. Session commits supply safe facts and an exact private immutable capture. Reporter owns saves, generations/revisions matching, report order and remote-effect accounting. Shared transport owns one lock/process and cleanup; command owners decide admission synchronously under that lock. Restore store owns secure immutable records, not history. Existing app owns selected-session lifetime and final prompt registration. Existing workflow service owns raw parsing; existing launcher chooses destination. No second token counter, process manager, inbox coordinator, UUID parser, atomic writer or launch subscriber.

Excluded: separate `../tui` redesign/TCSS/input geometry, Slotui, provider behavior changes, upstream Herdr, HTTP/direct sockets, databases/migrations, pricing, automatic pane focus/replacement/close, background-job restore, automatic claimed-message recovery and restore-file GC. Required C lifetime/inbox edits in `src/tui/app.py` ARE Herdr scope; unrelated styling/selection/auth redesign is not.

## Actual six-task dependency graph

```text
T1 safe foundations
  └─T2 reporter + shared CLI transport
       ├─T3 immutable restore + CLI admission─┐
       └─T4 one-shot viewer + context reader──┤
                                             T5 session/app integration
                                               └─T6 composed proof/docs/live gate
```

Edges: T1→T2, T2→T3, T2→T4, T3→T5, T4→T5, T5→T6. Two critical prerequisite chains: T1/T2/T3/T5/T6 and T1/T2/T4/T5/T6. Only T3/T4 have disjoint parallel write sets; this statement authorizes no dispatch. Shared declarations land in T1; T2 uses injected store; T4 injected transport/authority. No enabled assembly until dependencies land in T5. One sequential owner must retain all coupled T5 session/app changes.

## Bounded coding assignments (future authorization only)

Every numbered increment below means failing decision-path test → smallest implementation → focused green → surrounding tests, not bulk writing the whole task. Approximately 50 implementation lines maximum between tests. Read actual affected owners/tests before each increment; old spec source line numbers are navigation, not proof that current code is identical.

### T1 — Establish safe tests and shared foundations — PENDING

1. Extend `tests/state_isolation.py` pre-import stripping and `tests/conftest.py` per-test isolation; force disabled, strip case-insensitive HERDR prefixes and metadata profile; preserve terminal guard. Implement temp-owned registration/identity/containment guard. Finish transport wrapper in T2 before any activation test.
2. Add final shared schemas in `src/agents/slo_agent/herdr/{__init__,dao}.py`: public tokens/snapshot/config, private frozen capture/pool/reference/record/publication/binding/tickets, result/close outcomes, protocols and viewer request/outcome/attempt. Session attention/provenance vocabulary lives only in `sessions/dao.py`. Required Pydantic fields retain privacy and descriptions.
3. Move full validator closure to `sessions/identity.py`, keep CLI compatibility import and ordinary slug normalization; add one strict canonical UUID predicate. Move exact half-up formatter to `sessions/token_format.py`, retain footer delegates.
4. Add `herdr/sequence_store.py`: one HerdrFileLease mechanism, secure distinct pane/restore scopes, hashed pane namespace counters, durable reservation/overflow/refusal. Reuse unchanged AtomicFileWriter.
5. Update only tracked Makefile test export/fallback and `environments/.env.template`; never invent `environments/template.env`, edit shell/installer or rely on untracked tests.env shipping.

Tests: `herdr/test_test_isolation.py`, `test_projection.py` DAO boundary, `test_sequence_store.py`, `test_token_format.py`, existing footer/headless-request tests. Prove temp-safe registration refusal, zero default spawn, strict immutable/state invariants, exact formatting and real process lock contention/restart. T1 alone does not claim complete activation safety until T2 wraps the real boundary.

### T2 — Build bounded reporting and shared CLI transport — PENDING, requires T1

1. `herdr/service.py` pure gate/null/projector and fixed-only diagnostics; disabled build/activation does zero I/O/capture/probe. Complete fake-only `_spawn` guard and negative mounted/headless proof.
2. Shared transport with lock-inclusive deadline, mandatory admission, tracked spawn, bounded concurrent readers, owned-group terminate/kill/reap and invocation-local outcome.
3. Reporter bounded pending/save/reservation/binding slots, exact save association (G1), synchronous publication and latest revision continuation; no credential lookup.
4. Batch ordering/semantic lifecycle ack/restore ack/display ack; all ticket families, durable sequence gaps and stale admitted effect accounting; real-lock G2 proof.
5. Activation release, two-second refresh/five-second TTL, close/revocation, sticky uncertainty, sealed transport drain before lease release; C's reporter/transport final local-drain methods stay here.

Tests: full B 7.11 method-to-branch ledger plus final helper additions and B 7.13; `test_reporter.py`, `test_cli_transport.py`, complete projection/isolation tests. Do not replace real-lock/process evidence with recording invoke mocks. No normal session activation yet.

### T3 — Immutable restore and CLI admission — PENDING, requires T2

1. `herdr/restore.py` inert store; secure nonblocking lock, immutable absent-name allocation, bounded quota/read, fixed errors, existing atomic writer. No latest pointer, overwrite, deletion, migration or history creation.
2. `src/cli/app.py::_default` thin `--herdr-restore`; `typer_dispatch.py::tui` canonical literal UUID + resume/conflict checks before construction; exact private load and new validated mutable pool reconstruction, no ambient preference merge.
3. Real file/lock/crash/durability/security/quota tests and CliRunner/dispatch compatibility. Two-process mounted restore follows in T6.

Tests: `herdr/test_restore.py`, `tests/cli/test_herdr_restore.py`, existing CLI/headless-request regression suite. No session/app/shared-DAO edits in this lane; no new Command class.

### T4 — One-shot viewer and context reader — PENDING, requires T2

1. Extract `orchestrator/context_reader.py::OrchestratorContextReader.load`; rewire `tui/workflow_visualizer_loader.py` and remove duplicate parser. Existing layout/schema/file remain unchanged.
2. `herdr/visualizer.py` strict split JSON parser, exact builders and immutable per-parent attempt ledger with live reporter authority under shared transport lock.
3. Shared pending-task cancellation/done-callback identity removal; retain uncertain split/known pane and never resend run. No focus/query/replacement/close behavior.

Tests: `herdr/test_visualizer.py`, `orchestrator/test_context_reader.py`, loader regressions and real shared-lock revoked split/rename/run composition. No session/app activation or T3 edits.

### T5 — Session, app and both viewer entry paths — PENDING, requires T3 AND T4

Single integration owner, sequential bounded increments:
1. Session capture/eligibility/generation and operation/attention tokens at actual usage/policy/history/run commits; no per-event disk/credential/model construction. Standard bootstrap before/after provenance in `orchestrator/bootstrap.py`; no general `standard=True` shortcut.
2. Session activation/close/suppression/retired drain and headless outer-finally ownership, preserving original results/JSONL/cancellation. Scheduler child copies inherited environment and removes only HERDR-prefixed names; preserve existing orchestrator allowlist.
3. App `/new` candidate preparation and candidate-only pool disposal, deep-copy old pool, irreversible shielded close/adopt, captured old-ID inbox lease transfer and sticky successor suppression. Preserve existing workspace/plugin `/new` policy.
4. Monotonic mount/unmount/replacement callbacks, timer rollback, retained failed handles, best-effort notices and one strongly retained quarantined session. Join replacement outside submission gate; persistent undrained teardown stays pending.
5. Actual inbox claim→advance→delivery→ack cutoffs and both final prompt-task assignments consolidated into `_register_prompt_task`; no await/hook after final closing check. Preserve existing pre-registered execution/abort policy and four delivery modes; no automatic reclaim.
6. Both existing viewer callers use same tracked schedule registry and async destination selector; joined platform thread; captured-session late-result suppression. Workflow service returns existing typed effects; delete renderer raw parser, old literal alias and old launch callable together.

Files: `sessions/service.py`, `orchestrator/bootstrap.py`, `cli/headless.py`, `scheduling/runtime/subprocess_runner.py`, `tui/app.py`, `tui/visualizer_launcher.py`, `tui/workflows/{service,renderer}.py`. Tests: new session publication/lifecycle/visualizer suites plus exact T5 modified-test list in H/tasks.md. Mandatory C 7.9–7.14 ledgers and D caller/platform tests are not optional. No TCSS edits.

### T6 — Composed acceptance and release evidence — PENDING, requires T5

1. `tests/integration/test_herdr_full_flow.py`: real PromptInput/Faux/session/storage/transport journey, disabled parity, privacy scans, G1/G2 composition and all 64 cutoff matrix cases.
2. Two actual isolated OS processes: first real current history/private capture/advertised argv; second actual parser/dispatch + headless-mounted TUI; exact policy/current history, changed ambient prefs irrelevant, no duplicate prompt/tool.
3. Full regression/static gates and precise receipts; resolve failures without suppressions/waivers; independent full-scope implementation review and fresh completion assessment later.
4. Update AGENTS.md, docs/RESEARCH.md, root RESEARCH navigation if needed, README.md, docs/INSTALL.md: ownership, setup/privacy, immutable retention, claimed-item limitation, rollback and actual compatibility evidence only.
5. Separately authorized live supported-release acceptance. Offline pass is not live acceptance.

## Requirements and acceptance checklist

All product evidence below is **pending**. IDs preserve H/review-evidence/task-breakdown-report.md; R23–R25 include historical specification-phase obligations rather than new runtime features.

| ID | Required result / check | Task owners |
|---|---|---|
| R1 | Optional/disabled zero work; stalled CLI never delays Faux completion; fixed diagnostic faults isolated | T1,T2,T5,T6 |
| R2 | Existing editor journey and pane schematic; actual operator pane approval separately | T6 |
| R3 | Atomic private handoff, reporter sole save scheduler, never public event/history capture | T1,T2,T5 |
| R4 | Exact config generation distinct from display revision and catalog generation | T2,T5 |
| R5 | G1 same-capture save reused with newest display after barrier | T2,T6 |
| R6 | Recursive immutability and bounded pending/save/binding/reservation slots | T1,T2,T5 |
| R7 | Four-provider synthetic sentinels and private paths absent from public channels; zero credential lookup | T1–T6 |
| R8 | Immutable exact revision with current history; security/quota/crash matrix and two-process restore | T3,T6 |
| R9 | Remote uncertainty separate from retained resources; seal/drain/unlock and quarantine | T2,T5,T6 |
| R10 | Lock acquired → synchronous owner admission → tracked spawn, no intervening await | T2,T4,T6 |
| R11 | Cancellation joins owned work; sequence gaps legal; stale effects do not ack newer facts | T2,T4,T5,T6 |
| R12 | Every claim/lifecycle/install/clear/set/release and viewer operation gated | T2,T4 |
| R13 | G2 viewer lock → A durable/queued → B → unlock: no A executable entry | T2,T4,T6 |
| R14 | Session working across tools/retries; final usage before settled; attention tokens; unchanged execution | T5,T6 |
| R15 | Actual scheduled child removes HERDR only; subagent/detached/relaunch exclusions preserved | T5 |
| R16 | Full validator extraction; canonical UUID Herdr-only restriction, ordinary slug resume unchanged | T1,T3,T4,T5 |
| R17 | Standard bootstrap provenance, not matching prompt/tool names; custom/mutated input ineligible | T1,T5 |
| R18 | One destination and one-shot attempts; manual reuse; submitted ≠ painted/running | T4,T5,T6 |
| R19 | Lower-layer context reader with one parser, no reverse TUI import | T4 |
| R20 | Candidate rollback/adoption, session-keyed lease transfer, shutdown delivery cutoff/claimed retention | T5,T6 |
| R21 | Exact numeric bounds; TTL not atomic ownership; no eviction/retry of uncertain pane effects | T1–T4,T6 |
| R22 | Declarative ownership, complete branch ledgers, static/full gates, no duplicate sample classes | All |
| R23 | Preserve read-only source and separate TUI; current chapter precedence | All |
| R24 | Prerequisite phase no implementation/live/commit/external actions | This deliverable |
| R25 | Consume accepted independent spec review; later independent implementation review still required | Later review |
| R26 | Prompt-input redesign intentionally excluded | None |

Top-level AC coverage: B1 nonblocking enqueue→T2/5/6; B2 cleanup→T2/5; B3 counters→T1/2; B4 sources/clear/TTL→T2/6; B5 formatter→T1; B6 privacy→all; B7 fake versus live→T2/6. C1 session authority→T5; C2 original-result isolation→T5/6; C3 exact restore→T3/5/6; C4 ordered /new→T5; C5 shutdown claim/task disposition→T5/6; C6 disabled parity→T1/5/6. D1 both paths→T4/5/6; D2 one-shot→T4/5; D3 cancellation/process ownership→T2/4/5; D4 offline/live evidence→T6; D5 independent pane acceptance→T6.

### Non-negotiable numeric and semantic checks

- One CLI child shared by reporting/viewer; 1s deadline includes lock wait; .25s terminate grace; 2s CLI close budget excludes filesystem and OS reap latency.
- Refresh 2s / TTL 5s; 18 owned keys; at most 16 patch keys, 32 retained pane keys; clear absent inventory before set; shutdown clear 16+2 only after confirmed release.
- Values nonempty, no category-C/non-ASCII-space whitespace, ≤80 characters AND ≤128 UTF-8 bytes; omit entire unsafe/overlong token. Omit model/provider/effort/session free text unconditionally. Seven fixed reasoning levels and four fixed attention reasons only.
- Counter strict non-bool integer 0..2^63−1; persist before every send; never reset corrupt state or send unreserved release.
- Restore ≤65,536 bytes; ≤1,024 records and 67,108,864 total bytes; inspect at most 1,025 entries; three random allocation attempts; 0700 owned directory/0600 record; no links/nonregular/insecure targets or automatic eviction.
- Restore argv exactly `slo --resume UUID --herdr-restore r1-<32 lowercase hex>`; plain slo on PATH, ≤64 args/8192 UTF-8 bytes including separators, no apostrophes/controls/private paths. Same SLO_HOME/current default history required.
- Claim→restore→display bootstrap; existing working before display; display attempt before settled even after failed display. Same-capture uncertain restore preserves confirmed identity but not install ack. Different config requires confirmed release before replacement display.
- Viewer split uses captured owner `--pane`, not focus/current; strict `.result.pane.pane_id`, ≤128 UTF-8 bytes; keep one attempt per parent/lifetime, no retry even on uncertain split. Run success is queue submission only.
- Refused inbox delivery stays claimed without ack or automatic replay; admitted pre-cutoff task keeps its existing execution policy. Quarantine retains one owner across repeated /new and suppresses every successor integration; persistent local drain failure leaves graceful teardown pending.

## Exact sample attachment locations

All attachments are physically in **H/tasks.md**, not separate runnable implementation files. Read canonical surrounding prose before using them. Inventory: **H/review-evidence/task-sample-inventory.md** (JSON companion contains hashes). All 72 allocated fences were read above, including all 69 current B/C/D/overview fences and three historical context excerpts.

| Task | tasks.md lines | Sample IDs |
|---|---|---|
| T1 | 286–445 | B01,B03,B07,B23,C27 |
| T2 | 446–1905 | B04,B06,B08–B22,B24,B25,C28,C29 |
| T3 | 1906–2108 | C03,C05,C06,C07,I04 |
| T4 | 2109–2400 | D04–D07 |
| T5 | 2401–3720 | B02,B05,C01,C02,C04,C08–C26,C30,D01–D03,D08,I02,I03 |
| T6 | 3721–3816 | B26,C31,D09,O01–O03 |

Ten inventoried exclusions are intentional: I01 early restore journey; I05 incomplete tree; I06 partial gate; I07 unsupported --model; I08 --current/focus/reporter map; P01/P03 free-text model display; P02 stale usage builder; P04 old report argv/patch; R01 unrelated editor schematic. Reading these legacy documents does not reinstate their superseded requirements. Repeated class snippets extend the SAME owner, never successive subclasses. Source specs/attachments stay read-only.

## Safety and execution rules

No coding/spawn/commit/global preference change/other-worktree modification is authorized by this prerequisite. Future coding stays in the dedicated feature checkout and uses the unchanged routing record. Preserve baseline evidence; do not rerun long gates just to reconfirm unchanged input. Static failures are not green and not a reason to abandon independent reading. See assessment for bounded remediation versus genuine authorization boundaries.

Before future activation tests, land T1/T2 isolation: remove inherited HERDR variables before imports and per test, force disabled, guard actual transport spawn independently of env, permit only a fixture-registered NEW regular executable and output/barrier files under that test's resolved root; revalidate no links/traversal and device/inode before delegation. Every write must prove containment first. Keep real-terminal guard; use Faux/synthetic credentials, no live providers or Herdr. Only test-owned subprocesses may be terminated for crash/cleanup tests. After stubbing suites verify `dpkg -V coreutils` is silent; any host anomaly stops work. No system/PATH files, installer, shell profile, global preference or live workspace edits.

Each handoff carries task scope, exact chapter/attachment paths, unchanged routing.md, requirement/test map and executed command/output/exit/count receipts. A READY child exit alone is insufficient. Reserve independent full-scope review and fresh completion after integrated code/tests; revision invalidates affected later review. Counters remain turn 1 active, started 1/completed 0/historical partial 0, dispatches 3 consumed/17 remaining of 20, unlimited turns, retries 0; no reset.

## Live acceptance prerequisites and authorization

Not needed to finish this read/plan or begin offline coding. Required before release/compatibility claim. `/root/.local/bin/herdr` is a regular mode-755 executable; it has not been executed here and compatibility is unproved.

Obtain explicit authorization for a **disposable named `slo-herdr-smoke` session**, its server restart, and cleanup of only its created panes/processes/temp data. Read machine-guardian policy first; never restart the user's active Herdr server or `herdr-agents.scope`. Use temp SLO_HOME, disposable repo, installed plain slo on PATH, default history and synthetic/Faux provider harness; retain same SLO_HOME across restart. Record exact Herdr version (0.9.2+ is a target, not certification), documented commands and wire output safely.

Verify idle/working/auth-blocked and passive cooldown, numeric fallback telemetry/omitted labels, explicit clear/TTL and agent-wait semantics; native restart exact config/current history/no resubmission; separate graceful-release clearing; attached/detached correct sibling parent/no initial focus theft/manual reuse/retention; actual viewer paint distinct from run submission. Disabled and stalled/failing variants must preserve Slo. Record pane visual acceptance independently of excluded editor redesign. If permission or supported runtime is unavailable, report the live gate pending, never waived.
