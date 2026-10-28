# T6 offline final author handoff — 150

## Verdict: REVISE — reproduced composed-test accounting failure

**Not READY OFFLINE. Entire feature INCOMPLETE. No Code-Test step completion or Review-gate advance.** The three 149 process acceptance cases are implemented, but fresh full and D09 gates reproduce an additional unresolved assertion failure. Static remains **281 errors / 58 files, UNWAIVED**. Live acceptance and independent full-scope Review/Completion remain unperformed.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 150, retries 0. Unlimited turns and dispatches; no agents dispatched and no parent workflow state changed. No commit/push/PR/reset/clean/stash, package/global/live/specification/other-worktree changes. No product changes. A temporary diagnostic test edit was restored exactly; final source/test hashes equal the pre-full snapshot.

## Fresh coordinated gates

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved Python 3.11.7. `make test-env` returned **fallback**. No environment file sourced. Explicit `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, PATH prefix and `PYENV_VERSION=slo-harness` make both direct and Poetry Python resolve to that environment. A preliminary PYENV_VERSION-only check resolved Poetry to the base 3.11.7 interpreter; this was corrected **before tests**. Safe exports and executable receipt helper are in [environment.sh](t6-offline-final-150-receipts/environment.sh). Root pre-import/per-test HERDR stripping, independent registered-fake transport guard and terminal guard remain unchanged. Bounded two-process authorization is the user's explicit 145/146/149 HOLD lift, not permission inferred from an old report.

All gate commands have exact `.command`, complete `.log`, and `.exit` artifacts in [receipts](t6-offline-final-150-receipts/). Bash allowance was 1800 seconds per gate; no runtime deadline was changed.

| Receipt | Actual result |
|---|---|
| full | `make test`: **1 failed, 8652 passed, 19 deselected, 779 warnings**, 1226.24s; make exit 2 |
| B26-test | Exact B26 pytest selection: **1452 passed**, 126 warnings; exit 0 |
| C31-test | Exact C31 pytest selection: **1459 passed**, 131 warnings; exit 0 |
| D09-test | Exact D09 pytest selection: **1 failed, 1668 passed**, 275 warnings; exit 1 |
| surrounding | Exact frozen routing surrounding selection: **472 passed**, 30 warnings; exit 0 |
| smoke | `make smoke`: **288 passed**, 2 warnings; exit 0 |
| lint | `make lint`: **281 errors in 58 files, checked 801**, make exit 2 |
| B26-black / C31-black / D09-black | Exact fences: **72 / 12 / 10 files unchanged**, exits 0 |
| all-black | All **122 changed/new Python files**, including evidence helpers: unchanged, exit 0 |
| diff | `git diff --check`: silent, exit 0 |
| coreutils-* | `/usr/bin/dpkg -V coreutils`: all retained logs empty, exits 0, after subprocess suites |

Overlapping `make test`, smoke and lint lines in B26/C31/D09 intentionally share the same unchanged-snapshot receipts. A shared failing receipt remains failing. Counts overlap and are not additive. Full includes guarded two-process, safety, 64-case and unified families; its sole reported failure is below. No live/E2E/provider/window claim is made from those tests.

## Exact observed failure and investigation

Node: `tests/integration/test_herdr_full_flow.py::test_pilot_configuration_and_typed_viewer_journey[success-True]`.

At line 1388:

```text
assert sum(step == "command_entry" for step, _ in viewer_steps) == len(transport_results)
AssertionError: assert 30 == 29
```

The full and exact D09 runs independently produce that same mismatch. Both have already passed the viewer argv/status/notice, replacement release ordering and privacy checks preceding this assertion. The observer records `command_entry` before awaiting `HerdrCliTransport.invoke`, and appends result/exit only after normal return. Transport explicitly preserves cancellation (`service.py::invoke` catches Exception, not CancelledError); cancellation is therefore a plausible missing terminal category, **not an established root cause**. Neither saved failure contains per-invocation cancellation evidence.

Isolation receipt: the exact node alone passed (1 passed, 4 warnings, 4.85s). This does not prove a repair or conclusively distinguish scheduling from cross-test state. Temporary instrumentation recorded `command_cancelled` and re-raised, retaining the original equality and adding the event list to assertion diagnostics. Whole full_flow then passed 144; exact D09 under that instrumentation passed 1669. The failing interleaving did not recur, so these diagnostic passes are **not final acceptance evidence** and cannot establish the hypothesis. Instrumentation was restored exactly; no weakened assertion, fabricated result, increased deadline, skip or production change remains.

**Next genuine code/test work:** deterministically expose the observer's outstanding invocation during replacement/unmount (capture invocation identity and terminal return/cancellation, with real transport cleanup retained). Establish whether a legitimate cancelled call lacks observer accounting, an owner remains undrained, or preceding test state changes behavior. If cancellation is demonstrated, account for it explicitly while retaining every returned-result privacy scan and asserting no outstanding invocation; do not simply change equality to `>=`. If ownership is defective, add the failing lifecycle regression before a minimal feature-only correction. Then run affected module, exact D09, surrounds and fresh full suite on the corrected frozen snapshot. No product defect or external blocker is asserted without that evidence.

## Freeze and baseline comparison

[files.txt](t6-offline-final-150-receipts/files.txt) inventories changed/untracked Python plus changed build/config inputs. [source-before.sha256](t6-offline-final-150-receipts/source-before.sha256) and [source-after.sha256](t6-offline-final-150-receipts/source-after.sha256) are byte-identical. They include all 122 Python files, including docs evidence helpers. Documentation is recorded separately; no source/test edit follows final hash verification. Diagnostic runs are explicitly distinguished above because they used temporary instrumentation.

[static-comparison.txt](t6-offline-final-150-receipts/static-comparison.txt) compares full diagnostic multisets, normalizing **line/column only**, retaining paths, full message, code and multiplicity. Initial baseline301/64 → current281/58: **0 added, 20 removed**. Current versus147: **0 added, 0 removed**. Both complete normalized multisets are retained. No ignore, exclusion, blanket waiver or installation was used. Follow the finite 142 partitions and 147 authorization boundary, not a new baseline replan.

## Canonical and prerequisite closure

Fresh verification of all **20 canonical hash entries** succeeds: [canonical.txt](t6-offline-final-150-receipts/canonical.txt). Every inventory fence digest and every exact allocated task attachment matches: **72 allocated, 10 excluded**, [samples.txt](t6-offline-final-150-receipts/samples.txt). The initial verification script incorrectly included the closing fence newline; correcting its extraction to the inventory's exact fence convention verified all 82. No canonical bytes were edited or executed.

The accepted [148 author assertion/read map](t6-read-close-148.md) is reused as explicitly authorized for unchanged B/C/D, all samples and T1–T5 continuations. It is not relabeled independent review. Freshly read: 149 report and full current process parent/entry; both148 receipts;135 privacy,140 matrix,141 unified,145 harness,146 positive; current t6-code-test and final-code-status; frozen routing/scope plan; root RESEARCH, supplied AGENTS/CLAUDE/maintained RESEARCH; actual Makefile/pyproject settings, complete root conftest/state isolation; KB Welcome, Slo README/gotchas, OS ROLE/README; overview, normative T6, exact B26/C31/D09/O01–03, C2110–2175 and accepted turn4 review; current README/INSTALL Herdr sections and121/147 static boundaries.

Fresh skills read include engineering routing/ownership/testing; coding rules/cadence/shared declarative; Python root/declarative/named arguments/docstrings/application services/Faux; full Typer/Textual; exact workflow SKILL and Code-Test-Review; debugging isolation. **149's requested complete prerequisite re-ingestion is not claimed complete:** Python domain recipe was freshly read only through560/1525; additional frozen routing companions were not all freshly loaded. Their unchanged148 closure is retained, but this receipt does not misrepresent partial fresh reads as complete fresh ingestion. This procedural limitation also prevents an unqualified final author handoff.

## R1–R26 final offline evidence map

The detailed actual-assertion table in [148](t6-read-close-148.md#actual-t6-assertion-map) remains the unchanged owner map. The following is its current disposition, not a new independent code review. `F`=test_herdr_full_flow.py, `U`=herdr_unified_141.py, `M`=test_herdr_lifetime_matrix.py, `P/E`=two_process_restore.py / herdr_restore_process_entry.py, all under tests/integration (P has test_ prefix).

| Requirements | Current owners and actual assertion evidence | Final disposition |
|---|---|---|
| R1 | EnvironmentGate/null; F stalled prompt/inactive/ordered parity | Present; full test gate not wholly green |
| R2 | README/INSTALL; U split/run argv | Offline submission only; pane acceptance pending |
| R3–R6 | session capture/publication; reporter save matching; frozen DAO; U record checkpoints; G1 same/change capture; P literal ordered pool/scalars and mutation | Accepted148 mapping retained; executable families included in fresh full |
| R7 | fixed projector; F publication-before-coalescing scans, credential blockers, both viewer paths | Present; viewer observer completeness assertion now REVISE |
| R8 | restore store/CLI; P/E exact old bytes/current history/no factory/no duplicate prompt; 149 capability/trust/public error | Three149 gaps implemented; source-entry, not installed/live restart |
| R9–R11 | reporter close/binding/acks; transport lock-held admission/join; M queued/admitted/save/thread; separate retained owners | Accepted148 map retained; not inferred from matrix alone |
| R12–R13 | reporter ticket families; G2 real shared viewer lock/A/B | Accepted lower-layer ledger, fresh chapter/full selections |
| R14 | session operation/attention authority; F real tools/retry/fallback; E blocked/error compositor | Fixed blocked state and safe displayed guidance present |
| R15 | scheduler narrow HERDR removal; child allowlist/headless | Accepted120/148; surrounding and full executed |
| R16–R17 | shared identity closure; CLI ordinary resume; bootstrap provenance | Accepted120/148; fresh chapter/surrounding coverage |
| R18 | viewer attempt ledger; U both paths and uncertain second split; F destination matrix | Present; observer failure not waived by successful submissions |
| R19 | OrchestratorContextReader; workflow service sole raw parser; renderer typed effects | Accepted148; loader/workflow surrounding executed |
| R20 | app captured lifetime/inbox/final registration/replacement; U/M plus separate all-owner races/quarantine | Accepted148 distinctions retained |
| R21 | restore bounds, sequence limits, projector limits, one-shot policy | Accepted lower-layer tests, fresh B/C chapters |
| R22 | conventions and all gates | **FAIL: full/D09 assertion; lint281/58; fresh read limitation** |
| R23–R24 | read-only canonical/separate editor/no live or external action | Preserved |
| R25 | accepted spec review only | Independent implementation Review/Completion still mandatory and not performed |
| R26 | separate editor redesign | Excluded, untouched |

149 actual closure: OAuth valid synthetic credential + current catalog supports_chatgpt_codex=false rejects mounted explicit submission for single/pool, leaves no factory/history mutation and preserves exact reference; publisher executes trusted project plugin, second process removes project trust and refuses that code while explicit ordered plugins still load; cropped error compositor and blocked fixed reason exclude synthetic credential/private HOME. Missing-credential cases remain distinct. No global ordinary-tool redactor is implied.

### Acceptance criteria

- B AC1: F stalled/inactive; AC2: M + retained cleanup; AC3: sequence restart/contender; AC4: explicit clear ordering + tickets; AC5: shared formatter/footer; AC6: privacy scans **with unresolved observer completeness failure**; AC7: fake protocol evidence only, live pending.
- C AC1/2: session lifecycle/original-result isolation and headless; AC3: exact P/E policy/history plus all149 current admission cases; AC4: U replacement + lower rollback/quarantine; AC5: final task gate and separate claim races; AC6: complete ordered parity/inactive spies. Offline assertions present, combined gate still RED.
- D AC1/2: U both routes/correct parents/one-shot uncertainty; AC3: M + real transport revocation/join; AC4: **not met** (full/D09 and static RED, live absent); AC5: **pending authorized pane/paint approval**.

All72 sample-to-owner allocation stays exactly148, now freshly hash-verified. B26/C31/D09 have actual commands/results above rather than read-only placeholders. O01/O02 match documented owners; O03 remains a proposed pane diagram, not visual evidence.

## Documentation and remaining requirements/permissions

README/INSTALL/AGENTS describe actual owners and retain target-only Herdr0.9.2+ language, same installed plain slo/SLO_HOME/default history, immutable policy/current history, no automatic prompt replay, private retention/quota, current trust, one-shot panes, claimed-item investigation and startup-only rollback. Root and maintained RESEARCH receive a current receipt pointer;121 remains historical. No live certification claim is added.

1. **No extra permission needed for the authorized feature-only diagnosis** above. Resolve the reproduced test accounting/ownership failure with deterministic evidence; finish the specifically partial fresh prerequisite reads, rerun affected/full and update this handoff. Do not claim READY from the instrumented pass.
2. **Static is mandatory:** resolve remaining finite281 diagnostics under the 142/147 plan, preserving behavior. Request narrowly scoped authorization only where demonstrated provider/unknown-tool/deadline semantics would change. No blanket baseline waiver.
3. **Separate dependency permission:** compatible explicitly pinned types-PyYAML dev dependency/lock update and installation into the approved existing slo-harness environment, without runtime upgrades/global/pipx installs, through machine-guardian confirmation and any required protected-path exception. No such operation performed.
4. **Separate live permission:** disposable named slo-herdr-smoke, only its server restart and only its created resource cleanup, temp SLO_HOME/disposable repo/installed plain slo/Faux. Verify exact supported version/wire, states/clear/TTL/wait, native restart versus graceful release, exact history/config/no resubmission, attached/detached placement/no focus theft/manual reuse/retention and actual viewer paint. Never touch active server or herdr-agents.scope.
5. **Independent full-scope Review and fresh Completion:** still mandatory after honest gate disposition; not performed by this author and not advanced here.
6. [Ordinary Slo credential finding132](security-finding-132.md) remains separately unresolved/out of Herdr scope; no waiver, no new global redactor requirement invented.

This is a concrete **REVISE**, not a capacity stop, not 100% completion and not external-block attribution for an unexplained test failure.
