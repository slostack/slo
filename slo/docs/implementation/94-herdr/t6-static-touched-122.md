# T6 feature-touched test static maintenance — lane 122

**READY — all 14 scoped diagnostics closed.** Global lint is still FAILED and
UNWAIVED: **281 errors / 58 files**. This is not T6 completion, independent review,
full-suite acceptance, live certification or release approval.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied
dispatch 122, retries 0. User-authorized unlimited turns AND dispatches supersede
old limits. No agents were spawned.

## Scope and routing

The lane-121 report and linked inventory confirmed exactly two owners:
`tests/cli/test_headless.py` (9) and
`tests/tui/workflows/test_workflow_app_service.py` (5). Only these two existing
files were edited. All other writes are this report and `t6-122-*` evidence in
this directory. Existing partial changes were preserved; before-images and
lane-only diffs are retained. No production, shared status, specifications, KB,
other worktree, package, global configuration or live-system edits; no commit,
push, PR, reset, clean or stash.

Applied supplied AGENTS/CLAUDE and actual docs/RESEARCH plus root RESEARCH,
frozen routing.md/scope-plan.md, engineering routing/ownership/testing,
coding-rules/code-test-loop, shared and Python declarative rules, Python root,
named-argument/type/docstring rules, product Typer, Textual, Faux testing,
environment guidance and workflow accounting. Selected checkout skill paths are
those recorded in routing.md; no Python personal override is present in the
supplied manifest. KB Welcome, slo README/gotchas and OS ROLE were consulted
read-only. This is isolated orchestration/CLI-surface and real-temp-store test
maintenance, not database, provider, CLI-command scaffolding or UI redesign.
No new architecture or spec was needed.

## Corrections and preserved contracts

- Subscriber collection now uses the actual `AgentEventSubscriber` contract in a
  typed local; the fake subscribe function and async iterator have explicit
  signatures. Dispatch-before-yield behavior is unchanged.
- Optional Typer command names are narrowed before creating `set[str]`; the
  required `run` assertion remains. Recorded kwargs retain `Mapping[str, object]`
  with an explicit call-record non-None assertion, rather than claiming dict.
- Drain stubs use scoped patches and spec-bound AsyncMocks returning actual bools;
  await/no-await/status assertions remain. Pool lookup replacement is scoped by
  the existing pytest monkeypatch fixture; no live pool/process is constructed.
- Store failure injection uses scoped spec-bound AsyncMocks. Fleet equality uses
  named constructor fields with exactly the original payload values.
- No assertions were removed or weakened, no new Any/ignore/cast escape hatch,
  checker exclusions or config changes. Existing unrelated annotations/ignores
  were not swept. Reviewed lane-only diffs:
  [headless](t6-122-headless.diff), [workflow](t6-122-workflow.diff).

## Incremental RED → focused/surrounding GREEN → static

Cwd: `/root/Code/slo-94-herdr-integration/slo`.
`PYENV_VERSION=slo-harness pyenv which python` resolved
`/root/.pyenv/versions/slo-harness/bin/python`; Python **3.11.7**.
`make test-env` reported **fallback**. The executable receipt
[t6-122-tests.sh](t6-122-tests.sh) records the reviewed Makefile fallback and
`poetry run pytest -m 'not e2e'`; it refuses a changed env variant. No dev env
was sourced. Root isolated-state, terminal and independently guarded Herdr
fixtures remain active. No real provider/window/Herdr action was performed.

Each correction was below approximately 50 lines and preceded by fresh
`PYENV_VERSION=slo-harness make lint`. Full logs and `.exit` files are retained.
The following static run is also the preceding increment's post-change check.

| Increment | Fresh RED | Correction | Focused + surrounding GREEN | Post-static |
|---|---|---|---|---|
| 1 | t6-122-red1.log: 295 errors, 14 target | subscriber/types/nullable names/Mapping | t6-122-green1.log: 78 passed, 4 warnings | red2: 292 errors, 11 target |
| 2 | t6-122-red2.log | three drain method assignments | t6-122-green2.log: 78 passed, 4 warnings | red3: 291 errors, 8 target; 2 concurrent unrelated additions |
| 3 | t6-122-red3.log | three pool lookup assignments | t6-122-green3.log: 78 passed, 4 warnings | red4: 286 errors, 5 target |
| 4 | t6-122-red4.log | store patches + explicit fleet fields | t6-122-green4.log: 81 passed, 2 warnings | final: 281 errors, 0 target |

Increments 1–3 ran `tests/cli/test_headless.py`,
`tests/cli/test_headless_request.py`, `tests/cli/test_headless_parity.py` together.
Increment 4 ran `tests/tui/workflows` and
`tests/tui/test_workflow_receive_path.py`. All pytest exits were 0; all global
lint exits were 2 (make propagating mypy failure), never called global GREEN.

Concurrent work appeared as two diagnostics in the out-of-scope
`tests/integration/test_herdr_full_flow.py` during red3. This lane did not edit
that file. Those diagnostics were absent in red4/final. Source-file counts also
changed (lane-121 793; fresh initial 796; final 797). These observations are
reported rather than attributed to this repair or hidden by filtering.

## Final exact multiset and gates

Fresh command: `PYENV_VERSION=slo-harness make lint`.
[t6-122-lint.log](t6-122-lint.log), [exit](t6-122-lint.exit): **2**;
`Found 281 errors in 58 files (checked 797 source files)`.

[t6-122-multiset.txt](t6-122-multiset.txt) compares both lane-121 and fresh initial
RED against final using Counters, removing only line/column coordinates while
preserving path, full message, code and duplicate counts. Both comparisons:
**14 removed, 0 added**, all removals in the two authorized files. The other
**281 diagnostics / 58 owners remain unchanged and UNWAIVED**.

Final combined surrounding command used the receipt runner with:

```text
tests/cli/test_headless.py tests/cli/test_headless_request.py
tests/cli/test_headless_parity.py tests/cli/test_headless_exclusions.py
tests/cli/test_headless_herdr.py tests/cli/test_headless_retained.py
tests/tui/workflows tests/tui/test_workflow_receive_path.py
```

[t6-122-surrounding.log](t6-122-surrounding.log): **188 passed, 8 warnings**,
exit 0, 10.17s; no failures/skips/deselections reported.

`PYENV_VERSION=slo-harness poetry run black --check` on exactly both edited
Python files: **2 unchanged**, exit 0 (`t6-122-black.log/.exit`).
`git diff --check`: silent, exit 0 (`t6-122-diff-check.log/.exit`).
`dpkg -V coreutils`: silent, exit 0 (`t6-122-coreutils.log/.exit`).

Full `make test`, broader integration, independent review and feature completion
remain for later integration as requested. No historical full-suite receipt is
relabeled as fresh evidence. READY applies only to this 14-error maintenance lane.
