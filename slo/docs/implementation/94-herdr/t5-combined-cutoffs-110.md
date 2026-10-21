# T5 combined cutoffs 110 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 110, retries 0. User turn/dispatch budgets unlimited; no agents launched. No production changes, commits, pushes, PRs, resets, cleaning, stashing, canonical/global/live/other-worktree edits. Existing changes preserved.

## Delivered bounded evidence

Owned new file: `tests/tui/test_herdr_combined_cutoffs.py`.

The new context manager composes the actual app scheduler/registry/cancellation join with the existing mounted real-inbox disposition tests. A registered pending worker requires the actual submission gate in its cancellation finalizer. Tests assert its termination, empty registry, and refusal of a late registration after shutdown. Existing assertions are reused rather than copied or weakened; the imported test module is not edited.

- Six refusal cases: three cutoffs (`claim_pending`, `workflow_advance_pending`, `before_chat_registration`) with healthy/throwing deferred-delivery notice sinks. Existing assertions verify actual claim bytes, durable workflow state, no ack/invoke, and fresh mounted restart retention followed by explicit user admission.
- Four already-registered cases: original/displaced store crossed with normal/operator active-stream abort. Existing assertions verify exact registered task, no shutdown-induced cancellation/abort, original captured ack, unchanged done bytes, one invoke, and actual durable abort policy.
- Faux factory, temporary history, suite HERDR/terminal guards remain active. Viewer worker is replaced with a barrier coroutine: this is registry ownership evidence, **not actual launch_async/gateway/CLI resource acceptance**.

No behavioral production RED occurred. Initial six cases passed; surrounding tests passed before adding the four registered cases. Production was not modified.

## Executed receipts

CWD: `/root/Code/slo-94-herdr-integration/slo`. All pytest commands used `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (includes 62 DAO/projection checks). Each prefix below has `.log` and `.exit`.

| Prefix | Arguments/result |
| --- | --- |
| `t5-110-viewer` | new file: 68 passed, 8 warnings, exit 0 |
| `t5-110-viewer-surround` | new file + inbox disposition + viewer registry: 95 passed, 21 warnings, exit 0 |
| `t5-110-registered` | same after registered cases: 99 passed, 25 warnings, exit 0 |
| `t5-110-surround` | `tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/tui/test_visualizer_launcher.py tests/tui/test_subagent_event_routing.py`: 666 passed, 85 warnings, 251.02s, exit 0 |
| `t5-110-format` / `t5-110-black` | scoped Black format/check: exit 0 |
| `t5-110-static` | `poetry run mypy --follow-imports=silent tests/tui/test_herdr_combined_cutoffs.py`: no issues in one file, exit 0; not full static green |
| `t5-110-diff` | `git diff --check`: silent, exit 0 |
| `t5-110-coreutils` | `dpkg -V coreutils`: silent, exit 0 |

Full make was not rerun. Historical 295 errors / 60 files remains unwaived and was not independently reverified here.

## Precise remaining closure

1. Add a genuine quarantined predecessor to the same mounted cutoff tests. Current helper uses the previous no-retired-owner fixture; it explicitly cannot satisfy this requested combined family.
2. Prove persistent predecessor drain cannot starve current cleanup, teardown remains pending until the owned barrier releases, and cleanup attempts survive errors. Current tests inherit selected-owner healthy cleanup spies but not combined owner-error evidence.
3. Reuse/extend strong-reference GC, single predecessor and repeated `/new` sticky suppression evidence within the combined fixture.
4. Compose the actual registered fake CLI child and real lease for resource acceptance; current worker substitution cannot prove that contract or suppression of late typed launch notices.
5. Finish requested actual-file prerequisite reads: actual AGENTS/CLAUDE/docs RESEARCH, routing/scope plan, exact canonical C/D/T5 samples and accepted reviews were not freshly read completely. Root RESEARCH and four requested handoffs were read; shared routing/testing/ownership/coding/cadence/Python/Faux/declarative were consulted, but a combined skill read truncated and Textual reading was partial. KB Welcome/gotchas read; KB repo index and workflow skill closure remain outstanding. Do not count supplied context or handoff summaries as fresh complete reads.
6. Run required complete surrounding/static/full integration gates after closure. No independent review or completion acceptance claimed.

**Verdict: INCOMPLETE.** Ten new occupied-registry compositions pass, but occupied retired-owner and actual child resource evidence are missing. T6's 4×8×2 matrix was not run and no 64-case completion is claimed.
