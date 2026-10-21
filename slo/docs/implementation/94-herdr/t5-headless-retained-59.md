# T5 continuation 59 — READY retained-runner family only

Same unfinished workflow turn 1: started 1/completed 0/historical partial 1/dispatch 59/retries 0. Effective turn and dispatch budgets unlimited. No agents dispatched here. Worker 58 interruption is not treated as an abort/retry event. This is bounded author verification, not independent review or complete T5 approval.

## Scope and actual implementation

Added `tests/cli/test_headless_retained.py`, with two parameterized actual-runner cases (recoverable final reap / persistent reap fault). No production file changed in this continuation: existing `src/cli/headless.py` ownership passed the new tests. Existing dirty files and prior evidence preserved.

Real path: `HeadlessRunner.invoke` → actual preparation/build/adoption → actual `SloAgentSession.start_external_reporting` → real reporter/sequence lease/registered fake subprocess → actual config-backed Faux graph submission → runner process cleanup → **runner outer finally** → actual session close and final retained cleanup. Neither session build, start, close, nor final cleanup is mocked. Factory replacement supplies `FauxChatModel`, not an injected session/agent. Credential resolver supplies only a synthetic API key. Headless native restore remains absent.

### Barrier and assertion map

| Boundary | Evidence in `test_runner_retains_child_and_lease_until_final_drain[persistent]` |
|---|---|
| Fixture child admission | Existing fake fixture grants executable/capture/barrier device+inode capability. New regular executable extended in place only after guard containment/identity validation. It records argv then stays alive; no real Herdr or terminal. |
| Actual lease acquisition | Reporter activation acquires real `HerdrSequenceStore` lock; no manual lease flag or acquire substituted. |
| Initial admitted-command reap | First `_terminate_and_reap` raises only after actual registered child admission. Activation command times out on the real transport deadline; process remains alive. |
| Initial transport close | Second reap raises; transport/lease remain retained. Activation failure does not prevent the real Faux prompt from completing. |
| Runner outer-finally final drain | Third reap signals `entered` and waits on `release`. At this event runner terminal kind is completed and actual session close outcome is retained. Same live process appears in all three attempts. |
| Strong reachability | Drop local runner/session/reporter bindings; force GC. Weakrefs still establish runner → session → reporter and exact lease identity while runner invocation is pending. |
| Concurrent lease exclusion | A separate real sequence store for the exact namespace/pane cannot acquire while final drain is held, or after persistent failure. |
| Repeated cancellation | Three `task.cancel()` deliveries with event-loop yields keep runner pending and child/lease owned before release. Persistent case repeats three more after failed final attempt. |
| Successful final drain | Release barrier; actual original reap executes. Child has returncode, transport empty, lease released and contender acquires. Only then runner propagates CancelledError. Sticky replacement uncertainty remains. |
| Persistent final fault | Release barrier; third reap raises. Final outcome stays retained, runner remains pending through repeated cancellation and GC, same child alive/lease locked. |
| No resend/release after revocation | Exactly one captured activation `release-agent` command. A new transport command after revocation is suppressed, not admitted, has no completion callback, and capture remains byte-identical. Repeated final drain returns identical cached outcome without fourth reap. |
| Controlled persistent teardown | Test restores only its reap patch, explicitly drains its owned transport, releases its owned lease, then cancels the private pending cleanup sentinel and joins runner. It never treats public cancellation as cleanup. Both cases end resources-drained with private credential cleared. |

`asyncio.sleep(0)` delivers cancellation; it is not a timing-based inference. Positive progress uses Event barriers and bounded waits. No new shared process framework, JSONL expansion, TUI/scheduler/session-service edits or spec changes.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `PYENV_VERSION=slo-harness pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; `PYENV_VERSION=slo-harness python --version` → Python 3.11.7. No venv or packages created. Approved safe helper supplies test environment and always includes DAO/projection tests.

Prefix: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.

Target argument: `tests/cli/test_headless_retained.py`.

Final surrounding arguments:

```text
tests/cli/test_headless_retained.py tests/cli/test_headless_herdr.py tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_spawn_env.py
```

All receipts below are in this directory as `<stem>.log` and `<stem>.exit`:

| Stem | Command / result |
|---|---|
| t5-59-target | Prefix + target: 64 passed, 4 warnings, exit 0 |
| t5-59-surrounding | Prefix + surrounding: 2 failed, 213 passed, 6 warnings, exit 1. New test used nonexistent `result.outcome.admitted`; exact AttributeError in log. Corrected to existing `result.admitted`. Test-authoring error, NOT production RED. |
| t5-59-format | `PYENV_VERSION=slo-harness poetry run black tests/cli/test_headless_retained.py`: exit 0 |
| t5-59-final | Prefix + surrounding after correction/format: **215 passed, 6 warnings, exit 0** |
| t5-59-black | `PYENV_VERSION=slo-harness poetry run black --check src/cli/headless.py tests/cli/test_headless_retained.py`: two unchanged, exit 0 |
| t5-59-diff | `git diff --check`: silent, exit 0 |
| t5-59-coreutils | `dpkg -V coreutils`: **silent**, exit 0, after final suite |

Reviewed complete added test and existing actual runner cleanup boundaries. Production RED/fix cycle not needed: no production failure exposed. Historical full/lint baseline **299 errors/63 files remains unwaived**; no new full make/smoke/lint run or diagnostic-comparison claim.

## Read scope and remaining work

Consumed supplied AGENTS/CLAUDE/docs RESEARCH; read root RESEARCH, routing/scope plan, handoff57/current status, actual headless-heritage tests, actual session quarantine cases, runner outer cleanup, session final-drain owner, reporter activation/lease/close and transport mechanics, registered fixture/guard and build helper/Makefile. Loaded shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python/Faux/declarative/named arguments, workflow SKILL. Consulted KB Welcome, actual slo README (no index.md), gotchas. Canonical read-only C7.2, final local-drain gateways/C7.14; exact T5 C23 sample; B cleanup/isolation/A2 correction and coverage additions informed this test. Some combined exploratory reads truncated; this is **not complete canonical or required full-document read closure**. No KB/global edits authorized or made.

Retained-runner family is READY for review. Overall headless family/T5 remains INCOMPLETE: exact whole JSONL parity, remaining status/notification and combined cleanup faults, broader read closure, final full/smoke/lint and independent review are separate later work. No claim about live Herdr compatibility, mounted TUI quarantine, or every lifetime cutoff. No commit/push/PR/reset/clean/stash/other-worktree/live-system/specification edits.
