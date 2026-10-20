# T6 viewer diagnostic fix 134

## Verdict

**Diagnostic correction READY; complete privacy-family acceptance INCOMPLETE.**

The actual 133 disclosure is corrected and the final explicit safe selection passes **281 tests, 139 warnings, exit 0 in 155.69s**. This does not certify the entire feature, independent review, native restore or live Herdr. Remaining privacy evidence is named below rather than deferred as an unbounded read tail.

Only production edit in this assignment: `src/tui/visualizer_launcher.py::_spawn_detached` replaces `error=str(exc), argv=argv` with the fixed `category="platform_spawn_failed"`, removes the exception binding, and explains why. No stringify, class-name extraction, credential lookup, global redactor, traceback or private argv/path is emitted. Existing bool and async opened/failed outcomes, cancellation/thread ownership, Herdr reuse, provider and history behavior are unchanged. No discovery/thread-wrapper production edit: the existing joined boundary already retrieves those errors and returns failed without payload logging, matching D's platform example.

Test edits are confined to `tests/integration/test_herdr_full_flow.py`. No harness, shared status, KB, spec, other-worktree, global or live changes. No agents, commit, push, PR, reset, clean or stash. Existing partial work preserved. Accounting: supplied unfinished turn 1, started 1/completed 0/historical partial 1, dispatch 134, retries 0; unlimited turns/dispatches; no dispatch here. Local test iterations do not complete a workflow turn.

## Reproduction and correction

Read retained `t6-privacy-final-133.md` and exact `t6-privacy-133/viewer-diagnostics.log`. Fresh `red.log` reproduces `test_high_level_viewer_public_outcome_privacy[platform_failed]`: **1 failed/62 passed**, exit 1. Failure is the synthetic private string in LogRecord `error`, not merely formatted message text. The same record also carried launch argv including private runtime paths.

After the three-line diagnostic change, `green.log`: **141 passed**, exit 0, including launcher and publication/viewer surrounds. New boundary assertions require exactly one spawn warning with the fixed category, no error/argv/exception/class fields, empty formatting args, and no exception/traceback payload. Discovery and thread failures retain failed with zero spawn and no launch warning. Their payload never reaches the result or rendered recovery notice.

## Finite requirement/evidence map

| Contract | Actual evidence and boundary |
|---|---|
| B 7.6 arbitrary model/session/effort omission; canonical reasoning only | Existing mounted 32-case compact/detail × tool success/error × child success/error × four sentinel-category matrix; asynchronous lifetime test validates private arbitrary model capture, invalid reasoning/effort omission, actual save and wire before/after rotation. Explicit absent token keys added. |
| Arbitrary provider labels | `SessionUsageSnapshotDAO` is extra-forbid and has no provider/provider_label input slot. Added both-field rejection assertions for all four labelled categories before/after rotation; projection emits no provider token. No invalid native-provider enum or real provider run is claimed. Initial assumption that extras were ignored failed four tests (`privacy.log`); corrected test asserts the actual reject contract without modifying production validation. |
| Zero reporting credential lookup | Existing separate-task blocker sensitivity and complete admitted reporter activation/save/publication/rotation/drain blocker test run. Ordinary Faux prompt credential admission occurs before blockers. Real rename persistence remains ordinary Slo responsibility and is tested separately in the mounted matrix. |
| B 8 report child stdout/stderr/events/environment | Mounted matrix scans every captured snapshot, wire, public transport results, close outcome and non-restore state; reporting diagnostics now scan full LogRecord dictionaries rather than only getMessage. |
| D 8 viewer submitted/reused/failed | Attached/detached mounted journeys use real registered fake CLI and real adapter ledger; success/reject/oversized/private-output cases. Both public result schema and public transport outcomes scanned. Private `json_bytes` stays parser input, not a public field claim. |
| Viewer public views | Mounted journey now scans all observed events, full integration/launcher diagnostic records, wire, actual viewer notice lines, every retained viewer result through the shared renderer, final snapshots and non-restore sequence state for original and successor owners. Exact result field set is status/pane_id. |
| Platform opened/failed, auto-off skipped, unavailable failed | Actual high-level destination tests inject only spawn/discovery/thread failure seams, scan returned DAO/argv/diagnostics and render each result through the production shared renderer. No real window. |
| D/C original execution and history | Existing enabled/disabled secret tool-error parity remains green. No provider/history/executor code changed. Finding `security-finding-132.md` remains separate and unwaived. |
| All-public-view composed acceptance | **Remaining:** platform opened/failed and auto-off/unavailable cases are high-level launcher plus renderer tests, not both mounted attached/detached entry routes. Mounted viewer test captures final snapshots, not every transient viewer-period snapshot. These prevent claiming complete all-view privacy-family READY. |
| Required read closure | Requested skill bodies, routing/scope plan, supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, KB entry/index/gotchas, canonical privacy/test/platform sections and accepted turn-4 review consulted. **Remaining:** complete affected session/app publication and viewer scheduling source closure has not been independently ingested in this assignment. Specific owners: session `_publish_herdr_snapshot`/`open_workflow_visualizer`; app `_schedule_visualizer_launch` and attached/detached worker completion; service typed effect construction. |

The next finite acceptance work is therefore: instrument every public snapshot in both mounted viewer paths; drive platform/auto-off/unavailable outcomes through those same mounted callers; finish the named source-owner reads and reconcile this table. No need to change providers, global redaction, restore-process harness or reopen ordinary-tool finding 132 to do that.

## Reads and design decision

Canonical root read-only: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`. Consulted B 7.6 and privacy prerequisite/section 8; C sections 8–9; D platform offload example and sections 8–9; tasks T6 B26/C31/D09/O01–O03; accepted independent turn-4 review. Fixed category is deliberately narrower than raw exception class names. D explicitly retains silent platform thread error retrieval, so additional diagnostic logging was not invented.

Loaded committed engineering routing/testing/ownership, coding-rules, code-test-loop, complete shared declarative (including previously unread tail), Python root/declarative/named-arguments/docstrings, full Faux graph testing, full Textual skill and workflow SKILL accounting. Routing excludes databases, new CLI verbs, agents and global infrastructure. Read Makefile test fallback, Python version declaration, fixture guards and registered file capability. One oversized combined orientation read truncated; separately reread routing, root research and scope-plan beginning rather than claiming that output alone established closure.

## Exact verification

CWD `/root/Code/slo-94-herdr-integration/slo`; verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No dev environment sourced. Every pytest invocation uses inspected existing wrapper:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <selection>
```

Wrapper adds exact DAO/projection files (62 tests), exports safe fallback, disables auto windows/Herdr; root guards strip inherited HERDR and require independent registered temp-owned regular fake files. These counts overlap; do not sum them.

Receipts directory: `docs/implementation/94-herdr/t6-viewer-diagnostic-134/`.

| Stem | Selection | Result |
|---|---|---|
| red | high-level platform_failed node | 1 failed, 62 passed |
| green | high-level privacy node; launcher; session_publication; herdr visualizer | 141 passed |
| privacy | high-level; reporter lifetime; mounted viewer journey | 4 failed, 76 passed (test assumption about extra-forbid, retained) |
| final | full owned integration file; launcher; session_publication; herdr visualizer | 267 passed |
| views | high-level; mounted viewer journey; workflow renderer | 90 passed |
| final2 | full owned integration file; launcher; session_publication; herdr visualizer; workflow renderer | **281 passed, 139 warnings**, exit 0 |

Final expanded selection:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh \
 tests/integration/test_herdr_full_flow.py \
 tests/tui/test_visualizer_launcher.py \
 tests/agents/slo_agent/herdr/test_session_publication.py \
 tests/agents/slo_agent/herdr/test_visualizer.py \
 tests/tui/workflows/test_workflow_renderer.py
```

Final static and safety commands:

```sh
PYENV_VERSION=slo-harness poetry run black --check src/tui/visualizer_launcher.py tests/integration/test_herdr_full_flow.py
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent src/tui/visualizer_launcher.py tests/integration/test_herdr_full_flow.py
git diff --check
dpkg -V coreutils
```

All exit 0; Black two unchanged; scoped mypy no issues in two files; diff and coreutils silent. No ignores added. Global **281 errors/58 files remains unwaived**, not rerun or represented as green. Full-suite/two-process HOLD honored: no make test, integration-directory collection, restore-process execution or unsafe unrelated test collection. Test timeout budget 1800 seconds. No system binaries/symlinks or live providers/Herdr/windows touched. HEAD diff includes pre-existing feature work; this report distinguishes the tiny production delta from that existing work.
