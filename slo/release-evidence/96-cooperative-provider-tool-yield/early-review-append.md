# 96.a.2 — early review of metadata and restricted append-once

**Verdict: REVISE — three concrete restricted-API defects below.**

This is independent, bounded, read-only EARLY feedback inside Step 1, not final review, milestone acceptance or completion. No tests, collection, static checks, feature execution or nested agents were run. Only this new report was written; source, tests, existing reports, SLO.md and docs/ were not edited.

## Scope, authority and accounting

- Checkout: `/root/Code/slo-message-queue/slo`, baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`, branch `message-queue`. Inspected actual baseline-to-worktree diffs and new untracked tests, not just author summaries.
- Original specification: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`, principally §§4.3, 6.2 and 9/A8, with §2.4's explicit re-fsync requirement and §6.3 used to distinguish later raw-group validation.
- Read `implementation-history-metadata.md`, `implementation-cooperative-append.md`, `current-handoff.md`, `routing.md`, `acceptance.md`, raw receipts and relevant source/tests. README first; root RESEARCH.md is absent, so no project-memory content was inferred or created. Consulted KB Welcome, slo/README, gotchas and operational-reference.
- Reused routing with installed root `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`: exact `orchestration/workflows/code-test-review.md` early-feedback checklist; shared routing/review/ownership/testing; overarching solution-design, coding-rules, naming-and-clarity, test-verification-policy and declarative-method-structure; Python conventions/review, named arguments/types, docstrings and declarative specialization. No new framework, database or harness requirement. Personal presentation/diff skills are unrelated. This is not skills maintenance.
- **Actual ledger supplied by the operator: turn 4, this dispatch 8/20; prior partial-turn calls 7/4/4; 60-turn ceiling; seven execution retries (audit 1/provider 1/repair 2/proof 1/append 2); no abort.** `turn5-retry2-append-*` filenames are inaccurate turn labels, not evidence of a new workflow turn. Preserve the receipts; do not reset counts or count this early review as a completed pass.

The API has no active cooperative producers. Findings concern what its current public port accepts/certifies, not an assertion that live urgent delivery currently exercises these bugs.

## Findings — finite repair list

### R1 — High: equal-event retry certifies raw presence without re-fsync

**Source:** `src/agents/slo_agent/history/filesystem_store.py:635–650`, especially 647–650; raw reader at 552–589; line writer at 1548–1559. Both adapters reach this implementation.

**Requirement:** spec §2.4 append-once row explicitly requires “successful re-fsync certification, not raw-presence success”; §6.2.2/.5 and §9 A8 require a confirmed storage barrier under unknown write outcome.

**Failure scenario:** the first append writes and flushes a complete LF-terminated JSON line, but its `events.jsonl` fsync raises. Bytes remain readable. A later owner recovery retries the exact retained event. The raw scan validates the line and digest; it does not fsync an ordinary valid terminated line. `_append_once_sync` rewrites `session.json` and immediately returns `existing`. Fsyncing the metadata temp file is not fsyncing the event file. The retry therefore reports success without ever confirming durability of those bytes. This is a code defect now, not merely a deferred fault-injection test.

**Smallest correction:** keep the same owner/shared append mechanics and exact ID/digest comparison. Before existing-event success, explicitly certify the matching raw events file through a successful fsync while still serialized; only then complete the metadata repair/return. Failure must escape as `CooperativeYieldSettlementError`, without another line, a reconstructed event or automatic live retry. Preserve application-specific validation/error translation when changing shared mechanics.

**Closure evidence:** real tmp-owned files, both adapters: complete bytes surviving failed first certification; failed re-certification still raises; successful later certification returns the original sequence/ID/timestamp/digest with one raw line. Also cover loss of reply after successful fsync and stale metadata. Readback/dedup alone cannot prove this requirement.

### R2 — High: a “validated complete opening” need not contain a complete call array

**Source:** `src/agents/slo_agent/history/dao.py:280–305`; test helper `tests/agents/slo_agent/messaging/test_history_cooperative_append.py:64–92` and success test at 147–165.

**Requirement:** §4.3 requires the first opening to contain the full ordered `tool_calls` and arguments. §6.2 restricts the port to validated marked records, not arbitrary tool events.

**Failure scenario:** the present helper builds an opening for `('call-a', 'call-b')` with only `tool_call_id='call-a'`, name and content: `payload.tool_calls` is absent. The success test demonstrates that this is accepted and persisted. The validator checks membership, status, attempt/iteration and deterministic ID, but never checks the complete call array, names or argument mappings. Even a supplied empty/reordered/mismatching array passes these checks. This creates invalid canonical opening evidence through the restricted API itself; a future raw validator would have to reject the records the positive tests currently bless.

**Smallest correction:** validate the self-contained opening shape at admission: full ordered IDs matching metadata, complete names/argument mappings and agreement of the selected call with its payload fields. Build valid full-array positive fixtures, then add focused negative cases for missing/empty/reordered/malformed arrays and mismatched selected identity. Keep sibling agreement, first-anchor/provider-extension ownership and cross-record completeness in the planned raw-group owner; this finding does **not** demand implementing that whole validator here.

**Conventions:** put the event-validation behavior behind a cohesive existing/new class owner rather than expanding the newly added public free-function/helper chain. README §Style rules reserves free functions for tool bridges, graph nodes and test helpers; `validate_cooperative_history_event` and its module helpers at `history/dao.py:249–346` do not fit those exceptions. Preserve typed keyword calls and flat named validation steps; do not create a framework or one class per check.

### R3 — Medium: cooperative marker discrimination is asymmetric/incomplete

**Source:** `src/agents/slo_agent/history/dao.py:280–287,308–346`; no-start fixture `test_history_cooperative_append.py:95–110`.

**Requirement:** §4.3 closed metadata/version contracts and affirmative no-start reason/disposition; §6.2 restricted validated forms. The author report additionally promises `tool_group_v1` or `cooperative_yield_v1`, “not both.”

**Failure scenarios:**

1. On `run_retrying`, both known marker keys are rejected. On `tool_call`/`tool_result`, only `tool_group_v1` is inspected. Adding `cooperative_yield_v1` with schema 2, malformed contents or incompatible attempt identity still passes the marked-tool branch. Thus a known cooperative marker can be smuggled past its validator on the wrong event kind; unknown-version rejection is not universal at this boundary.
2. The no-start positive fixture has only `tool_group_v1.disposition='not_started'`; neither fixture nor validator supplies/requires the §4.3 `reason='cooperative_yield'` discriminator. The port therefore accepts an underspecified no-start event as canonical.

**Smallest correction:** centralize the allowed known-marker/kind combinations before dispatching validation. Reject conflicting or misplaced cooperative markers, including a null/unknown-version second marker, instead of ignoring them. Establish and enforce the canonical outer no-start reason/disposition location in the existing payload metadata shape, following existing `run_retrying` conventions; update fixtures accordingly. Do not indiscriminately forbid unrelated established metadata or require a new history kind. Add both-adapter rejection/readback tests proving refused candidates add no line and advance no cursor.

## Requested boundary checks: what is sound, and what is not yet proven

- **Metadata carriers:** strict/frozen/extra-forbid, canonical UUID/group derivation, nonnegative counters, bounded printable distinct IDs, aware UTC opening, closed status/disposition/reason vocabularies and group correlation are present. Individual event turn/iteration and deterministic IDs are checked. Carriers alone cannot certify producer provenance, run/boundary ownership or cross-record group consistency; those remain trusted-session/raw-validation duties.
- **Error translation:** cooperative sync wrapper at `filesystem_store.py:608–618` translates validation/I/O/digest errors to fixed `CooperativeYieldSettlementError('cooperative_yield_settlement_failed')`. The application wrapper at 595–606 retains its projector guard and `MessageStoreError`. Shared settlement predicate covers both terminal classes before agent/session retry planners. No concrete wrong-wrapper-type defect found in the inspected path. Error causes remain chained; no claim was made that arbitrary exception traces are safe public diagnostics.
- **Lock and cancellation:** flat `async with self._lock` encloses worker creation and `_join_application_worker` (438–477). Shield/repeated cancellation drains the worker before unlock and propagates caller cancellation; the new test at 376–424 exercises this for flat success. No finding that the worker is abandoned. Failure-plus-cancellation and the tree wrapper are not proved by that test.
- **Tree:** `tree_store.py:306–319` delegates without enrichment and updates only a strictly newer returned sequence. That matches §6.2.3; the serial cursor test at 427–453 proves the next ordinary event's parent. Tree has no separate lock; flat owns byte serialization and session execution/history barriers must own higher-level order. Cancellation during the flat await intentionally supplies no successful persisted return to the tree wrapper, so its cursor update is skipped. Do not claim cancellation-safe tree cursor recovery or concurrent tree ordering from the current test. Require exact-event owner recovery before continuation; assess that integration when producers land, rather than inventing a new tree-lock blocker for this subset.
- **No-start versus actual results:** the positive test at 270–311 writes both a result and a no-start marker for the same group. This is individually admissible shape testing, not a settled group. §6.3 must eventually reject that history. Split/label fixtures so this cannot become purported valid recovery evidence. Cross-record rejection remains the explicitly missing raw-validator work, not a fourth restricted-API blocker here.

## Receipt/source-count audit — inspected, not rerun

All paths below are under this evidence directory's `logs/`.

| Receipt | What its content actually supports |
|---|---|
| `turn5-retry2-append-red.log` | Command, cwd, baseline, UTC; exit 1; **13 failed / 2 passed**, missing port plus old error-code assertion. Original 15-case RED only. |
| `turn5-retry2-append-green-postformat.log` | Complete-looking 15-case progress/warnings receipt, exit 0, 15 passed at 03:29:21Z. |
| `turn5-retry2-append-green-final.log` | Complete-looking 17-case progress/warnings receipt, exit 0, **17 passed**, 2 warnings, 1.65s at 03:37:54Z. |
| `turn5-retry2-append-green-final-postformat.log` | Only 11 lines: header plus warning tail/summary, exit 0, **17 passed**, 2 warnings, 1.83s at 03:39:12Z. No progress line/full warning preamble: retain as a summary/tail receipt, not an intact full capture. |
| `turn5-retry2-append-regression.log` | Seven named files; exit 0, **225 passed**, 320 warnings, 67.73s at 03:27:48Z. Scoped regression only. |
| `turn5-retry2-append-static.log` | Initial Black exit 1 retained, then reported final Black/mypy exit 0. Commands contain `<7 changed files>` / `<5 changed source files>` placeholders, so exact argv/file lists are not independently auditable. Not a full static gate. |

Manual source enumeration, without pytest collection: cooperative append **8 functions -> 14 cases** (six two-adapter parameterizations plus two singles), settlement **3**, hence **17** focused. Metadata **16 tool-group + 8 cooperative + 3 settlement = 27**. Regression files expand to **29 application + 104 delivery + 43 reconciler + 18 projector + 7 provider-guard + 16 tool-group + 8 cooperative = 225**. Totals are internally consistent; they are not independent execution evidence or proof of all failure paths.

The append raw logs omit an explicit environment stanza; the implementation report supplies it. Baseline HEAD headers do not identify the dirty source bytes tested (no final source digest inventory). Consequently final-current-source execution integrity is limited, not disproved. Preserve chronological truth: duplicate/raw-corruption cases were added after implementation; do not retroactively call them RED. Earlier “13 passed” is invalid; 13 is the failure count in the retained RED.

## Coverage disposition and next action

| Original requirement | Current status / closure |
|---|---|
| §4.3 carriers | Implemented schema foundation; R2/R3 constrain admission validation. No producer/provenance claim. |
| §6.2 restricted append-once | Partial; R1–R3 must be repaired/tested before this subset is accepted. Shared owner and both adapters exist. |
| §9 A8 unknown reply/fsync/crash evidence | Missing for the current append guarantee; directly tied to R1. Existing readback/high-water tests do not substitute. |
| §6.3 startup/context/compaction raw validation; §6.4 replay/status | Explicitly unfinished T1 work, not newly discovered blockers of this restricted increment. Required before producers/consumers activate. |
| T2 provider race, bind/control/cursor/cleanup; tools/TUI | Expected missing future work, not new blockers here. Urgent runnable milestone remains pending. |
| Full non-e2e / static gates | `make test PYTEST_WORKERS=6` **BLOCKED** by other executable-fixture consent; full static **UNRUN**. YAML-stub failure baseline remains unestablished, not waived. No smaller total substitutes. |

### Minimal fault-injection approach, not a new harness

Use real files under resolved test-owned temp roots and the existing store/session injection pattern. `tests/agents/slo_agent/test_usage_trace_cancellation.py:109–128` already injects a small `FilesystemSessionHistoryStore` subclass through `history_store=` and delegates real persistence before withholding a reply. A similarly injected public-port override can prove **unknown reply after real successful persistence**, but cannot prove a failed fsync inside the real port.

For that latter claim, prefer a tiny owned I/O certification collaborator with a production default and a constructor-injected test implementation: retain real write/flush/read/metadata operations; record the exact file being certified and raise a controlled OSError at the certification boundary, then permit real fsync on recovery. A narrow intentional subclass override of such a designated hook is also viable if kept as the supported injection seam; an arbitrary private-method patch is not. Tree currently constructs its flat owner internally (`tree_store.py:49–59`): if the test needs the same injected certification there, add only the narrow compatible constructor forwarding/injection needed, not `tree._flat = ...`.

Do **not** monkeypatch module-global `os.fsync`, `open` or `Path`, or claim that an internal stdlib filesystem call is a third-party API exemption. The active policy permits injected internal collaborators, not private monkeypatching. A tmp-contained real metadata-path obstruction can separately prove post-line metadata failure without any such seam. No command stubs, executable changes, packages, system mutation or elaborate harness are needed.

### Repair/verification handoff

1. Write failing real-file proofs for R1 and failing restricted-admission proofs for R2/R3; implement minimal owner-local repairs and keep application behavior intact.
2. Supply current focused plus affected-regression receipts with exact argv/cwd/environment/exit/counts and final source identity; do not rename old logs to fabricate a new turn or RED chronology.
3. Re-review this subset; then finish the already-planned raw barriers before producer activation and T2. Independent final review and completion remain mandatory later.

Preflight hash independently read: `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`, unchanged from routing. The sole consented deploy-worker temp `bin/curl` fixture was not exercised. No commit/push/merge/PR, package, infrastructure, executable or system mutation was performed.
