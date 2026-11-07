# M2 store continuation — REVISE, useful functioning progress

Turn 2 dispatch 2/20; 60-turn user limit. Local continuation, not execution retry.
Counters/ledger untouched. No nested agents, commit/push or runtime activation.
**Not M2 READY, module READY, Step1 READY, or A.1 acceptance.** Independent
Review/Completion have not run. No full-gate waiver.

## Scope, authority and reconciliation

Read the continuation ledger, storage-safety/early-feedback/change2-retry1,
root RESEARCH, supplied project instructions, exact repository
`skills/orchestration/workflows/{code-test-review.md,SKILL.md}`, canonical HTML
§3/§8 DAO/store/delivery/history/test matrices and both linked runnable-core and
implementation-walkthrough assets. Consulted KB Welcome and slo README/gotchas.
Active installed skill root is `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`:
engineering routing/testing/ownership; coding rules, solution-design,
code-design-principles, declarative-method-structure, test-verification-policy,
code-test-loop; Python root, named arguments/types, docstrings/declarative,
domain/application building and persistence test recipes. SQLite/Pydantic/asyncio
is the affected stack; no SQLAlchemy/DBOS/FastAPI adoption.

Ordered implementation plan was exact application evidence -> persistent local
recovery -> bounded readers/note claims/compaction -> concrete integrity guards ->
focused/affected/static gates. Existing ownership and queue/client/delivery files
are preserved. Writes are store.py, dao.py, messaging tests and evidence only.
No second history writer: mark_history_committed remains the trusted session's
assertion after the existing history owner has appended exact evidence. Store
cannot certify actual context insertion or history activation by itself.

Corrected §3 controls later dependency examples: persistent recipient-local
recovery is implemented, external import and ephemeral recovery are refused.
`commit_workflow_effect` now returns fixed `unsupported`, rather than treating
opaque `{"status":"advanced"}` bytes as B.2 success. Its docstring requires the
later canonical B.2 validator and complete admission policy to be enabled together;
no permissive validator/plugin framework was invented. Store is a trusted internal
collaborator, not session principal registration, capability admission, preview
registration or human-interaction authority.

Canonical §8 delivery explicitly prescribes workflow_update, deterministic UUID5,
admitted_at, logical run and text, with only messaging_v1 metadata and remaining
history defaults. Old user_message/random-ID fixtures were wrong. New RED tests
reproduced acceptance of unrelated event/claim fields **before** implementation;
legacy fixtures now derive from the actual claim. Reset's old automatic-reclaim
oracle was replaced by retained/no-execution proof. Recovery fixtures now use real
persistent databases rather than asserting unsupported ephemeral continuation.
Compaction's old applying fixture and maintenance expectations were not used as
proof of coverage; new tests assert persisted exact membership and refuse global
unsettled claims/observations. All payload-limit errors use invalid_message, not
queue_full, and capacity counts exclude retained input.

## Implemented behavior and evidence

| Requirement | Functioning implementation / evidence |
|---|---|
| EF03 stored claim/envelope/boundary/event equality | prepare_application reconstructs the stored claim and compares the supplied delivery; deterministic event validation checks every supplied event field against canonical defaults. New `test_store_journey.py` tests event ID/session/kind/time/turn/text/metadata/iteration and forged boundary. |
| EF03 normalized evidence / no premature ack | Normalization excludes **only** top-level sequence and payload.token_usage, sorted compact UTF-8 JSON. Identity event ID/hash commits with journal at prepare. Matching assigned history fields retry idempotently; mismatches refuse. Identity/body/journal/hash/commit-state validation gates acknowledgement and restart. Repeated applied acknowledgement preserves original receipt after prune. |
| EF04 persistent local recovery | reset clears unprepared claims to retained accepted. Two/three-generation real SQLite journey checks stored original digest, full original author, original target and exact new destination; preserves original bytes/receipt target and separately records execution generation. Persisted full confirmer JSON binds replay. Transfer replay returns original outcome before current destination checks. Capacity recheck and exact cancellation are transactional. Missing identity/import unavailable; ephemeral returns unsupported. `test_store_recovery_journey.py`, atomic/retained tests. |
| EF05 reads and claim_note | read_identities, read_compactions, read_observations and read_retained run on worker in one operation transaction. Strict cursor/limit checks return invalid_message; empty terminates. Note selection is FIFO context/transcript only, independent unique boundary slot; prepared retry returns the same original claim, not another pop. `test_store_pages.py`. |
| EF05 lifetime proof | Real public admission/application of 513 terminal messages and 17 observations, prune/reopen, traversal at limits 1/256 with exact sequence/IDs and empty termination: `test_store_persistence.py`. Lifetime identity/application hash remains after body/journal pruning; observation bodies pruned only under committed coverage. |
| EF05 compaction | One prepared operation, idempotent exact set membership, only applied members, rejects any applying message/prepared observation. Finish immutable; all states read back. Prune refuses unsettled application/observation/prepared compaction; preserves identities, transfers, hashes and memberships. History activation/rollback deliberately outside module. |
| EF02 atomic/bounded validation | Every operation acquires BEGIN IMMEDIATE before meta/lane/addressed validation and reads/writes, releases only after post-path check and commit. Inner operation savepoints no longer commit the validation snapshot early. Routine prechecks inspect at most 513 active lane rows, not lifetime records. Startup streams lifetime validation under one transaction before reseal, including recovery/observation/compaction ledgers. Real SQL trace and externally corrupted journals/ledgers tested with unchanged dump assertions. |
| DAO/concrete identity | Compaction unique membership and summary/state combinations; receipt application-state constraints; principal key printable 1..128; UTF-8/complete 64KiB submission construction; exact configured inclusive canonical byte budget; scheduler/workflow source author/shape consistency and source-ID uniqueness conflict before insertion. |

New test files: `test_store_journey.py`, `test_store_recovery_journey.py`,
`test_store_pages.py`, `test_store_strictness.py`, `test_store_persistence.py`,
`test_store_atomic_reads.py`, `test_store_retained.py`,
`test_store_ledger_validation.py`, `test_store_limits.py`. Existing test_store and
one store_repairs event fixture updated. Ownership unchanged. Test count is not
closure; the remaining guarantees below prevent READY.

## Exact receipts

All paths below are relative to this directory. Each stem has distinct `.log`
and actual `.exit`, except the interrupted full suite, whose exit is **unknown**
(no fabricated process exit). See `store-commands.md` for commands/environment.

- `store-ef03-red`: 10 failed -> `store-ef03-green`: 10 passed.
- `store-ef04-red`: 7 failed -> `store-ef04-green`: 7 passed.
- `store-ef05-red`: 5 failed/2 passed -> `store-ef05-green`: 7 passed.
- `store-strict-red`: 10 failed -> `store-strict-green`: 10 passed.
- `store-atomic-red`: 1 failed/2 passed -> `store-atomic-green`: 3 passed.
- `store-retained-red`: 2 failed -> `store-retained-green`: 2 passed.
- `store-ledger-red`: 6 failed -> `store-ledger-green`: 6 passed.
- `store-limits-red`: 2 failed/2 passed -> `store-limits-green`: 4 passed.
  Surrogate is rejected by Pydantic before the custom text validator on this
  version; that branch was confirmation, not claimed new repair.
- `store-focused-closure`: **226 passed**, 2 warnings, 21.13s, exit 0.
- `store-affected-closure`: **2544 passed**, 220 warnings, 123.63s, exit 0.
- `store-black-closure`: 23 files unchanged, exit 0.
- `store-types-closure`: scoped source command exited 1, six imported provider
  errors (faux, anthropic_claude_code, openai_codex), none in owned source.
  Earlier `store-types-final` passed 3 files; final result supersedes it, not green.
- `store-package-types-final`: exit 1, 14 errors in 8 files: four unchanged
  queue/client skeleton errors plus imported provider/TUI/CLI errors; owned test
  typing errors from first package check repaired. This receipt predates final
  limits test file; no claim of final all-test type cleanliness.
- `store-make-lint`: **315 errors in 68 files**, exit 2. No waiver.
- `store-make-test`: tool timeout at **600 seconds**, log stops at 89%; three
  failures already displayed (commit-footer and two orchestrator-limit tests).
  No completion summary or `.exit`. No full suite pass. Later source changes
  additionally invalidate this as a post-final-edit full gate. No full rerun
  attempted while origin/completion was uncertain.
- `store-diff-closure`: git diff --check exit 0 (tracked whitespace only).
- `store-coreutils`: dpkg -V coreutils exit 0, no output; full suite stubs did
  not alter checked system binaries. No binary/system changes performed.

Python is 3.11.7 via slo-harness, not documented absent slo env. No environment
installation or credential changes. Dummy-key Makefile environment used; no live
provider tests or terminal windows intentionally launched.

## Finite remaining M2 work (normal implementation, not operator blockers)

1. **Complete bounded cross-record checks at each addressed transition.** Current
   startup validates transfer ledgers, but transfer replay must revalidate that
   full row against original identity in the same live snapshot, including stored
   outcome state/time/run fidelity. Addressed retained history marking should
   explicitly validate its identity/journal before changing a flag. Page readers
   must validate compaction members' applied state and observation body/session
   bounds at read time, not rely only on startup. Add representative corruption
   regressions for these paths; no Cartesian matrix required.
2. **Bound compaction membership/work.** Identity/observation pages are bounded,
   but a single compaction DAO still materializes all its membership. Canonical
   interface returns tuples with no explicit member-count bound. Need reconcile
   a concrete maximum or a compatible streaming membership read before claiming
   strict bounded memory for arbitrary lifetime compaction. Do not silently
   reject legitimate lifetime membership with an invented 256 limit.
3. **Idle run lifetime precondition.** maintain now refuses any applying row,
   prepared observation or prepared compaction. The store still has no actual
   active-run lease: an applied boundary could belong to a still-running run.
   Session is specified to call maintenance only outside execution; document and
   verify a narrow caller-idle contract/injected policy rather than claiming the
   store independently knows run termination. No session wiring authorized here.
4. **Strictness/conventions finish.** Most original DAO fields still lack explicit
   Field descriptions; nested history/workflow objects are not deeply immutable.
   Closed workflow failure-code vocabulary still needs a canonical source (do
   not invent it). Complete relevant DAO typed documentation/validation and exact
   observation bounds without activating A.3/B.2. Tests still include old private
   connection seeding for storage pressure/failure; replace those with supported
   real external SQLite/factory setups if claiming full public-boundary coverage.
5. **Native storage failures.** Real locked/full/uncertain-commit and cleanup
   failure evidence is not complete. Operations roll back exceptions, but durable
   post-commit ambiguity needs an explicit sealed/unavailable state preventing
   new admission until reconciliation. Final schema/read/rollback/cancellation
   evidence must cover this, not merely happy-path transaction success.
6. Required full/static gates remain failed/unverified, no waiver. Run final
   full make test and make lint on a stable worktree; preserve failure honesty.

EF03/04/05 have substantial representative journeys now, but the issues above
mean no blanket closure for M2. No unavailable future service prevents continuing
this finite store work. M3/EF06 ownership remains separate and unchanged.

## Native SQLite containment boundary — actual unsupported stronger guarantee

Existing no-follow directory/DB/WAL/SHM descriptor checks and post-operation
identity checks fail closed on detected substitution. They **do not** control the
native SQLite VFS's internal path resolution/sidecar reopen/unlink. Same-UID
concurrent namespace mutation between checks can race VFS accesses; detecting it
afterward cannot undo a write, nor guarantee safe native close after permanent
replacement. Linux /proc descriptor URI is not a custom secure VFS. Local filesystems
only; portable filesystem detection/guarantee remains absent.

Do not introduce a custom VFS or claim race-free protection. If the acceptance
contract requires resistance to an actively malicious same-UID process replacing
owned directories while SQLite runs, that guarantee is unsupported by this design
and needs an operator threat-model decision (or different storage isolation).
Under cooperative same-owner/exclusive-session local-filesystem assumptions,
remaining correctness tasks above are ordinary implementation, not reasons to
stop for permission. Package remains inactive either way.

## Worktree and gate reliability

Initial status during this call: only RESEARCH.md/docs/RESEARCH.md modifications
and untracked messaging artifacts. Later status showed unrelated AGENTS/README
changes, CLAUDE.md/docs/RESEARCH.md and many historical documentation deletions,
and skill-test fixture changes. These were **not made or reverted here**. Preserve
operator/concurrent work. They contaminate broad baseline comparison; no claim
that full-suite failures are all caused by M2 or all preexisting.

The 600-second Bash timeout ended the command wrapper without a receipt. Read-only
process inspection later found no newly started make/poetry/pytest from that run;
only an unrelated pytest PID 1261413 with >22-hour elapsed time and PPID 1. It was
not signalled. No agent/scope/process cleanup performed. Guardian guidance read
before process diagnostics. Final full gate remains unverified, not assumed
success or assigned a guessed child exit code.
