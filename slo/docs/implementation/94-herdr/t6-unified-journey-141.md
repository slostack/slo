# T6 unified mounted journey — 141

## Verdict: INCOMPLETE overall; six unified mounted cases pass

The missing same-app composition is implemented and green. This is not full T6 readiness, independent review, two-process restore, static-baseline approval or live acceptance. Required complete prerequisite/source ingestion was not finished in this session, so **READY unified mounted family is withheld** rather than inferred from green tests.

Accounting retained: unfinished turn 1, started 1/completed 0/historical partial 1, supplied dispatch 141, retries 0; unlimited turns and dispatches. No agents dispatched. No production, matrix, parity helper, shared-status, canonical specification, other-worktree or global configuration edits. No commit/push/PR/reset/clean/stash or live operation.

## Owned implementation and plan

Only code changes:

- `tests/integration/test_herdr_full_flow.py`: optional mounted continuation on the existing real prompt test and six new unified cases (single/retry/fallback × successful/uncertain second split).
- `tests/integration/herdr_unified_141.py`: uniquely named continuation/assertion helper.

Plan executed incrementally: preserve existing prompt/parity oracle → add same-mounted-app continuation → prove both public routes and configuration transitions → add uncertain second split and exact advertised argv → explicit safe surrounds → owned static/integrity gates. No production behavior change was necessary.

Each new case runs actual Pilot PromptInput → config-backed Faux factory → actual graph/tool execution → real session usage/history/reporter. The existing controlled pre-output failure exercises actual retry or actual ModelPool fallback. Each case then continues **without unmounting or constructing another app** through attached event relay and detached raw launch_workflow tool-result relay, rename, model switch and `/new`. The detached persisted parent has a distinct canonical identity/context; no workflow child process is started. Routes converge through the real gateway/T4 shared transport to the independently registered fake executable.

Single-model cases retain the actual CLI report barrier while the Faux prompt completes; retry/fallback cases retain the existing unstalled transport to avoid conflating the real 15-second retry wait with the CLI's bounded timeout. Final totals are exactly 8; one user prompt, one now result and one completed run remain in old history after replacement. Fresh successor totals are **None (unknown), not zero** and its history has no prompt/tool/completion. Old totals remain 8.

The continuation asserts exact split owner/no-focus, label and plain `slo visualize --session UUID --follow` argv for both distinct parents. A malformed second split consumes the detached parent's attempt; direct gateway retry plus public-event repetition produce no extra split/run. No OS fallback is called. No focus/get/close commands occur. Successful submission notices total two, or one when the second split is uncertain. This is queue-submission evidence, not pane paint.

At initial, renamed, model-switched and successor checkpoints, actual fake CLI captured resume argv must equal `slo --resume UUID --herdr-restore REFERENCE`. Persisted records equal the entire captured config and envelope; capture identity/generation matches the session. Every configured pool field/order is compared in JSON representation; the configured primary stays distinct from routed fallback. Effective reasoning, workdir, empty plugin order and absent workspace are checked. Previously observed revision bytes stay identical through later configuration saves, replacement and unmount. No restart/CLI restore execution is claimed.

## Finite acceptance map

| Contract | Evidence / boundary |
|---|---|
| B §9 enqueue/nonblocking; C §8 submission scope | Existing real prompt/tool barrier retained in unified single case; actual retry/fallback variants now continue to both viewers/configuration in the same mounted app |
| B §8/9 ordered telemetry; D §8 context/cooldown clears | Existing `test_actual_session_unknown_usage_explicitly_clears_before_patch` and `_assert_usage_clears`; rerun with whole owned file, not duplicated |
| C §8/9 exact supported capture/current history | Unified exact full private record/capture/generation and unchanged old history checks; two-process restore remains HOLD |
| C §9 ordered replacement | Pilot `/new`, release before successor claim, no old-ID command after successor claim, drained old reporter, old history preserved |
| D §8/9 both existing routes/correct parent | Six unified cases traverse both actual public event routes, real service/renderer/registry/gateway/transport |
| D §9 one-shot including uncertainty | Second split malformed in three variants; repeat direct gateway and public relay cannot create replacement split/run; no OS fallback |
| B privacy / C inactive parity | READY135 preserved; original oracle/helper untouched; full_flow rerun. No duplicate privacy oracle introduced |
| C lifetime 64 / G1/G2 / quarantine | READY140 ownership retained, matrix neither edited nor collected here |
| B/C/D full static, process, release/live gates | Pending separately; supplied global 281 errors/58 files remains UNWAIVED |

The three prompt policies are separate parameterized journeys, each containing both viewer paths and configuration/replacement. This is not one prompt that performs both single-model retry and pool fallback, nor a claim that all finite acceptance cases live in one giant scenario.

## Verification receipts

Directory: `docs/implementation/94-herdr/t6-unified-journey-141-receipts/`.
Cwd: `/root/Code/slo-94-herdr-integration/slo`. Verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. All pytest commands used `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`, the inspected explicit safe fallback; 62 foundation tests are included in each count. No dev env sourced. Commands had 1800-second allowance. Root HERDR stripping/disabled defaults, capability registration and real-terminal guard remain intact. Fake writes preserve registered executable/capture/barrier identities; new context writes verify test-root containment and no destination symlink. Coreutils verification was silent after stubbing runs.

| Receipt | Selection/result |
|---|---|
| initial | existing single-enabled prompt after continuation seam: 63 passed |
| unified | first three journeys: 3 failed/62 passed; wrong test assumption compared effective reasoning with optional configured request |
| unified2 | 3 failed/62 passed; fresh totals incorrectly assumed zero; immutable tuple versus mutable-list Python dump comparison |
| unified3 | corrected actual contracts: 65 passed |
| unified4 | six variants including uncertain second split/exact resume argv: 68 passed |
| final | whole full_flow + attached_composed + visualizer_launcher + workflow_renderer: **248 passed, 152 warnings, 193.84s, exit 0** |
| mypy | initial owned static check: one nullable config access diagnostic |
| mypy-final | explicit config assertion: success, two files, exit 0 |
| final-focus | post-final assertion six variants: **68 passed, 16 warnings, 42.28s, exit 0** |
| black | both owned files unchanged, exit 0 |
| diff | git diff --check, exit 0/silent |
| coreutils-final | dpkg -V coreutils, exit 0/silent |

Full final selection:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh \
 tests/integration/test_herdr_full_flow.py \
 tests/tui/test_herdr_attached_composed.py \
 tests/tui/test_visualizer_launcher.py \
 tests/tui/workflows/test_workflow_renderer.py
PYENV_VERSION=slo-harness poetry run black --check tests/integration/test_herdr_full_flow.py tests/integration/herdr_unified_141.py
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/integration/test_herdr_full_flow.py tests/integration/herdr_unified_141.py
```

Failures were test construction/static mistakes, not demonstrated source bugs. No source RED is being hidden; no production edit, skip, xfail or suppression was introduced. Counts overlap and must not be summed. Untracked files were read directly; ordinary git diff alone does not review them. Two-process HOLD honored: no full make, integration-directory collection or restore-process execution.

## Read closure and remaining work

Consulted supplied AGENTS/CLAUDE/docs RESEARCH; root RESEARCH and routing/scope-plan/assessment were retrieved. Read mounted122/close123, privacy135, matrix140 and attached107/detached109 evidence, current full_flow portions and fixture/guard/Makefile/build requirements. Read KB Welcome/slo README/gotchas. Read engineering routing/testing/ownership, coding rules/test loop, Python root/declarative/named arguments/docstrings, full Faux graph testing and Textual guidance. Canonical exact tasks3721–3816 and B/C/D sections8–10 were read directly. Inspected actual DAO/restore/viewer owners and registered fake fixture.

However, bulk retrievals of broader routing/context material truncated; copying skill text to a temporary file is **not** reading it. Full shared declarative/workflow guidance, canonical overview/T6 normative allocation/accepted-review closure and all affected session/app/reporter source paths were not completely consumed. Those remain explicit prerequisite work before READY. No earlier author's ingestion claim is adopted as this session's evidence.

No arbitrary workflow/dispatch cap caused stopping; no full-family approval is implied by these bounded tests. Remaining: complete named prerequisite/source closure and final review of the new helper; determine whether the requested wording requires retry and fallback sequentially in one instance rather than these separate complete parameterized stories. Full T6 still independently requires held two-process proof, full non-E2E/static gates, independent review and separately authorized live evidence.
