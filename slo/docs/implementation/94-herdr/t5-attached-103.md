# T5 attached 103 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 103, retries 0. User turn and dispatch budgets unlimited. No subagents dispatched.

## Actual work

Read-only inspection only; no production or test files changed. Existing worktree modifications were preserved. No selection, specification, shared status, global, live-system, or other-worktree edits. No commit/push/PR/reset/clean/stash.

Confirmed against actual `src/tui/app.py`:

- `sub_agent_spawned` reaches `_maybe_launch_visualizer`, which still directly invokes synchronous `VisualizerLauncher.launch`.
- `_schedule_visualizer_launch` captures the selected session, deduplicates pending parent IDs and checks auto-visualize, closing and delivery quiescence.
- `_run_visualizer_launch` currently discards the typed async outcome and lacks a post-await current-session check.
- `_on_visualizer_launch_done` already retrieves noncancelled exceptions and removes only the identical registered task.
- Shutdown already drains the registry outside the submission gate.
- `_start_new_session` holds `_prompt_submission_lock` while joining the retained replacement commit. `_commit_replacement_session` revokes old reporting but does not drain the viewer registry. Inserting a drain into that body without changing gate ownership can deadlock a worker finalizer needing the gate.
- Ordinary prompt registration currently checks only `_app_closing`, not replacement transition. Releasing the submission gate for viewer drain therefore also requires explicit transition admission protection, not merely moving the await.
- The existing detached renderer has only synchronous boolean notice rendering. Canonical D assigns typed outcome formatting to the renderer, while this task authorizes only app.py and attached tests and defers detached migration. A temporary app-owned attached formatter versus a shared renderer change needs an explicit bounded design; do not silently claim canonical renderer consolidation is complete.

## Reading evidence and gaps

Read owner-102 and registry-101 receipts, actual replacement/registry/attached caller bodies and tests, selected surrounding renderer and prompt admission code, D 7.1–7.5, exact T5 D01/D02/D03/D08 samples, C 7.13–7.14 and first portion of 7.9. Read engineering routing/testing/ownership, Python conventions, coding rules/cadence, Textual, shared/Python declarative guidance, workflow skill first portion, and Faux testing first portion. AGENTS/CLAUDE/docs RESEARCH were supplied in context. Routing/scope-plan/KB bulk output truncated; complete prerequisite ingestion is not claimed. Accepted reviews and remaining C sections still need complete reading.

## Verification

- `PYENV_VERSION=slo-harness poetry run python --version`: Python 3.11.7, exit 0.
- `dpkg -V coreutils`: silent exit 0; receipts `t5-103-coreutils.log` and `.exit`.
- No tests, Black, mypy or final diff check run in this continuation. No new red/green evidence. The prior 243-pass receipt remains historical, not fresh verification here.

## Remaining scope

All requested implementation remains: replacement drain outside the gate with preserved candidate commit and transition cutoffs; typed truthful current-capture-only notices and fault-safe reset; attached caller migration; mounted actual gateway/Faux/temp history/context/registered fake Herdr proof; platform-thread replacement barrier; callback/error/disabled/auto-off/no-fallback coverage; focused and requested surrounding gates; final own-file static/diff/coreutils evidence. Detached migration and full make integration remain later. Baseline failures are unwaived.

**Verdict: INCOMPLETE — no implementation delivered in this continuation.**
