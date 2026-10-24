# T5 continuation 73 — INCOMPLETE captured initialization ownership

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 73, retries 0. User turn/dispatch limits unlimited; no numeric budget
stop is asserted. No agents, commits, pushes, PRs, reset/clean/stash, global/live,
canonical-specification or other-worktree edits. Existing work preserved.

## Executed increment

Two mounted regressions first failed because a typed acquisition result with a
foreign session ID or foreign owner ID still authorized both delivery timers.
The cases persist the foreign lease through the real temporary store and assert
that rejection preserves it. The factory is patched to Faux; normal suite
Herdr/environment and terminal guards remain enabled.

`_acquire_session_lease` now accepts the captured session and owner ID, returns
`SessionOwnershipLeaseDAO`, and refuses a missing store. Initialization validates
both returned identifiers before proceeding. This bounded increment adds fewer
than 50 production lines. It does NOT complete capture across all initialization
awaits: rollback still reads the current app owner ID, and the complete canonical
runtime sequence has not been consolidated.

## Finite branch disposition

| Branch | Current evidence / outstanding obligation |
|---|---|
| Acquisition returns foreign session ID | New mounted real-store RED then GREEN; foreign record preserved |
| Acquisition returns foreign owner ID | New mounted real-store RED then GREEN; foreign record preserved |
| Normal initialization | Existing surrounding tests green |
| Inbox creation or timer1/timer2 registration throws | Continuation72 mounted cases rerun green |
| Closing at timer1/timer2 registration | Continuation72 mounted cases rerun green |
| Shutdown joins held acquisition return | Existing initialization regression rerun green |
| Missing lease store direct helper branch | Explicit RuntimeError; dedicated test still required |
| Captured owner mutation across acquire/inbox/rollback awaits | NOT complete; release still resolves current app owner |
| Successor replacement at reconcile/acquire/inbox cutoffs | Complete real-store barrier matrix pending |
| Both failed timer stops retain handles; later stop succeeds | Helper retained; complete mounted fault-product matrix pending |
| Timer/release faults combined with throwing notices | Complete matrix pending |
| Repeated public cancellation during actual off-loop acquire/init/rollback | Complete real-thread barrier proof pending |
| Closing never reopens delivery on any late continuation | Existing bounded checks retained; full matrix pending |
| Duplicate initialization cannot overwrite retained timers | Pending |
| Exact canonical mount/replacement runtime phase order | Pending; mount still owns delivery-only sequence |
| Enabled activation | Intentionally not wired before ownership readiness |

## Exact commands and results

CWD `/root/Code/slo-94-herdr-integration/slo`. Log and exit files are in this
same documentation directory. Every pytest command uses the approved fallback,
not a new environment; the helper adds 62 foundation tests.

RED:

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_init_ownership.py
```

`t5-73-red1.log/.exit`: exit 1, **2 failed, 62 passed**, 1.74s.
Both failures are the `app._delivery_quiescing` assertion after mismatched
acquisition, not fixture/import errors.

GREEN + surrounding before any further production increment:

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication
```

`t5-73-green1.log/.exit`: exit 0, **332 passed, 1 deselected**, 192.90s.
This retains the prior 330-pass shared rollback surrounding partition.

Final checks (each matching prefix has `.log` and `.exit`):

- `t5-73-black`: `PYENV_VERSION=slo-harness poetry run black src/tui/app.py tests/tui/test_herdr_init_ownership.py`, exit 0.
- `t5-73-black-check`: same with `black --check`, exit 0, two unchanged files.
- `t5-73-diff`: `git diff --check`, exit 0, silent.
- `t5-73-coreutils`: `dpkg -V coreutils`, exit 0, zero bytes.

No full make run: ownership family is not ready. No fresh lint result or waiver;
prior 299 errors/63 files remains unwaived, no new ignores added.

## Read / review boundary

Consulted supplied actual project instructions and docs/RESEARCH, root RESEARCH,
continuation72, frozen routing/scope-plan (combined output truncated; complete
fresh ingestion is NOT claimed), actual app initializer/rollback/replacement and
lease DAO/store, existing initialization/rollback tests, shared routing/ownership/
testing/coding rules/cadence, Python/declarative/Faux/Textual guidance and workflow
SKILL. Consulted KB Welcome and Slo README/gotchas. Canonical C initializer and
lifetime correction read directly; exact complete T5 samples, accepted reviews,
remaining style recipes and C7.9–7.14 full reread are not closed by this receipt.
No KB edits under the user's external-write restriction.

Review confirms this increment rejects returned identity mismatch without adding
a lease policy/coordinator or deleting the foreign lease. It does not establish
complete ownership acceptance. **INCOMPLETE initialization ownership family**;
not entire T5, activation readiness, independent review or full-suite acceptance.
