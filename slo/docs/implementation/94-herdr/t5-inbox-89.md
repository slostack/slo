# T5 inbox / final registration continuation 89 — INCOMPLETE

Only the shared synchronous final registration boundary has been implemented.
This is NOT READY INBOX/REGISTRATION, complete T5, independent review, or live
acceptance. Same unfinished turn 1: started 1, completed 0, historical partial 1,
supplied dispatch 89, retries 0. Turns and dispatches unlimited; no agents launched.

## Change and finite branch status

Both existing `_in_flight_task = create_task(...)` sites in `src/tui/app.py`
now delegate to `_register_prompt_task(text=...)`. The one owner checks
`_app_closing` and creates/registers the coroutine synchronously with no intervening
await or callback. It returns an explicit bool. `_run_prompt` and shutdown's
existing execution/abort/join policy are unchanged. No join under the gate added.

| Branch | Evidence / remaining work |
|---|---|
| Local echo suspended during public shutdown | New mounted Faux regression in `tests/tui/test_herdr_inbox_cutoffs.py::test_prompt_registration_shutdown_local_echo_pending`; real echo, real submission lock and public on_unmount; RED then GREEN |
| Both assignment sites use final gate | Source inspection; inbox caller currently discards bool, so disposition is NOT complete |
| Closing ordinary-entry / queued successor | Not implemented; full prescribed registration matrix remains |
| Claim pending / workflow advance pending | Not implemented; actual real-store mounted cutoff tests remain |
| Before chat registration / already registered successful ack and abort variant | Not tested; final gate alone does not establish ack correctness |
| Four delivery modes and explicit handler bool | Existing behavior retained, not migrated; no claim of new disposition safety |
| Captured session/store identity, retained claim, no auto replay, fixed diagnostics | Not implemented/tested |
| Full disposition matrix including exceptions/cancel/ack outcomes | Pending |

## Exact executed commands

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved fallback, no environment or
package installation changes. `check` below expands to
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
The script adds 62 DAO/projection tests and forces disabled Herdr test settings.
Existing suite isolation/terminal guards remain untouched; model factory returns
Faux. New test uses pytest temp history only and creates no fake executable/link.

- `check tests/tui/test_herdr_inbox_cutoffs.py` → **1 failed, 62 passed**, exit 1;
  `t5-89-registration-red.log/.exit`. Failure is a post-cutoff registered task,
  not a missing helper or artificial fake-only predicate. Baseline task drained
  outside submission lock in fixture cleanup.
- `check tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/scheduling`
  → **377 passed, 25 warnings**, exit 0, 168.66s;
  `t5-89-registration-green.log/.exit`.
- `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_herdr_inbox_cutoffs.py`
  → two unchanged, exit 0; `t5-89-black.log/.exit`.
- `git diff --check` → silent exit 0; `t5-89-diff.log/.exit`.
- `dpkg -V coreutils` → silent exit 0 after tests; `t5-89-coreutils.log/.exit`.

Full make test/smoke/lint NOT run for this incomplete family. Prior 88 full
7962/smoke288 and lint298/63 remain historical, not post-edit evidence. Lint remains
UNWAIVED. No ignore/skip/xfail added.

## Read evidence and continuation

Read routing.md, scope-plan.md, current t5-code-test, full activation audit88,
root RESEARCH, actual app claim/handler/chat/local registration/finalizer code,
initial lifecycle and receive-path test sections, and actual inbox store API.
Canonical C lines 1100–1569 read including complete inbox corrective contract and
named matrices. Complete C, exact tasks2401–3720, accepted reviews, actual disk
AGENTS/CLAUDE/docs RESEARCH reread and remaining test/guard inspection are NOT
claimed complete in this continuation. They remain required before family closure.
Project-context versions of AGENTS/CLAUDE/docs RESEARCH were supplied.
Loaded engineering routing/testing/ownership, coding rules/code-test-loop,
Python root/declarative, Faux test guide, Textual guide, shared declarative and
workflow SKILL. Combined shared-declarative output initially truncated; missing
first280 lines subsequently read. KB Welcome/slo README/gotchas consulted read-only.

Continue the same family: complete read closure; add real temp inbox mounted
barriers and exact bool disposition test-first; wire captured claim/advance/ack
cutoffs and update direct-handler test locks/explicit booleans; finish queue/entry
registration matrices with successful/abort admitted-task identity proof; run
surroundings each increment and final full/static gates. Viewer entry paths are
NEXT only after this family, then T6 and independent review. No canonical/global/
live/other-worktree changes, commits, pushes, PRs or reset/clean/stash performed.
