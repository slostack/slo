# Feature 96 A.1 Change2 retry1 — REVISE

Useful partial progress; **not Change2 READY**, messaging-module READY, full A.1 readiness, approved spec, or independent review. No nested agents, commit/push, canonical-spec changes, ledger edits, queue/client/delivery implementation, or application cutover.

## Scope and evidence

Read the continuation ledger first, all requested project/skill sources, full current messaging source/tests and canonical relevant DAO/store/ownership/validation sections. The canonical HTML remains draft/REVISE. Routing, reconciliation and ordered plan: [change2-plan.md](change2-plan.md). Exact commands/environment/output/exits: [commands.md](commands.md), adjacent `.log` / `.exit` receipts.

Baseline before source edits: focused **95 passed**, affected **2413 passed**. Current checkpoint: focused **113 passed**, affected **2431 passed**, both exit 0. Scoped changed-code Black and three-source-file mypy pass. Full `make test` / `make lint` are pending, not waived. The historical alleged credential-failure waiver was not used; correct-environment affected baseline is green.

## Requirement → current evidence

| ID / source | Changes and public proof | Status |
|---|---|---|
| M3 ownership no-follow/private paths, HTML `#srcagentsslo_agentmessagingownershippy` | Descriptor-relative directory walk refuses linked session directories; lock requires current-user regular single-link inode; existing stale contents preserved. New session-symlink and hardlink tests RED 2 path failures → GREEN. Existing real flock/process exclusion tests retained and rerun. | Bounded paths proved; replacement-race/platform/cleanup-failure matrix remains |
| M3 cancellation/startup/release | Acquisition owned task is joined through repeated caller cancellation, then releases any acquired lease. Release is one retained task; all concurrent waiters join it before return. Explicit ephemeral exclusion is removed on its worker. Executor factory seam supplies a real dedicated worker with bounded scheduling gate. RED missing seam plus path defects → 23 ownership tests GREEN. | Repeated-cancel normal acquisition/release proved; failure-with-cancellation precedence remains |
| M1 canonical identities/hash/UTC, HTML DAO contract | Regex `fullmatch` rejects final-newline UUIDs/hash/source IDs. Complete submission is sorted compact UTF-8 JSON, non-ASCII unescaped, nonfinite JSON prohibited. Aware admission/receipt timestamp values normalize to UTC. Seven RED failures → seven GREEN. | Partial M1; not full DAO matrix |
| M2 worker lifetime, HTML store cancellation contract | Store open owns startup task; close owns one task; worker operations shield **and join** through repeated cancellation. A real second SQLite writer holds BEGIN IMMEDIATE; cancelled admit stays pending until transaction settles and accepted receipt reads back. Startup/close use real-worker gated factory. 3 RED → 3 GREEN. | Bounded joined success path proved, not full failure matrix |
| M2 atomic schema | BEGIN is inside executescript (SQLite otherwise commits preceding BEGIN implicitly); DDL/meta/version commit together. Real preexisting table collision leaves version 0 and only original table. RED → GREEN. | Atomic failure proved; schema v1 shape/integrity validation remains |
| M2 stable claim identity, HTML delivery canonical-event paragraph | Claim uses UUID5(session UUID, `message:` + message UUID), not random UUID4. RED → GREEN. | Event ID only; exact event preparation still defective |
| M2 original terminal outcomes | mark_applied returns original applied receipt idempotently, including after seven-day terminal body/application pruning. Duplicate admit after pruning returns same receipt. RED → GREEN. | Bounded happy-path proof; tombstone consistency validation remains |

**No M1/M2/M3 acceptance item is declared fully closed.** Tests establish these bounded behaviors, not completeness by count. Scoped mypy passing does not validate SQLite invariants.

## Files modified / preserved

Modified existing substantial untracked files: `src/agents/slo_agent/messaging/{dao,ownership,store}.py`. All other partial module files remain untouched. Existing `test_store.py` and `test_ownership.py` preserved unchanged, including their weaknesses. Added `test_dao.py`, `test_ownership_repairs.py`, `test_store_repairs.py`. New report/plan/receipts live here. Root `RESEARCH.md` and `docs/RESEARCH.md` record the durable join/SQLite transaction lessons and explicit nonactivation boundary. Shared KB was consulted but not edited because this dispatch's user scope permits writes only in the worktree; copy durable lessons there in a separately authorized follow-up.

Ownership was reshaped within its existing class (no new runtime module) to make lifecycle ownership real. Optional `executor_factory` defaults to the dedicated production worker; it transfers executor lifecycle ownership. Tests use a real executor barrier, not patched private methods or fake database/flock. Public startup remains explicit. Store path validation and open are NOT yet safe enough for activation.

## Finite remaining Change2 checklist (required before READY)

### M1 DAO repairs required by M2/M3

- [ ] Complete strict UUID/principal/source identity and finite-number/UTF-8 byte validation (principal_id currently unbounded; source-event authority shape incomplete; surrogate handling/64KiB construction limit not proved).
- [ ] Add descriptions/Field declarations required by Python DAO recipe; most skeleton fields still bare. Validate receipt state/run/applied-time/retention combinations, recovery logical destination/digest relationships, compaction unique membership/state-summary combinations, delivery/event identity and observation/hash relationships. Pydantic strict/frozen outer types alone do not prove deep immutability of nested history/workflow objects.
- [ ] Closed safe workflow failure-code validation: skeleton accepts arbitrary string. Keep valid shared future type definition separate from A.1 capability acceptance.

### M2 store correctness and proofs

- [ ] **Safe SQLite open first**: current `_connect` uses a `/proc/self/fd` pathname without SQLite URI mode, path validation is TOCTOU, WAL/SHM are not checked no-follow/private/current-owner, descriptor/connection can leak on `_connect` pragma failure. Replace safely on dedicated worker and prove containment/permissions and partial-start cleanup. Do not activate current implementation.
- [ ] Validate user_version=1 schema shape and meta values/integrity (currently trusts version alone), bind exact session path/current generation, start sealed on every open. Keep reconciled core DDL and note index, no later-only added initial tables. Unknown/corrupt versions fail fixed error without fallback.
- [ ] Validate identity/body state, sequence, digest, original principal/target agreement on admission/recovery/reads. Full principal mismatch is unauthorized, not merely conflict; source identity conflicts must not escape as storage failure. Validate current target/generation for live retries.
- [ ] Use canonical submission bytes for capacity/storage, correct payload error, exact inclusive capacity and sequence overflow boundaries, retained vs applying counts, concurrent atomic allocation. Prove real locked/full/corrupt/rollback boundaries, WAL-inclusive 256MiB refusal without tombstone deletion, and uncertain commit seals new admission until reconciliation. Current tests seed storage by private connection access; replace with real public/external SQLite setup, not mocks.
- [ ] `claim_note` absent; implement independent FIFO note slot and stable repeated claims (prepared claim replay currently returns None rather than recoverable prepared event). Empty-boundary freezing belongs to M5/session, not store guessing. Verify deterministic event and full delivery match at prepare_application; skeleton currently accepts arbitrary unrelated event ID/session/content/turn/metadata. Do not merely change old test oracles without RED behavior proof.
- [ ] Applying journal/evidence ordering: verify exact history commitment, immutable event ID/hash, idempotent post-prune acknowledgements against valid tombstones. Current early-applied return assumes row validity; cross-record validation is still needed.
- [ ] Restart retains all unapplied input; `reset_unprepared_claims` currently reactivates accepted without retained flag. Preserve prepared claims for explicit reconciliation; no automatic execute on restart. Exact cancellation selection and retained-source read/preview support are incomplete.
- [ ] Local recovery must compare stored original digest/whole original identity and confirming principal, validate destination=current session with only generation change, activate new owner generation atomically, preserve original bytes, replay original transfer outcome and confirmer after pruning/restart, capacity rules. Skeleton compares computed input digest to caller-supplied digest, not stored digest; wrong destination/confirmer can succeed. Missing recipient identity must refuse (no D.1 import in A.1).
- [ ] `read_identities`, `read_compactions`, `read_observations` absent: worker-owned snapshot pages, strict 1..256 bounds, ordered cursor/empty termination, safe corruption errors, identity evidence and retained selection readers. No private connection tests as replacement.
- [ ] Compaction: preparation idempotency/exact membership, at most one prepared transaction, refuse prepared observations/unsettled applications, immutable finalized outcome, committed coverage vs prepared/rollback readback, body pruning preserves required evidence and active-run boundary. Current observation/compaction tests mostly assert no exception and do not prove coverage. Reconcile A.3-only pool observation capabilities, never placeholder success or missing import.
- [ ] B.2 workflow effect methods currently accept arbitrary JSON and tests assert placeholder `advanced` success on plain text. Reconcile as unavailable A.1 capability; retain partial work but do not claim or activate B.2 success. New workflow/channel route refusal must ultimately be session policy under M4 mutex; store is not authorization owner.
- [ ] Repeated cancellation plus worker rollback/error/close races and already-closed API calls must preserve error/cancellation semantics, resource ownership and fixed diagnostics. New join loop can still allow a worker exception to win over a simultaneous cancellation; define/test precedence.

### M3 remaining assurance

- [ ] Prove unsupported-platform outcome (conditional fcntl import exists but not tested), startup I/O failure cleanup/no fd or executor leak, release cleanup failure honesty (finally closes fd), cancelled acquisition ending in contention/I/O failure, ephemeral acquisition cancellation and concurrent release across multiple cancellations.
- [ ] Harden held directory/file identity against ancestor replacement races; directory traversal refuses symlinks, but held-lock publication currently does not revalidate the pathname after walk. Prove every path/UUID check uses exact canonical identity before touching files.
- [ ] Caller must join store/history writers before ownership release; only module contract is documented. Full session lifecycle is explicitly NOT proven here.

## Out-of-dispatch work / blocked acceptance

M4 queue mutex/authority/signals, M5 delivery cursor/cache/slots and M6 local client deadline/unknown-outcome lifecycle remain skeletons. M7/full Step1 and A.1 integration require session/history/agent/TUI/headless/legacy bridges, local commands/draft safety/capability refusals and full gates. These are not implemented or manufactured as accepted. Orchestrator obtains independent early read-only feedback and schedules further bounded implementation, then final independent Review/Completion. No external dependency presently blocks useful work; remainder is implementation/verification scope.

Self-check: reviewed changed source/tests; expected RED failures precede each bounded implementation; checkpoint focused/affected green; no unrelated edits. Untracked files are invisible to ordinary git diff, so diff-check is only whitespace evidence for tracked changes, not review of these new files. Preserve all untracked partial work. No acceptance counters changed.
