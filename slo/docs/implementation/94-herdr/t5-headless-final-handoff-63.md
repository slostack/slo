# T5 headless final handoff 63 — INCOMPLETE (static gate)

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 63, retries 0. Effective turn/dispatch budgets unlimited. No agents dispatched. This is author evidence, not independent review or full-feature acceptance.

## Owned change

Only `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py` and continuation-63 evidence/status documents were edited. No production changes, deadlines changed, transport mocks, pre-generated A reservations, specification/global/other-worktree changes, commits or external actions.

The operational test now starts the actual registered fake viewer and observes its executable capture while the real shared lock is held BEFORE publishing A. A's real off-thread sequence reservation has a controlled entry/release barrier. The test awaits reservation completion (`prepared`) separately from transport entry (`queued`), asserts durable disk sequence, real lock waiters, pending A/viewer and no admitted ticket, then publishes B before release/close/cancel/timeout. Same-generation and changed-generation cases retain exact command order, zero A entry, higher B sequence, one-shot retention and duplicate refusal. The production one-second timer is unchanged. The two-second test watchdog is not the transport deadline.

The separate `test_reservation_outlives_viewer_deadline` deliberately holds the real filesystem reservation until the real viewer timeout finishes. It proves no reserved ticket or queued waiter before reservation completion, then publishes B and releases reservation: late A is durably reserved but suppressed, with only split in executable capture. This is expiry behavior, NOT a substitute pass for canonical positive G2.

Positive G2 still explicitly fails if viewer expiry prevents the required ordering. No wall-clock positive test can guarantee scheduling under arbitrary load. This revision separates completion observation from queue observation; it does not remove executor scheduling from the positive case or claim that arbitrary-load guarantee. A failed positive case must not be converted into a timeout-case pass.

## Test-first causal evidence

`t5-63-red.log`: added viewer-first assertions at the actual reservation boundary to candidate62. Candidate62 fails (1 failed / 62 passed): its reservation precedes viewer entry.

`t5-63-green.log`: first ordering repair exposed a test instrumentation defect (8 failed / 73 passed): the A-only lock assertion also applied to B after viewer completion, causing sequence-unavailable. Fixed by limiting that barrier/assertion to A; production untouched. `t5-63-green2.log`: 81 passed. Added separate real deadline/reservation case and formatted owned file: `t5-63-expiry.log`, 82 passed. The earlier deterministic pending-reservation RED remains in `t5-62-red.log`; this is not retrospective proof of scheduling state in historical full60.

## Fresh executed gates

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`, Python 3.11.7 (`/root/.pyenv/versions/slo-harness/bin/python`). No venv installation. Targeted commands use `bash docs/implementation/94-herdr/t1-dao-check.sh`; its 62 foundation tests are included, not additional unique coverage. All receipt stems below are relative to this directory; `.log` and `.exit` retain output and status.

| Receipt | Command | Result |
|---|---|---|
| t5-63-expiry | approved helper + tests/agents/slo_agent/herdr/test_visualizer_acceptance.py | 82 passed, 2 warnings, exit 0 |
| t5-63-package | helper + tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 1345 passed, 125 warnings, exit 0 |
| t5-63-final-test | PYENV_VERSION=slo-harness make test | **7772 passed, 19 deselected, 550 warnings**, 629.63s, exit 0 |
| t5-63-final-smoke | PYENV_VERSION=slo-harness make smoke | **288 passed, 2 warnings**, exit 0 |
| t5-63-final-lint | PYENV_VERSION=slo-harness make lint | 298 errors/63 files, exit 2; incremental result omitted one baseline registry YAML-stub error |
| t5-63-lint-clean-cache | PYENV_VERSION=slo-harness poetry run mypy --no-incremental src/ tests/ | 299 errors/63 files, exit 1 |
| t5-63-final-lint-confirmed | PYENV_VERSION=slo-harness make lint | **299 errors/63 files**, exit 2; baseline unwaived |
| t5-63-black-final | PYENV_VERSION=slo-harness poetry run black --check over all 98 paths in t5-63-changed-python.txt | **FAIL**: 97 unchanged, one would reformat |
| t5-63-diff | git diff --check | silent, exit 0 |
| t5-63-coreutils | dpkg -V coreutils after gates | zero bytes, exit 0 |

`t5-63-lint-confirmed-comparison.log` compares diagnostic multisets to `t5-55-final-lint.log`, normalizing line numbers only: **ADDED [] / REMOVED []**. The initial 298 result is retained, not silently called exact baseline. Rebuilding mypy's cache is a diagnostic experiment, not a source repair or waiver.

The first Black command used repository-root-prefixed tracked paths from git and failed before checking files (`t5-63-black.log`). Corrected `git diff --name-only --relative` plus untracked Python enumeration produced the complete check above. No paths were excluded to obtain green.

### Explicit remaining blocker

`tests/cli/test_headless_retained.py` has one excess blank line after imports. Exact Black proposal is retained in `t5-63-retained-format.diff`. This file is outside the user's authorized viewer/new-helper write scope; it was NOT changed. The owned acceptance file independently passes Black. Whole-family READY is withheld: all-changed Black fails and lint remains unwaived. A formatting-only scope authorization is needed for the retained test; baseline attribution does not waive lint.

## Read/evidence boundary

Consumed current routing.md/scope-plan.md, root RESEARCH, supplied AGENTS/CLAUDE/docs RESEARCH, actual candidate62 report/test, headless-audit62, current status/history, real transport/reservation/viewer owners and fixture safety boundaries. Read selected engineering routing/testing/ownership, Python root/style/Faux, coding rules/cadence and exact workflow files; KB Welcome/slo README/gotchas. Read canonical B G2/transport contract and accepted turn4 review directly. The full canonical D/C/task attachment and on-disk project-doc reread closure requested for this continuation was **not completed**; do not promote inherited audit62 read closure into newly executed reads. Audit62's finite headless/exclusion map and 435-pass receipt remain inherited evidence, unchanged.

Safety remained enabled: registered temp-owned regular fake executable/capture/barrier identities, autouse HERDR stripping/disabled default, independent fake-only spawn capability, real-terminal guard, no real provider/Herdr/windows. Coreutils verified silent. No production repair was substantiated.

## Finite disposition

- Viewer-first G2: positive operational test and separate deadline-crossing regression pass, including full suite. Arbitrary-load positive guarantee is not claimed.
- Headless families54–61 and exclusion audit62: inherited evidence retained; no new implementation changes.
- Fresh full/smoke: green on current code/test bytes.
- Static: exact unwaived lint baseline; all-changed Black blocked outside write scope.
- Remaining requested read closure: explicit above.
- **Whole-family READY withheld.** Full TUI integration, T6/live acceptance and independent review remain later work, not claimed by this handoff.
