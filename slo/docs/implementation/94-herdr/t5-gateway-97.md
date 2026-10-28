# T5 gateway 97 — implemented, acceptance INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 97, retries 0. User unlimited turn/dispatch limits retained; no agents dispatched. No commit/push/PR/spec/global/live edits.

## Scope and routing

Python session-owned eligibility gateway; existing T4 transport/reader and 94 async selector retained. Shared engineering routing/testing/ownership, coding rules/cadence, Python conventions/declarative/service guidance and workflow accounting consulted. Canonical D was read at the corrected `herdr/94.c.1-herdr-workflow-visualizer-and-acceptance.md` path, including eligibility/admission 7.4/7.5 and app/session contract 7.1–7.3; tasks D01/D02/D03/D08 reconciled. No canonical file is missing. Bash works from `/root/Code/slo-94-herdr-integration/slo`; there is no reproduced ENOENT runtime blocker.

## Changes

`src/agents/slo_agent/sessions/service.py` now exposes `open_workflow_visualizer(parent_session_id=...)`. It rejects noncanonical requested parents before I/O, checks existing interactive/restorable capture and live reporter authority, reads exact-parent metadata/workdir, checks plain `slo` availability off-loop, consumes existing context reader or exact-parent spawned-event evidence, and rechecks authority after awaits. It delegates to the same owned T4 adapter; no TUI imports, history creation, private-context diagnostics, duplicate context parser, or OS fallback.

`tests/agents/slo_agent/herdr/test_session_visualizer.py` uses real config-backed sessions with Faux factory, real contained history/context, registered fake Herdr executable and existing transport. Positive context and attached-event cases submit split/rename/run for a parent distinct from the owner. Refusal matrix: invalid ID, close, missing parent, corrupt context, corrupt metadata, ordinary parent, different workdir, unavailable PATH, mutated history eligibility, and reporter revocation at an awaited metadata barrier. Refusals assert no split/run. Fake command capture normalizes `--json`; reporter commands are excluded from viewer command assertions rather than mistaken for viewer effects.

## Commands and evidence

All pytest commands use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` from this checkout (approved 3.11.7 fallback; no environment creation).

- `tests/agents/slo_agent/herdr/test_session_visualizer.py`: `t5-97-red.log`, exit 1, **1 failed / 62 passed**, missing public method AttributeError.
- Added gateway; `...test_session_visualizer.py ...test_session_publication.py`: `t5-97-green.log`, exit 1, 1 failed/84 passed: test incorrectly included reporter pane commands. `t5-97-green2.log`, exit 1: newly strengthened containment assertion exposed the cached default-root constant despite env override. Test now binds `_CFG_SLO_HOME` to its own tmp_path; no real state modification.
- Same command: `t5-97-green3.log`, exit 0, **85 passed**.
- Initial refusal matrix plus Herdr/context-reader/selector/launcher/workflows: `t5-97-surrounding.log`, exit 0, **1433 passed**.
- Added metadata/attached/revocation cases; target: `t5-97-branches.log`, exit 0, **74 passed** (includes mandatory DAO/projection tests).
- Final after Black: `tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/agents/slo_agent/test_session.py tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_session_lifecycle.py`: `t5-97-final.log` and `.exit`, **1566 passed, 137 warnings**, exit 0, 129.85s.
- `PYENV_VERSION=slo-harness poetry run black src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_visualizer.py`: exit 0.
- `git diff --check` and `dpkg -V coreutils`: silent exit 0 after final suite.

## Remaining acceptance (not a runtime blocker)

Do not claim full gateway-family READY yet: coverage still needs explicit custom-root/noninteractive/injected-session refusals, metadata wrong-ID and read OS errors, off-loop/thread proof, cancellation/privacy capture, selector-to-real-session positive composition and complete exact-command assertions. Default-root eligibility currently relies on the existing activation capture rather than a fresh default-root resolution per viewer request; reconcile that against requested actual-root semantics. New test helper signature has an unannotated return; static own-file checking was not run. Complete requested skill/instruction read closure was not achieved (capturing skills to a scratch file does not count as reading). No full non-E2E gate or mypy rerun; historical 298 errors/63 files remains unwaived.

App registry/caller migration, inbox audit, T6 and independent review remain future scope. This is real test-first implementation progress, not feature completion or a claim of live Herdr viewer paint.
