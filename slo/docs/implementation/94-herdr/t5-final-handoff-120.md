# Entire T5 technical author handoff 120 — READY

**READY: entire T5 technical author scope.** This closes exactly the two finite
items in [119](t5-full-handoff-119.md); it is not independent Review, Completion,
T6, live compatibility or release approval. Global static failures remain UNWAIVED.
Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied
parent dispatch 120, retries 0; unlimited turns AND dispatches. No agents launched.

## Scope and cadence

Only product edits in this continuation are the three requested docstrings in
`src/tui/app.py` and `src/tui/visualizer_launcher.py`. Tests added in
`tests/tui/test_herdr_platform_commit.py` and `tests/tui/test_visualizer_launcher.py`.
No behavior change, new runtime owner, parser, thread slot or lifecycle flag.
No canonical/global/KB/live/other-worktree edits, commits or external delivery.

Initial real thread proof plus launcher surroundings: **84 passed**, exit 0.
Mounted replacement/unmount composition plus surrounding viewer tests: **91
passed**, exit 0. These are missing-evidence increments that passed immediately,
not invented RED-to-GREEN production repairs. Final error-path test first failed
with **2 failed,111 passed** because its test file lacked the `patch` import.
Adding that import corrected the test-only defect: **113 passed**, exit 0.
No production defect was discovered or hidden. These counts include the helper's
DAO/projection foundations and overlap; do not sum them.

## Exact remaining proofs, now closed

| Requirement | Executable evidence | Result |
|---|---|---|
| D7.5 discovery blocked after admission | `test_platform_launch_join[discovery_blocked]` runs real `launch` and retained join, blocks discovery with threading Events, changes auto policy after admission, cancels waiter three times | No spawn before release; captured parent spawns exactly once afterward; cancellation escapes only after completion |
| D7.5 spawn already committed | Same test `[spawn_blocked]`, injected actual callable boundary records submission then blocks | Exactly one submission, repeated cancellation cannot abandon it; finished before CancelledError |
| D7.5 C captured-lifetime composition | `test_platform_commit_joins_app_lifetime[replacement/unmount × discovery_blocked/spawn_blocked]` | Real sync launch, shell/argv construction, Linux discovery continuation, registry and lifetime owners; teardown cannot complete while blocked; old identity stays selected until release |
| Rejected registration and duplicate parent | Same mounted composition attempts duplicate before teardown and rejected parent after actual drain begins | Same registered task; rejected parent never registered/spawned; one captured-parent argv |
| No late notice | Same composition spies renderer while real replacement/unmount drains | Zero outcome notices after cutoff, empty registry, correct final selected identity |
| Discovery/spawn ordinary errors | `test_real_platform_launch_error_outcome[discovery/spawn]` in launcher suite | Real launch maps error through retained gateway to failed; zero/one spawn-boundary invocation respectively |
| Root terminal safety | Every new test checks existing `_default_spawn.__test_stub__`; success spies delegate only to that captured root stub | No Popen, terminal, Herdr or provider execution; existing root guard unchanged |
| Three contract docstrings | `_prepare_session_delivery`, `_publish_delivery_timers`, `VisualizerLauncher` | Actual binding/timers parameters; sync bool submission evidence and async destination/owned-thread contract; no pure-helper claim |

The mounted proof blocks `_resolve_linux_terminal`, not the whole launch. The
innermost `_default_spawn` callable is injected with a test spy retaining the root
guard; it does not replace `launch`, `_launch_platform_joined`, or app registry.
Standalone proof additionally demonstrates policy is checked before discovery:
turning auto-launch off after admission does not retroactively revoke committed
work. This is exactly D's allowed late user-owned window semantics, not a promise
that cancelling a thread waiter prevents spawn. Events have bounded waits and
finally releases/joins. Cancellation checkpoint uses a queued event, no arbitrary
sleep. Existing before-entry/captured-session and late-result registry tests remain
applicable, not replaced by the new thread proofs.

## Whole finite T5 reconciliation

The complete requirement → owner → test table in 119 (section “Whole finite
requirements → owners → executable evidence”) is incorporated without dropping
any row. All rows remain closed, with its two exceptions superseded above:

- C7.9 capture inputs/provenance/immutable pool and generation/publication faults:
  session capture, publication, compositions, isolation and mutation suites retained.
- C7.9 candidate preparation/disposal, irreversible adoption, captured lease/timers,
  late auth, all four inbox dispositions and final local/queued/machine admission:
  lifecycle, lifetime, initialization, replacement, inbox and registration suites retained.
- C7.10 operation/attention/usage, actual tool/retry/recovery/abort/cancel and final
  snapshot: attention composed suites and usage regressions retained.
- C7.11–13 activation/close races, retained local resources versus remote uncertainty,
  final drain/GC, initializer rollback and join outside submission gate: lifetime,
  final-lifetime, activation and app-shutdown suites retained.
- C7.14 F1–F4 all-owner cutoffs/quarantine/gate ordering/independent cleanup and
  throwing notices: combined118 evidence retained; canonical UUID/slug identity
  prerequisite remains closed. No new 64-case T6 demand imposed here.
- D persisted parent and awaited revocation gateway; attached/detached actual ingress;
  typed service/renderer consolidation; duplicate/multiple worker/identity cleanup;
  five outcomes, single destination, manual reuse/no fallback: 100/109/111/118
  evidence retained. D platform continuation is now proved above, not inferred
  from their whole-launch stubs.
- C7.2 adopted headless lifetime, original result/stdout/terminal failure and scheduler
  exact case-insensitive `HERDR_` filtering: retained62/64/111 evidence. No widening
  of the prefix or changes to child/detached/relaunch exclusions.

119's runtime/consolidation trace remains unchanged: session owns capture/reporting;
app owns captured registration and retained replacement/shutdown; one typed service
parser and one outcome renderer; launcher selects one destination; platform worker
owns one local joined task. No duplicate accounting, parser or process owner added.
The finite audit110 findings remain corrected by111 and combined118; none is
reopened or silently waived. Final full gate covers the current combined snapshot.

## Verification receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`
Python 3.11.7/Poetry fallback, no environment install. Root fixtures strip inherited
Herdr state, disable it and enforce registered fake capabilities; Faux boundaries
and terminal guard remain. The new mounted test explicitly supplies Faux factory.

Every log below has same-stem `.exit`; all are under this directory.

| Stem `t5-120-` | Command / result |
|---|---|
| platform-initial | safe `t1-dao-check.sh` + new platform file + launcher suite: 84 passed,2 warnings; 0 |
| composed-initial | helper + platform file + viewer replacement + Herdr visualizer: 91 passed,2 warnings; 0 |
| focused | helper + platform/launcher/Herdr visualizer/viewer replacement: test import error,2 failed/111 passed; 1 |
| focused-green | same command after test import repair:113 passed,2 warnings; 0 |
| task | helper + exact T5 tasks.md line234 list:472 passed,32 warnings; 0 |
| surrounding | helper + exact routing.md additional surrounding list:534 passed,31 warnings; 0 |
| full | `PYENV_VERSION=slo-harness make test`:8213 passed,19 deselected,626 warnings,756.75s; 0 |
| smoke | `PYENV_VERSION=slo-harness make smoke`:288 passed,2 warnings; 0 |
| lint | `PYENV_VERSION=slo-harness make lint`:295 errors/60 files,793 checked; 2 |
| lint-comparison | `diff -u` of sorted complete ` error:` lines from118 and120: silent; 0 |
| black | `PYENV_VERSION=slo-harness poetry run black --check $(cat .../t5-120-python-files.txt)`:142 unchanged; 0 |
| coreutils | `dpkg -V coreutils`:silent; 0 |
| diff | `git diff --check`:see final receipt; no whitespace errors |

The 142-file changed-Python inventory adds only the new platform test and the
previously unchanged launcher test to118's140-file inventory. Static comparison
is exact (no diagnostic normalization/ignores); docstring replacements preserve
source line counts. Baseline lint is not green or waived. Full/smoke are fresh
post-code-edit receipts, not reused118 results. Warnings and normal19 deselections
are explicit. Source/test review checked actual barriers, captured argv, retained
join, cleanup and all three docstrings; no independent review claimed.

## Authority and next boundary

119's cumulative full C/D/T5 attachments/accepted-review and frozen skill read
closure is retained, not relabeled as a fresh independent review. Current work
inspected actual launcher/app registry/docstrings, replacement tests, root guards,
Makefile/task commands, frozen routing/scope and KB Welcome/gotchas, plus scoped
engineering/Python/Textual/Faux/declarative/workflow guidance. Source architecture
is unchanged; no new design ceremony or KB write was necessary/authorized.

**T6 may be considered next, but was not started here.** Full64 cutoff composition,
two-OS-process restore, full journey/privacy acceptance, runtime documentation and
separately authorized live version/restart/pane-paint remain T6. Independent full
feature Review and Completion remain future gates. Technical T5 READY does not
convert unwaived global static failures into approval or authorize delivery.
