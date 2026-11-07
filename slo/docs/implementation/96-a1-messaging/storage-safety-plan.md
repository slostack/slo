# EF96-01 / EF96-02 bounded revision plan

Status: Code+Test, turn 2 dispatch 1; not an execution retry. No ledger writes,
nested agents, commits, runtime wiring or later queue/client/recovery work.

Authority: continuation ledger; early-feedback EF96-01/02; canonical HTML
`96.a.1-session-owned-durable-delivery.html` §8 store/DAO, corrected by §3 and
`assets/a1-runnable-core.md` and `a1-implementation-walkthrough.md`.
Existing 113/2431 receipts are a checkpoint, not acceptance.

Routing reused and checked against active installed skills under
`/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`:
engineering routing/ownership/testing; coding rules, design principles,
solution-design, declarative structure, test loop and verification policy;
Python root/style/domain/application/testing recipes. Repository exact workflow
`skills/orchestration/workflows/{code-test-review.md,SKILL.md}` applies. SQLite
adapter integration tests use real disposable files/SQLite, not PostgreSQL,
SQLAlchemy, durability mocks or a new harness. Python 3.11.7 uses the existing
slo-harness pyenv environment rather than absent documented slo environment.

## Independently verified defects and approach

`_validate_path` runs on the loop and `_connect` later re-resolves/chmods the
parent; database hardlinks and WAL/SHM are unchecked. Descriptor cleanup follows
successful connect only, connection cleanup misses pragma failures. Version 1
returns without validation or resealing. Duplicate and receipt authorization
compare principal_id alone. These match EF01/02. Existing real reopen receipts
mean absence of uri=True alone is NOT a demonstrated failure.

Keep MessageStore as the single deep persistence/resource owner; no new service
or runtime entry. Public open/admit/read/close remain the real test boundary.
Move path traversal/acquisition/validation entirely onto the dedicated worker.
Use no-follow directory-relative opens, private single-link owned file checks,
retain directory/database/sidecar descriptors with the connection, and recheck
pathname identity before publication/operations. Never chmod a pathname reached
by a second traversal. SQLite's stdlib VFS performs its own pathname operations:
verify its actual path/pragmas, expose any remaining race limitation honestly,
and do not imply a descriptor URI magically secures the VFS. No platform fallback.
An injected real connection factory may observe startup or install a real SQLite
authorizer to induce pragma failure; it must not replace durability.

For EF02 validate complete core schema shape/indexes/constraints, metadata and
SQLite integrity before an atomic reseal/current-generation adoption. Retain old
unapplied input; open must never authorize execution. Validate identity/body
relationships at startup and trusted public read/admission boundaries, and full
principal equality before distinguishing payload conflict. Refuse stale live
submission targets, preserve original duplicate/terminal receipt identity, and
prove refusals do not allocate or rewrite records. Sealed storage is not session
history reconciliation.

## Ordered verification increments

1. EF01 unsafe inode/sidecar/ancestry public-open RED; minimal worker acquisition
   and cleanup; GREEN including unchanged destination bytes/modes and real reopen.
2. EF01 real connection/pragma failure and repeated-cancel cleanup, actual pragma
   readback and held-path replacement proof. Keep residual safety gaps explicit.
3. EF02 sealed two-generation reopen and schema/meta corruption RED/GREEN.
4. EF02 cross-record/principal/stale-target RED/GREEN; correct old test setup only
   when exact canonical contract plus actual failure establishes false expectation.
5. Focused messaging suite per increment; affected slo_agent suite at milestone;
   scoped Black/mypy and untracked-file review. Distinct complete RED/GREEN logs,
   commands and exits go beside final `storage-safety.md`.

Safe environment and exact commands follow `commands.md`/Makefile fallback.
Full make test and make lint are still required before overall Step1 readiness,
not claimed in this bounded dispatch. Formal independent Review/Completion pending.
