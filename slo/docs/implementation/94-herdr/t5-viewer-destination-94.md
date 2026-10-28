# T5 viewer destination 94 — INCOMPLETE gateway/selector family

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 94, retries 0. Unlimited turn/dispatch budgets; no agents dispatched. No commits, external systems, canonical specifications, global settings or other worktrees changed.

## Implemented bounded unit

`VisualizerLauncher.launch_async(parent_session_id=..., session=...)` applies the live auto-visualize gate before consulting destination. Platform delegates to the existing retained/joined thread helper; Herdr delegates to the captured session gateway; unavailable returns fixed failed. No Herdr outcome falls through to platform. No registry, reservation map, context parser, or Herdr command construction was added.

This method is NOT yet called by the app. The real session gateway is still missing, so the Herdr branch has only orchestration-fake evidence. Do not call this family READY or invoke this branch with a real session yet.

## Finite branch map and execution

- Auto disabled × platform/herdr/unavailable: skipped; neither delegate called.
- Auto enabled/platform: joined platform delegate; opened result.
- Auto enabled/herdr: exact requested parent forwarded; skipped result retained; zero platform calls.
- Auto enabled/unavailable: failed; neither delegate called.
- Actual async platform path: real synchronous launch and spawn boundary under root autouse `_default_spawn` guard, with only argv discovery patched; no terminal opened.
- Existing joined-thread true/false/error/repeated-cancellation tests retained.

All commands executed from this checkout with `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`:

1. `tests/tui/test_herdr_visualizer.py`: `t5-94-selector-red.log/.exit`, exit 1, **7 failed, 66 passed**. All new failures were absent `launch_async`.
2. `tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_app.py tests/tui/test_herdr_session_lifecycle.py`: `t5-94-selector-green.log/.exit`, exit 0, **360 passed, 31 warnings**, 174.10s.
3. Black formatted the new tests only; production unchanged by formatting. `t5-94-black.log/.exit`, exit 0. Diff check and coreutils verification both silent exit 0 (`t5-94-diff`, `t5-94-coreutils`).

## Explicit remaining work

Session eligibility gateway was not implemented. It still needs canonical requested-parent UUID validation, enabled/default-root history, same-workdir/plain-PATH/restorable-interactive provenance, persisted metadata and exact-parent attached-event or existing `OrchestratorContextReader` evidence. Private context must remain local; no TUI dependency or duplicate parser. Revalidate close/revocation and preserve reporter-owned adapter authority. Exercise real temp-owned registered fake capability and persisted history, not merely mocked adapter invocation.

Read closure remains incomplete: inspected actual session Herdr symbols, T4 launcher, destination/context-reader D sections, root fixture route, previous checkpoint and shared/Python core skills. Canonical C, task samples 2401–3720, accepted reviews, complete actual instruction/research reads and remaining requested skills were not reconciled in full. Reading files into a scratch capture does not count as that reconciliation.

App registry/caller migration, inbox audit, occupied-retired/viewer cleanup composition, final T5/T6 and independent review remain later. No full make gate rerun because the requested family is not ready. Historical lint **298 errors / 63 files** remains unwaived; no ignore added. The surrounding gate is not a substitute for full acceptance.
