# T5 activation proof 82 — INCOMPLETE: session-owned successor-authority defect

Accounting preserved: same unfinished turn 1, started 1/completed 0/historical
partial 1, supplied dispatch 82, retries 0. Unlimited turns and dispatches; no
budget stop. No agents launched. INIT audit remains the other lane's work.

## Changed files and scope

Added only `tests/tui/test_herdr_activation_composed.py` plus this receipt and
`t5-82-*` logs/exit files. No production edits, shared-status edits, specification
edits, commits or external actions. Existing partial work preserved.

## Reproducible production blocker (not a fixture failure)

`test_mount_native_save_display_and_new_lease_order` mounts a config-backed
session with the real default temporary history, registered fake executable,
real inbox/ownership lease, restore store, sequence lease, shared transport and
reporter. LLMFactory is patched to Faux **before construction**, not replaced
with an injected session agent. Original mount demonstrably claims, saves an
immutable native record, advertises its reference and acknowledges display.
The real viewer shares the real reporter transport. `/new` goes through the
slash-command dispatcher.

Replacement correctly releases the old inbox ID and acquires the new inbox ID
with the same captured owner. It also sends old pane release and clears display.
But no new pane claim occurs:

```
AssertionError: HerdrReporterCloseOutcomeDAO(replacement='uncertain', resources='drained')
assert not new._herdr_suppressed
```

The final regression additionally asserts, before the failing assertion:

- `reporter._close_task.result().resources == 'retained'`
- `reporter._transport_close_task.result().replacement == 'safe'`

Both pass. `HerdrReporter._close_outcome()` includes the still-held lease in its
provisional uncertainty. `SloAgentSession._close_herdr_once()` ORs that provisional
`replacement == 'uncertain'` into `_herdr_close_uncertain` before calling
`close_transport()`. Successful final seal/drain/unlock cannot clear it. App
`_adopt_replacement_session()` correctly honors that uncertainty and permanently
suppresses successors. Fix belongs in **sessions/service.py / reporter outcome
semantics**, outside this lane's authorized production file (`app.py`). Do not
weaken app quarantine or reinterpret cached outcomes in the app. Session owner
must distinguish genuine remote uncertainty from provisional local retention,
then rerun this unmodified failing test and surrounding tests.

## Existing correct cases now composed

Five new passing parameter cases accompany the failing native replacement case:

1. Explicit-disabled mount/new: no Herdr assembly, task, integration directory or
   fake command; actual PromptInput/Faux answer and persisted user history remain.
2. Outside-Herdr equivalent, retaining platform destination.
3. Unmount while real reporter assembly is pending: repeated cancellation joins
   the mount/session owner; no late report-agent claim, preparation or timers.
4. Unmount before real reporter start: same retained-owner/cutoff assertions.
5. Actual mounted enabled reporter with injected real lease-unlock refusal:
   two slash replacements suppress every successor; GC does not lose the one
   app-retained old owner; actual contender cannot acquire its lease; final local
   drain releases ownership and clears the app slot. No successor CLI commands.

These are existing-correct proofs, not fabricated RED/production-fix claims.
The native first-mount assertions pass but the combined replacement test is RED;
it is not counted as a passing happy-path acceptance test.

## Executed verification

CWD: `/root/Code/slo-94-herdr-integration/slo`.
All pytest calls use `PYENV_VERSION=slo-harness bash
 docs/implementation/94-herdr/t1-dao-check.sh <tests>`; approved fallback includes
62 DAO/projection tests. Registered fake-only spawn guard, HERDR stripping,
temporary SLO_HOME and terminal guard remain enabled. No system symlinks.

- `t5-82-composed-first`: 1 failed/62 passed; fixture typo `_display_ack`.
- `t5-82-composed-second`: 1 failed/62 passed; successor-claim timeout.
- `t5-82-composed-red`: 1 failed/62 passed; precise suppressed-successor assertion.
- `t5-82-branches`: 3 failed/64 passed; two fixture `read_events` typos corrected
  to actual `load_events`; production failure unchanged.
- `t5-82-branches-corrected`: 1 failed/66 passed.
- First `t5-82-surrounding.log` invocation exceeded tool timeout at 120 seconds;
  partial log only, no valid exit receipt or pass claim.
- `t5-82-surrounding-final`: **1 failed, 334 passed, 1 deselected**, exit 1,
  194.21 seconds. Exact test arguments: composed activation, activation,
  test_herdr_replacement.py, test_herdr_app_shutdown.py,
  test_herdr_session_lifecycle.py, test_app.py, test_queued_prompt_block.py,
  tests/tui/authentication. Only failure is the new successor regression.
- `t5-82-final-target`: after adding precise provisional/final outcome assertions,
  **1 failed, 67 passed**, exit 1; composed activation file plus wrapper's 62 tests.
- `t5-82-black`: Black --check app.py and both activation test files, exit 0.
- `t5-82-diff`: git diff --check, silent exit 0.
- `t5-82-coreutils`: dpkg -V coreutils, **silent exit 0**, after final suite.

## Remaining obligations / honest boundary

Activation family is NOT READY. The session-owned blocker prevents safe-successor
acceptance within this lane's write authority. No xfail/skip/assertion weakening
or new static ignore was added. Full make gate awaits lane integration as requested;
historical 299 errors/63 files static baseline is unwaived, not revalidated here.
Additional complete activation failure/cutoff matrix (contender, activation defects,
each runtime await and diagnostic failure, remote-only collectability) remains
unproved by this new file; existing unit tests do not substitute for it. No full
T5/T6 or independent review/completion claim.

Read routing/scope plan, continuation 81, current app/session/reporters/restore and
real fixture safety boundaries; selected engineering ownership/testing/routing,
coding rules/cadence/declarative, Python/Faux/style, Textual and workflow SKILL;
KB entry and Slo gotchas; root research, supplied project instructions and
actual docs research context. Canonical C activation/replacement/7.11/7.14 excerpts
were read directly. This receipt does **not** claim a fresh full exact-sample
B/C/D audit or all canonical C7.9–7.14 ingestion; INIT exact-citation audit remains
with its separately assigned lane. No KB/shared research edits under this scope.
