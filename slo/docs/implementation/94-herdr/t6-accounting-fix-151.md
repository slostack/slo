# T6 observer accounting correction — 151

## Verdict

**READY OFFLINE for the bounded observer correction. Overall T6 remains REVISE:** mandatory lint is still **281 errors / 58 files, UNWAIVED**, and independent implementation review/completion and live acceptance remain outstanding. This is author verification, not independent review. No production code changed.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 151, retries 0. User turn/dispatch budgets unlimited; no agents dispatched. No commits, push, PR, reset, clean, stash, global/package/live/specification or other-worktree changes.

## Causal diagnosis

150's full and D09 logs report `30 command_entry / 29 returned results`. The observer appended entry before awaiting `HerdrCliTransport.invoke`, but appended exit/result only after normal return. Its equality incorrectly required a returned DAO for every invocation.

The canonical B transport contract explicitly says caller cancellation **raises instead of returning a cancelled result**, while admitted owner completion still receives safe terminal accounting. Actual `service.py` implements this: `invoke` catches ordinary Exception, not CancelledError; `_execute_admitted` joins `_finish_admitted` in finally; `_finish_admitted` drains/reaps, completes admission, clears resource slots, then cancellation unwinds. Reporter `_close_once` cancels and joins its worker before shutdown release. An entry is therefore not a promise of a returned DAO.

### Deterministic RED

The existing mounted journey still runs the Faux tool, configuration changes, both typed viewer routes, replacement and shutdown. After viewer completion, a test barrier holds the next real report-metadata collection after real admission and subprocess creation. The actual two-second refresh supplies the report. Pilot `/new` invokes production replacement, which cancels the reporter worker. Neither the observer nor the test directly cancels that invocation.

`causal-red.log`: **1 failed**, original equality **30 == 28**. Before that equality, every invocation passed the new terminal checks: one terminal, joined owning task, admitted completion exactly once, cleared active/spawn/cleanup slots, and any captured child has a non-None return code. At least one admitted cancellation was required. This is a causal counterexample to the original oracle with actual cleanup retained, not an isolation pass interpreted as a fix. The historical uninstrumented 30/29 execution cannot be retroactively reconstructed, but its failing invariant is decisively disproved.

An initial barrier experiment used the wrong operation name (`set-meta`) and timed out; `red.log` retains that failed setup. It is not the causal RED. The first correct barrier held reports until replacement and could hold a successor report too; final barrier is one-shot (`report_entered`) and holds only the first report. This narrows scheduling control, not accounting: **all** subsequent entries remain observed and checked.

### GREEN correction

Changed only:

- `tests/integration/test_herdr_full_flow.py`: structured observation per invocation, try/except/finally terminal capture, deterministic report/replacement barrier, exact terminal/returned-result cardinality and privacy scanning.
- `tests/integration/herdr_transport_observer.py`: test-only typed record and admission delegate; real owner decisions/callbacks and real transport execution remain intact.

Every entry must terminate exactly once. Returned observations must equal the actual returned DAO count; entry and finally-exit counts must each equal the complete observation list. No last-command exception, dropped cancellation, `<=` comparison or fabricated DAO. Unexpected escaping errors are recorded as fixed `error`, re-raised and rejected by the final assertion. Cancelled observations pass only with drain and callback evidence; queued nonadmitted invocations require zero callbacks and own no child. Owning tasks must be done after app shutdown. Existing viewer ledger/argv/notices/release ordering and all returned-result privacy scans remain. Added cancellation metadata contains only task identity integer, operation, fixed status, admission/completion counts/status and drain boolean; no exception text, argv or private output. It joins the existing synthetic-secret/private-path scan.

The barrier controls collection after spawning; it does not claim a live Herdr server or force a particular OS child exit latency. Existing transport cancellation/reap tests in D09 retain that lower-level coverage.

## Verification

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved `slo-harness` Python 3.11.7, explicit VIRTUAL_ENV/PATH/PYENV_VERSION and safe tracked fallback exports from 150's environment helper. Root HERDR stripping, fake capability identity/containment guard and terminal guard unchanged. No development environment or real provider/Herdr/window used. User-authorized bounded two-process tests run within the full suite. Each Bash gate allowed 1800 seconds.

Receipts: [t6-accounting-fix-151-receipts](t6-accounting-fix-151-receipts/), each gate has `.command`, complete `.log`, `.exit`.

| Gate | Actual result |
|---|---|
| causal-red | Original count equality fails 30/28 after cleanup assertions; exit 1 |
| focused-green | Full full_flow module: 144 passed, 152 warnings; exit 0 |
| D09 | Exact chapter selection: 1669 passed, 275 warnings; exit 0 |
| full | `make test`: 8653 passed, 19 deselected, 777 warnings in 1236.74s; exit 0 |
| surrounding-corrected | Exact frozen surrounding selection: 472 passed, 30 warnings; exit 0 |
| smoke | `make smoke`: 288 passed, 2 warnings; exit 0 |
| lint | `make lint`: 281 errors / 58 files, 802 checked; exit 2, UNWAIVED |
| all-black | All 123 changed/new Python files unchanged; exit 0 |
| diff | `git diff --check`: silent; exit 0 |
| coreutils-* | `/usr/bin/dpkg -V coreutils`: silent, exit 0 after each executed suite |

The first surrounding command reconstructed an old display-only command string without preserving quotes around `not e2e`: collection failed with `file or directory not found: e2e`, exit 4. Retained as `surrounding`; corrected direct argv run is `surrounding-corrected`. No failed execution is relabeled green.

Static comparison normalizes line/column only, preserving full paths, messages, codes and multiplicity. Both multisets sorted in the same C locale: **zero added, zero removed** against150 (`static-comparison.txt` empty). An initial diff used inconsistent locale sorting and differed only in order; final normalized artifacts correct that comparison. No ignores, waivers, installs or baseline changes.

`files.txt` extends150's source/test/build/config manifest with the one new helper. `source-before.sha256` (before full) and `source-after.sha256` are identical. No source/test change after the frozen full gate. Documentation updated separately after verification. Full includes the unchanged B/C, two-process and other composed families; no additive count claim for overlapping selections.

## Scope, prerequisites and limitations

Consulted supplied project instructions/maintained RESEARCH, actual root RESEARCH, frozen routing/scope-plan, actual transport/reporter/observer, 150 exact failure logs and diagnostic receipt, canonical B completion/cancellation and C lifetime sections plus T6 sample attachments. Loaded engineering routing/ownership/testing, coding rules/cadence/shared declarative, Python root/declarative/named arguments/docstrings, Textual/Faux and workflow counting guidance. KB entry/gotchas consulted. This bounded correction does **not** claim a fresh complete re-ingestion of every large prerequisite in the frozen feature routing record; 148's unchanged author read closure and150's disclosed partial refresh remain historical. No independent review is implied.

Remaining genuine gates: finite unwaived static281/58 remediation under142/147 authorization; complete prerequisite refresh if required for full-scope handoff; independent full-scope review/completion; separately authorized supported-version live native restore and pane/paint acceptance. Offline submission and cancellation evidence is not live certification. Herdr0.9.2+ remains a target only. The separate security132 finding is unchanged.
