# T5 attached wire 104 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 104, retries 0. User turn/dispatch budgets unlimited; no agents dispatched. No commit/push/PR/reset/clean/stash/global/live/specification/other-worktree edits. Selection files untouched.

## Actual changes

- `src/tui/app.py`: actual `sub_agent_spawned` routing now reaches the existing synchronous registry scheduler instead of directly calling the synchronous platform launcher. The scheduler captures the selected session and parent before task execution and retains pending deduplication/master auto-off admission.
- Worker awaits `VisualizerLauncher.launch_async`, normalizes unexpected exceptions to fixed failed outcomes, then rejects closing/quiescing/replaced-session completions before any notice or guard mutation.
- Attached-only typed notice method distinguishes opened/submitted/reused/failed/skipped. Submitted explicitly describes command submission, not process execution or paint. Failed/skipped offer the captured-parent manual command; known pane is retained in notices. Failed outcome resets the attached request guard in `finally`, even if notice writing throws. No raw exception is logged.
- Existing identity-checked completion callback and shutdown drain unchanged. Existing session adapter one-shot map unchanged. Detached path unchanged.
- `tests/tui/test_herdr_attached.py`: mounted Faux-backed actual sub-agent routing + async gateway mock, five outcome cases, replacement/closing/quiescing late cutoff cases, gateway/notice exception isolation.

## Branch map and verification

Commands run from application root with approved `PYENV_VERSION=slo-harness`; test prefix `bash docs/implementation/94-herdr/t1-dao-check.sh` adds DAO/projection safety tests. All logs/exits named below are retained here.

| Receipt | Result |
| --- | --- |
| t5-104-wire-red | Actual attached route never awaited async gateway: 1 failed, 62 passed; exit 1 |
| t5-104-wire-green | Attached + selector/registry/platform/workflow receive surrounding: 177 passed; exit 0 |
| t5-104-outcome-red | Initial test fixture Mock session invalid for app constructor: 5 failed/63 passed; not behavior RED |
| t5-104-outcome-red2 | Real config-backed session fixes fixture; all five missing outcome writes fail: 5 failed/63 passed; exit 1 |
| t5-104-outcome-green | Outcome implementation + launcher/receive/shutdown/replacement/inbox partition: 241 passed; exit 0 |
| t5-104-final | Same partition plus late/error tests, after Black: 246 passed, 16 warnings; exit 0 |
| t5-104-black | Black app.py/new attached test; exit 0 |
| t5-104-diff | git diff --check; silent exit 0 |
| t5-104-coreutils | dpkg -V coreutils; silent exit 0 |

## Missing acceptance / constraints

**Not READY.** Mounted positive registered fake Herdr via real gateway/context/history split→rename→run has NOT been added. The mounted test mocks launch_async and is only routing/orchestration evidence. Callback identity/error coverage remains inherited, not expanded. App-wide surrounding tests, own-file mypy/static baseline comparison, full make integration and independent review have not run here. Full suite baseline remains unwaived. Late/error cases were added after implementation (coverage, not test-first RED).

Canonical D assigns shared outcome formatting to the renderer. This bounded attached-only app formatter is an explicit interim implementation under the app.py ownership restriction; detached consolidation must move it to the shared renderer, not duplicate it. Replacement transition admission/drain outside the submission gate is NEXT family, deliberately unchanged; captured-session checks suppress late presentation now but are not proof of replacement resource drainage.

Read t5-attached-103, registry101/owner102, actual caller/worker/renderer, D7.1 and relevant D search context, provided AGENTS/CLAUDE/docs RESEARCH, engineering routing/testing/ownership, coding rules/cadence/declarative and portions of routing/scope/KB. Bulk prerequisite output was truncated; complete required skill/sample/C/accepted-review reading is not claimed. No KB/global edits per user restriction.
