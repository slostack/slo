# T6 harness PATH 145 — READYOVERALLHARNESS

**READYOVERALLHARNESS for the bounded offline harness safety gate.** The final concrete prerequisite defect identified by map144 is closed. Recommend that the parent lift its harness HOLD only after verifying this receipt and current hashes against the combined evidence. **Parent state is unchanged; positive Herdr family and full make were NOT executed here.** This is author safety evidence, not independent implementation review, T6 acceptance, installed-launcher compatibility, live certification or feature completion.

Accounting: same unfinished turn 1; started 1, completed 0, historical partial 1, supplied dispatch 145, retries 0. User workflow-turn AND dispatch budgets unlimited; old numeric limits void. No agents dispatched.

## Scope and plan

Python 3.11.7 process adapter/safety tests only. Reuse existing supervisor, registered-file validator and source entry; no production semantics or new process manager. Read map144 and capture-final144 completely, preserve completed finite audit/read closure, reproduce the actual PATH prerequisite in a guarded record-only supervised child, add exact owned PATH admission, verify rejection and interpreter isolation, rerun all safety units after each increment, then static checks and aggregate disposition. Positive publication/restore stays with the parent.

Changed code: `tests/integration/herdr_restore_process_bootstrap.py`, `tests/integration/test_herdr_two_process_restore.py`, `tests/integration/test_herdr_restore_harness_safety.py`. `herdr_restore_process_entry.py` is unchanged and included in four-file static/hash checks. Existing unrelated work preserved. Documentation changes are this receipt, safety123 current section and path145 evidence files. No specifications, production, KB/global/live/other-worktree edits; no commit/push/PR/reset/clean/stash.

## Correction and proof

- `prepare_restore_process(root, helper)` extracts the actual parent preparation without executing the product helper. It creates the regular `slo`, captures its identity through existing `FakeHerdrSpawnGuard`, and returns the prepared owner plus explicit HOME/SLO_HOME/T6_ROOT/**PATH exactly equal to the owned root**. No ambient PATH or `/bin:/usr/bin` suffix is copied. Both positive request phases use this environment; the second owner retains the first owner's safety registration rather than recapturing a potentially replaced inode.
- `OwnedProcessRun.validate_launch` delegates environment admission to `ProcessSafety.validate_environment`. Only PATH is added to the previous five permitted names. PATH requires exact root spelling plus registered `root/slo`; registration and every admission revalidate regular single-link executable identity, permissions and containment through the existing guard. Empty, relative, multiple-directory, outside and unregistered paths fail. No PATH permission is added to subprocess audit: it still requires the exact separately admitted executable, not arbitrary commands found in that directory.
- `test_parent_path_reaches_real_plain_slo_probe` uses the same preparation with a record-only helper. Actual isolated supervisor/child installs filesystem and execution guards before importing the real reporter, calls real `HerdrReporter._plain_slo_available()` and real `shutil.which('slo')`, asserts discovered path equals the registered shim and PATH is exactly root. It neither activates reporter/transport nor constructs a provider. It asserts unqualified `slo` execution remains refused by the audit policy. No manufactured advertised.json is used by this proof.
- Its old-missing-PATH variant removes only PATH and executes the same real probe. The discovery assertion exits 1; outer test expects that nonzero result. Thus old behavior remains observably red under the common oracle, rather than relying solely on the first missing-helper ImportError. This does not execute any discovered host command.
- Nine refusal cases exercise outside/relative/empty/multiple/symlink/substituted/missing/nonexecutable/unregistered admission with Popen blocked. Wrong-name registration additionally refuses without granting PATH. All link/substitution targets are freshly created test-owned files; no system symlinks.
- Parent shim and generated capture fake now have the absolute current approved Python shebang with `-IB`. No `/usr/bin/env python`, shell or PATH-resolved interpreter dependency. Main requests remain `[absolute_python, '-I', '-B', absolute_shim, ...]`. Existing real generated-capture/Popen/run/asyncio tests rerun with the strengthened shebang. This is source-harness evidence, not proof of a real installed plain-slo restart.
- Parent recorder still verifies exact five-element advertised argv shape and unchanged restore tail/SLO_HOME, but remains explicitly synthetic request evidence. Actual positive emitted argv assertions are retained for parent execution, not relabeled proved here.

## Combined finite closure map

The complete application persistence/operation traversal remains [map144](t6-harness-map-144.md), sections “Entry and execution map”, “Initial hazards”, “Actual application persistence traversal”, “Primitive coverage” and “Read closure”. This continuation adds only PATH admission/discovery and interpreter-flag changes; no new writer family or unreviewed application journey.

| Initial122/subsequent safety gap | Closure evidence |
|---|---|
| Direct-child-only timeout, retained interruption, READY FD ownership and concurrent drain | [PROCESS136](t6-process-final-136.md), four-row disposition; actual descendant, early-leader, TERM/KILL, retained-resource and ECHILD tests rerun in all 223 |
| Integer FD mutations and ignored dir_fd | map144 initial-hazards and primitive tables; actual descriptor/stdio/open-dirfd refusal and owned-dirfd tests retained |
| Alternate/unregistered executable routes and replacement inode | [sensitivity140](t6-guard-sensitivity-140.md), actual Popen/run/asyncio matching/replaced cases plus installed exec/spawn refusals; no PATH execution broadening |
| Unsafe parent probe / unguarded positive runner | [parent141](t6-harness-final-audit-141.md), supervised contained sibling victim and exact parent requests; now shared preparation includes exact validated PATH |
| Capture check/open race | sensitivity140 common old/current preservation oracle with real generated writer and barriers |
| Opened special/multiply-linked file, pathname rename/replacement and FD-slot reuse | [142](t6-harness-safety-close-142.md), [143](t6-harness-edge-close-143.md), map144; retained tests rerun |
| Capture nonregular opened substitution, close-primary masking and registration/refusal inventory | [capture-final144](t6-capture-fault-final-144.md), all three rows READYCAPTUREGATE, 211 prior units retained |
| Used persistence writers / unsupported fallthrough / read tails | map144 complete finite traversal and read closure; no generic “remaining audit” reinstated |
| Registered shim absent from child PATH | This receipt: real supervised reporter/which proof, old-environment sensitivity, exact PATH and registration refusals; **closed** |

All identified initial122 **harness safety** gaps are closed within the mapped finite fixture contract. Product acceptance concerns (including public admission/scalar oracle concerns distinguished in map144), whole T6, independent review and live approval are not safety rows and remain separate. No claim of a malicious-Python sandbox, atomic check/use confinement, same-inode hostile rewriting protection, arbitrary API coverage, or bounded forced killing of escaped sessions. Map144's separate-session transport qualification remains: generated fake is finite, transport owns its own child, and new deliberately hung/escaped-session scenarios require their own cleanup proof.

## Actual checks and receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`. Interpreter explicitly `/root/.pyenv/versions/slo-harness/bin/python`, observed **Python 3.11.7**. No environment file sourced. Pytest environment:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
$P -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
```

Root collection/per-test fixtures strip inherited HERDR settings and retain disabled integration/terminal/fake-only spawn guards. Children use explicit environment; no real provider/Herdr/window. Signals are only the existing safety suite's created anchored groups/disposable wrappers.

| Receipt prefix (each .log/.exit) | Actual result |
|---|---|
| path145-red | Missing preparation API: 1 failed/211 deselected; exit 1; preliminary RED, not behavior proof |
| path145-red-probe | After preparation extraction, actual child fails `KeyError: PATH`: 1 failed/211 deselected; exit 1 |
| path145-green1 | 212 passed, 2 warnings, 66.44s; exit 0 |
| path145-green2 | 221 passed, 2 warnings, 66.54s; exit 0 |
| path145-red-isolation | Fake shebang missing -I: 1 failed/220 deselected; exit 1 |
| path145-green3 | 221 passed, 2 warnings, 66.48s; exit 0 |
| path145-red-shim | Parent shim lacks absolute isolated shebang: 1 failed/220 deselected; exit 1 |
| path145-final | 221 passed, 2 warnings, 66.57s; exit 0 |
| path145-mypy | Initial static attempt: one `_shim_guard` attribute redefinition error; exit 1, corrected with explicit class attribute annotation |
| **path145-verified** | **223 passed, 2 warnings, 68.26s; exit 0**, after final source formatting/type correction and old-PATH sensitivity addition |
| path145-black-final | Four files unchanged; exit 0 |
| path145-mypy-final | No issues in four source files; exit 0 |
| path145-coreutils-final | `dpkg -V coreutils`: empty output, exit 0 |

Static commands: `$P -B -m black --check <four files>` and `$P -B -m mypy --follow-imports=skip <four files>` using bootstrap, entry, parent test and safety test. Scoped mypy is not repository lint. Coreutils was silent immediately after every pytest invocation; final receipt persisted. `path145-files.sha256` binds four-file bytes. `git diff --check` receipt is path145-diff-final; these pre-existing untracked files are not representable by a normal HEAD diff, so changed source regions were inspected directly. Existing deprecation warnings only.

## Context and authorization boundaries

AGENTS/CLAUDE/docs RESEARCH supplied in full; root RESEARCH/routing read, scope-plan consulted (complete supplied prior read closure retained via map144). Selected committed engineering routing/testing/ownership, coding rules/cadence/shared declarative, Python root/declarative/named arguments/docstrings/Faux recipe and canonical workflow SKILL loaded. No dedicated Python-process skill exists in manifest; existing supervisor contract and shared adapter guidance apply. No new design/spec or independent review claimed. KB ROLE read first, Welcome/os README and relevant workloads/Slo README/gotchas consulted read-only. Some combined context reads truncated; not claimed as new complete ingestion; the user's completed map144 read-tail closure is preserved, not reopened. Canonical read-only H B1872–1918, C295–325 exact argv, tasks238–285 T6 and accepted finalization receipt consulted. Specification acceptance is not implementation acceptance.

**Recommendation: parent may verify READYOVERALLHARNESS and then decide whether to lift its safety HOLD. This worker did not lift it, execute the positive family, modify parent workflow state, or authorize live testing.** No arbitrary unit cap or budget cutoff applied.
