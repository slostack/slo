# Feature 86 — Step 1 R2/R3/R4 remediation

Date: 2026-10-03. Requested model/settings: **gpt-6-astra medium**; backend identity is not independently attestable through these tools.

**REMEDIATION READY. Step 2 needs independent rereview. No Step 3 assessment or Feature 86 completion claim.**

## Corrections and causal evidence

- **R2 — F86-03/22/35/37:** the session's F1 ContextVar lifetime was correct but ended in the stream task. HeadlessRunner now retains the private admitted capture observed by its actual event subscriber, sanitizes the serialized public event before caching/emission, and binds that capture around delayed terminal notifier persistence. `invoke` releases the reference in `finally`, including cleanup errors/cancellation. The resolver exposes only a typed private-operation capture accessor; no source re-resolution for admission, public DTO credential field, persisted key, global archive, raw FD filter, or private-continuation modification. Preparation events with no admitted operation retain their prior fixed-safe path.
- Real session admission/lazy construction/history and runner child-task/terminal notifier/inbox regressions: **4 RED**, with A retained in completed/failed inbox under B, or terminal message absent on resolver failure. Initial surrounding run: **2 failed, 80 passed** due to an unnecessary extra resolver call on already-safe preparation events; restricting new event sanitation to admitted captures restored the existing call contract without changing assertions. Final lifetime partition: **90 passed**. Cleanup-success/error/actual task-cancel cases assert populated redacted inbox and reset; concurrent session scopes/runner handoffs assert distinct admitted captures. Existing next-admission B and private continuation tests remain green.
- **R3 — F86-13/23/24:** exact MockTransport sequence unpaged `next`, 500 rows at offsets 0/500, empty at 1000 reproduced **DID NOT RAISE**. Client now rejects a full page adding no unique records, including reordered repetition, while preserving equal boundary-row deduplication and distinct-page/exact-empty termination. No page cap/retry/sleep/skip added. RED **1 failed, 1 passed**; client **14 passed**; client + catalog + actual refresh retention **302 passed**. Repeated/HTTP/partial refresh leaves prior snapshot and byte-identical provider cache (including successful timestamp) unchanged.
- **R4 — F86-28/41:** precise public export/type regression RED **1 failed**. Rename the presentation-only type to `ModelPickerRowDAO` in the existing live view and test consumers. Canonical catalog DAO unchanged; no old-name alias. Picker/search/menu/router surrounding **127 passed**.

## Changed source/test paths in this remediation

- `src/auth/credential_resolver.py`
- `src/cli/headless.py`
- `src/integrations/openrouter/client.py`
- `src/tui/model_catalog.py`
- `tests/cli/test_openrouter_terminal_lifetime.py` (new)
- `tests/integrations/openrouter/test_pagination_completeness.py` (new)
- `tests/integration/test_openrouter_repeated_page_retention.py` (new)
- `tests/tui/test_picker_row_identity.py` (new)
- `tests/tui/test_model_catalog.py`

Other dirty/untracked work was preserved. Documentation updates: this report, implementation log, current status, remaining requirements, root RESEARCH, docs/RESEARCH and AGENTS. Immutable specifications and independent review are unchanged.

## Fresh gates and exact command convention

All Python execution used existing `/root/.pyenv/versions/slo-harness/bin/python -B` (3.11.7), no installation/environment repair. Each run allocated `ROOT=$(mktemp -d "$PWD/.f86-<name>-XXXXXX")`; HOME/TMPDIR/SLO_HOME/auth and pytest basetemp were checkout-contained. Full commands used timeout **1200 seconds**, logs redirected before bounded tail output.

Final command:

```bash
ROOT=$(mktemp -d "$PWD/.f86-remediation-full-final-XXXXXX")
mkdir "$ROOT/home" "$ROOT/tmp"
env -i PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
  VIRTUAL_ENV=/root/.pyenv/versions/slo-harness HOME="$ROOT/home" TMPDIR="$ROOT/tmp" \
  SLO_HOME="$ROOT/home" SLO_AUTH_FILE="$ROOT/home/auth.json" SLO_ENV=test \
  SLO_AUTO_VISUALIZE=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q -m 'not e2e' \
  -p no:cacheprovider --basetemp="$ROOT/tests" tests --tb=short \
  > docs/implementation/86-openrouter/logs/remediation-full-final-non-e2e.log 2>&1
```

**5045 passed, 15 deselected, 196 warnings, 353.28s, exit 0.** This is the COMPLETE current non-E2E suite, not a historical or selected gate. Warnings remain in the complete log, including deprecations and unawaited AsyncMock warnings.

Earlier full command used `PATH=/usr/bin:/bin` and `SLO_PLUGINS_DISABLED=1`: **19 failed, 5026 passed, 15 deselected, 196 warnings**. Cause: explicit plugin kill switch yielded empty registrations (18 failures); restricted PATH hid existing Poetry in release-smoke collection (1 failure). Neither was an ordering defect. Corrected invocation only; no tests/assertions weakened. Exact failed-family partition passed **40 tests** before final full run. Historical failed log retained, no lucky retry or sleep.

Focused commands use the same isolated pattern and `pytest -q -p no:cacheprovider --basetemp="$ROOT/tests" <selection> --tb=short`; initial scoped runs used `/usr/bin:/bin` and plugin kill switch (not needed by those selected tests).

| Log under `docs/implementation/86-openrouter/logs/` | Selection | Result |
|---|---|---|
| `r2-red.log` | new terminal lifetime module (initial four cases) | 4 failed |
| `r2-surrounding.log` | terminal, headless, preparation, resolver binding, notifier, key admission, provider channels | 2 failed, 80 passed |
| `r2-surrounding-final.log` | same | 82 passed |
| `r2-lifetime.log` | same, expanded cleanup cases | 90 passed |
| `r3-red.log` | pagination completeness | 1 failed, 1 passed |
| `r3-client.log` | tests/integrations/openrouter | 14 passed |
| `r3-surrounding.log` | previous + tests/agents/model_catalog + repeated-page retention integration | 302 passed |
| `r4-red.log` | picker row identity | 1 failed |
| `r4-surrounding.log` | row identity, model_catalog, openrouter_picker, picker_g8/status_publication/viewport_acceptance, slash_suggestion_engine/menu/suggestions_app/router | 127 passed |
| `remediation-focused.log` | terminal lifetime including concurrent handoff, integrations/openrouter, repeated-page retention, row identity | 31 passed |
| `remediation-full-non-e2e.log` | initial full invocation | 19 failed, 5026 passed |
| `remediation-env-proof.log` | plugin loader/session wiring, plugin command runtime/slash commands, release automation | 40 passed |
| `remediation-full-final-non-e2e.log` | all tests, not e2e | 5045 passed |

`git diff --check` passed. Post-suite `dpkg -V coreutils` produced no output. No system/PATH files modified, no Git staging/commit/push/merge/reset/clean/rebase/worktree operation, external network/real credentials/live provider/paid inference or spec mutation.

**Static formatting/mypy are expressly waived as gates for F86, record but do not block; functional/security tests not waived.** Static tools were not rerun; this is not a formatting/type-clean claim.

## Evidence limits and safety disclosure

The R2 regression injects a synthetic terminal payload through actual runner/session/history/notifier owners; it does not claim that a live SDK disclosed a key. Concurrent handoff is a bounded two-session seam test, not two complete concurrent CLI processes. Existing full-suite SDK private-continuation tests pass unchanged. The retained full gate includes the earlier capture qualification; it does not convert shipped-body/native-I/O instrumentation into native interpreter-startup equivalence.

One initial oversized combined context read caused a tool-managed spill at `/tmp/slo-bash-26qc4u4b.txt`, outside the requested write boundary. It was not a deliberate code/test write and was left untouched; disclosed rather than hidden or deleted. All deliberate new artifacts/tests were repo-contained. Shared KB was consulted but not modified because this request prohibits outside-repo writes.

Independent Step 2 must rereview these corrections; Step 3 has not been performed. Existing independently recorded nonblocking convention debt is not silently certified away.
