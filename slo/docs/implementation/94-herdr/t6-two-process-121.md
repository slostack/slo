# T6 two-process acceptance 121 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 121, retries 0; unlimited turns and dispatches. No agents launched. No production/shared-test/docs/spec/global/live edits. This report and same-prefix receipts are the only evidence writes.

## Implemented evidence

New exclusive files:
- `tests/integration/test_herdr_two_process_restore.py`
- `tests/integration/herdr_restore_process_bootstrap.py`
- `tests/integration/herdr_restore_process_entry.py`

Four cases: single/pool × available/missing-credential refusal. Each launches two independent interpreters sequentially. Publisher mounts the actual SloTUI/config-backed session with normal bootstrap provenance; actual Faux graph executes a standard `now` tool and two prompts. Actual reporter/restore store/transport advertises through a registered temp regular fake CLI. Parent takes the literal five-token argv from that external capture receipt and executes it via plain `slo` on its temp PATH. Second interpreter calls actual CLI main/parser/dispatch, actual store and session, and mounts the real app through run_test (only terminal driver replaced).

Current history includes the second prompt after advertisement. Ordered events remain exact, including after second teardown; two visible prompt blocks, one persisted tool result, zero second-process factory calls. Saved model/reasoning/workdir/workspace/plugin order and all pool scalars compare exactly. Changed actual preferences are irrelevant. Explicit plugin markers prove both reload; untrusted project plugin has a side-effect marker that remains absent. Missing synthetic credential before imports refuses actual lazy readiness, with both configured pool members retained. This is a bounded missing-credential admission proof, not every possible future catalog capability failure.

Child pre-import audit denies external mutations, network and unregistered subprocesses. Herdr environment starts stripped/disabled; transport guard is installed before activation. Temp executable/capture/shim identities are registered and rechecked, fake executable validates capture containment/inode itself, parent validates entry shim before execution. Terminal default spawn is forbidden. DEVNULL is redirected to a temp-owned regular sink, not a host write. Models are patched before construction; only synthetic OpenAI env credential exists. No live Herdr/provider/window executed.

**Qualification:** this is a regular source-entry shim executing current source, NOT installed isolated pipx launcher compatibility or native live Herdr restart. Application state is shared only through temp SLO_HOME; test harness files/observations live in its parent temp directory. Second child never reads published/advertised expectation receipts; it receives argv and reads actual store/history. No multiprocessing or inherited monkeypatch state.

## Actual iteration receipts

All prefixes below are `docs/implementation/94-herdr/t6-two-process-121-`; each run has `.log` and `.exit`. Commands use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <tests>` (adds 62 DAO/projection cases).

- bootstrap-red: 1 failed/62 passed, missing new helper (harness construction RED).
- bootstrap-green: 63 passed.
- entry-red: 1 failed/63 passed, missing new entry helper.
- publish: 1 failed/63 passed, test used wrong invoke keyword; fixed to async-generator `text` consumption.
- publish2: 1 failed/63 passed, test selected agent label `slo` instead of resume argv's `slo`; fixed extraction at `--resume`.
- restore: 64 passed, first complete single-policy two-process proof.
- policy-red: 2 failed/63 passed, missing new observations.
- policy: 1 failed/64 passed, fixture used unsupported gpt-5.4-mini; changed fixture to current supported gpt-5.5.
- policy-green / safety: 65 passed each.
- capability-red: 4 failed/63 passed, missing capability observation.
- capability-green: 2 failed/65 passed; test removed credential after config import, so cached synthetic config remained. Not a production bug. Moved missing-credential setup before imports.
- capability2: 67 passed.
- focused: 228 passed,2 warnings; family + `tests/cli/test_herdr_restore.py` + `tests/agents/slo_agent/herdr/test_restore*.py`.
- final-family: 67 passed,2 warnings; includes strengthened plugin markers, parent shim capability, final on-disk history comparison, private-path/credential absence in CLI capture.
- black: 3 files unchanged, exit 0.
- static-final: exit 1,9 dependency errors/6 files, none in 3 scoped files (before last marker/assertion additions). Full output retained; not waived/green.
- diff: exit 0.
- coreutils: silent exit 0.

No production RED found; no source repair claimed. Errors above are explicitly harness/setup errors or missing-observation test-first increments.

## Remaining before READY

- Safety audit review is incomplete: strengthen and test direct-fd/dir-fd filesystem mutation and alternate exec/spawn paths, and guarantee descendant cleanup under parent timeout. Current happy-path children exit normally and reporter teardown joins fake CLI; timeout kill of publisher is not a proved complete descendant cleanup boundary.
- Add independent explicit expected scalar/path assertions beyond capture-versus-restored equality (pool order is independently asserted, but full scalar oracle still relies on publisher capture).
- Strengthen capability case through a public user-visible admission path rather than direct `_ensure_agent_ready`; preserve no automatic resubmission.
- Complete required fresh-read audit: core routing/ownership/testing/Python/Faux/declarative/workflow, canonical C restore/security/sections8–10, D acceptance and tasks T6 samples were consulted; some combined long reads were truncated. Full actual AGENTS/CLAUDE/docs RESEARCH reread, remaining integration guidance and truncated skill/review ranges must be completed. Do not treat previous handoff read audits as this worker's fresh reads.
- Rerun surrounding restore/CLI integration and scoped static after final strengthening. Run coordinated full make only after parallel lanes settle; no fresh full-suite claim here. Supplied T5 8213-pass receipt is not post-T6 evidence.

No independent review/completion or complete T6 claim. Live supported-release restart remains separately unauthorized and pending.
