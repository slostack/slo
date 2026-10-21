# T2-38 — READY for entire T2 technical dependency handoff

Code/Test continuation only. Both remaining T2 assertion gaps from
`t2-37-finalization.md` are closed. Together with that reconciled finite map,
**entire T2 is technically READY as a dependency for T3/T4**. This is not whole
Feature 94 completion, independent Review/Completion, all-static-green status,
or live compatibility certification. No production correction was needed.

## Scope and exact test map

New file: `tests/agents/slo_agent/herdr/test_viewer_authority_closure.py`.
All 23 new cases passed initially: coverage-only, no fabricated behavioral RED.
The three increments were tested in sequence before the next addition.

| Contract | New executable evidence | Result |
|---|---|---|
| B7.13 independent live predicate and destination | `test_independent_live_authority`, seven cases: viewer revoked, closing, disabled, activation not released, lease lost, sequence unsafe, transport sealed | Each starts with all authority facts positive, changes only one fact, and requires the captured bound predicate false and destination unavailable; no I/O |
| B7.13 authority changes while queued at actual shared lock | `test_queued_live_authority`, same seven cases plus unchanged positive control | Real transport invoke queues on its existing asyncio lock; actual pending lock waiter is observed before mutation/unlock. Unsealed cases evaluate the bound predicate under that lock exactly once; sealed transport refuses before delegate admission. All losses return suppressed/unadmitted, no completion and empty executable capture. Positive control actually enters the registered regular fake executable once and completes once; resources drain |
| B final helper/B20 positive assembly | `test_build_visualizer_identity` | Calls production `build_visualizer`; asserts constructor result identity, exact transport object, owner pane and bound method `__self__`/`__func__`. The supplied callable changes from true to false after public revocation, not a captured Boolean |
| B final helper inactive/closed/unsafe refusal | `test_build_visualizer_refuses_lost_authority`, seven independent cases | Production assembly raises HerdrRestoreUnavailableError before any constructor call; no filesystem work. Prior inactive coverage remains retained |

The authority setup deliberately establishes event-loop policy inputs without
claiming real activation or a real acquired lease. This isolates each predicate
instead of coupling several losses through shutdown. Activation/lease lifetime
proof remains in the reconciled T2-37 map. The queued test uses the real transport,
real lock, unchanged spawn guard and an actual registered executable positive
control; no mocked invoke/spawn or replacement authority policy. Its RecordingAdmission
subclass only counts evaluations/completions and delegates to the bound reporter
predicate. Lock waiter inspection establishes queuing deterministically, with a
bounded timeout rather than a timing sleep assumption.

Assembly substitutes ONLY the not-yet-T4 module import/constructor using a
pytest-scoped sys.modules entry. Production reporter assembly is exercised now,
not deferred. Concrete launcher behavior is deferred: strict split parser,
one-shot per-parent split/rename/run ledger, new-request and already-admitted
viewer semantics, sequence failure cause compositions through that ledger,
context reader and actual viewer cancellation/paint are T4/T6 responsibilities.
H/tasks.md T2 explicitly permits deferred assembly imports; T4 owns the real
viewer-operation tests. No T4 implementation was added to close T2 assertions.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `pyenv which python`:
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7;
`make test-env`: `fallback`. Prefix H below denotes the read-only canonical
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
Test command prefix P is exactly:
`bash docs/implementation/94-herdr/t1-dao-check.sh`.
The inspected helper supplies the safe fallback environment and adds the existing
62 DAO/projection cases. HERDR stripping/default disable, registered fake-only
spawn capability and terminal guard remain unchanged. No dev environment or real
Herdr/provider/terminal used. Fixture files are new contained regular files,
revalidated by identity before spawn; these tests add no file-writing fixtures.

Receipts are `docs/implementation/94-herdr/<prefix>.log` and `.exit`:

| Prefix | Exact command | Result |
|---|---|---|
| t2-38-predicate | P tests/agents/slo_agent/herdr/test_viewer_authority_closure.py | 69 passed, 2 warnings; exit 0 (first 7 cases) |
| t2-38-queued | P tests/agents/slo_agent/herdr/test_viewer_authority_closure.py | 77 passed, 2 warnings; exit 0 (15 cases) |
| t2-38-target | P tests/agents/slo_agent/herdr/test_viewer_authority_closure.py | 85 passed, 2 warnings; exit 0 (all 23 cases) |
| t2-38-package | P tests/agents/slo_agent/herdr tests/agents/slo_agent/test_token_format.py tests/tui/test_usage_status_bar.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py | 900 passed, 5 warnings; exit 0 |
| t2-38-black | poetry run black --check tests/agents/slo_agent/herdr/test_viewer_authority_closure.py | 1 unchanged; exit 0 |
| t2-38-coreutils | dpkg -V coreutils | silent; exit 0 |
| t2-38-diff | git diff --check | silent; exit 0 |

No production changes: per this request, fresh integrated full make test/smoke/lint
can follow T3/T4. Prior 7064/full, 877/chapter, 518/surrounding and 285/smoke are
**pre-change evidence only**, not verification of these new tests. Prior lint
**301 errors/64 files remains unwaived, not green**; no fresh lint claim. This
bounded dependency verdict does not advance the whole-scope workflow review gate.

## Authority, preservation and next owners

Read current routing/scope-plan, T2-37 finalization and current/history status
ledgers; actual supplied AGENTS/CLAUDE/docs RESEARCH plus root RESEARCH, Makefile,
safe test helper, reporter authority/assembly/lifetime and transport admission
owners, existing reporter/transport/independent-holder tests and root fixture guard.
Consulted read-only KB Welcome, Slo README/gotchas (bound-method identity caveat).
Loaded checkout engineering routing/testing/ownership, coding rules/cadence/shared
declarative, Python root/declarative/type/docstring/application-service guidance,
and exact Code-Test-Review workflow/shared SKILL. Frozen routing is unchanged.
Reference checks: B final helper and 7.13 (2048–2165), C final local drain
(1985–2055), tasks T2 contract (102–134), B20/B24/B25/C28/C29 samples, and D's
T4 authority/operation sample allocation. Current chapters control historical
samples; no old superseded pending ledger has been revived. These are bounded
closure reads, not a new independent full T1–T6 audit.

Author self-check confirms no production edits, skipped assertions, safety-guard
changes or weakened prior tests. Preserve all earlier partial work and receipts.
T3 owns immutable storage/CLI; T4 concrete viewer/context reader; T5 automatic
session/app integration; T6 composed/live acceptance and full static gates.
Independent full-scope Review and Completion remain later. No live restart,
restore, 0.9.2 compatibility or pane-paint claim; no agents, commits, push/PR,
reset/clean/stash, global/KB/specification/other-worktree modifications.

Parent counts unchanged: unfinished turn 1; started 1/completed 0;
historical partial 1; dispatch 25; retries 0. Workflow turns and dispatches per
turn unlimited by user; no capacity stop, reset or new completed turn asserted.
