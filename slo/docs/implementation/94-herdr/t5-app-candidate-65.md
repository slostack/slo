# T5 continuation 65 — candidate preparation technical READY

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 65,
retries 0. Effective turn/dispatch budgets unlimited. No agents dispatched; parent
counter unchanged. Author implementation evidence, not independent acceptance or
whole-T5 readiness.

## Delivered finite family

Changed only `src/tui/app.py`, new `tests/tui/test_herdr_session_lifecycle.py`, and
continuation evidence/status files. Existing unrelated work is preserved.

`_replace_idle_session_and_clear_queue` now delegates candidate preparation before
cancelling old preparation or unsubscribing. `_prepare_replacement_session` builds,
checks unchanged history root, attaches the fresh standard pool, and optionally
renames. Build/attach/name failures retain old ownership and emit fixed best-effort
copy. Cancellation joins candidate-only disposal before escaping. The app retains
`_candidate_cleanup_task`; session `dispose_unmounted_session` remains the sole
reporter/pool/final-local-drain owner. No old pool drain, mounted fleet reset or
candidate reporting activation was added.

The replacement builder deep-copies configured pool, its list and entries. Existing
/new policy is unchanged: workdir/model/configured pool/effective reasoning/history
carry over; workspace/plugins are not newly inherited (C 7.9 explicitly requires
preserving this distinction from native restore).

## Finite branch/evidence map

All new tests mount real Textual around config-backed sessions, use actual bootstrap
and candidate/session owners, and use controlled failures at their boundaries.

| Branch | Evidence |
|---|---|
| Build fails before candidate exists | `test_new_prepare_retains_mounted_owner[build]`; no disposal target |
| Attachment fails after real fresh pool attachment | `[attach]`; candidate pool sealed, old pool unsealed |
| Rename fails / caller cancelled during rename | `[name,cancel]`; Event barrier, old subscription/preparation/queue/transcript/history/lease retained |
| Cancellation before rename | `[cancel_before_name]`; attached candidate disposed, old intact |
| Throwing diagnostic sink | `[notice]`; original fault contained and old session still invokes Faux |
| Successful named/unnamed candidate, pool/no pool | `test_new_prepared_policy_is_independent`, four combinations; actual selected identity/subscription and cleared queue |
| Mutable pool isolation | same test mutates candidate entry and list; old values/order unchanged; nonalias assertions |
| No pool / pool disposal, repeat, ordinary pool cleanup error | `test_candidate_cleanup_joins_repeated_cancellation`, four combinations; real session disposal, retained task and old owner assertions |
| Repeated caller cancellation while cleanup blocked | same test holds reporter or pool boundary; caller remains pending until release, then cancellation escapes |
| Different history root | `test_new_rejects_candidate_history_root_change`; refusal before destructive old mutation |
| Existing busy/session-task gate and ordinary queue/new/auth | full `test_app.py`, authentication and session surrounding partitions |

No helper-only test is substituted for mounted preparation evidence. The first six
failure cases execute a subsequent real session/Faux invoke to establish usability.
The suite-wide HERDR stripping/disabled defaults, actual fake-only transport guard,
temp-owned state and terminal guard remain unchanged. No Herdr capability is enabled
by this family; no fake executable or system symlink is needed. LLMFactory is patched
before construction for the tests that invoke a model. Remaining mounted tests never
invoke/build an agent. No live provider, Herdr or terminal was intentionally invoked.

## Executed receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`,
`pyenv which python` => `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7.
No installation, new venv or environment-file changes.
Every receipt below has `.log` and `.exit` under this directory.

Define exact focused command F:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_session_lifecycle.py`

Define exact surrounding command S:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication tests/agents/slo_agent/test_session.py tests/agents/slo_agent/herdr/test_session_lifetime.py`

| Stem | Command | Observed result |
|---|---|---|
| t5-65-red | F | 4 failed / 62 passed, exit 1; escaping build/attach/name errors and lost cancellation subscription |
| t5-65-green1 | F | 4 failed / 62 passed, exit 1; new fixture incorrectly awaited async generator after preservation assertions passed |
| t5-65-surround1 | S | 432 passed / 1 deselected, exit 0; fixed fixture consumes invoke with async-for |
| t5-65-red2 | F | 2 failed / 68 passed, exit 1; pooled candidates alias old pool |
| t5-65-surround2 | S | 436 passed / 1 deselected, exit 0 after deep-copy change |
| t5-65-red3 | F | 1 failed / 74 passed, exit 1; different-root candidate adopted |
| t5-65-surround3 | S | 441 passed / 1 deselected, exit 0 after root refusal |
| t5-65-full | `PYENV_VERSION=slo-harness make test` | 7785 passed / 19 deselected, exit 0 |
| t5-65-smoke | `PYENV_VERSION=slo-harness make smoke` | 288 passed, exit 0 |
| t5-65-lint | `PYENV_VERSION=slo-harness make lint` | 300 errors / 64 files, exit 2; one new Task[Literal[True]] fixture annotation error |
| t5-65-surround-final | S | 443 passed / 1 deselected, exit 0 after typed fixture correction and added cancellation/notice cases |
| t5-65-lint-final | `PYENV_VERSION=slo-harness make lint` | baseline 299 errors / 63 files, exit 2; no ignores added |
| t5-65-full-final | `PYENV_VERSION=slo-harness make test` | 7787 passed / 19 deselected / 556 warnings, exit 0, 655.79s |
| t5-65-black | `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_herdr_session_lifecycle.py` | 2 unchanged, exit 0 |
| t5-65-diff | `git diff --check` | silent, exit 0 |
| t5-65-coreutils | `dpkg -V coreutils` | zero bytes, exit 0 |

`t5-65-lint-comparison.log` is silent, exit 0: compare sorted `error:` lines against
`t5-63-final-lint-confirmed.log`, normalizing only source line numbers via
`sed -E 's/:[0-9]+: error:/:LINE: error:/'`. No added/removed diagnostics.
Baseline lint is unwaived, not green. Full tests include existing warnings; none
were filtered. Focused helper includes 62 foundation tests; do not sum overlapping
counts. Production increments were approximately 50 substantive lines, then pool
copy, then root check, each followed by GREEN surroundings before the next unit.

## Context and review boundary

Consumed start64, current t5-code-test, frozen routing/scope-plan, supplied full
AGENTS/CLAUDE/docs RESEARCH context and root RESEARCH. Read entire canonical C in
three bounded ranges (1–750, 751–1500, 1501–2175), exact tasks 2401–3720 in two
ranges, accepted turn4 review and finalization receipt, actual app construction,
mount/preparation/replacement/config/delivery/auth and session disposal/join seams,
existing app/new/queue fixtures and test isolation/build rules. KB Welcome and
slo README/gotchas/tui-cli-session consulted; historical paths are not authority.
Selected shared engineering/coding/Python service/Faux/declarative/Textual and
workflow guidance used. Oversized concatenated skill reads truncated; Python
root/service/Faux were subsequently read individually. Do not describe this as a
fresh whole B/D audit or independent review; frozen prerequisite scope exclusions
and accepted prior families remain inherited evidence.

Author diff review confirms preparation precedes destructive old actions, deep
copy is confined to pool policy, and no session/helper owner was duplicated.

## Next family, deliberately NOT delivered

Shielded irreversible close/adopt and cancellation during old-preparation join are
not yet implemented. Successful adoption still uses the legacy post-preparation
sequence. App monotonic shutdown, session-keyed inbox transfer, retained quarantine,
viewer callers and auth callback identity remain pending T5 families. No claim that
this partial app can safely activate Herdr through all those paths. Do not enable
new app reporting until those families are integrated and tested.

Technical READY applies only to the finite candidate-preparation family above.
Whole T5/T6, global static acceptance, independent review and live compatibility
remain pending. No commits/push/PR/reset/clean/stash/global/KB/spec/other-worktree edits.
