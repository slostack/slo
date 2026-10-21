# T5 gateway lifetime 99 — READY for the finite tested lifetime family

Not full T5, feature, independent-review or release acceptance. Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 99, retries 0. User turn and dispatch limits unlimited; no agents dispatched.

## Owned change

Only `src/agents/slo_agent/sessions/service.py` and NEW `tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py` changed by this lane, plus this report/99 receipts. Existing parallel `test_session_visualizer.py`, launcher, canonical specs, shared status, global settings and other worktrees were not edited. No commits/push/PR/reset/clean/stash or live Herdr/provider/window actions.

Gateway now retains one eligibility task locally and joins it using existing `HerdrTaskJoin.wait`. This includes history-store internal threads as well as direct context/PATH offloads. Repeated cancellation retrieves terminal work/errors before propagating CancelledError, and never enters T4 submission. Ordinary private eligibility exceptions return fixed skipped, without diagnostics. After context/event evidence completes, canonical `default_history_root()` is reread off-loop; a changed default refuses admission. Existing final memory-only capture/close/authority checks and viewer object identity check remain the admission boundary. Production change is below 50 lines; no generic manager, new thread pool or per-parent registry.

D 7.5 explicitly requires off-loop reader use; D A2/D08 explicitly prescribes joining committed **platform** work. It does not literally prescribe a separate Herdr reader-thread registry. This change applies the shared resource-ownership requirement using the already awaited gateway task: app launch-worker cancellation cannot abandon eligibility threads. Direct session close revokes pane admission but is not a new owner of callers' read-only gateway tasks. The actual app contract drains launch workers before reporter teardown. An indefinitely stuck filesystem can therefore keep a cancelled gateway pending; no finite OS-thread kill guarantee is claimed. No additional thread is started to wait on a barrier.

## Test-first evidence

Real RED `t5-99-red2.log/.exit`: **6 failed, 74 passed**, exit 1. Four repeated-cancellation/error cases proved the gateway finished before the blocked thread; two changed-default cases incorrectly submitted. Initial `red.log` also records an assertion mistake: filtering every pane command included legitimate reporter release-agent commands. Corrected the filter to split/rename/run before accepting RED; assertions were not weakened for viewer effects.

After the small production fix: `green.log/.exit` **97 passed**, exit 0 (new 18-case family plus existing gateway and mandatory DAO/projection tests). Expanded matrix: `matrix.log/.exit` **110 passed**, exit 0.

## Finite lifetime map

All four actual boundaries have the same 12 cases (48 executions):

| Boundary | Real operation retained behind deterministic barrier |
|---|---|
| metadata | Exact requested parent's `session.json` Path.read_text through actual tree/flat store |
| attached events | Exact parent's `events.jsonl` Path.read_text, valid persisted sub_agent_spawned, no context |
| context | Actual OrchestratorContextReader.load reading private temp JSON |
| PATH | Actual shutil.which discovering the temp-owned regular slo executable |

Cases at **each** boundary: repeated cancel; repeated cancel followed by private OSError; session close; reporter authority revocation; changed canonical default; changed config history root; replaced actual store/root; changed configured workdir; replaced viewer identity; unchanged success; private OSError; private unexpected RuntimeError.

Each barrier asserts worker thread differs from the event-loop thread *before blocking*. Loop-side entered/checkpoint events establish progress without sleeps. Release is a threading.Event; timeouts only prevent test hangs. Cancelled caller remains pending before release and completes only after finished; success uses real session/T4/shared transport/registered fake executable. Refusals and cancellation assert zero split/rename/run after final joins; success asserts exactly split→rename→run. Outcomes, stdout/stderr/log capture and command records exclude PRIVATE. Cleanup releases barriers, retrieves gateway results, closes session and any replaced original adapter. Fixture writes resolve inside tmp_path; fake executable identity is validated by the registered capability. Existing terminal and disabled-by-default guards remain.

This family does not redefine filesystem reads as an atomic snapshot against concurrent external writers, prove arbitrary symlink swaps, or claim full app scheduling/replacement acceptance. Existing parallel lane owns remaining eligibility/selector branch reconciliation. Canonical default comparison is after evidence awaits; final session config/path-source checks are synchronous. T4 continues to own queued command authority under its transport lock.

## Gates and commands

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved prefix:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
The script includes mandatory DAO/projection tests, safe Faux/offline environment, disabled Herdr default, and preserved terminal guard.

- `t5-99-surrounding.log/.exit`: **1632 passed, 137 warnings**, exit 0. Suffix: `tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/agents/slo_agent/test_session.py tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_session_lifecycle.py`.
- After adding cancellation docstring and public stdout/stderr/log privacy assertions: `t5-99-final.log/.exit`: **110 passed, 2 warnings**, exit 0; suffix `tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py`. Surrounding run predates only those final doc/test assertions.
- `PYENV_VERSION=slo-harness poetry run mypy src/agents/slo_agent/sessions/service.py src/tui/visualizer_launcher.py tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py`: `t5-99-mypy.log/.exit`, exit 1, **9 errors in 6 imported files**, zero requested-file diagnostics. Imports: yaml stubs, transcript_projector, Faux, chunk normalizer, Anthropic/Codex typing. This is not green mypy or a fresh full baseline reproduction; historical 298 errors/63 files remains unwaived.
- Same three files `black --check`: `t5-99-black.log/.exit`, exit 0.
- `git diff --check` and `dpkg -V coreutils`: corresponding 99 logs silent, exit 0 after final test.
- No full make integration gate here; user assigned it later. No independent review claimed.

## Context / read boundary

Consulted supplied project AGENTS/CLAUDE/docs RESEARCH, actual root RESEARCH, routing and scope-plan, gateway handoff 98, current gateway/history/context/T4 and platform join code; canonical D in full including 7.3/7.5/A2 and exact T5 D01/D02/D03/D08 attachments; C capture and activation/close contracts and T5 lifecycle attachments; accepted independent turn-4 review. KB Welcome, actual slo README index and gotchas consulted read-only. Shared engineering routing/testing/ownership, coding rules/cadence, Python root/declarative/Faux and workflow accounting consulted. Broad combined guidance/task reads were truncated; this is not a claim of complete fresh rereading of every full frozen routing recipe or all of C. No shared KB edits authorized; durable finding is recorded here: cancelling a to_thread waiter is not joining its thread, including threads hidden behind async history-store methods.

READY is restricted to the explicit 48-case lifetime/mutation/error family above. Full required-read closure, parallel eligibility family, app registry integration, fresh full make/static gates and independent acceptance remain outside this verdict.
