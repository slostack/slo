# Feature 96 expectations-versus-code review — blocked recovery attempt

## Verdict and scope

**INDETERMINATE — review incomplete; acceptance not approved.** High confidence in the launcher blocker and recovered specification identity; no confidence assessment of implementation conformance is possible from the unfinished review. This is a recovery/blocker report, not a completed independent source review.

**No tests ran.** No builds, linters, type-checks, formatting, installs, reviewed TUI/application launches, code changes, staging or commits were performed. Inspection used read-only source/git/log queries. The only intentional repository write is this report. The authorized child-agent CLI launch failed before import. Existing tracked unstaged and untracked work was preserved.

## Recovery evidence and budget

- Previous workflow: `wf-5e42`; orchestrator session `541edc66-194e-4c23-bf36-06fafb40c0aa`.
- Its handle at `/root/.slo/sessions/history/aa748ac9-d92e-45c0-b80d-a46198eed3a5/workflows/wf-5e42.json` records `state: failed` and the original read-only review brief.
- Its `stderr.log` reports `/root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python: Error while finding module specification for 'src.cli' (ModuleNotFoundError: No module named 'src')`; `stdout.jsonl` is zero bytes. No child artifacts were found in that session directory.
- User-provided recovery context records two orchestrator startup failures and zero prior child dispatches. The inspected first-session evidence supports that account; a separate second-startup log was not independently established. Counts are carried forward from that explicit context, not reset or assumed from missing logs.
- `src/agents/slo_agent/orchestrator/process.py:318–345` builds children using `sys.executable -I -m src.cli`. Starting this orchestrator without `-I` does not change that child command.
- One focused ownership/history/lifecycle inspection was attempted through `spawn_sub_agents`. Task `ownership-history-lifecycle`, child session `266f7077-3134-4b6e-a238-fa6fddebeee0`, returned **failed**, exit code **1**, with the same import error and no answer.
- Overall ad-hoc dispatch consumption: **1/6**, leaving **5**. Child retries: **0**. Startup retry count is separate: this run was the user-authorized second startup retry. No aborted child was resumed. No repeated identical import attempts, nested orchestrators, launcher edits or installs were made.
- Navigation/visibility/snapshot and app-integration/packaging inspections were not dispatched after the shared launcher failure. No reviewer completed a source inspection. No solo implementation-review takeover was substituted for the required delegation.

## Authoritative specification recovered

The original normative specification is **available**, contrary to the earlier limited search:

`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/tui-refactor-side-quest/96.e.1-chat-transcript.html`

SHA256: `45ca028feaa92ba118424fb1ae5a08e7097e8b7f7df3bd40ed85bd5532312c38`.

This matches the identity recorded in `docs/implementation/96-chat-transcript/handoff.md:286`. The absolute location was recovered from `precise-scroll-proofs.md:10`. The repository-local `specifications` path does not exist in this worktree. Specification AC01–AC13 occur at HTML lines 385–397; exact navigation acceptance starts at line 415 (`#navigation-tests`). Relevant excerpts were located, but the full specification and referenced spec family were not comprehensively reviewed.

Implementation notes, AGENTS.md and docs/RESEARCH.md remain context and claims, not substitutes for this normative source.

## Expectation-to-code review matrix

All statuses below are **INDETERMINATE / not independently reviewed**. Code paths are the intended inspection targets, not verified implementation mappings. Specification line references refer to the absolute HTML path above. This matrix preserves the requested scope without fabricating source conclusions or implementation line citations.

| ID / normative line | Expectation | Code inspection targets | Evidence limitation |
|---|---|---|---|
| AC01 / 385 | Ordered 65-entry history, 30/30/5 loading, live once, hydration read-only | `components/chat_transcript/component.py`, `app.py`, `transcript_projector.py` | Historical claim only, dispatch12.md:97 |
| AC02 / 386 | Thinking-ID repair, terminal sealing, replay adjacency | `transcript_projector.py`, `widgets/assistant_stream_block.py`, `widgets/assistant_stream_thinking_block.py` | Historical claim only, dispatch12.md:98 |
| AC03 / 387 | Tool identity/partials and steering lifetimes | `transcript_projector.py`, component, tool widgets | Historical claim only, dispatch12.md:99 |
| AC04 / 388 | 500-child window, newest ten/live protection, logical cursor | Component | Historical claim only, dispatch12.md:100 |
| AC05 / 389, 399–415 | Follow snapshots, native navigation, named anchors and exact interruption proofs | Component, both streaming widgets | Exact proof gaps already recorded, dispatch12.md:32–50,101 |
| AC06 / 390 | Single-flight reads, stale-result rejection, cancellation and lifecycle admission | Component, `app.py`, projector | Historical claim only, dispatch12.md:102 |
| AC07 / 391 | Hidden updates, named-row restoration, identity/focus retention | Component, `agent_pane_manager.py`, `app.py` | Manual evidence gap recorded, dispatch12.md:103 |
| AC08 / 392 | Native visible selection/raw copy and one clipboard funnel | Component, `app.py`, message widgets | Historical claim only, dispatch12.md:104 |
| AC09 / 393 | Clear/new/expansion semantics and app-owned queue | `app.py`, component, `app.tcss` | Historical claim only, dispatch12.md:105 |
| AC10 / 394 | Tree siblings survive clear/window; exporter remains external | `app.py`, component | Historical claim only, dispatch12.md:106 |
| AC11 / 395 | Child exclusion, exact workflow notices, unchanged workflow ownership | `app.py`, `adapters/workflow_notice.py`, `adapters/workflow_progress.py` | Historical claim only, dispatch12.md:107 |
| AC12 / 396 | Standalone CSS, themes/sizes, wheel and sdist resource loading | `css.tcss`, component, `app.tcss`, `pyproject.toml` | Historical claim only, dispatch12.md:79–80,108 |
| AC13 / 397 | Independent adapters, acyclic imports, record/visual-order separation | `adapters/transcript.py`, `workflow_notice.py`, `workflow_progress.py`, projector | Historical claim only, dispatch12.md:109 |

Paths in the matrix are relative to `src/tui/`, except `pyproject.toml`; component and adapter paths are under `src/tui/components/chat_transcript/`.

## Severity-ranked findings

### Blocking — review infrastructure cannot start standard children

**Demonstrated operational failure, not a Feature 96 source defect.** The hard-coded isolated child command (`process.py:318–345`) fails to resolve `src` under the current interpreter. Both prior stderr and the new child result show the import error. The process never produced review findings. Whether this launcher behavior is itself correct under installed-command isolation is outside Feature 96 scope; no regression attribution is made.

**Action:** obtain explicit authorization for a working child environment or a supported launch configuration, then resume the three scoped read-only inspections with the remaining five dispatches. Do not silently install packages, remove isolation, edit launchers or repeat unchanged failures. Preserve the failed task's retry history.

### High — required independent conformance review remains outstanding

No delegated inspection completed. Therefore neither MATCH nor MISMATCH is justified. The matrix is a scope inventory, not proof. Existing untracked component/tests and tracked unstaged edits were identified by `git status --short`, but their implementation behavior was not independently assessed.

**Action:** complete ownership/history/lifecycle, navigation/visibility/stream snapshots, and app integration/packaging reviews against the recovered normative specification. Require exact implementation file/line references and distinguish proven defects from inference before replacing this blocker report with a completed assessment.

### Acceptance-blocking historical evidence gaps — not demonstrated current code defects

`dispatch12.md:32–50` records missing deliberately unequal-axis completion ordering and every-paint interruption proofs, plus manual evidence limitations. Its lines 85–88 record 292 mypy diagnostics in 58 files, claimed unchanged from baseline; lines 111–114 explicitly retain BLOCKED acceptance and independent review responsibility.

**Action:** preserve these as unresolved historical acceptance claims until independently dispositioned. A read-only source review can assess ownership and plausible logic defects, but cannot establish every terminal paint or manual behavior. No validation commands are authorized by this request. Do not treat missing execution evidence as proof of a source bug, and do not waive requirements on the strength of passing-count summaries.

## Historical evidence and missing work

`dispatch12.md:52–75` claims 8502 passing tests, 19 deselected and 482 warnings; lines 79–88 claim archive, formatting and static-check results. These were not rerun or independently validated here. The underlying logs were not comprehensively audited. No current pass/fail assertion follows from them.

Still missing: completed child reviews; current expectation-to-implementation line mapping; source-based defect assessment and regression attribution; full normative-spec/reference review; independent disposition of exact navigation/manual evidence and static baseline claims. The authoritative primary spec itself is no longer missing.

**Final status: report written; expectations-versus-code review NOT COMPLETE.** Continue only with an authorized working child-launch path and the preserved budget. No tests ran.
