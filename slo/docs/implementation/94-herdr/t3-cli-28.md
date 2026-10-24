# T3 CLI 28 — CLI behavior implemented; integrated acceptance INCOMPLETE

Exclusive changed code: `src/cli/app.py`, `src/cli/typer_dispatch.py`,
`tests/cli/test_herdr_restore.py`. Other lane changes preserved. No agents,
commits, push, PR, reset/clean/stash, live Herdr/provider/window, global state,
KB, specification or other-worktree changes. Only this receipt and own gate
receipts written. Counters unchanged: turn 1 started 1/completed 0/historical
partial 1; dispatch 28, retries 0; user budgets unlimited. No independent review.

## Implemented family

`--herdr-restore` is an optional root integration flag. Literal canonical UUID
and explicit workdir/workspace/plugin conflicts refuse before lookup/build.
Subcommand combination also refuses rather than silently ignoring restore.
Existing version/help and ordinary slug/name resume behavior remain unchanged.

Dispatch reads existing metadata by exact ID first (therefore a UUID-looking
name cannot redirect a missing history ID), verifies embedded identity, and
requires the existing resolver to agree. The public store loads the exact opaque
revision. The CLI never derives a restore-record path. Missing/corrupt history,
record/ref/identity failures and pool validation errors become the fixed unavailable
Typer error with suppressed chaining. No implicit fallback or preference read.

Fresh ModelPoolEntryDAO instances preserve all five scalar fields and order;
a fresh ModelPoolDAO list runs current provider validators. SessionConfigDAO
uses the saved model/reasoning/workdir/workspace/ordered plugins, default history
root with history enabled, and ordinary prompt/tool/hook defaults. Saved missing
workspace refuses without printing its path. Plugin paths still enter normal
session loading/trust, not a parallel importer. Current model preparation remains
normal `build(..., allow_pending_preparation=True)` behavior.

The reporter argv builder's exact five-token vector reaches actual CliRunner /
dispatch / real lazy session construction with Faux factory safeguards installed
before entry, zero factory calls and unchanged current history bytes. TUI.run is
mocked: this is not mounted restoration or two-process T6 proof.

Removed the root callback's untyped kwargs/type-ignore. Corrected parse_args's
existing narrowed context annotation to Typer's actual vendored base Context,
without parser behavior changes. No new Command, DAO, session or store owner.

## Verification / cadence

CWD `/root/Code/slo-94-herdr-integration/slo`; verified pyenv
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7;
`make test-env`: fallback. P = `bash docs/implementation/94-herdr/t1-dao-check.sh`.
P includes 62 DAO/projection cases, safe fallback exports and disabled Herdr.
Existing pre-import stripping/fake capability/terminal guards remain active.
All prefixes below have `.log` and `.exit` under this directory.

| Prefix | Command / scope | Result |
|---|---|---|
| t3-cli-28-01-red | P tests/cli/test_herdr_restore.py | 10 failed, 62 passed; missing option/admission |
| t3-cli-28-01-green | P restore CLI + test_app.py + test_typer_dispatch.py | 118 passed |
| t3-cli-28-02-red | P restore CLI | 5 failed, 72 passed; exact load/history refusal |
| t3-cli-28-02-green | P restore CLI/app/dispatch | 1 failed, 122 passed; store exception needed explicit catch |
| t3-cli-28-02-green2 | same | 123 passed |
| t3-cli-28-03-red | P restore CLI | 2 failed, 77 passed; missing pool reconstruction |
| t3-cli-28-03-green | P restore CLI/app/dispatch/headless_request | 151 passed |
| t3-cli-28-04-evidence | same | 163 passed; added negative matrix already correct |
| t3-cli-28-05-red | P restore CLI | 2 failed, 91 passed; missing workspace/subcommand gates |
| t3-cli-28-05-green | P restore CLI/app/dispatch/headless_request | 165 passed |
| t3-cli-28-task | P restore CLI/app/dispatch/headless_request/headless + entire Herdr package | 1053 passed, 6 warnings |
| t3-cli-28-06-red | P restore CLI | 1 failed, 94 passed; resolver agreement |
| t3-cli-28-06-green | P restore CLI/app/dispatch/headless_request | 167 passed |
| t3-cli-28-final-cli | P restore CLI/app/dispatch/headless_request/headless | 208 passed, 4 warnings |
| t3-cli-28-full | make test | 1 failed, 7285 passed, 19 deselected; test class identity after prior module reload |
| t3-cli-28-full-final | make test | **7286 passed, 19 deselected, 406 warnings; exit 0** |
| t3-cli-28-smoke | make smoke | 288 passed, 2 warnings; exit 0 |
| t3-cli-28-lint | make lint | **304 errors in 67 files; exit 2** |
| t3-cli-28-black-final | poetry run black --check src/cli/app.py src/cli/typer_dispatch.py tests/cli/test_herdr_restore.py | exit 0 |
| t3-cli-28-diff | git diff --check | exit 0 |
| t3-cli-28-coreutils-final | dpkg -V coreutils | silent, exit 0 |

Production increments stayed below approximately 50 lines before focused and
surrounding verification. The failed full gate was not waived: earlier module
reload tests leave dispatch holding the original session class. The assertion
now checks the actual dispatch-owned class binding, retaining real construction,
identity/config/history assertions. Fresh full gate is green after that correction.

## Self-review and requirement mapping

Python/Typer; orchestration plus real temp filesystem adapter tests. Loaded frozen
routing/scope plan, previous T3/store receipts, full C chapter in three ranges,
T3 attachments 1906–2108, actual DAO/store/session config/pool validators,
root RESEARCH, supplied AGENTS/CLAUDE/docs RESEARCH and KB entry/index/gotchas.
Shared engineering/coding, Python root/DAO/service/declarative, product Typer,
workflow and review/completion guidance consulted. Some oversized combined
companion reads truncated; not claiming complete fresh ingestion of every frozen
routing companion. No shared documentation updated under exclusive write scope.

| Requirement | Evidence / assessment |
|---|---|
| literal UUID before lookup; conflicts before construction | seven UUID forms, three path conflicts; no resolver/build/TUI |
| exact revision; no current preferences | single/pool tests forbid preference/config assembly; old reference remains old |
| complete independent mutable pool | all five fields/order plus mutation and real-store reload; wrong provider refuses |
| invalid private input / history | JSON/schema/extra/ref/session/slug, malformed refs, missing/corrupt/wrong-ID metadata |
| existing path/history/prompt policy | workspace/plugins exact, missing workspace refusal, standard config assertions |
| ordinary CLI compatibility | real slug resume plus existing app/dispatch/headless suites and complete gate |
| producer-consumer argv | production reporter builder → real parser/dispatch/session; no model construction or replay |
| static correctness | no errors in owned CLI/test files; global gate remains failed |

Flow: `_default → tui → argument admission → exact metadata/resolver → public
HerdrRestoreStore.load → new validated pool/SessionConfigDAO → standard session
build → SloTUI.run`. Private storage mechanics stay in store; no new mutable
capture, serializer, history writer or runtime owner. No identified functional
CLI gap from this self-review, but this is not independent workflow acceptance.

## Exact unwaived blockers

Baseline was 301 errors / 64 files. Current complete lint is 304 / 67. The CLI
Context correction removes two baseline override errors; five Herdr errors remain:

- `src/agents/slo_agent/herdr/visualizer.py:135`: str status vs outcome Literal.
- `src/agents/slo_agent/herdr/reporter.py:976`: NullHerdrReporter.build_visualizer
  returns None vs protocol HerdrVisualizerLauncher.
- `tests/agents/slo_agent/herdr/test_restore_security.py:80`: ** expansion of object.
- `tests/agents/slo_agent/herdr/test_visualizer.py:26`: str operation vs Literal.
- `tests/agents/slo_agent/herdr/test_visualizer.py:71`: str status vs Literal.

These are outside this exclusive lane and were not ignored or changed. STORE 28
still explicitly says INCOMPLETE with security/concurrency/crash/composition
obligations outstanding. T3 overall cannot advance to T5 without STORE READY.
Final suite is a current-checkout receipt, not proof that all lanes are frozen or
complete; rerun integrated gates after remaining lanes finish. Independent
review/completion and T6 mounted/two-process/live acceptance remain outstanding.

**Verdict: INCOMPLETE for gated delivery; CLI behavior family implemented and
full non-E2E green, but static gate and STORE readiness remain unwaived.**
