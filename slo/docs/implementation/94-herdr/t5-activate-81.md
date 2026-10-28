# T5 continuation 81 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 81 (user supplied), retries 0. Unlimited turns and dispatches;
no budget exhaustion claimed. No agents or external actions.

## INIT status

INCOMPLETE audit. Prior evidence is preserved. This continuation did not finish
the requested exact branch/sample map, canonical C7.9–7.14 reads, or all scoped
skill reads. No INITREADY claim. Project instructions and docs/RESEARCH were
available in context; not represented as fresh disk reads. Read continuation 80,
activation test, shared runtime, shutdown fixture, KB Welcome/gotchas and shared
engineering policies. Combined skill output was truncated; not a complete read.

## Activation status

INCOMPLETE family; the existing RED ordering regression is now GREEN.
`src/tui/app.py::_finish_replacement_runtime` now calls captured-session
`start_external_reporting(interactive=True)` after delivery, contains ordinary
activation failure through the existing safe notice, rechecks current/closing
eligibility after the await, then refreshes context before title and usage.
Canonical C `94.b.2-session-publication-and-native-restore.md:925–948` was read
with its surrounding failure-boundary explanation (900–970).

The first surrounding run exposed a shutdown fixture conflict: it installed an
inactive reporter with a manually acquired real fixture lease before mount.
Mount now correctly activates reporting, so that fixture no longer preserved
its intended inactive-reporter state. `test_persistent_real_lease_keeps_app_shutdown_pending`
now suppresses mount reporting and attaches its fixture reporter after mount.
Its real failed-unlock, contender refusal, retained-owner and repeated-cancel
assertions remain intact. This is inactive-reporter shutdown evidence, NOT
mounted enabled activation acceptance.

## Commands / retained receipts

All commands run from application root with PYENV_VERSION=slo-harness.
Test commands use `bash docs/implementation/94-herdr/t1-dao-check.sh` (includes
62 DAO/projection tests); artifacts below have matching `.exit` files.

- Existing RED: continuation 80 `t5-80-order-red.log`, 1 failed/62 passed.
- `tests/tui/test_herdr_activation.py`: `t5-81-order-green.log`, 63 passed, exit 0.
- Initial surrounding command incorrectly named nonexistent test_prompt_queue.py:
  `t5-81-surrounding.log`, exit 4; no tests ran.
- Corrected surrounding: `t5-81-surrounding-corrected.log`, 1 failed/327 passed/
  1 deselected, exit 1. Exact assertion: `assert app._retired_herdr_session is old`
  observed None in the inactive-reporter lease fixture described above.
- Shutdown + activation after fixture correction: `t5-81-shutdown-green.log`,
  73 passed, exit 0.
- Final surrounding: test_herdr_replacement.py, test_herdr_app_shutdown.py,
  test_herdr_session_lifecycle.py, test_herdr_activation.py, test_app.py,
  test_queued_prompt_block.py and authentication/: `t5-81-surrounding-green.log`,
  329 passed/1 deselected, exit 0.
- `poetry run black --check src/tui/app.py tests/tui/test_herdr_activation.py
  tests/tui/test_herdr_app_shutdown.py`: t5-81-black.log, exit 0.
- `git diff --check`: t5-81-diff.log, silent exit 0.
- `dpkg -V coreutils`: t5-81-coreutils.log, silent exit 0.

## Outstanding acceptance

No newly added mounted Faux + registered-fake activation proof. Still required:
original native eligibility, /new old-release-before-successor-claim, disabled
zero-I/O parity, activation pending during unmount with repeated cancellation,
sticky quarantine suppression, per-await cutoff/fault tests, complete INIT audit
and prescribed sample/skill reads. Full make/lint not run because family is not
ready. Historical 299 errors/63 files lint baseline remains unwaived. No new
ignore or waiver. Inbox/viewer caller work untouched. No whole-family READY or
independent-review completion claim.
