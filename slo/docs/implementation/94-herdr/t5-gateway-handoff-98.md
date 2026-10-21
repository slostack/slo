# T5 gateway/selector 98 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 98, retries 0. Unlimited user turn/dispatch budgets; no agents dispatched. No app registry, canonical spec, global, live, other-worktree or git-history edits.

## Implemented delta

The session gateway now calls the existing `default_history_root()` off-loop and compares the actual resolved history-store root before parent metadata reads. This uses the canonical config-backed `_CFG_SLO_HOME` authority, not a newly invented environment-root resolver. A changed canonical default after activation now refuses the viewer despite the earlier activation cache. Three production lines added.

Extended the existing actual-session/registered-fake test with default-root drift, wrong metadata ID, metadata OSError, and REAL `VisualizerLauncher.launch_async` → actual config-backed session → owned T4 adapter/registered executable positive and skipped paths. The selector cases forbid sync platform launch. Existing fixture Faux factory and fake executable identity guard remain. Corrected test annotations, nullable narrowing, typed event payload, and concrete reporter import; no ignores.

## Finite gateway map and evidence boundaries

| Boundary | Current evidence / remaining obligation |
|---|---|
| Canonical requested ID | Existing invalid case refuses before parent I/O; valid saved different-parent case submits |
| Session close/history mutation/reporter revoked after metadata await | Existing cases retained and green |
| Native capture eligibility | Explicit custom-root, noninteractive and injected-session gateway cases remain required; prior capture tests are not claimed as gateway acceptance |
| Fresh default root | New `default_changed` regression: RED submitted vs skipped; GREEN actual-root comparison |
| Store/config/default mutation during later awaits | Still requires explicit barrier cases/reconciliation; the new comparison is at eligibility entry, not an atomic filesystem snapshot |
| Metadata missing/corrupt/wrong ID/OSError | Missing/corrupt retained; wrong-ID and OSError added; OSError text PRIVATE absent from outcome |
| Resolved parent workdir | Existing mismatch case retained; resolve failure and currentness across barrier not separately proved |
| PATH availability | Existing unavailable case retained; blocking-thread identity/cancellation barrier remains |
| Context | Existing valid/corrupt/absent and attached-event alternative retained; reader's own tests ran; blocking-reader cancellation/private-channel proof remains |
| Attached events | Valid attached parent and ordinary no-event refusal retained; wrong-session event/error and mixed-event decisions not explicitly reconciled here |
| Final authority/viewer identity | Reporter revocation retained; replacement identity branch and close during each awaited boundary still need direct proof |
| Actual selector composition | New positive and skipped cases use real session/T4/fake executable; no platform fallback allowed |
| Platform selector lifetime | Existing selector/launcher tests ran; complete branch reconciliation was not performed in this continuation |
| Transport ownership/no late commands | Existing T4 suites ran; gateway-specific cancelled blocking-reader/PATH barriers and retained ownership still outstanding |
| Exact wire/privacy | Existing split/rename/run order and exact parent run string retained; full exact argv and public-channel capture assertions remain |

This is a finite remaining list, not a claim that existing surrounding passes prove these missing composed cases. Family READY is withheld; parent app-registry work must not start from this receipt.

## Executed gates

CWD `/root/Code/slo-94-herdr-integration/slo`. Pytest prefix: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (approved fallback, mandatory DAO/projection cases included).

- `tests/agents/slo_agent/herdr/test_session_visualizer.py`: `t5-98-red.log/.exit`, exit 1, **1 failed, 74 passed**. Default changed still submitted before fix.
- After three-line production fix: `t5-98-surrounding.log/.exit`, exit 0, **1567 passed, 137 warnings**.
- Expanded composition/error cases: `t5-98-composed.log/.exit`, exit 0, **79 passed, 2 warnings**.
- Final surrounding partition before last reporter-import correction: `t5-98-final.log/.exit`, exit 0, **1571 passed, 137 warnings**.
- Post-import focused gate: `t5-98-focused-final.log/.exit`, exit 0, **79 passed, 2 warnings**. Do not label the prior surrounding run as post-import.

Surrounding suffix (both executions): `tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/agents/slo_agent/test_session.py tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_session_lifecycle.py`.

Static: `PYENV_VERSION=slo-harness poetry run mypy src/agents/slo_agent/sessions/service.py src/tui/visualizer_launcher.py tests/agents/slo_agent/herdr/test_session_visualizer.py`: final `t5-98-mypy-final2.log/.exit`, exit 1, **9 errors in 6 imported files**, zero diagnostics in the three requested files. Earlier mypy logs preserve the test errors corrected here. Remaining diagnostics name yaml stubs, transcript_projector, Faux model, chunk normalizer, Anthropic and Codex provider typing. This is NOT a green mypy gate or a fresh reproduction of historical full 298 errors/63 files; that baseline remains unwaived.

`black --check` on the same three files: exit 0. `git diff --check` and `dpkg -V coreutils`: silent exit 0 after final focused gate. No full make gate: family not ready.

## Read closure limitation

Read current checkpoint 97, current T5 status, full canonical D at the corrected path, frozen routing/scope plan, root research, KB Welcome/README/gotchas, shared engineering routing/testing/ownership, Python root/service/declarative guidance and coding rules/cadence. Project AGENTS/CLAUDE/docs RESEARCH were supplied in context. Complete requested fresh required-read closure (canonical C lifetime, accepted reviews, exact task attachments D01/D02/D03/D08, full remaining recipe/build guidance) was NOT completed; do not infer it from the frozen plan's historical reads. No independent review or full feature completion claimed.
